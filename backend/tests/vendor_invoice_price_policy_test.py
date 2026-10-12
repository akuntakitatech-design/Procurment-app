"""Kebijakan nilai Tagihan DO / Invoice Vendor vs harga beli PO (PR #70) — throwaway tenant, DB uji terisolasi.

Keputusan pemilik: Finance TANPA view_purchase_price yang memiliki izin modul tagihan (invoice.*) TETAP melihat nominal
Tagihan DO (nilai DO), Invoice Vendor, outstanding & pembayaran (dibutuhkan untuk membayar). Harga satuan PO, diskon
pembelian, Grand Total PO dan rincian harga beli lain TETAP disembunyikan. Akses berbasis izin modul + tenant/cakupan
(bukan nama role): user tanpa izin invoice.view -> 403 di daftar, detail, cetak, tagihan DO, export & lampiran.
Alur pembayaran Finance tidak berubah (buat invoice, catat & batalkan pembayaran, unggah bukti).

Pakai: TEST_API_URL=http://127.0.0.1:8013/api python vendor_invoice_price_policy_test.py
"""
import os
import sys

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402
from price_visibility_scan_test import make_po_priced, fetch, find_hits, money_values, PRICE  # noqa: E402
from supplier_dp_price_policy_test import other_tenant_admin  # noqa: E402

call, API = T.call, T.API
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
RES = {"pass": 0, "fail": 0}
INV_DENY = {"invoice.view": "deny", "invoice.create": "deny", "invoice.edit": "deny", "invoice.pay": "deny", "invoice.print": "deny"}


def check(name, cond, info=""):
    RES["pass" if cond else "fail"] += 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {str(info)[:300]}"))


def upload(sess, entity, eid):
    return sess.post(f"{API}/attachments", files={"file": ("bukti.pdf", PDF, "application/pdf")},
                     data={"entity": entity, "entity_id": eid}).status_code


def main():
    M = T.setup()
    po, _mro, _ro = make_po_priced(M)  # harga khas 123457, diskon baris 4321, PPN, diskon final 3%, DP 40%
    sc, do = call("POST", "do", T.do_body(M, po, 2, "supX"), 200)
    check("fixture: PO Approved + DO 2 dari 3", po.get("status") == "Approved" and sc == 200, (po.get("status"), sc))
    # Nilai rahasia = seluruh nilai uang PO (qty 3) yang dilihat admin + harga satuan & diskon baris; DP dikecualikan
    # (Finance berizin modul DP, kebijakan opsi C). Nilai DO (qty 2) BUKAN rahasia bagi pemegang invoice.view.
    secrets = set()
    money_values(call("GET", f"po/{po['id']}")[1], secrets)
    secrets |= {float(PRICE), float(PRICE * 3), 4321.0}
    dp = round(float(po["dp_amount"]), 2)
    secrets = {s for s in secrets if abs(s) >= 1000} - {dp}
    gt = round(float(po["grand_total"]), 2)
    check("fixture: Grand Total PO & harga satuan termasuk nilai rahasia", gt in secrets and float(PRICE) in secrets, sorted(secrets))

    fin = mk_user("finance", overrides={"view_purchase_price": "deny"})
    fin_noinv = mk_user("finance", overrides={"view_purchase_price": "deny", **INV_DENY})
    wh = mk_user("warehouse", divs=[M["div"]["id"]])

    # --- 1. Finance tanpa izin harga: alur tagihan & pembayaran tidak berubah, nominal tagihan tampil
    sc, el = fin("GET", f"vendor-invoices/eligible-dos?supplier_id={M['supX']['id']}")
    row = next((r for r in el or [] if r.get("do_id") == do["id"] or r.get("id") == do["id"] or r.get("do_no") == do["no"]), {}) \
        if isinstance(el, list) else {}
    do_value = row.get("do_value")
    check("finance-deny: DO layak ditagih tampil dengan Nilai DO (nominal tagihan)", sc == 200 and isinstance(do_value, (int, float))
          and do_value > 0, (sc, row))
    body = {"supplier_id": M["supX"]["id"], "invoice_no": "INV-PRICE-1", "invoice_date": "2026-06-01", "received_date": "2026-06-02",
            "due_date": "2026-07-01", "amount": do_value, "tax_amount": 0, "allocations": [{"do_id": do["id"], "amount": do_value}]}
    sc, inv = fin("POST", "vendor-invoices", body)
    check("finance-deny: buat invoice vendor 200 (alur tidak berubah)", sc == 200 and inv.get("amount") == do_value, (sc, inv))
    iid = inv.get("id")
    check("finance-deny: unggah lampiran invoice 200", upload(fin.S, "invoice", iid) == 200)
    pay = round(do_value / 2, 2)
    sc, r = fin("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-10", "amount": pay, "reference": "TRF-PP-1"})
    check("finance-deny: catat pembayaran 200 -> Dibayar Sebagian", sc == 200 and r.get("payment_status") == "Dibayar Sebagian", (sc, r))
    pid = ((r.get("payments") or [{}])[-1]).get("id")
    check("finance-deny: unggah bukti pembayaran 200", upload(fin.S, "invoice_payment", pid) == 200)
    sc, r2 = fin("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-11", "amount": 1000, "reference": "TRF-PP-2"})
    pid2 = next((p["id"] for p in r2.get("payments") or [] if p.get("id") != pid), None)
    sc, r2 = fin("POST", f"vendor-invoices/{iid}/payments/{pid2}/cancel", {"reason": "uji batal"})
    check("finance-deny: batalkan pembayaran 200 (riwayat tetap)", sc == 200 and len(r2.get("payments") or []) == 2, (sc, r2))

    sc, det = fin("GET", f"vendor-invoices/{iid}")
    check("finance-deny: detail invoice — nominal, outstanding & riwayat pembayaran tampil",
          sc == 200 and det.get("amount") == do_value and len(det.get("payments") or []) == 2
          and any(p.get("amount") == pay for p in det["payments"]) and det.get("payment_status") == "Dibayar Sebagian", (sc, det))
    sc, b = fin("GET", f"vendor-invoices/do/{do['id']}")
    check("finance-deny: Tagihan DO — nilai DO & sisa tagihan tampil", sc == 200 and isinstance(b.get("billed"), (int, float))
          and b.get("billed") == do_value, (sc, b))
    sc, lst = fin("GET", "vendor-invoices")
    check("finance-deny: daftar invoice memuat invoice + nominal", sc == 200 and any(x.get("id") == iid and x.get("amount") == do_value
          for x in (lst if isinstance(lst, list) else lst.get("items", []))), sc)

    # --- 2. Harga beli PO tetap tersembunyi di seluruh jalur tagihan (JSON, cetak, paging, export, lampiran)
    sc, cat = call("GET", "report-center/catalog")
    keys = [r.get("key") for g in (cat if isinstance(cat, list) else cat.get("groups", cat.get("items", [])))
            for r in (g.get("reports", [g]) if isinstance(g, dict) else []) if isinstance(r, dict) and r.get("key")]
    ap_keys = [k for k in keys if k.startswith("ap-")]
    check("fixture: laporan hutang (ap-*) terdaftar", len(ap_keys) >= 5, keys)
    paths = ["vendor-invoices", "vendor-invoices?page=1&page_size=50", "vendor-invoices/summary", "vendor-invoices/do-billing",
             f"vendor-invoices/eligible-dos?supplier_id={M['supX']['id']}", f"vendor-invoices/do/{do['id']}",
             f"vendor-invoices/{iid}", f"vendor-invoices/{iid}/print", f"vendor-invoices/{iid}/dp-candidates",
             f"attachments?entity=invoice&entity_id={iid}", f"attachments?entity=invoice_payment&entity_id={pid}"]
    for k in ap_keys:
        paths += [f"report-center/{k}", f"report-center/{k}/export.xlsx",
                  f"report-center/{k}/export.pdf?date_from=2026-01-01&date_to=2026-12-31"]
    for path in paths:
        sc, body_, kind = fetch(fin, path)
        hits = find_hits(body_, secrets) if body_ is not None else []
        ok = sc == 200 and body_ is not None and not kind.endswith("?") and not hits
        check(f"finance-deny: {path} [{kind}] 200 tanpa harga satuan/diskon/Grand Total PO", ok, (sc, kind, hits[:5]))
    sc, atts = fin("GET", f"attachments?entity=invoice&entity_id={iid}")
    aid = (atts[0] if isinstance(atts, list) and atts else {}).get("id")
    r = fin.S.get(f"{API}/attachments/{aid}/download")
    check("finance-deny: unduh lampiran invoice 200 (isi = file asli)", r.status_code == 200 and r.content == PDF, r.status_code)
    sc, pod = fin("GET", f"po/{po['id']}")
    ln = (pod.get("lines") or [{}])[0] if sc == 200 else {}
    check("finance-deny: PO detail — harga satuan, diskon, Grand Total tetap null", sc in (403, 404) or (
        pod.get("grand_total") is None and ln.get("price") is None and ln.get("discount") is None), (sc, pod.get("grand_total"), ln.get("price")))
    sc, adm = call("GET", f"vendor-invoices/{iid}")
    check("kontrol admin: detail invoice identik pada nominal", sc == 200 and adm.get("amount") == det.get("amount")
          and [p.get("amount") for p in adm.get("payments") or []] == [p.get("amount") for p in det.get("payments") or []], sc)
    sc, apo = call("GET", f"po/{po['id']}")
    check("kontrol admin: PO detail memuat harga & Grand Total", apo.get("grand_total") == po["grand_total"]
          and (apo.get("lines") or [{}])[0].get("price") == PRICE, apo.get("grand_total"))

    # --- 3. Tanpa izin modul tagihan -> 403 (berbasis izin, bukan nama role; role finance tetap ditolak)
    deny_paths = ["vendor-invoices", "vendor-invoices?page=1&page_size=50", "vendor-invoices/summary", "vendor-invoices/do-billing",
                  f"vendor-invoices/eligible-dos?supplier_id={M['supX']['id']}", f"vendor-invoices/do/{do['id']}",
                  f"vendor-invoices/{iid}", f"vendor-invoices/{iid}/print", f"vendor-invoices/{iid}/dp-candidates",
                  f"attachments?entity=invoice&entity_id={iid}", f"attachments?entity=invoice_payment&entity_id={pid}",
                  f"attachments/{aid}/download"]
    for k in ap_keys:
        deny_paths += [f"report-center/{k}", f"report-center/{k}/export.xlsx"]
    for who, u in (("finance tanpa invoice.*", fin_noinv), ("warehouse default", wh)):
        bad = []
        for path in deny_paths:
            sc_ = u.S.get(f"{API}/{path}").status_code
            if sc_ != 403:
                bad.append(f"{path} -> {sc_}")
        check(f"{who}: seluruh jalur tagihan/laporan hutang/lampiran -> 403 ({len(deny_paths)} jalur)", not bad, bad)
        sc_, _ = u("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-12", "amount": 1000})
        check(f"{who}: catat pembayaran -> 403", sc_ == 403, sc_)
        check(f"{who}: unggah lampiran invoice -> 403", upload(u.S, "invoice", iid) == 403)

    # --- 4. Tenant isolation
    other = other_tenant_admin()
    for path in (f"vendor-invoices/{iid}", f"vendor-invoices/{iid}/print", f"vendor-invoices/do/{do['id']}", f"attachments/{aid}/download"):
        sc_, _ = other("GET", path)
        check(f"tenant lain: {path} -> 404", sc_ == 404, sc_)
    sc_, rows = other("GET", "vendor-invoices")
    check("tenant lain: daftar invoice tidak memuat invoice tenant ini", sc_ == 200 and not any(
        x.get("id") == iid for x in (rows if isinstance(rows, list) else rows.get("items", []))), sc_)

    n = RES["pass"] + RES["fail"]
    print(f"\n{RES['pass']}/{n} passed")
    return 0 if RES["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
