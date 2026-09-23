"""Safety wrapper for transaction edit/delete stock reversals.

A posted inbound transaction (for example DO) may have been consumed by later
stock issues without a direct document allocation. Reversing that receipt must
not drive physical stock negative. This wrapper blocks edit/delete until the
stock is available again, even when no document dependency exists.
"""
from fastapi import Depends, HTTPException


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _stock_blockers(server, did):
    rows = await server.db.stock_ledger.find({
        "doc_id": did,
        "is_reversal": {"$ne": True},
        "reversed": {"$ne": True},
    }, {"_id": 0}).to_list(10000)
    impact = {}
    for row in rows:
        key = (row.get("item_id"), row.get("warehouse_id"))
        # Reversal impact = old qty_out - old qty_in.
        impact[key] = impact.get(key, 0.0) + float(row.get("qty_out") or 0) - float(row.get("qty_in") or 0)
    blockers = []
    for (item_id, warehouse_id), delta in impact.items():
        if delta >= -1e-9:
            continue
        current = float(await server.stock_balance(item_id, warehouse_id) or 0)
        after = current + delta
        if after >= -1e-9:
            continue
        item = await server.db.items.find_one({"id": item_id}, {"_id": 0}) or {}
        wh = await server.db.warehouses.find_one({"id": warehouse_id}, {"_id": 0}) or {}
        blockers.append({
            "type": "STOCK",
            "id": item_id,
            "no": item.get("code") or item.get("name") or item_id,
            "detail": f"Stok {wh.get('name') or warehouse_id} saat ini {current:g}; reversal akan menjadi {after:g}",
        })
    return blockers


def install(server):
    app = server.app

    cap_route = _find_route(app, "/api/transactions/{module}/{did}/capability", "GET")
    if cap_route:
        original_cap = cap_route.endpoint
        app.router.routes.remove(cap_route)

        async def safe_capability(module: str, did: str, user=Depends(server.current_user)):
            result = await original_cap(module, did, user)
            stock = await _stock_blockers(server, did)
            if stock:
                result["blockers"] = (result.get("blockers") or []) + stock
                result["can_edit"] = False
                result["can_delete"] = False
                result["reason"] = "Stok yang berasal dari transaksi ini sudah terpakai. Koreksi/hapus transaksi pemakaian stok terlebih dahulu."
            return result

        app.add_api_route("/api/transactions/{module}/{did}/capability", safe_capability, methods=["GET"], tags=["transaction-mutation"])

    put_route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if put_route:
        original_put = put_route.endpoint
        app.router.routes.remove(put_route)

        def make_safe_edit(original_endpoint):
            async def safe_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
                stock = await _stock_blockers(server, did)
                if stock:
                    raise HTTPException(409, "Stok dari transaksi ini sudah terpakai. Hapus/koreksi transaksi pemakaian stok terlebih dahulu.")
                return await original_endpoint(module, did, body, user)
            return safe_edit

        app.add_api_route(
            "/api/transactions/{module}/{did}",
            make_safe_edit(original_put),
            methods=["PUT"],
            tags=["transaction-mutation"],
        )

    delete_route = _find_route(app, "/api/transactions/{module}/{did}", "DELETE")
    if delete_route:
        original_delete = delete_route.endpoint
        app.router.routes.remove(delete_route)

        def make_safe_delete(original_endpoint):
            async def safe_delete(module: str, did: str, user=Depends(server.current_user)):
                stock = await _stock_blockers(server, did)
                if stock:
                    raise HTTPException(409, "Stok dari transaksi ini sudah terpakai. Hapus/koreksi transaksi pemakaian stok terlebih dahulu.")
                return await original_endpoint(module, did, user)
            return safe_delete

        app.add_api_route(
            "/api/transactions/{module}/{did}",
            make_safe_delete(original_delete),
            methods=["DELETE"],
            tags=["transaction-mutation"],
        )
