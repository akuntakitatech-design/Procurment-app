"""P6 — Export Excel/PDF seluruh daftar transaksi (Procurement, Warehouse, SPK, Finance) lewat engine Pusat Laporan.

Prinsip:
- TIDAK ada engine baru: tiap daftar = ReportSpec (catalog=False, tidak tampil di hub) yang memakai run()/export
  Pusat Laporan (izin, batas Excel 100.000 / PDF 5.000 baris -> 422 tanpa potong diam-diam, audit export,
  redaksi kolom harga server-side, kop & keterangan filter, tanggal DD-MM-YYYY).
- Baris diambil dari LOGIKA DAFTAR YANG SAMA dengan halaman daftar: endpoint daftar existing (tenant -> izin ->
  cakupan divisi/gudang -> enrichment) + filter/periode/pencarian/sort daftar ber-halaman (txn_list_paging_layer),
  sehingga isi export = seluruh hasil daftar yang sedang difilter (bukan hanya halaman aktif).
- Batas muat 1000 dokumen terbaru pada endpoint daftar dinaikkan khusus export (list_cap) -> seluruh dokumen.
- Read-only: tidak mengubah MWA, valuation, ledger, posting, maupun logika transaksi.
"""
from urllib.parse import urlencode

from starlette.requests import Request

import list_cap
from reporting.registry import Column, Filter, ReportSpec, register

EXPORT_ALL = 10_000_000  # tanpa batas muat untuk export; batas baris export ditegakkan check_limit (422)
DATE = (Filter("date_from", "Tanggal Awal", "date"), Filter("date_to", "Tanggal Akhir", "date"))
LIST_PARAMS = ("q", "sort", "dir", "date_field", "f_", "rf_")
NOTE = ("Export daftar transaksi: seluruh hasil sesuai filter, pencarian, periode & urutan yang sedang aktif pada daftar "
        "(bukan hanya halaman aktif). Cakupan tenant/divisi/gudang & hak akses sama dengan daftar.")


def _no(label):
    return Column("no", label, width=18)


def _date(label="Tanggal"):
    return Column("date", label, "date", width=11)


def _t(key, label, width=16):
    return Column(key, label, width=width)


def _n(key, label, total=False):
    return Column(key, label, "qty", total=total, width=10)


def _int(key, label):
    return Column(key, label, "int", width=8)


def _m(key, label, price=False, total=True):
    return Column(key, label, "money", price=price, total=total, width=16)


ST = _t("status", "Status", 14)


def _flatten(rows):
    for r in rows:
        lc = r.get("lifecycle")
        if isinstance(lc, dict):
            for k, v in lc.items():
                r[f"lifecycle.{k}"] = v
    return rows


def _list_builder(module, post=None):
    async def build(server, user, p):
        with list_cap.raised(EXPORT_ALL):
            rows = await server.TXN_LIST_ROWS(module, user, p)
        rows = _flatten([dict(r) for r in rows])
        return post(rows) if post else rows
    return build


def _mi_source(rows):
    for r in rows:
        r["source_type"] = "Direct" if (r.get("source_mode") == "direct" or r.get("source_type") == "Direct") else "MRO"
    return rows


async def _route_pages(server, path, user, qp):
    """Panggil endpoint daftar ber-halaman (SPK/Kontrak) persis lewat rantai route existing (izin & cakupan divisi),
    halaman demi halaman hingga seluruh hasil terkumpul."""
    route = next(r for r in server.app.router.routes if getattr(r, "path", "") == path and "GET" in (r.methods or set()))
    items, page = [], 1
    while True:
        q = {**{k: v for k, v in qp.items() if v not in (None, "")}, "page": str(page), "page_size": "100"}
        req = Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": urlencode(q).encode()})
        res = await route.endpoint(request=req, user=user)
        batch = (res or {}).get("items") or []
        items += batch
        if not batch or len(items) >= int((res or {}).get("total") or 0) or page > 100_000:
            return items
        page += 1


SPK_STATUS = {"draft": "Draft", "active": "Active", "closed": "Closed", "cancelled": "Cancelled"}


async def _spk(server, user, p):
    qp = {k: p.get(k) for k in ("q", "status", "division_id", "period_start", "period_end")}
    qp["sort"] = ("-" if p.get("dir") == "desc" and not str(p.get("sort") or "").startswith("-") else "") + (p.get("sort") or "-created_at")
    rows = await _route_pages(server, "/api/spk", user, qp)
    pol = lambda v: "Blokir" if v == "HARD_BLOCK" else "Peringatan"  # noqa: E731
    for r in rows:
        ep = r.get("effective_policy") or {}
        r["policy"] = f"{pol(ep.get('global'))}/{pol(ep.get('category'))}"
        r["status"] = SPK_STATUS.get(r.get("status"), r.get("status"))  # sort sudah oleh daftar (kode status)
    return rows


async def _vc(server, user, p):
    qp = {k: p.get(k) for k in ("q", "status", "supplier_id", "currency", "period_start", "period_end")}
    qp["sort"] = ("-" if p.get("dir") == "desc" and not str(p.get("sort") or "").startswith("-") else "") + (p.get("sort") or "-created_at")
    return await _route_pages(server, "/api/vendor-contracts", user, qp)


DP_TABS = {"pending": "Menunggu Verifikasi", "paid": "Sudah Dibayar"}


async def _dp(server, user, p):
    route = next(r for r in server.app.router.routes if getattr(r, "path", "") == "/api/supplier-dp" and "GET" in (r.methods or set()))
    rows = await route.endpoint(user=user)
    tab = p.get("tab") or "pending"  # sama dengan tab bawaan halaman DP Supplier
    k = (p.get("q") or "").strip().lower()
    return [r for r in rows if (tab == "all" or r.get("status_label") == DP_TABS.get(tab))
            and (not k or any(k in str(r.get(x) or "").lower() for x in ("dp_no", "po_no", "supplier_name", "division_name")))]


def _spec(key, group, title, perm, cols, builder, labels=(), filters=DATE, passthrough=LIST_PARAMS, basis="Tanggal dokumen"):
    register(ReportSpec(key=key, group=group, title=title, description=NOTE, columns=tuple(cols), builder=builder,
                        filters=filters, permission=perm, date_basis=basis, catalog=False, passthrough=passthrough,
                        param_labels=tuple(labels), own_sort=True))


TR = {k: _t(f"trace_{k}", lb, w) for k, lb, w in (("mro", "No. MRO", 16), ("ro", "No. RO", 16), ("po", "No. PO", 16),
                                                  ("project", "Project", 18), ("division", "Divisi", 16), ("spk", "No. SPK", 16),
                                                  ("warehouse", "Gudang", 16), ("unit", "Unit/Aset", 16), ("requester", "Pemohon", 16))}

# ---------------------------------------------------------------- Procurement
_spec("txn-mro", "procurement", "Daftar MRO", "mro.view", [
    _no("No. MRO"), _date(), _t("requester", "Pemohon"), _t("division_name", "Divisi"), TR["project"], TR["spk"], TR["warehouse"],
    _int("line_count", "Item"), _t("lifecycle_stage", "Tracking", 11), _n("lifecycle.request", "Request"), _n("lifecycle.qty_mi", "MI"),
    _n("lifecycle.outstanding", "Outstanding"), ST], _list_builder("mro"), labels=(("f_lifecycle_stage", "Tahap Tracking"),))
_spec("txn-ro", "procurement", "Daftar RO", "ro.view", [
    _no("No. RO"), _date(), _t("requester", "Pemohon"), TR["mro"], TR["project"], _t("division_name", "Divisi"), TR["spk"],
    _int("line_count", "Item"), ST], _list_builder("ro"))
_spec("txn-po", "procurement", "Daftar PO", "po.view", [
    _no("No. PO"), _date(), _t("supplier_name", "Supplier", 20), TR["mro"], TR["ro"], TR["project"], TR["division"], TR["spk"],
    _t("buyer_contact_name", "Buyer"), _m("grand_total", "Nilai", price=True), _t("document_status", "Status Dokumen", 14),
    Column("approval2_at", "Tgl Approval 2 (WIB)", "date", width=12),
    _t("receipt_status", "Status Penerimaan", 14)], _list_builder("po"), labels=(("f_receipt_status", "Status Penerimaan"),))
_spec("txn-do", "procurement", "Daftar DO / Penerimaan Barang", "do.view", [
    _no("No. DO"), _date(), _t("supplier_name", "Supplier", 20), _t("supplier_dn", "No. Surat Jalan"), TR["mro"], TR["ro"], TR["po"],
    TR["project"], TR["division"], TR["spk"], _t("supplier_invoice", "No. Faktur"), _int("line_count", "Item"), ST], _list_builder("do"))

# ---------------------------------------------------------------- Warehouse
_spec("txn-mi", "warehouse", "Daftar Pengeluaran Barang (MI)", "mi.view", [
    _no("No. MI"), _date(), TR["mro"], TR["project"], TR["division"], TR["spk"], TR["requester"], _t("receiver", "Penerima"),
    _t("source_type", "Sumber", 9), _int("line_count", "Item"), ST], _list_builder("mi", _mi_source))
_spec("txn-transfer", "warehouse", "Daftar Transfer Antar Gudang", "transfer.view", [
    _no("No. Transfer"), _date(), _t("from_name", "Dari", 18), _t("to_name", "Ke", 18), TR["project"], TR["unit"],
    _int("line_count", "Item"), ST], _list_builder("transfer"))
_spec("txn-loan", "warehouse", "Daftar Pinjam Antar Gudang", "loan.view", [
    _no("No. Pinjaman"), _date(), _t("from_name", "Pemberi", 18), _t("to_name", "Peminjam", 18), _t("requester", "Pemohon"),
    TR["project"], TR["unit"], _n("outstanding_total", "Outstanding Dasar", total=True), ST], _list_builder("loan"))
_spec("txn-adjustment", "warehouse", "Daftar Penyesuaian Stok", "adjustment.view", [
    _no("No. Adjustment"), _date(), _t("warehouse_name", "Gudang", 18), _t("adj_type", "Jenis", 10), _t("reason", "Alasan", 20),
    TR["project"], TR["unit"], _int("line_count", "Item"), ST], _list_builder("adjustment"))
_spec("txn-opname", "warehouse", "Daftar Stock Opname", "opname.view", [
    _no("No. Opname"), _date(), _t("warehouse_name", "Gudang", 18), _t("mode", "Mode", 10), _int("line_count", "Item"), ST],
    _list_builder("opname"))

# ---------------------------------------------------------------- SPK & Kontrak Harga Vendor
_SPK_P = ("q", "status", "period_start", "period_end", "sort", "dir")
_spec("txn-spk", "spk", "Daftar SPK", "spk:view", [
    Column("spk_number", "No SPK", width=16), _t("project_name", "Nama Pekerjaan", 22), _t("customer", "Customer"),
    _t("division_name", "Divisi"), _t("pic_name", "PIC"), _m("spk_value", "Nilai SPK"), _m("procurement_budget", "Budget Pengadaan"),
    Column("start_date", "Mulai", "date", width=11), Column("end_date", "Selesai", "date", width=11), _t("policy", "Kebijakan", 14),
    _t("status", "Status", 11)], _spk, filters=(Filter("division_id", "Divisi", "division", hidden=True),), passthrough=_SPK_P,
    basis="Periode SPK", labels=(("status", "Status"), ("period_start", "Periode Mulai"), ("period_end", "Periode Selesai")))
_VC_P = ("q", "status", "currency", "period_start", "period_end", "sort", "dir")
_spec("txn-vendor-contract", "spk", "Daftar Kontrak Harga Vendor", "vendor_contract:view", [
    Column("contract_number", "No Kontrak", width=18), _t("supplier_name", "Vendor", 20), Column("start_date", "Mulai", "date", width=11),
    Column("end_date", "Selesai", "date", width=11), _t("currency", "Mata Uang", 8), _int("item_count", "Jml Item"), _t("vendor_pic", "PIC"),
    Column("updated_at", "Terakhir Diperbarui", "date", width=12), _t("derived_status", "Status", 12)], _vc,
    filters=(Filter("supplier_id", "Vendor", "supplier", hidden=True),), passthrough=_VC_P, basis="Periode kontrak",
    labels=(("status", "Status"), ("currency", "Mata Uang")))

# ---------------------------------------------------------------- Finance
_INV_L = (("f_supplier_name", "Supplier"), ("f_trace_division", "Divisi"), ("f_trace_project", "Proyek"), ("f_trace_spk", "SPK"),
          ("f_trace_po", "PO"), ("f_do_nos", "DO"), ("f_status", "Status Invoice"), ("f_payment_status", "Status Pembayaran"),
          ("f_settlement_status", "Status Hutang"), ("f_due_state", "Jatuh Tempo"))
_spec("txn-invoice", "hutang", "Daftar Invoice Vendor", "invoice.view", [
    Column("no", "No. Internal", width=16), _t("supplier_name", "Supplier", 20), _t("invoice_no", "No Invoice"), _t("trace_po", "PO"),
    _t("do_nos", "DO"), _t("trace_spk", "SPK"), _t("trace_project", "Proyek"), _t("trace_division", "Divisi"),
    Column("invoice_date", "Tgl Invoice", "date", width=11), Column("due_date", "Jatuh Tempo", "date", width=11),
    _t("due_state", "Keterangan Jatuh Tempo", 14), _m("amount", "Nilai Invoice"), _m("dp_allocated_total", "DP Dialokasikan"),
    _m("paid_total", "Sudah Dibayar"), _m("remaining", "Sisa Hutang"), _t("status", "Status Invoice", 12),
    _t("payment_status", "Status Pembayaran", 12), _t("settlement_status", "Status Hutang", 12)], _list_builder("invoice"),
    labels=_INV_L, basis="Tanggal invoice (periode = Tgl Invoice)")
_spec("txn-do-billing", "hutang", "Daftar Status Penagihan DO", "invoice.view", [
    _t("do_no", "No DO", 16), _date("Tgl DO"), _t("supplier_name", "Supplier", 20), _t("po_nos", "PO"), _t("spk", "SPK"),
    _t("project", "Proyek"), _t("division", "Divisi"), _m("do_value", "Nilai DO"), _m("billed", "Sudah Ditagihkan"),
    _m("remaining", "Sisa Belum Ditagihkan"), _t("billing_status", "Status Penagihan", 14)], _list_builder("do_billing"),
    labels=(("f_supplier_name", "Supplier"), ("f_division", "Divisi"), ("f_project", "Proyek"), ("f_spk", "SPK"),
            ("f_billing_status", "Status Penagihan")), basis="Tanggal DO")
_spec("txn-supplier-dp", "hutang", "Daftar DP Supplier", "supplier_dp.view", [
    _t("dp_no", "No. DP", 16), _t("po_no", "PO", 16), Column("po_date", "Tanggal PO", "date", width=11), _t("supplier_name", "Supplier", 20),
    _t("division_name", "Divisi"), _m("po_value", "Nilai PO", price=True), _t("dp_terms", "Ketentuan DP", 16), _m("dp_amount", "Nilai DP"),
    _m("paid_amount", "Sudah Dibayar"), _t("status_label", "Status", 14)], _dp, filters=(), passthrough=("q", "tab"),
    labels=(("tab", "Tab"),), basis="Tanggal PO")
