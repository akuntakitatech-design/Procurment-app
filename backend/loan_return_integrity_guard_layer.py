"""Integrity guard for loan return create/edit operations.

Validates the full request before legacy handlers write headers, counters, returned
quantities, or stock ledgers. This prevents cross-loan line references and partial
writes on invalid return requests.
"""
from fastapi import Depends, HTTPException


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _replace_route(app, route, path, method, endpoint):
    if route in app.router.routes:
        app.router.routes.remove(route)
    app.add_api_route(path, endpoint, methods=[method], tags=["loan-return-integrity"])


async def _normalized_requests(server, loan_id, body, restore_by_line=None):
    restore_by_line = restore_by_line or {}
    requested = {}
    item_totals = {}
    positive = 0

    for raw in (body or {}).get("lines", []):
        line_id = raw.get("loan_line_id")
        if not line_id:
            raise HTTPException(400, "Baris pinjaman wajib dipilih")
        loan_line = await server.db.loan_lines.find_one({"id": line_id}, {"_id": 0})
        if not loan_line:
            raise HTTPException(400, "Baris pinjaman tidak ditemukan")
        if loan_line.get("loan_id") != loan_id:
            raise HTTPException(400, "Baris pinjaman tidak berasal dari dokumen pinjaman ini")

        factor = float(loan_line.get("conversion_factor") or 1)
        if factor <= 0:
            factor = 1.0
        qty = float(raw.get("qty") or 0) * factor
        if qty <= 0:
            continue
        positive += 1
        requested[line_id] = requested.get(line_id, 0.0) + qty
        item_id = loan_line.get("item_id")
        item_totals[item_id] = item_totals.get(item_id, 0.0) + qty

    if positive == 0:
        raise HTTPException(400, "Qty return harus lebih dari 0")

    for line_id, qty in requested.items():
        loan_line = await server.db.loan_lines.find_one({"id": line_id}, {"_id": 0}) or {}
        returned = float(loan_line.get("returned") or 0)
        restored = float(restore_by_line.get(line_id) or 0)
        available = float(loan_line.get("qty") or 0) - returned + restored
        if qty > available + 1e-6:
            raise HTTPException(400, "Qty return melebihi outstanding pinjaman")

    return item_totals


async def _validate_borrower_stock(server, loan, item_totals, user, restore_by_item=None):
    restore_by_item = restore_by_item or {}
    borrower_wh = loan.get("to_warehouse_id")
    for item_id, qty in item_totals.items():
        current = float(await server.stock_balance(item_id, borrower_wh) or 0)
        available = current + float(restore_by_item.get(item_id) or 0)
        if qty > available + 1e-6 and not server.has_perm(user, "override_qty"):
            raise HTTPException(400, f"Stok gudang peminjam tidak cukup untuk return (tersedia {available})")


def install(server):
    app = server.app

    create_route = _find_route(app, "/api/loans/{did}/return", "POST")
    if create_route:
        original_create = create_route.endpoint

        async def guarded_create_return(did: str, body: dict, user=Depends(server.current_user)):
            loan = await server.db.loans.find_one({"id": did}, {"_id": 0})
            if not loan:
                raise HTTPException(404, "Pinjaman tidak ditemukan")
            item_totals = await _normalized_requests(server, did, body)
            await _validate_borrower_stock(server, loan, item_totals, user)
            return await original_create(did, body, user)

        _replace_route(app, create_route, "/api/loans/{did}/return", "POST", guarded_create_return)

    edit_route = _find_route(app, "/api/loan-returns/{rid}", "PUT")
    if edit_route:
        original_edit = edit_route.endpoint

        async def guarded_edit_return(rid: str, body: dict, user=Depends(server.current_user)):
            ret = await server.db.loan_returns.find_one({"id": rid}, {"_id": 0})
            if not ret:
                raise HTTPException(404, "Return tidak ditemukan")
            loan = await server.db.loans.find_one({"id": ret.get("loan_id")}, {"_id": 0})
            if not loan:
                raise HTTPException(404, "Pinjaman tidak ditemukan")

            old_lines = await server.db.loan_return_lines.find({"return_id": rid}, {"_id": 0}).to_list(1000)
            restore_by_line = {}
            restore_by_item = {}
            for line in old_lines:
                qty = float(line.get("qty") or 0)
                line_id = line.get("loan_line_id")
                item_id = line.get("item_id")
                restore_by_line[line_id] = restore_by_line.get(line_id, 0.0) + qty
                restore_by_item[item_id] = restore_by_item.get(item_id, 0.0) + qty

            item_totals = await _normalized_requests(
                server, ret.get("loan_id"), body, restore_by_line=restore_by_line
            )
            await _validate_borrower_stock(
                server, loan, item_totals, user, restore_by_item=restore_by_item
            )
            return await original_edit(rid, body, user)

        _replace_route(app, edit_route, "/api/loan-returns/{rid}", "PUT", guarded_edit_return)
