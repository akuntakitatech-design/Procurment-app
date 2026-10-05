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


def pl(M, item, qty, price, discount=0, tax=0, uom=None):
    return {"item_id": item["id"], "qty": qty, "uom_id": (uom or M["uom"])["id"], "conversion_factor": 1, "price": price,
            "discount": discount, "tax": tax, "warehouse_id": M["wh"]["id"], "price_change_reason": "uji harga"}


def manual_po(M, sup, item, qty, price, date, discount=0, tax=0, inclusive=False, div=None, approve=True, lines=None, final=None):
    body = {"supplier_id": sup["id"], "division_id": div or M["div"]["id"], "date": date, "tax_inclusive": inclusive,
            "lines": lines or [pl(M, item, qty, price, discount, tax)]}
    if final:
        body["final_discount_type"], body["final_discount_value"] = final
    sc, po = call("POST", "po", body, 200)
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


def legacy_line(po_id, item_id, uom_id=None, unit=None, qty=None, price=None):
    """Simulasi baris PO historis (pra-normalisasi UOM): hapus jejak faktor konversi. Dev DB saja."""
    import pymysql
    from urllib.parse import urlparse, unquote
    url = next(x.split("=", 1)[1].strip().strip('"') for x in open("/app/backend/.env") if x.startswith("DATABASE_URL="))
    assert "prod" not in url
    u = urlparse(url.replace("mariadb://", "mysql://"))
    c = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""), database=u.path.lstrip("/"))
    with c.cursor() as cur:
        expr = "JSON_REMOVE(doc, '$.conversion_factor', '$.display_qty', '$.display_unit', '$.base_qty', '$.display_price')"
        expr = f"JSON_SET({expr}, '$.uom_id', %s)" if uom_id else f"JSON_REMOVE({expr}, '$.uom_id')"
        if unit:
            expr = f"JSON_SET({expr}, '$.unit', %s)"
        if qty is not None:
            expr = f"JSON_SET({expr}, '$.qty', %s, '$.price', %s)"
        args = [a for a in (uom_id, unit) if a] + ([qty, price] if qty is not None else []) + [po_id, item_id]
        n = cur.execute(f"UPDATE po_lines SET doc = {expr} WHERE po_id = %s AND item_id = %s", args)
    c.commit(); c.close()
    assert n == 1, n


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

    # --- 8. NET effective (diskon item + Diskon Final + PPN) & UOM terbukti
    sc, box = call("POST", "master/uoms", {"code": f"BX{u}", "name": f"Box {u}", "symbol": f"BX{u[:2]}"}, 200)
    sc, dus = call("POST", "master/uoms", {"code": f"DS{u}", "name": f"Dus {u}"}, 200)
    seal = mk_item(M, f"SEAL{u}", "Seal Pompa")
    call("PUT", f"master/items/{seal['id']}", {**{k: v for k, v in seal.items() if k not in ("_id",)}, "uoms": [{"uom_id": box["id"], "factor": 10}]}, 200)
    dummy = mk_item(M, f"DMY{u}", "Barang Lain")
    S = {k: mk(f"P{k}", f"Supplier Net {k}") for k in ("A", "B", "C", "D", "E", "F", "G", "H", "J")}
    manual_po(M, S["A"], seal, 4, 100000, "2026-05-01", discount=40000)                     # item disc: 90.000
    manual_po(M, S["B"], seal, 2, 100000, "2026-05-01", final=("percent", 10))             # final 10%: 90.000
    poC = manual_po(M, S["C"], None, 0, 0, "2026-05-01", final=("amount", 38000),
                    lines=[pl(M, seal, 2, 100000, 20000), pl(M, dummy, 1, 200000)])       # 180k+200k, final 38k -> 0,9 -> 81.000
    manual_po(M, S["D"], seal, 1, 222000, "2026-05-01", discount=22000, tax=11, inclusive=True, final=("percent", 10))  # 180.000/1,11
    poE = manual_po(M, S["E"], None, 0, 0, "2026-05-01", final=("percent", 5), lines=[pl(M, seal, 2, 1000000, uom=box)])  # 950.000/BOX -> 95.000/dasar
    poF = manual_po(M, S["F"], None, 0, 0, "2026-05-01", lines=[pl(M, seal, 1, 1000, uom=box)])     # nanti dibuat legacy tanpa faktor
    poG = manual_po(M, S["G"], seal, 3, 500, "2026-05-01")                                   # legacy satuan teks lain (DUS)
    poH = manual_po(M, S["H"], seal, 1, 97000, "2026-05-01")                                 # legacy satuan teks = dasar -> faktor 1 valid
    manual_po(M, S["J"], seal, 1, 99000, "2026-05-01")                                       # pembanding biasa
    legacy_line(poF["id"], seal["id"], uom_id=box["id"], qty=1, price=1000)  # tersimpan dalam satuan transaksi
    legacy_line(poG["id"], seal["id"], unit=dus["code"])
    legacy_line(poH["id"], seal["id"], unit=M["uom"]["code"])
    M["seal"] = seal
    m4, l4 = mro(M, f"MRO-S-{u}", 5, item="seal")
    ro4 = mk_ro(M, [(seal, 5, [(m4, l4, 5)])])
    sc, r = ins(ro4["lines"][0]["id"])
    s = by_sup(r)
    g = lambda k, f="last_price_base": (s.get(S[k]["id"]) or {}).get(f)
    close = lambda a, b: a is not None and abs(a - b) < 0.01
    check("net: diskon item (4x100.000 - 40.000)/4 = 90.000", close(g("A"), 90000), g("A"))
    check("net: Diskon Final PO 10% = 90.000", close(g("B"), 90000), g("B"))
    check("net: diskon item + Diskon Final Rp dialokasikan prorata (81.000)", close(g("C"), 81000), g("C"))
    sc, dC = call("GET", f"po/{poC['id']}")
    dpp_sum = sum(float(x.get("dpp") or 0) for x in dC.get("lines") or [])
    check("alokasi Diskon Final konsisten: total DPP baris = subtotal setelah diskon item - Diskon Final (342.000)",
          abs(dpp_sum - 342000) < 0.01 and close(next(float(x["dpp"]) / 2 for x in dC["lines"] if x["item_id"] == seal["id"]), 81000), (dpp_sum, dC.get("final_discount_amount")))
    check("net: harga termasuk PPN + diskon item + Diskon Final -> 180.000/1,11", close(g("D"), 180000 / 1.11), g("D"))
    check("UOM beda dengan faktor valid: 950.000/BOX -> 95.000 per satuan dasar", close(g("E"), 95000) and close(g("E", "last_price"), 950000)
          and g("E", "last_comparable") is True and g("E", "last_qty") == 2, s.get(S["E"]["id"]))
    check("UOM beda TANPA faktor: Tidak dapat dibandingkan (tanpa harga), No PO/tanggal/qty/satuan tetap",
          g("F", "last_comparable") is False and g("F") is None and g("F", "last_price") is None and g("F", "last_po_no") == poF["no"]
          and g("F", "last_qty") == 1 and g("F", "last_unit") and g("F", "diff_label") is None, s.get(S["F"]["id"]))
    check("legacy satuan teks berbeda tanpa faktor: Tidak dapat dibandingkan", g("G", "last_comparable") is False and g("G") is None, s.get(S["G"]["id"]))
    check("legacy satuan = satuan dasar: faktor 1 tetap valid", g("H", "last_comparable") is True and close(g("H"), 97000), s.get(S["H"]["id"]))
    lows = [x["supplier_id"] for x in r["suppliers"] if x["is_lowest"]]
    check("record tidak comparable tidak mendapat label Harga terendah (harga mentah 100 & 500 diabaikan)",
          lows == [S["C"]["id"]] and not g("F", "is_lowest") and not g("G", "is_lowest"), [(x["supplier_name"], x["is_lowest"], x.get("last_price_base")) for x in r["suppliers"]])
    sc, hf = call("GET", f"{HIS}?ro_line_id={ro4['lines'][0]['id']}&supplier_id={S['F']['id']}")
    check("riwayat: baris tidak comparable tanpa harga, tetap No PO/tanggal/qty/satuan",
          sc == 200 and hf["rows"] and hf["rows"][0]["comparable"] is False and hf["rows"][0]["unit_net_price"] is None and hf["rows"][0]["po_no"] == poF["no"]
          and hf["rows"][0]["qty"] == 1 and hf["rows"][0]["unit"], hf)
    sc, he = call("GET", f"{HIS}?ro_line_id={ro4['lines'][0]['id']}&supplier_id={S['E']['id']}")
    check("riwayat: UOM BOX tampil satuan asli dengan harga net per BOX", he["rows"][0]["comparable"] is True and close(he["rows"][0]["unit_net_price"], 950000)
          and he["rows"][0]["qty"] == 2, he["rows"][0])

    # --- 9. read-only
    before = snapshot()
    for _ in range(2):
        ins(RB["id"]); ins(RF["id"]); ins(RO_["id"]); ins(ro4["lines"][0]["id"])
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
