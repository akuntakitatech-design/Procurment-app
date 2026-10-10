"""Regression keamanan: audit export Pusat Laporan (/api/audit entity "report") hanya terlihat oleh pemegang izin laporan.

Celah sebelum perbaikan: pengguna lintas divisi ber-izin `view` tanpa `invoice.view` mendapat 403 pada laporan Hutang, namun
dapat membaca baris audit export laporan tsb (filter terpakai memuat nomor invoice, jumlah baris) dari /api/audit.
Perbaikan hanya menyaring baris audit; pencatatan audit & aturan transaksi tidak berubah. DB test terisolasi *itest*.
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
    _, d = V.mk_do("supX", 1000)
    no = f"AUD-{uuid.uuid4().hex[:5]}"
    sc, inv = call("POST", "vendor-invoices", V.inv_body(no, "supX", [(d, 1_000_000)]))
    check("fixture: invoice", sc == 200, (sc, inv))
    r1 = T.S.get(f"{API}/report-center/ap-payments/export.xlsx?invoice_id={inv['id']}")
    r2 = T.S.get(f"{API}/report-center/mro-traceability/export.xlsx")
    check("fixture: admin export laporan Hutang (filter invoice) & laporan umum", r1.status_code == 200 and r2.status_code == 200,
          (r1.status_code, r2.status_code))

    def audit(u):
        sc, rows = u("GET", "audit?entity=report&limit=300")
        return sc, rows if isinstance(rows, list) else (rows or {}).get("items") or []

    sc, ad = audit(call)
    mine = [a for a in ad if a.get("entity_id") == "ap-payments" and no in str(a.get("after"))]
    check("A1 admin (ber-izin invoice.view) melihat audit export laporan Hutang beserta label invoice", sc == 200 and len(mine) >= 1, len(mine))

    g = V.mk_user("purchasing", overrides={"invoice.view": "deny"})   # Purchasing = Semua Divisi (global), izin view & export
    check("A2 user tanpa invoice.view: laporan Hutang 403", g("GET", "report-center/ap-payments")[0] == 403)
    sc, gr = audit(g)
    check("A3 user tanpa invoice.view: audit export laporan Hutang TIDAK terlihat (nomor invoice tidak bocor)",
          sc == 200 and not any(str(a.get("entity_id") or "").startswith("ap-") for a in gr) and no not in str(gr), sc)
    check("A4 audit export laporan yang diizinkan (mro-traceability) tetap terlihat -> penyaringan hanya per izin laporan",
          any(a.get("entity_id") == "mro-traceability" for a in gr), len(gr))
    sc, gr = g("GET", f"audit?entity=report&entity_id=ap-payments")
    check("A5 filter langsung entity_id=ap-payments -> kosong", sc == 200 and not (gr if isinstance(gr, list) else gr.get("items")), sc)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
