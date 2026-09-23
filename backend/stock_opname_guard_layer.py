"""Safety guards for stock-opname counting and posting."""
from fastapi import Depends, HTTPException


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _doc(server, did):
    doc = await server.db.opname.find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Stock Opname tidak ditemukan")
    return doc


async def _lines(server, did):
    return await server.db.opname_lines.find({"opname_id": did}, {"_id": 0}).to_list(10000)


def _counted_value(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, "Qty hitung Stock Opname tidak valid")
    if value < -1e-9:
        raise HTTPException(400, "Qty hitung Stock Opname tidak boleh negatif")
    return value


async def _require_complete(server, did):
    rows = await _lines(server, did)
    if not rows:
        raise HTTPException(400, "Stock Opname tidak memiliki baris barang")
    missing = [row for row in rows if row.get("counted") is None]
    if missing:
        raise HTTPException(400, f"Masih ada {len(missing)} barang yang belum dihitung")
    for row in rows:
        _counted_value(row.get("counted"))
    return rows


async def _validate_post_balance(server, doc, rows):
    wh = doc.get("warehouse_id")
    for row in rows:
        snapshot = float(row.get("snapshot") or 0)
        counted = _counted_value(row.get("counted"))
        variance = counted - snapshot
        current = float(await server.stock_balance(row.get("item_id"), wh) or 0)
        after = current + variance
        if after < -1e-9:
            item = await server.db.items.find_one({"id": row.get("item_id")}, {"_id": 0}) or {}
            label = item.get("code") or item.get("name") or row.get("item_id")
            raise HTTPException(409, f"Posting opname {label} akan membuat stok negatif ({after:g})")


def install(server):
    app = server.app

    route = _find_route(app, "/api/opname/{did}/count", "PUT")
    if route:
        original_count = route.endpoint
        app.router.routes.remove(route)

        async def safe_count(did: str, body: dict, user=Depends(server.current_user)):
            doc = await _doc(server, did)
            if doc.get("status") == "Posted":
                raise HTTPException(409, "Stock Opname sudah diposting. Gunakan Edit transaksi untuk koreksi dengan reversal.")
            seen = set()
            for raw in (body or {}).get("lines", []):
                line_id = raw.get("line_id")
                if not line_id or line_id in seen:
                    raise HTTPException(400, "Baris Stock Opname tidak valid atau duplikat")
                seen.add(line_id)
                row = await server.db.opname_lines.find_one({"id": line_id, "opname_id": did}, {"_id": 0})
                if not row:
                    raise HTTPException(400, "Baris tidak berasal dari Stock Opname ini")
                _counted_value(raw.get("counted"))
            return await original_count(did, body, user)

        app.add_api_route("/api/opname/{did}/count", safe_count, methods=["PUT"], tags=["opname-safety"])

    route = _find_route(app, "/api/opname/{did}/submit", "POST")
    if route:
        original_submit = route.endpoint
        app.router.routes.remove(route)

        async def safe_submit(did: str, user=Depends(server.current_user)):
            doc = await _doc(server, did)
            if doc.get("status") == "Posted":
                raise HTTPException(409, "Stock Opname sudah diposting")
            await _require_complete(server, did)
            return await original_submit(did, user)

        app.add_api_route("/api/opname/{did}/submit", safe_submit, methods=["POST"], tags=["opname-safety"])

    route = _find_route(app, "/api/opname/{did}/post", "POST")
    if route:
        original_post = route.endpoint
        app.router.routes.remove(route)

        async def safe_post(did: str, user=Depends(server.current_user)):
            doc = await _doc(server, did)
            if doc.get("status") == "Posted":
                raise HTTPException(409, "Stock Opname sudah diposting")
            rows = await _require_complete(server, did)
            await _validate_post_balance(server, doc, rows)
            return await original_post(did, user)

        app.add_api_route("/api/opname/{did}/post", safe_post, methods=["POST"], tags=["opname-safety"])

    route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if route:
        original_transaction_edit = route.endpoint
        app.router.routes.remove(route)

        async def safe_transaction_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module != "opname":
                return await original_transaction_edit(module, did, body, user)
            doc = await _doc(server, did)
            old_rows = await _lines(server, did)
            old_by_id = {row.get("id"): row for row in old_rows}
            raw_lines = (body or {}).get("lines") or []
            if doc.get("status") == "Posted":
                if len(raw_lines) != len(old_rows):
                    raise HTTPException(400, "Koreksi Stock Opname Posted tidak boleh mengubah cakupan barang")
                seen_items = set()
                for raw in raw_lines:
                    old = old_by_id.get(raw.get("id"))
                    if not old:
                        raise HTTPException(400, "Baris koreksi tidak berasal dari Stock Opname ini")
                    if raw.get("item_id") not in (None, old.get("item_id")):
                        raise HTTPException(400, "Barang Stock Opname Posted tidak boleh diganti")
                    if raw.get("snapshot") is not None and abs(float(raw.get("snapshot")) - float(old.get("snapshot") or 0)) > 1e-9:
                        raise HTTPException(400, "Snapshot Stock Opname Posted tidak boleh diubah")
                    if old.get("item_id") in seen_items:
                        raise HTTPException(400, "Barang Stock Opname duplikat")
                    seen_items.add(old.get("item_id"))
                    if raw.get("counted") is None:
                        raise HTTPException(400, "Qty hitung wajib diisi pada koreksi Stock Opname Posted")
                    _counted_value(raw.get("counted"))
            else:
                for raw in raw_lines:
                    if raw.get("counted") is not None:
                        _counted_value(raw.get("counted"))
            return await original_transaction_edit(module, did, body, user)

        app.add_api_route("/api/transactions/{module}/{did}", safe_transaction_edit, methods=["PUT"], tags=["opname-safety"])
