"""RO Consolidation — Multi MRO / Multi SPK.

Satu baris RO (Permintaan Pembelian) boleh mengonsolidasikan kebutuhan beberapa baris MRO
dengan Divisi + Barang yang sama (MRO/SPK/Proyek/Unit boleh berbeda). Breakdown sumber TIDAK
disimpan di tabel baru: memakai koleksi existing `allocations` (source_type="mro",
source_line_id=baris MRO, target_type="ro", target_line_id=baris RO, qty), yang sudah dipakai
remaining-control MRO, mutation/reversal, dan pewarisan SPK. Tidak ada migrasi schema.

Layer ini (dipasang sebelum access_control_layer, sehingga tenant -> izin -> divisi tetap
dievaluasi lebih dulu) menambahkan:
- Validasi server saat simpan (POST /api/ro & PUT /api/transactions/ro/{id}):
  * satu RO = satu Divisi; seluruh MRO sumber wajib berdivisi sama dengan RO;
  * barang sumber = barang baris RO; MRO sumber aktif (submitted, tidak batal);
  * sum(alokasi sumber) = Qty RO per baris;
  * total alokasi per baris MRO (lintas baris RO dokumen ini) <= sisa MRO
    (Qty MRO - alokasi RO aktif lain; RO batal/ditolak tidak dihitung -> sisa kembali).
- GET /api/ro/{id}: setiap baris membawa `sources` (MRO, SPK, Proyek, Unit/Aset, Divisi,
  Qty MRO, Sudah RO, Sisa, Qty ke RO) berlabel human-readable.
- GET /api/pull/mro-for-ro: tambahan field divisi, tanggal MRO, label SPK, satuan dasar.
RO tidak menyentuh stok/valuasi. Supplier tidak dipakai sebagai kunci grouping.
"""
from fastapi import Depends, HTTPException

import uom_layer
from ro_source_lock import mro_line_locks
from transaction_mutation_layer import _allocated_elsewhere

EPS = 1e-6
# Satu pesan generik untuk sumber MRO yang tidak ada / tenant lain / di luar cakupan divisi user,
# agar response tidak membedakan "record ada di tenant/divisi lain" dengan "record tidak ada".
SOURCE_NOT_FOUND = "Sumber MRO tidak ditemukan atau tidak dapat diakses."


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
    app.add_api_route(path, make(r.endpoint), methods=[method], tags=["ro-consolidation"])
    return True


def _fmt(q):
    q = round(float(q or 0), 6)
    return f"{q:g}"


async def _spk_breakdown(server, mro_line):
    """[(label, qty)] SPK baris MRO + sisa Non-SPK (derived)."""
    db = server.db
    qty = float(mro_line.get("qty") or 0)
    rows = await db.procurement_item_spk_allocations.find(
        {"source_type": "mro", "item_line_id": mro_line["id"]}, {"_id": 0}).to_list(200)
    out, total = [], 0.0
    for r in rows:
        spk = await db.spk.find_one({"id": r.get("spk_id")}, {"_id": 0, "spk_number": 1}) or {}
        q = float(r.get("allocated_qty") or 0)
        total += q
        out.append({"spk_id": r.get("spk_id"), "spk_number": spk.get("spk_number") or "SPK", "qty": round(q, 6)})
    non = round(qty - total, 6)
    return out, max(0.0, non)


def _spk_label(spks, non_spk):
    names = [s["spk_number"] for s in spks]
    if non_spk > EPS or not names:
        names.append("Non-SPK")
    return ", ".join(dict.fromkeys(names))


async def _base_unit(server, item_id, cache):
    if item_id in cache:
        return cache[item_id]
    db = server.db
    it = await db.items.find_one({"id": item_id}, {"_id": 0}) or {}
    u = await db.uoms.find_one({"id": it.get("base_uom_id")}, {"_id": 0}) if it.get("base_uom_id") else None
    label = (u or {}).get("symbol") or (u or {}).get("code") or (u or {}).get("name") or it.get("unit") or ""
    cache[item_id] = {"base_uom_id": it.get("base_uom_id"), "base_unit": label}
    return cache[item_id]


def _not_found():
    return HTTPException(404, SOURCE_NOT_FOUND)


def _allowed_divisions(server, user):
    """None = semua divisi (global); set = cakupan divisi user (sama dengan access_control_layer)."""
    if not user or server.is_global(user):
        return None
    return {str(x) for x in (user.get("divisions") or []) if x}


def body_source_line_ids(body):
    return [s.get("line_id") or s.get("mro_line_id") for l in (body or {}).get("lines") or []
            for s in (l.get("sources") or []) if isinstance(s, dict)]


async def lock_line_ids(server, body, did=None):
    """Baris MRO yang wajib dikunci: sumber di body + (edit) sumber lama dokumen ini."""
    ids = set(x for x in body_source_line_ids(body) if x)
    if did:
        old = await server.db.allocations.find({"target_doc_id": did, "target_type": "ro", "source_type": "mro"}, {"_id": 0}).to_list(5000)
        ids |= {a.get("source_line_id") for a in old if a.get("source_line_id")}
    return ids


async def validate_ro_body(server, body, did=None, user=None):
    db = server.db
    alw = _allowed_divisions(server, user)
    normalized, _ = await uom_layer._normalize_body(server, body or {})
    lines = normalized.get("lines") or []
    if did:
        await _require_balanced_edit(server, did, lines)
    sourced = [l for l in lines if l.get("sources")]
    if not sourced:
        return
    division_id = normalized.get("division_id")
    if not division_id:
        raise HTTPException(400, "Divisi RO wajib diisi sebelum menarik kebutuhan MRO")
    taken = {}   # mro_line_id -> total qty dari dokumen ini
    mlines = {}
    for l in sourced:
        line_qty = float(l.get("qty") or 0)
        total = 0.0
        seen = set()
        for s in l.get("sources") or []:
            sl = s.get("line_id") or s.get("mro_line_id")
            q = float(s.get("qty") or 0)
            if not sl or not s.get("mro_id") or q <= 0:
                raise HTTPException(400, "Alokasi sumber MRO tidak valid (MRO wajib, qty harus > 0)")
            if sl in seen:
                raise HTTPException(400, "Baris MRO sumber yang sama tercantum lebih dari sekali pada satu baris RO")
            seen.add(sl)
            ml = mlines.get(sl) or await db.mro_lines.find_one({"id": sl}, {"_id": 0})  # tenant-scoped proxy
            if not ml or (s.get("mro_id") and s.get("mro_id") != ml.get("mro_id")):
                raise _not_found()
            mlines[sl] = ml
            head = await db.mro.find_one({"id": ml.get("mro_id")}, {"_id": 0}) or {}
            if not head or (alw is not None and head.get("division_id") and head.get("division_id") not in alw):
                raise _not_found()  # di luar cakupan divisi = diperlakukan sama dengan tidak ada
            no = head.get("no") or "MRO"
            if head.get("cancelled") or not head.get("submitted"):
                raise HTTPException(400, f"{no} tidak aktif / belum disubmit, tidak dapat ditarik ke RO")
            if head.get("division_id") != division_id:
                raise HTTPException(400, f"Satu RO hanya untuk satu Divisi. {no} berasal dari divisi lain.")
            if ml.get("item_id") != l.get("item_id"):
                raise HTTPException(400, f"Barang pada {no} berbeda dengan barang baris RO")
            ml["_no"] = no
            taken[sl] = taken.get(sl, 0.0) + q
            total += q
        if abs(total - line_qty) > EPS:
            raise HTTPException(400, f"Total alokasi sumber ({_fmt(total)}) harus sama dengan Qty RO ({_fmt(line_qty)})")
    for sl, q in taken.items():
        ml = mlines[sl]
        elsewhere = await _allocated_elsewhere(server, sl, "ro", did)
        sisa = float(ml.get("qty") or 0) - elsewhere
        if q > sisa + EPS:
            raise HTTPException(400, f"Qty alokasi {ml['_no']} ({_fmt(q)}) melebihi sisa belum RO ({_fmt(max(0.0, sisa))})")


async def _require_balanced_edit(server, did, lines):
    """Edit RO: baris lama yang bersumber MRO wajib mengirim ulang rincian alokasi bila Qty RO
    berubah. Tanpa ini engine edit generik memotong alokasi secara greedy (tidak terkontrol user)."""
    db = server.db
    for l in lines:
        if l.get("sources") or not l.get("id"):
            continue
        old = await db.allocations.find({"target_line_id": l["id"], "target_doc_id": did, "source_type": "mro"}, {"_id": 0}).to_list(500)
        if not old:
            continue
        total_old = sum(float(a.get("qty") or 0) for a in old)
        if abs(total_old - float(l.get("qty") or 0)) > EPS:
            raise HTTPException(400, f"Qty RO berubah ({_fmt(total_old)} -> {_fmt(l.get('qty'))}). Atur ulang Rincian alokasi sumber MRO hingga seimbang.")


async def ro_line_sources(server, did, line, m, ucache):
    db = server.db
    allocs = await db.allocations.find({"target_line_id": line["id"], "source_type": "mro"}, {"_id": 0}).to_list(500)
    out = []
    for a in allocs:
        ml = await db.mro_lines.find_one({"id": a.get("source_line_id")}, {"_id": 0})
        if not ml:
            continue
        head = await db.mro.find_one({"id": ml.get("mro_id")}, {"_id": 0}) or {}
        spks, non = await _spk_breakdown(server, ml)
        mro_qty = float(ml.get("qty") or 0)
        elsewhere = await _allocated_elsewhere(server, ml["id"], "ro", did)
        out.append({
            "mro_id": ml.get("mro_id"), "mro_no": head.get("no"), "mro_date": head.get("date"),
            "line_id": ml["id"], "item_id": ml.get("item_id"),
            "division_id": head.get("division_id"),
            "division_name": m["divisions"].get(head.get("division_id"), {}).get("name"),
            "project_id": ml.get("project_id"), "project_name": m["projects"].get(ml.get("project_id"), {}).get("name"),
            "unit_id": ml.get("unit_id"), "unit_name": (lambda u: u.get("plate_no") or u.get("name"))(m["units"].get(ml.get("unit_id"), {}) or {}),
            "warehouse_id": ml.get("warehouse_id"),
            "spk": spks, "non_spk_qty": non, "spk_label": _spk_label(spks, non),
            "mro_qty": mro_qty, "sudah_ro": round(elsewhere, 6), "sisa": round(max(0.0, mro_qty - elsewhere), 6),
            "qty": float(a.get("qty") or 0), "base_qty": float(a.get("qty") or 0),
        })
    out.sort(key=lambda x: (str(x.get("mro_date") or ""), str(x.get("mro_no") or "")))
    return out


def install(server):
    app = server.app
    import doc_procurement

    def mk_create(orig):
        async def create_ro_consolidated(body: dict, user=Depends(server.current_user)):
            # Kunci lintas proses per baris MRO -> hitung ulang sisa -> tulis allocation -> lepas.
            async with mro_line_locks(server, await lock_line_ids(server, body)):
                await validate_ro_body(server, body, None, user)
                return await orig(body, user)
        return create_ro_consolidated

    def mk_put(orig):
        async def put_transaction(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module != "ro":
                return await orig(module, did, body, user)
            async with mro_line_locks(server, await lock_line_ids(server, body, did)):
                await validate_ro_body(server, body, did, user)
                result = await orig(module, did, body, user)
            if getattr(server, "spk_inherit_line", None):
                try:  # baris RO baru hasil edit mewarisi SPK dari sumber MRO-nya
                    for l in await server.db.ro_lines.find({"ro_id": did}, {"_id": 0}).to_list(2000):
                        await server.spk_inherit_line("ro", did, l, user)
                except Exception as exc:  # jangan gagalkan edit RO
                    server.logger.warning(f"RO consolidation inherit after edit: {exc}")
            return result
        return put_transaction

    def mk_get(orig):
        async def get_ro_consolidated(did: str, user=Depends(server.current_user)):
            d = await orig(did, user)
            if not isinstance(d, dict):
                return d
            m = await doc_procurement.maps()
            ucache = {}
            for l in d.get("lines") or []:
                if not l.get("id"):
                    continue
                l["sources"] = await ro_line_sources(server, did, l, m, ucache)
                l["mro_count"] = len({s["mro_id"] for s in l["sources"]})
                l["division_id"] = d.get("division_id")
                l["division_name"] = d.get("division_name")
                bu = await _base_unit(server, l.get("item_id"), ucache)
                l["base_unit"] = bu["base_unit"]
                l["base_uom_id"] = bu["base_uom_id"]
            return d
        return get_ro_consolidated

    def mk_pull(orig):
        async def pull_mro_for_ro_consolidated(user=Depends(server.current_user)):
            rows = await orig(user=user)
            m = await doc_procurement.maps()
            ucache, heads = {}, {}
            for r in rows or []:
                ml = await server.db.mro_lines.find_one({"id": r.get("line_id")}, {"_id": 0})
                if not ml:
                    continue
                hid = ml.get("mro_id")
                if hid not in heads:
                    heads[hid] = await server.db.mro.find_one({"id": hid}, {"_id": 0}) or {}
                head = heads[hid]
                spks, non = await _spk_breakdown(server, ml)
                bu = await _base_unit(server, r.get("item_id"), ucache)
                r.update({
                    "division_id": head.get("division_id"),
                    "division_name": m["divisions"].get(head.get("division_id"), {}).get("name"),
                    "mro_date": head.get("date"), "spk": spks, "non_spk_qty": non, "spk_label": _spk_label(spks, non),
                    "unit_name": r.get("unit_name") or (lambda u: u.get("plate_no") or u.get("name"))(m["units"].get(ml.get("unit_id"), {}) or {}),
                    "base_unit": bu["base_unit"], "base_uom_id": bu["base_uom_id"],
                })
            return rows
        return pull_mro_for_ro_consolidated

    _wrap(app, "/api/ro", "POST", mk_create)
    _wrap(app, "/api/transactions/{module}/{did}", "PUT", mk_put)
    _wrap(app, "/api/ro/{did}", "GET", mk_get)
    _wrap(app, "/api/pull/mro-for-ro", "GET", mk_pull)
