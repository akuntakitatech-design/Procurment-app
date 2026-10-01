"""CP4 — SPK Allocation Flow (MRO → RO → PO) + Budget Commitment.

Menghubungkan SPK dari level item MRO, diwariskan ke RO, lalu diverifikasi &
dikoreksi di PO; budget control & commitment baru dieksekusi di PO (harga final).

Prinsip kunci (dikunci sesuai keputusan user):
- Non-SPK adalah DEFAULT/remainder otomatis (derived): non_spk = item_qty - total_spk_alloc.
  User tidak membuat baris Non-SPK; tidak ada alasan Non-SPK.
- 1 item boleh 0..N SPK + optional Non-SPK remainder; item tetap 1 baris.
- MRO/RO TIDAK melakukan budget control. Budget hanya di PO (vendor+qty+unit price diketahui).
- Commitment tercatat 1x saat PO = Approved (idempotent); RELEASE saat PO Cancelled/Rejected
  (reject sebelum pernah commit = no-op). Draft/Waiting Approval tidak commit.
- HARD_BLOCK mencegah transisi yang menghasilkan PO Approved jika over-budget;
  WARNING_ONLY boleh lanjut dengan warning. Draft tetap boleh dibuat/diedit.
- Current Procurement Budget (post-Addendum CP2 = field procurement_budget) yang dipakai.
- Nilai per SPK = pembagian proporsional qty dari nilai line PO existing (line.total),
  largest-remainder agar sum persis = nilai line (tanpa selisih Rp1/Rp2). Non-SPK TIDAK commit.

Data model:
- procurement_item_spk_allocations : alokasi eksplisit per line (source_type mro/ro/po)
- spk_commitment_ledger            : event COMMIT / RELEASE / ADJUST (audit-friendly)

Permission: spk_allocation:view / :manage / :verify  (+ permission dokumen existing + status + tenant).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

PERM_VIEW = "spk_allocation:view"
PERM_MANAGE = "spk_allocation:manage"
PERM_VERIFY = "spk_allocation:verify"
NEW_PERMISSIONS = [PERM_VIEW, PERM_MANAGE, PERM_VERIFY]

LINE_COLL = {"mro": "mro_lines", "ro": "ro_lines", "po": "po_lines"}
HEAD_COLL = {"mro": "mro", "ro": "ro", "po": "po"}
PO_FINAL_STATUS = "Approved"
PO_ALLOC_EDITABLE = {"Draft", "Waiting Approval"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _distribute(total_int: int, parts: list) -> dict:
    """Bagi total_int ke parts [(key, qty)] proporsional qty, largest-remainder.

    Dijamin sum(hasil) == total_int (tanpa selisih rounding).
    """
    total_int = int(round(total_int or 0))
    tq = sum(float(q) for _, q in parts)
    if tq <= 0 or not parts:
        return {k: 0 for k, _ in parts}
    raw = [(k, (total_int * float(q)) / tq) for k, q in parts]
    out = {k: int(v) for k, v in raw}
    rem = total_int - sum(out.values())
    fr = sorted(((v - int(v), k) for k, v in raw), reverse=True)
    i = 0
    while rem > 0 and fr:
        out[fr[i % len(fr)][1]] += 1
        rem -= 1
        i += 1
    return out


def install(server):
    app = server.app

    # ---- register permissions mengikuti permission dokumen existing ----
    try:
        for p in NEW_PERMISSIONS:
            if p not in server.ALL_PERMISSIONS:
                server.ALL_PERMISSIONS.append(p)  # admin & director (=ALL_PERMISSIONS) otomatis dapat
        rd = server.ROLE_DEFAULTS
        for role, perms in list(rd.items()):
            if perms is server.ALL_PERMISSIONS:
                continue
            if "view" in perms and PERM_VIEW not in perms:
                perms.append(PERM_VIEW)
            # manage mengikuti hak edit dokumen (author MRO/RO/PO)
            if "edit" in perms and PERM_MANAGE not in perms:
                perms.append(PERM_MANAGE)
            # verify khusus Purchasing/Buyer + Manager (punya 'approve' atau 'submit'+'view_purchase_price')
            if role in ("manager", "purchasing") and PERM_VERIFY not in perms:
                perms.append(PERM_VERIFY)
    except Exception as exc:  # pragma: no cover
        server.logger.warning(f"SPK allocation permission registration: {exc}")

    def _db():
        return server.db

    # --------------------------------------------------------------- helpers
    def _find_route(path, method):
        for route in list(app.router.routes):
            if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
                return route
        return None

    async def _head(source_type, doc_id):
        return await getattr(_db(), HEAD_COLL[source_type]).find_one({"id": doc_id}, {"_id": 0})

    async def _line(source_type, line_id):
        return await getattr(_db(), LINE_COLL[source_type]).find_one({"id": line_id}, {"_id": 0})

    async def _allocs(source_type, line_id):
        return await _db().procurement_item_spk_allocations.find(
            {"source_type": source_type, "item_line_id": line_id}, {"_id": 0}).sort("created_at", 1).to_list(200)

    async def _spk_label(spk_id):
        s = await _db().spk.find_one({"id": spk_id}, {"_id": 0, "spk_number": 1, "project_name": 1, "customer": 1, "status": 1, "procurement_budget": 1})
        return s or {}

    async def _line_summary(source_type, line_id, *, line=None):
        line = line or await _line(source_type, line_id)
        if not line:
            raise HTTPException(404, "Item line tidak ditemukan")
        qty = float(line.get("qty") or 0)
        rows = await _allocs(source_type, line_id)
        enr = []
        total_spk = 0.0
        for r in rows:
            lbl = await _spk_label(r["spk_id"])
            total_spk += float(r.get("allocated_qty") or 0)
            enr.append({**r, "spk_number": lbl.get("spk_number"), "project_name": lbl.get("project_name"),
                        "customer": lbl.get("customer"), "spk_status": lbl.get("status")})
        non_spk = round(qty - total_spk, 6)
        return {
            "source_type": source_type, "item_line_id": line_id, "item_id": line.get("item_id"),
            "item_qty": qty, "unit": line.get("unit"),
            "allocations": enr, "total_spk_qty": round(total_spk, 6),
            "non_spk_qty": max(0.0, non_spk),
            "is_over": total_spk - qty > 1e-6,
        }

    def _require_doc_edit(user, source_type, head):
        """allocation:manage + hak edit dokumen + status + (tenant auto-scoped)."""
        server.require(user, PERM_MANAGE)
        server.require(user, "edit")
        if not head:
            raise HTTPException(404, "Dokumen tidak ditemukan")
        if head.get("cancelled") or head.get("status") == "Cancelled":
            raise HTTPException(409, "Dokumen dibatalkan; allocation tidak dapat diubah")
        if source_type == "po" and head.get("status") not in PO_ALLOC_EDITABLE:
            raise HTTPException(409, "Allocation PO hanya dapat diubah saat Draft / Waiting Approval")

    async def _set_line_allocations(source_type, doc_id, line_id, items, user, *, reason=None, inherited=False, enforce_active=True):
        line = await _line(source_type, line_id)
        if not line:
            raise HTTPException(404, "Item line tidak ditemukan")
        if line.get(HEAD_COLL[source_type] + "_id") not in (doc_id, None) and line.get(f"{source_type}_id") not in (doc_id, None):
            # pastikan line milik doc
            owner = line.get(f"{source_type}_id")
            if owner and owner != doc_id:
                raise HTTPException(400, "Item line bukan milik dokumen ini")
        qty = float(line.get("qty") or 0)
        # normalisasi + validasi
        clean = []
        total = 0.0
        seen = set()
        for it in items or []:
            sid = (it.get("spk_id") or "").strip()
            aq = float(it.get("allocated_qty") or 0)
            if not sid or aq <= 0:
                continue
            if sid in seen:
                raise HTTPException(400, "SPK duplikat pada satu item line")
            seen.add(sid)
            spk = await _db().spk.find_one({"id": sid}, {"_id": 0, "id": 1, "status": 1, "spk_number": 1})
            if not spk:
                raise HTTPException(400, "SPK tidak ditemukan / tenant berbeda")
            if enforce_active and not inherited and spk.get("status") != "active":
                raise HTTPException(400, f"Hanya SPK Active yang dapat dipilih (SPK {spk.get('spk_number')})")
            total += aq
            clean.append({"spk_id": sid, "allocated_qty": aq})
        if total - qty > 1e-6:
            raise HTTPException(400, f"Alokasi SPK melebihi Qty Item sebanyak {round(total - qty, 4)} {line.get('unit') or ''}".strip())

        before = await _allocs(source_type, line_id)
        before_map = {b["spk_id"]: b for b in before}
        now = _now()
        await _db().procurement_item_spk_allocations.delete_many({"source_type": source_type, "item_line_id": line_id})
        for c in clean:
            prev = before_map.get(c["spk_id"])
            await _db().procurement_item_spk_allocations.insert_one({
                "id": (prev or {}).get("id") or str(uuid.uuid4()),
                "source_type": source_type, "source_document_id": doc_id, "item_line_id": line_id,
                "item_id": line.get("item_id"), "spk_id": c["spk_id"], "allocated_qty": c["allocated_qty"],
                "inherited_from": (prev or {}).get("inherited_from") if not inherited else "inherit",
                "verified_by": (prev or {}).get("verified_by"), "verified_at": (prev or {}).get("verified_at"),
                "changed_reason": reason,
                "created_by": (prev or {}).get("created_by") or user.get("email"), "created_at": (prev or {}).get("created_at") or now,
                "updated_by": user.get("email"), "updated_at": now,
            })
        await server.audit(user, "edit" if before else "create", f"spk_allocation_{source_type}", line_id,
                           (await _head(source_type, doc_id) or {}).get("no"),
                           before={"alloc": [{"spk": b["spk_id"], "qty": b["allocated_qty"]} for b in before]},
                           after={"alloc": [{"spk": c["spk_id"], "qty": c["allocated_qty"]} for c in clean], "reason": reason})
        return await _line_summary(source_type, line_id, line=line)

    # ---------------- inheritance (materialize) ----------------
    async def _src_line_ids(target_type, target_line_id):
        """Source line id untuk target line via koleksi db.allocations (MRO->RO / RO->PO)."""
        src_type = "mro" if target_type == "ro" else "ro"
        rows = await _db().allocations.find(
            {"target_line_id": target_line_id, "source_type": src_type}, {"_id": 0}).to_list(500)
        return [(r.get("source_line_id"), float(r.get("qty") or 0)) for r in rows if r.get("source_line_id")]

    async def _source_allocs_for_line(target_type, target_line):
        """Kumpulkan alokasi SPK dari source line(s) (linkage via db.allocations)."""
        src_type = "mro" if target_type == "ro" else "ro"
        agg = {}
        for src_line_id, _q in await _src_line_ids(target_type, target_line["id"]):
            for a in await _allocs(src_type, src_line_id):
                agg[a["spk_id"]] = agg.get(a["spk_id"], 0.0) + float(a.get("allocated_qty") or 0)
        return agg

    async def _consumed_by_other(target_type, source_line_ids, spk_id, exclude_doc_id):
        """Qty spk_id yang sudah dialokasikan oleh dokumen target lain (non-cancelled) dari source line sama."""
        if not source_line_ids:
            return 0.0
        src_set = set(source_line_ids)
        rows = await _db().procurement_item_spk_allocations.find(
            {"source_type": target_type, "spk_id": spk_id}, {"_id": 0}).to_list(2000)
        used = 0.0
        for r in rows:
            if r.get("source_document_id") == exclude_doc_id:
                continue
            tl_src = {sid for sid, _ in await _src_line_ids(target_type, r["item_line_id"])}
            if tl_src & src_set:
                head = await _head(target_type, r.get("source_document_id"))
                if head and not head.get("cancelled") and head.get("status") not in ("Cancelled", "Rejected"):
                    used += float(r.get("allocated_qty") or 0)
        return used

    async def _inherit_line(target_type, doc_id, target_line, user):
        """Buat alokasi target dari source, di-cap ke qty line target (proporsional)."""
        if await _allocs(target_type, target_line["id"]):
            return  # sudah ada
        agg = await _source_allocs_for_line(target_type, target_line)
        if not agg:
            return
        qty = float(target_line.get("qty") or 0)
        total_src = sum(agg.values())
        parts = [(sid, q) for sid, q in agg.items()]
        if total_src <= qty + 1e-6:
            final = {sid: q for sid, q in parts}
        else:
            # cap proporsional ke qty line (largest remainder pada skala 1 unit)
            dist = _distribute(int(round(qty * 1000)), parts)  # presisi 3 desimal
            final = {k: v / 1000.0 for k, v in dist.items()}
        items = [{"spk_id": sid, "allocated_qty": q} for sid, q in final.items() if q > 0]
        if items:
            await _set_line_allocations(target_type, doc_id, target_line["id"], items, user,
                                        inherited=True, enforce_active=False, reason="Inherited")

    # =============================================================== ENDPOINTS
    @app.get("/api/spk-allocations/{source_type}/doc/{doc_id}", tags=["spk_allocation"])
    async def get_doc_allocations(source_type: str, doc_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        if source_type not in LINE_COLL:
            raise HTTPException(404, "source_type tidak valid")
        head = await _head(source_type, doc_id)
        if not head:
            raise HTTPException(404, "Dokumen tidak ditemukan")
        lines = await getattr(_db(), LINE_COLL[source_type]).find({f"{source_type}_id": doc_id}, {"_id": 0}).to_list(500)
        out = []
        for l in lines:
            out.append(await _line_summary(source_type, l["id"], line=l))
        return {"source_type": source_type, "doc_id": doc_id, "status": head.get("status"),
                "cancelled": bool(head.get("cancelled")), "lines": out,
                "can_manage": server.has_perm(user, PERM_MANAGE) and server.has_perm(user, "edit"),
                "can_verify": server.has_perm(user, PERM_VERIFY)}

    @app.get("/api/spk-allocations/{source_type}/line/{line_id}", tags=["spk_allocation"])
    async def get_line_allocation(source_type: str, line_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        if source_type not in LINE_COLL:
            raise HTTPException(404, "source_type tidak valid")
        return await _line_summary(source_type, line_id)

    @app.put("/api/spk-allocations/{source_type}/line/{line_id}", tags=["spk_allocation"])
    async def set_line_allocation(source_type: str, line_id: str, body: dict, user=Depends(server.current_user)):
        if source_type not in LINE_COLL:
            raise HTTPException(404, "source_type tidak valid")
        line = await _line(source_type, line_id)
        if not line:
            raise HTTPException(404, "Item line tidak ditemukan")
        doc_id = line.get(f"{source_type}_id")
        head = await _head(source_type, doc_id)
        _require_doc_edit(user, source_type, head)
        reason = (body or {}).get("reason")
        # perubahan allocation inherited pada RO/PO wajib alasan
        if source_type in ("ro", "po") and await _allocs(source_type, line_id) and not reason:
            raise HTTPException(400, "Perubahan alокаsi SPK (inherited) wajib menyertakan alasan")
        return await _set_line_allocations(source_type, doc_id, line_id, (body or {}).get("allocations", []),
                                           user, reason=reason)

    # ---- PO: available (partial) ----
    @app.get("/api/spk-allocations/po/line/{line_id}/available", tags=["spk_allocation"])
    async def po_line_available(line_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        line = await _line("po", line_id)
        if not line:
            raise HTTPException(404, "PO line tidak ditemukan")
        src_pairs = await _src_line_ids("po", line_id)
        src_line_ids = [sid for sid, _ in src_pairs]
        agg = {}
        for sid_line in src_line_ids:
            for a in await _allocs("ro", sid_line):
                agg[a["spk_id"]] = agg.get(a["spk_id"], 0.0) + float(a.get("allocated_qty") or 0)
        rows = []
        ro_qty = 0.0
        for sid_line in src_line_ids:
            rl = await _line("ro", sid_line)
            ro_qty += float((rl or {}).get("qty") or 0)
        for sid, ro_alloc in agg.items():
            consumed = await _consumed_by_other("po", src_line_ids, sid, line.get("po_id"))
            lbl = await _spk_label(sid)
            rows.append({"spk_id": sid, "spk_number": lbl.get("spk_number"), "project_name": lbl.get("project_name"),
                         "ro_allocated": round(ro_alloc, 6), "consumed_by_other_po": round(consumed, 6),
                         "available": round(max(0.0, ro_alloc - consumed), 6), "spk_status": lbl.get("status")})
        return {"po_line_id": line_id, "po_qty": float(line.get("qty") or 0), "ro_source_qty": ro_qty, "spk": rows}

    # ---- PO: verify allocation ----
    @app.post("/api/spk-allocations/po/{po_id}/verify", tags=["spk_allocation"])
    async def verify_po_allocation(po_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VERIFY)
        head = await _head("po", po_id)
        if not head:
            raise HTTPException(404, "PO tidak ditemukan")
        if head.get("status") not in PO_ALLOC_EDITABLE:
            raise HTTPException(409, "Verifikasi hanya saat PO Draft / Waiting Approval")
        now = _now()
        lines = await _db().po_lines.find({"po_id": po_id}, {"_id": 0}).to_list(500)
        warnings = []
        for l in lines:
            s = await _line_summary("po", l["id"], line=l)
            if s["is_over"]:
                raise HTTPException(400, "Masih ada line dengan alokasi melebihi Qty; perbaiki sebelum verify")
            for a in s["allocations"]:
                if a.get("spk_status") in ("closed", "cancelled"):
                    warnings.append(f"SPK {a.get('spk_number')} berstatus {a.get('spk_status')}")
        await _db().procurement_item_spk_allocations.update_many(
            {"source_type": "po", "source_document_id": po_id},
            {"$set": {"verified_by": user.get("email"), "verified_at": now}})
        await _db().po.update_one({"id": po_id}, {"$set": {"spk_allocation_verified": True,
            "spk_allocation_verified_by": user.get("email"), "spk_allocation_verified_at": now}})
        await server.audit(user, "approve", "spk_allocation_po", po_id, head.get("no"), after={"verified": True})
        return {"ok": True, "verified_by": user.get("email"), "verified_at": now, "warnings": warnings}

    # =============================================================== COMMITMENT
    def _line_total_int(line):
        return int(round(float(line.get("total") or 0)))

    async def _po_spk_amounts(po_id):
        """Hitung nilai commitment per SPK untuk sebuah PO (proporsional qty nilai line)."""
        lines = await _db().po_lines.find({"po_id": po_id}, {"_id": 0}).to_list(500)
        per_spk = {}
        detail = []
        for l in lines:
            total_int = _line_total_int(l)
            allocs = await _allocs("po", l["id"])
            qty = float(l.get("qty") or 0)
            spk_qty = sum(float(a.get("allocated_qty") or 0) for a in allocs)
            non_spk = max(0.0, qty - spk_qty)
            parts = [(a["spk_id"], float(a.get("allocated_qty") or 0)) for a in allocs]
            parts.append(("__nonspk__", non_spk))
            dist = _distribute(total_int, parts)
            for a in allocs:
                amt = dist.get(a["spk_id"], 0)
                per_spk[a["spk_id"]] = per_spk.get(a["spk_id"], 0) + amt
                detail.append({"po_line_id": l["id"], "item_id": l.get("item_id"), "spk_id": a["spk_id"],
                               "qty": float(a.get("allocated_qty") or 0), "amount": amt})
        return per_spk, detail

    async def _spk_committed(spk_id, exclude_po_id=None):
        rows = await _db().spk_commitment_ledger.find({"spk_id": spk_id}, {"_id": 0}).to_list(5000)
        bal = 0
        for r in rows:
            if exclude_po_id and r.get("po_id") == exclude_po_id:
                continue
            sgn = 1 if r.get("event") == "COMMIT" else (-1 if r.get("event") == "RELEASE" else 1)
            bal += sgn * int(r.get("amount") or 0)
        return bal

    async def _is_committed(po_id):
        rows = await _db().spk_commitment_ledger.find({"po_id": po_id}, {"_id": 0}).to_list(5000)
        bal = sum((1 if r.get("event") == "COMMIT" else -1) * int(r.get("amount") or 0)
                  for r in rows if r.get("event") in ("COMMIT", "RELEASE"))
        return bal > 0, rows

    async def _evaluate_po_budget(po_id):
        """Evaluasi budget per SPK untuk PO (dipakai saat finalisasi & untuk summary)."""
        td = await _db().settings.find_one({"id": "procurement_budget_policy"}, {"_id": 0}) or {}
        tenant_def = {
            "default_global_budget_policy": td.get("default_global_budget_policy") or "HARD_BLOCK",
            "default_category_budget_policy": td.get("default_category_budget_policy") or "WARNING_ONLY",
        }
        import spk_layer
        per_spk, _ = await _po_spk_amounts(po_id)
        result = []
        decisions = []
        for spk_id, amount in per_spk.items():
            spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
            if not spk:
                continue
            budget = int(spk.get("procurement_budget") or 0)
            existing = await _spk_committed(spk_id, exclude_po_id=po_id)
            policy = spk_layer.effective_policy(spk, tenant_def)["global"]
            ev = spk_layer.evaluate_budget(existing, amount, budget, policy)
            decisions.append(ev["decision"])
            result.append({
                "spk_id": spk_id, "spk_number": spk.get("spk_number"), "project_name": spk.get("project_name"),
                "current_procurement_budget": budget, "existing_commitment": existing, "po_amount": amount,
                "projected_commitment": ev["projected_commitment"], "projected_remaining": ev["projected_remaining"],
                "over_by": ev["over_by"], "policy": policy, "status": ev["decision"],
            })
        blocked = any(d == "block" for d in decisions)
        warning = any(d == "warning" for d in decisions)
        return {"per_spk": result, "blocked": blocked, "warning": warning}

    async def _commit_po(po_id, user):
        committed, _ = await _is_committed(po_id)
        if committed:
            return  # idempotent
        per_spk, detail = await _po_spk_amounts(po_id)
        head = await _head("po", po_id)
        now = _now()
        for d in detail:
            if d["amount"] <= 0:
                continue
            await _db().spk_commitment_ledger.insert_one({
                "id": str(uuid.uuid4()), "event": "COMMIT", "spk_id": d["spk_id"],
                "po_id": po_id, "po_no": (head or {}).get("no"), "po_line_id": d["po_line_id"],
                "item_id": d["item_id"], "qty": d["qty"], "amount": d["amount"],
                "reason": "PO Approved", "created_by": user.get("email"), "created_at": now})
        if per_spk:
            await server.audit(user, "approve", "spk_commitment", po_id, (head or {}).get("no"),
                               after={"committed": {k: v for k, v in per_spk.items()}})

    async def _release_po(po_id, user, reason="PO released"):
        committed, rows = await _is_committed(po_id)
        if not committed:
            return  # idempotent (belum pernah commit / sudah dilepas)
        head = await _head("po", po_id)
        now = _now()
        # jumlahkan net per (spk,line) dari COMMIT - RELEASE existing, lalu RELEASE sisanya
        net = {}
        for r in rows:
            key = (r.get("spk_id"), r.get("po_line_id"))
            sgn = 1 if r.get("event") == "COMMIT" else -1
            net[key] = net.get(key, 0) + sgn * int(r.get("amount") or 0)
        for (spk_id, line_id), amt in net.items():
            if amt <= 0:
                continue
            await _db().spk_commitment_ledger.insert_one({
                "id": str(uuid.uuid4()), "event": "RELEASE", "spk_id": spk_id,
                "po_id": po_id, "po_no": (head or {}).get("no"), "po_line_id": line_id,
                "amount": amt, "reason": reason, "created_by": user.get("email"), "created_at": now})
        await server.audit(user, "cancel", "spk_commitment", po_id, (head or {}).get("no"), reason=reason)

    async def _would_be_final_on_submit(po_id):
        head = await _db().po.find_one({"id": po_id}, {"_id": 0})
        approvers = await server.db.settings.find_one({"id": "approval_rules"}) or {}
        rules = approvers.get("rules", [])
        amount = (head or {}).get("grand_total", 0)
        req = []
        for rule in rules:
            if rule.get("max") is None or amount <= rule["max"]:
                req = rule.get("approvers", [])
                break
        return len(req) == 0

    async def _would_be_final_on_approve(po_id):
        nxt = await _db().po_approvals.find_one({"po_id": po_id, "status": "Waiting"}, sort=[("seq", 1)])
        return nxt is None

    async def _guard_hard_block(po_id):
        ev = await _evaluate_po_budget(po_id)
        if ev["blocked"]:
            over = [s for s in ev["per_spk"] if s["status"] == "block"]
            raise HTTPException(status_code=409, detail={
                "message": "HARD_BLOCK: PO melebihi Current Procurement Budget SPK. Finalisasi ditolak.",
                "over_budget": over})
        return ev

    # ---- budget summary endpoint (per SPK) untuk PO ----
    @app.get("/api/spk-allocations/po/{po_id}/budget-summary", tags=["spk_allocation"])
    async def po_budget_summary(po_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        head = await _head("po", po_id)
        if not head:
            raise HTTPException(404, "PO tidak ditemukan")
        ev = await _evaluate_po_budget(po_id)
        committed, _ = await _is_committed(po_id)
        return {"po_id": po_id, "status": head.get("status"), "committed": committed,
                "verified": bool(head.get("spk_allocation_verified")),
                "verified_by": head.get("spk_allocation_verified_by"),
                "verified_at": head.get("spk_allocation_verified_at"),
                **ev}

    @app.get("/api/spk-allocations/spk/{spk_id}/commitment", tags=["spk_allocation"])
    async def spk_commitment(spk_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        if not spk:
            raise HTTPException(404, "SPK tidak ditemukan")
        committed = await _spk_committed(spk_id)
        budget = int(spk.get("procurement_budget") or 0)
        ledger = await _db().spk_commitment_ledger.find({"spk_id": spk_id}, {"_id": 0}).sort("created_at", -1).to_list(2000)
        return {"spk_id": spk_id, "spk_number": spk.get("spk_number"),
                "current_procurement_budget": budget, "commitment": committed,
                "available_budget": budget - committed, "ledger": ledger}

    # =============================================================== WRAP PO ROUTES (commitment + inherit)
    def _wrap(path, method, make_wrapper):
        route = _find_route(path, method)
        if not route:
            server.logger.warning(f"CP4: route {method} {path} tidak ditemukan untuk wrapping")
            return
        original = route.endpoint
        app.router.routes.remove(route)
        wrapper = make_wrapper(original)
        app.add_api_route(path, wrapper, methods=[method], tags=["spk_allocation"])

    # POST /api/ro : inherit allocation dari MRO
    def _mk_create_ro(original):
        async def create_ro_inherit(body: dict, user=Depends(server.current_user)):
            result = await original(body, user)
            try:
                rid = result.get("id") if isinstance(result, dict) else None
                if rid:
                    for l in await _db().ro_lines.find({"ro_id": rid}, {"_id": 0}).to_list(500):
                        await _inherit_line("ro", rid, l, user)
            except Exception as exc:  # jangan gagalkan pembuatan RO
                server.logger.warning(f"CP4 RO inherit: {exc}")
            return result
        return create_ro_inherit

    # POST /api/po : inherit allocation dari RO (sebagai referensi, unverified)
    def _mk_create_po(original):
        async def create_po_inherit(body: dict, user=Depends(server.current_user)):
            result = await original(body, user)
            try:
                pid = result.get("id") if isinstance(result, dict) else None
                if pid:
                    for l in await _db().po_lines.find({"po_id": pid}, {"_id": 0}).to_list(500):
                        await _inherit_line("po", pid, l, user)
            except Exception as exc:
                server.logger.warning(f"CP4 PO inherit: {exc}")
            return result
        return create_po_inherit

    # POST /api/po/{did}/submit : HARD_BLOCK guard + commit bila jadi Approved
    def _mk_submit(original):
        async def submit_guard(did: str, user=Depends(server.current_user)):
            if await _would_be_final_on_submit(did):
                await _guard_hard_block(did)
            result = await original(did, user)
            head = await _db().po.find_one({"id": did}, {"_id": 0})
            if head and head.get("status") == PO_FINAL_STATUS:
                await _commit_po(did, user)
            return result
        return submit_guard

    # POST /api/po/{did}/approve : HARD_BLOCK guard pada langkah final + commit
    def _mk_approve(original):
        async def approve_guard(did: str, body: dict = None, user=Depends(server.current_user)):
            if await _would_be_final_on_approve(did):
                await _guard_hard_block(did)
            result = await original(did, body, user)
            head = await _db().po.find_one({"id": did}, {"_id": 0})
            if head and head.get("status") == PO_FINAL_STATUS:
                await _commit_po(did, user)
            return result
        return approve_guard

    def _mk_cancel(original):
        async def cancel_release(did: str, body: dict = None, user=Depends(server.current_user)):
            result = await original(did, body, user)
            await _release_po(did, user, reason=(body or {}).get("reason") or "PO cancelled")
            return result
        return cancel_release

    def _mk_reject(original):
        async def reject_release(did: str, body: dict = None, user=Depends(server.current_user)):
            result = await original(did, body, user)
            await _release_po(did, user, reason=(body or {}).get("reason") or "PO rejected")
            return result
        return reject_release

    _wrap("/api/ro", "POST", _mk_create_ro)
    _wrap("/api/po", "POST", _mk_create_po)
    _wrap("/api/po/{did}/submit", "POST", _mk_submit)
    _wrap("/api/po/{did}/approve", "POST", _mk_approve)
    _wrap("/api/po/{did}/cancel", "POST", _mk_cancel)
    _wrap("/api/po/{did}/reject", "POST", _mk_reject)

    # PO edit (transaction mutation) : bila PO Approved diedit & keluar dari Approved → release
    def _mk_tx_put(original):
        async def tx_put(module: str, did: str, body: dict, user=Depends(server.current_user)):
            was_committed = False
            if module == "po":
                was_committed, _ = await _is_committed(did)
            result = await original(module, did, body, user)
            if module == "po" and was_committed:
                head = await _db().po.find_one({"id": did}, {"_id": 0})
                if head and head.get("status") != PO_FINAL_STATUS:
                    await _release_po(did, user, reason="PO diedit setelah Approved")
            return result
        return tx_put
    _wrap("/api/transactions/{module}/{did}", "PUT", _mk_tx_put)

    server.logger.info("CP4 SPK Allocation + Budget Commitment layer installed")
