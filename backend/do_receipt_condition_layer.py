"""Receipt-condition handling for DO / penerimaan barang.

This layer keeps the commercial receipt quantity (`qty`) separate from quality/physical
exceptions. The existing DO allocation continues to decide how much of the PO is received.
`exception_qty` is informational except for damaged goods, where the damaged portion is
immediately removed from usable stock through an offsetting ledger entry.

Supported conditions:
- Baik   : normal receipt; exception_qty is forced to 0.
- Rusak  : qty still counts as physically received against the PO, while exception_qty
           (<= qty) is moved out of usable stock as "DO Damaged Hold".
- Kurang : qty is the quantity actually received; exception_qty records the shortage and
           does not reduce the remaining PO outstanding.
- Lebih  : qty is the quantity accepted against the PO; exception_qty records physical
           excess that is not accepted into stock and does not exceed the PO commercially.

Edit/delete remain reversible because the damaged-stock offset uses the same DO id and is
therefore included in the generic transaction reversal mechanism.
"""
from __future__ import annotations

from copy import deepcopy

from fastapi import Depends, HTTPException


CONDITIONS = {
    "baik": "Baik",
    "rusak": "Rusak",
    "kurang": "Kurang",
    "lebih": "Lebih",
}
EPS = 1e-6


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _condition(value):
    key = str(value or "Baik").strip().lower()
    if key not in CONDITIONS:
        raise HTTPException(400, "Kondisi penerimaan harus Baik, Rusak, Kurang, atau Lebih")
    return CONDITIONS[key]


def _prepare_body(body: dict):
    payload = deepcopy(body or {})
    for line in payload.get("lines") or []:
        qty = float(line.get("qty") or 0)
        if qty <= 0:
            continue
        cond = _condition(line.get("condition"))
        exc = float(line.get("exception_qty") or 0)
        if exc < -EPS:
            raise HTTPException(400, "Qty selisih/rusak tidak boleh negatif")
        exc = max(0.0, exc)

        if cond == "Baik":
            exc = 0.0
        elif cond == "Rusak":
            if exc <= EPS:
                raise HTTPException(400, "Kondisi Rusak wajib mengisi Qty Rusak")
            if exc > qty + EPS:
                raise HTTPException(400, "Qty Rusak tidak boleh melebihi Qty Terima")
        elif cond == "Kurang":
            if exc <= EPS:
                raise HTTPException(400, "Kondisi Kurang wajib mengisi Qty Kurang")
        elif cond == "Lebih":
            if exc <= EPS:
                raise HTTPException(400, "Kondisi Lebih wajib mengisi Qty Lebih")

        line["condition"] = cond
        line["exception_qty"] = exc
    return payload


async def _doc_context(server, did: str):
    doc = await server.db.do.find_one({"id": did}, {"_id": 0, "no": 1, "division_id": 1}) or {}
    return doc.get("no") or did, doc.get("division_id")


async def _match_stored_lines(server, did: str, raw_lines: list[dict]):
    stored = await server.db.do_lines.find({"do_id": did}, {"_id": 0}).to_list(5000)
    unused = list(stored)
    pairs = []
    for raw in raw_lines:
        if float(raw.get("qty") or 0) <= 0:
            continue
        po_line_id = raw.get("po_line_id") or (((raw.get("sources") or [{}])[0]) or {}).get("line_id")
        item_id = raw.get("item_id")
        idx = next((i for i, row in enumerate(unused)
                    if str(row.get("po_line_id")) == str(po_line_id)
                    and str(row.get("item_id")) == str(item_id)), None)
        if idx is None:
            raise HTTPException(500, "Baris DO tersimpan tidak dapat dipetakan ke input penerimaan")
        pairs.append((raw, unused.pop(idx)))
    return pairs


async def _apply_metadata_and_damage(server, did: str, body: dict, user: dict, result=None):
    pairs = await _match_stored_lines(server, did, body.get("lines") or [])
    doc_no, division_id = await _doc_context(server, did)
    has_exception = False
    summary = {"rusak": 0.0, "kurang": 0.0, "lebih": 0.0}
    result_by_id = {x.get("id"): x for x in (result or {}).get("lines", []) if isinstance(x, dict)} if isinstance(result, dict) else {}

    for raw, stored in pairs:
        cond = _condition(raw.get("condition"))
        exc_display = float(raw.get("exception_qty") or 0)
        factor = float(stored.get("conversion_factor") or 1)
        if factor <= 0:
            factor = 1.0
        exc_base = exc_display * factor
        received_base = float(stored.get("qty") or 0)
        usable_base = received_base

        if cond == "Rusak":
            if exc_base > received_base + EPS:
                raise HTTPException(400, "Qty Rusak melebihi Qty Terima setelah konversi satuan")
            usable_base = max(0.0, received_base - exc_base)
            wh = stored.get("warehouse_id") or body.get("default_warehouse_id")
            if exc_base > EPS:
                await server.post_ledger(
                    "DO Damaged Hold", doc_no, did, stored.get("item_id"), wh,
                    0, exc_base,
                    project_id=stored.get("project_id"), unit_id=stored.get("unit_id"),
                    division_id=division_id, user=user,
                )
        if cond != "Baik" and exc_display > EPS:
            has_exception = True
            summary[cond.lower()] = summary.get(cond.lower(), 0.0) + exc_display

        patch = {
            "condition": cond,
            "exception_qty": exc_display,
            "exception_qty_base": exc_base,
            "usable_qty": usable_base / factor,
            "usable_qty_base": usable_base,
        }
        await server.db.do_lines.update_one({"id": stored.get("id")}, {"$set": patch})
        if stored.get("id") in result_by_id:
            result_by_id[stored.get("id")].update(patch)

    await server.db.do.update_one({"id": did}, {"$set": {
        "has_receipt_exception": has_exception,
        "receipt_exception_summary": summary,
    }})
    if isinstance(result, dict):
        result["has_receipt_exception"] = has_exception
        result["receipt_exception_summary"] = summary
    return result


def install(server):
    app = server.app

    create_route = _find_route(app, "/api/do", "POST")
    if create_route:
        original_create = create_route.endpoint
        app.router.routes.remove(create_route)

        async def create_do(body: dict, user=Depends(server.current_user)):
            payload = _prepare_body(body)
            result = await original_create(body=payload, user=user)
            did = result.get("id") if isinstance(result, dict) else None
            if did:
                result = await _apply_metadata_and_damage(server, did, payload, user, result)
            return result

        app.add_api_route("/api/do", create_do, methods=["POST"], tags=["do-condition"])

    edit_route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if edit_route:
        original_edit = edit_route.endpoint
        app.router.routes.remove(edit_route)

        async def transaction_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
            payload = _prepare_body(body) if module == "do" else body
            result = await original_edit(module=module, did=did, body=payload, user=user)
            if module == "do":
                result = await _apply_metadata_and_damage(server, did, payload, user, result)
            return result

        app.add_api_route("/api/transactions/{module}/{did}", transaction_edit, methods=["PUT"], tags=["do-condition"])
