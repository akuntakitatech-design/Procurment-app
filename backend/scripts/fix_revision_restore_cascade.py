"""Perbaikan sekali jalan (2026-11-11) — opsi A yang disetujui pemilik.

Konteks: 4 PO dibatalkan pada 09/11/2026 karena saat itu belum ada fitur "Minta Revisi".
Dua di antaranya sebenarnya REVISI, dua memang BATAL. Ruth lalu membuat PO pengganti untuk 3 di
antaranya. Agar tidak terjadi pemesanan ganda, PO pengganti ditutup saat PO asal dihidupkan.

Aksi:
1. RESTORE  PO/EW-PPPRE/137, PO/EW-PPPRE/139  -> status/approval `Revision`, cancelled=false,
   task approval -> Revision, catatan revisi + audit. Purchasing bisa Edit -> Submit ulang (level 1).
2. BATALKAN PO pengganti PO/EW-PPPRE/163, PO/EW-PPPRE/162 (dibuat 09/11 setelah PO asal dibatalkan)
   + lepas alokasinya (cascade), karena PO aslinya dihidupkan lagi.
3. CASCADE  PO/OMSS/148, PO/EW-PPPRE/140 (tetap batal): lepas alokasi RO->PO agar status RO/MRO
   akurat. RO yang masih dicakup PO aktif lain TIDAK dibatalkan (opsi A).

Jalankan dari folder `backend`:
    python scripts/fix_revision_restore_cascade.py            # dry-run (default, tidak menulis)
    python scripts/fix_revision_restore_cascade.py --apply    # menulis ke DB

Dry-run hanya membaca. Backup baris terdampak dibuat terpisah (lihat .tmp-verify/backup_fix_2026-11-11).
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
import po_cancel_cascade_layer as Cascade  # noqa: E402

ACTOR = {"email": "agustrnt@gmail.com", "name": "Imelda Pangaribuan", "role": "director", "divisions": []}

RESTORE = [
    ("PO/EW-PPPRE/137/XI/2026",
     "PO dikembalikan ke Perlu Revisi: pembatalan 09/11/2026 dilakukan karena fitur Minta Revisi "
     "belum tersedia. Silakan perbaiki lalu ajukan ulang approval."),
    ("PO/EW-PPPRE/139/XI/2026",
     "PO dikembalikan ke Perlu Revisi: pembatalan 09/11/2026 dilakukan karena fitur Minta Revisi "
     "belum tersedia. Silakan perbaiki lalu ajukan ulang approval."),
]
REPLACEMENT = [
    ("PO/EW-PPPRE/163/XI/2026", "PO/EW-PPPRE/137/XI/2026"),
    ("PO/EW-PPPRE/162/XI/2026", "PO/EW-PPPRE/139/XI/2026"),
]
GENUINE_CANCEL = [
    ("PO/OMSS/148/XI/2026", "PO dibatalkan (dikonfirmasi pemilik 11/11/2026): alokasi RO dilepas "
                            "agar status RO/MRO akurat."),
    ("PO/EW-PPPRE/140/XI/2026", "PO dibatalkan (dikonfirmasi pemilik 11/11/2026): alokasi RO dilepas "
                                "agar status RO/MRO akurat."),
]


async def _find_po(no: str):
    doc = await server.db.po.find_one({"no": no}, {"_id": 0})
    if not doc:
        raise SystemExit(f"PO tidak ditemukan: {no}")
    return doc


def _install_tenant_aware_hooks(tenant_id: str):
    """`server.audit/notify` dipakai cascade; untuk skrip raw DB, tenant_id harus diisi eksplisit."""

    async def audit(user, action, entity, entity_id, doc_no=None, before=None, after=None, reason=None):
        await server.db.audit_logs.insert_one({
            "id": server.gid(), "user": user.get("email"), "user_name": user.get("name"),
            "action": action, "entity": entity, "entity_id": entity_id, "doc_no": doc_no,
            "before": before, "after": after, "reason": reason, "at": server.now_iso(),
            "tenant_id": tenant_id,
        })

    async def notify(title, message, category, scope_division=None):
        await server.db.notifications.insert_one({
            "id": server.gid(), "title": title, "message": message, "category": category,
            "division": scope_division, "read": False, "at": server.now_iso(), "tenant_id": tenant_id,
        })

    server.audit = audit
    server.notify = notify


async def _restore_revision(po: dict, note: str, apply: bool) -> dict:
    pid = po["id"]
    entry = {"id": server.gid(), "level": 2, "by": ACTOR["name"], "by_email": ACTOR["email"],
             "at": server.now_iso(), "note": note}
    if apply:
        await server.db.po.update_one({"id": pid}, {
            "$set": {"status": "Revision", "approval_status": "Revision", "cancelled": False},
            "$push": {"revision_requests": entry}, "$inc": {"revision_count": 1}})
        await server.db.approval_tasks.update_many(
            {"module": "po", "document_id": pid},
            {"$set": {"status": "Revision", "note": note, "acted_at": server.now_iso()}})
        await server.db.po_approvals.update_many(
            {"po_id": pid}, {"$set": {"status": "Revision", "note": note, "acted_at": server.now_iso()}})
        await server.audit(ACTOR, "restore_revision", "po", pid, po.get("no"), reason=note)
        await server.notify("PO perlu revisi", f"{po.get('no')} dikembalikan ke Perlu Revisi. {note}",
                            "revision", po.get("division_id"))
    return {"po": po.get("no"), "action": "restore_revision"}


async def _cancel_po(po: dict, reason: str, apply: bool) -> dict:
    pid = po["id"]
    if apply:
        await server.db.po.update_one({"id": pid}, {"$set": {
            "status": "Cancelled", "cancelled": True, "approval_status": "Cancelled"}})
        await server.db.approval_tasks.update_many(
            {"module": "po", "document_id": pid, "status": {"$in": ["Pending", "Waiting"]}},
            {"$set": {"status": "Cancelled", "note": reason, "acted_at": server.now_iso()}})
        await server.db.po_approvals.update_many(
            {"po_id": pid, "status": {"$in": ["Pending", "Waiting"]}},
            {"$set": {"status": "Cancelled", "note": reason, "acted_at": server.now_iso()}})
        await server.audit(ACTOR, "cancel", "po", pid, po.get("no"), reason=reason)
        await server.notify("PO dibatalkan", f"{po.get('no')} dibatalkan. {reason}",
                            "approval", po.get("division_id"))
        info = await Cascade.cascade(server, pid, ACTOR, reason)
    else:
        info = {"dry_run": True}
    return {"po": po.get("no"), "action": "cancel", "cascade": info}


async def _cascade_existing(po: dict, reason: str, apply: bool) -> dict:
    info = await Cascade.cascade(server, po["id"], ACTOR, reason) if apply else {"dry_run": True}
    return {"po": po.get("no"), "action": "cascade_only", "cascade": info}


def _guard(po: dict, expected: str, label: str):
    status = str(po.get("status") or "").strip().lower()
    if status != expected.lower():
        raise SystemExit(f"{label}: status PO {po.get('no')} = {po.get('status')!r}, "
                         f"diharapkan {expected!r}. Dibatalkan agar data tidak salah ubah.")


async def main(apply: bool):
    print("MODE:", "APPLY (menulis ke DB)" if apply else "DRY-RUN (hanya membaca)")

    restore_pos, replacement_pos, genuine_pos = [], [], []
    for no, note in RESTORE:
        po = await _find_po(no)
        _guard(po, "Cancelled", "RESTORE")
        restore_pos.append((po, note))
    for no, source in REPLACEMENT:
        po = await _find_po(no)
        _guard(po, "Waiting Approval", "REPLACEMENT")
        replacement_pos.append((po, source))
    for no, reason in GENUINE_CANCEL:
        po = await _find_po(no)
        _guard(po, "Cancelled", "CASCADE")
        genuine_pos.append((po, reason))

    tenant_ids = {p.get("tenant_id") for p, _ in restore_pos + replacement_pos + genuine_pos}
    if len(tenant_ids) != 1:
        raise SystemExit(f"PO berasal dari tenant berbeda: {tenant_ids}")
    tenant_id = tenant_ids.pop()
    print("tenant:", tenant_id)
    _install_tenant_aware_hooks(tenant_id)

    results = []
    # 1) hidupkan PO yang sebenarnya revisi lebih dulu, agar RO tetap tercakup saat PO pengganti ditutup
    for po, note in restore_pos:
        results.append(await _restore_revision(po, note, apply))
    # 2) tutup PO pengganti + lepas alokasinya
    for po, source in replacement_pos:
        reason = (f"PO pengganti tidak diperlukan lagi: {source} dikembalikan ke Perlu Revisi.")
        results.append(await _cancel_po(po, reason, apply))
    # 3) PO yang memang batal: lepas alokasi agar status RO/MRO akurat
    for po, reason in genuine_pos:
        results.append(await _cascade_existing(po, reason, apply))

    print("\n--- hasil ---")
    for r in results:
        print(" ", r)

    print("\n--- status sekarang ---")
    for no, _ in RESTORE:
        po = await server.db.po.find_one({"no": no}, {"_id": 0})
        print(f"  {no}: status={po.get('status')} approval={po.get('approval_status')} "
              f"cancelled={po.get('cancelled')} revision_count={po.get('revision_count')} "
              f"catatan={(po.get('revision_requests') or [{}])[-1].get('note','')[:50]}")
    for no, _ in REPLACEMENT + GENUINE_CANCEL:
        po = await server.db.po.find_one({"no": no}, {"_id": 0})
        print(f"  {no}: status={po.get('status')} cancelled={po.get('cancelled')}")

    print("\n--- RO/MRO terdampak ---")
    for ro_no in ("RO/2026/11/00026", "RO/2026/11/00033", "RO/2026/11/00022", "RO/2026/11/00036"):
        ro = await server.db.ro.find_one({"no": ro_no}, {"_id": 0})
        lines = await server.db.ro_lines.find({"ro_id": ro["id"]}, {"_id": 0, "id": 1, "qty": 1}).to_list(500)
        ids = [x["id"] for x in lines]
        total = sum(float(x.get("qty") or 0) for x in lines)
        allocs = await server.db.allocations.find({"source_line_id": {"$in": ids}, "target_type": "po"},
                                                 {"_id": 0, "qty": 1, "target_doc_id": 1}).to_list(50000) if ids else []
        orderable = []
        for a in allocs:
            tgt = await server.db.po.find_one({"id": a.get("target_doc_id")},
                                             {"_id": 0, "no": 1, "status": 1, "approval_status": 1, "cancelled": 1})
            if tgt and not Cascade._is_inactive(tgt):
                orderable.append(float(a.get("qty") or 0))
        ordered = sum(orderable)
        status = "Fully Ordered" if total > 0 and ordered >= total else ("Partial Ordered" if ordered > 0 else "Open")
        print(f"  {ro_no}: cancelled={ro.get('cancelled')} qty={total} ordered_aktif={ordered} -> {status}")

    if not apply:
        print("\nDRY-RUN selesai — tidak ada perubahan. Jalankan ulang dengan --apply untuk menerapkan.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="tulis perubahan ke database")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
