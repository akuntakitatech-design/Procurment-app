"""Cascade pembatalan PO -> RO -> MRO.

Aturan (opsi A yang disetujui pemilik):

1. **Reject** PO (Approval 1/2) dan **Batalkan** PO sama-sama menjadikan PO **batal final**
   (`status=Cancelled`, `cancelled=true`). Jalur perbaikan bukan lagi reject, melainkan
   "Minta Revisi" (lihat `po_revision_layer.py`).
2. Alokasi `RO -> PO` milik PO itu dilepas agar sisa qty RO akurat dan bisa dipesan lagi.
3. **RO** sumber dibatalkan otomatis HANYA bila setelah pelepasan tidak ada lagi PO aktif
   yang mengambil RO tersebut (sisa qty tidak boleh hilang gara-gara PO lain).
4. **MRO** dibatalkan otomatis HANYA bila seluruh RO turunannya sudah dibatalkan dan tidak ada
   MI (barang sudah keluar gudang).

Tidak menyentuh stok, valuasi, atau dokumen turunan lain. Setiap pembatalan otomatis dicatat di
`audit_logs` (aksi `auto_cancel_source`) + notifikasi bell, dengan alasan asal pembatalan.
Komitmen SPK dilepas oleh `spk_allocation_layer` (hook `spk_release_po`).
"""
from __future__ import annotations

from fastapi import Depends

INACTIVE_STATUS = {"cancelled", "canceled", "rejected"}
PO_PROJ = {"_id": 0, "id": 1, "status": 1, "approval_status": 1, "cancelled": 1, "deleted": 1}


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _is_inactive(doc: dict | None) -> bool:
    """Dokumen tidak lagi aktif (batal/ditolak/terhapus) menurut status yang dipakai transaksi."""
    if not doc:
        return True
    if doc.get("cancelled") is True or doc.get("deleted") is True:
        return True
    if _norm(doc.get("status")) in INACTIVE_STATUS:
        return True
    if _norm(doc.get("approval_status")) in INACTIVE_STATUS:
        return True
    return False


async def _active_po_ids(server, ids) -> set:
    ids = [x for x in set(ids) if x]
    if not ids:
        return set()
    rows = await server.db.po.find({"id": {"$in": ids}}, PO_PROJ).to_list(len(ids))
    return {r["id"] for r in rows if r.get("id") and not _is_inactive(r)}


async def _ro_line_ids(server, ro_id: str):
    rows = await server.db.ro_lines.find({"ro_id": ro_id}, {"_id": 0, "id": 1}).to_list(20000)
    return [r["id"] for r in rows if r.get("id")]


async def _ro_still_used(server, ro_id: str) -> bool:
    """True bila masih ada alokasi ke PO aktif pada salah satu baris RO ini."""
    line_ids = await _ro_line_ids(server, ro_id)
    if not line_ids:
        return False
    allocs = await server.db.allocations.find(
        {"source_line_id": {"$in": line_ids}, "target_type": "po"},
        {"_id": 0, "target_doc_id": 1, "qty": 1}).to_list(50000)
    if not allocs:
        return False
    active = await _active_po_ids(server, [a.get("target_doc_id") for a in allocs])
    return any(a.get("target_doc_id") in active and float(a.get("qty") or 0) > 0 for a in allocs)


async def _cancel_ro_if_unused(server, ro_id: str, user: dict, reason: str):
    ro = await server.db.ro.find_one({"id": ro_id}, {"_id": 0})
    if not ro or ro.get("cancelled") is True or ro.get("deleted") is True:
        return None
    if ro.get("submitted") is False:  # draf yang belum diajukan bukan urusan cascade
        return None
    if await _ro_still_used(server, ro_id):
        return None
    await server.db.ro.update_one({"id": ro_id}, {"$set": {
        "cancelled": True, "auto_cancelled_at": server.now_iso(), "auto_cancel_reason": reason}})
    await server.audit(user, "auto_cancel_source", "ro", ro_id, ro.get("no"), reason=reason)
    await server.notify("RO dibatalkan otomatis",
                        f"{ro.get('no')} dibatalkan karena {reason}", "approval", ro.get("division_id"))
    return ro.get("no") or ro_id


async def _mro_ro_ids(server, mro_id: str) -> set:
    rows = await server.db.allocations.find(
        {"source_doc_id": mro_id, "target_type": "ro"},
        {"_id": 0, "target_doc_id": 1}).to_list(20000)
    return {r.get("target_doc_id") for r in rows if r.get("target_doc_id")}


async def _mro_has_active_mi(server, mro_id: str) -> bool:
    rows = await server.db.allocations.find(
        {"source_doc_id": mro_id, "target_type": "mi"},
        {"_id": 0, "target_doc_id": 1}).to_list(20000)
    ids = [r.get("target_doc_id") for r in rows if r.get("target_doc_id")]
    if not ids:
        return False
    mis = await server.db.mi.find({"id": {"$in": list(set(ids))}},
                                  {"_id": 0, "id": 1, "status": 1, "cancelled": 1, "deleted": 1}).to_list(len(ids))
    return any(not _is_inactive(m) for m in mis)


async def _cancel_mro_if_unused(server, mro_id: str, user: dict, reason: str):
    mro = await server.db.mro.find_one({"id": mro_id}, {"_id": 0})
    if not mro or mro.get("cancelled") is True or mro.get("deleted") is True:
        return None
    if mro.get("submitted") is False:
        return None
    ro_ids = await _mro_ro_ids(server, mro_id)
    if not ro_ids:  # belum pernah ditarik ke RO: bukan urusan cascade
        return None
    ros = await server.db.ro.find({"id": {"$in": list(ro_ids)}},
                                  {"_id": 0, "id": 1, "cancelled": 1, "deleted": 1}).to_list(len(ro_ids))
    by_id = {r["id"]: r for r in ros if r.get("id")}
    if any(not (by_id.get(rid) or {}).get("cancelled") for rid in ro_ids):
        return None  # masih ada RO aktif
    if await _mro_has_active_mi(server, mro_id):
        return None  # barang sudah keluar gudang
    await server.db.mro.update_one({"id": mro_id}, {"$set": {
        "cancelled": True, "auto_cancelled_at": server.now_iso(), "auto_cancel_reason": reason}})
    await server.audit(user, "auto_cancel_source", "mro", mro_id, mro.get("no"), reason=reason)
    await server.notify("MRO dibatalkan otomatis",
                        f"{mro.get('no')} dibatalkan karena {reason}", "approval", mro.get("division_id"))
    return mro.get("no") or mro_id


async def cascade(server, po_id: str, user: dict, reason: str) -> dict:
    """Lepas alokasi PO lalu batalkan RO/MRO sumber yang sudah tidak dipakai (idempoten)."""
    po = await server.db.po.find_one({"id": po_id}, {"_id": 0})
    if not po or not _is_inactive(po):
        return {"skipped": "PO masih aktif"}

    allocs = await server.db.allocations.find(
        {"target_doc_id": po_id, "target_type": "po"},
        {"_id": 0, "source_doc_id": 1}).to_list(50000)
    ro_ids = sorted({a.get("source_doc_id") for a in allocs if a.get("source_doc_id")})
    if allocs:
        await server.db.allocations.delete_many({"target_doc_id": po_id, "target_type": "po"})

    ro_cancelled = []
    for rid in ro_ids:
        no = await _cancel_ro_if_unused(server, rid, user, reason)
        if no:
            ro_cancelled.append(no)

    mro_ids = set()
    for rid in ro_ids:
        rows = await server.db.allocations.find(
            {"target_doc_id": rid, "target_type": "ro"},
            {"_id": 0, "source_doc_id": 1}).to_list(20000)
        mro_ids |= {r.get("source_doc_id") for r in rows if r.get("source_doc_id")}
    mro_cancelled = []
    for mid in sorted(mro_ids):
        no = await _cancel_mro_if_unused(server, mid, user, reason)
        if no:
            mro_cancelled.append(no)

    return {"allocations_released": len(allocs), "ro_cancelled": ro_cancelled, "mro_cancelled": mro_cancelled}


async def _safe_cascade(server, po_id: str, user: dict, reason: str) -> dict:
    try:
        return await cascade(server, po_id, user, reason)
    except Exception as exc:  # aksi utama (batal/tolak) tidak boleh gagal karena cascade
        logger = getattr(server, "logger", None)
        if logger:
            logger.warning(f"cascade batal PO {po_id} gagal: {exc}")
        return {"error": str(exc)}


async def _release_spk(server, po_id: str, user: dict, reason: str) -> None:
    """Idempoten: rute reject/cancel langsung sudah melepas; inbox approval belum."""
    release = getattr(server, "spk_release_po", None)
    if release:
        try:
            await release(po_id, user, reason=reason)
        except Exception as exc:
            logger = getattr(server, "logger", None)
            if logger:
                logger.warning(f"release SPK PO {po_id} gagal: {exc}")


async def _finalize_reject(server, po_id: str, body: dict, user: dict, result):
    """Reject approver = PO batal final (bukan `Rejected` yang bisa diedit & diajukan ulang)."""
    reason = str((body or {}).get("reason") or "PO ditolak approver").strip()
    po = await server.db.po.find_one({"id": po_id}, {"_id": 0})
    if not po:
        return result
    if _norm(po.get("status")) in ("cancelled", "canceled"):
        return result
    await server.db.po.update_one({"id": po_id}, {"$set": {
        "status": "Cancelled", "cancelled": True, "approval_status": "Cancelled"}})
    await server.audit(user, "reject_cancel", "po", po_id, po.get("no"), reason=reason)
    await _release_spk(server, po_id, user, reason)
    info = await _safe_cascade(server, po_id, user, f"PO {po.get('no')} ditolak approver")
    if isinstance(result, dict):
        return {**result, "status": "Cancelled", "approval_status": "Cancelled", "cancelled": True,
                "document_status": "Cancelled", "cascade": info}
    return result


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def install(server):
    app = server.app

    # 1) Batalkan PO (tombol Batalkan): cascade setelah guard divisi/dokumen turunan + pelepasan SPK.
    path = "/api/po/{did}/cancel"
    route = _find_route(app, path, "POST")
    if route:
        original = route.endpoint
        app.router.routes.remove(route)

        async def cancel_cascade(did: str, body: dict = None, user=Depends(server.current_user)):
            result = await original(did, body or {}, user)
            reason = str((body or {}).get("reason") or "PO dibatalkan").strip()
            info = await _safe_cascade(server, did, user, reason)
            return {**result, "cascade": info} if isinstance(result, dict) else result

        app.add_api_route(path, cancel_cascade, methods=["POST"], tags=["po-cancel-cascade"])

    # 2) Reject dari halaman detail PO.
    path = "/api/po/{did}/reject"
    route = _find_route(app, path, "POST")
    if route:
        original = route.endpoint
        app.router.routes.remove(route)

        async def reject_cascade(did: str, body: dict = None, user=Depends(server.current_user)):
            result = await original(did, body or {}, user)
            return await _finalize_reject(server, did, body or {}, user, result)

        app.add_api_route(path, reject_cascade, methods=["POST"], tags=["po-cancel-cascade"])

    # 3) Reject dari inbox Approval (Approval 1 maupun Approval 2).
    path = "/api/approvals/{approval_id}/reject"
    route = _find_route(app, path, "POST")
    if route:
        original = route.endpoint
        app.router.routes.remove(route)

        async def inbox_reject_cascade(approval_id: str, body: dict = None, user=Depends(server.current_user)):
            task = await server.db.approval_tasks.find_one(
                {"id": approval_id}, {"_id": 0, "module": 1, "document_id": 1})
            result = await original(approval_id, body or {}, user)
            if task and task.get("module") == "po" and task.get("document_id"):
                return await _finalize_reject(server, task["document_id"], body or {}, user, result)
            return result

        app.add_api_route(path, inbox_reject_cascade, methods=["POST"], tags=["po-cancel-cascade"])
