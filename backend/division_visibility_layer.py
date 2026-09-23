"""Division-scoped visibility and mutation guard for the procurement chain.

Business rules:
- Admin, Director, Purchasing, global-scope users, or users with view_all_division may see all divisions.
- Other users may only see MRO/RO/PO documents in their assigned divisions.
- A user explicitly assigned as an approver may still open the assigned document for approval.
- Limited users may not create or edit procurement documents into a division they do not own.
- Source pickers are filtered server-side so other divisions cannot be discovered through pull dialogs.

This layer is intentionally server-side. Frontend filtering is only presentation and is not the
security boundary.
"""
from __future__ import annotations

from copy import deepcopy

from fastapi import Depends, HTTPException


PROCUREMENT_MODULES = {
    "mro": "mro",
    "ro": "ro",
    "po": "po",
}


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _is_global(server, user: dict) -> bool:
    return bool(server.is_global(user))


def _allowed_divisions(user: dict) -> set[str]:
    return {str(x) for x in (user.get("divisions") or []) if x}


def _division_allowed(server, user: dict, division_id) -> bool:
    if _is_global(server, user):
        return True
    return bool(division_id) and str(division_id) in _allowed_divisions(user)


async def _assigned_approval_ids(server, module: str, user: dict) -> set[str]:
    email = str(user.get("email") or "").strip().lower()
    if not email:
        return set()
    rows = await server.db.approval_tasks.find(
        {"module": module, "approver_email": email},
        {"_id": 0, "document_id": 1},
    ).to_list(5000)
    return {str(x.get("document_id")) for x in rows if x.get("document_id")}


async def _can_view_doc(server, module: str, doc: dict, user: dict) -> bool:
    if not doc:
        return False
    if _division_allowed(server, user, doc.get("division_id")):
        return True
    assigned = await _assigned_approval_ids(server, module, user)
    return str(doc.get("id")) in assigned


async def _require_doc_view(server, module: str, did: str, user: dict):
    doc = await getattr(server.db, PROCUREMENT_MODULES[module]).find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"{module.upper()} tidak ditemukan")
    if not await _can_view_doc(server, module, doc, user):
        raise HTTPException(403, "Transaksi berada di divisi lain")
    return doc


async def _require_doc_mutation(server, module: str, did: str, user: dict):
    doc = await getattr(server.db, PROCUREMENT_MODULES[module]).find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"{module.upper()} tidak ditemukan")
    if not _division_allowed(server, user, doc.get("division_id")):
        raise HTTPException(403, "Tidak dapat mengubah transaksi divisi lain")
    return doc


def _guard_body_division(server, body: dict, user: dict) -> dict:
    payload = deepcopy(body or {})
    if _is_global(server, user):
        return payload

    allowed = _allowed_divisions(user)
    division_id = payload.get("division_id")
    if not division_id:
        if len(allowed) == 1:
            payload["division_id"] = next(iter(allowed))
            return payload
        raise HTTPException(400, "Pilih divisi yang menjadi kewenangan user")
    if str(division_id) not in allowed:
        raise HTTPException(403, "Tidak dapat menggunakan divisi di luar kewenangan user")
    return payload


async def _filter_rows_by_doc(server, module: str, id_key: str, rows: list, user: dict):
    if _is_global(server, user):
        return rows or []
    rows = rows or []
    ids = list({x.get(id_key) for x in rows if x.get(id_key)})
    if not ids:
        return []
    docs = await getattr(server.db, PROCUREMENT_MODULES[module]).find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "division_id": 1}
    ).to_list(len(ids) + 10)
    allowed = _allowed_divisions(user)
    visible_ids = {
        d.get("id") for d in docs
        if d.get("division_id") and str(d.get("division_id")) in allowed
    }
    return [x for x in rows if x.get(id_key) in visible_ids]


def install(server):
    app = server.app

    # Final list/detail wrappers for the procurement request/order chain.
    for module in PROCUREMENT_MODULES:
        list_path = f"/api/{module}"
        list_route = _find_route(app, list_path, "GET")
        if list_route:
            original_list = list_route.endpoint
            app.router.routes.remove(list_route)

            def make_list(kind, original_endpoint):
                async def listing(user=Depends(server.current_user)):
                    rows = await original_endpoint(user=user)
                    if _is_global(server, user):
                        return rows
                    assigned = await _assigned_approval_ids(server, kind, user)
                    allowed = _allowed_divisions(user)
                    return [
                        row for row in (rows or [])
                        if (row.get("division_id") and str(row.get("division_id")) in allowed)
                        or str(row.get("id")) in assigned
                    ]
                return listing

            app.add_api_route(list_path, make_list(module, original_list), methods=["GET"], tags=["division-access"])

        detail_path = f"/api/{module}/{{did}}"
        detail_route = _find_route(app, detail_path, "GET")
        if detail_route:
            original_detail = detail_route.endpoint
            app.router.routes.remove(detail_route)

            def make_detail(kind, original_endpoint):
                async def detail(did: str, user=Depends(server.current_user)):
                    await _require_doc_view(server, kind, did, user)
                    return await original_endpoint(did=did, user=user)
                return detail

            app.add_api_route(detail_path, make_detail(module, original_detail), methods=["GET"], tags=["division-access"])

        create_route = _find_route(app, list_path, "POST")
        if create_route:
            original_create = create_route.endpoint
            app.router.routes.remove(create_route)

            def make_create(kind, original_endpoint):
                async def create(body: dict, user=Depends(server.current_user)):
                    payload = _guard_body_division(server, body, user)
                    return await original_endpoint(body=payload, user=user)
                return create

            app.add_api_route(list_path, make_create(module, original_create), methods=["POST"], tags=["division-access"])

    # Source pickers must never leak other divisions.
    for path, module, id_key in (
        ("/api/pull/mro-for-ro", "mro", "mro_id"),
        ("/api/pull/mro-for-mi", "mro", "mro_id"),
        ("/api/pull/ro-for-po", "ro", "ro_id"),
    ):
        route = _find_route(app, path, "GET")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_pull(kind, key, original_endpoint):
            async def pull(user=Depends(server.current_user)):
                rows = await original_endpoint(user=user)
                return await _filter_rows_by_doc(server, kind, key, rows, user)
            return pull

        app.add_api_route(path, make_pull(module, id_key, original), methods=["GET"], tags=["division-access"])

    po_do_route = _find_route(app, "/api/pull/po-for-do", "GET")
    if po_do_route:
        original_po_do = po_do_route.endpoint
        app.router.routes.remove(po_do_route)

        async def pull_po_for_do(supplier_id: str = None, user=Depends(server.current_user)):
            rows = await original_po_do(supplier_id=supplier_id, user=user)
            return await _filter_rows_by_doc(server, "po", "po_id", rows, user)

        app.add_api_route("/api/pull/po-for-do", pull_po_for_do, methods=["GET"], tags=["division-access"])

    # Generic guarded edit/delete/capability routes are also division-aware for MRO/RO/PO.
    cap_route = _find_route(app, "/api/transactions/{module}/{did}/capability", "GET")
    if cap_route:
        original_cap = cap_route.endpoint
        app.router.routes.remove(cap_route)

        async def transaction_capability(module: str, did: str, user=Depends(server.current_user)):
            if module in PROCUREMENT_MODULES:
                await _require_doc_view(server, module, did, user)
            return await original_cap(module=module, did=did, user=user)

        app.add_api_route(
            "/api/transactions/{module}/{did}/capability", transaction_capability,
            methods=["GET"], tags=["division-access"],
        )

    edit_route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if edit_route:
        original_edit = edit_route.endpoint
        app.router.routes.remove(edit_route)

        async def transaction_edit(module: str, did: str, body: dict, user=Depends(server.current_user)):
            payload = body
            if module in PROCUREMENT_MODULES:
                await _require_doc_mutation(server, module, did, user)
                payload = _guard_body_division(server, body, user)
            return await original_edit(module=module, did=did, body=payload, user=user)

        app.add_api_route(
            "/api/transactions/{module}/{did}", transaction_edit,
            methods=["PUT"], tags=["division-access"],
        )

    delete_route = _find_route(app, "/api/transactions/{module}/{did}", "DELETE")
    if delete_route:
        original_delete = delete_route.endpoint
        app.router.routes.remove(delete_route)

        async def transaction_delete(module: str, did: str, user=Depends(server.current_user)):
            if module in PROCUREMENT_MODULES:
                await _require_doc_mutation(server, module, did, user)
            return await original_delete(module=module, did=did, user=user)

        app.add_api_route(
            "/api/transactions/{module}/{did}", transaction_delete,
            methods=["DELETE"], tags=["division-access"],
        )
