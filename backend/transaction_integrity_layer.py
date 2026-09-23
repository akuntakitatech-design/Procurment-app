"""Cross-transaction integrity fixes for source pulling and approval routing.

This layer keeps source availability consistent with what users see in transaction
lists, ignores allocations that only point to cancelled/rejected/deleted downstream
docs, repairs legacy submitted flags, and prevents create-with-submit payloads from
bypassing configured approval.
"""
from copy import deepcopy
from fastapi import Depends, HTTPException

import doc_procurement
import doc_reports


TARGET_COLLECTIONS = {
    "ro": "ro",
    "po": "po",
    "do": "do",
    "mi": "mi",
}


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _approval_enabled(server, module):
    cfg = await server.db.settings.find_one({"id": "approval_modules"}, {"_id": 0}) or {}
    row = (cfg.get("modules") or {}).get(module)
    if row is not None:
        return bool(row.get("enabled", False))
    if module == "po":
        legacy = await server.db.settings.find_one({"id": "approval_levels"}, {"_id": 0}) or {}
        return bool(legacy.get("levels"))
    return False


def _norm(v):
    return str(v or "").strip().lower()


def _source_allowed(doc, module):
    """Return whether a header may be offered as a source document.

    Missing `submitted` is treated as legacy-approved because the transaction list
    historically did the same. Waiting/rejected approval always wins over that
    compatibility behavior.
    """
    if not doc:
        return False
    if doc.get("cancelled") is True or doc.get("deleted") is True:
        return False

    status = _norm(doc.get("status"))
    approval_status = _norm(doc.get("approval_status"))
    if status in ("cancelled", "canceled", "rejected"):
        return False
    if approval_status in ("waiting approval", "rejected"):
        return False

    if module in ("mro", "ro"):
        return doc.get("submitted", True) is not False
    if module == "po":
        return status in ("approved", "partially received", "fully received")
    return True


def install(server):
    app = server.app

    async def normalize_legacy_submission(module):
        """Make legacy MRO/RO list and pull semantics identical.

        Old rows may have no `submitted` field. Lists treated those rows as Open,
        while source pulls required submitted=True and therefore returned nothing.
        Never auto-approve rows already marked Waiting Approval or Rejected.
        """
        if module not in ("mro", "ro"):
            return
        col = getattr(server.db, module)
        safe_legacy = {
            "submitted": {"$exists": False},
            "cancelled": {"$ne": True},
            "approval_status": {"$nin": ["Waiting Approval", "Rejected"]},
        }
        await col.update_many(
            safe_legacy,
            {"$set": {
                "submitted": True,
                "approval_status": "Legacy Approved",
                "approval_mode": "legacy",
            }},
        )
        await col.update_many(
            {
                "submitted": True,
                "approval_status": {"$exists": False},
                "cancelled": {"$ne": True},
            },
            {"$set": {"approval_status": "Legacy Approved", "approval_mode": "legacy"}},
        )

    async def active_alloc_out(source_line_id, target_type):
        """Sum only allocations whose downstream document is still active.

        Cancelled, rejected, deleted, and orphaned downstream documents must not
        permanently consume source outstanding qty. Draft/Waiting Approval rows do
        remain reserved, preventing duplicate pulls while a transaction is in flight.
        """
        rows = await server.db.allocations.find(
            {"source_line_id": source_line_id, "target_type": target_type}, {"_id": 0}
        ).to_list(5000)
        if not rows:
            return 0
        collection_name = TARGET_COLLECTIONS.get(target_type)
        if not collection_name:
            return sum(float(r.get("qty") or 0) for r in rows)

        doc_ids = list({r.get("target_doc_id") for r in rows if r.get("target_doc_id")})
        if not doc_ids:
            return 0
        docs = await getattr(server.db, collection_name).find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "cancelled": 1, "deleted": 1, "status": 1, "approval_status": 1},
        ).to_list(len(doc_ids) + 10)
        active_ids = set()
        for doc in docs:
            status = _norm(doc.get("status"))
            approval_status = _norm(doc.get("approval_status"))
            if doc.get("cancelled") is True or doc.get("deleted") is True:
                continue
            if status in ("cancelled", "canceled", "rejected") or approval_status == "rejected":
                continue
            active_ids.add(doc.get("id"))
        return sum(float(r.get("qty") or 0) for r in rows if r.get("target_doc_id") in active_ids)

    # Replace module globals used at request time. This makes MRO/RO/PO source
    # outstanding quantities recover when a downstream document is cancelled or
    # rejected, without deleting historical allocation rows.
    server.alloc_out = active_alloc_out
    doc_procurement.alloc_out = active_alloc_out
    doc_reports.alloc_out = active_alloc_out

    @app.on_event("startup")
    async def migrate_legacy_submission_flags():
        for module in ("mro", "ro"):
            await normalize_legacy_submission(module)

    async def filter_source_rows(module, id_key, rows):
        rows = rows or []
        ids = list({r.get(id_key) for r in rows if r.get(id_key)})
        if not ids:
            return []
        docs = await getattr(server.db, module).find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "submitted": 1, "cancelled": 1, "deleted": 1,
             "status": 1, "approval_status": 1, "approval_mode": 1},
        ).to_list(len(ids) + 10)
        by_id = {d.get("id"): d for d in docs}
        return [r for r in rows if _source_allowed(by_id.get(r.get(id_key)), module)]

    # Harden every source-picker in the procurement chain. This also performs the
    # legacy repair immediately on each request, so source availability does not
    # depend on a one-time migration having run successfully.
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
            async def guarded_pull(user=Depends(server.current_user)):
                await normalize_legacy_submission(kind)
                rows = await original_endpoint(user=user)
                return await filter_source_rows(kind, key, rows)
            return guarded_pull

        app.add_api_route(path, make_pull(module, id_key, original), methods=["GET"], tags=["integrity"])

    route = _find_route(app, "/api/pull/po-for-do", "GET")
    if route:
        original_po_pull = route.endpoint
        app.router.routes.remove(route)

        async def guarded_po_pull(supplier_id: str = None, user=Depends(server.current_user)):
            rows = await original_po_pull(supplier_id=supplier_id, user=user)
            return await filter_source_rows("po", "po_id", rows)

        app.add_api_route("/api/pull/po-for-do", guarded_po_pull, methods=["GET"], tags=["integrity"])

    # API callers (including the MRO "Simpan & Submit" button) must not be able
    # to bypass approval merely by sending submitted=true in the create payload.
    for module in ("mro", "ro"):
        route = _find_route(app, f"/api/{module}", "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_create(kind, original_endpoint):
            async def create_with_submit_guard(body: dict, user=Depends(server.current_user)):
                payload = deepcopy(body or {})
                wants_submit = bool(payload.get("submitted"))
                if wants_submit and await _approval_enabled(server, kind):
                    payload["submitted"] = False
                    result = await original_endpoint(payload, user)
                    did = result.get("id") if isinstance(result, dict) else None
                    if not did:
                        return result
                    submit_route = _find_route(app, f"/api/{kind}/{{did}}/submit", "POST")
                    if not submit_route:
                        raise HTTPException(500, f"Route submit {kind.upper()} tidak tersedia")
                    return await submit_route.endpoint(did, user)
                return await original_endpoint(payload, user)
            return create_with_submit_guard

        app.add_api_route(f"/api/{module}", make_create(module, original), methods=["POST"], tags=["integrity"])

    # PO form still exposes direct Approve/Reject buttons. Route them through the
    # same email-assigned approval task used by the dedicated Approval inbox.
    for action in ("approve", "reject"):
        route = _find_route(app, f"/api/po/{{did}}/{action}", "POST")
        if not route:
            continue
        legacy_endpoint = route.endpoint
        app.router.routes.remove(route)

        def make_po_action(kind, legacy):
            async def guarded(did: str, body: dict = None, user=Depends(server.current_user)):
                task = await server.db.approval_tasks.find_one(
                    {"module": "po", "document_id": did, "status": "Pending"},
                    {"_id": 0}, sort=[("seq", 1)],
                )
                if task:
                    inbox_route = _find_route(app, f"/api/approvals/{{approval_id}}/{kind}", "POST")
                    if not inbox_route:
                        raise HTTPException(500, "Route Approval tidak tersedia")
                    return await inbox_route.endpoint(task["id"], body or {}, user)

                po = await server.db.po.find_one({"id": did}, {"_id": 0}) or {}
                if po.get("approval_mode") == "email-level":
                    raise HTTPException(400, "Tidak ada approval email yang sedang menunggu")
                return await legacy(did, body or {}, user)
            return guarded

        app.add_api_route(
            f"/api/po/{{did}}/{action}", make_po_action(action, legacy_endpoint),
            methods=["POST"], tags=["integrity"],
        )
