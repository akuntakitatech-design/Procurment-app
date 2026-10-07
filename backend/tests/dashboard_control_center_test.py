"""Dashboard Procurement & Finance v1 — GET /api/dashboard/control-center (throwaway tenants, localhost:8001).

Memastikan: tenant isolation, division scope (termasuk division_id manual di luar scope), filter periode/divisi/
project/supplier, KPI Approval 1/2 (document_status derived), receipt KPI, PO terlambat, invoice belum diterima
(DO belum ditagih), sisa hutang (amount - DP dialokasikan - dibayar), DP belum dialokasikan, jatuh tempo <= 7 hari,
lewat jatuh tempo, ranking supplier, agregasi chart, izin finance/harga, dan angka kartu = hasil drill-down list.
"""
import sys
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import po_approval2_batch_test as A
import receipt_control_test as T
import supplier_dp_test as SD
import vendor_invoice_test as V

call, check = T.call, T.check
TD = datetime.now(ZoneInfo("Asia/Jakarta")).date()
ISO = lambda d: d.isoformat()  # noqa: E731
M = None


def cc(u=None, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v is not None)
    return (u or call)("GET", "dashboard/control-center" + (f"?{qs}" if qs else ""))


def drill(path, u=None, **q):
    qs = "&".join(f"{k}={v}" for k, v in {"page": 1, "page_size": 100, **q}.items() if v not in (None, ""))
    sc, d = (u or call)("GET", f"{path}?{qs}")
    return d if isinstance(d, dict) else {"items": [], "total": -1}


def mkpo(qty, price, div="div", item="item", supplier="supX", project="pa", eta=None, submit=True, **dp):
    sc, mro = call("POST", "mro", {"no": f"MRO-{uuid.uuid4().hex[:6]}", "division_id": M[div]["id"], "requester": "Budi", "submitted": True,
                                   "lines": [{"item_id": M[item]["id"], "qty": qty, "warehouse_id": M["wh"]["id"], "project_id": M[project]["id"]}]}, 200)
    call("POST", f"mro/{mro['id']}/submit", {})
    sc, ro = call("POST", "ro", {"division_id": M[div]["id"], "submitted": True,
                                 "lines": [{"item_id": M[item]["id"], "qty": qty, "warehouse_id": M["wh"]["id"], "project_id": M[project]["id"],
                                            "sources": [{"mro_id": mro["id"], "line_id": mro["lines"][0]["id"], "qty": qty}]}]}, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    body = {"supplier_id": M[supplier]["id"], "division_id": M[div]["id"], **dp,
            "lines": [{"item_id": M[item]["id"], "qty": qty, "price": price, "warehouse_id": M["wh"]["id"], "project_id": M[project]["id"],
                       "sources": [{"ro_id": ro["id"], "line_id": ro["lines"][0]["id"], "qty": qty}]}]}
    if eta:
        body["eta"] = eta
    sc, po = call("POST", "po", body, 200)
    if submit:
        call("POST", f"po/{po['id']}/submit", {})
        if call("GET", f"po/{po['id']}")[1].get("status") != "Approved":
            call("POST", f"po/{po['id']}/approve", {})
    return call("GET", f"po/{po['id']}")[1]


def mkdo(po, qty, supplier="supX"):
    sc, d = call("POST", "do", {"supplier_id": M[supplier]["id"], "supplier_dn": f"SJ-{uuid.uuid4().hex[:6]}",
                                "default_warehouse_id": M["wh"]["id"], "lines": [SD.do_line(po, qty)]}, 200)
    return d


def mkinv(no, do, amount, inv_date, due, dp=None, supplier="supX"):
    b = {"supplier_id": M[supplier]["id"], "invoice_no": no, "invoice_date": inv_date, "received_date": inv_date, "due_date": due,
         "amount": amount, "tax_amount": 0, "allocations": [{"do_id": do["id"], "amount": amount}]}
    if dp:
        b["dp_allocations"] = [{"po_id": p["id"], "amount": a} for p, a in dp]
    sc, r = call("POST", "vendor-invoices", b)
    check(f"Invoice {no} tercatat", sc == 200, (sc, r))
    return r


def ids(rows, key="id"):
    return {r.get(key) for r in rows}


def main():
    global M
    M = T.setup()
    SD.M = V.M = M
    sc, M["divB"] = call("POST", "master/divisions", {"code": f"DB{uuid.uuid4().hex[:5]}", "name": "Divisi Produksi"}, 200)
    sc, M["itemB"] = call("POST", "master/items", {"code": f"IB{uuid.uuid4().hex[:5]}", "name": "Oli Mesin", "unit": "PCS", "is_active": True,
                                                   **T.item_ref(M, division_id=M["divB"]["id"])}, 200)
    off = {"mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []}, "po": {"enabled": False, "levels": []}}
    call("PUT", "settings/approval_modules", {"modules": off}, 200)

    # ---------------- PO approved (tanpa approval) + penerimaan
    yday, tmr = ISO(TD - timedelta(days=1)), ISO(TD + timedelta(days=30))
    pLate = mkpo(10, 100_000, eta=yday)                                   # Approved, Belum Diterima, ETA lewat
    pPart = mkpo(10, 50_000, supplier="supY", project="pb", eta=tmr)       # Approved, Diterima Sebagian
    pFull = mkpo(4, 250_000)                                              # Ditutup
    pB = mkpo(5, 300_000, div="divB", item="itemB", supplier="supY")      # divisi B
    check("Fixture PO approved", all(p.get("status") == "Approved" for p in (pLate, pPart, pFull, pB)),
          [p.get("status") for p in (pLate, pPart, pFull, pB)])
    dPart = mkdo(pPart, 4, supplier="supY")
    dFull = mkdo(pFull, 4)
    dB = mkdo(pB, 5, supplier="supY")

    # ---------------- DP + Invoice (rumus sisa hutang)
    pDpA = mkpo(10, 100_000, dp_enabled=True, dp_type="nominal", dp_value=400_000)     # 1 jt, DP 400 rb
    pDpB = mkpo(20, 100_000, dp_enabled=True, dp_type="nominal", dp_value=1_000_000)   # 2 jt, DP 1 jt
    pDpC = mkpo(10, 100_000, dp_enabled=True, dp_type="nominal", dp_value=500_000)     # DP dibayar, belum dialokasikan
    for p in (pDpA, pDpB, pDpC):
        SD.pay_dp(p)
    dA, dBB = mkdo(pDpA, 10), mkdo(pDpB, 10)
    i_case1 = mkinv(f"INV-A-{uuid.uuid4().hex[:4]}", dA, 1_000_000, ISO(TD - timedelta(days=5)), ISO(TD - timedelta(days=2)), dp=[(pDpA, 200_000)])
    sc, r = call("POST", f"vendor-invoices/{i_case1['id']}/payments", {"date": ISO(TD), "amount": 300_000, "reference": "TRF-1"})
    check("Pembayaran 300.000 invoice kasus 1", sc == 200, (sc, r))
    i_case2 = mkinv(f"INV-B-{uuid.uuid4().hex[:4]}", dBB, 1_000_000, ISO(TD), ISO(TD + timedelta(days=3)), dp=[(pDpB, 1_000_000)])
    i_soon = mkinv(f"INV-C-{uuid.uuid4().hex[:4]}", dFull, 1_000_000, ISO(TD), ISO(TD + timedelta(days=3)))
    mkinv(f"INV-D-{uuid.uuid4().hex[:4]}", dB, 1_500_000, ISO(TD), ISO(TD + timedelta(days=60)), supplier="supY")

    # ---------------- Approval 1 / Approval 2
    a1, a2 = A.mk_user("l1", [M["div"]["id"]]), A.mk_user("l2", [M["div"]["id"]])
    A.set_ov(a2, {"upload_attachment": "allow"})
    call("PUT", "settings/approval_modules", {"modules": {**off, "po": {"enabled": True, "levels": [
        {"level": 1, "email": a1.email}, {"level": 2, "email": a2.email}]}}}, 200)
    mkpo(1, 10_000, submit=False)  # Draft (tidak dihitung di kartu approval)
    pW1, pR2, pW2 = (mkpo(1, 20_000 + i, submit=False) for i in range(3))
    for p in (pW1, pR2, pW2):
        call("POST", f"po/{p['id']}/submit", {}, 200)
    for p in (pR2, pW2):
        a1("POST", f"approvals/{A.task(a1, p['id'], 1)['id']}/approve", {"note": "ok"})
    sc, el = a2("GET", "approval2/po/eligible")
    tid = {x["po_id"]: x["approval_task_id"] for x in el or []}
    sc, B = a2("POST", "approval2/po/batches", {"title": "Dash", "submission_date": ISO(TD), "approval_task_ids": [tid[pW2["id"]]]})
    a2("POST", f"approval2/po/batches/{B['id']}/submit", {})
    call("PUT", "settings/approval_modules", {"modules": off}, 200)
    for u in (a1, a2):  # batas user paket starter: nonaktifkan approver fixture (task tetap Pending)
        call("DELETE", f"users/{u.uid}", None, 200)

    # ================= admin (global) — periode semua
    sc, D = cc(period="all")
    check("control-center 200 + kontrak", sc == 200 and all(k in D for k in ("filters", "procurement", "finance", "inventory", "charts",
                                                                             "supplier_rank", "attention", "generated_at")), (sc, list(D)[:12]))
    P, Fn = D["procurement"], D["finance"]
    print("   timing_ms:", D.get("timing_ms"))
    check("Nominal berupa angka (bukan string)", isinstance(P["po_value"]["value"], (int, float)) and isinstance(Fn["payable"]["value"], (int, float)))

    def kpi_drill(kind, want_ids, label):
        lst = drill("po", rf_kind=kind)
        check(f"KPI {label}: kartu = drill-down = fixture", P[kind]["count"] == lst["total"] and ids(lst["items"]) == want_ids,
              (P[kind]["count"], lst["total"], len(want_ids)))
    kpi_drill("waiting_a1", {pW1["id"]}, "Menunggu Approval 1")
    kpi_drill("ready_a2", {pR2["id"]}, "Siap Diajukan Approval 2")
    kpi_drill("waiting_a2", {pW2["id"]}, "Menunggu Approval 2")
    kpi_drill("late", {pLate["id"]}, "PO Terlambat")
    kpi_drill("partial", {pPart["id"], pDpB["id"]}, "PO Diterima Sebagian")
    nr = drill("po", rf_kind="not_received")
    check("KPI PO Belum Diterima = Disetujui & Belum Diterima", P["not_received"]["count"] == nr["total"] and pLate["id"] in ids(nr["items"])
          and not ({pPart["id"], pFull["id"], pW1["id"]} & ids(nr["items"])), (P["not_received"]["count"], nr["total"]))
    ap = drill("po", rf_kind="approved")
    check("KPI PO Disetujui = document_status Approved (Ditutup tidak termasuk)", P["approved"]["count"] == ap["total"]
          and pFull["id"] not in ids(ap["items"]) and pLate["id"] in ids(ap["items"]))
    full = drill("po")
    comp = D["charts"]["composition"]
    check("Komposisi donut: total = jumlah PO list = Σ status", comp["total"] == full["total"] == sum(x["count"] for x in comp["items"]),
          (comp["total"], full["total"]))
    cm = {x["status"]: x["count"] for x in comp["items"]}
    check("Komposisi memuat Draft/WA1/RA2/WA2/Approved/Closed", all(cm.get(s, 0) >= 1 for s in
          ("Draft", "Waiting Approval 1", "Ready Approval 2", "Waiting Approval 2", "Approved", "Closed")), cm)
    valid_list = [r for r in full["items"] if r.get("status") in ("Approved", "Partially Received", "Fully Received")]
    check("Nilai PO = Σ Grand Total PO valid (Draft/Waiting/Rejected/Cancelled dikecualikan)",
          abs(P["po_value"]["value"] - sum(float(r.get("grand_total") or 0) for r in valid_list)) < 0.01 and P["po_value"]["count"] == len(valid_list),
          (P["po_value"], len(valid_list)))
    check("MRO Belum Diproses & RO Belum Menjadi PO (dokumen Draft PO tidak memakan sisa RO? dihitung dari alokasi)",
          P["mro_open"] is not None and P["ro_open"] is not None and P["mro_open"]["count"] == drill("mro", rf_kind="open")["total"]
          and P["ro_open"]["count"] == drill("ro", rf_kind="open")["total"], (P["mro_open"], P["ro_open"]))

    # ---------------- Finance
    sc, inv1 = call("GET", f"vendor-invoices/{i_case1['id']}")
    check("Rumus kasus 1: 1.000.000 - DP 200.000 - bayar 300.000 = 500.000", abs(float(inv1.get("remaining") or 0) - 500_000) < 0.01,
          inv1.get("remaining"))
    sc, inv2 = call("GET", f"vendor-invoices/{i_case2['id']}")
    check("Rumus kasus 2: DP 1.000.000 penuh, bayar 0 -> sisa 0; payment_status tetap engine existing",
          abs(float(inv2.get("remaining") or 0)) < 0.01 and inv2.get("payment_status") == "Belum Dibayar", (inv2.get("remaining"), inv2.get("payment_status")))
    expect_payable = 500_000 + 0 + 1_000_000 + 1_500_000
    check("Sisa Hutang Supplier = Σ max(amount - DP - paid, 0) (cross-check 4 invoice)", abs(Fn["payable"]["value"] - expect_payable) < 0.01
          and Fn["payable"]["count"] == 3, Fn["payable"])
    li = drill("vendor-invoices", rf_kind="unpaid")
    check("Invoice Belum Dibayar: kartu = drill-down (remaining > 0); invoice tertutup DP tidak termasuk",
          Fn["invoice_unpaid"]["count"] == li["total"] == 3 and i_case2["id"] not in ids(li["items"])
          and abs(Fn["invoice_unpaid"]["value"] - sum(float(x["remaining"]) for x in li["items"])) < 0.01, (Fn["invoice_unpaid"], li["total"]))
    check("Lewat Jatuh Tempo = invoice kasus 1 (sisa 500.000)", Fn["overdue"] == {"count": 1, "value": 500_000.0}
          and ids(drill("vendor-invoices", rf_kind="overdue")["items"]) == {i_case1["id"]}, Fn["overdue"])
    check("Jatuh Tempo <= 7 hari: hanya invoice dengan sisa > 0 (kasus 2 sisa 0 dikecualikan)", Fn["due_soon"] == {"count": 1, "value": 1_000_000.0}
          and ids(drill("vendor-invoices", rf_kind="due_soon")["items"]) == {i_soon["id"]}, Fn["due_soon"])
    ub = drill("vendor-invoices/do-billing", rf_kind="unbilled")
    check("Invoice Belum Diterima = DO bernilai belum ditagih (kartu = drill-down, nilai = Σ sisa)",
          Fn["invoice_unbilled"]["count"] == ub["total"] and dPart["id"] in ids(ub["items"], "do_id") and dFull["id"] not in ids(ub["items"], "do_id")
          and abs(Fn["invoice_unbilled"]["value"] - sum(float(x["remaining"]) for x in ub["items"])) < 0.01, (Fn["invoice_unbilled"], ub["total"]))
    sc, dps = call("GET", "supplier-dp")
    av = {r["po_id"]: r["dp_available"] for r in dps}
    check("DP Belum Dialokasikan = Σ saldo DP positif (dibayar - dialokasikan)", Fn["dp_unallocated"]["count"] == 2
          and abs(Fn["dp_unallocated"]["value"] - (200_000 + 500_000)) < 0.01 and av.get(pDpB["id"]) == 0, (Fn["dp_unallocated"], av))
    check("DP Sudah Dibayar = Σ DP approved", Fn["dp_paid"] == {"count": 3, "value": 1_900_000.0}, Fn["dp_paid"])

    # ---------------- filter
    sc, Dd = cc(period="all", division_id=M["divB"]["id"])
    check("Filter Divisi B: hanya PO/invoice divisi B", Dd["procurement"]["po_total"]["count"] == 1 and Dd["finance"]["payable"]["value"] == 1_500_000
          and drill("po", rf_division_id=M["divB"]["id"])["total"] == 1, (Dd["procurement"]["po_total"], Dd["finance"]["payable"]))
    sc, Ds = cc(period="all", supplier_id=M["supY"]["id"])
    check("Filter Supplier Y: PO supplier Y saja", Ds["procurement"]["po_total"]["count"] == drill("po", rf_supplier_id=M["supY"]["id"])["total"] == 2,
          Ds["procurement"]["po_total"])
    sc, Dp = cc(period="all", project_id=M["pb"]["id"])
    check("Filter Project B: PO project B saja", Dp["procurement"]["po_total"]["count"] == 1 and Dp["procurement"]["partial"]["count"] == 1,
          Dp["procurement"]["po_total"])
    sc, Do = cc(date_from="2020-01-01", date_to="2020-01-31")
    check("Filter periode lampau: semua KPI 0", Do["procurement"]["po_total"]["count"] == 0 and Do["finance"]["payable"]["value"] == 0
          and Do["charts"]["composition"]["total"] == 0, Do["procurement"]["po_total"])
    sc, Dm = cc()
    m0 = ISO(TD.replace(day=1))
    check("Default periode = bulan berjalan", Dm["filters"]["date_from"] == m0 and Dm["filters"]["date_to"] >= ISO(TD), Dm["filters"])
    sc, r = cc(date_from="2026-10-31", date_to="2026-10-01")
    check("Periode terbalik ditolak 400", sc == 400, sc)

    # ---------------- chart & ranking
    tr = {x["month"]: x for x in D["charts"]["trend"]["series"]}
    cur = tr.get(ISO(TD)[:7]) or {}
    month_valid = [r for r in valid_list if str(r.get("date") or "")[:7] == ISO(TD)[:7]]
    sc, invs = call("GET", "vendor-invoices")
    month_inv = [i for i in invs if str(i.get("invoice_date") or "")[:7] == ISO(TD)[:7]]
    check("Tren bulan berjalan: Nilai PO = Σ Grand Total PO valid; Nilai Invoice = Σ invoice",
          abs((cur.get("po_value") or 0) - sum(float(r.get("grand_total") or 0) for r in month_valid)) < 0.01
          and abs((cur.get("invoice_value") or 0) - sum(float(i["amount"]) for i in month_inv)) < 0.01 and len(tr) == 12, cur)
    rk = D["supplier_rank"]["items"]
    vals = [x["value"] for x in rk]
    check("Top supplier urut Nilai PO desc, total per supplier = Σ PO valid", vals == sorted(vals, reverse=True) and len(rk) <= 5 and
          all(abs(x["value"] - sum(float(r.get("grand_total") or 0) for r in valid_list if r.get("supplier_id") == x["supplier_id"])) < 0.01 for x in rk), rk)
    att = D["attention"]
    pr = [x["priority"] for x in att["rows"]]
    check("Attention: urut paling urgent (overdue dulu) & hitungan tab", pr == sorted(pr) and att["rows"][0]["priority"] == 1
          and att["counts"]["due"] == 2 and att["counts"]["approval"] == 3, (pr[:6], att["counts"]))

    # ================= keamanan
    fin = V.mk_user("finance")
    sc, Df = cc(fin, period="all")
    check("User finance: section finance tampil", sc == 200 and Df["finance"] is not None and Df["permissions"]["invoice"], (sc, Df.get("permissions")))
    nonfin = V.mk_user("purchasing", {"invoice.view": "deny", "supplier_dp.view": "deny", "view_purchase_price": "deny"})
    sc, Dn = cc(nonfin, period="all")
    att_types = {x["doc_type"] for x in Dn["attention"]["rows"]}
    check("User non-finance: finance tidak dikirim, attention tanpa invoice/DO", sc == 200 and Dn["finance"] is None and not ({"Invoice", "DO"} & att_types)
          and Dn["charts"]["trend"]["series"][0]["invoice_value"] is None, (sc, Dn.get("finance"), att_types))
    check("Tanpa izin harga: nilai PO tidak dikirim (null)", Dn["procurement"]["po_value"]["value"] is None and
          all(x["value"] is None for x in Dn["supplier_rank"]["items"]) and all(x.get("value") is None for x in Dn["attention"]["rows"]),
          Dn["procurement"]["po_value"])
    lim = V.mk_user("manager", {"po.view": "allow", "invoice.view": "allow", "supplier_dp.view": "allow", "view_purchase_price": "allow",
                                "mro.view": "allow", "ro.view": "allow"}, divs=[M["div"]["id"]])
    sc, Dl = cc(lim, period="all")
    check("User scope Divisi A: aggregate tanpa PO/invoice Divisi B", sc == 200 and Dl["procurement"]["po_total"]["count"] == D["procurement"]["po_total"]["count"] - 1
          and abs(Dl["finance"]["payable"]["value"] - (expect_payable - 1_500_000)) < 0.01, (sc, Dl.get("procurement", {}).get("po_total"), (Dl.get("finance") or {}).get("payable")))
    check("Opsi filter Divisi mengikuti cakupan (admin = semua, user terbatas = Divisi A saja)",
          D["scope"]["divisions"] is None and Dl["scope"]["divisions"] == [M["div"]["id"]], (D.get("scope"), Dl.get("scope")))
    sc, r = cc(lim, period="all", division_id=M["divB"]["id"])
    check("User scope Divisi A kirim division_id B manual -> 403", sc == 403, sc)
    sc, r = cc(lim, period="all", supplier_id=M["supY"]["id"])
    check("User scope Divisi A filter supplier Y: tidak bocor PO divisi B", sc == 200 and r["procurement"]["po_total"]["count"] == 1, r.get("procurement", {}).get("po_total"))

    # tenant lain
    import requests
    s1 = T.S
    T.S = requests.Session()  # sesi bersih (tanpa header/cookie tenant pertama)
    M2 = T.setup()
    sc, D2 = cc(period="all")
    check("Tenant lain: tidak ada data tenant pertama", sc == 200 and D2["procurement"]["po_total"]["count"] == 0
          and D2["finance"]["payable"]["value"] == 0 and D2["supplier_rank"]["items"] == [], D2["procurement"]["po_total"])
    sc, D2s = cc(period="all", supplier_id=M["supX"]["id"])
    check("Tenant lain + supplier_id tenant pertama: tetap 0", sc == 200 and D2s["procurement"]["po_total"]["count"] == 0)
    sc, r = cc(period="all", division_id=M["div"]["id"])
    check("Tenant lain + division_id tenant pertama: tidak bocor (0 data)", sc in (200, 403) and (sc == 403 or r["procurement"]["po_total"]["count"] == 0), sc)
    T.S = s1
    del M2
    check("Tanpa login -> 401", requests.get(f"{T.API}/dashboard/control-center").status_code == 401)

    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\n{ok}/{len(T.RESULTS)} passed")
    return 0 if ok == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
