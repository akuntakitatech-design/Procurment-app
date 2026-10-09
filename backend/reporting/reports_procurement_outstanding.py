"""P2b — Outstanding & Nilai Procurement pada Pusat Laporan (READ-ONLY).

Sumber & aturan existing (tidak ada formula baru):
  - Outstanding dihitung dari ALOKASI per baris (`allocations`: MRO→RO/MI, RO→PO, PO→DO) seperti helper existing
    `doc_procurement.ro_line_state` / `po_line_state` / `mro_line_monitor` (outstanding = max(0, qty − teralokasi)).
    Pembatalan/reversal dokumen lanjutan menghapus alokasinya (transaction_mutation_layer) -> otomatis kembali outstanding;
    multi-referensi dijumlah per baris sumber -> tanpa double counting.
  - Cut-off historis: alokasi dihitung bila tanggal bisnis WIB dokumen lanjutan ≤ Tanggal Akhir (default hari ini).
  - Outstanding DO→MI = qty diterima (rantai MRO→RO→PO→DO, rumus `mro_monitor_batch`) − qty MI per baris MRO.
  - Nilai PO = komitmen (PO Approved/Closed menurut `receipt_control_layer.document_status`, sama dengan Register PO);
    snapshot baris PO (gross/discount/dpp/tax_amount/total). Nilai DO = realisasi: qty diterima × DPP (dan PPN) per unit
    baris PO (rumus Register DO / MRO Traceability). Satu baris PO dihitung sekali walau diterima beberapa DO.
  - Visibilitas dokumen = aturan daftar existing (`ACCESS_FILTER_VISIBLE` lewat Register P2a); kolom nilai price=True.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date

import doc_procurement as DP
import receipt_control_layer as RC
import stock_summary as SS
from reporting.registry import Column, Filter, ReportSpec, register
from reporting.reports_procurement_ops import (F_CAT, F_DIV, F_FROM, F_ITEM, F_PROJ, F_SUP, F_TO, _f, _in_period, _visible)
from reporting.scope import local_day

G = "procurement"
EPS = 1e-9
COMMIT = ("Approved", "Closed")
NEXT = {"mro": ("mi", "MI"), "ro": ("po", "PO"), "po": ("do", "DO")}


def today_wib() -> str:
    return SS.today_iso()


def _cancelled(d) -> bool:
    return d.get("cancelled") is True or str(d.get("status") or "").lower() in ("cancelled", "canceled", "dibatalkan")


BULK = 300  # di atas ini: 1 query pushdown kolom terindeks + saring himpunan di Python (hasil identik `$in`, tanpa ribuan parameter SQL)


async def _find_in(coll, fk, ids, base=None):
    """Dokumen dengan `fk` ∈ ids (+ filter `base`), urutan baris sama dengan `find({fk: {"$in": ids}, **base})`."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return []
    if len(ids) <= BULK:
        return await coll.find({fk: {"$in": sorted(ids)}, **(base or {})}, {"_id": 0}).to_list(None)
    def hit(v):  # semantik `$in` Mongo: skalar ∈ ids, atau salah satu elemen bila field berupa list
        vals = v if isinstance(v, list) else [v]
        return any(isinstance(x, (str, int, float)) and not isinstance(x, bool) and x in ids for x in vals)
    return [d for d in await coll.find(dict(base or {}), {"_id": 0}).to_list(None) if fk in d and hit(d[fk])]


async def _lines_by_doc(server, src, doc_ids):
    """= `DP.lines_by_doc(f"{src}_lines", f"{src}_id", ids)` (baris dikelompokkan per dokumen, urutan sama)."""
    out = {i: [] for i in doc_ids}
    for ln in await _find_in(getattr(server.db, f"{src}_lines"), f"{src}_id", doc_ids):
        out.setdefault(ln.get(f"{src}_id"), []).append(ln)
    return out


async def _allocs_from(server, line_ids, target):
    """= `DP.allocs_from(line_ids, target)` (alokasi per baris sumber)."""
    out = {}
    for a in await _find_in(server.db.allocations, "source_line_id", line_ids, {"target_type": target}):
        out.setdefault(a.get("source_line_id"), []).append(a)
    return out


async def _raw_docs(server, mod, p, extra_ok=None):
    return [d for d in await getattr(server.db, mod).find({}, {"_id": 0}).to_list(None)
            if _in_period(local_day(d.get("date")), p) and not _cancelled(d) and (extra_ok is None or extra_ok(d))]


async def _enrich_visible(server, user, mod, p, docs, trace=True):
    """Enrichment + visibilitas daftar existing (`ACCESS_FILTER_VISIBLE`) + filter divisi (header atau telusur).
    trace=False (rekap: hanya butuh visibilitas, kolom header mentah): pengguna lintas-divisi (`is_global`) melihat semua
    dokumen menurut hook existing (`filter_visible` -> list(rows)) -> enrichment telusur tidak diperlukan."""
    if not docs:
        return []
    if not trace and not p.get("division_id") and getattr(server, "ACCESS_FILTER_VISIBLE", None) and server.is_global(user):
        return list(docs)
    rows = await _visible(server, user, mod, await RC.enrich_list(server, mod, docs))
    if p.get("division_id"):
        rows = [r for r in rows if r.get("division_id") == p["division_id"] or p["division_id"] in (r.get("trace_division_ids") or [])]
    return rows


async def _docs(server, user, mod, p, extra_ok=None, trace=True):
    """Header dokumen dalam periode (tanggal bisnis WIB) yang terlihat oleh pengguna (aturan daftar existing)."""
    return await _enrich_visible(server, user, mod, p, await _raw_docs(server, mod, p, extra_ok), trace)


async def _target_docs(server, allocs):
    by_type = defaultdict(set)
    for a in allocs:
        by_type[a.get("target_type")].add(a.get("target_doc_id"))
    out = {}
    for t, ids in by_type.items():
        if t in ("ro", "po", "do", "mi") and ids:
            for d in await _find_in(getattr(server.db, t), "id", ids):
                out[d["id"]] = d
    return out


def _cut(allocs, tdocs, cutoff):
    """Alokasi berlaku: dokumen lanjutan ada, tidak batal, tanggal bisnis ≤ cut-off."""
    keep = []
    for a in allocs or []:
        d = tdocs.get(a.get("target_doc_id"))
        if d and not _cancelled(d) and (local_day(d.get("date")) or "") <= cutoff:
            keep.append(a)
    return keep


async def _allocs_cut(server, line_ids, target, cutoff):
    al = await _allocs_from(server, line_ids, target)
    td = await _target_docs(server, [a for v in al.values() for a in v])
    return {k: _cut(v, td, cutoff) for k, v in al.items()}, td


def _age(d, cutoff):
    try:
        return max(0, (date.fromisoformat(cutoff) - date.fromisoformat(d)).days) if d else None
    except ValueError:
        return None


def _line_status(qty, done):
    if done <= EPS:
        return "Belum Diproses"
    return "Selesai" if done + EPS >= qty else "Sebagian"


def _is_commit(po) -> bool:
    return RC.document_status(po, "") in COMMIT  # klasifikasi sama dengan Register PO


# --------------------------------------------------------------------------------------------- outstanding
async def outstanding(server, user, mod, p):
    cutoff = p.get("date_to") or today_wib()
    ok = _is_commit if mod == "po" else (lambda d: d.get("submitted", True) is not False)
    src = "mro" if mod == "do" else mod
    raw_l, m = await asyncio.gather(_raw_docs(server, src, p, ok), DP.maps())
    raw = {d["id"]: d for d in raw_l}
    lines = [ln for v in (await _lines_by_doc(server, src, list(raw))).values() for ln in v]
    nm = lambda coll, i: (m[coll].get(i) or {}).get("name") if i else None  # noqa: E731
    if mod == "do":
        done, refs = await _do_to_mi(server, lines, cutoff)
    else:
        tgt = NEXT[mod][0]
        al, td = await _allocs_cut(server, [ln["id"] for ln in lines], tgt, cutoff)
        done = {ln["id"]: DP._sum(al.get(ln["id"])) for ln in lines}
        refs = {ln["id"]: sorted({(td.get(a["target_doc_id"]) or {}).get("no") or "" for a in al.get(ln["id"], [])} - {""}) for ln in lines}
    def qd(ln):
        return done[ln["id"]] if mod == "do" else (_f(ln.get("qty")), done[ln["id"]])
    if p.get("show", "outstanding") == "outstanding":  # enrichment/visibilitas hanya untuk dokumen yang punya baris tampil
        lines = [ln for ln in lines if qd(ln)[0] - qd(ln)[1] > EPS]
    hid = {h["id"]: h for h in await _enrich_visible(server, user, src, p, [raw[i] for i in {ln[f"{src}_id"] for ln in lines}])}
    out = []
    for ln in lines:
        h = hid.get(ln[f"{src}_id"])
        if h is None:
            continue
        if mod == "do":
            qty, d = done[ln["id"]]
        else:
            qty, d = _f(ln.get("qty")), done[ln["id"]]
        osd = max(0.0, qty - d)
        if p.get("show", "outstanding") == "outstanding" and osd <= EPS:
            continue
        pid = ln.get("project_id") or h.get("default_project_id")
        if p.get("project_id") and pid != p["project_id"]:
            continue
        if p.get("item_id") and ln.get("item_id") != p["item_id"]:
            continue
        it = m["items"].get(ln.get("item_id")) or {}
        if p.get("category_id") and it.get("category_id") != p["category_id"]:
            continue
        sup = h.get("supplier_id")
        if p.get("supplier_id") and sup != p["supplier_id"]:
            continue
        day = local_day(h.get("date"))
        out.append({"doc_id": h["id"], "mod": src, "no": h.get("no"), "date": day,
                    "division": h.get("trace_division") or nm("divisions", h.get("division_id")) or "-",
                    "project": nm("projects", pid) or h.get("trace_project") or "-", "supplier": nm("suppliers", sup) or "-",
                    "item_code": it.get("code") or ln.get("item_code"), "item_name": it.get("name") or ln.get("item_name"),
                    "unit": ln.get("display_unit") or ln.get("unit") or it.get("unit") or "-",
                    "qty": round(qty, 6), "done": round(d, 6), "outstanding": round(osd, 6),
                    "pct": round(min(100.0, d / qty * 100.0), 1) if qty > EPS else 0.0,
                    "age": _age(day, cutoff) if osd > EPS else None, "status": _line_status(qty, d),
                    "refs": ", ".join(refs.get(ln["id"]) or []) or "-"})
    if p.get("status"):
        out = [o for o in out if o["status"] == p["status"]]
    out.sort(key=lambda o: (o["date"] or "", o["no"] or "", o["item_code"] or ""))
    return out


async def _do_to_mi(server, mro_lines, cutoff):
    """Cerminan `DP.mro_monitor_batch` (min(porsi, …) per alokasi RO) dengan cut-off; parity diuji tanpa cut-off."""
    lids = [ln["id"] for ln in mro_lines]
    (to_ro, _), (to_mi, _) = await asyncio.gather(_allocs_cut(server, lids, "ro", cutoff), _allocs_cut(server, lids, "mi", cutoff))
    to_po, _ = await _allocs_cut(server, [a["target_line_id"] for v in to_ro.values() for a in v], "po", cutoff)
    to_do, td3 = await _allocs_cut(server, [a["target_line_id"] for v in to_po.values() for a in v], "do", cutoff)
    done, refs = {}, {}
    for ln in mro_lines:
        received, dnos = 0.0, set()
        for a in to_ro.get(ln["id"], []):
            rl, portion = a["target_line_id"], a["qty"]
            rec = 0.0
            for pa in to_po.get(rl, []):
                ds = to_do.get(pa["target_line_id"], [])
                rec += DP._sum(ds)
                dnos |= {(td3.get(x["target_doc_id"]) or {}).get("no") or "" for x in ds}
            received += min(portion, rec)
        issued = DP._sum(to_mi.get(ln["id"]))
        done[ln["id"]] = (received, min(issued, received))
        refs[ln["id"]] = sorted(dnos - {""})
    return done, refs


def _ost_builder(mod):
    async def build(server, user, p):
        return await outstanding(server, user, mod, p)
    return build


SHOW = Filter("show", "Tampilkan", "select", (("outstanding", "Hanya outstanding"), ("all", "Semua baris")), default="outstanding")
LSTAT = Filter("status", "Status Baris", "select", tuple((s, s) for s in ("Belum Diproses", "Sebagian", "Selesai")))
OST = {
    "mro": ("Outstanding MRO", "Qty Permintaan", "Qty Dikeluarkan (MI)", "Ref. MI",
            "Baris MRO yang belum dipenuhi MI: qty permintaan − qty MI teralokasi (pemenuhan MRO existing)."),
    "ro": ("Outstanding RO", "Qty RO", "Qty Dipesan (PO)", "Ref. PO",
           "Baris RO yang belum dipesan: qty RO − qty PO teralokasi (status pemesanan RO existing)."),
    "po": ("Outstanding PO", "Qty Pesanan", "Qty Diterima (DO)", "Ref. DO",
           "Baris PO komitmen (Approved/Closed) yang belum diterima: qty PO − qty DO teralokasi."),
    "do": ("Outstanding DO → MI", "Qty Diterima (DO)", "Qty Diserahkan (MI)", "Ref. DO",
           "Barang sudah diterima via DO untuk MRO tetapi belum diserahkan via MI (per baris MRO, rantai alokasi)."),
}
for _mod, (_t, _q, _d, _r, _desc) in OST.items():
    cols = [Column("no", "No. MRO" if _mod == "do" else "No. Dokumen", width=20), Column("date", "Tanggal", "date", width=11),
            Column("division", "Divisi", width=14), Column("project", "Proyek", width=16)]
    if _mod == "po":
        cols.append(Column("supplier", "Supplier", width=18))
    cols += [Column("item_code", "Kode Barang", width=13), Column("item_name", "Nama Barang", width=22),
             Column("unit", "Satuan", width=8), Column("qty", _q, "qty", total=True, width=11),
             Column("done", _d, "qty", total=True, width=11), Column("outstanding", "Qty Outstanding", "qty", total=True, width=11),
             Column("pct", "% Selesai", "qty", width=8), Column("age", "Umur (hari)", "int", width=8),
             Column("status", "Status Baris", width=12), Column("refs", _r, width=20)]
    register(ReportSpec(
        key=f"outstanding-{_mod}", group=G, title=_t, description=_desc, builder=_ost_builder(_mod), columns=tuple(cols),
        date_basis="Periode = tanggal dokumen bisnis WIB, inklusif. Cut-off = Tanggal Akhir (default hari ini): hanya dokumen "
                   "lanjutan bertanggal ≤ cut-off yang dihitung. Umur = hari sejak tanggal dokumen s/d cut-off. Dokumen batal "
                   "tidak dihitung; pembatalan dokumen lanjutan mengembalikan outstanding.",
        filters=(F_FROM, F_TO, F_DIV, F_PROJ, *((F_SUP,) if _mod == "po" else ()), F_CAT, F_ITEM, SHOW, LSTAT),
        search_keys=("no", "division", "project", "supplier", "item_code", "item_name", "refs"),
        drill=lambda r: {"label": r.get("no"), "to": f"/{r.get('mod')}/{r.get('doc_id')}"} if r.get("doc_id") else None))


# --------------------------------------------------------------------------------------------- rekap nilai
GROUP_BY = (("supplier", "Supplier"), ("item", "Barang"), ("category", "Kategori"), ("division", "Divisi"),
            ("project", "Proyek"), ("month", "Periode Bulanan"), ("year", "Periode Tahunan"))
F_GB = Filter("group_by", "Kelompokkan", "select", GROUP_BY, default="supplier")


def _po_line_values(pl):
    """Snapshot baris PO (compute_po_totals); fallback baris lama = rumus Register DO/Traceability existing."""
    q, price = _f(pl.get("qty")), _f(pl.get("price"))
    gross = _f(pl.get("gross")) if pl.get("gross") is not None else q * price
    if pl.get("dpp") is not None:
        dpp, tax = _f(pl.get("dpp")), _f(pl.get("tax_amount"))
        total = _f(pl.get("total")) if pl.get("total") is not None else dpp + tax
    else:
        dpp = q * price - _f(pl.get("discount")); tax = 0.0; total = dpp
    net_after_disc = total if pl.get("tax_inclusive") else dpp
    return {"qty": q, "gross": gross, "discount": max(0.0, gross - net_after_disc), "dpp": dpp, "tax": tax, "total": total}


def _group_key(gb, day, sup, item, div, proj, m):
    it = m["items"].get(item) or {}
    if gb == "supplier":
        return sup or "-", (m["suppliers"].get(sup) or {}).get("name") or "(Tanpa Supplier)"
    if gb == "item":
        return item or "-", f"{it.get('code') or ''} — {it.get('name') or ''}".strip(" —") or "(Tanpa Barang)"
    if gb == "category":
        cid = it.get("category_id")
        return cid or "-", (m.get("item_categories", {}).get(cid) or {}).get("name") or it.get("category_name") or "(Tanpa Kategori)"
    if gb == "division":
        return div or "-", (m["divisions"].get(div) or {}).get("name") or "(Tanpa Divisi)"
    if gb == "project":
        return proj or "-", (m["projects"].get(proj) or {}).get("name") or "(Tanpa Proyek)"
    k = (day or "")[:7] if gb == "month" else (day or "")[:4]
    return k or "-", k or "(Tanpa Tanggal)"


async def _cat_map(server):
    return {c["id"]: c for c in await server.db.item_categories.find({}, {"_id": 0}).to_list(None) if c.get("id")}


def _line_filters_ok(p, sup, item, div, proj, m):
    it = m["items"].get(item) or {}
    return not ((p.get("supplier_id") and sup != p["supplier_id"]) or (p.get("item_id") and item != p["item_id"])
                or (p.get("category_id") and it.get("category_id") != p["category_id"])
                or (p.get("project_id") and proj != p["project_id"]) or (p.get("division_id") and div != p["division_id"]))


async def rekap_pembelian(server, user, p):
    cutoff = p.get("date_to") or today_wib()
    pos_l, m0, cats = await asyncio.gather(_docs(server, user, "po", {k: v for k, v in p.items() if k != "division_id"}, _is_commit, False),
                                           DP.maps(), _cat_map(server))
    pos = {h["id"]: h for h in pos_l}
    lines = [ln for v in (await _lines_by_doc(server, "po", list(pos))).values() for ln in v]
    al, _ = await _allocs_cut(server, [ln["id"] for ln in lines], "do", cutoff)
    m = dict(m0); m["item_categories"] = cats
    gb = p.get("group_by") or "supplier"
    agg = {}
    for ln in lines:
        h = pos[ln["po_id"]]
        sup, item, div = h.get("supplier_id"), ln.get("item_id"), h.get("division_id")
        proj = ln.get("project_id") or h.get("default_project_id")
        if not _line_filters_ok(p, sup, item, div, proj, m):
            continue
        v = _po_line_values(ln)
        rec = DP._sum(al.get(ln["id"]))
        unit_dpp = v["dpp"] / v["qty"] if v["qty"] > EPS else 0.0
        k, label = _group_key(gb, local_day(h.get("date")), sup, item, div, proj, m)
        a = agg.setdefault(k, {"group": label, "pos": set(), "lines": 0, "qty": 0.0, "gross": 0.0, "discount": 0.0, "dpp": 0.0,
                               "tax": 0.0, "total": 0.0, "qty_received": 0.0, "dpp_received": 0.0})
        a["pos"].add(h["id"]); a["lines"] += 1
        for f in ("qty", "gross", "discount", "dpp", "tax", "total"):
            a[f] += v[f]
        a["qty_received"] += rec; a["dpp_received"] += rec * unit_dpp
    out = [{"group": a["group"], "po_count": len(a["pos"]), "line_count": a["lines"], "qty": round(a["qty"], 6),
            "gross": round(a["gross"], 2), "discount": round(a["discount"], 2), "dpp": round(a["dpp"], 2), "tax": round(a["tax"], 2),
            "total": round(a["total"], 2), "qty_received": round(a["qty_received"], 6), "dpp_received": round(a["dpp_received"], 2),
            "dpp_open": round(max(0.0, a["dpp"] - a["dpp_received"]), 2)} for a in agg.values()]
    out.sort(key=lambda o: o["group"] if gb not in ("month", "year") else "~" + o["group"], reverse=gb in ("month", "year"))
    return out


async def rekap_do(server, user, p):
    dos_l, m0, cats = await asyncio.gather(_docs(server, user, "do", {k: v for k, v in p.items() if k != "division_id"}, None, False),
                                           DP.maps(), _cat_map(server))
    dos = {h["id"]: h for h in dos_l}
    lines = [ln for v in (await _lines_by_doc(server, "do", list(dos))).values() for ln in v]
    pls = {x["id"]: x for x in await _find_in(server.db.po_lines, "id", {ln.get("po_line_id") for ln in lines if ln.get("po_line_id")})}
    pos = {x["id"]: x for x in await _find_in(server.db.po, "id", {x.get("po_id") for x in pls.values() if x.get("po_id")})}
    m = dict(m0); m["item_categories"] = cats
    gb = p.get("group_by") or "supplier"
    agg = {}
    for ln in lines:
        h, pl = dos[ln["do_id"]], pls.get(ln.get("po_line_id")) or {}
        po = pos.get(pl.get("po_id")) or {}
        sup, item, div = h.get("supplier_id") or po.get("supplier_id"), ln.get("item_id"), po.get("division_id")
        proj = ln.get("project_id") or pl.get("project_id") or po.get("default_project_id")
        if not _line_filters_ok(p, sup, item, div, proj, m):
            continue
        v, q = _po_line_values(pl), _f(ln.get("qty"))
        per = (lambda x: x / v["qty"] * q) if v["qty"] > EPS else (lambda x: 0.0)
        k, label = _group_key(gb, local_day(h.get("date")), sup, item, div, proj, m)
        a = agg.setdefault(k, {"group": label, "dos": set(), "pos": set(), "pls": {}, "lines": 0, "qty": 0.0, "dpp": 0.0,
                               "tax": 0.0, "total": 0.0})
        a["dos"].add(h["id"]); a["lines"] += 1
        if pl.get("po_id"):
            a["pos"].add(pl["po_id"])
        if pl.get("id"):
            a["pls"][pl["id"]] = v["dpp"]  # komitmen per baris PO dihitung SEKALI walau multi-DO
        a["qty"] += q; a["dpp"] += per(v["dpp"]); a["tax"] += per(v["tax"]); a["total"] += per(v["dpp"]) + per(v["tax"])
    out = []
    for a in agg.values():
        commit = sum(a["pls"].values())
        out.append({"group": a["group"], "do_count": len(a["dos"]), "po_count": len(a["pos"]), "line_count": a["lines"],
                    "qty": round(a["qty"], 6), "dpp": round(a["dpp"], 2), "tax": round(a["tax"], 2), "total": round(a["total"], 2),
                    "po_dpp": round(commit, 2), "pct": round(a["dpp"] / commit * 100.0, 1) if commit > EPS else 0.0})
    out.sort(key=lambda o: o["group"] if gb not in ("month", "year") else "~" + o["group"], reverse=gb in ("month", "year"))
    return out


_RF = (F_FROM, F_TO, F_GB, F_SUP, F_ITEM, F_CAT, F_DIV, F_PROJ)
_RS = ("group",)
register(ReportSpec(
    key="rekap-pembelian", group=G, title="Rekap Pembelian (Komitmen PO)",
    description="Komitmen PO Approved/Closed per Supplier/Barang/Kategori/Divisi/Proyek/Periode: qty, bruto, diskon, DPP, PPN, "
                "total; dibandingkan DPP yang sudah diterima via DO.",
    date_basis="Periode = tanggal PO bisnis WIB, inklusif. Nilai = snapshot baris PO existing (tanpa formula baru). DPP diterima "
               "= qty DO teralokasi (≤ Tanggal Akhir) × DPP per unit baris PO.",
    builder=rekap_pembelian,
    columns=(Column("group", "Kelompok", width=26), Column("po_count", "Jumlah PO", "int", total=True, width=9),
             Column("line_count", "Jumlah Baris", "int", total=True, width=9), Column("qty", "Qty Dipesan", "qty", total=True, width=11),
             Column("gross", "Nilai Bruto", "money", price=True, total=True, width=15),
             Column("discount", "Diskon", "money", price=True, total=True, width=13),
             Column("dpp", "DPP (Sebelum PPN)", "money", price=True, total=True, width=15),
             Column("tax", "PPN", "money", price=True, total=True, width=13),
             Column("total", "Total Termasuk PPN", "money", price=True, total=True, width=15),
             Column("qty_received", "Qty Diterima (DO)", "qty", total=True, width=11),
             Column("dpp_received", "DPP Diterima (DO)", "money", price=True, total=True, width=15),
             Column("dpp_open", "DPP Belum Diterima", "money", price=True, total=True, width=15)),
    filters=_RF, search_keys=_RS))
register(ReportSpec(
    key="rekap-nilai-do", group=G, title="Rekap Nilai Penerimaan DO",
    description="Realisasi penerimaan DO per Supplier/Barang/Kategori/Divisi/Proyek/Periode: DPP (basis utama), PPN, dan total "
                "terpisah, dibandingkan komitmen DPP baris PO terkait.",
    date_basis="Periode = tanggal DO bisnis WIB, inklusif; DO batal tidak dihitung. Nilai = qty diterima × DPP/PPN per unit baris "
               "PO (rumus Register DO). Komitmen PO = DPP baris PO yang diterima pada periode, dihitung sekali per baris PO.",
    builder=rekap_do,
    columns=(Column("group", "Kelompok", width=26), Column("do_count", "Jumlah DO", "int", total=True, width=9),
             Column("po_count", "Jumlah PO", "int", total=True, width=9), Column("line_count", "Jumlah Baris", "int", total=True, width=9),
             Column("qty", "Qty Diterima", "qty", total=True, width=11),
             Column("dpp", "DPP Diterima (Sebelum PPN)", "money", price=True, total=True, width=16),
             Column("tax", "PPN", "money", price=True, total=True, width=13),
             Column("total", "Total Termasuk PPN", "money", price=True, total=True, width=15),
             Column("po_dpp", "DPP Komitmen PO Terkait", "money", price=True, total=True, width=16),
             Column("pct", "% Realisasi DPP", "qty", price=True, width=9)),
    filters=_RF, search_keys=_RS))
