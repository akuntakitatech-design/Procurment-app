"""Role Finance: izin default DP Supplier + Invoice Vendor + read-only pendukung (throwaway tenant, dev DB, localhost)."""
import sys
import uuid

import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/tests")
import supplier_dp_test as SD  # noqa: E402
from access_control_layer import FINANCE_DEFAULT  # noqa: E402

T, V = SD.T, SD.V
call, check = T.call, T.check
EXPECTED = {
    "supplier_dp.view", "supplier_dp.approve", "supplier_dp.print",
    "invoice.view", "invoice.create", "invoice.edit", "invoice.pay", "invoice.print",
    "po.view", "do.view", "suppliers.view", "divisions.view", "projects.view", "units.view",
    "export", "upload_attachment", "view_purchase_price", "view_all_warehouse",
}


def main():
    M = T.setup()
    T.M = V.M = SD.M = M
    sc, M["div2"] = call("POST", "master/divisions", {"code": f"D2{uuid.uuid4().hex[:5]}", "name": "Divisi Dua"}, 200)

    # ------------------------------------------------------------------ role terdaftar & default
    sc, roles = call("GET", "access/roles")
    fr = next((r for r in roles if r["role"] == "finance"), {}) if isinstance(roles, list) else {}
    check("F1. Role Finance terdaftar (label 'Finance') di matriks role", fr.get("label") == "Finance" and not fr.get("locked"), fr.get("label"))
    check("F2. Izin default Finance = DP Supplier + Invoice (tanpa hapus) + read-only pendukung (persis)",
          set(fr.get("permissions") or []) == EXPECTED == set(FINANCE_DEFAULT), sorted(set(fr.get("permissions") or []) ^ EXPECTED))
    check("F3. Cakupan divisi default Finance = Semua Divisi", (fr.get("division_scope") or {}).get("mode") == "all", fr.get("division_scope"))
    forbidden = {"invoice.delete", "users.view", "users.create", "po.create", "po.edit", "po.approve", "po.post", "mro.view", "mro.create",
                 "ro.view", "ro.create", "do.create", "do.edit", "adjustment.create", "transfer.create", "mi.create", "opname.create",
                 "suppliers.create", "suppliers.edit", "items.edit", "edit_purchase_price"}
    check("F4. Finance TIDAK mendapat hapus Invoice / kelola user / transaksi PO-MRO-RO-DO-stok / edit master",
          not (set(fr.get("permissions") or []) & forbidden), sorted(set(fr.get("permissions") or []) & forbidden))
    others = {r["role"]: set(r["permissions"]) for r in roles if r["role"] in ("director", "purchasing", "manager", "warehouse")}
    check("F5. Role lain tetap tanpa supplier_dp.* (tidak berubah)", all(not any(k.startswith("supplier_dp.") for k in v) for v in others.values()),
          {k: sorted(x for x in v if x.startswith("supplier_dp.")) for k, v in others.items()})

    # ------------------------------------------------------------------ user Finance
    email = f"fin_{uuid.uuid4().hex[:6]}@example.com"
    sc, u = call("POST", "users", {"email": email, "password": V.PW, "name": "QA Finance", "role": "finance"})
    check("F6. Admin dapat membuat user role Finance", sc == 200 and u.get("role") == "finance", (sc, u))
    fin = V.U(email)
    sc, me = fin("GET", "access/me")
    check("F7. Effective permission user Finance = default role (Ikuti Role, tanpa override)",
          sc == 200 and set(me.get("effective") or []) == EXPECTED and not (me.get("overrides") or {}), (sc, sorted(set(me.get("effective") or []) ^ EXPECTED)))
    check("F8. Cakupan divisi user Finance = Semua Divisi", (me.get("division_scope") or {}).get("mode") == "all", me.get("division_scope"))
    sc, inv_ = call("POST", "invitations", {"name": "QA Fin Inv", "email": f"finv_{uuid.uuid4().hex[:6]}@example.com", "role": "finance", "scope": "limited"})
    check("F9. Undangan role Finance diterima & scope dipaksa global", sc == 200 and inv_.get("role") == "finance" and inv_.get("scope") == "global",
          (sc, {k: inv_.get(k) for k in ("role", "scope")} if isinstance(inv_, dict) else inv_))

    # ------------------------------------------------------------------ alur Finance end-to-end
    p1 = SD.mk_po(100000, dp_enabled=True, dp_type="percentage", dp_value=40)            # PO 100jt, DP 40jt (divisi utama)
    p2 = SD.mk_po(1000, div="div2", dp_enabled=True, dp_type="percentage", dp_value=20)  # divisi 2
    sc, rows = fin("GET", "supplier-dp")
    ids = {r["po_id"] for r in rows} if isinstance(rows, list) else set()
    check("F10. Finance melihat DP Supplier semua divisi", sc == 200 and {p1["id"], p2["id"]} <= ids, (sc, len(ids)))
    sc, d = fin("POST", f"supplier-dp/{p1['id']}/draft", {})
    pid = (d.get("active_payment") or {}).get("id") if isinstance(d, dict) else None
    fs = requests.Session()
    fs.headers.update({"Authorization": f"Bearer {requests.post(f'{T.API}/auth/login', json={'email': email, 'password': V.PW}).json()['token']}"})
    up = SD.upload(pid, fs)[0] if pid else None
    sc2, ap = fin("POST", f"supplier-dp/payments/{pid}/approve", {"payment_date": "2026-06-05", "fund_source": "Bank BCA", "reference": "TRF-FIN"})
    check("F11. Finance: buat draft DP, upload bukti, approve pembayaran DP", sc == 200 and up == 200 and sc2 == 200, (sc, up, sc2, ap if sc2 != 200 else ""))
    sc, _ = fin("GET", f"supplier-dp/payments/{pid}/print")
    check("F12. Finance: cetak bukti DP", sc == 200, sc)
    dd = SD.mk_do((p1, 60000))
    sc, C = fin("POST", "vendor-invoices/dp-candidates", {"supplier_id": M["supX"]["id"], "allocations": [{"do_id": dd["id"], "amount": 60_000_000}]})
    check("F13. Finance: kandidat DP pada Invoice", sc == 200 and any(c["po_id"] == p1["id"] for c in C or []), (sc, C))
    b = V.inv_body(f"INV-FIN-{uuid.uuid4().hex[:4]}", "supX", [(dd, 60_000_000)])
    b["dp_allocations"] = [{"po_id": p1["id"], "amount": 40_000_000}]
    sc, iv = fin("POST", "vendor-invoices", b)
    check("F14. Finance: buat Invoice Vendor + alokasi DP (sisa 20jt, Belum Dibayar)", sc == 200 and iv.get("remaining") == 20_000_000
          and iv.get("payment_status") == "Belum Dibayar", (sc, iv.get("remaining") if isinstance(iv, dict) else iv))
    sc, r = fin("PUT", f"vendor-invoices/{iv['id']}", {"notes": "revisi finance"})
    check("F15. Finance: edit Invoice", sc == 200, sc)
    sc, r = fin("POST", f"vendor-invoices/{iv['id']}/payments", {"date": "2026-06-10", "amount": 20_000_000})
    check("F16. Finance: catat pembayaran Invoice -> Lunas, Status Hutang Lunas", sc == 200 and r.get("payment_status") == "Lunas"
          and r.get("settlement_status") == "Lunas", (sc, r.get("payment_status") if isinstance(r, dict) else r))
    reads = [fin("GET", p)[0] for p in ("vendor-invoices", f"vendor-invoices/{iv['id']}", "po", f"po/{p1['id']}", "do", f"do/{dd['id']}",
                                        "master/suppliers", "master/divisions", "master/projects")]
    check("F17. Finance: read-only PO, DO, Supplier, Divisi, Proyek, Invoice", all(c == 200 for c in reads), reads)

    # ------------------------------------------------------------------ yang tidak boleh
    sc_del, _ = fin("DELETE", f"vendor-invoices/{iv['id']}")
    still = call("GET", f"vendor-invoices/{iv['id']}")[0]
    check("F18. Finance TIDAK dapat menghapus Invoice (403, data tetap ada)", sc_del == 403 and still == 200, (sc_del, still))
    denied = {
        "PO create": fin("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "lines": []})[0],
        "PO edit": fin("PUT", f"transactions/po/{p2['id']}", {"notes": "x"})[0],
        "PO approve": fin("POST", f"po/{p2['id']}/approve", {})[0],
        "PO cancel": fin("POST", f"po/{p2['id']}/cancel", {"reason": "x"})[0],
        "MRO list": fin("GET", "mro")[0],
        "MRO create": fin("POST", "mro", {"division_id": M["div"]["id"], "lines": []})[0],
        "RO list": fin("GET", "ro")[0],
        "DO create": fin("POST", "do", {"supplier_id": M["supX"]["id"], "lines": []})[0],
        "Adjustment create": fin("POST", "adjustments", {"warehouse_id": M["wh"]["id"], "lines": []})[0],
        "Transfer create": fin("POST", "transfers", {"lines": []})[0],
        "Supplier create": fin("POST", "master/suppliers", {"code": "X", "name": "X"})[0],
        "Supplier edit": fin("PUT", f"master/suppliers/{M['supX']['id']}", {"name": "Y"})[0],
        "Users list": fin("GET", "users")[0],
        "User create": fin("POST", "users", {"email": f"x_{uuid.uuid4().hex[:5]}@example.com", "password": V.PW, "role": "warehouse"})[0],
        "Role edit": fin("PUT", "access/roles/finance", {"permissions": sorted(EXPECTED | {"invoice.delete"})})[0],
    }
    check("F19. Finance ditolak (403) untuk PO/MRO/RO/DO/stok/master edit/kelola user", all(c == 403 for c in denied.values()), denied)
    sc, po2 = call("GET", f"po/{p2['id']}")
    check("F20. PO tidak berubah setelah percobaan Finance", po2.get("status") == "Approved" and po2.get("notes") != "x", (po2.get("status"), po2.get("notes")))

    # ------------------------------------------------------------------ override granular tetap berfungsi
    call("PUT", f"access/users/{u['id']}", {"overrides": {"supplier_dp.approve": "deny", "invoice.delete": "allow"}, "division_override": None}, 200)
    fin2 = V.U(email)
    sc_a, _ = fin2("POST", f"supplier-dp/{p2['id']}/draft", {})
    sc_me, me2 = fin2("GET", "access/me")
    eff2 = set(me2.get("effective") or [])
    check("F21. Override granular per user: deny supplier_dp.approve & allow invoice.delete berlaku",
          sc_a == 403 and "supplier_dp.approve" not in eff2 and "invoice.delete" in eff2 and "supplier_dp.view" in eff2, (sc_a, sorted(eff2 ^ EXPECTED)))
    call("PUT", f"access/users/{u['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": [M["div2"]["id"]]}}, 200)
    fin3 = V.U(email)
    sc, rows = fin3("GET", "supplier-dp")
    ids = {r["po_id"] for r in rows} if isinstance(rows, list) else set()
    sc_x, _ = fin3("GET", f"supplier-dp/{p1['id']}")
    check("F22. Cakupan divisi Finance dapat dibatasi manual: hanya divisi 2, DP divisi lain 404 generik",
          sc == 200 and p2["id"] in ids and p1["id"] not in ids and sc_x == 404, (sc, len(ids), sc_x))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
