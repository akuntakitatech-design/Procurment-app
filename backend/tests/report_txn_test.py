"""P6 — Export seluruh daftar transaksi lewat engine Pusat Laporan (DB test terisolasi *itest*, read-only terhadap engine).

Membuktikan untuk 14 daftar (MRO, RO, PO, DO, MI, Transfer, Pinjam, Penyesuaian, Opname, SPK, Kontrak, Invoice,
Penagihan DO, DP Supplier):
- isi export (JSON/Excel/PDF) = SELURUH hasil daftar (semua halaman) dgn filter/pencarian/periode/sort yang sama, urutan sama;
- tidak tampil di katalog/hub Pusat Laporan; batas export 100.000/5.000 tetap;
- izin modul (403 JSON/Excel/PDF), cakupan divisi, redaksi kolom harga server-side, sort kolom harga tersembunyi ditolak;
- nilai Invoice (Sisa Hutang) sama dengan Pusat Laporan (ap-invoice-register).
"""
import io
import os
import sys
import uuid

from openpyxl import load_workbook
from pypdf import PdfReader

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T
import supplier_dp_test as SD
import vendor_invoice_test as V
from opening_correction_test import conn, ins

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:5]

LISTS = {"txn-mro": "mro", "txn-ro": "ro", "txn-po": "po", "txn-do": "do", "txn-mi": "mi", "txn-transfer": "transfers",
         "txn-loan": "loans", "txn-adjustment": "adjustments", "txn-opname": "opname", "txn-invoice": "vendor-invoices",
         "txn-do-billing": "vendor-invoices/do-billing", "txn-spk": "spk", "txn-vendor-contract": "vendor-contracts"}
IDKEY = {"txn-spk": "spk_number", "txn-vendor-contract": "contract_number", "txn-do-billing": "do_no"}


def list_all(fn, path, qs=""):
    """Seluruh baris daftar ber-halaman (semua halaman, page_size 100) + total."""
    items, page = [], 1
    while True:
        sc, r = fn("GET", f"{path}?page={page}&page_size=100&{qs}")
        if sc != 200:
            return sc, [], 0
        items += r.get("items") or []
        if len(items) >= int(r.get("total") or 0) or not r.get("items"):
            return sc, items, int(r.get("total") or 0)
        page += 1


def rc(fn, key, qs=""):
    return fn("GET", f"report-center/{key}?page_size=500&{qs}")


def xl(sess, key, qs=""):
    r = sess.get(f"{API}/report-center/{key}/export.xlsx?{qs}")
    if not r.ok:
        return r.status_code, [], []
    vals = [list(v) for v in load_workbook(io.BytesIO(r.content), read_only=True).worksheets[0].iter_rows(values_only=True)]
    hi = next((i for i, v in enumerate(vals) if v and v[0] in ("No. MRO", "No. RO", "No. PO", "No. DO", "No. MI", "No. Transfer",
                                                                  "No. Pinjaman", "No. Adjustment", "No. Opname", "No SPK", "No Kontrak",
                                                                  "No. Internal", "No DO", "No. DP")), None)
    if hi is None:
        return r.status_code, [], []
    return r.status_code, [str(x) for x in vals[hi]], [v for v in vals[hi + 1:] if v and any(x is not None for x in v) and v[0] != "TOTAL"]


def pdf(sess, key, qs=""):
    r = sess.get(f"{API}/report-center/{key}/export.pdf?{qs}")
    return r.status_code, (" ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages).split()) if r.ok else "")


def ids(rows_, key):
    return [str(r.get(IDKEY.get(key, "no")) or "") for r in rows_]


def main():
    if not os.environ.get("DATABASE_URL") or "itest" not in os.environ.get("DATABASE_URL", ""):
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    M = T.setup()
    T.M = V.M = SD.M = M
    call("PUT", "settings/approval_modules", {"modules": {k: {"enabled": False, "levels": []} for k in ("mro", "ro", "po")}}, 200)
    tenant = call("GET", "auth/me")[1].get("tenant_id")
    sc, M["divB"] = call("POST", "master/divisions", {"code": f"DB{u}", "name": f"Divisi B {u}"}, 200)

    # ---------------------------------------------------------------- fixture (transaksi lewat API existing)
    _, d1 = V.mk_do("supX", 1000)
    _, d2 = V.mk_do("supY", 500)
    sc, inv = call("POST", "vendor-invoices", V.inv_body(f"INV-T-{u}", "supX", [(d1, 1_000_000)]))
    check("fixture invoice", sc == 200, (sc, inv))
    SD.mk_po(1000, dp_enabled=True, dp_type="percentage", dp_value=40)
    for i in range(27):  # > 1 halaman daftar (25) -> export wajib memuat seluruh halaman
        call("POST", "mro", {"no": f"MRX-{u}-{i:02d}", "division_id": M["div"]["id"], "requester": f"Peminta{'ABC'[i % 3]}",
                             "lines": [{"item_id": M["item"]["id"], "qty": i + 1, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]})
    call("POST", "mro", {"no": f"MRB-{u}", "division_id": M["divB"]["id"], "requester": "Divisi B",
                         "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]})
    cn = conn()
    try:
        for no, st, bud in ((f"SPK-T1-{u}", "active", 900_000), (f"SPK-T2-{u}", "draft", 100_000)):
            ins(cn, "spk", {"id": f"spk-{no}", "tenant_id": tenant, "spk_number": no, "project_id": M["pa"]["id"], "project_name": "Proyek A",
                            "division_id": M["div"]["id"], "status": st, "start_date": "2026-01-01", "end_date": "2026-12-31",
                            "spk_value": bud * 2, "procurement_budget": bud, "created_at": f"2026-01-0{1 if st == 'active' else 2}T00:00:00+00:00"})
        cn.commit()
    finally:
        cn.close()
    call("POST", "vendor-contracts", {"supplier_id": M["supX"]["id"], "contract_number": f"KT-{u}", "start_date": "2026-01-01",
                                      "end_date": "2026-12-31", "default_tolerance_pct": 5}, 200)
    # Warehouse (F): saldo awal lewat Penyesuaian Opening, lalu Transfer & Pinjam lewat API existing (tanpa jalan pintas DB)
    # tanggal = hari ini (WIB): aturan "tidak boleh posting mundur" existing tetap berlaku (DO fixture bertanggal hari ini)
    from datetime import datetime, timedelta, timezone
    TD = datetime.now(timezone(timedelta(hours=7))).date()
    TODAY, YDAY = TD.isoformat(), (TD - timedelta(days=1)).isoformat()
    wa, wb, it = M["wh"]["id"], M["wh2"]["id"], M["item"]["id"]
    for i, (q_, c_) in enumerate(((40, 1000), (5, 1200))):
        call("POST", "adjustments", {"date": TODAY, "warehouse_id": wa, "division_id": M["div"]["id"], "adj_type": "Opening",
                                     "reason": f"Saldo awal F{i}", "notes": f"ADJF-{u}",
                                     "lines": [{"item_id": it, "adjustment": q_, "reason": "QA", "approved_unit_cost": c_}]}, 200)
    WL = lambda q_: [{"item_id": it, "qty": q_, "uom_id": M["uom"]["id"], "from_warehouse_id": wa, "to_warehouse_id": wb}]  # noqa: E731
    for i, q_ in enumerate((3, 2, 1)):
        call("POST", "transfers", {"date": TODAY, "division_id": M["div"]["id"], "from_warehouse_id": wa, "to_warehouse_id": wb,
                                   "notes": f"TRF-F{i}-{u}", "lines": WL(q_)}, 200)
    for i, q_ in enumerate((4, 6)):
        call("POST", "loans", {"date": TODAY, "division_id": M["div"]["id"], "from_warehouse_id": wa, "to_warehouse_id": wb,
                               "due_date": "2026-12-31", "requester": f"PeminjamF{i}", "notes": f"LOAN-F{i}-{u}", "lines": WL(q_)}, 200)

    # ---------------------------------------------------------------- A. katalog & batas
    sc, cat = call("GET", "report-center/catalog")
    keys = [r["key"] for g in cat.get("groups", []) for r in g["reports"]]
    check("A1 export daftar transaksi TIDAK tampil di katalog/hub Pusat Laporan (catalog=False)",
          sc == 200 and not any(k.startswith("txn-") for k in keys) and len(keys) > 0, keys[:5])
    sc, r = rc(call, "txn-po")
    check("A2 batas export tetap Excel 100.000 & PDF 5.000", sc == 200 and r.get("export_limits") == {"xlsx": 100000, "pdf": 5000}, r.get("export_limits"))

    # ---------------------------------------------------------------- B. paritas daftar <-> export (seluruh halaman, urutan sama)
    par = {}
    for key, path in LISTS.items():
        sl, items, total = list_all(call, path)
        sj, rj = rc(call, key)
        sx, hdr, body = xl(T.S, key)
        sp, _ = pdf(T.S, key)
        par[key] = (sl, sj, sx, sp, total, rj.get("total_rows"), len(body), ids(items, key) == ids(rj.get("rows", []), key))
    check("B1 14 daftar: JSON/Excel/PDF 200, jumlah baris export = total daftar (semua halaman), urutan baris identik",
          all(v[:4] == (200, 200, 200, 200) and v[4] == v[5] == v[6] and v[7] for v in par.values()), par)
    check("B2 MRO: daftar 28 dokumen > 1 halaman (25) -> export memuat seluruhnya", par["txn-mro"][4] >= 28 and par["txn-mro"][6] == par["txn-mro"][4],
          par["txn-mro"])
    sl, dp_rows = call("GET", "supplier-dp")
    sj, rj = rc(call, "txn-supplier-dp", "tab=all")
    sx, _, body = xl(T.S, "txn-supplier-dp", "tab=all")
    check("B3 DP Supplier (tab Semua): export = daftar /supplier-dp (jumlah & urutan PO)",
          sl == 200 and sj == 200 and sx == 200 and [r["po_no"] for r in dp_rows] == [r["po_no"] for r in rj["rows"]] and len(body) == len(dp_rows) >= 1,
          (len(dp_rows), rj.get("total_rows"), len(body)))
    sj, rp_ = rc(call, "txn-supplier-dp")
    check("B4 DP Supplier tab bawaan (Menunggu Verifikasi) sama dengan halaman", sj == 200
          and all(r["status_label"] == "Menunggu Verifikasi" for r in rp_["rows"]), [r["status_label"] for r in rp_["rows"]])

    # ---------------------------------------------------------------- C. filter, pencarian, periode, sort mengikuti daftar
    cases = [("txn-mro", "mro", "q=PemintaB&sort=lifecycle.request&dir=desc"), ("txn-mro", "mro", f"sort=no&dir=asc&q=MRX-{u}"),
             ("txn-po", "po", "f_receipt_status=Received&sort=grand_total&dir=desc"), ("txn-po", "po", "sort=supplier_name&dir=asc"),
             ("txn-invoice", "vendor-invoices", f"f_supplier_name={M['supX']['name'].replace(' ', '+')}&date_from=2020-01-01&date_to=2099-12-31"),
             ("txn-do", "do", "q=Supplier+Y"), ("txn-spk", "spk", f"q=SPK-T&sort=-procurement_budget"),
             ("txn-spk", "spk", "status=active"), ("txn-vendor-contract", "vendor-contracts", f"q=KT-{u}&sort=contract_number")]
    res = {}
    for key, path, qs in cases:
        sl, items, total = list_all(call, path, qs)
        sj, rj = rc(call, key, qs)
        sx, _, body = xl(T.S, key, qs)
        res[f"{key}?{qs}"] = (sl, sj, sx, total, rj.get("total_rows"), len(body), ids(items, key) == ids(rj.get("rows", []), key),
                              [str(b[0]) for b in body] == ids(rj.get("rows", []), key))
    check("C1 filter/pencarian/periode/sort: hasil & urutan export (JSON & Excel) = daftar",
          all(v[:3] == (200, 200, 200) and v[3] == v[4] == v[5] and v[6] and v[7] for v in res.values()), res)
    check("C2 pencarian mempersempit hasil (MRO 'PemintaB' = 9 dokumen)", res[cases[0][0] + "?" + cases[0][2]][3] == 9, res[cases[0][0] + "?" + cases[0][2]])
    sj, rj = rc(call, "txn-po", "f_receipt_status=Received&sort=grand_total&dir=desc&q=PO")
    fa = {f["label"]: f["value"] for f in rj.get("filters_applied", [])}
    check("C3 keterangan filter export: Status Penerimaan, Pencarian, Urutan (label kolom & arah)",
          fa.get("Status Penerimaan") == "Received" and fa.get("Pencarian") == "PO" and fa.get("Urutan") == "Nilai (menurun)", fa)
    sp, ptxt = pdf(T.S, "txn-po", "sort=no&dir=desc")
    check("C4 PDF memuat keterangan urutan & tanggal DD-MM-YYYY", sp == 200 and "Urutan" in ptxt and "No. PO (menurun)" in ptxt, ptxt[:300])
    check("C5 kolom urutan tidak dikenal -> 400 (bukan diabaikan diam-diam)", rc(call, "txn-po", "sort=hacker")[0] == 400)

    # ---------------------------------------------------------------- D. konsistensi nilai dengan Pusat Laporan
    sj, ti = rc(call, "txn-invoice")
    sa, ap = rc(call, "ap-invoice-register")
    tv = {r["invoice_no"]: (r["amount"], r["dp_allocated_total"], r["paid_total"], r["remaining"], r["payment_status"]) for r in ti["rows"]}
    av = {r["invoice_no"]: (r["amount"], r["dp_allocated"], r["paid"], r["remaining"]) for r in ap["rows"]}
    check("D1 nilai/DP/dibayar/sisa invoice di export daftar = Pusat Laporan (Register Invoice)",
          sj == 200 and sa == 200 and tv and all(tuple(tv[k][:4]) == av[k] for k in tv) and abs(ti["totals"]["remaining"] - ap["totals"]["remaining"]) < 0.01,
          (tv, av))

    # ---------------------------------------------------------------- E. izin, cakupan, redaksi harga
    np_ = V.mk_user("purchasing", overrides={"view_purchase_price": "deny", "supplier_dp.view": "allow"})  # batas 5 user/tenant
    sj, rj = rc(np_, "txn-po")
    sx, hdr, body = xl(np_.S, "txn-po")
    check("E1 tanpa view_purchase_price: kolom Nilai PO dibuang server-side (JSON & Excel), catatan harga disembunyikan",
          sj == 200 and "grand_total" not in [c["key"] for c in rj["columns"]] and rj["price_visible"] is False
          and "Nilai" not in hdr and sx == 200 and not any("grand_total" in r for r in rj["rows"]), (hdr, rj.get("price_visible")))
    check("E2 urut berdasarkan kolom harga tersembunyi -> 400 (urutan tidak membocorkan harga)", rc(np_, "txn-po", "sort=grand_total")[0] == 400)
    sjd, rjd = rc(np_, "txn-supplier-dp", "tab=all")
    check("E3 DP Supplier: Nilai PO = kolom harga (dibuang tanpa view_purchase_price)",
          sjd == 200 and "po_value" not in [c["key"] for c in rjd.get("columns", [])], sjd)
    nm = V.mk_user("purchasing", overrides={"po.view": "deny", "mro.view": "deny", "invoice.view": "deny", "transfer.view": "deny",
                                            "loan.view": "deny", "adjustment.view": "deny"})  # punya izin export
    wh = V.mk_user("warehouse")
    deny = {f"{k}@{n}": (rc(us, k)[0], us.S.get(f"{API}/report-center/{k}/export.xlsx").status_code,
                         us.S.get(f"{API}/report-center/{k}/export.pdf").status_code)
            for n, us, ks in (("purchasing-deny", nm, ("txn-po", "txn-mro", "txn-invoice", "txn-do-billing")),
                              ("gudang", wh, ("txn-invoice", "txn-supplier-dp", "txn-spk", "txn-vendor-contract")))
            for k in ks}
    check("E4 tanpa izin modul -> 403 JSON, Excel, PDF (bukan 200 kosong)", all(v == (403, 403, 403) for v in deny.values()), deny)
    check("E4b izin export tetap wajib: Gudang (tanpa export) melihat daftar PO, export Excel/PDF 403",
          rc(wh, "txn-po")[0] == 200 and wh.S.get(f"{API}/report-center/txn-po/export.xlsx").status_code == 403)
    mgB = V.mk_user("manager", divs=[M["divB"]["id"]])
    slb, itb, tb = list_all(mgB, "mro")
    sjb, rjb = rc(mgB, "txn-mro")
    sxb, _, bb = xl(mgB.S, "txn-mro")
    check("E5 Manajer Divisi B: export MRO = daftarnya sendiri (1 MRO Divisi B), MRO Divisi Teknik tidak bocor",
          sjb == 200 and tb == rjb["total_rows"] == len(bb) == 1 and f"MRX-{u}" not in str(rjb) and ids(itb, "txn-mro") == ids(rjb["rows"], "txn-mro"),
          (tb, rjb.get("total_rows"), len(bb)))
    check("E6 filter divisi SPK di luar cakupan -> 403", rc(mgB, "txn-spk", f"division_id={M['div']['id']}")[0] == 403)
    sc, aud = call("GET", "audit?entity=report&limit=300")
    items = aud if isinstance(aud, list) else (aud or {}).get("items") or []
    check("E7 export daftar tercatat di audit (entity report, format & jumlah baris)",
          any(a.get("entity_id") == "txn-po" and (a.get("after") or {}).get("format") in ("xlsx", "pdf") for a in items), len(items))

    # ---------------------------------------------------------------- F. Transfer, Pinjam, Penyesuaian (regresi khusus)
    WH3 = {"txn-transfer": "transfers", "txn-loan": "loans", "txn-adjustment": "adjustments"}
    stock_of = lambda: sorted((w.get("warehouse_id"), float(w.get("stock") or 0))  # noqa: E731
                              for w in (call("GET", f"stock/by-warehouse/{it}")[1] or {}).get("warehouses", []))
    s_before, n_before = stock_of(), {p: len(call("GET", p)[1]) for p in WH3.values()}
    dl = {}
    for key, path in WH3.items():
        sl, items, total = list_all(call, path)
        rx = T.S.get(f"{API}/report-center/{key}/export.xlsx")
        rp = T.S.get(f"{API}/report-center/{key}/export.pdf")
        _, hdr, body = xl(T.S, key)
        dl[key] = (sl, rx.status_code, rp.status_code, "spreadsheetml" in rx.headers.get("content-type", ""), rp.content[:4] == b"%PDF",
                   f'filename="{key}_' in rx.headers.get("content-disposition", ""), total, int(rx.headers.get("x-report-rows") or -1), len(body),
                   [str(b[0]) for b in body] == ids(items, key))
    check("F1 Transfer/Pinjam/Penyesuaian: Excel & PDF terunduh (200, tipe file & nama file benar), baris = total daftar, urutan = daftar",
          all(v[:6] == (200, 200, 200, True, True, True) and v[6] == v[7] == v[8] >= 2 and v[9] for v in dl.values()), dl)
    fcases = [("txn-transfer", "transfers", f"q=TRF-F1-{u}"), ("txn-transfer", "transfers", "sort=no&dir=asc"),
              ("txn-transfer", "transfers", f"date_to={YDAY}"),
              ("txn-loan", "loans", "q=PeminjamF1"), ("txn-loan", "loans", f"sort=requester&dir=desc&date_from={TODAY}&date_to={TODAY}"),
              ("txn-adjustment", "adjustments", f"q=ADJF-{u}&sort=no&dir=asc"), ("txn-adjustment", "adjustments", f"date_from={TODAY}&q=Saldo+awal+F1")]
    fr = {}
    for key, path, qs in fcases:
        sl, items, total = list_all(call, path, qs)
        sj, rj = rc(call, key, qs)
        sx, _, body = xl(T.S, key, qs)
        fr[f"{key}?{qs}"] = (sl, sj, sx, total, rj.get("total_rows"), len(body), ids(items, key) == ids(rj.get("rows", []), key),
                             [str(b[0]) for b in body] == ids(items, key))
    check("F2 filter/pencarian/periode/sort terkirim & diterapkan: hasil & urutan export = daftar (JSON & Excel)",
          all(v[:3] == (200, 200, 200) and v[3] == v[4] == v[5] and v[6] and v[7] for v in fr.values()), fr)
    check("F2b filter benar-benar mempersempit (Transfer cari TRF-F1 = 1, periode s/d kemarin = 0; Pinjam PeminjamF1 = 1; Adjustment hari ini + cari Saldo awal F1 = 1)",
          [fr[f"{k}?{q}"][3] for k, _, q in (fcases[0], fcases[2], fcases[3], fcases[6])] == [1, 0, 1, 1], fr)
    sj, rl = rc(call, "txn-loan")
    _, lit, _ = list_all(call, "loans")
    _, lh, lb = xl(T.S, "txn-loan")
    rx = T.S.get(f"{API}/report-center/txn-loan/export.xlsx")
    xl_tot = [list(v) for v in load_workbook(io.BytesIO(rx.content), read_only=True).worksheets[0].iter_rows(values_only=True) if v and v[0] == "TOTAL"]
    oi = lh.index("Outstanding Dasar") if "Outstanding Dasar" in lh else -1
    exp_out = sum(float(r.get("outstanding_total") or 0) for r in lit)
    check("F3 Pinjam: total Outstanding Dasar export (JSON & baris TOTAL Excel) = jumlah daftar (4 + 6 = 10)",
          sj == 200 and abs(float(rl["totals"].get("outstanding_total") or 0) - exp_out) < 1e-6 and exp_out >= 10 and oi >= 0
          and xl_tot and abs(float(xl_tot[0][oi] or 0) - exp_out) < 1e-6, (rl.get("totals"), exp_out, xl_tot))
    sp, ptxt = pdf(T.S, "txn-transfer", f"q=TRF-F1-{u}")
    check("F4 PDF Transfer memuat judul, keterangan pencarian & dokumen hasil filter", sp == 200 and "Daftar Transfer Antar Gudang" in ptxt
          and "Pencarian" in ptxt and ids(rc(call, "txn-transfer", f"q=TRF-F1-{u}")[1]["rows"], "txn-transfer")[0] in ptxt, ptxt[:300])
    deny3 = {f"{k}@{n}": (rc(us, k)[0] if n == "tanpa-view" else None, us.S.get(f"{API}/report-center/{k}/export.xlsx").status_code,
                          us.S.get(f"{API}/report-center/{k}/export.pdf").status_code)
             for n, us in (("tanpa-view", nm), ("tanpa-export", wh)) for k in WH3}
    check("F5 tanpa izin modul (transfer/loan/adjustment.view) -> 403 JSON/Excel/PDF; Gudang tanpa izin export -> 403 Excel/PDF",
          all(v == (403, 403, 403) for k, v in deny3.items() if k.endswith("tanpa-view"))
          and all(v[1:] == (403, 403) for k, v in deny3.items() if k.endswith("tanpa-export")), deny3)
    check("F6 export read-only: stok per gudang & jumlah dokumen Transfer/Pinjam/Penyesuaian tidak berubah",
          stock_of() == s_before and {p: len(call("GET", p)[1]) for p in WH3.values()} == n_before, (s_before, stock_of()))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
