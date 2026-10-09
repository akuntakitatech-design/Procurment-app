"""P2a — Reporting Operasional Procurement pada Pusat Laporan (READ-ONLY).

Tidak menduplikasi aturan existing:
  - Register MRO/RO/PO/DO/MI memakai enrichment daftar dokumen existing (`receipt_control_layer.enrich_list`: telusur
    MRO/RO/PO, divisi, proyek, SPK, unit, status dokumen PO) + aturan visibilitas daftar/Dashboard
    (`server.ACCESS_FILTER_VISIBLE`) + helper status existing (`doc_procurement.mro_status` / `ro_status`).
  - Lead Time memakai rantai builder MRO Traceability (`report_trace_detail._build_rows` + scope divisi + koreksi
    finansial) -> satu sumber dengan MRO Traceability; granularitas per MRO × barang (bukan hanya dokumen pertama header).
  - Pemakaian Barang per Unit/Proyek memakai sumber & scope P1 (valuation ledger entri MI net Reversal MI, satuan dasar
    barang; scope `stock_summary.compute`) -> konsisten dengan Mutasi (Pemakaian MI) & Rekap HPP MI.
Nilai PO (bruto/diskon/DPP/pajak/total), Nilai DO, dan HPP MI dipisah (tidak dijumlahkan) dan hanya untuk
`view_purchase_price` (kolom price=True dibuang server-side di JSON/Excel/PDF/total).
"""
from __future__ import annotations

from datetime import date

import doc_procurement as DP
import receipt_control_layer as RC
import report_control_scope_layer as RCS
import report_trace_detail as RTD
from reporting import reports_inventory as RI
from reporting.registry import Column, Filter, ReportSpec, register
from reporting.scope import local_day

G = "procurement"
F_FROM, F_TO = Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date")
F_DIV, F_PROJ = Filter("division_id", "Divisi", "division"), Filter("project_id", "Proyek", "project")
F_SUP = Filter("supplier_id", "Supplier", "supplier")
F_ITEM, F_CAT = Filter("item_id", "Barang", "item"), Filter("category_id", "Kategori", "category")
DOC_COLL = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi"}
PO_BASE = ("Draft", "Waiting Approval", "Approved", "Closed", "Rejected", "Cancelled")  # receipt_control_layer.document_status
PO_RECEIPT = ("Belum Diterima", "Diterima Sebagian", "Diterima Penuh", "Over Receipt")    # receipt_control_layer.receipt_status


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _in_period(day, p) -> bool:
    return (not p.get("date_from") or day >= p["date_from"]) and (not p.get("date_to") or day <= p["date_to"])


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days if a and b else None
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------- register
async def _visible(server, user, mod, rows):
    fv = getattr(server, "ACCESS_FILTER_VISIBLE", None)
    if fv:
        return await fv(mod, rows, user)
    return [r for r in rows if RCS._division_allowed(server, user, r.get("division_id"))]


async def register_rows(server, user, mod, p):
    """Dokumen dalam periode (tanggal dokumen WIB) + enrichment & visibilitas daftar existing (tanpa batas jumlah)."""
    docs = await getattr(server.db, DOC_COLL[mod]).find({}, {"_id": 0}).to_list(None)
    docs = [d for d in docs if _in_period(local_day(d.get("date")), p)]
    rows = await _visible(server, user, mod, await RC.enrich_list(server, mod, docs) if docs else [])
    if p.get("division_id"):
        rows = [r for r in rows if r.get("division_id") == p["division_id"] or p["division_id"] in (r.get("trace_division_ids") or [])]
    if p.get("project_id"):
        rows = [r for r in rows if p["project_id"] in (r.get("trace_project_ids") or [])]
    if p.get("supplier_id"):
        rows = [r for r in rows if r.get("supplier_id") == p["supplier_id"]]
    m = await DP.maps()
    lines = await DP.lines_by_doc(f"{mod}_lines", f"{mod}_id", [r["id"] for r in rows])
    nm = lambda coll, i: (m[coll].get(i) or {}).get("name") if i else None  # noqa: E731
    if mod == "mro":
        mon = await DP.mro_monitor_batch([ln for v in lines.values() for ln in v])
    elif mod == "ro":
        ordered = await DP.allocs_from([ln["id"] for v in lines.values() for ln in v], "po")
    elif mod == "do":
        pol = {x["id"]: x for x in await server.db.po_lines.find(
            {"id": {"$in": sorted({ln.get("po_line_id") for v in lines.values() for ln in v if ln.get("po_line_id")})}},
            {"_id": 0}).to_list(None)} if lines else {}
        pos = {x["id"]: x.get("no") for x in await server.db.po.find({}, {"_id": 0, "id": 1, "no": 1}).to_list(None)}
    elif mod == "mi":
        hpp = {}
        if rows:
            for e in await server.db.valuation_ledger.find({"doc_id": {"$in": [r["id"] for r in rows]}}, {"_id": 0}).to_list(None):
                if RI.cat_of(e.get("doc_type")) == "mi":
                    hpp[e["doc_id"]] = hpp.get(e["doc_id"], 0.0) + _f(e.get("value_out")) - _f(e.get("value_in"))
    out = []
    for r in rows:
        ls = lines.get(r["id"], [])
        o = {"id": r["id"], "mod": mod, "no": r.get("no"), "date": local_day(r.get("date")),
             "division": r.get("trace_division") or nm("divisions", r.get("division_id")) or "-",
             "project": r.get("trace_project") or "-", "line_count": len(ls), "notes": r.get("notes") or ""}
        if mod == "mro":
            o.update(need_date=r.get("need_date"), requester=r.get("requester"), department=r.get("department"),
                     warehouse=r.get("trace_warehouse") or "-", unit=r.get("trace_unit") or "-",
                     status=DP.mro_status([mon[ln["id"]] for ln in ls], r.get("cancelled"), r.get("submitted", True)))
        elif mod == "ro":
            st = [{"qty": ln.get("qty", 0), "ordered": DP._sum(ordered.get(ln["id"])),
                   "outstanding": max(0, ln.get("qty", 0) - DP._sum(ordered.get(ln["id"])))} for ln in ls]
            o.update(requester=r.get("requester") or r.get("trace_requester"), mro_refs=r.get("trace_mro") or "-",
                     status=DP.ro_status(st, r.get("cancelled"), r.get("submitted", True)))
        elif mod == "po":
            disc = _f(r.get("item_discount_total")) + _f(r.get("final_discount_amount"))
            o.update(supplier=nm("suppliers", r.get("supplier_id")) or "-", eta=r.get("eta"), ro_refs=r.get("trace_ro") or "-",
                     mro_refs=r.get("trace_mro") or "-", spk=r.get("trace_spk") or "-",
                     status=r.get("document_status") or r.get("status"), receipt_status=r.get("receipt_status") or "-",
                     status_filter=(lambda st: st if st in PO_BASE else "Waiting Approval")(r.get("document_status") or r.get("status")),
                     gross=_f(r.get("gross_total")), discount=round(disc, 2),
                     dpp=_f(r.get("subtotal_after_discount") if r.get("subtotal_after_discount") is not None else r.get("subtotal_after_item_discount")),
                     tax=_f(r.get("tax_total")), grand_total=_f(r.get("grand_total")))
        elif mod == "do":
            val = 0.0
            for ln in ls:  # Nilai DO = qty diterima × DPP per unit baris PO (rumus MRO Traceability existing)
                pl = pol.get(ln.get("po_line_id")) or {}
                q = _f(pl.get("qty"))
                dpp = _f(pl.get("dpp")) if pl.get("dpp") is not None else q * _f(pl.get("price")) - _f(pl.get("discount"))
                val += (dpp / q) * _f(ln.get("qty")) if q > 0 else 0.0
            o.update(supplier=nm("suppliers", r.get("supplier_id")) or "-", supplier_dn=r.get("supplier_dn") or "-",
                     supplier_invoice=r.get("supplier_invoice") or "-",
                     po_refs=", ".join(sorted({pos.get(ln.get("po_id")) or "" for ln in ls} - {""})) or "-",
                     warehouse=r.get("trace_warehouse") or "-", spk=r.get("trace_spk") or "-",
                     status=r.get("status") or "-", do_value=round(val, 2))
        else:
            o.update(source=r.get("source_type") or "-", receiver=r.get("receiver"), department=r.get("department"),
                     warehouse=r.get("trace_warehouse") or "-", unit=r.get("trace_unit") or "-", spk=r.get("trace_spk") or "-",
                     mro_refs=r.get("trace_mro") or "-", status=r.get("status") or "-", hpp=round(hpp.get(r["id"], 0.0), 2))
        out.append(o)
    if p.get("status"):  # PO: kelompok status dasar (tahap approval dinamis -> Waiting Approval)
        out = [o for o in out if o.get("status_filter", o.get("status")) == p["status"]]
    if p.get("receipt_status"):
        out = [o for o in out if o.get("receipt_status") == p["receipt_status"]]
    out.sort(key=lambda o: (o["date"] or "", o["no"] or ""), reverse=True)
    return out


def _reg_builder(mod):
    async def build(server, user, p):
        return await register_rows(server, user, mod, p)
    return build


def _drill(r):
    return {"label": r.get("no"), "to": f"/{r.get('mod')}/{r.get('id')}"} if r.get("id") else None


C_NO, C_DATE = Column("no", "No. Dokumen", width=20), Column("date", "Tanggal", "date", width=11)
C_DIV, C_PROJ = Column("division", "Divisi", width=16), Column("project", "Proyek", width=18)
C_LINES, C_STATUS = Column("line_count", "Jumlah Baris", "int", total=True, width=10), Column("status", "Status", width=14)
SEARCH = ("no", "division", "project", "requester", "department", "supplier", "supplier_dn", "supplier_invoice",
          "mro_refs", "ro_refs", "po_refs", "spk", "unit", "warehouse", "receiver", "notes")
REG_DESC = {
    "mro": "Daftar MRO: pemohon, departemen, proyek, gudang, unit, jumlah baris, dan status pemenuhan.",
    "ro": "Daftar RO beserta referensi MRO, proyek, jumlah baris, dan status pemesanan (PO).",
    "po": "Daftar PO per supplier: referensi RO, SPK, ETA, nilai bruto/diskon/DPP/pajak/total, status & penerimaan.",
    "do": "Daftar penerimaan DO per supplier: referensi PO, surat jalan, invoice supplier, gudang, dan nilai DO.",
    "mi": "Daftar pengeluaran barang (MI): sumber, referensi MRO, penerima, proyek, unit, SPK, gudang, dan HPP.",
}
REGISTERS = {
    "mro": ("Register MRO", (C_NO, C_DATE, Column("need_date", "Tgl Dibutuhkan", "date", width=11), C_DIV,
                             Column("requester", "Pemohon", width=16), Column("department", "Departemen", width=14), C_PROJ,
                             Column("warehouse", "Gudang", width=16), Column("unit", "Unit", width=14), C_LINES, C_STATUS),
            ("Draft", "Open", "Partial", "Completed", "Cancelled"), ()),
    "ro": ("Register RO", (C_NO, C_DATE, C_DIV, Column("requester", "Pemohon", width=16),
                           Column("mro_refs", "Ref. MRO", width=20), C_PROJ, C_LINES, C_STATUS),
           ("Draft", "Open", "Partial Ordered", "Fully Ordered", "Cancelled"), ()),
    "po": ("Register PO", (C_NO, C_DATE, Column("supplier", "Supplier", width=20), C_DIV, C_PROJ,
                           Column("ro_refs", "Ref. RO", width=18), Column("spk", "SPK", width=14), Column("eta", "ETA", "date", width=11),
                           C_LINES, Column("gross", "Nilai Bruto", "money", price=True, total=True, width=15),
                           Column("discount", "Diskon", "money", price=True, total=True, width=13),
                           Column("dpp", "DPP", "money", price=True, total=True, width=15),
                           Column("tax", "Pajak", "money", price=True, total=True, width=13),
                           Column("grand_total", "Total PO", "money", price=True, total=True, width=15),
                           C_STATUS, Column("receipt_status", "Status Penerimaan", width=14)),
           PO_BASE, (F_SUP, Filter("receipt_status", "Status Penerimaan", "select", tuple((s, s) for s in PO_RECEIPT)))),
    "do": ("Register DO", (C_NO, C_DATE, Column("supplier", "Supplier", width=20), Column("po_refs", "Ref. PO", width=18),
                           Column("supplier_dn", "Surat Jalan", width=14), Column("supplier_invoice", "Invoice Supplier", width=14),
                           C_DIV, C_PROJ, Column("warehouse", "Gudang", width=16), Column("spk", "SPK", width=14), C_LINES,
                           Column("do_value", "Nilai DO (DPP × Qty Diterima)", "money", price=True, total=True, width=16), C_STATUS),
           ("Posted", "Cancelled"), (F_SUP,)),
    "mi": ("Register MI", (C_NO, C_DATE, C_DIV, Column("source", "Sumber", width=9), Column("mro_refs", "Ref. MRO", width=18),
                           Column("receiver", "Penerima", width=14), Column("department", "Departemen", width=14), C_PROJ,
                           Column("unit", "Unit", width=14), Column("spk", "SPK", width=14), Column("warehouse", "Gudang", width=16),
                           C_LINES, Column("hpp", "HPP MI", "money", price=True, total=True, width=15), C_STATUS),
           ("Posted", "Cancelled"), ()),
}
for _mod, (_title, _cols, _status, _extra) in REGISTERS.items():
    register(ReportSpec(
        key=f"register-{_mod}", group=G, title=_title, description=REG_DESC[_mod], date_basis="Tanggal dokumen bisnis WIB, inklusif. "
        "Status = status dokumen saat ini (sama dengan daftar dokumen).", builder=_reg_builder(_mod), columns=_cols,
        filters=(F_FROM, F_TO, F_DIV, F_PROJ, *_extra, Filter("status", "Status", "select", tuple((s, s) for s in _status))),
        search_keys=SEARCH, drill=_drill))


# ----------------------------------------------------------------------------------------------- lead time
async def lead_time(server, user, p):
    rows = await RTD._build_rows(server, p.get("date_from"), p.get("date_to"), user)  # rantai MRO Traceability
    mros = {m["id"]: m for m in await server.db.mro.find({}, {"_id": 0}).to_list(None)}
    if p.get("division_id"):
        rows = [r for r in rows if (mros.get(r.get("mro_id")) or {}).get("division_id") == p["division_id"]]
    lines = await server.db.mro_lines.find({"mro_id": {"$in": sorted({r.get("mro_id") for r in rows})}}, {"_id": 0}).to_list(None) if rows else []
    proj = {}
    for ln in lines:
        proj.setdefault((ln.get("mro_id"), ln.get("item_id")), set()).add(ln.get("project_id") or (mros.get(ln.get("mro_id")) or {}).get("default_project_id"))
    po_ids = sorted({x["id"] for r in rows for x in r.get("po_refs") or [] if x.get("id")})
    pos = {x["id"]: x for x in await server.db.po.find({"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "supplier_id": 1}).to_list(None)} if po_ids else {}
    m = await DP.maps()
    out = []
    for r in rows:
        projects = proj.get((r.get("mro_id"), r.get("item_id")), set()) - {None}
        sups = {(pos.get(x.get("id")) or {}).get("supplier_id") for x in r.get("po_refs") or []} - {None}
        if p.get("project_id") and p["project_id"] not in projects:
            continue
        if p.get("supplier_id") and p["supplier_id"] not in sups:
            continue
        first = lambda k: (r.get(k) or [{}])[0]  # noqa: E731  (refs urut tanggal naik)
        d_mro = local_day(r.get("mro_date"))
        d_ro, d_po, d_do, d_mi = (local_day(first(k).get("date")) if first(k).get("date") else None
                                  for k in ("ro_refs", "po_refs", "do_refs", "mi_refs"))
        d_done = local_day(r["mi_refs"][-1].get("date")) if r.get("status") == "Completed" and r.get("mi_refs") else None
        out.append({"mro_id": r.get("mro_id"), "mro_no": r.get("mro_no"), "mro_date": d_mro, "item_code": r.get("item_code"),
                    "item_name": r.get("item_name"), "unit": r.get("unit"), "request": r.get("request"),
                    "project": ", ".join(sorted(filter(None, ((m["projects"].get(x) or {}).get("name") for x in projects)))) or "-",
                    "supplier": ", ".join(sorted(filter(None, ((m["suppliers"].get(x) or {}).get("name") for x in sups)))) or "-",
                    "ro_date": d_ro, "po_date": d_po, "do_date": d_do, "mi_date": d_mi, "done_date": d_done,
                    "mro_to_ro": _days(d_mro, d_ro), "ro_to_po": _days(d_ro, d_po), "po_to_do": _days(d_po, d_do),
                    "do_to_mi": _days(d_do, d_mi), "mro_to_mi": _days(d_mro, d_mi), "mro_to_done": _days(d_mro, d_done),
                    "status": r.get("status")})
    if p.get("status"):
        out = [o for o in out if o["status"] == p["status"]]
    return out


register(ReportSpec(
    key="lead-time", group=G, title="Lead Time Procurement",
    description="Selisih hari MRO → RO → PO → DO → MI per MRO × barang (dokumen pertama tiap tahap) dan hari s/d selesai.",
    date_basis="Periode = tanggal MRO bisnis WIB, inklusif. Sumber = rantai MRO Traceability (scope sama). "
               "Hari = tanggal dokumen pertama tahap berikut − tahap sebelumnya; kosong = tahap belum terjadi.",
    builder=lead_time,
    columns=(Column("mro_no", "No. MRO", width=20), Column("mro_date", "Tanggal MRO", "date", width=11),
             Column("item_code", "Kode Barang", width=13), Column("item_name", "Nama Barang", width=24),
             Column("unit", "Satuan", width=8), Column("request", "Qty MRO", "qty", total=True, width=9),
             Column("project", "Proyek", width=16), Column("supplier", "Supplier", width=18),
             Column("ro_date", "RO Pertama", "date", width=11), Column("po_date", "PO Pertama", "date", width=11),
             Column("do_date", "DO Pertama", "date", width=11), Column("mi_date", "MI Pertama", "date", width=11),
             Column("mro_to_ro", "Hari MRO→RO", "int", width=9), Column("ro_to_po", "Hari RO→PO", "int", width=9),
             Column("po_to_do", "Hari PO→DO", "int", width=9), Column("do_to_mi", "Hari DO→MI", "int", width=9),
             Column("mro_to_mi", "Hari MRO→MI", "int", width=9), Column("done_date", "Tanggal Selesai", "date", width=11),
             Column("mro_to_done", "Hari s/d Selesai", "int", width=10), Column("status", "Status", width=11)),
    filters=(F_FROM, F_TO, F_DIV, F_PROJ, F_SUP, Filter("status", "Status", "select",
                                                        (("Open", "Open"), ("Partial", "Partial"), ("Completed", "Completed")))),
    search_keys=("mro_no", "item_code", "item_name", "project", "supplier"),
    drill=lambda r: {"label": r.get("mro_no"), "to": f"/mro/{r.get('mro_id')}"} if r.get("mro_id") else None,
    legacy=("/api/reports/lead-time",),
))


# ----------------------------------------------------------------------------------------------- pemakaian
USAGE_GROUP = (("unit", "Unit"), ("project", "Proyek"))


async def pemakaian(server, user, p):
    sc = await RI.scope(server, user, p)
    rows = [r for r in RI.inherit_reversal_attrs(await RI._rows(server, "valuation_ledger", sc))
            if RI.cat_of(r.get("doc_type")) == "mi" and RI._in_period(r, p)]
    for k in ("project_id", "unit_id"):
        if p.get(k):
            rows = [r for r in rows if r.get(k) == p[k]]
    gb = p.get("group_by") or "unit"
    names = {x["id"]: x for x in await getattr(server.db, "units" if gb == "unit" else "projects").find({}, {"_id": 0}).to_list(None) if x.get("id")}
    agg = {}
    for r in rows:
        gid = r.get(f"{gb}_id") or "-"
        a = agg.setdefault((gid, r["item_id"]), {"docs": set(), "qty": 0.0, "hpp": 0.0})
        a["docs"].add(r.get("doc_id")); a["qty"] += _f(r.get("qty_out")) - _f(r.get("qty_in"))
        a["hpp"] += _f(r.get("value_out")) - _f(r.get("value_in"))
    out = []
    for (gid, iid), a in agg.items():
        if abs(a["qty"]) <= 1e-9 and abs(a["hpp"]) <= 1e-6:
            continue  # MI dibatalkan penuh (net reversal 0)
        g, it = names.get(gid) or {}, sc["items"].get(iid, {})
        label = (g.get("plate_no") or g.get("code") or "") if gb == "unit" else (g.get("code") or "")
        out.append({"group_code": label, "group_name": g.get("name") or f"(Tanpa {dict(USAGE_GROUP)[gb]})",
                    "item_code": it.get("code"), "item_name": it.get("name"), "category": it.get("category_label"),
                    "base_unit": it.get("unit_label"), "doc_count": len(a["docs"]), "qty": round(a["qty"], 6),
                    "hpp": round(a["hpp"], 4)})
    out.sort(key=lambda o: (o["group_name"].lower(), str(o["item_name"] or "").lower()))
    return out


register(ReportSpec(
    key="pemakaian-barang", group=G, title="Pemakaian Barang per Unit/Proyek",
    description="Qty pemakaian MI (satuan dasar barang, net pembatalan/reversal) per Unit atau Proyek × barang; HPP terpisah.",
    date_basis="Periode = tanggal MI bisnis WIB, inklusif. Sumber = valuation ledger entri MI (sama dengan Mutasi & Rekap HPP MI). "
               "Cakupan = aturan Inventory.",
    builder=pemakaian,
    columns=(Column("group_code", "Kode/No. Polisi", width=13), Column("group_name", "Unit/Proyek", width=22),
             Column("item_code", "Kode Barang", width=13), Column("item_name", "Nama Barang", width=24),
             Column("category", "Kategori", width=14), Column("base_unit", "Satuan Dasar", width=9),
             Column("doc_count", "Jumlah MI", "int", width=9), Column("qty", "Qty Pemakaian", "qty", total=True, width=12),
             Column("hpp", "HPP Pemakaian", "money", price=True, total=True, width=15)),
    filters=(F_FROM, F_TO, Filter("group_by", "Kelompokkan", "select", USAGE_GROUP, default="unit"),
             Filter("unit_id", "Unit", "unit"), F_PROJ, F_DIV, Filter("warehouse_id", "Gudang", "warehouse"), F_CAT, F_ITEM),
    search_keys=("group_code", "group_name", "item_code", "item_name", "category"),
    legacy=("/api/reports/unit-usage",),
))
