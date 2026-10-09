"""Laporan kelompok Procurement pada Pusat Laporan. P0: MRO Traceability (migrasi; endpoint lama tetap)."""
from __future__ import annotations

import report_trace_detail as RTD
from reporting.registry import Column, Filter, ReportSpec, register

STATUS = (("Open", "Open"), ("Partial", "Partial"), ("Completed", "Completed"))


def _flat(r):
    j = RTD._join_refs
    return {
        "mro_id": r.get("mro_id"), "item_code": r.get("item_code"), "item_name": r.get("item_name"),
        "category": r.get("category"), "unit": r.get("unit"),
        "mro_date": j(r.get("mro_refs"), "date"), "mro_no": j(r.get("mro_refs"), "no"), "request": r.get("request"),
        "ro_date": j(r.get("ro_refs"), "date"), "ro_no": j(r.get("ro_refs"), "no"), "qty_ro": r.get("qty_ro"),
        "po_date": j(r.get("po_refs"), "date"), "po_no": j(r.get("po_refs"), "no"), "qty_po": r.get("qty_po"),
        "po_gross": r.get("po_gross"), "po_discount": r.get("po_discount"), "po_dpp": r.get("po_dpp"),
        "po_tax": r.get("po_tax"), "po_total": r.get("po_total"),
        "do_date": j(r.get("do_refs"), "date"), "do_no": j(r.get("do_refs"), "no"), "qty_received": r.get("qty_received"),
        "do_total": r.get("do_total"),
        "mi_date": j(r.get("mi_refs"), "date"), "mi_no": j(r.get("mi_refs"), "no"), "qty_mi": r.get("qty_mi"),
        "outstanding": r.get("outstanding"), "status": r.get("status"),
    }


async def mro_traceability(server, user, p):
    # Rantai builder existing (scope divisi + koreksi finansial) -> identik dengan endpoint lama.
    rows = await RTD._build_rows(server, p.get("date_from"), p.get("date_to"), user)
    if p.get("division_id"):  # sudah divalidasi dalam cakupan oleh report_center.parse_params
        ids = {m["id"] for m in await server.db.mro.find({"division_id": p["division_id"]}, {"_id": 0, "id": 1}).to_list(None)}
        rows = [r for r in rows if r.get("mro_id") in ids]
    if p.get("item_id"):  # P2a: filter barang & kategori (pasca-scope; aturan visibilitas existing tetap)
        rows = [r for r in rows if r.get("item_id") == p["item_id"]]
    if p.get("category_id"):
        iids = {i["id"] for i in await server.db.items.find({"category_id": p["category_id"]}, {"_id": 0, "id": 1}).to_list(None)}
        rows = [r for r in rows if r.get("item_id") in iids]
    out = [_flat(r) for r in rows]
    if p.get("status"):
        out = [r for r in out if r["status"] == p["status"]]
    return out


register(ReportSpec(
    key="mro-traceability", group="procurement", title="MRO Traceability",
    description="Telusur per barang dari MRO ke RO, PO, DO, dan MI beserta outstanding.",
    date_basis="Tanggal dokumen MRO (WIB), inklusif.", builder=mro_traceability,
    columns=(
        Column("item_code", "Kode Barang", width=15), Column("item_name", "Nama Barang", width=28),
        Column("category", "Kategori", width=18), Column("unit", "Satuan", width=10),
        Column("mro_date", "Tanggal MRO", "date", width=13), Column("mro_no", "No. MRO", width=22),
        Column("request", "Qty MRO", "qty", total=True, width=11),
        Column("ro_date", "Tanggal RO", "date", width=13), Column("ro_no", "No. RO", width=22),
        Column("qty_ro", "Qty RO", "qty", total=True, width=11),
        Column("po_date", "Tanggal PO", "date", width=13), Column("po_no", "No. PO", width=22),
        Column("qty_po", "Qty PO", "qty", total=True, width=11),
        Column("po_gross", "Nilai PO", "money", price=True, total=True, width=15),
        Column("po_discount", "Diskon PO", "money", price=True, total=True, width=14),
        Column("po_dpp", "DPP PO", "money", price=True, total=True, width=15),
        Column("po_tax", "Pajak PO", "money", price=True, total=True, width=14),
        Column("po_total", "Total PO", "money", price=True, total=True, width=15),
        Column("do_date", "Tanggal DO", "date", width=13), Column("do_no", "No. DO", width=22),
        Column("qty_received", "Qty DO", "qty", total=True, width=11),
        Column("do_total", "Total DO (DPP x Qty Diterima)", "money", price=True, total=True, width=18),
        Column("mi_date", "Tanggal MI", "date", width=13), Column("mi_no", "No. MI", width=22),
        Column("qty_mi", "Qty MI", "qty", total=True, width=11),
        Column("outstanding", "Outstanding", "qty", total=True, width=12), Column("status", "Status", width=11),
    ),
    filters=(Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date"),
             Filter("division_id", "Divisi", "division"), Filter("status", "Status", "select", STATUS),
             Filter("item_id", "Barang", "item"), Filter("category_id", "Kategori", "category")),
    search_keys=("item_code", "item_name", "category", "mro_no", "ro_no", "po_no", "do_no", "mi_no"),
    drill=lambda r: {"label": r.get("mro_no"), "to": f"/mro/{r.get('mro_id')}"} if r.get("mro_id") else None,
    legacy=("/api/reports/mro-traceability", "/api/reports/mro-traceability/export.xlsx"),
))
