"""Unit test Minta Revisi & Tarik Approval (fake DB, tanpa jaringan/DB sungguhan).

Menguji `backend/po_revision_layer.py`:
- request-revision: izin, divisi, status, catatan wajib, kepemilikan tahap, penutupan task,
  status PO -> Revision, riwayat revision_requests, audit + notifikasi.
- revoke-approval: hanya admin/director, alasan wajib, guard dokumen turunan, PO tanpa approval,
  riwayat task lama -> Revoked, rantai baru level 1, mirror po_approvals dibuat ulang,
  PO kembali Waiting Approval, audit + notifikasi.

Jalankan: backend/.venv/Scripts/python.exe tests/po_revision_unit_test.py
"""
import asyncio
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import po_revision_layer as R  # noqa: E402

FAILS = []


def check(label, cond, extra=None):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond or extra is None else f"  -> {extra!r}"))
    if not cond:
        FAILS.append(label)


def expect_http(label, code, fn):
    try:
        fn()
    except HTTPException as e:
        check(label, e.status_code == code, f"HTTP {e.status_code}: {e.detail}")
        return e
    check(label, False, "tidak melempar HTTPException")
    return None


def _sorted(rows, sort):
    if not sort:
        return list(rows)
    pairs = sort if isinstance(sort, list) else [sort]
    out = list(rows)
    for key, direction in reversed(pairs):
        out.sort(key=lambda r: (r.get(key) is None, r.get(key) or 0, str(r.get(key) or "")),
                 reverse=(int(direction) == -1))
    return out


class Coll:
    def __init__(self, rows=None):
        self.rows = [deepcopy(r) for r in (rows or [])]

    @staticmethod
    def _match(doc, q):
        for k, v in (q or {}).items():
            if isinstance(v, dict):
                if "$in" in v and doc.get(k) not in v["$in"]:
                    return False
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
                if "$lt" in v and not (doc.get(k) is not None and doc.get(k) < v["$lt"]):
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def find_one(self, q, proj=None, sort=None):
        rows = _sorted([r for r in self.rows if self._match(r, q)], sort)
        return deepcopy(rows[0]) if rows else None

    def find(self, q, proj=None):
        return FindProxy(self, q)

    async def update_one(self, q, patch, upsert=False):
        for r in self.rows:
            if self._match(r, q):
                self._apply(r, patch)
                return
        if upsert:
            doc = {k: v for k, v in q.items() if not isinstance(v, dict)}
            self._apply(doc, patch)
            self.rows.append(doc)

    async def update_many(self, q, patch):
        for r in self.rows:
            if self._match(r, q):
                self._apply(r, patch)

    async def insert_one(self, doc):
        self.rows.append(deepcopy(doc))

    async def delete_many(self, q):
        self.rows = [r for r in self.rows if not self._match(r, q)]

    @staticmethod
    def _apply(doc, patch):
        for op, val in (patch or {}).items():
            if op == "$set":
                doc.update(deepcopy(val))
            elif op == "$push":
                for k, v in val.items():
                    doc.setdefault(k, []).append(deepcopy(v))
            elif op == "$inc":
                for k, v in val.items():
                    doc[k] = (doc.get(k) or 0) + v


class FindProxy:
    """Meniru cursor Motor: hanya butuh sort(...)/to_list(n)."""

    def __init__(self, coll, q):
        self.coll, self.q, self.sort_spec = coll, q, None

    def sort(self, key, direction=1):
        self.sort_spec = [(key, direction)]
        return self

    async def to_list(self, n=None):
        rows = _sorted([deepcopy(r) for r in self.coll.rows if Coll._match(r, self.q)], self.sort_spec)
        return rows[:n] if n else rows


class Server:
    def __init__(self):
        self.db = SimpleNamespace(
            po=Coll(), approval_tasks=Coll(), po_approvals=Coll(),
            allocations=Coll(), loan_returns=Coll(), notifications=Coll(), audit_logs=Coll(),
        )
        self.audits, self.notifs = [], []

    def now_iso(self):
        return "2026-11-11T03:00:00+00:00"

    def gid(self):
        return str(uuid4())

    def is_global(self, user):
        return user.get("role") in ("admin", "director", "purchasing") or user.get("scope") == "global"

    def has_perm(self, user, perm):
        return user.get("role") == "admin" or perm in (user.get("permissions") or [])

    async def audit(self, *a, **kw):
        self.audits.append({"args": a, "kw": kw})

    async def notify(self, *a, **kw):
        self.notifs.append({"args": a, "kw": kw})


# FindProxy sudah dipakai sejak awal (lihat definisi di atas), tidak perlu patch.

USER_L1 = {"id": "u1", "name": "Andi", "email": "andi@test", "role": "staff",
           "divisions": ["div1"], "permissions": ["approve"]}
USER_L2 = {"id": "u2", "name": "Budi", "email": "budi@test", "role": "staff",
           "divisions": ["div1"], "permissions": ["approve"]}
USER_ADMIN = {"id": "u9", "name": "Root", "email": "root@test", "role": "admin",
              "divisions": [], "permissions": []}
USER_PURCH = {"id": "u8", "name": "Sari", "email": "sari@test", "role": "purchasing",
              "divisions": ["div1"], "permissions": ["approve", "edit"]}


def seed(status="Waiting Approval", task_states=("Pending", "Waiting"), approved=False):
    s = Server()
    pid = "po-1"
    s.db.po.rows.append({"id": pid, "no": "PO/TEST/001", "status": status,
                         "approval_status": status, "division_id": "div1", "grand_total": 100000})
    for i, st in enumerate(task_states, start=1):
        task = {"id": f"t{i}", "module": "po", "document_type": "Purchase Order", "document_id": pid,
                "document_no": "PO/TEST/001", "seq": i, "level": i,
                "approver_user_id": f"u{i}", "approver_email": ["andi@test", "budi@test"][i - 1], "approver_name": f"User {i}",
                "status": st, "acted_by": "User" if st == "Approved" else None,
                "acted_by_email": None, "acted_at": None, "note": None}
        s.db.approval_tasks.rows.append(dict(task))
        po_task = {k: v for k, v in task.items() if k not in ("module", "document_type", "document_id", "document_no")}
        po_task.update({"po_id": pid, "role": None})
        s.db.po_approvals.rows.append(po_task)
    return s, pid


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    # ---------- request_revision ----------
    s, pid = seed()
    r = asyncio.get_event_loop().run_until_complete(
        R.request_revision(s, pid, {"note": "Harga item 2 belum sesuai penawaran"}, USER_L1))
    po = s.db.po.rows[0]
    check("revisi: respons ok", r.get("ok") is True and r.get("level") == 1, r)
    check("revisi: PO.status -> Revision", po.get("status") == "Revision" and po.get("approval_status") == "Revision", po)
    check("revisi: revision_requests tercatat", len(po.get("revision_requests") or []) == 1
          and po["revision_requests"][0]["note"].startswith("Harga item 2"), po.get("revision_requests"))
    check("revisi: revision_count = 1", po.get("revision_count") == 1, po.get("revision_count"))
    t1 = [t for t in s.db.approval_tasks.rows if t["id"] == "t1"][0]
    t2 = [t for t in s.db.approval_tasks.rows if t["id"] == "t2"][0]
    check("revisi: task aktif -> Revision + acted_by", t1["status"] == "Revision" and t1["acted_by"] == "Andi", t1)
    check("revisi: task menunggu lain ikut Revision", t2["status"] == "Revision", t2)
    m1 = [x for x in s.db.po_approvals.rows if x["id"] == "t1"][0]
    check("revisi: po_approvals mirror ikut Revision", m1["status"] == "Revision", m1)
    check("revisi: audit request_revision", s.audits and s.audits[-1]["args"][1] == "request_revision", s.audits[-1:])
    check("revisi: notifikasi revision", s.notifs and s.notifs[-1]["args"][2] == "revision", s.notifs[-1:])

    # level 2 meminta revisi (task Pending seq2)
    s2, pid2 = seed(task_states=("Approved", "Pending"))
    asyncio.get_event_loop().run_until_complete(
        R.request_revision(s2, pid2, {"note": "Mohon lampirkan quotation terbaru"}, USER_L2))
    check("revisi L2: task seq2 -> Revision", [t for t in s2.db.approval_tasks.rows if t["id"] == "t2"][0]["status"] == "Revision")
    check("revisi L2: riwayat L1 tetap Approved", [t for t in s2.db.approval_tasks.rows if t["id"] == "t1"][0]["status"] == "Approved")
    check("revisi L2: level catatan = 2", s2.db.po.rows[0]["revision_requests"][0]["level"] == 2)

    # validasi
    s3, pid3 = seed()
    expect_http("revisi: tanpa izin approve -> 403", 403,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abcdef"}, {**USER_L1, "permissions": []})))
    expect_http("revisi: catatan < 5 karakter -> 400", 400,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abc"}, USER_L1)))
    s3.db.po.rows[0].update({"status": "Draft", "approval_status": None})
    expect_http("revisi: PO Draft -> 409 (status)", 409,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abcdef"}, USER_L1)))
    s3.db.po.rows[0].update({"status": "Cancelled", "cancelled": True, "approval_status": "Approved"})
    expect_http("revisi: PO cancelled -> 409", 409,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abcdef"}, USER_L1)))
    s3.db.po.rows[0].update({"status": "Waiting Approval", "cancelled": False,
                             "approval_status": "Waiting Approval", "division_id": "div2"})
    expect_http("revisi: divisi lain -> 403", 403,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abcdef"}, USER_L1)))
    s3.db.po.rows[0].update({"division_id": "div1"})
    expect_http("revisi: bukan approver tahap aktif -> 403", 403,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abcdef"}, {**USER_L2, "email": "budi@test"})))
    s3.db.approval_tasks.rows = []
    expect_http("revisi: tanpa tahap approval -> 400", 400,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, pid3, {"note": "abcdef"}, USER_L1)))
    expect_http("revisi: PO tidak ada -> 404", 404,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.request_revision(s3, "tidak-ada", {"note": "abcdef"}, USER_ADMIN)))

    # ---------- revoke_approval ----------
    s4, pid4 = seed(status="Approved", task_states=("Approved", "Approved"), approved=True)
    old_ids = [t["id"] for t in s4.db.approval_tasks.rows]
    r4 = asyncio.get_event_loop().run_until_complete(
        R.revoke_approval(s4, pid4, {"reason": "Nilai PO berubah setelah negosiasi"}, USER_ADMIN))
    po4 = s4.db.po.rows[0]
    tasks4 = s4.db.approval_tasks.rows
    check("tarik: respons Waiting Approval", r4.get("ok") is True and r4.get("status") == "Waiting Approval", r4)
    check("tarik: PO kembali Waiting Approval", po4["status"] == "Waiting Approval"
          and po4["approval_status"] == "Waiting Approval", po4)
    check("tarik: riwayat approval_revocations", len(po4.get("approval_revocations") or []) == 1
          and po4["approval_revocations"][0]["reason"].startswith("Nilai PO"), po4.get("approval_revocations"))
    old_rows = [t for t in tasks4 if t["id"] in old_ids]
    check("tarik: 2 task lama -> Revoked", len(old_rows) == 2 and all(t["status"] == "Revoked" for t in old_rows), old_rows)
    new_rows = [t for t in tasks4 if t["id"] not in old_ids]
    check("tarik: rantai baru 2 task", len(new_rows) == 2, new_rows)
    pend = [t for t in new_rows if t["status"] == "Pending"]
    wait = [t for t in new_rows if t["status"] == "Waiting"]
    check("tarik: level 1 Pending & level 2 Waiting",
          len(pend) == 1 and len(wait) == 1 and pend[0]["seq"] == 1 and wait[0]["seq"] == 2, new_rows)
    check("tarik: susunan approver dipertahankan",
          [t["approver_email"] for t in sorted(new_rows, key=lambda x: x["seq"])] == ["andi@test", "budi@test"],
          [t["approver_email"] for t in new_rows])
    check("tarik: po_approvals dibuat ulang (2 baris, seq unik)",
          len(s4.db.po_approvals.rows) == 2
          and sorted((x["seq"], x["status"]) for x in s4.db.po_approvals.rows) == [(1, "Pending"), (2, "Waiting")],
          s4.db.po_approvals.rows)
    check("tarik: audit revoke_approval", s4.audits and s4.audits[-1]["args"][1] == "revoke_approval", s4.audits[-1:])

    # revoke pada PO yang baru L1 approve (status masih Waiting Approval)
    s5, pid5 = seed(task_states=("Approved", "Pending"))
    asyncio.get_event_loop().run_until_complete(
        R.revoke_approval(s5, pid5, {"reason": "Salah approver level 1"}, USER_ADMIN))
    check("tarik L1: rantai baru level 1 Pending", len([t for t in s5.db.approval_tasks.rows if t["status"] == "Pending"]) == 1)
    check("tarik L1: approval lama Revoked", len([t for t in s5.db.approval_tasks.rows if t["status"] == "Revoked"]) == 2)

    # validasi revoke
    s6, pid6 = seed(status="Approved", task_states=("Approved", "Approved"))
    expect_http("tarik: role purchasing -> 403", 403,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.revoke_approval(s6, pid6, {"reason": "abcdef"}, USER_PURCH)))
    expect_http("tarik: alasan < 5 karakter -> 400", 400,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.revoke_approval(s6, pid6, {"reason": "abc"}, USER_ADMIN)))

    orig_blockers = R.TML._blockers
    async def fake_blockers(server, module, did):
        return [{"type": "DO", "id": "do-1", "no": "DO/TEST/01"}]
    R.TML._blockers = fake_blockers
    try:
        e = expect_http("tarik: PO sudah dipakai DO -> 409", 409,
                        lambda: asyncio.get_event_loop().run_until_complete(
                            R.revoke_approval(s6, pid6, {"reason": "abcdef"}, USER_ADMIN)))
        check("tarik: pesan menyebut DO", e is not None and "DO/TEST/01" in str(e.detail), e and e.detail)
    finally:
        R.TML._blockers = orig_blockers

    s7, pid7 = seed(status="Draft", task_states=())
    expect_http("tarik: PO Draft tanpa approval -> 409", 409,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.revoke_approval(s7, pid7, {"reason": "abcdef"}, USER_ADMIN)))

    s8, pid8 = seed(status="Waiting Approval", task_states=("Pending", "Waiting"))
    expect_http("tarik: belum ada approval diberikan -> 400", 400,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.revoke_approval(s8, pid8, {"reason": "abcdef"}, USER_ADMIN)))

    s9, pid9 = seed(status="Approved", task_states=("Approved", "Approved"))
    s9.db.approval_tasks.rows = []
    expect_http("tarik: PO tanpa tahap approval -> 400", 400,
                lambda: asyncio.get_event_loop().run_until_complete(
                    R.revoke_approval(s9, pid9, {"reason": "abcdef"}, USER_ADMIN)))

    print()
    if FAILS:
        print(f"GAGAL: {len(FAILS)} -> {FAILS}")
        return 1
    print("SEMUA UNIT TEST LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
