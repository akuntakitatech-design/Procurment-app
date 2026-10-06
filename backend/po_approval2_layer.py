"""PO Approval Level 2 via Pengajuan Batch (manual external approval, mis. grup WhatsApp pimpinan).

Tidak membuat approval engine baru. Approval Level 1 tetap memakai approval_tasks + endpoint existing.
Khusus task PO seq=2 (Pending):
- tidak dapat di-approve/reject individual (diblok di approval_email_layer -> pesan APPROVAL2_ONLY_MSG);
- dikumpulkan ke batch `po_approval2_batches` (+ `po_approval2_batch_items` berisi snapshot data pengajuan);
- batch di-export JPEG (frontend) -> status Diajukan (export TIDAK meng-approve);
- bukti persetujuan pimpinan diunggah sekali ke batch (attachment engine existing, entity `po_approval2_batch`);
- "Approve Terpilih" memanggil approve_current() existing per PO (state identik dengan approval individual:
  approval_tasks + po_approvals + PO.status/approval_status + audit + notifikasi + SPK commitment),
  lalu membuat referensi lampiran (metadata baru, storage object yang sama) pada setiap PO yang di-approve.

Keamanan (urutan): tenant (proxy db) -> permission (po.view / po.approve / upload_attachment) -> assignment
(exact approver_email, sama seperti approval existing) -> division scope -> business rule.
Concurrency: MariaDB named lock per approval task (`pfa2:<task_id>`) + recheck di dalam lock.
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile

import division_visibility_layer as Division
import doc_procurement as DPM
import ro_source_lock as RS

ENTITY = "po_approval2_batch"
COLL_BATCH = "po_approval2_batches"
COLL_ITEM = "po_approval2_batch_items"
EVIDENCE_CATEGORY = "Bukti Approval 2"
LOCK_PREFIX = "pfa2:"
APPROVAL2_ONLY_MSG = "Approval Level 2 PO diproses melalui Pengajuan Approval 2."
EVIDENCE_EXT = {"jpg", "jpeg", "png", "webp", "pdf"}

ST_DRAFT, ST_SUBMITTED, ST_PARTIAL, ST_DONE = "Draft", "Diajukan", "Selesai Sebagian", "Selesai"
IT_PENDING, IT_APPROVED, IT_INACTIVE = "Pending", "Approved", "Tidak Aktif"
READY, SUBMITTED = "Siap Diajukan", "Sudah Diajukan"
MSG_NOT_FOUND = "Pengajuan Approval 2 tidak ditemukan"


def is_level2_po_task(task: dict | None) -> bool:
    return bool(task) and task.get("module") == "po" and int(task.get("seq") or 0) == 2


def _r2(v) -> float:
    return round(float(v or 0) + 0.0, 2)


def _norm(v) -> str:
    return str(v or "").strip().lower()


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _valid_date(v) -> str:
    s = str(v or "").strip()[:10]
    try:
        date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "Tanggal Pengajuan wajib diisi (format YYYY-MM-DD)")
    return s


def _cancelled(po: dict) -> bool:
    return bool(po.get("cancelled")) or _norm(po.get("status")) in {"cancelled", "canceled"}


def _waiting(po: dict) -> bool:
    return "waiting approval" in (_norm(po.get("status")), _norm(po.get("approval_status")))


def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731
    cu = server.current_user

    def need(user, key, verb):
        if not server.has_perm(user, key):
            raise HTTPException(403, f"Anda tidak memiliki izin untuk {verb}")

    def is_admin(user):
        return user.get("role") == "admin"

    def me(user):
        return _norm(user.get("email"))

    async def po_in_scope(user, po, task=None):
        """Division scope existing: divisi diizinkan ATAU user memang approver yang ditugaskan."""
        if not po:
            return False
        if Division._division_allowed(server, user, po.get("division_id")):
            return True
        if task is not None and _norm(task.get("approver_email")) == me(user):
            return True
        return str(po.get("id")) in await Division._assigned_approval_ids(server, "po", user)

    # ------------------------------------------------------------------ PIC (pembuat PO)
    async def resolve_pic(po: dict) -> str:
        name = str(po.get("created_by_name") or "").strip()
        if name:
            return name
        ref = str(po.get("created_by") or "").strip()
        if ref:
            u = await db().users.find_one({"$or": [{"email": ref.lower()}, {"email": ref}, {"id": ref}]},
                                          {"_id": 0, "name": 1, "email": 1})
            if u and (u.get("name") or u.get("email")):
                return u.get("name") or u.get("email")
        log = await db().audit_logs.find_one({"entity": "po", "entity_id": po.get("id"), "action": "create"},
                                             {"_id": 0, "user": 1, "user_name": 1})
        if log and (log.get("user_name") or log.get("user")):
            return log.get("user_name") or log.get("user")
        return ref or "-"

    # ------------------------------------------------------------------ snapshot pengajuan (backend = source of truth)
    async def po_snapshot(po: dict) -> dict:
        lines = await db().po_lines.find({"po_id": po["id"]}, {"_id": 0}).to_list(2000)
        out_lines, totals = DPM.compute_po_totals(po, lines)
        dpp = _r2(sum(float(x.get("dpp") or 0) for x in out_lines))
        ppn = _r2(totals["tax_total"])
        grand = _r2(totals["grand_total"])
        item_ids = list({l.get("item_id") for l in lines if l.get("item_id")})
        items = {i["id"]: i for i in await db().items.find({"id": {"$in": item_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(len(item_ids) + 1)} if item_ids else {}
        names, seen = [], set()
        for l in lines:
            n = str((items.get(l.get("item_id")) or {}).get("name") or l.get("item_name") or l.get("description") or "").strip()
            if n and n not in seen:
                seen.add(n); names.append(n)
        proj_ids = []
        for l in lines:
            pid = l.get("project_id") or po.get("default_project_id")
            if pid and pid not in proj_ids:
                proj_ids.append(pid)
        projs = {p["id"]: p for p in await db().projects.find({"id": {"$in": proj_ids}}, {"_id": 0, "id": 1, "name": 1, "code": 1}).to_list(len(proj_ids) + 1)} if proj_ids else {}
        proj_texts = []
        for pid in proj_ids:
            p = projs.get(pid) or {}
            t = str(p.get("name") or p.get("code") or "").strip()
            if t and t not in proj_texts:
                proj_texts.append(t)
        sup = await db().suppliers.find_one({"id": po.get("supplier_id")}, {"_id": 0, "name": 1}) or {}
        stored = po.get("grand_total")
        return {
            "po_id": po["id"], "po_no": po.get("no"), "po_date": po.get("date"),
            "supplier_name": sup.get("name") or "-",
            "transaction_description": ", ".join(names) or "-",
            "project_text": ", ".join(proj_texts) or "-",
            "dpp": dpp, "ppn": ppn, "grand_total": grand,
            "pic_name": await resolve_pic(po),
            "division_id": po.get("division_id"),
            "totals_consistent": stored is None or abs(float(stored or 0) - grand) < 0.5,
        }

    # ------------------------------------------------------------------ eligible tasks
    async def pending_l2_tasks(user, scope="mine"):
        q = {"module": "po", "seq": 2, "status": "Pending"}
        if not (is_admin(user) and scope == "all"):
            q["approver_email"] = me(user)
        return await db().approval_tasks.find(q, {"_id": 0}).to_list(5000)

    async def active_membership(task_ids):
        if not task_ids:
            return {}
        rows = await db()[COLL_ITEM].find({"approval_task_id": {"$in": list(task_ids)}, "status": IT_PENDING},
                                          {"_id": 0}).to_list(5000)
        return {r["approval_task_id"]: r for r in rows}

    @app.get("/api/approval2/po/eligible", tags=["approval2"])
    async def eligible(scope: str = Query("mine"), user=Depends(cu)):
        need(user, "po.view", "melihat PO")
        tasks = await pending_l2_tasks(user, scope)
        member = await active_membership([t["id"] for t in tasks])
        out = []
        for t in tasks:
            po = await db().po.find_one({"id": t.get("document_id")}, {"_id": 0})
            if not po or _cancelled(po) or not _waiting(po):
                continue
            if not await po_in_scope(user, po, t):
                continue
            snap = await po_snapshot(po)
            m = member.get(t["id"])
            out.append({**snap, "approval_task_id": t["id"], "approver_email": t.get("approver_email"),
                        "approver_name": t.get("approver_name"), "level": t.get("level"),
                        "can_approve": _norm(t.get("approver_email")) == me(user),
                        "submission_status": SUBMITTED if m else READY,
                        "batch_id": (m or {}).get("batch_id"), "batch_no": (m or {}).get("batch_no")})
        out.sort(key=lambda r: (r["submission_status"] != READY, str(r.get("po_no") or "")))
        return out

    # ------------------------------------------------------------------ batch helpers
    async def next_batch_no():
        now = server.now_iso()
        y, m = now[:4], now[5:7]
        res = await db().counters.find_one_and_update({"id": f"A2-{y}-{m}"}, {"$inc": {"seq": 1}},
                                                     upsert=True, return_document=True)
        return f"A2/{y}/{m}/{int((res or {}).get('seq') or 1):04d}"

    async def batch_items(batch_id):
        return await db()[COLL_ITEM].find({"batch_id": batch_id}, {"_id": 0}).sort("position", 1).to_list(5000)

    async def can_view_batch(user, batch, items=None):
        if is_admin(user) or _norm(batch.get("created_by")) == me(user):
            return True
        items = items if items is not None else await batch_items(batch["id"])
        ids = [i.get("approval_task_id") for i in items]
        if not ids:
            return False
        return bool(await db().approval_tasks.find_one({"id": {"$in": ids}, "approver_email": me(user)}, {"_id": 0, "id": 1}))

    async def load_batch(batch_id, user):
        need(user, "po.view", "melihat PO")
        b = await db()[COLL_BATCH].find_one({"id": str(batch_id or "").strip()}, {"_id": 0})
        if not b:
            raise HTTPException(404, MSG_NOT_FOUND)
        items = await batch_items(b["id"])
        if not await can_view_batch(user, b, items):
            raise HTTPException(404, MSG_NOT_FOUND)
        return b, items

    async def evidence_list(batch_id):
        return await db().attachments.find({"entity": ENTITY, "entity_id": batch_id, "is_deleted": False},
                                           {"_id": 0, "storage_path": 0}).sort("created_at", 1).to_list(200)

    async def live_items(user, items):
        tids = [i["approval_task_id"] for i in items]
        tasks = {t["id"]: t for t in await db().approval_tasks.find({"id": {"$in": tids}}, {"_id": 0}).to_list(5000)} if tids else {}
        out = []
        for it in items:
            t = tasks.get(it["approval_task_id"])
            status = it.get("status")
            if status == IT_PENDING and not (t and t.get("status") == "Pending"):
                status = IT_INACTIVE
            po = await db().po.find_one({"id": it["po_id"]}, {"_id": 0, "status": 1, "approval_status": 1, "division_id": 1, "id": 1})
            visible = bool(po) and await po_in_scope(user, po, t)
            row = {**it, "display_status": status, "po_status": (po or {}).get("status"),
                   "task_status": (t or {}).get("status"),
                   "can_approve": status == IT_PENDING and bool(t) and _norm(t.get("approver_email")) == me(user)}
            if not visible and not is_admin(user):
                continue
            out.append(row)
        return out

    def batch_totals(items):
        return {"po_count": len(items), "total_dpp": _r2(sum(i.get("dpp") or 0 for i in items)),
                "total_ppn": _r2(sum(i.get("ppn") or 0 for i in items)),
                "total_value": _r2(sum(i.get("grand_total") or 0 for i in items))}

    async def batch_view(user, b, items):
        rows = await live_items(user, items)
        return {**b, **batch_totals(items), "items": rows, "evidence": await evidence_list(b["id"]),
                "approved_count": sum(1 for r in rows if r["display_status"] == IT_APPROVED),
                "pending_count": sum(1 for r in rows if r["display_status"] == IT_PENDING)}

    # ------------------------------------------------------------------ create batch
    @app.post("/api/approval2/po/batches", tags=["approval2"])
    async def create_batch(body: dict, user=Depends(cu)):
        need(user, "po.view", "melihat PO")
        need(user, "po.approve", "mengajukan Approval 2 PO")
        body = body or {}
        title = re.sub(r"\s+", " ", str(body.get("title") or "")).strip()
        if not title:
            raise HTTPException(400, "Judul Pengajuan wajib diisi")
        if len(title) > 150:
            raise HTTPException(400, "Judul Pengajuan maksimal 150 karakter")
        sub_date = _valid_date(body.get("submission_date"))
        task_ids = []
        for t in body.get("approval_task_ids") or []:
            t = str(t or "").strip()
            if t and t not in task_ids:
                task_ids.append(t)
        if not task_ids:
            raise HTTPException(400, "Pilih minimal 1 PO untuk diajukan")

        async with RS.source_line_locks(server, task_ids, LOCK_PREFIX):
            rows = []
            for tid in task_ids:
                t = await db().approval_tasks.find_one({"id": tid}, {"_id": 0})
                if not is_level2_po_task(t) or t.get("status") != "Pending":
                    raise HTTPException(409, "Hanya PO dengan Approval Level 2 Pending yang dapat diajukan")
                if not is_admin(user) and _norm(t.get("approver_email")) != me(user):
                    raise HTTPException(403, f"Approval {t.get('document_no') or ''} ditugaskan ke user lain")
                po = await db().po.find_one({"id": t.get("document_id")}, {"_id": 0})
                if not po or not await po_in_scope(user, po, t):
                    raise HTTPException(404, "PO tidak ditemukan")
                if _cancelled(po) or not _waiting(po):
                    raise HTTPException(409, f"PO {po.get('no')} tidak lagi menunggu approval")
                await DPM.assert_po_unit_prices(po["id"])  # Harga Satuan wajib > 0
                rows.append((t, po))
            busy = await active_membership(task_ids)
            if busy:
                nos = ", ".join(sorted({f"{r.get('po_no')} ({r.get('batch_no')})" for r in busy.values()}))
                raise HTTPException(409, f"PO sudah berada pada Pengajuan Approval 2 aktif: {nos}")

            now = server.now_iso()
            bid = server.gid()
            no = await next_batch_no()
            batch = {"id": bid, "no": no, "title": title, "submission_date": sub_date, "status": ST_DRAFT,
                     "created_by": user.get("email"), "created_by_name": user.get("name") or user.get("email"),
                     "created_at": now, "submitted_at": None, "completed_at": None, "export_count": 0}
            items = []
            for pos, (t, po) in enumerate(rows):
                snap = await po_snapshot(po)
                items.append({"id": server.gid(), "batch_id": bid, "batch_no": no, "position": pos,
                              "approval_task_id": t["id"], "status": IT_PENDING, "approved_at": None,
                              "approved_by": None, "approved_by_email": None, "evidence_attachment_id": None,
                              "created_at": now, **snap})
            await db()[COLL_BATCH].insert_one(dict(batch))
            for it in items:
                await db()[COLL_ITEM].insert_one(dict(it))
        await server.audit(user, "create", ENTITY, bid, no, after={"title": title, "submission_date": sub_date,
                                                                    "po_count": len(items), **batch_totals(items)})
        for it in items:
            await server.audit(user, "add_po", ENTITY, bid, no, after={"po_id": it["po_id"], "po_no": it["po_no"],
                                                                      "approval_task_id": it["approval_task_id"]})
            await server.audit(user, "approval2_batch_add", "po", it["po_id"], it["po_no"],
                               after={"batch_id": bid, "batch_no": no})
        return await batch_view(user, batch, items)

    @app.get("/api/approval2/po/batches", tags=["approval2"])
    async def list_batches(user=Depends(cu)):
        need(user, "po.view", "melihat PO")
        rows = await db()[COLL_BATCH].find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
        out = []
        for b in rows:
            items = await batch_items(b["id"])
            if not await can_view_batch(user, b, items):
                continue
            live = await live_items(user, items)
            out.append({**b, **batch_totals(items),
                        "approved_count": sum(1 for r in live if r["display_status"] == IT_APPROVED),
                        "pending_count": sum(1 for r in live if r["display_status"] == IT_PENDING)})
        return out

    @app.get("/api/approval2/po/batches/{batch_id}", tags=["approval2"])
    async def get_batch(batch_id: str, user=Depends(cu)):
        b, items = await load_batch(batch_id, user)
        return await batch_view(user, b, items)

    @app.post("/api/approval2/po/batches/{batch_id}/submit", tags=["approval2"])
    async def submit_batch(batch_id: str, body: dict = None, user=Depends(cu)):
        """Dipanggil saat Export JPEG. Idempoten: tidak membuat batch baru & tidak mengubah approval."""
        b, items = await load_batch(batch_id, user)
        need(user, "po.approve", "mengajukan Approval 2 PO")
        patch = {"export_count": int(b.get("export_count") or 0) + 1, "last_exported_at": server.now_iso()}
        if b.get("status") == ST_DRAFT:
            patch.update({"status": ST_SUBMITTED, "submitted_at": server.now_iso()})
        await db()[COLL_BATCH].update_one({"id": b["id"]}, {"$set": patch})
        await server.audit(user, "export" if b.get("status") != ST_DRAFT else "submit", ENTITY, b["id"], b.get("no"),
                           after={"status": patch.get("status") or b.get("status"), "format": "jpeg",
                                  "export_count": patch["export_count"]})
        return await batch_view(user, {**b, **patch}, items)

    # ------------------------------------------------------------------ approve terpilih
    @app.post("/api/approval2/po/batches/{batch_id}/approve", tags=["approval2"])
    async def approve_batch(batch_id: str, body: dict = None, user=Depends(cu)):
        need(user, "po.approve", "menyetujui PO")
        b, items = await load_batch(batch_id, user)
        body = body or {}
        if b.get("status") == ST_DRAFT:
            raise HTTPException(409, "Pengajuan belum diajukan. Export JPEG terlebih dahulu.")
        wanted = [str(x).strip() for x in (body.get("item_ids") or []) if str(x).strip()]
        wanted = list(dict.fromkeys(wanted))
        if not wanted:
            raise HTTPException(400, "Pilih minimal 1 PO yang disetujui pimpinan")
        by_id = {i["id"]: i for i in items}
        sel = []
        for iid in wanted:
            it = by_id.get(iid)
            if not it:
                raise HTTPException(400, "PO terpilih bukan bagian dari pengajuan ini")
            sel.append(it)
        approve_current = getattr(server, "approval_approve_current", None)
        if approve_current is None:
            raise HTTPException(500, "Approval engine tidak tersedia")
        spk = getattr(server, "spk_po_approval_hooks", None) or {}
        task_ids = [i["approval_task_id"] for i in sel]
        approved = []
        async with RS.source_line_locks(server, task_ids, LOCK_PREFIX):
            # Pre-validasi SELURUH PO terpilih sebelum mutasi apa pun (tidak ada approve sebagian karena error).
            plan = []
            for it in sel:
                cur = await db()[COLL_ITEM].find_one({"id": it["id"]}, {"_id": 0})
                if not cur or cur.get("status") != IT_PENDING:
                    raise HTTPException(409, f"PO {it.get('po_no')} sudah diproses pada pengajuan ini")
                t = await db().approval_tasks.find_one({"id": it["approval_task_id"]}, {"_id": 0})
                if not is_level2_po_task(t) or t.get("status") != "Pending":
                    raise HTTPException(409, f"Approval Level 2 PO {it.get('po_no')} tidak lagi Pending")
                if _norm(t.get("approver_email")) != me(user):
                    raise HTTPException(403, f"Approval {it.get('po_no')} ditugaskan ke {t.get('approver_email') or 'user lain'}")
                po = await db().po.find_one({"id": it["po_id"]}, {"_id": 0})
                if not po or not await po_in_scope(user, po, t):
                    raise HTTPException(404, "PO tidak ditemukan")
                if _cancelled(po) or not _waiting(po) or _norm(po.get("status")) in {"approved", "rejected"}:
                    raise HTTPException(409, f"PO {po.get('no')} tidak lagi menunggu approval")
                current = await db().approval_tasks.find_one({"module": "po", "document_id": po["id"], "status": "Pending"},
                                                             {"_id": 0, "id": 1}, sort=[("seq", 1)])
                if not current or current["id"] != t["id"]:
                    raise HTTPException(409, f"Tahap approval PO {po.get('no')} berubah, muat ulang halaman")
                await DPM.assert_po_unit_prices(po["id"])  # Harga Satuan wajib > 0 (sebelum mutasi apa pun)
                final = bool(spk.get("would_be_final")) and await spk["would_be_final"](po["id"])
                if final and spk.get("guard"):
                    await spk["guard"](po["id"])  # HARD_BLOCK budget SPK, sama seperti approve individual
                plan.append((it, po, final))

            # Business rule (setelah tenant -> permission -> assignment -> division): bukti wajib ada.
            evidence = await evidence_list(b["id"])
            if not evidence:
                raise HTTPException(400, "Bukti Persetujuan Pimpinan wajib diunggah sebelum approve")
            ev_id = str(body.get("evidence_attachment_id") or "").strip() or evidence[-1]["id"]
            ev_full = await db().attachments.find_one({"id": ev_id, "entity": ENTITY, "entity_id": b["id"], "is_deleted": False}, {"_id": 0})
            if not ev_full:
                raise HTTPException(400, "Bukti Persetujuan tidak ditemukan pada pengajuan ini")

            for it, po, final in plan:
                await approve_current("po", po["id"], f"Approval 2 via batch {b.get('no')}", user)
                head = await db().po.find_one({"id": po["id"]}, {"_id": 0, "status": 1})
                if final and spk.get("commit") and (head or {}).get("status") == "Approved":
                    await spk["commit"](po["id"], user)
                now = server.now_iso()
                ref_id = server.gid()
                await db().attachments.insert_one({
                    "id": ref_id, "storage_path": ev_full.get("storage_path"),
                    "original_filename": ev_full.get("original_filename"), "content_type": ev_full.get("content_type"),
                    "size": ev_full.get("size"), "entity": "po", "entity_id": po["id"],
                    "category": EVIDENCE_CATEGORY, "note": f"Approval 2 Batch {b.get('no')}",
                    "source_attachment_id": ev_full.get("id"), "source_entity": ENTITY, "source_entity_id": b["id"],
                    "uploaded_by": user.get("name"), "uploaded_by_email": user.get("email"),
                    "is_deleted": False, "created_at": now})
                await db()[COLL_ITEM].update_one({"id": it["id"]}, {"$set": {
                    "status": IT_APPROVED, "approved_at": now, "approved_by": user.get("name") or user.get("email"),
                    "approved_by_email": user.get("email"), "evidence_attachment_id": ev_id, "po_attachment_id": ref_id}})
                await server.audit(user, "approval2_batch_approve", "po", po["id"], po.get("no"),
                                   reason=f"Approval 2 approved via batch {b.get('no')}",
                                   after={"batch_id": b["id"], "batch_no": b.get("no"), "evidence_attachment_id": ev_id,
                                          "po_attachment_id": ref_id, "approved_at": now})
                approved.append(it["po_no"])

            items = await batch_items(b["id"])
            pending = 0
            for i in items:
                if i.get("status") == IT_PENDING:
                    t = await db().approval_tasks.find_one({"id": i["approval_task_id"]}, {"_id": 0, "status": 1})
                    pending += 1 if (t or {}).get("status") == "Pending" else 0
            n_ok = sum(1 for i in items if i.get("status") == IT_APPROVED)
            status = ST_DONE if pending == 0 else (ST_PARTIAL if n_ok else b.get("status"))
            patch = {"status": status}
            if status == ST_DONE:
                patch["completed_at"] = server.now_iso()
            await db()[COLL_BATCH].update_one({"id": b["id"]}, {"$set": patch})
        await server.audit(user, "bulk_approve", ENTITY, b["id"], b.get("no"),
                           after={"approved_po": approved, "evidence_attachment_id": ev_id, "status": status})
        return await batch_view(user, {**b, **patch}, items)

    # ------------------------------------------------------------------ lampiran bukti (attachment engine existing)
    async def att_batch(entity_id, user):
        return await load_batch(entity_id, user)

    r_up = _find_route(app, "/api/attachments", "POST")
    if r_up:
        orig_up = r_up.endpoint
        app.router.routes.remove(r_up)

        async def upload(request: Request, file: UploadFile = File(...), entity: str = Form(...), entity_id: str = Form(...),
                         category: str = Form("Lainnya"), note: str = Form("")):
            if _norm(entity) != ENTITY:
                return await orig_up(request, file, entity, entity_id, category, note)
            user = await cu(request)
            server.require(user, "upload_attachment")
            need(user, "po.approve", "mengunggah bukti Approval 2")
            b, _items = await att_batch(entity_id, user)
            name = str(file.filename or "").rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in EVIDENCE_EXT:
                raise HTTPException(400, "Bukti Approval 2 harus berformat JPG, JPEG, PNG, WEBP, atau PDF")
            res = await orig_up(request, file, ENTITY, b["id"], EVIDENCE_CATEGORY, note)
            await server.audit(user, "upload_approval_evidence", ENTITY, b["id"], b.get("no"),
                               after={"file": name, "attachment_id": (res or {}).get("id")})
            return res
        app.add_api_route("/api/attachments", upload, methods=["POST"], tags=["approval2"])

    r_list = _find_route(app, "/api/attachments", "GET")
    if r_list:
        orig_list = r_list.endpoint
        app.router.routes.remove(r_list)

        async def list_att(entity: str, entity_id: str, user=Depends(cu)):
            if _norm(entity) == ENTITY:
                await att_batch(entity_id, user)
            return await orig_list(entity=entity, entity_id=entity_id, user=user)
        app.add_api_route("/api/attachments", list_att, methods=["GET"], tags=["approval2"])

    r_dl = _find_route(app, "/api/attachments/{aid}/download", "GET")
    if r_dl:
        orig_dl = r_dl.endpoint
        app.router.routes.remove(r_dl)

        async def download(aid: str, request: Request, auth: str = Query(None)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0, "entity": 1, "entity_id": 1})
            if rec and rec.get("entity") == ENTITY:
                await att_batch(rec["entity_id"], await cu(request))
            return await orig_dl(aid=aid, request=request, auth=auth)
        app.add_api_route("/api/attachments/{aid}/download", download, methods=["GET"], tags=["approval2"])

    r_del = _find_route(app, "/api/attachments/{aid}", "DELETE")
    if r_del:
        orig_del = r_del.endpoint
        app.router.routes.remove(r_del)

        async def delete_att(aid: str, user=Depends(cu)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0})
            if rec and rec.get("entity") == ENTITY:
                need(user, "po.approve", "menghapus bukti Approval 2")
                b, _items = await att_batch(rec["entity_id"], user)
                # Soft delete metadata saja: referensi pada PO yang sudah di-approve tetap utuh.
                await db().attachments.update_one({"id": aid}, {"$set": {"is_deleted": True, "deleted_by": user.get("email"),
                                                                       "deleted_at": server.now_iso()}})
                await server.audit(user, "delete_file", ENTITY, b["id"], b.get("no"), before={"file": rec.get("original_filename")})
                return {"ok": True}
            return await orig_del(aid=aid, user=user)
        app.add_api_route("/api/attachments/{aid}", delete_att, methods=["DELETE"], tags=["approval2"])

    # ------------------------------------------------------------------ audit trail batch
    r_audit = _find_route(app, "/api/audit", "GET")
    if r_audit:
        orig_audit = r_audit.endpoint
        app.router.routes.remove(r_audit)

        async def audit_list(entity: str = None, entity_id: str = None, limit: int = 300, user=Depends(cu)):
            if _norm(entity) == ENTITY and entity_id:
                await load_batch(entity_id, user)
                return await db().audit_logs.find({"entity": ENTITY, "entity_id": entity_id}, {"_id": 0}).sort("at", -1).to_list(min(int(limit or 300), 1000))
            return await orig_audit(entity=entity, entity_id=entity_id, limit=limit, user=user)
        app.add_api_route("/api/audit", audit_list, methods=["GET"], tags=["approval2"])
