"""Approval lifecycle guards for MRO, RO, and PO.

Business rules enforced here:
- Waiting/approved/rejected documents cannot be re-submitted without the proper transition.
- Rejected documents must be edited/revised first; generic transaction edit resets approval to Draft.
- Cancelled documents cannot still be approved/rejected from a stale approval task.
- Cancelling a document closes any pending/waiting approval tasks so inboxes do not show actionable ghosts.
- Rejecting a level closes later waiting levels as Skipped while preserving the approval trail.
- Division authorization is checked before document state so cross-division users cannot infer status.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException

import division_visibility_layer as Division


MODULES = {"mro": "mro", "ro": "ro", "po": "po"}


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _norm(value):
    return str(value or "").strip().lower()


async def _doc(server, module: str, did: str):
    if module not in MODULES:
        raise HTTPException(400, "Modul approval tidak didukung")
    doc = await getattr(server.db, MODULES[module]).find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"{module.upper()} tidak ditemukan")
    return doc


async def _require_owner_division(server, module: str, did: str, user: dict):
    """Reject cross-division mutation before revealing document lifecycle/state."""
    doc = await _doc(server, module, did)
    if not Division._division_allowed(server, user, doc.get("division_id")):
        raise HTTPException(403, "Tidak dapat memproses transaksi divisi lain")
    return doc


def _is_cancelled(doc: dict) -> bool:
    return bool(doc.get("cancelled")) or _norm(doc.get("status")) in {"cancelled", "canceled"}


def _assert_submit_state(module: str, doc: dict):
    if _is_cancelled(doc):
        raise HTTPException(409, f"{module.upper()} sudah dibatalkan")

    approval = _norm(doc.get("approval_status"))
    status = _norm(doc.get("status"))

    if approval == "waiting approval" or status == "waiting approval":
        raise HTTPException(409, f"{module.upper()} masih menunggu approval")

    if approval == "rejected" or status == "rejected":
        raise HTTPException(409, f"{module.upper()} ditolak. Edit/revisi dokumen terlebih dahulu sebelum submit ulang")

    if module in ("mro", "ro"):
        if doc.get("submitted") is True or approval in {"approved", "not required", "legacy approved"}:
            raise HTTPException(409, f"{module.upper()} sudah disubmit/disetujui dan tidak dapat disubmit ulang")
        return

    if status in {"approved", "partially received", "fully received"} or approval in {
        "approved", "not required", "legacy approved"
    }:
        raise HTTPException(409, f"PO dengan status {doc.get('status') or doc.get('approval_status')} tidak dapat disubmit ulang")


async def _close_open_tasks(server, module: str, did: str, status: str, note: str):
    now = server.now_iso()
    query = {
        "module": module,
        "document_id": did,
        "status": {"$in": ["Pending", "Waiting"]},
    }
    patch = {"status": status, "acted_at": now, "note": note}
    rows = await server.db.approval_tasks.find(query, {"_id": 0, "id": 1}).to_list(5000)
    if rows:
        await server.db.approval_tasks.update_many(query, {"$set": patch})
        if module == "po":
            ids = [x.get("id") for x in rows if x.get("id")]
            if ids:
                await server.db.po_approvals.update_many({"id": {"$in": ids}}, {"$set": patch})


def install(server):
    app = server.app

    # Final submit state validation. Division ownership is intentionally checked first so an
    # unrelated user receives 403 without learning whether the document is draft/submitted/etc.
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
                _assert_submit_state(kind, doc)
                return await original_endpoint(did, user)
            return guarded_submit

        app.add_api_route(path, make_submit(module, original), methods=["POST"], tags=["approval-state"])

    # A cancelled document must not leave live approval tasks in user inboxes. Authorization is
    # rechecked before mutation so document state cannot be exposed across divisions.
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
                result = await original_endpoint(did, body or {}, user)
                await _close_open_tasks(server, kind, did, "Cancelled", "Dokumen dibatalkan")
                return result
            return guarded_cancel

        app.add_api_route(path, make_cancel(module, original), methods=["POST"], tags=["approval-state"])

    # Approval inbox actions must re-check document state, not only the task row. Approval tasks
    # may legitimately be assigned cross-division, so the underlying approval layer remains the
    # authority for exact approver identity on these task-based endpoints.
    for action in ("approve", "reject"):
        path = f"/api/approvals/{{approval_id}}/{action}"
        route = _find_route(app, path, "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_inbox_action(kind, original_endpoint):
            async def guarded_action(approval_id: str, body: dict = None, user=Depends(server.current_user)):
                task = await server.db.approval_tasks.find_one({"id": approval_id}, {"_id": 0})
                if not task:
                    raise HTTPException(404, "Approval tidak ditemukan")
                module = task.get("module")
                did = task.get("document_id")
                doc = await _doc(server, module, did)
                if _is_cancelled(doc):
                    raise HTTPException(409, "Dokumen sudah dibatalkan dan tidak dapat diproses approval")
                if _norm(doc.get("approval_status")) != "waiting approval" and _norm(doc.get("status")) != "waiting approval":
                    raise HTTPException(409, "Dokumen tidak lagi dalam status menunggu approval")

                result = await original_endpoint(approval_id, body or {}, user)
                if kind == "reject":
                    await _close_open_tasks(server, module, did, "Skipped", "Approval dihentikan karena dokumen ditolak")
                return result
            return guarded_action

        app.add_api_route(path, make_inbox_action(action, original), methods=["POST"], tags=["approval-state"])
