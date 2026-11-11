"""Minta Revisi & Tarik Approval untuk PO.

Dua jalur yang dipisahkan dengan sengaja:

1. `POST /api/po/{did}/request-revision` — **approver** pada tahap yang sedang menunggu (Approval 1
   atau Approval 2) mengembalikan PO ke purchasing dengan **catatan wajib**. PO berstatus `Revision`
   ("Perlu Revisi"), seluruh task approval yang masih terbuka ditutup, purchasing memperbaiki lalu
   submit ulang. Rantai approval dibuat ulang dari level 1 oleh endpoint submit yang sudah ada.

2. `POST /api/po/{did}/revoke-approval` — **Admin/Director** mencabut approval yang SUDAH diberikan
   (mis. PO sudah `Approved` tetapi isinya perlu direvisi). Rantai approval dibuka ulang dari level 1
   dengan riwayat lama ditandai `Revoked` (tidak dihapus). Ditolak bila PO sudah dipakai dokumen
   turunan (DO/invoice) memakai pemeriksaan yang sama dengan edit/hapus transaksi.

Tidak mengubah angka, stok, maupun valuasi: hanya status + jejak approval/audit.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException

import transaction_mutation_layer as TML

REVISION = "Revision"
OPEN_STATUSES = ["Approved", "Pending", "Waiting", "Revision"]


def _norm(v) -> str:
    return str(v or "").strip().lower()


def _is_cancelled(doc: dict) -> bool:
    return bool(doc.get("cancelled")) or _norm(doc.get("status")) in {"cancelled", "canceled"}


def _is_waiting(doc: dict) -> bool:
    return _norm(doc.get("status")) == "waiting approval" or _norm(doc.get("approval_status")) == "waiting approval"


def _require_owner_division(server, doc: dict, user: dict) -> None:
    """Cakupan divisi diperiksa SEBELUM status dokumen supaya status tidak bocor antar divisi."""
    if server.is_global(user):
        return
    divs = {str(x) for x in (user.get("divisions") or []) if x}
    div = doc.get("division_id")
    if div and str(div) not in divs:
        raise HTTPException(403, "Tidak dapat memproses transaksi divisi lain")


async def _get_po(server, did: str) -> dict:
    doc = await server.db.po.find_one({"id": did}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "PO tidak ditemukan")
    return doc


def _actor(user: dict) -> dict:
    return {"name": user.get("name") or user.get("email"), "email": user.get("email")}


async def _close_task(server, task_id: str, patch: dict) -> None:
    """Sinkronkan status task inbox + salinan `po_approvals` (keduanya memakai id yang sama)."""
    await server.db.approval_tasks.update_one({"id": task_id}, {"$set": patch})
    await server.db.po_approvals.update_many({"id": task_id}, {"$set": patch})


async def request_revision(server, did: str, body: dict, user: dict) -> dict:
    if not server.has_perm(user, "approve"):
        raise HTTPException(403, "Anda tidak memiliki izin untuk menyetujui dokumen")
    doc = await _get_po(server, did)
    _require_owner_division(server, doc, user)
    if _is_cancelled(doc):
        raise HTTPException(409, "PO sudah dibatalkan")
    if not _is_waiting(doc):
        raise HTTPException(409, "PO tidak sedang menunggu approval")

    note = str((body or {}).get("note") or "").strip()
    if len(note) < 5:
        raise HTTPException(400, "Catatan revisi wajib diisi (minimal 5 karakter)")

    step = await server.db.approval_tasks.find_one(
        {"module": "po", "document_id": did, "status": "Pending"}, {"_id": 0}, sort=[("seq", 1)])
    if not step:
        raise HTTPException(400, "Tidak ada tahap approval yang menunggu")

    assigned = str(step.get("approver_email") or "").lower()
    me_email = str(user.get("email") or "").lower()
    if assigned and assigned != me_email and user.get("role") != "admin":
        raise HTTPException(403, f"Tahap ini menjadi wewenang {step.get('approver_name') or assigned}")

    now = server.now_iso()
    actor = _actor(user)
    level = step.get("level") or step.get("seq")
    await _close_task(server, step["id"], {"status": "Revision", "acted_by": actor["name"],
                                          "acted_by_email": actor["email"], "acted_at": now, "note": note})

    # Tahap lain yang belum diproses ikut ditutup agar tidak ada task menggantung di inbox.
    rest = await server.db.approval_tasks.find(
        {"module": "po", "document_id": did, "id": {"$ne": step["id"]},
         "status": {"$in": ["Pending", "Waiting"]}}, {"_id": 0, "id": 1}).to_list(200)
    rest_ids = [x["id"] for x in rest if x.get("id")]
    if rest_ids:
        await server.db.approval_tasks.update_many(
            {"id": {"$in": rest_ids}},
            {"$set": {"status": "Revision", "acted_at": now, "note": f"Revisi diminta pada level {level}"}})
        await server.db.po_approvals.update_many(
            {"id": {"$in": rest_ids}},
            {"$set": {"status": "Revision", "acted_at": now, "note": f"Revisi diminta pada level {level}"}})

    entry = {"id": server.gid(), "level": level, "by": actor["name"], "by_email": actor["email"],
             "at": now, "note": note}
    await server.db.po.update_one(
        {"id": did},
        {"$set": {"status": REVISION, "approval_status": REVISION},
         "$push": {"revision_requests": entry}, "$inc": {"revision_count": 1}})

    await server.audit(user, "request_revision", "po", did, doc.get("no"), reason=f"Level {level}: {note}")
    await server.notify(
        "PO perlu revisi",
        f"{doc.get('no')} dikembalikan untuk direvisi oleh {actor['name']} (level {level}). Catatan: {note[:180]}",
        "revision", doc.get("division_id"))
    return {"ok": True, "status": REVISION, "level": level}


async def revoke_approval(server, did: str, body: dict, user: dict) -> dict:
    if user.get("role") not in ("admin", "director"):
        raise HTTPException(403, "Hanya Admin atau Director yang dapat menarik approval")
    doc = await _get_po(server, did)
    _require_owner_division(server, doc, user)
    if _is_cancelled(doc):
        raise HTTPException(409, "PO sudah dibatalkan")

    reason = str((body or {}).get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(400, "Alasan penarikan approval wajib diisi (minimal 5 karakter)")

    status = _norm(doc.get("status"))
    if status in ("", "draft"):
        raise HTTPException(409, "PO belum disubmit sehingga belum ada approval untuk ditarik")

    # PO yang sudah dipakai DO/invoice tidak boleh dibuka ulang (stok & keuangan sudah mengalir).
    blockers = await TML._blockers(server, "po", did)
    if blockers:
        names = ", ".join(f"{b['type']} {b['no']}" for b in blockers[:4])
        raise HTTPException(409, f"Approval tidak dapat ditarik: PO sudah dipakai oleh {names}. "
                                 f"Batalkan dokumen turunan terlebih dahulu.")

    tasks = await server.db.approval_tasks.find(
        {"module": "po", "document_id": did}, {"_id": 0}).sort("seq", 1).to_list(200)
    if not tasks:
        raise HTTPException(400, "PO ini tidak memiliki tahap approval (disetujui tanpa approver).")

    approved = [t for t in tasks if _norm(t.get("status")) == "approved"]
    if not approved and status != "approved":
        raise HTTPException(400, "Belum ada approval yang diberikan pada PO ini")

    now = server.now_iso()
    actor = _actor(user)
    history = {"status": "Revoked", "acted_by": actor["name"], "acted_by_email": actor["email"],
               "acted_at": now, "note": reason}
    # Riwayat approval lama tetap tersimpan di approval_tasks (status Revoked) + audit_logs.
    await server.db.approval_tasks.update_many(
        {"module": "po", "document_id": did, "status": {"$in": OPEN_STATUSES}}, {"$set": history})

    # Rantai baru dari level 1 memakai susunan approver yang sama seperti sebelumnya.
    # `po_approvals` hanya mirror tampilan, jadi dibuat ulang agar detail PO tidak menampilkan
    # dua baris dengan seq yang sama (appoval lama sudah tercatat Revoked di approval_tasks).
    await server.db.po_approvals.delete_many({"po_id": did})
    for i, t in enumerate(tasks):
        task = {
            "id": server.gid(), "module": "po", "document_type": t.get("document_type") or "Purchase Order",
            "document_id": did, "document_no": doc.get("no"),
            "seq": t.get("seq") or i + 1, "level": t.get("level"),
            "approver_user_id": t.get("approver_user_id"), "approver_email": t.get("approver_email"),
            "approver_name": t.get("approver_name"),
            "status": "Pending" if i == 0 else "Waiting",
            "acted_by": None, "acted_by_email": None, "acted_at": None, "note": None,
        }
        await server.db.approval_tasks.insert_one(dict(task))
        po_task = {**task, "po_id": did, "role": None}
        for key in ("module", "document_type", "document_id", "document_no"):
            po_task.pop(key, None)
        await server.db.po_approvals.insert_one(po_task)

    entry = {"id": server.gid(), "by": actor["name"], "by_email": actor["email"], "at": now, "reason": reason}
    await server.db.po.update_one(
        {"id": did},
        {"$set": {"status": "Waiting Approval", "approval_status": "Waiting Approval"},
         "$push": {"approval_revocations": entry}})

    await server.audit(user, "revoke_approval", "po", did, doc.get("no"), reason=reason)
    await server.notify(
        "Approval PO ditarik",
        f"{doc.get('no')} dibuka ulang untuk approval oleh {actor['name']}. Alasan: {reason[:180]}",
        "revision", doc.get("division_id"))
    return {"ok": True, "status": "Waiting Approval"}


def install(server):
    app = server.app

    @app.post("/api/po/{did}/request-revision", tags=["po-revision"])
    async def po_request_revision(did: str, body: dict = None, user=Depends(server.current_user)):
        return await request_revision(server, did, body or {}, user)

    @app.post("/api/po/{did}/revoke-approval", tags=["po-revision"])
    async def po_revoke_approval(did: str, body: dict = None, user=Depends(server.current_user)):
        return await revoke_approval(server, did, body or {}, user)
