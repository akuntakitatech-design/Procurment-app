"""Export daftar Master Barang (stok per gudang) lewat engine Pusat Laporan.

Kolom gudang bersifat DINAMIS (mengikuti gudang dalam cakupan pengguna), sehingga `columns` berupa callable.
Baris memakai logika daftar yang sama dengan halaman Master Data -> Barang (stock_summary.list_all + cells_for),
jadi isi export = seluruh hasil filter yang sedang aktif (bukan hanya halaman aktif).
"""
import stock_summary as SS
from reporting.registry import Column, Filter, ReportSpec, register

DESCR = ("Export daftar Master Barang: seluruh hasil sesuai filter kategori/gudang/divisi/status barang & status stok "
         "yang sedang aktif (bukan hanya halaman aktif). Stok per gudang dalam satuan dasar; cakupan gudang & divisi "
         "sama dengan halaman Master Barang.")

BASE = (Column("code", "Kode", width=16), Column("name", "Barang", width=34), Column("part_number", "Part Number", width=16),
        Column("category_label", "Kategori", width=16), Column("unit_label", "Satuan", width=10),
        Column("division_label", "Divisi", width=16))
TAIL = (Column("total_stock", "Total Stok", "qty", total=True, width=12), Column("stock_status", "Status", width=14))

ACTIVE_OPTIONS = (("Aktif", "Aktif"), ("Nonaktif", "Nonaktif"))


def _scoped_warehouses(server, user):
    """Gudang kolom = gudang aktif dalam cakupan pengguna (sama dengan kolom daftar Master Barang)."""
    return SS.scoped_warehouse_list(server, user)


async def _columns(server, user, params=None):
    """Kolom mengikuti filter gudang (sama dengan kolom data yang dihasilkan stock_summary.compute)."""
    whs = await _scoped_warehouses(server, user)
    wid = (params or {}).get("warehouse_id") or ""
    if wid:
        whs = [w for w in whs if w["id"] == wid] or whs  # gudang di luar cakupan: biar builder yang menolak (403)
    wh_cols = tuple(Column(f"wh_{w['id']}", w.get("name") or w.get("code") or "Gudang", "qty", width=12) for w in whs)
    return BASE + wh_cols + TAIL


async def _rows(server, user, p):
    res = await SS.list_all(server, user, {k: p.get(k) or "" for k in
                                           ("warehouse_id", "division_id", "category_id", "active", "q", "stock_status", "sort", "dir")})
    rows, whs = res["rows"], res["col_whs"]
    cells = await SS.cells_for(server, [r["id"] for r in rows], [w["id"] for w in whs])
    out = []
    for r in rows:
        row = {c.key: r.get(c.key) for c in BASE}
        row["total_stock"] = r.get("total_stock")
        row["stock_status"] = r.get("stock_status")
        st = cells.get(r["id"], {})
        for w in whs:
            c = st.get(w["id"])
            row[f"wh_{w['id']}"] = c["qty"] if c else None
        out.append(row)
    return out


register(ReportSpec(
    key="master-items", group="persediaan", title="Daftar Master Barang (Stok per Gudang)", description=DESCR,
    columns=_columns, builder=_rows,
    filters=(Filter("category_id", "Kategori", "category"), Filter("warehouse_id", "Gudang", "warehouse"),
             Filter("division_id", "Divisi", "division"),
             Filter("active", "Status Barang", "select", options=ACTIVE_OPTIONS),
             Filter("stock_status", "Status Stok", "select", options=tuple((s, s) for s in SS.STATUSES))),
    permission="items.view", own_sort=True, catalog=False, passthrough=("q", "sort", "dir")))
