"""Kebijakan harga DP Supplier (PR #70) — throwaway tenant, DB uji terisolasi.

Finance TANPA view_purchase_price + izin modul DP: tetap dapat memproses & melihat nominal DP, sisa DP, riwayat dan
status pembayaran; TIDAK melihat Nilai PO / Grand Total / sisa PO setelah DP / persentase DP (rekonstruksi Grand Total).
Diuji di backend/API: list, detail, paging, print, respon POST/PUT (draft/edit/approve/cancel), export Excel/PDF Daftar
DP Supplier, PO detail; kontrol: admin & finance default (berizin harga) tetap melihat nilai lengkap; tenant lain 404.

Pakai: TEST_API_URL=http://127.0.0.1:8013/api python supplier_dp_price_policy_test.py
"""
import os
import sys

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402
from price_visibility_scan_test import make_po_priced, fetch, find_hits  # noqa: E402

call, API = T.call, T.API
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
RES = {"pass": 0, "fail": 0}


def check(name, cond, info=""):
    RES["pass" if cond else "fail"] += 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {str(info)[:300]}"))


def upload(sess, pid):
    r = sess.post(f"{API}/attachments", files={"file": ("bukti.pdf", PDF, "application/pdf")},
                  data={"entity": "supplier_dp_payment", "entity_id": pid, "category": "Bukti Pembayaran"})
    return r.status_code


FREE_TEXT = ("payment_notes", "notes")


def no_free_text(obj):
    """Catatan bebas (payment_notes/notes) diketik pengguna & TIDAK diredaksi otomatis (risiko residu terdokumentasi):
    pemeriksaan persen DP hanya pada field terstruktur."""
    if isinstance(obj, dict):
        return {k: no_free_text(v) for k, v in obj.items() if k not in FREE_TEXT}
    if isinstance(obj, list):
        return [no_free_text(v) for v in obj]
    return obj


def hidden_ok(d, dp):
    """Detail DP untuk user tanpa izin harga: nominal DP tampil; nilai PO & persen DP tidak."""
    po = d.get("po") or {}
    pays = d.get("payments") or []
    return (d.get("dp_amount") == dp and d.get("po_value") is None and po.get("grand_total") is None
            and po.get("dp_remaining") is None and d.get("dp_value") is None and "%" not in str(d.get("dp_terms"))
            and all(p.get("dp_value") is None and p.get("amount") == dp for p in pays))


def other_tenant_admin():
    """Admin tenant B dengan sesi terpisah (cookie), pola master_tenant_isolation_test."""
    import uuid
    import requests
    S, u = requests.Session(), uuid.uuid4().hex[:8]
    email = f"dpiso_{u}@example.com"
    r = S.post(f"{API}/saas/register", json={"company_name": f"DPISO {u}", "pic_name": "QA", "email": email, "whatsapp": "+628123456789",
                                            "workspace_slug": f"dpiso-{u}", "plan_code": "starter", "password": "TestPass123!",
                                            "address": "x", "terms_accepted": True})
    assert r.status_code == 200, r.text[:200]
    S.cookies.clear()
    r = S.post(f"{API}/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text[:200]

    def c(method, path, body=None):
        x = S.request(method, f"{API}/{path}", json=body)
        try:
            return x.status_code, x.json()
        except Exception:
            return x.status_code, {}
    return c


def main():
    M = T.setup()
    po, _mro, _ro = make_po_priced(M)  # DP 40% dari Grand Total, harga khas
    gt, dp = round(float(po["grand_total"]), 2), round(float(po["dp_amount"]), 2)
    rem = round(gt - dp, 2)
    check("fixture: PO Approved ber-DP persen", po.get("status") == "Approved" and po.get("dp_type") == "percentage" and dp > 0, po.get("status"))
    fin = mk_user("finance", overrides={"view_purchase_price": "deny"})
    fin_ok = mk_user("finance")  # role default finance = berizin view_purchase_price (kontrol)

    # --- Finance tanpa izin harga: proses pembayaran DP tetap bisa, respon tiap langkah diredaksi
    sc, d = fin("POST", f"supplier-dp/{po['id']}/draft", {"notes": "draft finance"})
    check("finance-deny: buat draft DP 200", sc == 200, (sc, d))
    pid = (d.get("active_payment") or {}).get("id")
    check("finance-deny: respon draft tanpa nilai PO/persen, nominal DP tampil", sc == 200 and hidden_ok(d, dp), d)
    sc, d = fin("PUT", f"supplier-dp/payments/{pid}", {"reference": "TRF-001", "fund_source": "Bank Operasional"})
    check("finance-deny: edit draft 200 + redaksi", sc == 200 and hidden_ok(d, dp), (sc, d))
    sc, d = fin("PUT", f"supplier-dp/payments/{pid}", {"amount": dp + 1})
    check("finance-deny: nominal DP tetap mengikuti PO (tidak dapat diubah)", sc == 400, sc)
    check("finance-deny: unggah bukti pembayaran 200", upload(fin.S, pid) == 200)
    sc, d = fin("POST", f"supplier-dp/payments/{pid}/approve", {"payment_date": "2026-06-05", "fund_source": "Bank Operasional"})
    check("finance-deny: approve pembayaran DP 200", sc == 200 and (d.get("active_payment") or {}).get("status") == "Approved", (sc, d))
    check("finance-deny: respon approve diredaksi; sudah dibayar & sisa DP tampil",
          sc == 200 and hidden_ok(d, dp) and d.get("paid_amount") == dp and d.get("dp_available") == dp
          and d.get("status") == "Approved" and bool(d.get("status_label")), d)

    # --- baca: list, paging, detail, print, PO detail
    sc, rows = fin("GET", "supplier-dp?tab=all")
    row = next((r for r in rows if r.get("po_id") == po["id"]), {}) if isinstance(rows, list) else {}
    check("finance-deny: list memuat DP, nominal/dibayar/sisa/status tampil",
          row.get("dp_amount") == dp and row.get("paid_amount") == dp and row.get("dp_available") == dp and row.get("status") == "Approved", row)
    check("finance-deny: list tanpa Nilai PO & persen DP", "po_value" in row and row.get("po_value") is None
          and row.get("dp_value") is None and "%" not in str(row.get("dp_terms")), row)
    sc, rows_p = fin("GET", "supplier-dp?page=1&page_size=50")
    rp = next((r for r in rows_p if r.get("po_id") == po["id"]), {}) if isinstance(rows_p, list) else {}
    check("finance-deny: paging tanpa Nilai PO & persen DP", sc == 200 and rp.get("po_value") is None and rp.get("dp_amount") == dp, (sc, rp))
    sc, d = fin("GET", f"supplier-dp/{po['id']}")
    check("finance-deny: detail diredaksi + riwayat pembayaran tampil", sc == 200 and hidden_ok(d, dp) and len(d.get("payments") or []) == 1
          and bool(d.get("history")), d)
    sc, d = fin("GET", f"supplier-dp/payments/{pid}/print")
    check("finance-deny: print diredaksi", sc == 200 and hidden_ok(d, dp), (sc, d))
    sc, pod = fin("GET", f"po/{po['id']}")
    check("finance-deny: PO detail tanpa Grand Total & persen DP", sc in (403, 404) or (pod.get("grand_total") is None and pod.get("dp_value") is None
          and pod.get("dp_amount") is None), (sc, {k: pod.get(k) for k in ("grand_total", "dp_value", "dp_amount")}))
    secrets = {gt, rem, float(123457), float(123457 * 3)}
    for path in (f"supplier-dp/{po['id']}", "supplier-dp", f"supplier-dp/payments/{pid}/print", f"po/{po['id']}",
                 "report-center/txn-supplier-dp", "report-center/txn-supplier-dp/export.xlsx",
                 "report-center/txn-supplier-dp/export.pdf?date_from=2026-01-01&date_to=2026-12-31&tab=all",
                 "report-center/txn-supplier-dp/export.xlsx?tab=all"):
        sc, body, kind = fetch(fin, path)
        hits = find_hits(body, secrets) if body is not None else []
        pct = "40%" in str(no_free_text(body)) or "40 %" in str(no_free_text(body))
        check(f"finance-deny: {path} [{kind}] tanpa Grand Total/sisa PO/harga/persen", sc in (200, 403, 404) and not hits and not pct,
              (sc, kind, hits[:5], pct))
    sc, body, kind = fetch(fin, "report-center/txn-supplier-dp/export.xlsx?tab=all")
    check("finance-deny: export Excel DP tetap memuat nominal DP", sc == 200 and body is not None and dp in {round(float(c), 2) for c in body
          if isinstance(c, (int, float)) and not isinstance(c, bool)}, (sc, kind))

    # --- kontrol: admin & finance berizin harga melihat nilai lengkap (perilaku tidak berubah)
    for who, u in (("admin", call), ("finance-default", fin_ok)):
        sc, d = u("GET", f"supplier-dp/{po['id']}")
        check(f"{who}: detail DP lengkap (Nilai PO, Grand Total, sisa PO, persen DP)",
              sc == 200 and d.get("po_value") == gt and (d.get("po") or {}).get("grand_total") == gt and d.get("dp_value") == 40
              and "40" in str(d.get("dp_terms")) and d.get("dp_amount") == dp, (sc, {k: d.get(k) for k in ("po_value", "dp_value", "dp_terms")}))
        sc, rows = u("GET", "supplier-dp?tab=all")
        r = next((x for x in rows if x.get("po_id") == po["id"]), {}) if isinstance(rows, list) else {}
        check(f"{who}: list DP lengkap", r.get("po_value") == gt and r.get("dp_value") == 40, r)

    # --- cancel draft (PO kedua, DP nominal) oleh finance-deny: respon diredaksi
    sc, po2 = call("POST", "po", {"supplier_id": M["supY"]["id"], "division_id": M["div"]["id"], "date": "2026-06-02",
                                  "dp_enabled": True, "dp_type": "nominal", "dp_value": 55555,
                                  "lines": [{"item_id": M["item2"]["id"], "qty": 2, "uom_id": M["uom"]["id"], "price": 98765,
                                             "tax": 11, "warehouse_id": M["wh"]["id"], "price_change_reason": "scan"}]}, 200)
    call("POST", f"po/{po2['id']}/submit", {})
    if call("GET", f"po/{po2['id']}")[1].get("status") != "Approved":
        call("POST", f"po/{po2['id']}/approve", {})
    sc, d2 = fin("POST", f"supplier-dp/{po2['id']}/draft", {})
    pid2 = (d2.get("active_payment") or {}).get("id")
    sc, d2 = fin("POST", f"supplier-dp/payments/{pid2}/cancel", {"reason": "uji batal"})
    check("finance-deny: batal draft 200 + redaksi (DP nominal tampil, Nilai PO tidak)",
          sc == 200 and (d2.get("po") or {}).get("grand_total") is None and d2.get("po_value") is None and d2.get("dp_amount") == 55555, (sc, d2))

    # --- tenant isolation: admin tenant lain tidak melihat DP tenant ini
    other = other_tenant_admin()
    sc, _ = other("GET", f"supplier-dp/{po['id']}")
    check("tenant lain: detail DP 404", sc == 404, sc)
    sc, rows = other("GET", "supplier-dp?tab=all")
    check("tenant lain: list DP tidak memuat PO tenant lain", sc == 200 and isinstance(rows, list)
          and not any(r.get("po_id") == po["id"] for r in rows), sc)
    sc, _ = other("POST", f"supplier-dp/{po['id']}/draft", {})
    check("tenant lain: tidak dapat membuat draft DP PO tenant lain", sc == 404, sc)

    n = RES["pass"] + RES["fail"]
    print(f"\n{RES['pass']}/{n} passed")
    return 0 if RES["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
