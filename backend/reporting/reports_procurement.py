"""Laporan kelompok Procurement pada Pusat Laporan. P0: PO Traceability (dulu "MRO Traceability";
satu sumber dengan endpoint lama `/api/reports/mro-traceability` yang tetap memakai tanggal MRO)."""
from __future__ import annotations

import report_trace_detail as RTD
import receipt_control_layer as RC
from reporting.registry import Column, Filter, ReportSpec, register

STATUS = (("Open", "Open"), ("Partial", "Partial"), ("Completed", "Completed"))
# Status penerimaan (DO) — terpisah dari status MI.
STATUS_DO = (("Diterima", "Diterima"), ("Diterima Sebagian", "Diterima Sebagian"),
             ("Belum Diterima", "Belum Diterima"), ("-", "Tanpa PO"))

# Status DOKUMEN PO — memakai definisi existing `receipt_control_layer` (sama dengan daftar/detail PO),
# hanya labelnya diterjemahkan. Tahap "Waiting Approval" dipecah Approval 1 / Approval 2 oleh
# `display_document_status` + `po_approval_stage_map`; "Closed" = penerimaan penuh (PO ditutup).
PO_STATUS_LABEL = {
    "Draft": "Draft",
    RC.DOC_WAITING_A1: "Menunggu Approval 1",
    RC.DOC_READY_A2: "Siap Approval 2",
    RC.DOC_WAITING_A2: "Menunggu Approval 2",
    "Waiting Approval": "Menunggu Approval",
    "Approved": "Disetujui",
    "Closed": "Ditutup",
    "Revision": "Revisi",
    "Rejected": "Ditolak",
    "Cancelled": "Dibatalkan",
}
PO_STATUS = tuple((label, label) for label in PO_STATUS_LABEL.values())
_PO_STATUS_ORDER = {label: i for i, label in enumerate(PO_STATUS_LABEL.values())}


def _po_status_text(labels):
    """Gabungan label status PO pada satu baris (satu baris bisa memuat beberapa PO)."""
    uniq = [x for x in dict.fromkeys(labels) if x]
    if not uniq:
        return "-"
    return ", ".join(sorted(uniq, key=lambda x: (_PO_STATUS_ORDER.get(x, 99), x)))


async def _po_status_map(server, rows):
    """{po_id: label status dokumen} untuk seluruh PO yang dirujuk baris.

    Sumber = definisi existing (`po_receipt_batch` + `po_approval_stage_map` + `display_document_status`),
    tanpa rumus baru dan tanpa menulis apa pun.
    """
    ids = sorted({ref.get("id") for r in rows for ref in (r.get("po_refs") or []) if ref.get("id")})
    if not ids:
        return {}
    docs = await server.db.po.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids))
    batch, _rec, _per = await RC.po_receipt_batch(server, docs)
    stages = await RC.po_approval_stage_map(server, docs)
    out = {}
    for po in docs:
        st = batch.get(po.get("id")) or {}
        status = RC.display_document_status(po, st.get("document_status"), stages.get(po.get("id")))
        out[po["id"]] = PO_STATUS_LABEL.get(status, status)
    return out


def _flat(r):
    j = RTD._join_refs
    qty_po = r.get("qty_po")
    gross = r.get("po_gross")
    ordered = float(qty_po or 0)
    received = float(r.get("qty_received") or 0)
    # Harga satuan PO = Nilai PO (sebelum diskon) / Qty PO. None bila kolom harga disembunyikan.
    unit_price = (gross / ordered) if (gross is not None and ordered > 0) else None
    # Status penerimaan (DO): menjawab "PO sudah diterima atau belum" — terpisah dari status MI di bawah.
    do_status = ("-" if ordered <= 0 else
                 "Belum Diterima" if received <= 0 else
                 "Diterima Sebagian" if received + 1e-9 < ordered else
                 "Diterima")
    return {
        "mro_id": r.get("mro_id"), "item_code": r.get("item_code"), "item_name": r.get("item_name"),
        "category": r.get("category"), "unit": r.get("unit"), "spk_no": r.get("spk_no"),
        "project_name": r.get("project_name"),
        "mro_date": j(r.get("mro_refs"), "date"), "mro_no": j(r.get("mro_refs"), "no"), "request": r.get("request"),
        "ro_date": j(r.get("ro_refs"), "date"), "ro_no": j(r.get("ro_refs"), "no"), "qty_ro": r.get("qty_ro"),
        "po_date": j(r.get("po_refs"), "date"), "supplier_name": r.get("supplier_name"),
        "po_no": j(r.get("po_refs"), "no"),
        "po_status": _po_status_text(r.get("_po_statuses") or []),
        "po_status_list": r.get("_po_statuses") or [],
        "qty_po": r.get("qty_po"), "po_unit_price": unit_price,
        "po_gross": r.get("po_gross"), "po_discount": r.get("po_discount"), "po_dpp": r.get("po_dpp"),
        "po_tax": r.get("po_tax"), "po_total": r.get("po_total"),
        "do_date": j(r.get("do_refs"), "date"), "do_no": j(r.get("do_refs"), "no"), "qty_received": r.get("qty_received"),
        "do_total": r.get("do_total"), "do_status": do_status,
        "inv_date": r.get("inv_date"), "inv_no": r.get("inv_no"), "qty_invoice": r.get("qty_invoice"),
        "inv_total": r.get("inv_total"),
        "mi_date": j(r.get("mi_refs"), "date"), "mi_no": j(r.get("mi_refs"), "no"), "qty_mi": r.get("qty_mi"),
        "outstanding": r.get("outstanding"), "status": r.get("status"),
    }


def _po_dates(r):
    """Tanggal PO pada satu baris (YYYY-MM-DD), dari hasil gabungan ref PO."""
    return [str((x or {}).get("date") or "")[:10] for x in (r.get("po_refs") or [])]


def _has_po_in_period(r, date_from, date_to):
    """True bila minimal satu PO pada baris jatuh di periode — dasar tanggal laporan = tanggal PO."""
    for d in _po_dates(r):
        if d and (not date_from or d >= date_from) and (not date_to or d <= date_to):
            return True
    return False


async def mro_traceability(server, user, p):
    # Rantai builder existing (scope divisi + koreksi finansial) -> identik dengan endpoint lama.
    # Dasar tanggal laporan = TANGGAL PO: rantai dibangun tanpa batas tanggal MRO (PO bisa lebih tua /
    # lebih baru dari tanggal MRO karena koreksi & backdate), lalu baris disaring lewat tanggal PO-nya.
    rows = await RTD._build_rows(server, None, None, user)
    date_from, date_to = p.get("date_from"), p.get("date_to")
    if date_from or date_to:  # periode kosong = "Semua data" (termasuk barang yang belum dipesan)
        rows = [r for r in rows if _has_po_in_period(r, date_from, date_to)]
    if p.get("division_id"):  # sudah divalidasi dalam cakupan oleh report_center.parse_params
        ids = {m["id"] for m in await server.db.mro.find({"division_id": p["division_id"]}, {"_id": 0, "id": 1}).to_list(None)}
        rows = [r for r in rows if r.get("mro_id") in ids]
    if p.get("item_id"):  # P2a: filter barang & kategori (pasca-scope; aturan visibilitas existing tetap)
        rows = [r for r in rows if r.get("item_id") == p["item_id"]]
    if p.get("category_id"):
        iids = {i["id"] for i in await server.db.items.find({"category_id": p["category_id"]}, {"_id": 0, "id": 1}).to_list(None)}
        rows = [r for r in rows if r.get("item_id") in iids]
    # Status DOKUMEN PO per baris (definisi existing receipt_control_layer) — dihitung setelah semua
    # filter baris agar hanya PO yang benar-benar tampil yang di-enrich.
    status_map = await _po_status_map(server, rows)
    for r in rows:
        refs = r.get("po_refs") or []
        r["_po_statuses"] = list(dict.fromkeys(
            s for s in (status_map.get(x.get("id")) for x in refs if x.get("id")) if s))
    out = [_flat(r) for r in rows]
    if p.get("status"):
        out = [r for r in out if r["status"] == p["status"]]
    if p.get("do_status"):
        out = [r for r in out if r["do_status"] == p["do_status"]]
    if p.get("po_status"):
        out = [r for r in out if p["po_status"] in (r.get("po_status_list") or [])]
    return out


register(ReportSpec(
    key="mro-traceability", group="procurement", title="PO Traceability",
    description=("Telusur per barang dari MRO ke RO, PO, DO, dan MI beserta outstanding. "
                 "Saat periode diisi, baris masuk bila minimal satu PO-nya jatuh di periode itu "
                 "(barang tanpa PO tidak tampil)."),
    date_basis="Tanggal PO (WIB), inklusif.", builder=mro_traceability,
    columns=(
        Column("item_code", "Kode Barang", width=15), Column("item_name", "Nama Barang", width=28),
        Column("category", "Kategori", width=18), Column("unit", "Satuan", width=10),
        Column("spk_no", "No. SPK", width=18),
        Column("project_name", "Nama Proyek", width=20),
        Column("mro_date", "Tanggal MRO", "date", width=13), Column("mro_no", "No. MRO", width=22),
        Column("request", "Qty MRO", "qty", total=True, width=11),
        Column("ro_date", "Tanggal RO", "date", width=13), Column("ro_no", "No. RO", width=22),
        Column("qty_ro", "Qty RO", "qty", total=True, width=11),
        Column("po_date", "Tanggal PO", "date", width=13),
        Column("supplier_name", "Nama Supplier", width=24),
        Column("po_no", "No. PO", width=22),
        # Status dokumen PO: Draft / Menunggu Approval 1 / Menunggu Approval 2 / Disetujui / Ditutup
        # (+ Revisi, Ditolak, Dibatalkan). Satu baris bisa memuat beberapa PO -> digabung dengan koma.
        Column("po_status", "Status PO", width=20),
        Column("qty_po", "Qty PO", "qty", total=True, width=11),
        # Harga satuan = Nilai PO / Qty PO, supaya qty x harga satuan bisa dicek langsung.
        Column("po_unit_price", "Harga Satuan", "money", price=True, width=15),
        Column("po_gross", "Nilai PO", "money", price=True, total=True, width=15),
        Column("po_discount", "Diskon PO", "money", price=True, total=True, width=14),
        Column("po_dpp", "DPP PO", "money", price=True, total=True, width=15),
        Column("po_tax", "Pajak PO", "money", price=True, total=True, width=14),
        Column("po_total", "Total PO", "money", price=True, total=True, width=15),
        Column("do_date", "Tanggal DO", "date", width=13), Column("do_no", "No. DO", width=22),
        Column("qty_received", "Qty DO", "qty", total=True, width=11),
        Column("do_total", "Total DO", "money", price=True, total=True, width=18),
        # Status DO = status PENERIMAAN: apakah PO sudah diterima (Diterima / Diterima Sebagian /
        # Belum Diterima). Berbeda dari Status MI di ujung kanan yang mengikuti outstanding MI.
        Column("do_status", "Status DO", width=17),
        Column("inv_date", "Tanggal Invoice", "date", width=13), Column("inv_no", "No. Invoice", width=20),
        Column("qty_invoice", "Qty Invoice", "qty", total=True, width=11),
        Column("inv_total", "Total Invoice", "money", price=True, total=True, width=15),
        Column("mi_date", "Tanggal MI", "date", width=13), Column("mi_no", "No. MI", width=22),
        Column("qty_mi", "Qty MI", "qty", total=True, width=11),
        Column("outstanding", "Outstanding", "qty", total=True, width=12),
        # Status MI = status outstanding MI (Open / Partial / Completed): apakah qty MRO sudah
        # dikeluarkan lewat MI.
        Column("status", "Status MI", width=12),
    ),
    filters=(Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date"),
             Filter("division_id", "Divisi", "division"), Filter("status", "Status MI", "select", STATUS),
             Filter("do_status", "Status DO", "select", STATUS_DO),
             Filter("po_status", "Status PO", "select", PO_STATUS),
             Filter("item_id", "Barang", "item"), Filter("category_id", "Kategori", "category")),
    search_keys=("item_code", "item_name", "category", "mro_no", "ro_no", "po_no", "do_no", "mi_no", "inv_no", "spk_no",
                 "project_name", "supplier_name"),
    drill=lambda r: {"label": r.get("mro_no"), "to": f"/mro/{r.get('mro_id')}"} if r.get("mro_id") else None,
    legacy=("/api/reports/mro-traceability", "/api/reports/mro-traceability/export.xlsx"),
))
