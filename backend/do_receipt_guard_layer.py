"""Integrity and access guard for DO / penerimaan barang.

The legacy DO endpoint posts stock immediately. This layer validates the complete
receipt before that write happens, scopes DO visibility to the source PO division,
and keeps edit/delete operations under the same boundary.

Rules:
- every receipt line must point to a real PO line from an active approved PO;
- header supplier, source supplier and source division must be consistent;
- one DO belongs to one division (multiple PO are allowed only within that division
  and supplier);
- limited users may only receive their own divisions and assigned warehouses;
- over-receipt is always rejected before any header/stock write; generic override_qty
  is intentionally not allowed to bypass the commercial quantity committed by the PO;
- editing an existing DO may use a Fully Received PO because the current DO itself
  can be the receipt that completed it;
- detail responses expose PO quantity / previous receipt / outstanding consistently.
"""
from __future__ import annotations

from copy import deepcopy

from fastapi import Depends, HTTPException

import transaction_mutation_layer as Mutation
import uom_layer


VALID_CREATE_PO_STATUS = {"approved", "partially received"}
VALID_EDIT_PO_STATUS = VALID_CREATE_PO_STATUS | {"fully received"}


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _norm(value):
    return str(value or "").strip().lower()


def _is_global(server, user: dict) -> bool:
    return bool(server.is_global(user))


def _allowed_divisions(user: dict) -> set[str]:
    return {str(x) for x in (user.get("divisions") or []) if x}


def _allowed_warehouses(user: dict) -> set[str]:
    return {str(x) for x in (user.get("warehouses") or []) if x}


def _line_source(line: dict):
    src = ((line.get("sources") or [None])[0]) or {}
    po_id = line.get("po_id") or src.get("po_id") or src.get("source_doc_id")
    po_line_id = line.get("po_line_id") or src.get("line_id") or src.get("po_line_id") or src.get("source_line_id")
    return po_id, po_line_id


async def _derive_do_division(server, doc: dict):
    if doc.get("division_id"):
        return doc.get("division_id")
    line = await server.db.do_lines.find_one({"do_id": doc.get("id")}, {"_id": 0})
    if not line:
        return None
    po = await server.db.po.find_one({"id": line.get("po_id")}, {"_id": 0, "division_id": 1})
    return (po or {}).get("division_id")


async def _require_do_view(server, did: str, user: dict):
    doc = await server.db.do.find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "DO tidak ditemukan")
    if _is_global(server, user):
        return doc
    division_id = await _derive_do_division(server, doc)
    if not division_id or str(division_id) not in _allowed_divisions(user):
        raise HTTPException(403, "Penerimaan barang berada di divisi lain")
    return doc


async def _validate_body(server, body: dict, user: dict, current_do_id: str | None = None):
    payload = deepcopy(body or {})
    normalized, _metas = await uom_layer._normalize_body(server, payload)
    lines = [x for x in (normalized.get("lines") or []) if float(x.get("qty") or 0) > 0]
    if not lines:
        raise HTTPException(400, "Penerimaan barang minimal memiliki satu item")

    supplier_ids: set[str] = set()
    division_ids: set[str] = set()
    accumulated: dict[str, float] = {}
    valid_status = VALID_EDIT_PO_STATUS if current_do_id else VALID_CREATE_PO_STATUS

    for line in lines:
        po_id, po_line_id = _line_source(line)
        if not po_id or not po_line_id:
            raise HTTPException(400, "Setiap item penerimaan harus berasal dari PO")

        po = await server.db.po.find_one({"id": po_id}, {"_id": 0})
        if not po:
            raise HTTPException(400, "PO sumber tidak ditemukan")
        if po.get("cancelled") is True or _norm(po.get("status")) in {"cancelled", "canceled", "rejected"}:
            raise HTTPException(409, f"PO {po.get('no') or po_id} sudah tidak aktif")
        if _norm(po.get("status")) not in valid_status:
            raise HTTPException(409, f"PO {po.get('no') or po_id} belum siap untuk penerimaan (status {po.get('status')})")

        po_line = await server.db.po_lines.find_one({"id": po_line_id}, {"_id": 0})
        if not po_line or str(po_line.get("po_id")) != str(po_id):
            raise HTTPException(400, "Item PO tidak sesuai dengan PO sumber")
        if str(po_line.get("item_id")) != str(line.get("item_id")):
            raise HTTPException(400, "Barang penerimaan berbeda dengan barang pada PO")

        supplier_id = po.get("supplier_id")
        division_id = po.get("division_id")
        if not supplier_id:
            raise HTTPException(400, f"PO {po.get('no') or po_id} belum memiliki supplier")
        if not division_id:
            raise HTTPException(400, f"PO {po.get('no') or po_id} belum memiliki divisi")
        supplier_ids.add(str(supplier_id))
        division_ids.add(str(division_id))

        if not _is_global(server, user) and str(division_id) not in _allowed_divisions(user):
            raise HTTPException(403, "Tidak dapat menerima PO dari divisi lain")

        warehouse_id = line.get("warehouse_id") or normalized.get("default_warehouse_id")
        if not warehouse_id:
            raise HTTPException(400, "Gudang penerimaan wajib dipilih")
        wh = await server.db.warehouses.find_one({"id": warehouse_id}, {"_id": 0})
        if not wh or wh.get("is_active") is False:
            raise HTTPException(400, "Gudang penerimaan tidak aktif atau tidak ditemukan")
        allowed_wh = _allowed_warehouses(user)
        if not _is_global(server, user) and allowed_wh and str(warehouse_id) not in allowed_wh:
            raise HTTPException(403, "Gudang penerimaan di luar kewenangan user")

        qty = float(line.get("qty") or 0)
        already_elsewhere = await Mutation._allocated_elsewhere(server, po_line_id, "do", current_do_id)
        accumulated[po_line_id] = accumulated.get(po_line_id, 0.0) + qty
        available = float(po_line.get("qty") or 0) - float(already_elsewhere or 0)
        if accumulated[po_line_id] > available + 1e-6:
            raise HTTPException(400, f"Qty terima melebihi outstanding PO (tersedia {max(0, available)})")

    if len(supplier_ids) != 1:
        raise HTTPException(400, "Satu DO hanya boleh berisi PO dari supplier yang sama")
    if len(division_ids) != 1:
        raise HTTPException(400, "Satu DO hanya boleh berisi PO dari divisi yang sama")

    supplier_id = next(iter(supplier_ids))
    division_id = next(iter(division_ids))
    header_supplier = normalized.get("supplier_id")
    if header_supplier and str(header_supplier) != supplier_id:
        raise HTTPException(400, "Supplier pada header berbeda dengan supplier PO")

    payload["supplier_id"] = supplier_id
    payload["division_id"] = division_id
    return payload, division_id


async def _decorate_detail(server, result: dict):
    if not isinstance(result, dict):
        return result
    division_id = result.get("division_id") or await _derive_do_division(server, result)
    result["division_id"] = division_id
    if division_id:
        div = await server.db.divisions.find_one({"id": division_id}, {"_id": 0, "name": 1}) or {}
        result["division_name"] = div.get("name")

    for line in result.get("lines") or []:
        po_line_id = line.get("po_line_id")
        if not po_line_id:
            continue
        po_line = await server.db.po_lines.find_one({"id": po_line_id}, {"_id": 0}) or {}
        factor = float(line.get("conversion_factor") or 1)
        if factor <= 0:
            factor = 1.0
        total_received = float(await server.alloc_out(po_line_id, "do") or 0)
        current_qty = float(line.get("qty") or 0)
        line["qty_po"] = float(po_line.get("qty") or 0) / factor
        line["received_before"] = max(0.0, total_received - current_qty) / factor
        line["outstanding"] = max(0.0, float(po_line.get("qty") or 0) - total_received) / factor
    return result


def install(server):
    app = server.app

    # List is filtered by source-PO division. Legacy DO without division_id are derived from lines.
    route = _find_route(app, "/api/do", "GET")
    if route:
        original_list = route.endpoint
        app.router.routes.remove(route)

        async def list_do(user=Depends(server.current_user)):
            rows = await original_list(user=user)
            out = []
            allowed = _allowed_divisions(user)
            for row in rows or []:
                division_id = row.get("division_id") or await _derive_do_division(server, row)
                row["division_id"] = division_id
                if division_id:
                    div = await server.db.divisions.find_one({"id": division_id}, {"_id": 0, "name": 1}) or {}
                    row["division_name"] = div.get("name")
                if _is_global(server, user) or (division_id and str(division_id) in allowed):
                    out.append(row)
            return out

        app.add_api_route("/api/do", list_do, methods=["GET"], tags=["do-integrity"])

    route = _find_route(app, "/api/do/{did}", "GET")
    if route:
        original_detail = route.endpoint
        app.router.routes.remove(route)

        async def get_do(did: str, user=Depends(server.current_user)):
            await _require_do_view(server, did, user)
            result = await original_detail(did=did, user=user)
            return await _decorate_detail(server, result)

        app.add_api_route("/api/do/{did}", get_do, methods=["GET"], tags=["do-integrity"])

    route = _find_route(app, "/api/do", "POST")
    if route:
        original_create = route.endpoint
        app.router.routes.remove(route)

        async def create_do(body: dict, user=Depends(server.current_user)):
            server.require(user, "create")
            payload, division_id = await _validate_body(server, body, user)
            result = await original_create(body=payload, user=user)
            did = result.get("id") if isinstance(result, dict) else None
            if did:
                await server.db.do.update_one({"id": did}, {"$set": {"division_id": division_id}})
                await server.db.stock_ledger.update_many({"doc_id": did}, {"$set": {"division_id": division_id}})
                result["division_id"] = division_id
                result = await _decorate_detail(server, result)
            return result

        app.add_api_route("/api/do", create_do, methods=["POST"], tags=["do-integrity"])

    cap_route = _find_route(app, "/api/transactions/{module}/{did}/capability", "GET")
    if cap_route:
        original_cap = cap_route.endpoint
        app.router.routes.remove(cap_route)

        async def transaction_capability(module: str, did: str, user=Depends(server.current_user)):
            if module == "do":
                await _require_do_view(server, did, user)
            return await original_cap(module=module, did=did, user=user)

        app.add_api_route("/api/transactions/{module}/{did}/capability", transaction_capability, methods=["GET"], tags=["do-integrity"])

    edit_route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if edit_route:
        original_edit = edit_route.endpoint
        app.router.routes.remove(edit_route)

        async def transaction_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
            payload = body
            division_id = None
            if module == "do":
                await _require_do_view(server, did, user)
                payload, division_id = await _validate_body(server, body, user, current_do_id=did)
            result = await original_edit(module=module, did=did, body=payload, user=user)
            if module == "do" and division_id:
                await server.db.do.update_one({"id": did}, {"$set": {"division_id": division_id}})
                await server.db.stock_ledger.update_many({"doc_id": did}, {"$set": {"division_id": division_id}})
            return result

        app.add_api_route("/api/transactions/{module}/{did}", transaction_edit, methods=["PUT"], tags=["do-integrity"])

    delete_route = _find_route(app, "/api/transactions/{module}/{did}", "DELETE")
    if delete_route:
        original_delete = delete_route.endpoint
        app.router.routes.remove(delete_route)

        async def transaction_delete(module: str, did: str, user=Depends(server.current_user)):
            if module == "do":
                await _require_do_view(server, did, user)
            return await original_delete(module=module, did=did, user=user)

        app.add_api_route("/api/transactions/{module}/{did}", transaction_delete, methods=["DELETE"], tags=["do-integrity"])
