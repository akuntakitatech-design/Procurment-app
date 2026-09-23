"""Multi-UOM compatibility layer for transaction routes.

Inventory and allocation quantities remain canonical in the item's base UOM.
Users may enter another UOM attached to the item. The wrapper converts the input
quantity to base quantity before invoking the existing transaction endpoint, then
stores display metadata on the line for UI/print convenience.
"""
from copy import deepcopy
from fastapi import Depends, HTTPException, Query

TX_ROUTES = [
    ("/api/mro", "POST", "mro_lines", "mro_id"),
    ("/api/ro", "POST", "ro_lines", "ro_id"),
    ("/api/po", "POST", "po_lines", "po_id"),
    ("/api/do", "POST", "do_lines", "do_id"),
    ("/api/mi", "POST", "mi_lines", "mi_id"),
    ("/api/transfers", "POST", "transfer_lines", "transfer_id"),
    ("/api/loans", "POST", "loan_lines", "loan_id"),
]

async def _uom_map(server):
    return {u["id"]: u for u in await server.db.uoms.find({}, {"_id": 0}).to_list(2000)}

def _uom_label(u):
    return (u or {}).get("symbol") or (u or {}).get("name") or (u or {}).get("code") or ""

async def _resolve_line_uom(server, line: dict):
    item = await server.db.items.find_one({"id": line.get("item_id")}, {"_id": 0}) or {}
    qty = float(line.get("qty") or 0)
    uoms = await _uom_map(server)
    base_uom_id = item.get("base_uom_id")
    base_uom = uoms.get(base_uom_id, {}) if base_uom_id else {}
    base_label = _uom_label(base_uom) or item.get("unit") or line.get("unit") or ""
    selected_id = line.get("uom_id") or base_uom_id
    factor = 1.0
    if selected_id and base_uom_id:
        if selected_id != base_uom_id:
            cfg = next((x for x in (item.get("uoms") or []) if x.get("uom_id") == selected_id), None)
            if not cfg:
                raise HTTPException(status_code=400, detail=f"Satuan tidak terdaftar pada barang {item.get('code') or ''}")
            factor = float(cfg.get("factor") or 0)
            if factor <= 0:
                raise HTTPException(status_code=400, detail="Konversi satuan tidak valid")
    selected_uom = uoms.get(selected_id, {}) if selected_id else {}
    display_unit = _uom_label(selected_uom) or line.get("unit") or base_label
    return {
        "display_qty": qty,
        "uom_id": selected_id,
        "conversion_factor": factor,
        "display_unit": display_unit,
        "base_qty": qty * factor,
        "base_uom_id": base_uom_id,
        "base_unit": base_label,
    }

async def _normalize_body(server, body: dict):
    normalized = deepcopy(body)
    metas = []
    for line in normalized.get("lines", []):
        meta = await _resolve_line_uom(server, line)
        line["qty"] = meta["base_qty"]
        line["unit"] = meta["base_unit"] or line.get("unit")
        if line.get("price") is not None:
            display_price = float(line.get("price") or 0)
            meta["display_price"] = display_price
            line["price"] = display_price / meta["conversion_factor"]
        for src in line.get("sources", []) or []:
            if src.get("base_qty") is not None:
                src["qty"] = float(src.get("base_qty") or 0)
            else:
                src["qty"] = float(src.get("qty") or 0) * meta["conversion_factor"]
        metas.append(meta)
    return normalized, metas

async def _decorate_stored_lines(server, collection_name, fk, doc_id, metas, result=None):
    if not doc_id or not metas:
        return result
    col = getattr(server.db, collection_name)
    rows = await col.find({fk: doc_id}, {"_id": 0}).to_list(1000)
    for row, meta in zip(rows, metas):
        await col.update_one({"id": row["id"]}, {"$set": meta})
    if isinstance(result, dict) and isinstance(result.get("lines"), list):
        for line, meta in zip(result["lines"], metas):
            line.update(meta)
    return result

def _find_route(app, path, method):
    for r in list(app.router.routes):
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set()):
            return r
    return None

def _remove_route(app, route):
    if route in app.router.routes:
        app.router.routes.remove(route)

async def _line_display(server, collection_name, line_id):
    row = await getattr(server.db, collection_name).find_one({"id": line_id}, {"_id": 0}) or {}
    factor = float(row.get("conversion_factor") or 1)
    return row, factor if factor > 0 else 1

async def _convert_pull_rows(server, rows, collection_name, numeric_keys):
    out = []
    for raw in rows:
        row = dict(raw)
        src, factor = await _line_display(server, collection_name, row.get("line_id"))
        row["uom_id"] = src.get("uom_id")
        row["conversion_factor"] = factor
        row["unit"] = src.get("display_unit") or row.get("unit")
        for key in numeric_keys:
            if row.get(key) is not None:
                row[f"{key}_base"] = row[key]
                row[key] = float(row[key]) / factor
        out.append(row)
    return out

def install(server):
    app = server.app

    def make_tx_wrapper(original, collection_name, fk):
        async def wrapped(body: dict, user=Depends(server.current_user)):
            normalized, metas = await _normalize_body(server, body)
            result = await original(normalized, user)
            doc_id = result.get("id") if isinstance(result, dict) else None
            return await _decorate_stored_lines(server, collection_name, fk, doc_id, metas, result)
        return wrapped

    for path, method, collection_name, fk in TX_ROUTES:
        route = _find_route(app, path, method)
        if not route:
            continue
        original = route.endpoint
        _remove_route(app, route)
        app.add_api_route(path, make_tx_wrapper(original, collection_name, fk), methods=[method], tags=["uom"])

    route = _find_route(app, "/api/mro/{did}", "PUT")
    if route:
        original = route.endpoint
        _remove_route(app, route)
        async def mro_update(did: str, body: dict, user=Depends(server.current_user)):
            normalized, metas = await _normalize_body(server, body)
            result = await original(did, normalized, user)
            return await _decorate_stored_lines(server, "mro_lines", "mro_id", did, metas, result)
        app.add_api_route("/api/mro/{did}", mro_update, methods=["PUT"], tags=["uom"])

    def make_pull_wrapper(original, collection_name, keys):
        async def wrapped(user=Depends(server.current_user)):
            rows = await original(user)
            return await _convert_pull_rows(server, rows, collection_name, keys)
        return wrapped

    pull_specs = [
        ("/api/pull/mro-for-ro", "mro_lines", ["requested", "processed", "outstanding"]),
        ("/api/pull/mro-for-mi", "mro_lines", ["requested", "issued", "outstanding", "available"]),
        ("/api/pull/ro-for-po", "ro_lines", ["qty_ro", "ordered", "outstanding"]),
    ]
    for path, collection_name, keys in pull_specs:
        route = _find_route(app, path, "GET")
        if not route:
            continue
        original = route.endpoint
        _remove_route(app, route)
        app.add_api_route(path, make_pull_wrapper(original, collection_name, keys), methods=["GET"], tags=["uom"])

    route = _find_route(app, "/api/pull/po-for-do", "GET")
    if route:
        original = route.endpoint
        _remove_route(app, route)
        async def pull_po_for_do(supplier_id: str = Query(None), user=Depends(server.current_user)):
            rows = await original(user=user, supplier_id=supplier_id)
            return await _convert_pull_rows(server, rows, "po_lines", ["qty_po", "received", "outstanding"])
        app.add_api_route("/api/pull/po-for-do", pull_po_for_do, methods=["GET"], tags=["uom"])

    route = _find_route(app, "/api/loans/{did}/returnable", "GET")
    if route:
        original_returnable = route.endpoint
        _remove_route(app, route)
        async def loan_returnable(did: str, user=Depends(server.current_user)):
            rows = await original_returnable(did, user)
            out = []
            for raw in rows:
                row = dict(raw)
                src, factor = await _line_display(server, "loan_lines", row.get("loan_line_id"))
                row["uom_id"] = src.get("uom_id")
                row["conversion_factor"] = factor
                row["unit"] = src.get("display_unit") or row.get("unit")
                for key in ("qty", "returned", "outstanding"):
                    if row.get(key) is not None:
                        row[f"{key}_base"] = row[key]
                        row[key] = float(row[key]) / factor
                out.append(row)
            return out
        app.add_api_route("/api/loans/{did}/returnable", loan_returnable, methods=["GET"], tags=["uom"])

    route = _find_route(app, "/api/loans/{did}/return", "POST")
    if route:
        original_return = route.endpoint
        _remove_route(app, route)
        async def loan_return(did: str, body: dict, user=Depends(server.current_user)):
            normalized = deepcopy(body)
            for line in normalized.get("lines", []):
                ll = await server.db.loan_lines.find_one({"id": line.get("loan_line_id")}, {"_id": 0}) or {}
                factor = float(ll.get("conversion_factor") or 1)
                line["qty"] = float(line.get("qty") or 0) * (factor if factor > 0 else 1)
            return await original_return(did, normalized, user)
        app.add_api_route("/api/loans/{did}/return", loan_return, methods=["POST"], tags=["uom"])
