"""Server-side pagination, search, filter & sort untuk list transaksi.

Aktif hanya bila query `page` dikirim (tanpa `page` respons tetap array lama untuk print/export).
Dipasang paling akhir sehingga baris sudah melewati tenant -> permission -> division scope
dan enrichment existing; layer ini hanya menyaring, mengurutkan dan memotong di backend,
lalu mengirim maksimal page_size baris ke browser.
Respons: {items, total, page, page_size, facets}.
"""
import asyncio
import os

from fastapi import Depends, Request
from fastapi.routing import APIRoute

LISTS = {"/api/mro": "mro", "/api/ro": "ro", "/api/po": "po", "/api/do": "do", "/api/mi": "mi",
         "/api/transfers": "transfer", "/api/loans": "loan", "/api/adjustments": "adjustment", "/api/opname": "opname",
         "/api/vendor-invoices": "invoice", "/api/vendor-invoices/do-billing": "do_billing"}
SIZES = (25, 50, 100)
DATE_FIELD = {"invoice": "invoice_date"}
NO_SEARCH = {"id", "tenant_id", "items", "lines", "trace_division_ids", "trace_project_ids", "lifecycle"}


def _split(v):
    if v is None:
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _get(row, key):
    cur = row
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _hay(r):
    vals = [str(v) for k, v in r.items() if k not in NO_SEARCH and not k.endswith("_id")
            and isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    return " ".join(vals).lower()


def _sort_key(v):
    if v is None or v == "":
        return (2, 0, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (0, float(v), "")
    return (1, 0, str(v).lower())


def _stage(t):
    req, ro, po, rec, mi = (float(t.get(k) or 0) for k in ("request", "qty_ro", "qty_po", "qty_received", "qty_mi"))
    if req > 0 and mi >= req:
        return "Completed"
    return "MI" if mi > 0 else "DO" if rec > 0 else "PO" if po > 0 else "RO" if ro > 0 else "MRO"


async def _lines_min(ids):
    """mro_lines per MRO — hanya field yang dibaca lifecycle (id, qty); urutan dasar sama dengan lines_by_doc."""
    out = {i: [] for i in ids}
    if ids:
        from server import db
        for ln in await db.mro_lines.find({"mro_id": {"$in": list(ids)}}, {"_id": 0, "id": 1, "qty": 1, "mro_id": 1}).to_list(None):
            out.setdefault(ln.get("mro_id"), []).append(ln)
    return out


async def _allocs_min(source_line_ids, target_type):
    """== doc_procurement.allocs_from, tetapi hanya field yang dibaca lifecycle (P7: tanpa memuat/mem-parse dokumen penuh)."""
    ids = [x for x in set(source_line_ids) if x]
    if not ids:
        return {}
    from server import db
    out = {}
    for a in await db.allocations.find({"source_line_id": {"$in": ids}, "target_type": target_type},
                                       {"_id": 0, "source_line_id": 1, "target_line_id": 1, "qty": 1}).to_list(None):
        out.setdefault(a.get("source_line_id"), []).append(a)
    return out


FULL_ALLOC_SCAN_MIN = 2000  # di atas ini: 1 scan allocations (field minimal) menggantikan 4 query IN raksasa (masing2 full scan)


def _gen_key(v):
    """Nilai yang dapat cocok dengan pushdown SQL `kolom generated IN/= ...` (perilaku adapter existing): hanya string
    non-kosong <= 191 karakter (array/objek/angka -> kolom generated NULL / berbeda -> tidak pernah cocok)."""
    return [v] if isinstance(v, str) and v and len(v) <= 191 else []


async def _allocs_by_type(types):
    """{target_type: {source_line_id: [alokasi]}} SELURUH alokasi bertipe `types` (field minimal), urutan dasar sama.
    Per kunci identik dengan `_allocs_min(ids, t)` = find({"source_line_id": {"$in": ids}, "target_type": t}) termasuk
    semantik pushdown kolom generated (lihat `_gen_key`; nilai di luar pola itu tidak pernah ikut di jalur lama)."""
    from server import db
    out = {t: {} for t in types}
    for a in await db.allocations.find({"target_type": {"$in": list(types)}},
                                       {"_id": 0, "source_line_id": 1, "target_line_id": 1, "qty": 1, "target_type": 1}).to_list(None):
        for t in _gen_key(a.get("target_type")):
            if t in out:
                for k in _gen_key(a.get("source_line_id")):
                    out[t].setdefault(k, []).append(a)
    return out


async def _mro_lifecycle(rows):
    """Request/RO/PO/DO/MI per MRO (rumus sama dgn /reports/mro-traceability), 5 query batch.
    P7: untuk banyak MRO (hitungan tahap / cari seluruh data) alokasi dimuat 1 scan bertipe (hasil per kunci identik)."""
    by_doc = await _lines_min([r["id"] for r in rows])
    lids = [l["id"] for v in by_doc.values() for l in v]
    if len(rows) > FULL_ALLOC_SCAN_MIN:
        allx = await _allocs_by_type(("ro", "mi", "po", "do"))
        to_ro, to_mi, to_po, to_do = allx["ro"], allx["mi"], allx["po"], allx["do"]
    else:
        to_ro, to_mi = await asyncio.gather(_allocs_min(lids, "ro"), _allocs_min(lids, "mi"))
        to_po = await _allocs_min([a["target_line_id"] for v in to_ro.values() for a in v], "po")
        to_do = await _allocs_min([a["target_line_id"] for v in to_po.values() for a in v], "do")
    for r in rows:
        t = {"request": 0.0, "qty_ro": 0.0, "qty_po": 0.0, "qty_received": 0.0, "qty_mi": 0.0}
        for l in by_doc.get(r["id"], []):
            t["request"] += float(l.get("qty") or 0)
            for a in to_ro.get(l["id"], []):
                t["qty_ro"] += float(a.get("qty") or 0)
                for pa in to_po.get(a["target_line_id"], []):
                    t["qty_po"] += float(pa.get("qty") or 0)
                    t["qty_received"] += sum(float(d.get("qty") or 0) for d in to_do.get(pa["target_line_id"], []))
            t["qty_mi"] += sum(float(a.get("qty") or 0) for a in to_mi.get(l["id"], []))
        t["outstanding"] = max(0.0, t["request"] - t["qty_mi"])
        r["lifecycle"] = t
        r["lifecycle_stage"] = _stage(t)


async def filter_sort(module, rows, qp, lifecycle=True):
    """Filter (f_*), periode, pencarian & sort daftar — SELURUH hasil (dipakai daftar ber-halaman & export P6).
    lifecycle=False (P7, jalur cepat): tahap MRO tidak dihitung untuk seluruh header bila tidak diminta (counts/f_)."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if module == "mro" and lifecycle:
        await _mro_lifecycle(rows)
    facets = {}
    for key in _split(qp.get("facets")):
        facets[key] = sorted({x for r in rows for x in _split(_get(r, key))}, key=str.lower)
    if qp.get("counts"):
        key = qp["counts"]
        cnt = {}
        for r in rows:
            cnt[str(_get(r, key))] = cnt.get(str(_get(r, key)), 0) + 1
        facets[f"count:{key}"] = cnt
    for k, v in qp.items():
        if k.startswith("f_") and v:
            key = k[2:]
            rows = [r for r in rows if v in _split(_get(r, key)) or str(_get(r, key)) == v]
    dkey = qp.get("date_field") or DATE_FIELD.get(module, "date")
    lo, hi = qp.get("date_from"), qp.get("date_to")
    if lo or hi:
        rows = [r for r in rows if (not lo or str(r.get(dkey) or "")[:10] >= lo) and (not hi or str(r.get(dkey) or "")[:10] <= hi)]
    terms = (qp.get("q") or "").strip().lower().split()
    if terms:
        rows = [r for r in rows if all(t in _hay(r) for t in terms)]
    sort = qp.get("sort")
    if sort:
        desc = qp.get("dir") == "desc"
        filled = [r for r in rows if _get(r, sort) not in (None, "")]
        empty = [r for r in rows if _get(r, sort) in (None, "")]
        filled.sort(key=lambda r: (_sort_key(_get(r, sort)), str(r.get("no") or "")), reverse=desc)
        rows = filled + empty
    else:  # default: terbaru terlebih dahulu
        rows.sort(key=lambda r: (str(r.get("created_at") or r.get(dkey) or ""), str(r.get("no") or "")), reverse=True)
    return rows, facets


def _page_window(qp, total):
    try:
        size = int(qp.get("page_size") or 25)
    except ValueError:
        size = 25
    size = size if size in SIZES else 25
    try:
        page = max(1, int(qp.get("page") or 1))
    except ValueError:
        page = 1
    return min(page, max(1, -(-total // size))), size


async def paginate(module, rows, qp):
    rows, facets = await filter_sort(module, rows, qp)
    total = len(rows)
    page, size = _page_window(qp, total)
    return {"items": rows[(page - 1) * size: page * size], "total": total, "page": page, "page_size": size, "facets": facets}


# ------------------------------------------------------------------ P7: jalur cepat daftar ber-halaman (hasil identik)
# Seluruh layer daftar (tenant -> izin -> cakupan divisi/gudang -> enrichment) bersifat per-baris (map + filter). Untuk user
# berakses global (layer cakupan tidak menyaring baris) dan tanpa pencarian/filter atas field hasil enrichment, urutan, total,
# periode, hitungan tahap & filter tahap MRO cukup dihitung dari field header dokumen; enrichment penuh hanya untuk baris halaman.
HEADER_COLL = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi", "transfer": "transfers", "loan": "loans",
               "adjustment": "adjustments", "opname": "opname"}
HEADER_FIELDS = ("id", "created_at", "date", "no")


# Jalur cepat untuk user TERBATAS divisi hanya MRO. Benchmark terkontrol (proc_perf_itest, docs/perf-p7.md §Root cause
# daftar terbatas divisi): untuk RO/PO/DO/MI, visible_doc_ids harus memperkaya (enrich_list) SELURUH kandidat demi
# trace_division_ids, lalu pipeline halaman memperkaya lagi -> kerja ganda, 1,2–1,6x lebih lambat dari jalur penuh +
# pra-saring cakupan. Untuk MRO pengayaan kandidat jauh lebih murah sehingga jalur cepat tetap menang (~0,68x main).
# P7_SCOPED_FAST=0 hanya untuk backend referensi uji ekuivalensi (jalur penuh); hasil identik di kedua jalur.
SCOPED_FAST = {"mro"}


def fast_ok(server, module, qp, user):
    if module not in HEADER_COLL:
        return False
    if not server.is_global(user) and (module not in SCOPED_FAST or getattr(server, "LIST_VISIBLE_IDS", None) is None
                                       or os.environ.get("P7_SCOPED_FAST", "1") in ("0", "none")):
        return False
    for k, v in qp.items():
        if v in (None, "") or k in ("page", "page_size", "dir"):
            continue
        if k == "sort" and v in ("no", "date", "created_at"):
            continue
        if k in ("date_from", "date_to"):
            continue
        if module == "mro" and ((k == "counts" and v == "lifecycle_stage") or k == "f_lifecycle_stage"):
            continue
        if k == "q" and not str(v).strip():
            continue
        return False
    return True


async def fast_page(server, module, qp, page_rows, user=None):
    """Header seluruh dokumen (field minimal) -> [user terbatas divisi: kandidat pra-saring -> dokumen terlihat menurut
    access_control.visible_doc_ids] -> filter_sort yang SAMA -> id halaman -> pipeline daftar penuh (termasuk filter cakupan
    existing) hanya untuk id tsb. None bila baris halaman tidak lengkap (fallback ke jalur penuh)."""
    import list_cap
    hdr = await getattr(server.db, HEADER_COLL[module]).find({}, {"_id": 0, **{f: 1 for f in HEADER_FIELDS}}) \
        .sort("created_at", -1).to_list(None)
    hdr = [h for h in hdr if h.get("id")]  # enrich_list existing membuang baris tanpa id
    if user is not None and not server.is_global(user):
        cand = await scope_candidates(server, module, user)
        if cand is not None:
            cs = set(cand)
            hdr = [h for h in hdr if h["id"] in cs]
        ok = await server.LIST_VISIBLE_IDS(module, [h["id"] for h in hdr], user)
        hdr = [h for h in hdr if h["id"] in ok]
    need = module == "mro" and (qp.get("counts") == "lifecycle_stage" or bool(qp.get("f_lifecycle_stage")))
    rows, facets = await filter_sort(module, hdr, qp, lifecycle=need)
    total = len(rows)
    page, size = _page_window(qp, total)
    ids = [r["id"] for r in rows[(page - 1) * size: page * size]]
    with list_cap.only(module, ids):
        got = await page_rows()
    by = {r.get("id"): r for r in got or [] if isinstance(r, dict)}
    if any(i not in by for i in ids) or len(by) != len(ids):
        return None
    items = [by[i] for i in ids]
    if module == "mro":
        await _mro_lifecycle(items)  # nilai per baris identik dengan perhitungan atas seluruh baris
    return {"items": items, "total": total, "page": page, "page_size": size, "facets": facets}


# P7: pra-saring cakupan untuk user terbatas divisi (jalur daftar ber-halaman penuh). Filter cakupan daftar existing
# (access_control mk_list) hanya meloloskan baris bila SELURUH divisi jejak (trace_division_ids + division_id baris) berada dalam
# divisi user, ATAU user ditugaskan sebagai approver dokumen; daftar DO juga mensyaratkan division_id dalam cakupan. Jadi dokumen
# ber-division_id tersimpan di luar cakupan & bukan penugasan approver PASTI tidak tampil -> tidak perlu dimuat & diperkaya.
# Dokumen lain tetap melewati pipeline + filter cakupan existing apa adanya (hasil & urutan identik). Modul cakupan gudang
# (transfer/pinjam/penyesuaian/opname) tidak dipra-saring. Nonaktif: P7_SCOPE_PREFILTER=0.
SCOPE_PREFILTER = {"mro", "ro", "po", "do", "mi"}


async def scope_candidates(server, module, user):
    """Daftar id kandidat (urutan bebas) atau None (tanpa pra-saring)."""
    if module not in SCOPE_PREFILTER or server.is_global(user) or os.environ.get("P7_SCOPE_PREFILTER", "1") == "0":
        return None
    alw = {str(x) for x in (user.get("divisions") or []) if x}  # == access_control.allowed(user) untuk user non-global
    hdr = await getattr(server.db, HEADER_COLL[module]).find({}, {"_id": 0, "id": 1, "division_id": 1}).to_list(None)
    asg = set()
    if module in ("mro", "ro", "po"):  # == access_control.assigned(mod, user)
        asg = {r.get("document_id") for r in await server.db.approval_tasks.find(
            {"module": module, "approver_email": str(user.get("email") or "").lower()}, {"_id": 0, "document_id": 1}).to_list(5000)}
    def keep(h):
        d = h.get("division_id")
        if not d:
            return True
        try:
            return d in alw or h["id"] in asg
        except TypeError:  # nilai tak-hashable: tidak dipra-saring (tetap dinilai filter cakupan existing)
            return True
    return [h["id"] for h in hdr if h.get("id") and keep(h)]


async def scope_prefilter(server, module, user):
    """Pra-saring yang sama dengan `scope_candidates`, sebagai filter dokumen untuk query daftar paling dalam (tanpa query
    header terpisah): division_id kosong/None/hilang/0/False, ATAU division_id dalam divisi user, ATAU id = penugasan approver.
    Dievaluasi adapter dengan semantik Mongo (pushdown SQL + verifikasi Python). None = tanpa pra-saring."""
    if module not in SCOPE_PREFILTER or server.is_global(user) or os.environ.get("P7_SCOPE_PREFILTER", "1") == "0":
        return None
    alw = sorted({str(x) for x in (user.get("divisions") or []) if x})
    # nilai falsy (hilang/None/""/0/False/[]/{}) dan array (tak-hashable: tidak dipra-saring) selalu ikut -> superset aman
    ors = [{"division_id": {"$exists": False}}, {"division_id": {"$in": [None, "", 0, False]}}, {"division_id": {"$size": 0}},
           {"division_id": {}}, {"division_id.0": {"$exists": True}}]
    if alw:
        ors.append({"division_id": {"$in": alw}})
    if module in ("mro", "ro", "po"):  # == access_control.assigned(mod, user)
        asg = sorted({r.get("document_id") for r in await server.db.approval_tasks.find(
            {"module": module, "approver_email": str(user.get("email") or "").lower()}, {"_id": 0, "document_id": 1}).to_list(5000)
            if isinstance(r.get("document_id"), str)})
        if asg:
            ors.append({"id": {"$in": asg}})
    return {"$or": ors}


def install(server):
    app = server.app
    sources = {}

    async def source_rows(module, user, qp):
        """Baris daftar persis seperti endpoint daftar (tenant -> izin -> cakupan divisi/gudang -> enrichment) + drill
        Dashboard (rf_*). Batas muat dokumen mengikuti list_cap (export menaikkannya)."""
        rows = await sources[module](user=user)
        if getattr(server, "REPORT_LIST_FILTER", None) and any(k.startswith("rf_") and v for k, v in qp.items()):
            rows = await server.REPORT_LIST_FILTER(module, rows or [], qp)
        return rows

    async def all_rows(module, user, qp):
        """SELURUH hasil daftar sesuai filter/pencarian/periode/sort yang sama dengan tampilan daftar (tanpa halaman)."""
        rows, _ = await filter_sort(module, await source_rows(module, user, qp), qp)
        return rows

    server.TXN_LIST_ROWS = all_rows
    for path, module in LISTS.items():
        route = next((r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path and "GET" in r.methods), None)
        if not route:
            continue
        orig = route.endpoint
        sources[module] = orig
        idx = app.router.routes.index(route)
        app.router.routes.remove(route)

        def make(orig=orig, module=module):
            async def listing(request: Request, user=Depends(server.current_user)):
                import list_cap
                qp = dict(request.query_params)
                if "page" not in qp:  # respons array lama (batas muat existing) untuk pemanggil tanpa halaman
                    return await source_rows(module, user, qp)  # drill-down Dashboard (rf_*, predikat sama)
                if fast_ok(server, module, qp, user):
                    res = await fast_page(server, module, qp, lambda: sources[module](user=user), user)
                    if res is not None:
                        return res
                with list_cap.raised(list_cap.ALL):  # P7: seluruh dokumen (tanpa batas 1.000) -> total & hasil cari/filter lengkap
                    sflt = await scope_prefilter(server, module, user)
                    if sflt is None:
                        rows = await source_rows(module, user, qp)
                    else:  # user terbatas divisi: dokumen yang PASTI di luar cakupan tidak dimuat/diperkaya (hasil identik)
                        with list_cap.scoped(module, sflt):
                            rows = await source_rows(module, user, qp)
                return await paginate(module, rows, qp)
            listing.__name__ = f"list_{module}_paged"
            return listing
        app.add_api_route(path, make(), methods=["GET"], tags=["list-paging"])
        app.router.routes.insert(idx, app.router.routes.pop())  # pertahankan urutan (mis. /do-billing sebelum /{id})
