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

LINE_COLL = {"mro": "mro_lines", "ro": "ro_lines", "po": "po_lines", "do": "do_lines", "mi": "mi_lines"}
HEAD_COLL = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi"}
# Inheritance source per target stage: RO<-MRO, PO<-RO, DO<-PO, MI<-DO
SRC_OF = {"ro": "mro", "po": "ro", "do": "po", "mi": "mro"}
DERIVED_TYPES = ("ro", "po", "do", "mi")  # stages that inherit allocation from upstream
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
        if source_type == "mi":
            raise HTTPException(409, "Alokasi MI bersifat read-only (diwarisi dari DO)")
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

        # remaining-only: alokasi manual pada stage turunan tidak boleh melebihi sisa dari source
        if not inherited and source_type in DERIVED_TYPES:
            avail = {a["spk_id"]: a["available"] for a in await _src_available(source_type, line_id, doc_id)}
            for c in clean:
                cap = avail.get(c["spk_id"])
                if cap is None:
                    raise HTTPException(400, "SPK ini tidak tersedia pada alokasi sumber (upstream) untuk item ini")
                if c["allocated_qty"] - cap > 1e-6:
                    sl = await _db().spk.find_one({"id": c["spk_id"]}, {"_id": 0, "spk_number": 1})
                    raise HTTPException(400, f"Alokasi SPK {sl.get('spk_number') if sl else ''} melebihi sisa yang tersedia dari sumber ({round(cap, 4)})".strip())

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
        """Source line id(s) untuk target line via koleksi db.allocations (lintas stage)."""
        src_type = SRC_OF.get(target_type)
        if not src_type:
            return []
        rows = await _db().allocations.find(
            {"target_line_id": target_line_id, "source_type": src_type}, {"_id": 0}).to_list(500)
        return [(r.get("source_line_id"), float(r.get("qty") or 0)) for r in rows if r.get("source_line_id")]

    async def _src_spk_ordered(target_type, target_line_id):
        """[(spk_id, total_source_alloc)] deterministik (urut created_at source) + daftar source line ids."""
        src_type = SRC_OF.get(target_type)
        src_line_ids = [sid for sid, _ in await _src_line_ids(target_type, target_line_id)]
        ordered, seen = [], {}
        if src_type:
            for sl in src_line_ids:
                for a in await _allocs(src_type, sl):
                    sp = a["spk_id"]
                    q = float(a.get("allocated_qty") or 0)
                    if sp in seen:
                        ordered[seen[sp]][1] += q
                    else:
                        seen[sp] = len(ordered)
                        ordered.append([sp, q])
        return [(sp, q) for sp, q in ordered], src_line_ids

    async def _src_available(target_type, target_line_id, exclude_doc_id):
        """Ketersediaan per SPK = alokasi source - dikonsumsi sibling (non-cancelled) selain doc ini."""
        ordered, src_line_ids = await _src_spk_ordered(target_type, target_line_id)
        out = []
        for sp, src_alloc in ordered:
            consumed = await _consumed_by_other(target_type, src_line_ids, sp, exclude_doc_id)
            out.append({"spk_id": sp, "source_allocated": round(src_alloc, 6),
                        "consumed_by_other": round(consumed, 6),
                        "available": round(max(0.0, src_alloc - consumed), 6)})
        return out

    async def _source_allocs_for_line(target_type, target_line):
        """Agregat alokasi SPK dari source line(s) (tanpa remaining-control) — util/debug."""
        ordered, _ = await _src_spk_ordered(target_type, target_line["id"])
        return {sp: q for sp, q in ordered}

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

    async def _per_source_spk(target_type, sources, exclude_doc_id):
        """RO konsolidasi (multi-MRO): SPK diwariskan PER SUMBER, dibatasi qty yang diambil
        dari masing-masing baris MRO, sehingga RO parsial tidak 'meminjam' SPK dari MRO
        yang tidak diambil. sources = [(source_line_id, qty_diambil)]."""
        src_type = SRC_OF.get(target_type)
        totals, order = {}, []
        for sl, taken in sources:
            rem = float(taken or 0)
            for a in await _allocs(src_type, sl):
                if rem <= 1e-9:
                    break
                sp = a["spk_id"]
                consumed = await _consumed_by_other(target_type, [sl], sp, exclude_doc_id)
                take = min(max(0.0, float(a.get("allocated_qty") or 0) - consumed), rem)
                if take > 1e-9:
                    if sp not in totals:
                        order.append(sp)
                    totals[sp] = totals.get(sp, 0.0) + take
                    rem -= take
        return [(sp, round(totals[sp], 6)) for sp in order]

    async def _inherit_line(target_type, doc_id, target_line, user):
        """Materialisasi alokasi target dari source: greedy SPK-first + remaining-only.

        - Konsumsi hanya ketersediaan tersisa per SPK (source - dikonsumsi sibling aktif).
        - Urutan deterministik (urut source). Non-SPK = sisa qty (derived, tidak disimpan).
        """
        if await _allocs(target_type, target_line["id"]):
            return  # sudah ada
        if target_type == "ro":
            srcs = await _src_line_ids("ro", target_line["id"])
            if len(srcs) > 1:
                picked = await _per_source_spk("ro", srcs, doc_id)
                items = [{"spk_id": sp, "allocated_qty": q} for sp, q in picked]
                if items:
                    await _set_line_allocations(target_type, doc_id, target_line["id"], items, user,
                                                inherited=True, enforce_active=False, reason="Inherited")
                return
        if target_type == "po":
            # PO dari RO terkonsolidasi: SPK per sumber RO yang benar-benar dikonsumsi (spk_split
            # pada allocation RO->PO, diisi po_ro_split_layer). PO lama (tanpa split) -> greedy.
            rows = await _db().allocations.find({"target_line_id": target_line["id"], "source_type": "ro"}, {"_id": 0}).to_list(500)
            if rows and all("spk_split" in r for r in rows):
                totals, order = {}, []
                for r in rows:
                    for x in r.get("spk_split") or []:
                        sp = x.get("spk_id")
                        if sp and float(x.get("qty") or 0) > 1e-9:
                            if sp not in totals:
                                order.append(sp)
                            totals[sp] = totals.get(sp, 0.0) + float(x.get("qty") or 0)
                items = [{"spk_id": sp, "allocated_qty": round(totals[sp], 6)} for sp in order]
                if items:
                    await _set_line_allocations(target_type, doc_id, target_line["id"], items, user,
                                                inherited=True, enforce_active=False, reason="Inherited")
                return
        avail = await _src_available(target_type, target_line["id"], doc_id)
        if not avail:
            return
        remaining = float(target_line.get("qty") or 0)
        items = []
        for a in avail:
            if remaining <= 1e-9:
                break
            take = min(a["available"], remaining)
            if take > 1e-9:
                items.append({"spk_id": a["spk_id"], "allocated_qty": round(take, 6)})
                remaining -= take
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
        # perubahan allocation inherited pada RO/PO/DO wajib alasan (audit trail)
        if source_type in ("ro", "po", "do") and await _allocs(source_type, line_id) and not reason:
            raise HTTPException(400, "Perubahan alokasi SPK (inherited) wajib menyertakan alasan")
        return await _set_line_allocations(source_type, doc_id, line_id, (body or {}).get("allocations", []),
                                           user, reason=reason)

    # ---- available (partial, remaining-only) untuk stage turunan PO/DO/MI ----
    @app.get("/api/spk-allocations/{source_type}/line/{line_id}/available", tags=["spk_allocation"])
    async def line_available(source_type: str, line_id: str, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        if source_type not in ("po", "do", "mi"):
            raise HTTPException(404, "available hanya untuk PO/DO/MI")
        line = await _line(source_type, line_id)
        if not line:
            raise HTTPException(404, "Item line tidak ditemukan")
        doc_id = line.get(f"{source_type}_id")
        rows = []
        for a in await _src_available(source_type, line_id, doc_id):
            lbl = await _spk_label(a["spk_id"])
            rows.append({**a, "spk_number": lbl.get("spk_number"),
                         "project_name": lbl.get("project_name"), "spk_status": lbl.get("status")})
        return {"source_type": source_type, "line_id": line_id,
                "qty": float(line.get("qty") or 0), "spk": rows}

    # ---- preview inherited allocation for an UNSAVED target line ----
    # Reuses the authoritative greedy SPK-first + remaining-only logic so the
    # frontend preview matches exactly what the backend will persist on save.
    @app.post("/api/spk-allocations/preview-inherit", tags=["spk_allocation"])
    async def preview_inherit(body: dict, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        target_type = (body or {}).get("target_type")
        src_type = SRC_OF.get(target_type)
        if not src_type:
            raise HTTPException(400, "target_type tidak valid untuk inheritance")
        sources = (body or {}).get("sources") or []
        # Aggregate SPK across source line(s), deterministic order (source created_at).
        ordered, seen, src_line_ids = [], {}, []
        for s in sources:
            sl = s.get("source_line_id") or s.get("line_id")
            if not sl:
                continue
            src_line_ids.append(sl)
            for a in await _allocs(src_type, sl):
                sp = a["spk_id"]; q = float(a.get("allocated_qty") or 0)
                if sp in seen:
                    ordered[seen[sp]][1] += q
                else:
                    seen[sp] = len(ordered); ordered.append([sp, q])
        total_qty = round(sum(float(s.get("qty") or 0) for s in sources), 6)
        remaining = total_qty
        allocations = []
        if target_type == "ro" and len(src_line_ids) > 1:
            pairs = [(s.get("source_line_id") or s.get("line_id"), float(s.get("qty") or 0)) for s in sources if (s.get("source_line_id") or s.get("line_id"))]
            for sp, q in await _per_source_spk("ro", pairs, (body or {}).get("exclude_doc_id")):
                lbl = await _spk_label(sp)
                allocations.append({"spk_id": sp, "spk_number": lbl.get("spk_number"),
                                    "project_name": lbl.get("project_name"), "allocated_qty": q})
                remaining -= q
            ordered = []  # per-source sudah dihitung; lewati greedy agregat di bawah
        for sp, src_alloc in ordered:
            if remaining <= 1e-9:
                break
            consumed = await _consumed_by_other(target_type, src_line_ids, sp, None)
            avail = max(0.0, src_alloc - consumed)
            take = min(avail, remaining)
            if take > 1e-9:
                lbl = await _spk_label(sp)
                allocations.append({"spk_id": sp, "spk_number": lbl.get("spk_number"),
                                    "project_name": lbl.get("project_name"),
                                    "allocated_qty": round(take, 6)})
                remaining -= take
        non_spk = max(0.0, round(total_qty - sum(a["allocated_qty"] for a in allocations), 6))
        return {"target_type": target_type, "item_qty": total_qty,
                "allocations": allocations, "non_spk_qty": non_spk}


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

    async def _budget_eval_for_amounts(per_spk, exclude_po_id=None):
        """Evaluasi budget per SPK dari peta {spk_id: amount} (source-of-truth tunggal).

        Dipakai oleh _evaluate_po_budget (PO tersimpan) dan preview-budget (PO belum
        tersimpan) agar perhitungan preview == commitment Approved. Budget & existing
        commitment SELALU diambil dari DB (tenant-scoped); frontend tidak dipercaya.
        """
        td = await _db().settings.find_one({"id": "procurement_budget_policy"}, {"_id": 0}) or {}
        tenant_def = {
            "default_global_budget_policy": td.get("default_global_budget_policy") or "HARD_BLOCK",
            "default_category_budget_policy": td.get("default_category_budget_policy") or "WARNING_ONLY",
        }
        import spk_layer
        result = []
        decisions = []
        for spk_id, amount in per_spk.items():
            spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
            if not spk:
                continue  # SPK tidak ada / tenant berbeda -> diabaikan
            budget = int(spk.get("procurement_budget") or 0)
            existing = await _spk_committed(spk_id, exclude_po_id=exclude_po_id)
            policy = spk_layer.effective_policy(spk, tenant_def)["global"]
            ev = spk_layer.evaluate_budget(existing, int(amount or 0), budget, policy)
            decisions.append(ev["decision"])
            result.append({
                "spk_id": spk_id, "spk_number": spk.get("spk_number"), "project_name": spk.get("project_name"),
                "current_procurement_budget": budget, "existing_commitment": existing, "po_amount": int(amount or 0),
                "projected_commitment": ev["projected_commitment"], "projected_remaining": ev["projected_remaining"],
                "over_by": ev["over_by"], "policy": policy, "status": ev["decision"],
            })
        blocked = any(d == "block" for d in decisions)
        warning = any(d == "warning" for d in decisions)
        return {"per_spk": result, "blocked": blocked, "warning": warning}

    async def _evaluate_po_budget(po_id):
        """Evaluasi budget per SPK untuk PO tersimpan (finalisasi & summary)."""
        per_spk, _ = await _po_spk_amounts(po_id)
        return await _budget_eval_for_amounts(per_spk, exclude_po_id=po_id)

    def _line_total_int_raw(line):
        """Nilai line (tax-inclusive) dari input mentah PO belum tersimpan.

        Mengikuti formula create_po EXACT: base = qty*price - discount; total = base + base*tax%.
        Dibulatkan ke rupiah integer sama seperti _line_total_int() agar preview == commitment.
        """
        qty = float(line.get("qty") or 0)
        price = float(line.get("price") or 0)
        disc = float(line.get("discount") or 0)
        tax = float(line.get("tax") or 0)
        base = qty * price - disc
        return int(round(base + base * tax / 100.0))

    def _amounts_from_lines(raw_lines, final_factor=1.0):
        """Agregasi nilai commitment per SPK dari line mentah (reuse _distribute).

        - Non-SPK = qty - total_spk (derived) dan TIDAK ikut agregasi SPK.
        - Distribusi proporsional qty largest-remainder -> sum rekonsiliasi eksak = nilai line.
        - final_factor: faktor Diskon Final level-PO (prorata), mengikuti compute_po_totals,
          agar preview == commitment setelah diskon final.
        """
        per_spk = {}
        for l in raw_lines or []:
            total_int = int(round(_line_total_int_raw(l) * (final_factor if final_factor and final_factor > 0 else 1.0)))
            qty = float(l.get("qty") or 0)
            allocs = []
            seen = set()
            for a in (l.get("allocations") or []):
                sid = (a.get("spk_id") or "").strip()
                aq = float(a.get("allocated_qty") or 0)
                if not sid or aq <= 0 or sid in seen:
                    continue
                seen.add(sid)
                allocs.append((sid, aq))
            spk_qty = sum(q for _, q in allocs)
            non_spk = max(0.0, qty - spk_qty)
            parts = list(allocs) + [("__nonspk__", non_spk)]
            dist = _distribute(total_int, parts)
            for sid, _q in allocs:
                per_spk[sid] = per_spk.get(sid, 0) + int(dist.get(sid, 0))
        return per_spk

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

    # ---- pre-save budget preview (PO belum tersimpan / sedang diedit) READ-ONLY ----
    # Zero-write: hanya validate -> calculate -> evaluate -> return. Reuse _distribute +
    # evaluate_budget persis seperti commitment Approved; budget & existing commitment
    # diambil dari DB (tenant-scoped). exclude_po_id dipakai saat edit Draft tersimpan.
    @app.post("/api/spk-allocations/po/preview-budget", tags=["spk_allocation"])
    async def preview_po_budget(body: dict, user=Depends(server.current_user)):
        server.require(user, PERM_VIEW)
        raw_lines = (body or {}).get("lines") or []
        exclude_po_id = (body or {}).get("exclude_po_id") or None
        # PO-level Final Discount (prorated) so preview matches the eventual commitment.
        _sub = 0.0
        for _l in raw_lines:
            _sub += max(0.0, float(_l.get("qty") or 0) * float(_l.get("price") or 0) - float(_l.get("discount") or 0))
        _fv = float((body or {}).get("final_discount_value") or 0)
        _ft = str((body or {}).get("final_discount_type") or "").lower()
        _fd = 0.0
        if _fv > 0 and _sub > 0:
            _fd = min(_sub, _sub * _fv / 100.0) if _ft in ("percent", "%", "persen", "pct") else min(_sub, _fv)
        _factor = ((_sub - _fd) / _sub) if _sub > 0 else 1.0
        per_spk = _amounts_from_lines(raw_lines, _factor)
        ev = await _budget_eval_for_amounts(per_spk, exclude_po_id=exclude_po_id)
        return {"status": "preview", "committed": False, **ev}

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

    # POST /api/do : inherit allocation dari PO (berdasarkan qty diterima; remaining-only)
    def _mk_create_do(original):
        async def create_do_inherit(body: dict, user=Depends(server.current_user)):
            result = await original(body, user)
            try:
                did = result.get("id") if isinstance(result, dict) else None
                if did:
                    for l in await _db().do_lines.find({"do_id": did}, {"_id": 0}).to_list(500):
                        await _inherit_line("do", did, l, user)
            except Exception as exc:
                server.logger.warning(f"CP4 DO inherit: {exc}")
            return result
        return create_do_inherit

    async def _consumed_from_do_line(do_line_id):
        """Qty do_line yang sudah dikonsumsi MI aktif (via lineage do->mi)."""
        rows = await _db().allocations.find(
            {"source_type": "do", "source_line_id": do_line_id, "target_type": "mi"}, {"_id": 0}).to_list(2000)
        s = 0.0
        for r in rows:
            mih = await _head("mi", r.get("target_doc_id"))
            if mih and not mih.get("cancelled") and mih.get("status") != "Cancelled":
                s += float(r.get("qty") or 0)
        return s

    async def _build_mi_do_lineage(mi_id):
        """Hubungkan MI line -> DO line (FIFO per item+gudang) sehingga MI mewarisi alokasi DO aktual.

        Tidak mengubah alur MI inti (stock/outstanding tetap pakai lineage mro->mi yang ada).
        """
        mi_lines = await _db().mi_lines.find({"mi_id": mi_id}, {"_id": 0}).to_list(500)
        for ml in mi_lines:
            existing = await _db().allocations.find(
                {"source_type": "do", "target_type": "mi", "target_line_id": ml["id"]}, {"_id": 0}).to_list(10)
            if existing:
                continue
            item_id = ml.get("item_id")
            wh = ml.get("warehouse_id")
            need = float(ml.get("qty") or 0)
            if need <= 0 or not item_id:
                continue
            cand = []
            for dl in await _db().do_lines.find({"item_id": item_id}, {"_id": 0}).to_list(3000):
                if wh and dl.get("warehouse_id") and dl.get("warehouse_id") != wh:
                    continue
                doh = await _head("do", dl.get("do_id"))
                if not doh or doh.get("cancelled") or doh.get("status") == "Cancelled":
                    continue
                cand.append(((doh.get("date") or doh.get("created_at") or ""), dl))
            cand.sort(key=lambda x: x[0])  # FIFO
            for _, dl in cand:
                if need <= 1e-9:
                    break
                remain = max(0.0, float(dl.get("qty") or 0) - await _consumed_from_do_line(dl["id"]))
                take = min(remain, need)
                if take > 1e-9:
                    await _db().allocations.insert_one({
                        "id": str(uuid.uuid4()), "source_type": "do", "source_line_id": dl["id"],
                        "source_doc_id": dl.get("do_id"), "target_type": "mi", "target_line_id": ml["id"],
                        "target_doc_id": mi_id, "qty": round(take, 6), "item_id": item_id, "at": _now()})
                    need -= take

    # POST /api/mi : bangun lineage MI->DO lalu inherit alokasi dari DO aktual (MI read-only)
    def _mk_create_mi(original):
        async def create_mi_inherit(body: dict, user=Depends(server.current_user)):
            result = await original(body, user)
            try:
                mid = result.get("id") if isinstance(result, dict) else None
                if mid:
                    await _build_mi_do_lineage(mid)
                    for l in await _db().mi_lines.find({"mi_id": mid}, {"_id": 0}).to_list(500):
                        await _inherit_line("mi", mid, l, user)
            except Exception as exc:
                server.logger.warning(f"CP4 MI inherit: {exc}")
            return result
        return create_mi_inherit

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

    server.spk_inherit_line = _inherit_line  # dipakai ro_consolidation_layer setelah edit RO
    _wrap("/api/ro", "POST", _mk_create_ro)
    _wrap("/api/po", "POST", _mk_create_po)
    _wrap("/api/do", "POST", _mk_create_do)
    _wrap("/api/mi", "POST", _mk_create_mi)
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
