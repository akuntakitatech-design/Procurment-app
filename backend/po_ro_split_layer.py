"""PO dari RO terkonsolidasi — 1 PO = 1 Divisi + 1 Supplier, split supplier / PO parsial.

Arsitektur (reuse, tanpa engine baru):
- Lineage RO -> PO tetap koleksi existing `allocations` (source_type="ro", target_type="po").
  Satu baris PO dapat mempunyai beberapa baris allocation ke baris RO yang sama — satu per
  *source allocation RO* (allocation MRO -> RO) yang dikonsumsi. Field tambahan (additive, JSON):
      via_alloc_id  : id allocation MRO->RO (sumber RO) yang dikonsumsi
      mro_line_id / mro_id : baris MRO asal
      spk_split     : [{spk_id, qty}] porsi SPK dari qty tersebut ("" = Non-SPK)
  -> PO item -> RO item -> RO source allocation -> MRO item -> SPK/Non-SPK dapat ditelusuri.
  alloc_out(ro_line, "po") (Sudah PO per baris RO) tidak berubah: tetap SUM qty allocation aktif.
- Allocation lama tanpa via_alloc_id (PO lama) tetap valid; untuk hitung sisa per sumber,
  qty-nya diatribusikan FIFO (urutan sumber deterministik) — PO lama tidak di-rewrite.
- Sisa dihitung ulang di backend saat simpan (create/edit), di dalam named lock MariaDB per
  baris RO (ro_source_lock, prefix 'pfpo:') -> aman lintas proses/worker.
- Tidak ada perubahan stok, valuasi, harga, kontrak, atau formula commitment SPK. SPK baris PO
  diwariskan per sumber (spk_allocation_layer membaca spk_split); commitment tetap mengikuti
  lifecycle PO existing (Approved).
"""
import contextvars

from fastapi import Depends, HTTPException

import uom_layer
from ro_source_lock import source_line_locks
from transaction_mutation_layer import _active_target

EPS = 1e-6
LOCK_PREFIX = "pfpo:"
SOURCE_NOT_FOUND = "Sumber RO tidak ditemukan atau tidak dapat diakses."
SUPPLIER_INVALID = "Supplier PO tidak ditemukan atau nonaktif."
NON_SPK = ""
_STAMP = contextvars.ContextVar("po_ro_alloc_stamp", default=None)


def _r(q):
    return round(float(q or 0), 6)


def _fmt(q):
    return f"{_r(q):g}"


def _find_route(app, path, method):
    for r in list(app.router.routes):
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set()):
            return r
    return None


def _wrap(app, path, method, make):
    r = _find_route(app, path, method)
    if r is None:
        return False
    app.router.routes.remove(r)
    app.add_api_route(path, make(r.endpoint), methods=[method], tags=["po-ro-split"])
    return True


def _allowed_divisions(server, user):
    if not user or server.is_global(user):
        return None
    return {str(x) for x in (user.get("divisions") or []) if x}


def _not_found():
    return HTTPException(404, SOURCE_NOT_FOUND)


def po_status_label(qty, ordered):
    qty, ordered = float(qty or 0), float(ordered or 0)
    if ordered <= EPS:
        return "Belum PO"
    if ordered + EPS < qty:
        return "PO Sebagian"
    return "Sudah PO Penuh"


# ============================================================ source state per baris RO
class _Ctx:
    """Cache per request (SPK label, head, master map)."""

    def __init__(self, server):
        self.server, self.db = server, server.db
        self.heads, self.spk_no, self.items = {}, {}, {}

    async def head(self, coll, hid):
        key = (coll, hid)
        if key not in self.heads:
            self.heads[key] = await getattr(self.db, coll).find_one({"id": hid}, {"_id": 0}) if hid else None
        return self.heads[key]

    async def spk_number(self, spk_id):
        if not spk_id:
            return "Non-SPK"
        if spk_id not in self.spk_no:
            s = await self.db.spk.find_one({"id": spk_id}, {"_id": 0, "spk_number": 1}) or {}
            self.spk_no[spk_id] = s.get("spk_number") or "SPK"
        return self.spk_no[spk_id]

    async def item(self, item_id):
        if item_id not in self.items:
            self.items[item_id] = await self.db.items.find_one({"id": item_id}, {"_id": 0}) or {}
        return self.items[item_id]


def _take_spk_first(avail, qty):
    """Ambil qty dari {spk: available} — SPK dulu (urutan dict), Non-SPK terakhir."""
    out, rem = {}, float(qty or 0)
    keys = [k for k in avail if k != NON_SPK] + ([NON_SPK] if NON_SPK in avail else [])
    for k in keys:
        if rem <= EPS:
            break
        t = min(max(0.0, avail.get(k, 0.0)), rem)
        if t > EPS:
            out[k] = out.get(k, 0.0) + t
            avail[k] = avail.get(k, 0.0) - t
            rem -= t
    return out, rem


async def ro_line_state(ctx, ro_line, exclude_doc_id=None):
    """Sumber (allocation MRO->RO) baris RO + komposisi SPK + konsumsi PO aktif lain.

    return {"sources": [...], "ordered_other": x, "remaining": y}
    source: {alloc_id, mro_id, mro_no, mro_line_id, project_id, unit_id, qty, comp{spk:qty},
             consumed{spk:qty}, avail{spk:qty}, sisa, sudah_po}
    """
    db = ctx.db
    rid = ro_line["id"]
    allocs = await db.allocations.find({"target_line_id": rid, "source_type": "mro"}, {"_id": 0}).to_list(500)
    srcs = []
    for a in allocs:
        ml = await db.mro_lines.find_one({"id": a.get("source_line_id")}, {"_id": 0}) or {}
        mh = await ctx.head("mro", a.get("source_doc_id") or ml.get("mro_id")) or {}
        srcs.append({"alloc_id": a.get("id"), "mro_id": mh.get("id") or a.get("source_doc_id"), "mro_no": mh.get("no"),
                     "mro_date": mh.get("date"), "mro_line_id": a.get("source_line_id"),
                     "project_id": ml.get("project_id"), "unit_id": ml.get("unit_id"),
                     "qty": float(a.get("qty") or 0), "_at": a.get("at") or ""})
    srcs.sort(key=lambda s: (str(s.get("mro_date") or ""), str(s.get("mro_no") or ""), str(s["_at"]), str(s["alloc_id"])))
    # komposisi SPK per sumber: dibatasi pool SPK baris RO, sesuai SPK baris MRO asal
    pool = {}
    for r in await db.procurement_item_spk_allocations.find({"source_type": "ro", "item_line_id": rid}, {"_id": 0}).sort("created_at", 1).to_list(200):
        pool[r.get("spk_id")] = pool.get(r.get("spk_id"), 0.0) + float(r.get("allocated_qty") or 0)
    if not srcs:  # baris RO manual (tanpa MRO) -> satu sumber semu
        srcs = [{"alloc_id": None, "mro_id": None, "mro_no": None, "mro_line_id": None, "project_id": ro_line.get("project_id"),
                 "unit_id": ro_line.get("unit_id"), "qty": float(ro_line.get("qty") or 0), "_at": ""}]
    for s in srcs:
        comp, rem = {}, s["qty"]
        mro_spk = []
        if s["mro_line_id"]:
            mro_spk = await db.procurement_item_spk_allocations.find({"source_type": "mro", "item_line_id": s["mro_line_id"]}, {"_id": 0}).sort("created_at", 1).to_list(200)
        else:
            mro_spk = [{"spk_id": k, "allocated_qty": v} for k, v in pool.items()]
        for a in mro_spk:
            sp = a.get("spk_id")
            t = min(pool.get(sp, 0.0), float(a.get("allocated_qty") or 0), rem)
            if t > EPS:
                comp[sp] = comp.get(sp, 0.0) + t
                pool[sp] -= t
                rem -= t
        if rem > EPS:
            comp[NON_SPK] = rem
        s["comp"] = comp
        s["consumed"] = {}
    by_id = {s["alloc_id"]: s for s in srcs if s["alloc_id"]}
    # konsumsi oleh PO aktif lain
    rows = await db.allocations.find({"source_line_id": rid, "source_type": "ro", "target_type": "po"}, {"_id": 0}).to_list(5000)
    ordered_other, legacy = 0.0, 0.0
    for a in rows:
        if exclude_doc_id and a.get("target_doc_id") == exclude_doc_id:
            continue
        if not await _active_target(ctx.server, a):
            continue
        q = float(a.get("qty") or 0)
        ordered_other += q
        s = by_id.get(a.get("via_alloc_id"))
        if s is None:
            legacy += q
            continue
        if a.get("spk_split"):
            for x in a["spk_split"]:
                k = x.get("spk_id") or NON_SPK
                s["consumed"][k] = s["consumed"].get(k, 0.0) + float(x.get("qty") or 0)
        else:
            avail = {k: v - s["consumed"].get(k, 0.0) for k, v in s["comp"].items()}
            took, _ = _take_spk_first(avail, q)
            for k, v in took.items():
                s["consumed"][k] = s["consumed"].get(k, 0.0) + v
    for s in srcs:  # PO lama tanpa atribusi sumber -> FIFO, SPK dulu
        avail = {k: v - s["consumed"].get(k, 0.0) for k, v in s["comp"].items()}
        if legacy > EPS:
            took, left = _take_spk_first(avail, legacy)
            for k, v in took.items():
                s["consumed"][k] = s["consumed"].get(k, 0.0) + v
            legacy = left
        s["avail"] = {k: max(0.0, v - s["consumed"].get(k, 0.0)) for k, v in s["comp"].items()}
        s["sisa"] = _r(sum(s["avail"].values()))
        s["sudah_po"] = _r(s["qty"] - s["sisa"])
    remaining = max(0.0, float(ro_line.get("qty") or 0) - ordered_other)
    return {"sources": srcs, "ordered_other": _r(ordered_other), "remaining": _r(remaining)}


async def describe_sources(ctx, state, m):
    """Bentuk tampilan (human readable) sumber RO."""
    out = []
    for s in state["sources"]:
        spk = []
        for k, v in s["comp"].items():
            spk.append({"spk_id": k or None, "spk_number": await ctx.spk_number(k), "qty": _r(v),
                        "available": _r(s["avail"].get(k, 0.0))})
        unit = m["units"].get(s.get("unit_id"), {}) or {}
        out.append({"ro_alloc_id": s["alloc_id"], "mro_id": s["mro_id"], "mro_no": s["mro_no"], "mro_line_id": s["mro_line_id"],
                    "project_id": s.get("project_id"), "project_name": m["projects"].get(s.get("project_id"), {}).get("name"),
                    "unit_id": s.get("unit_id"), "unit_name": unit.get("plate_no") or unit.get("name"),
                    "spk": spk, "spk_label": ", ".join(dict.fromkeys(x["spk_number"] for x in spk)) or "Non-SPK",
                    "ro_source_qty": _r(s["qty"]), "sudah_po": s["sudah_po"], "sisa": s["sisa"]})
    return out


# ============================================================ validasi simpan PO
async def _ro_line_checked(ctx, src, alw):
    db = ctx.db
    lid, rid = src.get("line_id") or src.get("ro_line_id"), src.get("ro_id")
    if not lid or not rid:
        raise HTTPException(400, "Sumber RO tidak valid (RO dan baris RO wajib)")
    rl = await db.ro_lines.find_one({"id": lid}, {"_id": 0})  # tenant-scoped proxy
    if not rl or rl.get("ro_id") != rid:
        raise _not_found()
    head = await ctx.head("ro", rid)
    if not head or (alw is not None and head.get("division_id") and head.get("division_id") not in alw):
        raise _not_found()  # di luar cakupan divisi = sama dengan tidak ada
    st = str(head.get("status") or "").lower()
    if head.get("cancelled") or st in ("cancelled", "canceled", "rejected") or head.get("approval_status") in ("Waiting Approval", "Rejected") \
            or head.get("submitted") is False:
        raise HTTPException(400, f"{head.get('no') or 'RO'} tidak aktif / belum disetujui sehingga tidak dapat ditarik ke PO")
    return rl, head


async def validate_po_body(server, body, did=None, user=None):
    """Hitung ulang sisa (di dalam lock) dan kembalikan rencana allocation per baris PO.

    Memodifikasi body: lines[].sources diganti hasil ekspansi per sumber RO (deterministik) dan
    division_id diisi dari RO bila kosong. return list stamp untuk create_alloc.
    """
    ctx = _Ctx(server)
    db = server.db
    alw = _allowed_divisions(server, user)
    raw_lines = body.get("lines") or []
    if did:
        await _restore_implicit_sources(ctx, did, raw_lines)
    normalized, _ = await uom_layer._normalize_body(server, body)
    nlines = normalized.get("lines") or []
    sourced = [i for i, l in enumerate(nlines) if l.get("sources")]
    supplier_id = body.get("supplier_id") or None
    for l in raw_lines:
        if l.get("supplier_id") and supplier_id and l.get("supplier_id") != supplier_id:
            raise HTTPException(400, "Satu PO hanya untuk satu Supplier. Buat PO terpisah untuk supplier lain.")
    if not sourced:
        return []
    if not supplier_id:
        raise HTTPException(400, "Supplier PO wajib dipilih (1 PO = 1 Divisi + 1 Supplier)")
    sup = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not sup or sup.get("is_active") is False or sup.get("active") is False:
        raise HTTPException(400, SUPPLIER_INVALID)
    division_id = body.get("division_id") or None
    states, ro_lines, taken_line = {}, {}, {}
    stamps = []
    for i in sourced:
        nl, rl_raw = nlines[i], raw_lines[i]
        line_qty = float(nl.get("qty") or 0)
        expanded, total = [], 0.0
        for s in nl.get("sources") or []:
            rl, head = await _ro_line_checked(ctx, s, alw)
            if rl.get("item_id") != nl.get("item_id"):
                raise HTTPException(400, f"Barang baris PO tidak sama dengan barang pada {head.get('no')}")
            hd = head.get("division_id")
            if division_id and hd and hd != division_id:
                raise HTTPException(400, f"Satu PO hanya untuk satu Divisi. {head.get('no')} berasal dari divisi lain.")
            division_id = division_id or hd
            if rl["id"] not in states:
                states[rl["id"]] = await ro_line_state(ctx, rl, did)
                ro_lines[rl["id"]] = (rl, head)
            st = states[rl["id"]]
            q = float(s.get("qty") or 0)
            if q <= EPS:
                continue
            via = s.get("ro_alloc_id")
            if via:
                cands = [x for x in st["sources"] if x["alloc_id"] == via]
                if not cands:
                    raise _not_found()
            else:  # proposal otomatis deterministik (urutan sumber RO)
                cands = list(st["sources"])
            rem = q
            for src in cands:
                if rem <= EPS:
                    break
                avail_total = sum(src["avail"].values())
                t = min(avail_total, rem) if not via else rem
                if via and t - avail_total > EPS:
                    raise HTTPException(400, f"Qty ke PO dari {src.get('mro_no') or head.get('no')} ({_fmt(t)}) melebihi Sisa sumber ({_fmt(avail_total)})")
                if t <= EPS:
                    continue
                split, left = _take_spk_first(src["avail"], t)
                if left > EPS:
                    raise HTTPException(400, f"Qty ke PO melebihi Sisa sumber {src.get('mro_no') or head.get('no')}")
                expanded.append({"ro_id": rl["ro_id"], "line_id": rl["id"], "qty": _r(t), "base_qty": _r(t),
                                 "ro_alloc_id": src["alloc_id"],
                                 "_stamp": {"via_alloc_id": src["alloc_id"], "mro_line_id": src["mro_line_id"], "mro_id": src["mro_id"],
                                            "spk_split": [{"spk_id": k or None, "qty": _r(v)} for k, v in split.items()]}})
                rem -= t
            if rem > EPS:
                raise HTTPException(400, f"Qty ke PO melebihi Sisa PO {head.get('no')} (sisa {_fmt(sum(sum(x['avail'].values()) for x in st['sources']))})")
            taken_line[rl["id"]] = taken_line.get(rl["id"], 0.0) + q
            if taken_line[rl["id"]] - st["remaining"] > EPS:
                raise HTTPException(400, f"Qty ke PO {_fmt(taken_line[rl['id']])} melebihi Sisa PO {head.get('no')} ({_fmt(st['remaining'])})")
            total += q
        if abs(total - line_qty) > 1e-4:
            raise HTTPException(400, f"Baris PO {i + 1}: total Rincian sumber RO ({_fmt(total)}) harus sama dengan Qty PO ({_fmt(line_qty)})")
        rl_raw["sources"] = [{k: v for k, v in e.items() if k != "_stamp"} for e in expanded]
        stamps.extend({"line_id": e["line_id"], "qty": e["qty"], "extra": e["_stamp"]} for e in expanded)
    if division_id and not body.get("division_id"):
        body["division_id"] = division_id
    return stamps


async def _restore_implicit_sources(ctx, did, raw_lines):
    """Edit tanpa `sources`: pertahankan allocation lama apa adanya bila qty sama; bila qty
    berubah wajib atur ulang rincian (tidak dipotong greedy diam-diam)."""
    for l in raw_lines:
        if l.get("sources") or not l.get("id"):
            continue
        old = await ctx.db.allocations.find({"target_line_id": l["id"], "target_doc_id": did, "source_type": "ro"}, {"_id": 0}).to_list(500)
        if not old:
            continue
        total_old = sum(float(a.get("qty") or 0) for a in old)
        cf = float(l.get("conversion_factor") or 1) or 1
        base = float(l.get("base_qty") if l.get("base_qty") is not None else float(l.get("qty") or 0) * cf)
        if abs(total_old - base) > 1e-4:
            raise HTTPException(400, f"Qty PO berubah ({_fmt(total_old)} -> {_fmt(base)}). Atur ulang Rincian sumber RO hingga seimbang.")
        l["sources"] = [{"ro_id": a.get("source_doc_id"), "line_id": a.get("source_line_id"), "qty": float(a.get("qty") or 0),
                         "base_qty": float(a.get("qty") or 0), "ro_alloc_id": a.get("via_alloc_id")} for a in old]


async def lock_ids(server, body, did=None):
    ids = {s.get("line_id") or s.get("ro_line_id") for l in (body or {}).get("lines") or [] for s in (l.get("sources") or []) if isinstance(s, dict)}
    if did:
        old = await server.db.allocations.find({"target_doc_id": did, "target_type": "po", "source_type": "ro"}, {"_id": 0}).to_list(5000)
        ids |= {a.get("source_line_id") for a in old}
    return {x for x in ids if x}


# ============================================================ install
def install(server):
    app = server.app
    import doc_procurement

    # --- create_alloc: tempel atribusi sumber RO pada allocation RO->PO yang dibuat engine existing
    base_create_alloc = server.create_alloc

    async def stamped_create_alloc(source_type, source_line_id, source_doc_id, target_type, target_line_id, target_doc_id, qty, item_id):
        queue = _STAMP.get()
        if queue and source_type == "ro" and target_type == "po":
            for i, e in enumerate(queue):
                if e["line_id"] == source_line_id and abs(float(e["qty"]) - float(qty or 0)) <= 1e-6:
                    queue.pop(i)
                    await server.db.allocations.insert_one({
                        "id": server.gid(), "source_type": source_type, "source_line_id": source_line_id,
                        "source_doc_id": source_doc_id, "target_type": target_type,
                        "target_line_id": target_line_id, "target_doc_id": target_doc_id,
                        "qty": qty, "item_id": item_id, "at": server.now_iso(), **e["extra"]})
                    return
        return await base_create_alloc(source_type, source_line_id, source_doc_id, target_type, target_line_id, target_doc_id, qty, item_id)

    server.create_alloc = stamped_create_alloc
    doc_procurement.create_alloc = stamped_create_alloc

    async def _inherit_spk(did, user):
        if not getattr(server, "spk_inherit_line", None):
            return
        try:
            for l in await server.db.po_lines.find({"po_id": did}, {"_id": 0}).to_list(2000):
                await server.spk_inherit_line("po", did, l, user)
        except Exception as exc:  # jangan gagalkan simpan PO
            server.logger.warning(f"PO split inherit SPK: {exc}")

    def mk_create(orig):
        async def create_po_split(body: dict, user=Depends(server.current_user)):
            async with source_line_locks(server, await lock_ids(server, body), LOCK_PREFIX):
                stamps = await validate_po_body(server, body, None, user)
                token = _STAMP.set(list(stamps))
                try:
                    result = await orig(body, user)
                finally:
                    _STAMP.reset(token)
            return result
        return create_po_split

    def mk_put(orig):
        async def put_transaction(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module != "po":
                return await orig(module, did, body, user)
            async with source_line_locks(server, await lock_ids(server, body, did), LOCK_PREFIX):
                stamps = await validate_po_body(server, body, did, user)
                token = _STAMP.set(list(stamps))
                try:
                    result = await orig(module, did, body, user)
                finally:
                    _STAMP.reset(token)
            await _inherit_spk(did, user)
            return result
        return put_transaction

    def mk_get_po(orig):
        async def get_po_split(did: str, user=Depends(server.current_user)):
            d = await orig(did, user)
            if not isinstance(d, dict):
                return d
            ctx = _Ctx(server)
            m = await doc_procurement.maps()
            for l in d.get("lines") or []:
                if not l.get("id"):
                    continue
                rows = await server.db.allocations.find({"target_line_id": l["id"], "source_type": "ro"}, {"_id": 0}).to_list(500)
                it = await ctx.item(l.get("item_id"))
                u = await server.db.uoms.find_one({"id": it.get("base_uom_id")}, {"_id": 0}) if it.get("base_uom_id") else None
                l["base_uom_id"] = it.get("base_uom_id")
                l["base_unit"] = (u or {}).get("code") or (u or {}).get("name") or it.get("unit")
                entries, states = [], {}
                for a in rows:
                    rl = await server.db.ro_lines.find_one({"id": a.get("source_line_id")}, {"_id": 0})
                    rh = await ctx.head("ro", a.get("source_doc_id")) or {}
                    if not rl:
                        continue
                    if rl["id"] not in states:
                        states[rl["id"]] = await ro_line_state(ctx, rl, did)
                    desc = {x["ro_alloc_id"]: x for x in await describe_sources(ctx, states[rl["id"]], m)}
                    src = desc.get(a.get("via_alloc_id")) or (next(iter(desc.values())) if len(desc) == 1 else {})
                    spk_lbl = None
                    if a.get("spk_split"):
                        spk_lbl = ", ".join(dict.fromkeys([await ctx.spk_number(x.get("spk_id") or "") for x in a["spk_split"]]))
                    entries.append({"ro_id": rh.get("id"), "ro_no": rh.get("no"), "line_id": rl["id"], "ro_alloc_id": a.get("via_alloc_id"),
                                    "mro_no": src.get("mro_no"), "mro_id": src.get("mro_id"),
                                    "project_name": src.get("project_name"), "unit_name": src.get("unit_name"),
                                    "spk_label": spk_lbl or src.get("spk_label") or "-",
                                    "ro_source_qty": src.get("ro_source_qty", _r(rl.get("qty"))),
                                    "sudah_po": src.get("sudah_po", states[rl["id"]]["ordered_other"]),
                                    "sisa": src.get("sisa", states[rl["id"]]["remaining"]),
                                    "qty": _r(a.get("qty")), "attributed": bool(a.get("via_alloc_id"))})
                l["ro_sources"] = entries
            return d
        return get_po_split

    def mk_get_ro(orig):
        async def get_ro_po_status(did: str, user=Depends(server.current_user)):
            d = await orig(did, user)
            if not isinstance(d, dict):
                return d
            for l in d.get("lines") or []:
                if l.get("id"):
                    ordered = await server.alloc_out(l["id"], "po")
                    l["po_ordered"] = _r(ordered)
                    l["po_remaining"] = _r(max(0.0, float(l.get("qty") or 0) - ordered))
                    l["po_status"] = po_status_label(l.get("qty"), ordered)
            return d
        return get_ro_po_status

    def mk_pull(orig):
        async def pull_ro_for_po_split(user=Depends(server.current_user)):
            rows = await orig(user=user)
            ctx = _Ctx(server)
            m = await doc_procurement.maps()
            show_price = server.has_perm(user, "view_purchase_price")
            contract_cache = {}
            resolve = getattr(server, "resolve_vendor_contract_price", None)
            out = []
            for r in rows or []:
                rl = await server.db.ro_lines.find_one({"id": r.get("line_id")}, {"_id": 0})
                if not rl:
                    continue
                head = await ctx.head("ro", rl.get("ro_id")) or {}
                import source_reservation_layer as _SR
                st = await ro_line_state(ctx, rl, _SR.excluded_doc("po"))
                it = await ctx.item(rl.get("item_id"))
                u = await server.db.uoms.find_one({"id": it.get("base_uom_id")}, {"_id": 0}) if it.get("base_uom_id") else None
                prim = m["suppliers"].get(it.get("primary_supplier_id"), {}) if it.get("primary_supplier_id") else {}
                if rl.get("item_id") not in contract_cache:
                    found = []
                    if resolve:
                        seen = set()
                        for ci in await server.db.vendor_contract_items.find({"item_id": rl.get("item_id")}, {"_id": 0}).to_list(500):
                            key = (ci.get("supplier_id"), ci.get("uom_id"))
                            if not ci.get("supplier_id") or key in seen:
                                continue
                            seen.add(key)
                            try:
                                res = await resolve(ci.get("supplier_id"), rl.get("item_id"), ci.get("uom_id"))
                            except Exception:
                                res = None
                            if res and not any(f["supplier_id"] == res.get("supplier_id") for f in found):
                                sup = m["suppliers"].get(res.get("supplier_id"), {})
                                if sup.get("is_active") is False:
                                    continue
                                found.append({"supplier_id": res.get("supplier_id"), "supplier_name": sup.get("name") or res.get("supplier_name"),
                                              "contract_number": res.get("contract_number"), "uom_name": res.get("uom_name"),
                                              "net_contract_price": res.get("net_contract_price") if show_price else None})
                    contract_cache[rl.get("item_id")] = found
                contracts = contract_cache[rl.get("item_id")]
                if contracts:
                    rec = {"supplier_id": contracts[0]["supplier_id"], "supplier_name": contracts[0]["supplier_name"], "source": "Kontrak Aktif"}
                elif prim:
                    rec = {"supplier_id": prim.get("id"), "supplier_name": prim.get("name"), "source": "Supplier Utama"}
                else:
                    rec = {"supplier_id": None, "supplier_name": None, "source": "Pilih Manual"}
                sources = await describe_sources(ctx, st, m)
                spk_lbl = ", ".join(dict.fromkeys(x for s in sources for x in s["spk_label"].split(", "))) or "Non-SPK"
                r.update({
                    "division_id": head.get("division_id"),
                    "division_name": m["divisions"].get(head.get("division_id"), {}).get("name"),
                    "base_uom_id": it.get("base_uom_id"),
                    "base_unit": (u or {}).get("code") or (u or {}).get("name") or it.get("unit") or rl.get("unit"),
                    "qty_ro_base": _r(rl.get("qty")), "ordered_base": st["ordered_other"], "outstanding_base": st["remaining"],
                    "po_status": po_status_label(rl.get("qty"), st["ordered_other"]),
                    "primary_supplier_id": prim.get("id"), "primary_supplier_name": prim.get("name"),
                    "contract_suppliers": contracts, "recommended_supplier": rec,
                    "sources": sources, "mro_nos": [s["mro_no"] for s in sources if s.get("mro_no")],
                    "mro_count": len({s["mro_id"] for s in sources if s.get("mro_id")}), "spk_label": spk_lbl,
                })
                out.append(r)
            return out
        return pull_ro_for_po_split

    _wrap(app, "/api/po", "POST", mk_create)
    _wrap(app, "/api/transactions/{module}/{did}", "PUT", mk_put)
    _wrap(app, "/api/po/{did}", "GET", mk_get_po)
    _wrap(app, "/api/ro/{did}", "GET", mk_get_ro)
    _wrap(app, "/api/pull/ro-for-po", "GET", mk_pull)
    server.logger.info("PO from consolidated RO (supplier split) layer installed")
