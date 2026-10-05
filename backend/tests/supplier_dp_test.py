"""DP Supplier + alokasi DP ke Invoice Vendor (throwaway tenant, dev DB, localhost). 30 skenario wajib + guard."""
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
import threading

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
import vendor_invoice_test as V  # noqa: E402
from opening_inventory_valuation_test import dbq  # noqa: E402

call, check, API = T.call, T.check, T.API
M = None
MSG_PO_CANCEL = "PO memiliki DP yang sudah dibayar. Selesaikan/reversal uang muka terlebih dahulu."
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def dbw(sql, args=()):
    import pymysql
    from urllib.parse import urlparse, unquote
    url = next(x.split("=", 1)[1].strip().strip('"') for x in open("/app/backend/.env") if x.startswith("DATABASE_URL="))
    assert "prod" not in url.lower()
    u = urlparse(url.replace("mariadb://", "mysql://"))
    c = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""), database=u.path.lstrip("/"))
    with c.cursor() as cur:
        cur.execute(sql, args)
    c.commit(); c.close()


def mk_po(qty, approve=True, submit=True, supplier="supX", div="div", **dp):
    mro_no = f"MRO-{uuid.uuid4().hex[:6]}"
    sc, mro = call("POST", "mro", {"no": mro_no, "division_id": M[div]["id"], "requester": "Budi", "submitted": True,
                                   "lines": [{"item_id": M["item"]["id"], "qty": qty, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]}, 200)
    call("POST", f"mro/{mro['id']}/submit", {})
    sc, ro = call("POST", "ro", {"division_id": M[div]["id"], "submitted": True,
                                 "lines": [{"item_id": M["item"]["id"], "qty": qty, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"],
                                            "sources": [{"mro_id": mro["id"], "line_id": mro["lines"][0]["id"], "qty": qty}]}]}, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    sc, po = call("POST", "po", {"supplier_id": M[supplier]["id"], "division_id": M[div]["id"], **dp,
                                 "lines": [{"item_id": M["item"]["id"], "qty": qty, "price": 1000, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"],
                                            "sources": [{"ro_id": ro["id"], "line_id": ro["lines"][0]["id"], "qty": qty}]}]}, 200)
    if submit:
        call("POST", f"po/{po['id']}/submit", {})
        if approve and call("GET", f"po/{po['id']}")[1].get("status") != "Approved":
            call("POST", f"po/{po['id']}/approve", {})
    return call("GET", f"po/{po['id']}")[1]


def do_line(po, qty):
    ln = po["lines"][0]
    return {"po_id": po["id"], "po_line_id": ln["id"], "item_id": ln["item_id"], "qty": qty, "uom_id": ln.get("uom_id"),
            "warehouse_id": ln.get("warehouse_id"), "project_id": ln.get("project_id"), "condition": "Baik", "exception_qty": 0,
            "sources": [{"po_id": po["id"], "line_id": ln["id"], "qty": qty}]}


def mk_do(*parts, supplier="supX"):
    body = {"supplier_id": M[supplier]["id"], "supplier_dn": f"SJ-{uuid.uuid4().hex[:6]}", "default_warehouse_id": M["wh"]["id"],
            "lines": [do_line(po, q) for po, q in parts]}
    sc, d = call("POST", "do", body, 200)
    return d


def dp_list(u=None):
    sc, rows = (u or call)("GET", "supplier-dp")
    return sc, {r["po_id"]: r for r in rows} if isinstance(rows, list) else {}


def upload(pid, session=None):
    s = session or T.S
    r = s.post(f"{API}/attachments", files={"file": ("bukti.pdf", PDF, "application/pdf")},
               data={"entity": "supplier_dp_payment", "entity_id": pid, "category": "Bukti Pembayaran"})
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})


def pay_dp(po, fund="Bank BCA Operasional"):
    sc, d = call("POST", f"supplier-dp/{po['id']}/draft", {}, 200)
    pid = d["active_payment"]["id"]
    upload(pid)
    sc, r = call("POST", f"supplier-dp/payments/{pid}/approve", {"payment_date": "2026-06-05", "fund_source": fund, "reference": "TRF-DP"}, 200)
    return pid, r


def inv(no, allocs, dp=None, amount=None, **kw):
    b = V.inv_body(no, "supX", allocs, amount=amount, **kw)
    if dp is not None:
        b["dp_allocations"] = [{"po_id": p["id"], "amount": a} for p, a in dp]
    return call("POST", "vendor-invoices", b)


def cands(allocs, invoice_id=None):
    sc, rows = call("POST", "vendor-invoices/dp-candidates", {"supplier_id": M["supX"]["id"], "invoice_id": invoice_id,
                                                              "allocations": [{"do_id": d["id"], "amount": a} for d, a in allocs]})
    return sc, {r["po_no"]: r for r in rows} if isinstance(rows, list) else rows


def session():
    s = requests.Session()
    s.headers.update(T.S.headers)
    return s


def mk_user_id(role):
    email = f"dp_{role}_{uuid.uuid4().hex[:6]}@example.com"
    sc, u = call("POST", "users", {"email": email, "password": V.PW, "name": f"QA {role}", "role": role}, 200)
    return u["id"], email


def reconf(uid, email, overrides=None, divs=None):
    """Konfigurasi ulang akses user yang sama (batas user per tenant) -> login ulang agar token memuat akses baru."""
    body = {"overrides": overrides or {}, "division_override": {"mode": "selected", "divisions": divs} if divs is not None else None}
    call("PUT", f"access/users/{uid}", body, 200)
    return V.U(email)


def main():
    global M
    M = T.setup()
    T.M = M
    V.M = M
    sc, M["div2"] = call("POST", "master/divisions", {"code": f"D2{uuid.uuid4().hex[:5]}", "name": "Divisi Dua"}, 200)

    # ---------------------------------------------------------------- list eligibility
    p_nodp = mk_po(1000)
    p_draft = mk_po(1000, submit=False, dp_enabled=True, dp_type="percentage", dp_value=40)
    p_wait = mk_po(1000, dp_enabled=True, dp_type="percentage", dp_value=40)
    dbw("UPDATE po SET doc = JSON_SET(doc, '$.status', 'Waiting Approval', '$.approval_status', 'Waiting Approval') WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.id'))=%s", [p_wait["id"]])
    p1 = mk_po(100000, dp_enabled=True, dp_type="nominal", dp_value=40_000_000)        # 100 jt, DP 40 jt
    sc, L = dp_list()
    check("1. PO tanpa DP tidak muncul", sc == 200 and p_nodp["id"] not in L, sc)
    check("2. PO DP Draft tidak muncul", p_draft["id"] not in L)
    check("3. PO DP Waiting Approval tidak muncul", p_wait["id"] not in L)
    r1 = L.get(p1["id"]) or {}
    check("4. PO DP Approved muncul (Menunggu Verifikasi)", r1.get("status_label") == "Menunggu Verifikasi" and r1.get("po_value") == 100_000_000, r1)
    check("5. Nilai DP mengikuti PO (dp_amount)", r1.get("dp_amount") == 40_000_000 and r1.get("paid_amount") == 0, r1)

    # ---------------------------------------------------------------- draft / approve
    sc, r = call("POST", f"supplier-dp/{p1['id']}/draft", {"amount": 39_000_000})
    check("6a. Finance tidak dapat mengubah Nilai DP saat membuat draft", sc == 400 and "mengikuti PO" in str(r), (sc, r))
    sc, d1 = call("POST", f"supplier-dp/{p1['id']}/draft", {}, 200)
    pay1 = d1["active_payment"]
    check("draft: nomor DP/YYYY/MM/SEQ, nilai = DP PO, tanggal default hari ini", sc == 200 and str(pay1["no"]).startswith("DP/") and pay1["amount"] == 40_000_000
          and pay1["payment_date"] == d1["today"] and pay1["status_label"] == "Menunggu Verifikasi", pay1)
    sc, r = call("POST", f"supplier-dp/{p1['id']}/draft", {})
    check("maks 1 draft aktif per PO", sc == 409, (sc, r))
    sc, r = call("PUT", f"supplier-dp/payments/{pay1['id']}", {"amount": 50_000_000})
    check("6b. Finance tidak dapat mengubah Nilai DP saat edit draft", sc == 400, (sc, r))
    call("PUT", f"supplier-dp/payments/{pay1['id']}", {"payment_date": "", "fund_source": ""}, 200)
    upload_sc, _ = upload(pay1["id"])
    sc, r = call("POST", f"supplier-dp/payments/{pay1['id']}/approve", {"fund_source": "Kas Besar"})
    check("7. Tanggal Pembayaran wajib", sc == 400 and "Tanggal Pembayaran" in str(r), (sc, r))
    sc, r = call("POST", f"supplier-dp/payments/{pay1['id']}/approve", {"payment_date": "2026-06-05", "fund_source": "  "})
    check("8. Sumber Dana wajib", sc == 400 and "Sumber Dana" in str(r), (sc, r))
    # bukti wajib: draft lain tanpa lampiran
    p9 = mk_po(10000, dp_enabled=True, dp_type="nominal", dp_value=1_000_000)
    sc, d9 = call("POST", f"supplier-dp/{p9['id']}/draft", {}, 200)
    sc, r = call("POST", f"supplier-dp/payments/{d9['active_payment']['id']}/approve", {"payment_date": "2026-06-05", "fund_source": "Kas Besar"})
    check("9. Bukti Pembayaran wajib sebelum approve", upload_sc == 200 and sc == 400 and "Bukti Pembayaran" in str(r), (upload_sc, sc, r))
    sc, r = call("POST", f"supplier-dp/payments/{pay1['id']}/approve", {"payment_date": "2026-06-05", "fund_source": "Bank BCA Operasional", "reference": "TRF-001"})
    approved = dbq("SELECT COUNT(*) FROM supplier_dp_payments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.po_id'))=%s AND JSON_UNQUOTE(JSON_EXTRACT(doc,'$.status'))='Approved'", [p1["id"]])
    check("10. Approve menghasilkan tepat satu pembayaran DP (Sudah Dibayar)", sc == 200 and r["status_label"] == "Sudah Dibayar" and r["paid_amount"] == 40_000_000 and approved == 1, (sc, r.get("status_label"), approved))
    sc, r = call("POST", f"supplier-dp/payments/{pay1['id']}/approve", {"payment_date": "2026-06-05", "fund_source": "Kas"})
    check("11. Tidak dapat approve DP dua kali", sc == 409, (sc, r))
    sc, r = call("POST", f"supplier-dp/payments/{pay1['id']}/cancel", {"reason": "salah"})
    check("DP Approved tidak dapat dibatalkan (belum ada reversal)", sc == 409 and "tidak dapat dibatalkan" in str(r), (sc, r))
    sc, r = upload(pay1["id"])
    check("bukti DP Approved terkunci (tidak bisa tambah lampiran)", sc == 409, sc)
    sc, L = dp_list()
    check("25. DP paid tetap tersedia sebelum invoice", L[p1["id"]]["dp_available"] == 40_000_000 and L[p1["id"]]["status_label"] == "Sudah Dibayar", L[p1["id"]])
    sc, hist = call("GET", f"supplier-dp/{p1['id']}")
    check("audit log create/approve tercatat", {"create", "approve"} <= {h["action"] for h in hist.get("history") or []}, [h["action"] for h in hist.get("history") or []])

    # draft cancel (soft) -> draft baru boleh, nomor tidak dipakai ulang, lampiran tetap
    sc, r = call("POST", f"supplier-dp/payments/{d9['active_payment']['id']}/cancel", {})
    check("batal draft tanpa alasan -> 400", sc == 400)
    upload(d9["active_payment"]["id"])
    sc, r = call("POST", f"supplier-dp/payments/{d9['active_payment']['id']}/cancel", {"reason": "Salah sumber dana"}, 200)
    cancelled = next(p for p in r["payments"] if p["id"] == d9["active_payment"]["id"])
    sc, d9b = call("POST", f"supplier-dp/{p9['id']}/draft", {}, 200)
    check("soft cancel draft: status Dibatalkan, lampiran tetap, draft baru dgn nomor baru", cancelled["status"] == "Cancelled" and cancelled.get("cancelled_at")
          and len(cancelled["attachments"]) == 1 and d9b["active_payment"]["no"] != cancelled["no"], (cancelled.get("status"), d9b.get("active_payment")))

    # concurrency: 2 draft bersamaan & 2 approve bersamaan
    pc = mk_po(5000, dp_enabled=True, dp_type="percentage", dp_value=50)
    bar = threading.Barrier(4)

    def fire(path, body):
        s = session()
        bar.wait()
        return s.post(f"{API}/{path}", json=body).status_code
    with ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(lambda _: fire(f"supplier-dp/{pc['id']}/draft", {}), range(4)))
    nd = dbq("SELECT COUNT(*) FROM supplier_dp_payments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.po_id'))=%s", [pc["id"]])
    check("concurrency: 4 request draft bersamaan -> hanya 1 draft aktif", codes.count(200) == 1 and nd == 1, (codes, nd))
    pcid = call("GET", f"supplier-dp/{pc['id']}")[1]["active_payment"]["id"]
    upload(pcid)
    bar = threading.Barrier(4)
    with ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(lambda _: fire(f"supplier-dp/payments/{pcid}/approve", {"payment_date": "2026-06-05", "fund_source": "Kas"}), range(4)))
    check("concurrency: 4 approve bersamaan -> hanya 1 berhasil", codes.count(200) == 1, codes)

    # ---------------------------------------------------------------- PO guard
    sc, r = call("POST", f"po/{p1['id']}/cancel", {"reason": "uji"})
    check("30. PO cancel diblok bila DP sudah dibayar", sc == 409 and MSG_PO_CANCEL in str(r), (sc, r))
    pe = call("GET", f"po/{pc['id']}")[1]
    body = {k: pe.get(k) for k in ("date", "supplier_id", "division_id", "payment_term", "currency", "tax_inclusive", "final_discount_type", "final_discount_value",
                                   "dp_enabled", "dp_type", "dp_value", "payment_notes")}
    ln = pe["lines"][0]
    line = {k: ln.get(k) for k in ("id", "item_id", "qty", "uom_id", "price", "discount", "tax", "warehouse_id", "project_id", "notes", "sources")}
    sc, r = call("PUT", f"transactions/po/{pc['id']}", {**body, "lines": [{**line, "price": 1200, "price_change_reason": "uji"}]})
    check("PO dgn DP dibayar: ubah harga (Grand Total) diblok 409", sc == 409 and "DP yang sudah dibayar" in str(r), (sc, r))
    sc, r = call("PUT", f"transactions/po/{pc['id']}", {**body, "supplier_id": M["supY"]["id"], "lines": [line]})
    check("PO dgn DP dibayar: ganti supplier diblok 409", sc == 409, (sc, r))
    sc, r = call("PUT", f"transactions/po/{pc['id']}", {**body, "dp_value": 30, "lines": [line]})
    check("PO dgn DP dibayar: ubah ketentuan DP diblok 409", sc == 409, (sc, r))
    sc, r = call("DELETE", f"transactions/po/{pc['id']}")
    check("PO dgn DP dibayar: hapus diblok 409", sc == 409, (sc, r))
    sc, r = call("PUT", f"transactions/po/{pc['id']}", {**body, "notes": "catatan internal", "lines": [line]})
    sc2, L = dp_list()
    check("PO dgn DP dibayar: edit administratif tanpa perubahan nilai diizinkan & DP tetap tampil Sudah Dibayar",
          sc == 200 and (L.get(pc["id"]) or {}).get("status_label") == "Sudah Dibayar", (sc, r if sc != 200 else L.get(pc["id"])))
    pu = mk_po(2000, dp_enabled=True, dp_type="percentage", dp_value=10)
    sc, du = call("POST", f"supplier-dp/{pu['id']}/draft", {}, 200)
    sc, r = call("POST", f"po/{pu['id']}/cancel", {"reason": "uji"})
    sc2, L = dp_list()
    dstat = call("GET", f"supplier-dp/{pu['id']}")[1]
    check("PO dgn DP belum dibayar dapat dibatalkan & hilang dari DP Supplier (draft ikut Dibatalkan)", sc == 200 and pu["id"] not in L
          and all(p["status"] == "Cancelled" for p in dstat.get("payments") or []), (sc, r, dstat.get("payments")))

    # ---------------------------------------------------------------- invoice: 1 DO + 1 PO, parsial
    d_p1a = mk_do((p1, 30000))                                             # 30 jt
    sc, C = cands([(d_p1a, 30_000_000)])
    c1 = C.get(p1["no"]) or {}
    check("12/14. DP tersedia muncul di Invoice (1 DO + 1 PO)", sc == 200 and c1.get("dp_available") == 40_000_000, (sc, C))
    check("17/18. Invoice parsial 30jt < DP 40jt: suggested = MIN(40jt, 30jt) = 30jt", c1.get("invoice_portion") == 30_000_000 and c1.get("suggested") == 30_000_000, c1)
    check("13. DP dari PO yang tidak terkait DO tidak muncul", pc["no"] not in C and p9["no"] not in C, list(C))
    sc, r = inv("INV-DP-OVER", [(d_p1a, 30_000_000)], dp=[(p1, 30_000_001)])
    check("20. DP di atas nilai bagian invoice PO -> reject", sc == 409, (sc, r))
    sc, r = inv("INV-DP-NEG", [(d_p1a, 30_000_000)], dp=[(p1, -1)])
    check("DP negatif -> reject", sc == 400, (sc, r))
    sc, r = inv("INV-DP-FOREIGN", [(d_p1a, 30_000_000)], dp=[(pc, 1000)])
    check("DP PO lain (bukan sumber DO) dipaksa via API -> reject", sc == 400, (sc, r))
    sc, i1 = inv("INV-DP-1", [(d_p1a, 30_000_000)], dp=[(p1, 30_000_000)])
    check("Invoice 30jt + DP 30jt -> Sisa Hutang 0, paid_total 0", sc == 200 and i1["dp_allocated_total"] == 30_000_000 and i1["remaining"] == 0
          and i1["paid_total"] == 0 and i1["payment_status"] == "Belum Dibayar" and i1["due_state"] == "-", (sc, i1.get("remaining"), i1.get("payment_status"), i1.get("due_state")))
    sc, L = dp_list()
    check("Sisa DP PO = 40jt - 30jt = 10jt", L[p1["id"]]["dp_used"] == 30_000_000 and L[p1["id"]]["dp_available"] == 10_000_000, L[p1["id"]])
    d_p1b = mk_do((p1, 30000))
    sc, r = inv("INV-DP-2X", [(d_p1b, 30_000_000)], dp=[(p1, 20_000_000)])
    check("21. DP tidak dapat digunakan dua kali (melebihi DP tersedia 10jt)", sc == 409 and "DP tersedia" in str(r), (sc, r))
    sc, i2 = inv("INV-DP-2", [(d_p1b, 30_000_000)], dp=[(p1, 10_000_000)])
    sc3, C = cands([(mk_do((p1, 10000)), 10_000_000)])
    check("26. DP habis setelah seluruhnya dialokasikan", sc == 200 and i2["remaining"] == 20_000_000 and p1["no"] not in C, (sc, i2.get("remaining"), list(C)))

    # 19 + 24: turunkan nominal; payment memakai sisa setelah DP
    p6 = mk_po(100000, dp_enabled=True, dp_type="percentage", dp_value=40)
    pay_dp(p6)
    d6 = mk_do((p6, 30000))
    sc, i6 = inv("INV-DP-6", [(d6, 30_000_000)], dp=[(p6, 20_000_000)])
    check("19. Finance dapat menurunkan nominal DP (30jt -> 20jt): Sisa Hutang 10jt", sc == 200 and i6["remaining"] == 10_000_000 and i6["paid_total"] == 0 and i6["payment_status"] == "Belum Dibayar", (sc, i6.get("remaining"), i6.get("payment_status")))
    sc, r = call("POST", f"vendor-invoices/{i6['id']}/payments", {"date": "2026-06-10", "amount": 10_000_001})
    check("24a. Pembayaran invoice dibatasi sisa setelah DP", sc == 409, (sc, r))
    sc, r = call("POST", f"vendor-invoices/{i6['id']}/payments", {"date": "2026-06-10", "amount": 10_000_000})
    check("24b. Bayar sisa 10jt -> Lunas; paid_total = 10jt (DP tidak masuk paid_total)", sc == 200 and r["paid_total"] == 10_000_000 and r["dp_allocated_total"] == 20_000_000
          and r["remaining"] == 0 and r["payment_status"] == "Lunas", (sc, r.get("paid_total"), r.get("remaining")))
    # Status pembayaran = pembayaran Invoice AKTUAL; DP bukan pembayaran Invoice
    pS = mk_po(100000, dp_enabled=True, dp_type="percentage", dp_value=40)   # PO 100jt, DP 40jt
    pay_dp(pS)
    dS = mk_do((pS, 100000))
    sc, iS = inv("INV-DP-STATUS", [(dS, 100_000_000)], dp=[(pS, 40_000_000)])
    sc_g, gS = call("GET", f"vendor-invoices/{iS['id']}")
    check("ST1. Invoice 100jt + DP 40jt, tanpa bayar: paid_total 0, dp 40jt, sisa 60jt, status Belum Dibayar",
          sc == 200 and sc_g == 200 and gS["paid_total"] == 0 and gS["dp_allocated_total"] == 40_000_000 and gS["remaining"] == 60_000_000
          and gS["payment_status"] == "Belum Dibayar", (sc, gS.get("paid_total"), gS.get("dp_allocated_total"), gS.get("remaining"), gS.get("payment_status")))
    sc_l, lst = call("GET", "vendor-invoices")
    rowS = next((x for x in lst if x["id"] == iS["id"]), {}) if isinstance(lst, list) else {}
    check("ST1b. List Invoice konsisten: Belum Dibayar, paid_total 0, sisa 60jt", rowS.get("payment_status") == "Belum Dibayar" and rowS.get("paid_total") == 0
          and rowS.get("remaining") == 60_000_000, rowS)
    sc, r = call("POST", f"vendor-invoices/{iS['id']}/payments", {"date": "2026-06-10", "amount": 20_000_000})
    check("ST2. Bayar aktual 20jt: paid_total 20jt, DP 40jt, sisa 40jt, status Dibayar Sebagian (aturan pembayaran aktual)",
          sc == 200 and r["paid_total"] == 20_000_000 and r["dp_allocated_total"] == 40_000_000 and r["remaining"] == 40_000_000
          and r["payment_status"] == "Dibayar Sebagian", (sc, r.get("paid_total"), r.get("remaining"), r.get("payment_status")))
    pid_s = r.get("created_payment_id")
    sc, r = call("POST", f"vendor-invoices/{iS['id']}/payments", {"date": "2026-06-11", "amount": 40_000_000})
    check("ST3. Bayar aktual sisa 40jt: paid_total 60jt (tanpa DP), sisa 0, Lunas", sc == 200 and r["paid_total"] == 60_000_000 and r["remaining"] == 0
          and r["payment_status"] == "Lunas" and r["settlement_status"] == "Lunas", (sc, r.get("paid_total"), r.get("payment_status")))
    if pid_s:
        call("POST", f"vendor-invoices/{iS['id']}/payments/{pid_s}/cancel", {"reason": "uji"})
        g = call("GET", f"vendor-invoices/{iS['id']}")[1]
        check("ST4. Batal pembayaran 20jt: paid_total 40jt, sisa 20jt, kembali Dibayar Sebagian (DP tetap 40jt)",
              g["paid_total"] == 40_000_000 and g["remaining"] == 20_000_000 and g["dp_allocated_total"] == 40_000_000 and g["payment_status"] == "Dibayar Sebagian",
              (g.get("paid_total"), g.get("remaining"), g.get("payment_status")))

    check("ST5. settlement_status (Status Hutang) terpisah: Belum Lunas saat sisa > 0, Lunas saat sisa 0",
          gS["settlement_status"] == "Belum Lunas" and rowS.get("settlement_status") == "Belum Lunas", (gS.get("settlement_status"), rowS.get("settlement_status")))
    # DP menutup 100% Invoice tanpa pembayaran kas
    pF = mk_po(100000, dp_enabled=True, dp_type="percentage", dp_value=40)   # DP 40jt
    pay_dp(pF)
    dF = mk_do((pF, 40000))                                                   # DO 40jt
    sc, iF = inv("INV-DP-FULL", [(dF, 40_000_000)], dp=[(pF, 40_000_000)])
    gF = call("GET", f"vendor-invoices/{iF['id']}")[1] if sc == 200 else {}
    lF = next((x for x in call("GET", "vendor-invoices")[1] if x["id"] == iF.get("id")), {}) if sc == 200 else {}
    check("FULL. DP 100%: amount 40jt, DP 40jt, paid 0, sisa 0, payment_status Belum Dibayar, Status Hutang Lunas, due_state '-'",
          sc == 200 and all(x.get("amount") == 40_000_000 and x.get("dp_allocated_total") == 40_000_000 and x.get("paid_total") == 0 and x.get("remaining") == 0
                            and x.get("payment_status") == "Belum Dibayar" and x.get("settlement_status") == "Lunas" and x.get("due_state") == "-" for x in (gF, lF)),
          {k: gF.get(k) for k in ("amount", "dp_allocated_total", "paid_total", "remaining", "payment_status", "settlement_status", "due_state")})
    sc, r = call("POST", f"vendor-invoices/{iF['id']}/payments", {"date": "2026-06-10", "amount": 1})
    g2 = call("GET", f"vendor-invoices/{iF['id']}")[1]
    check("FULL-b. DP 100%: pembayaran kas tambahan ditolak (sisa 0); DP tidak tercatat sebagai pembayaran (payments kosong)",
          sc == 409 and g2["paid_total"] == 0 and not [x for x in g2.get("payments") or [] if x.get("status") == "Aktif"], (sc, g2.get("paid_total")))
    sc, pg = call("GET", "vendor-invoices?page=1&page_size=500&facets=payment_status,settlement_status")
    fac = (pg or {}).get("facets") or {}
    check("FULL-c. Monitoring: facet Status Hutang tersedia & filter settlement_status=Lunas memuat invoice DP penuh",
          sc == 200 and "Lunas" in [str(v.get("value") if isinstance(v, dict) else v) for v in fac.get("settlement_status") or []]
          and iF["id"] in {x["id"] for x in (call("GET", "vendor-invoices?page=1&page_size=500&f_settlement_status=Lunas")[1] or {}).get("items") or []},
          fac.get("settlement_status"))

    # 22 edit mempertahankan alokasi; perubahan DO yang membuat DP invalid -> BLOCK
    sc, r = call("PUT", f"vendor-invoices/{i1['id']}", {"notes": "revisi catatan"})
    check("22. Edit invoice (tanpa kirim dp_allocations) mempertahankan alokasi DP", sc == 200 and r["dp_allocated_total"] == 30_000_000 and len(r["dp_allocations"]) == 1, (sc, r.get("dp_allocations")))
    sc, r = call("PUT", f"vendor-invoices/{i1['id']}", {"amount": 20_000_000, "allocations": [{"do_id": d_p1a["id"], "amount": 20_000_000}]})
    still = call("GET", f"vendor-invoices/{i1['id']}")[1]
    check("22b. Perubahan DO membuat DP lama invalid -> BLOCK dgn pesan jelas, alokasi tidak hilang", sc == 409 and "alokasi DP" in str(r) and still["dp_allocated_total"] == 30_000_000, (sc, r))
    sc, r = call("PUT", f"vendor-invoices/{i1['id']}", {"amount": 20_000_000, "allocations": [{"do_id": d_p1a["id"], "amount": 20_000_000}], "dp_allocations": [{"po_id": p1["id"], "amount": 20_000_000}]})
    check("22c. Edit dengan penyesuaian DP eksplisit -> tersimpan", sc == 200 and r["dp_allocated_total"] == 20_000_000 and r["remaining"] == 0, (sc, r))
    sc, L = dp_list()
    check("DP tersedia bertambah setelah alokasi diturunkan (40-20-10=10jt)", L[p1["id"]]["dp_available"] == 10_000_000, L[p1["id"]])
    sc, r = call("DELETE", f"vendor-invoices/{i2['id']}")
    sc2, L = dp_list()
    check("23. Delete invoice mengembalikan DP availability (10jt -> 20jt)", sc == 200 and L[p1["id"]]["dp_available"] == 20_000_000, (sc, L[p1["id"]]))

    # ---------------------------------------------------------------- 1 DO + 2 PO (contoh spesifikasi)
    pa = mk_po(100000, dp_enabled=True, dp_type="nominal", dp_value=40_000_000)   # PO-001
    pb = mk_po(40000, dp_enabled=True, dp_type="percentage", dp_value=40)          # PO-002 DP 16jt
    pay_dp(pa); pay_dp(pb)
    dab = mk_do((pa, 60000), (pb, 40000))                                         # 60jt + 40jt
    sc, C = cands([(dab, 80_000_000)])
    ca, cb = C.get(pa["no"]) or {}, C.get(pb["no"]) or {}
    check("15. 1 DO + 2 PO: popup menampilkan kedua PO, bagian invoice 48jt/32jt", ca.get("invoice_portion") == 48_000_000 and cb.get("invoice_portion") == 32_000_000, (ca, cb))
    check("15b. suggested PO-001 = 40jt, PO-002 = 16jt", ca.get("suggested") == 40_000_000 and cb.get("suggested") == 16_000_000, (ca.get("suggested"), cb.get("suggested")))
    sc, iab = inv("INV-DP-AB", [(dab, 80_000_000)], dp=[(pa, 40_000_000), (pb, 16_000_000)])
    check("15c. DP 56jt, Sisa Hutang 24jt; alokasi tersimpan per PO", sc == 200 and iab["dp_allocated_total"] == 56_000_000 and iab["remaining"] == 24_000_000
          and len(iab["dp_allocations"]) == 2, (sc, iab.get("remaining")))
    rows = dbq("SELECT COUNT(*) FROM vendor_invoice_dp_allocations WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.invoice_id'))=%s", [iab["id"]])
    check("alokasi DP disimpan di vendor_invoice_dp_allocations (2 baris)", rows == 2, rows)

    # ---------------------------------------------------------------- 2 DO + beberapa PO
    p3 = mk_po(50000, dp_enabled=True, dp_type="percentage", dp_value=40)          # DP 20jt
    p4 = mk_po(30000, dp_enabled=True, dp_type="nominal", dp_value=10_000_000)
    pay_dp(p3); pay_dp(p4)
    dA = mk_do((p3, 20000), (p4, 30000))
    dB = mk_do((p3, 30000))
    sc, C = cands([(dA, 50_000_000), (dB, 30_000_000)])
    c3, c4 = C.get(p3["no"]) or {}, C.get(p4["no"]) or {}
    check("16. 2 DO + beberapa PO: bagian invoice PO3=50jt, PO4=30jt; suggested 20jt/10jt", c3.get("invoice_portion") == 50_000_000 and c4.get("invoice_portion") == 30_000_000
          and c3.get("suggested") == 20_000_000 and c4.get("suggested") == 10_000_000, (c3, c4))
    sc, i34 = inv("INV-DP-34", [(dA, 50_000_000), (dB, 30_000_000)], dp=[(p3, 20_000_000), (p4, 10_000_000)])
    check("16b. Invoice 80jt - DP 30jt = Sisa 50jt", sc == 200 and i34["remaining"] == 50_000_000, (sc, i34.get("remaining")))
    sc, r = call("GET", f"vendor-invoices/{i34['id']}/dp-candidates")
    check("GET dp-candidates invoice tersimpan memuat alokasi saat ini", sc == 200 and sorted(x["current_allocation"] for x in r) == [10_000_000, 20_000_000], r)

    # 29. concurrent allocation (2 invoice berbeda, DP sama)
    pz = mk_po(100000, dp_enabled=True, dp_type="nominal", dp_value=40_000_000)
    pay_dp(pz)
    dz1, dz2 = mk_do((pz, 30000)), mk_do((pz, 30000))
    bar = threading.Barrier(2)

    def fire_inv(args):
        no, d = args
        s = session()
        b = V.inv_body(no, "supX", [(d, 30_000_000)])
        b["dp_allocations"] = [{"po_id": pz["id"], "amount": 30_000_000}]
        bar.wait()
        return s.post(f"{API}/vendor-invoices", json=b).status_code
    with ThreadPoolExecutor(2) as ex:
        codes = list(ex.map(fire_inv, [("INV-CC-1", dz1), ("INV-CC-2", dz2)]))
    used = dbq("SELECT COALESCE(SUM(JSON_EXTRACT(doc,'$.amount')),0) FROM vendor_invoice_dp_allocations WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.po_id'))=%s", [pz["id"]])
    check("29. Concurrent allocation: hanya 1 invoice berhasil, DP terpakai <= DP dibayar", sorted(codes) == [200, 409] and float(used) == 30_000_000, (codes, used))

    # ---------------------------------------------------------------- backward compat invoice tanpa DP
    p0 = mk_po(5000)
    d0 = mk_do((p0, 5000))
    sc, i0 = inv("INV-NODP", [(d0, 5_000_000)])
    check("Invoice tanpa DP: remaining = amount - paid_total (tanpa perubahan perilaku)", sc == 200 and i0["remaining"] == 5_000_000 and i0["dp_allocated_total"] == 0
          and i0["dp_allocations"] == [], (sc, i0.get("remaining")))

    # ---------------------------------------------------------------- permission / division / tenant (matriks akses)
    draft_id = d9b["active_payment"]["id"]                  # draft aktif di divisi utama
    att_q = {"entity": "supplier_dp_payment", "entity_id": pay1["id"]}

    def att_list(u):
        return u("GET", "attachments?" + "&".join(f"{k}={v}" for k, v in att_q.items()))[0]

    # A. permission salah (tanpa supplier_dp.*) + divisi benar
    mgr_id, mgr_email = mk_user_id("manager")
    pu_id, pu_email = mk_user_id("purchasing")
    dir_id, dir_email = mk_user_id("director")
    # Default role: hanya Admin yang otomatis memiliki supplier_dp.*; Direktur/Purchasing TIDAK (walau punya invoice.pay)
    eff = {}
    for nm, em in (("admin", None), ("director", dir_email), ("purchasing", pu_email)):
        sc_, me_ = (call("GET", "access/me") if em is None else V.U(em)("GET", "access/me"))
        eff[nm] = {k for k in (me_.get("effective") or []) if str(k).startswith(("supplier_dp.", "invoice.pay"))}
    check("R1. Admin default: supplier_dp.view/approve/print", {"supplier_dp.view", "supplier_dp.approve", "supplier_dp.print"} <= eff["admin"], eff["admin"])
    check("R2. Direktur & Purchasing default: punya invoice.pay tetapi TIDAK punya supplier_dp.* sama sekali",
          all("invoice.pay" in eff[r] and not any(k.startswith("supplier_dp.") for k in eff[r]) for r in ("director", "purchasing")), eff)
    dr = V.U(dir_email)
    codes = [dr("GET", "supplier-dp")[0], dr("POST", f"supplier-dp/payments/{d9b['active_payment']['id']}/approve", {})[0]]
    check("R3. Direktur default: list & approve DP via API -> 403", codes == [403, 403], codes)
    dr = reconf(dir_id, dir_email, overrides={"supplier_dp.view": "allow"})
    sc_, rows_ = dr("GET", "supplier-dp")
    sc2_, _ = dr("POST", f"supplier-dp/payments/{d9b['active_payment']['id']}/approve", {})
    check("R4. Grant manual granular (hanya supplier_dp.view) ke Direktur: list OK, approve tetap 403", sc_ == 200 and isinstance(rows_, list) and sc2_ == 403, (sc_, sc2_))
    mgr = reconf(mgr_id, mgr_email, divs=[M["div"]["id"]])
    codes = [mgr("GET", "supplier-dp")[0], mgr("GET", f"supplier-dp/{p1['id']}")[0], mgr("POST", f"supplier-dp/{p9['id']}/draft", {})[0],
             mgr("PUT", f"supplier-dp/payments/{draft_id}", {"notes": "x"})[0], mgr("POST", f"supplier-dp/payments/{draft_id}/approve", {})[0],
             mgr("POST", f"supplier-dp/payments/{draft_id}/cancel", {"reason": "x"})[0], mgr("GET", f"supplier-dp/payments/{pay1['id']}/print")[0],
             att_list(mgr)]
    check("A. Manager tanpa supplier_dp.* (divisi benar): list/detail/draft/edit/approve/cancel/print/lampiran -> 403", all(c == 403 for c in codes), codes)
    sc, me = mgr("GET", "access/me")
    check("A2. Manager: effective permission tidak memuat supplier_dp.* (menu disembunyikan)",
          sc == 200 and isinstance(me.get("effective"), list) and not any(str(k).startswith("supplier_dp.") for k in me["effective"]), me)
    nod = reconf(pu_id, pu_email, overrides={"supplier_dp.view": "deny", "supplier_dp.approve": "deny", "supplier_dp.print": "deny"}, divs=[M["div"]["id"]])
    codes = [nod("GET", "supplier-dp")[0], nod("GET", f"supplier-dp/{p1['id']}")[0], nod("POST", f"supplier-dp/payments/{draft_id}/approve", {})[0]]
    check("A3. Purchasing dgn supplier_dp.* deny (divisi benar) -> 403", all(c == 403 for c in codes), codes)

    # B. view tanpa approve
    viewer = reconf(pu_id, pu_email, overrides={"supplier_dp.view": "allow", "supplier_dp.print": "allow"})
    sc, _ = viewer("GET", "supplier-dp")
    sc_d, det = viewer("GET", f"supplier-dp/{p9['id']}")
    codes = [viewer("POST", f"supplier-dp/{p1['id']}/draft", {})[0], viewer("PUT", f"supplier-dp/payments/{draft_id}", {"notes": "x"})[0],
             viewer("POST", f"supplier-dp/payments/{draft_id}/approve", {"payment_date": "2026-06-05", "fund_source": "Kas"})[0],
             viewer("POST", f"supplier-dp/payments/{draft_id}/cancel", {"reason": "x"})[0]]
    still = call("GET", f"supplier-dp/{p9['id']}")[1]["active_payment"]
    check("B. view tanpa approve: list/detail OK; draft/edit/approve/cancel via API -> 403; draft tetap Menunggu Verifikasi",
          sc == 200 and sc_d == 200 and all(c == 403 for c in codes) and still["status"] == "Draft", (sc, sc_d, codes, still.get("status")))

    # C. tanpa print
    nop = reconf(pu_id, pu_email, overrides={"supplier_dp.view": "allow", "supplier_dp.approve": "allow"})
    sc, _ = nop("GET", f"supplier-dp/payments/{pay1['id']}/print")
    sc2, _ = nop("GET", f"supplier-dp/{p1['id']}")
    check("C. tanpa supplier_dp.print: print -> 403, detail tetap 200", sc == 403 and sc2 == 200, (sc, sc2))

    # D. permission benar + divisi salah
    pd2 = mk_po(1000, div="div2", dp_enabled=True, dp_type="percentage", dp_value=20)
    lim = reconf(pu_id, pu_email, overrides={"supplier_dp.view": "allow", "supplier_dp.approve": "allow", "supplier_dp.print": "allow"}, divs=[M["div2"]["id"]])
    sc, rows = lim("GET", "supplier-dp")
    ids = {r["po_id"] for r in rows} if isinstance(rows, list) else set()
    check("28. Division isolation: list hanya DP divisi yang diizinkan", sc == 200 and pd2["id"] in ids and p1["id"] not in ids and p9["id"] not in ids, (sc, len(ids)))
    codes = [lim("GET", f"supplier-dp/{p1['id']}")[0], lim("POST", f"supplier-dp/{p1['id']}/draft", {})[0],
             lim("PUT", f"supplier-dp/payments/{draft_id}", {"notes": "x"})[0], lim("POST", f"supplier-dp/payments/{draft_id}/approve", {})[0],
             lim("POST", f"supplier-dp/payments/{draft_id}/cancel", {"reason": "x"})[0], lim("GET", f"supplier-dp/payments/{pay1['id']}/print")[0],
             att_list(lim)]
    ghost = [lim("GET", f"supplier-dp/{uuid.uuid4()}")[0], lim("POST", f"supplier-dp/payments/{uuid.uuid4()}/approve", {})[0]]
    _, r404 = lim("GET", f"supplier-dp/{p1['id']}")
    check("28a. Divisi lain via ID: detail/draft/edit/approve/cancel/print/lampiran -> 404 generik (sama dgn ID tidak ada)",
          all(c == 404 for c in codes + ghost) and "tidak ditemukan atau tidak dapat diakses" in str(r404), (codes, ghost, r404))
    sc5, r5 = lim("POST", "vendor-invoices/dp-candidates", {"supplier_id": M["supX"]["id"], "allocations": [{"do_id": dab["id"], "amount": 1}]})
    check("28c. Kandidat DP Invoice dari DO divisi lain -> 404 generik", sc5 == 404 and dab["no"] not in str(r5), (sc5, r5))
    # DO campuran lintas divisi ditolak oleh aturan DO existing -> DP lintas divisi tidak dapat "menumpang" lewat DO.
    pay_dp(pd2)
    pm = mk_po(1000, dp_enabled=True, dp_type="percentage", dp_value=20)
    pay_dp(pm)
    sc_mix, _ = call("POST", "do", {"supplier_id": M["supX"]["id"], "supplier_dn": f"SJ-{uuid.uuid4().hex[:6]}", "default_warehouse_id": M["wh"]["id"],
                                    "lines": [do_line(pm, 1000), do_line(pd2, 1000)]})
    dd2 = mk_do((pd2, 1000))
    sc_l, rl = lim("POST", "vendor-invoices/dp-candidates", {"supplier_id": M["supX"]["id"], "allocations": [{"do_id": dd2["id"], "amount": 1_000_000}]})
    l_nos = {x["po_no"] for x in rl} if isinstance(rl, list) else set()
    check("28d. User divisi 2: kandidat DP hanya PO divisi 2 (DP PO divisi lain dgn supplier sama tidak muncul); DO lintas divisi ditolak",
          sc_mix == 400 and sc_l == 200 and l_nos == {pd2["no"]} and pm["no"] not in l_nos, (sc_mix, sc_l, l_nos))
    b = V.inv_body(f"INV-D2-{uuid.uuid4().hex[:4]}", "supX", [(dd2, 1_000_000)])
    b["dp_allocations"] = [{"po_id": pm["id"], "amount": 100_000}]
    sc6, r6 = lim("POST", "vendor-invoices", b)
    check("28e. User divisi 2 memaksa alokasi DP PO divisi lain via API -> ditolak, tidak tersimpan", sc6 == 400 and pm["no"] not in str(r6), (sc6, r6))

    # E. tenant berbeda
    u = uuid.uuid4().hex[:8]
    s2 = requests.Session()
    res = s2.post(f"{API}/saas/register", json={"company_name": f"DPB {u}", "pic_name": "QA", "email": f"dpb_{u}@example.com", "whatsapp": "+628123456789",
                                                "workspace_slug": f"dpb-{u}", "plan_code": "starter", "password": V.PW, "address": "x", "terms_accepted": True}).json()
    tok = res.get("token") or s2.post(f"{API}/auth/login", json={"email": f"dpb_{u}@example.com", "password": V.PW}).json().get("token")
    s2.headers.update({"Authorization": f"Bearer {tok}"})
    rows = s2.get(f"{API}/supplier-dp").json()
    codes = [s2.get(f"{API}/supplier-dp/{p1['id']}").status_code, s2.post(f"{API}/supplier-dp/{p6['id']}/draft", json={}).status_code,
             s2.get(f"{API}/supplier-dp/payments/{pay1['id']}/print").status_code,
             s2.get(f"{API}/attachments", params=att_q).status_code,
             s2.put(f"{API}/supplier-dp/payments/{draft_id}", json={"notes": "x"}).status_code,
             s2.post(f"{API}/supplier-dp/payments/{draft_id}/approve", json={}).status_code,
             s2.post(f"{API}/supplier-dp/payments/{draft_id}/cancel", json={"reason": "x"}).status_code,
             upload(draft_id, s2)[0]]
    cands_t = s2.post(f"{API}/vendor-invoices/dp-candidates", json={"supplier_id": M["supX"]["id"], "allocations": [{"do_id": dab["id"], "amount": 1}]})
    check("27. Tenant isolation: tenant lain tidak melihat/memproses DP tenant ini (semua 404)", isinstance(rows, list) and not rows and all(c == 404 for c in codes)
          and cands_t.status_code == 404, (rows if not isinstance(rows, list) else len(rows), codes, cands_t.status_code))
    still = call("GET", f"supplier-dp/{p9['id']}")[1]["active_payment"]
    check("27b. Draft tidak berubah setelah percobaan akses tenant/divisi lain", still["status"] == "Draft" and not still.get("notes"), still)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
