"""Regression akses endpoint Invoice Vendor (/api/vendor-invoices*): izin invoice.view / print / create / edit / pay / delete
per role + override granular, dan cakupan divisi — termasuk endpoint baca yang belum diuji vendor_invoice_test
(summary, do-billing, dp-candidates, histori DO, lampiran). Hanya membaca hasil hook izin existing
(access_control_layer.classify + server.current_user); tidak mengubah aturan transaksi. DB test terisolasi *itest*.
"""
import os
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T
import vendor_invoice_test as V

call, check, API = T.call, T.check, T.API


def main():
    if not os.environ.get("DATABASE_URL") or "itest" not in os.environ.get("DATABASE_URL", ""):
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    M = T.setup()
    T.M = M
    V.M = M
    divA = M["div"]
    _, dA = V.mk_do("supX", 3000)
    _, dA2 = V.mk_do("supX", 1000)
    sc, divB = call("POST", "master/divisions", {"code": f"DB{uuid.uuid4().hex[:4]}", "name": "Divisi B"}, 200)
    M["div"] = divB
    _, dB = V.mk_do("supX", 2000)
    M["div"] = divA
    sc, iA = call("POST", "vendor-invoices", V.inv_body(f"ACC-A-{uuid.uuid4().hex[:4]}", "supX", [(dA, 3_000_000)]))
    sc2, iB = call("POST", "vendor-invoices", V.inv_body(f"ACC-B-{uuid.uuid4().hex[:4]}", "supX", [(dB, 2_000_000)]))
    check("fixture: invoice Divisi A & Divisi B", sc == 200 and sc2 == 200, (sc, sc2))
    sc, pd = call("POST", f"vendor-invoices/{iA['id']}/payments", {"date": "2026-06-10", "amount": 1_000_000})
    pid = pd.get("created_payment_id")
    sup = M["supX"]["id"]
    reads = {
        "list": ("GET", "vendor-invoices", None), "summary": ("GET", "vendor-invoices/summary", None),
        "do-billing": ("GET", "vendor-invoices/do-billing", None), "detail": ("GET", f"vendor-invoices/{iA['id']}", None),
        "histori DO": ("GET", f"vendor-invoices/do/{dA['id']}", None),
        "dp-candidates tersimpan": ("GET", f"vendor-invoices/{iA['id']}/dp-candidates", None),
        "lampiran": ("GET", f"attachments?entity=invoice&entity_id={iA['id']}", None),
    }
    writes = {
        "tambah": ("POST", "vendor-invoices", V.inv_body("ACC-X", "supX", [(dA2, 1)])),
        "edit": ("PUT", f"vendor-invoices/{iA['id']}", {"notes": "x"}), "hapus": ("DELETE", f"vendor-invoices/{iB['id']}", None),
        "bayar": ("POST", f"vendor-invoices/{iA['id']}/payments", {"date": "2026-06-11", "amount": 1}),
        "batal bayar": ("POST", f"vendor-invoices/{iA['id']}/payments/{pid}/cancel", {"reason": "x"}),
        "eligible-dos": ("GET", f"vendor-invoices/eligible-dos?supplier_id={sup}", None),
        "dp-candidates form": ("POST", "vendor-invoices/dp-candidates", {"supplier_id": sup, "allocations": []}),
    }

    def codes(u, eps):
        return {k: u(m, p, b)[0] for k, (m, p, b) in eps.items()}

    # 1. role tanpa izin Invoice (Gudang) -> seluruh endpoint 403
    wh = V.mk_user("warehouse")
    c = codes(wh, {**reads, "cetak": ("GET", f"vendor-invoices/{iA['id']}/print", None), **writes})
    check("A1 role Gudang (tanpa invoice.*): seluruh endpoint baca/tulis Invoice Vendor -> 403", all(v == 403 for v in c.values()), c)

    # 2. Manajer (invoice.view + print) -> baca 200, tulis 403
    mg = V.mk_user("manager", divs=[divA["id"]])
    c = codes(mg, {**reads, "cetak": ("GET", f"vendor-invoices/{iA['id']}/print", None)})
    check("A2 Manajer (Lihat + Cetak): seluruh endpoint baca & cetak -> 200", all(v == 200 for v in c.values()), c)
    c = codes(mg, writes)
    check("A3 Manajer: tambah / edit / hapus / bayar / batal bayar / pemilihan DO -> 403", all(v == 403 for v in c.values()), c)

    # 3. override granular: deny invoice.view -> baca 403 walau role mengizinkan; allow view pada Gudang -> baca 200, cetak 403
    nv = V.mk_user("manager", overrides={"invoice.view": "deny"}, divs=[divA["id"]])
    c = codes(nv, {k: v for k, v in reads.items() if k != "lampiran"})
    check("A4 override deny invoice.view pada Manajer -> endpoint baca 403", all(v == 403 for v in c.values()), c)
    wv = V.mk_user("warehouse", overrides={"invoice.view": "allow", "invoice.pay": "allow", "invoice.create": "allow"}, divs=[divA["id"]])
    c = codes(wv, {k: v for k, v in reads.items() if k != "lampiran"})
    check("A5 override allow invoice.view (+ pay/create) pada Gudang -> endpoint baca 200", all(v == 200 for v in c.values()), c)
    check("A6 override view tanpa print -> cetak 403", wv("GET", f"vendor-invoices/{iA['id']}/print")[0] == 403)

    # 4. cakupan divisi (Manajer Divisi A)
    ma = mg  # Manajer Divisi A (batas jumlah user paket tenant test)
    ids = {x["id"] for x in ma("GET", "vendor-invoices")[1]}
    check("D1 list: invoice Divisi A tampil, Divisi B tidak", iA["id"] in ids and iB["id"] not in ids, ids)
    c = {k: ma(m, p)[0] for k, (m, p) in {"detail": ("GET", f"vendor-invoices/{iB['id']}"), "cetak": ("GET", f"vendor-invoices/{iB['id']}/print"),
                                          "histori DO": ("GET", f"vendor-invoices/do/{dB['id']}"),
                                          "dp-candidates": ("GET", f"vendor-invoices/{iB['id']}/dp-candidates"),
                                          "lampiran": ("GET", f"attachments?entity=invoice&entity_id={iB['id']}")}.items()}
    check("D2 dokumen Divisi B: detail / cetak / histori DO / dp-candidates / lampiran -> 403", all(v == 403 for v in c.values()), c)
    sm = ma("GET", "vendor-invoices/summary")[1]
    check("D3 summary hanya invoice dalam cakupan", sm.get("invoice_received") == len(ids) and sm.get("invoice_received_value") == 3_000_000, sm)
    check("D4 do-billing tanpa DO Divisi B", dB["id"] not in {x["do_id"] for x in ma("GET", "vendor-invoices/do-billing")[1]})
    pb = wv  # Gudang Divisi A + override Lihat/Bayar/Tambah
    sc, r = pb("POST", f"vendor-invoices/{iB['id']}/payments", {"date": "2026-06-11", "amount": 1})
    check("D5 user Divisi A (izin Bayar) membayar invoice Divisi B -> 403", sc == 403, (sc, r))
    sc, r = pb("POST", "vendor-invoices/dp-candidates", {"supplier_id": sup, "allocations": [{"do_id": dB["id"], "amount": 1}]})
    check("D6 dp-candidates dengan DO Divisi B -> ditolak generik (404)", sc == 404, (sc, r))
    after = call("GET", f"vendor-invoices/{iA['id']}")[1]
    check("RO tes akses tidak mengubah invoice (dibayar tetap 1 jt)", after.get("paid_total") == 1_000_000, after.get("paid_total"))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
