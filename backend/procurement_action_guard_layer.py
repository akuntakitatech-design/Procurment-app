"""Guard direct procurement actions that sit outside generic transaction mutation routes.

This closes two important integrity gaps:
- submit/cancel/approve/reject endpoints must obey division visibility just like list/detail/edit;
- a source document cannot be cancelled or re-submitted after an active downstream document exists.

Cancelling/rejecting a downstream document intentionally releases its source reservation because
transaction_integrity_layer only counts allocations whose downstream document remains active.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException

import division_visibility_layer as Division
import transaction_mutation_layer as Mutation


MODULES = {
    "mro": "mro",
    "ro": "ro",
    "po": "po",
}


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _norm(value):
    return str(value or "").strip().lower()


async def _doc(server, module: str, did: str):
    doc = await getattr(server.db, MODULES[module]).find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"{module.upper()} tidak ditemukan")
    return doc


async def _require_owner_division(server, module: str, did: str, user: dict):
    doc = await _doc(server, module, did)
    if not Division._division_allowed(server, user, doc.get("division_id")):
        raise HTTPException(403, "Tidak dapat memproses transaksi divisi lain")
    return doc


async def _require_view_or_assignment(server, module: str, did: str, user: dict):
    doc = await _doc(server, module, did)
    if not await Division._can_view_doc(server, module, doc, user):
        raise HTTPException(403, "Transaksi berada di divisi lain")
    return doc


async def _require_no_downstream(server, module: str, did: str, action: str):
    blockers = await Mutation._blockers(server, module, did)
    if not blockers:
        return
    names = ", ".join(f"{b['type']} {b['no']}" for b in blockers[:4])
    raise HTTPException(
        409,
        f"{module.upper()} tidak dapat {action} karena sudah digunakan oleh {names}. "
        "Batalkan/hapus transaksi turunannya terlebih dahulu.",
    )


def install(server):
    app = server.app

    # Submit is a mutation and therefore must remain inside the user's own division. Once a
    # downstream document exists, re-submit is blocked because it could reset approval/state
    # while the child transaction is still operational.
    for module in MODULES:
        path = f"/api/{module}/{{did}}/submit"
        route = _find_route(app, path, "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_submit(kind, original_endpoint):
            async def guarded_submit(did: str, user=Depends(server.current_user)):
                doc = await _require_owner_division(server, kind, did, user)
                if doc.get("cancelled") is True or _norm(doc.get("status")) in {"cancelled", "canceled"}:
                    raise HTTPException(409, f"{kind.upper()} sudah dibatalkan")
                await _require_no_downstream(server, kind, did, "disubmit ulang")

                if kind == "po":
                    status = _norm(doc.get("status"))
                    approval_status = _norm(doc.get("approval_status"))
                    if status in {"waiting approval", "approved", "partially received", "fully received"}:
                        raise HTTPException(409, f"PO dengan status {doc.get('status')} tidak dapat disubmit ulang")
                    if approval_status == "waiting approval":
                        raise HTTPException(409, "PO masih menunggu approval")
                return await original_endpoint(did, user)
            return guarded_submit

        app.add_api_route(path, make_submit(module, original), methods=["POST"], tags=["procurement-guard"])

    # Cancellation is allowed only from the user's own division and only when there is no active
    # downstream document. A cancelled downstream document is not considered a blocker, which is
    # what restores the upstream outstanding quantity.
    for module in MODULES:
        path = f"/api/{module}/{{did}}/cancel"
        route = _find_route(app, path, "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_cancel(kind, original_endpoint):
            async def guarded_cancel(did: str, body: dict = None, user=Depends(server.current_user)):
                await _require_owner_division(server, kind, did, user)
                await _require_no_downstream(server, kind, did, "dibatalkan")
                return await original_endpoint(did, body or {}, user)
            return guarded_cancel

        app.add_api_route(path, make_cancel(module, original), methods=["POST"], tags=["procurement-guard"])

    # Direct PO approve/reject buttons may be used by an approver assigned to another division,
    # but not by an unrelated user. The underlying approval layer still enforces the exact email
    # assignment, so this wrapper only adds the division/visibility boundary.
    for action in ("approve", "reject"):
        path = f"/api/po/{{did}}/{action}"
        route = _find_route(app, path, "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_approval(original_endpoint):
            async def guarded_approval(did: str, body: dict = None, user=Depends(server.current_user)):
                await _require_view_or_assignment(server, "po", did, user)
                return await original_endpoint(did, body or {}, user)
            return guarded_approval

        app.add_api_route(path, make_approval(original), methods=["POST"], tags=["procurement-guard"])
