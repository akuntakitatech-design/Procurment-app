"""PO — Informasi Harga & Supplier saat Tarik RO (throwaway tenant, localhost, dev DB)."""
import json
import sys
import uuid

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402
from ro_consolidation_test import mro  # noqa: E402
from po_ro_split_test import mk_item, mk_ro  # noqa: E402

call, check = T.call, T.check
INS, HIS = "pull/ro-for-po/price-insight", "pull/ro-for-po/price-history"


def manual_po(M, sup, item, qty, price, date, discount=0, tax=0, inclusive=False, div=None, approve=True):
    sc, po = call("POST", "po", {"supplier_id": sup["id"], "division_id": div or M["div"]["id"], "date": date, "tax_inclusive": inclusive,
                                 "lines": [{"item_id": item["id"], "qty": qty, "uom_id": M["uom"]["id"], "conversion_factor": 1, "price": price,
                                            "discount": discount, "tax": tax, "warehouse_id": M["wh"]["id"], "price_change_reason": "uji harga"}]}, 200)
    if approve:
        call("POST", f"po/{po['id']}/submit", {})
        sc, d = call("GET", f"po/{po['id']}")
        if d.get("status") == "Waiting Approval":
            call("POST", f"po/{po['id']}/approve", {})
        sc, d = call("GET", f"po/{po['id']}")
        assert d.get("status") == "Approved", d.get("status")
        return d
    return po


def contract(sup, no, item, uom, price, start="2020-01-01", end="2099-12-31", activate=True):
    sc, vc = call("POST", "vendor-contracts", {"supplier_id": sup["id"], "contract_number": no, "start_date": start, "end_date": end}, 200)
    call("POST", f"vendor-contracts/{vc['id']}/items", {"item_id": item["id"], "uom_id": uom["id"], "base_price": price}, 200)
    if activate:
        call("POST", f"vendor-contracts/{vc['id']}/activate", {}, 200)
    return vc


def ins(line_id, fn=None, date="2026-06-01"):
    return (fn or call)("GET", f"{INS}?ro_line_id={line_id}&date={date}")


def by_sup(res):
    return {s["supplier_id"]: s for s in (res or {}).get("suppliers") or []}


def main():
    M = T.setup()
    T.M = M
    import vendor_invoice_test as V
    V.M = M
    u = uuid.uuid4().hex[:5]
    supX, supY = M["supX"], M["supY"]
    mk = lambda k, n: call("POST", "master/suppliers", {"code": f"{k}{u}", "name": n, "supplier_category_id": M["scat"]["id"]}, 200)[1]
    supZ, supW, supV = mk("SZ", "Supplier Z"), mk("SW", "Supplier W"), mk("SV", "Supplier V")
    sc, dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)

    bearing = mk_item(M, f"BRG{u}", "Bearing 6205")                 # 1 supplier kontrak (Y), tanpa Supplier Utama
    filt = mk_item(M, f"FLT{u}", "Filter Oli", primary=supX["id"])  # 2 kontrak (X utama + Z) + riwayat W
    oli = mk_item(M, f"OLI{u}", "Oli Mesin", primary=supY["id"])    # Supplier Utama tanpa kontrak
    M.update({"bearing": bearing, "filt": filt, "oli": oli})
    contract(supY, f"KHV-Y-{u}", bearing, M["uom"], 50000)
    contract(supX, f"KHV-X-{u}", filt, M["uom"], 115000)
    contract(supZ, f"KHV-Z-{u}", filt, M["uom"], 118000)
    contract(supW, f"KHV-W-DRAFT-{u}", filt, M["uom"], 1000, activate=False)    # draft -> tidak ditampilkan
    contract(supV, f"KHV-V-EXP-{u}", filt, M["uom"], 1000, end="2021-12-31")    # lewat periode -> tidak ditampilkan

    # riwayat pembelian Filter
    manual_po(M, supX, filt, 1, 125000, "2026-01-10")
    poX2 = manual_po(M, supX, filt, 2, 130000, "2026-02-10", discount=20000)    # net (2x130.000-20.000)/2 = 120.000
    manual_po(M, supX, filt, 1, 90000, "2026-03-01", approve=False)            # Draft -> diabaikan
    poX4 = manual_po(M, supX, filt, 1, 80000, "2026-03-05")
    call("POST", f"po/{poX4['id']}/cancel", {}, 200)                            # Cancelled -> diabaikan
    manual_po(M, supW, filt, 1, 110000, "2026-01-20")
    manual_po(M, supV, filt, 1, 50000, "2026-04-01", div=dB["id"])             # PO divisi B (cakupan)
    # 6 pembelian bearing ke Y -> riwayat maks 5
    for i in range(6):
        manual_po(M, supY, bearing, 1, 50000 + i * 1000, f"2026-0{i + 1}-15")
    # PPN termasuk: 111.000 incl. 11% -> net 100.000
    manual_po(M, supY, oli, 1, 111000, "2026-05-05", tax=11, inclusive=True)

    m1, l1 = mro(M, f"MRO-B-{u}", 10, item="bearing")
    m2, l2 = mro(M, f"MRO-F-{u}", 8, item="filt")
    m3, l3 = mro(M, f"MRO-O-{u}", 4, item="oli")
    ro = mk_ro(M, [(bearing, 10, [(m1, l1, 10)]), (filt, 8, [(m2, l2, 8)]), (oli, 4, [(m3, l3, 4)])])
    L = {l["item_id"]: l for l in ro["lines"]}
    RB, RF, RO_ = L[bearing["id"]], L[filt["id"]], L[oli["id"]]

    # --- baseline untuk uji read-only
    def snapshot():
        out = {}
        for k in ("pull/ro-for-po", f"ro/{ro['id']}", f"po/{poX2['id']}", "vendor-contracts?page_size=100",
                  f"stock/by-warehouse/{filt['id']}", "master/items"):
            sc, d = call("GET", k)
            out[k] = json.dumps(d, sort_keys=True, default=str)
        return out
    before = snapshot()

    # --- 1. satu supplier kontrak
    sc, r = ins(RB["id"])
    s = by_sup(r)
    check("1 supplier kontrak: header barang/qty/sisa/satuan/divisi", sc == 200 and r["item_code"] == bearing["code"] and r["item_name"] == "Bearing 6205"
          and r["qty_ro"] == 10 and r["sisa_po"] == 10 and r["sudah_po"] == 0 and r["base_unit"] and r["division_name"] == "Divisi Teknik" and r["ro_no"] == ro["no"], r)
    check("1 supplier kontrak: Y = Kontrak Aktif, harga & periode", supY["id"] in s and s[supY["id"]]["status"] == "Kontrak Aktif"
          and s[supY["id"]]["contract_price"] == 50000 and s[supY["id"]]["contract_number"] == f"KHV-Y-{u}" and s[supY["id"]]["effective_end"] == "2099-12-31"
          and s[supY["id"]]["contract_status"] == "Aktif" and r["contract_supplier_count"] == 1, s.get(supY["id"]))

    # --- 2. beberapa supplier kontrak + supplier utama + riwayat
    sc, r = ins(RF["id"])
    s = by_sup(r)
    check("beberapa supplier kontrak: X & Z tampil terpisah, draft/expired tidak", r["contract_supplier_count"] == 2 and s[supX["id"]]["is_contract"]
          and s[supZ["id"]]["is_contract"] and s[supZ["id"]]["contract_price"] == 118000 and not s.get(supW["id"], {}).get("is_contract")
          and not s.get(supV["id"], {}).get("is_contract"), [(x["supplier_name"], x["status"]) for x in r["suppliers"]])
    check("status: X = Kontrak Aktif + Supplier Utama, Z = Kontrak Aktif, W = Riwayat Pembelian",
          s[supX["id"]]["status"] == "Kontrak Aktif + Supplier Utama" and s[supZ["id"]]["status"] == "Kontrak Aktif" and s[supW["id"]]["status"] == "Riwayat Pembelian",
          {k: v["status"] for k, v in s.items()})
    check("Harga Beli Terakhir X = PO Approved terbaru (net setelah diskon item) — Draft/Cancelled diabaikan",
          s[supX["id"]]["last_price_base"] == 120000 and s[supX["id"]]["last_po_no"] == poX2["no"] and str(s[supX["id"]]["last_po_date"])[:10] == "2026-02-10"
          and s[supX["id"]]["last_qty"] == 2, s[supX["id"]])
    check("supplier lain dengan histori: W harga terakhir 110.000", s[supW["id"]]["last_price_base"] == 110000 and s[supW["id"]].get("contract_price") is None, s[supW["id"]])
    check("selisih informatif: Kontrak 4,2% lebih rendah", s[supX["id"]]["diff_label"] == "Kontrak 4,2% lebih rendah" and s[supX["id"]]["diff_pct"] < 0, s[supX["id"]].get("diff_label"))
    check("Harga terendah ditandai (informasi), urutan tetap per status (tidak memilih otomatis)",
          [x["supplier_id"] for x in r["suppliers"] if x["is_lowest"]] == [supV["id"]] and r["suppliers"][0]["supplier_id"] == supX["id"],
          [(x["supplier_name"], x["is_lowest"]) for x in r["suppliers"]])
    check("nomor PO human-readable (bukan UUID)", str(s[supX["id"]]["last_po_no"]).startswith("PO") and s[supX["id"]]["last_po_no"] != poX2["id"], s[supX["id"]]["last_po_no"])

    # resolver kontrak existing (refactor _pick_price) tetap sama
    pc = lambda sup: call("POST", "po/price-control", {"supplier_id": sup["id"], "date": "2026-06-01", "lines": [{"key": 0, "item_id": filt["id"], "uom_id": M["uom"]["id"], "qty": 1}]})[1]["lines"][0]
    cx, cw, cv = pc(supX), pc(supW), pc(supV)
    check("Kontrol harga PO existing tidak berubah (aktif=found, draft=tidak, expired=out_of_period)",
          cx.get("found") and cx.get("contract_price") == 115000 and not cw.get("found") and not cv.get("found") and cv.get("out_of_period"), (cx, cw, cv))

    # --- 3. supplier utama tanpa kontrak + PPN termasuk dikeluarkan
    sc, r = ins(RO_["id"])
    s = by_sup(r)
    check("Supplier Utama tanpa kontrak: Y = Supplier Utama", s[supY["id"]]["status"] == "Supplier Utama" and not s[supY["id"]]["is_contract"]
          and r["contract_supplier_count"] == 0, s.get(supY["id"]))
    check("harga termasuk PPN: harga pembanding tanpa PPN (111.000 -> 100.000)", abs(s[supY["id"]]["last_price_base"] - 100000) < 0.01, s[supY["id"]].get("last_price_base"))

    # --- 4. riwayat 5 terakhir
    sc, h = call("GET", f"{HIS}?ro_line_id={RB['id']}&supplier_id={supY['id']}&limit=10")
    rows = h.get("rows") or []
    check("riwayat: maksimal 5, terbaru dulu, No PO human-readable", sc == 200 and len(rows) == 5 and h["count"] == 6
          and [str(x["date"])[:10] for x in rows] == [f"2026-0{i}-15" for i in (6, 5, 4, 3, 2)] and all(str(x["po_no"]).startswith("PO") for x in rows)
          and rows[0]["unit_net_price"] == 55000 and rows[0]["supplier_name"] == "Supplier Y" and rows[0]["unit"], rows[:2])
    sc, h0 = call("GET", f"{HIS}?ro_line_id={RF['id']}&supplier_id={supZ['id']}")
    check("riwayat kosong: supplier kontrak tanpa pembelian", sc == 200 and h0["rows"] == [] and h0["count"] == 0, h0)

    # --- 5. Tarik RO tetap ringan (tanpa histori harga di initial load)
    sc, pr = call("GET", "pull/ro-for-po")
    rowF = next((x for x in pr if x.get("line_id") == RF["id"]), {})
    check("Tarik RO: tanpa data histori harga (lazy), kontrak tetap 2 supplier", len(rowF.get("contract_suppliers") or []) == 2
          and not any(k in rowF for k in ("last_price", "last_price_base", "suppliers")), list(rowF.keys())[:40])

    # --- 6. division / permission scope
    fake = str(uuid.uuid4())
    ub = mk_user("purchasing", divs=[dB["id"]])
    a1, a2 = ins(RF["id"], ub), ins(fake, ub)
    check("division scope: RO divisi lain == tidak ada (404 identik)", a1[0] == a2[0] == 404 and a1[1] == a2[1], (a1, a2))
    h1 = ub("GET", f"{HIS}?ro_line_id={RF['id']}&supplier_id={supX['id']}")
    check("division scope: riwayat RO divisi lain 404", h1[0] == 404, h1)
    ua = mk_user("purchasing", divs=[M["div"]["id"]])
    sc, ra = ins(RF["id"], ua)
    sc2, rg = ins(RF["id"])
    check("division scope: PO pembanding divisi di luar cakupan tidak dipakai (Harga terendah ikut cakupan)", sc == 200 and supV["id"] not in by_sup(ra)
          and supV["id"] in by_sup(rg) and by_sup(rg)[supV["id"]]["last_price_base"] == 50000 and by_sup(ra)[supW["id"]]["is_lowest"], ([x["supplier_name"] for x in ra.get("suppliers", [])], [x["supplier_name"] for x in rg.get("suppliers", [])]))
    nop = mk_user("purchasing", overrides={"view_purchase_price": "deny"})
    sc, rn = ins(RF["id"], nop)
    sn = by_sup(rn)
    check("tanpa izin Lihat Harga Beli: supplier tampil, harga & PO terakhir disembunyikan", sc == 200 and rn["price_visible"] is False
          and sn[supX["id"]]["status"] == "Kontrak Aktif + Supplier Utama" and sn[supX["id"]].get("contract_price") is None
          and sn[supX["id"]].get("last_price_base") is None and sn[supX["id"]].get("last_po_no") is None and supW["id"] not in sn, rn)
    hn = nop("GET", f"{HIS}?ro_line_id={RF['id']}&supplier_id={supX['id']}")
    check("tanpa izin Lihat Harga Beli: riwayat 403", hn[0] == 403, hn)
    vw = mk_user("purchasing", overrides={"po.create": "deny"})
    vv = ins(RF["id"], vw)
    check("izin PO: user tanpa akses buat PO ditolak", vv[0] == 403, vv[0])

    # --- 7. tenant isolation
    sess_a = T.S
    T.S = requests.Session()
    M2 = T.setup()
    t1, t2 = ins(RF["id"]), ins(fake)
    check("tenant isolation: RO tenant lain == tidak ada (404 identik)", t1[0] == t2[0] == 404 and t1[1] == t2[1], (t1, t2))
    m9, l9 = mro(M2, f"MRO-T2-{u}", 3)
    ro2 = mk_ro(M2, [(M2["item"], 3, [(m9, l9, 3)])])
    sc, r2 = ins(ro2["lines"][0]["id"])
    h2 = call("GET", f"{HIS}?ro_line_id={ro2['lines'][0]['id']}&supplier_id={supX['id']}")
    check("tenant isolation: supplier/kontrak/PO tenant lain tidak terlihat", sc == 200 and not any(x["supplier_id"] in (supX["id"], supY["id"], supZ["id"], supW["id"]) for x in r2["suppliers"])
          and h2[0] == 404, (r2, h2))
    T.S = sess_a

    # --- 8. read-only
    for _ in range(2):
        ins(RB["id"]); ins(RF["id"]); ins(RO_["id"])
        call("GET", f"{HIS}?ro_line_id={RF['id']}&supplier_id={supX['id']}")
    after = snapshot()
    changed = [k for k in before if before[k] != after[k]]
    check("popup read-only: PO/RO/Tarik RO/kontrak/stok/Supplier Utama tidak berubah", not changed, changed)
    sc, it = call("GET", "master/items")
    items = it.get("items", it) if isinstance(it, dict) else it
    check("Supplier Utama Master Barang tetap", next(x for x in items if x["id"] == filt["id"]).get("primary_supplier_id") == supX["id"])

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
