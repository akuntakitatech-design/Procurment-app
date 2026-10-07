"""Dashboard — POSISI s/d cut-off (saldo terbuka, termasuk periode sebelumnya) vs TRANSAKSI periode ini.

Throwaway tenant, localhost:8001. Hari ini (WIB) harus > 2026-10-06 (fixture bertanggal Sep/Okt 2026).

Finance (posisi historis direkonstruksi dari event bertanggal; field current remaining/paid_total TIDAK dipakai):
  Invoice X 1.000.000 tgl 20/09 (jatuh tempo 27/09), bayar 400.000 tgl 05/10
      cut-off 19/09 -> belum ada invoice (DO 18/09 = Invoice Belum Diterima 1.000.000)
      cut-off 22/09 -> Sisa 1.000.000, Jatuh Tempo <= 7 hari ; cut-off 30/09 -> Sisa 1.000.000, Lewat Jatuh Tempo
      cut-off 04/10 -> 1.000.000 ; cut-off 06/10 -> 600.000 ; 31/10 (bulan berjalan) -> 600.000
  Invoice Y 1.000.000 tgl 20/09 + DP 300.000 dialokasikan 03/10 (waktu alokasi dicatat)
      cut-off 30/09 -> Sisa 1.000.000 (DP Belum Dialokasikan 300.000) ; 31/10 -> 700.000 ; 02/10 -> 1.000.000 ; 04/10 -> 700.000
      edit invoice tanpa ubah DP tidak menggeser tanggal efektif alokasi DP.
Procurement:
  PO A tgl 15/09 diajukan, Approval 1 disetujui HARI INI -> per 30/09 'Menunggu Approval 1'; saat ini tidak.
  PO R tgl 12/09 (ETA 20/09), DO penuh tgl 02/10 -> per 18/09 Belum Diterima (tidak terlambat) ; per 30/09 Belum Diterima
      + Terlambat ; per 03/10 Ditutup (tidak di kartu) ; saat ini tidak di kartu.
  MRO tgl 05/09 dipenuhi RO tgl 02/10 -> per 30/09 MRO Belum Diproses ; saat ini tidak.
Drill-down list dengan rf_asof = angka kartu. Aktivitas (Total PO) hanya PO bertanggal di dalam periode.
"""
import json
import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import po_approval2_batch_test as A
import receipt_control_test as T
import supplier_dp_test as SD
import vendor_invoice_test as V

call, check = T.call, T.check
TODAY = datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()
M = None


def cc(**q):
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    sc, d = call("GET", "dashboard/control-center" + (f"?{qs}" if qs else ""))
    check(f"control-center 200 [{qs}]", sc == 200, (sc, str(d)[:200]))
    return d or {}


def drill(path, **q):
    qs = "&".join(f"{k}={v}" for k, v in {"page": 1, "page_size": 100, **q}.items() if v not in (None, ""))
    _, d = call("GET", f"{path}?{qs}")
    return d if isinstance(d, dict) else {"items": [], "total": -1}


def ids(rows):
    return {r.get("id") for r in rows}


def mkpo(qty, price, date, supplier="supX", eta=None, submit=True, **extra):
    body = {"supplier_id": M[supplier]["id"], "division_id": M["div"]["id"], "date": date, **extra,
            "lines": [{"item_id": M["item"]["id"], "qty": qty, "price": price, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]}
    if eta:
        body["eta"] = eta
    _, po = call("POST", "po", body, 200)
    if submit:
        call("POST", f"po/{po['id']}/submit", {})
        if call("GET", f"po/{po['id']}")[1].get("status") != "Approved":
            call("POST", f"po/{po['id']}/approve", {})
    return call("GET", f"po/{po['id']}")[1]


def mkdo(po, qty, date, supplier="supX"):
    sc, d = call("POST", "do", {"supplier_id": M[supplier]["id"], "supplier_dn": f"SJ-{uuid.uuid4().hex[:6]}", "date": date,
                                "default_warehouse_id": M["wh"]["id"], "lines": [SD.do_line(po, qty)]})
    check(f"DO {date} tercatat", sc == 200, (sc, d))
    return d


def inv_body(no, do, amount, inv_date, due, dp=None, supplier="supX"):
    b = {"supplier_id": M[supplier]["id"], "invoice_no": no, "invoice_date": inv_date, "received_date": inv_date, "due_date": due,
         "amount": amount, "tax_amount": 0, "allocations": [{"do_id": do["id"], "amount": amount}]}
    if dp:
        b["dp_allocations"] = [{"po_id": p["id"], "amount": a} for p, a in dp]
    return b


def fin(d, k):
    return (d.get("finance") or {}).get(k) or {}


def proc(d, k):
    return (d.get("procurement") or {}).get(k) or {}


def db_conn():
    if not os.environ.get("DATABASE_URL"):
        return None
    from urllib.parse import unquote, urlparse

    import pymysql
    u = urlparse(os.environ["DATABASE_URL"].replace("mariadb://", "mysql://"))
    return pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                           database=u.path.lstrip("/"), autocommit=True)


def main():
    global M
    if TODAY <= "2026-10-06":
        print("SKIP: fixture membutuhkan hari ini > 2026-10-06")
        return
    M = T.setup()
    SD.M = V.M = M
    off = {"mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []}, "po": {"enabled": False, "levels": []}}
    call("PUT", "settings/approval_modules", {"modules": off}, 200)
    sx, sy = M["supX"]["id"], M["supY"]["id"]

    # ================= Finance — pembayaran setelah cut-off (supplier X)
    pX = mkpo(10, 100_000, "2026-09-15")
    dX = mkdo(pX, 10, "2026-09-18")
    sc, iX = call("POST", "vendor-invoices", inv_body(f"INV-X-{uuid.uuid4().hex[:4]}", dX, 1_000_000, "2026-09-20", "2026-09-27"))
    check("Invoice X 1.000.000 tgl 20/09 tercatat", sc == 200, (sc, iX))
    sc, r = call("POST", f"vendor-invoices/{iX['id']}/payments", {"date": "2026-10-05", "amount": 400_000, "reference": "TRF-0510"})
    check("Pembayaran 400.000 tgl 05/10 tercatat", sc == 200, (sc, r))

    d = cc(date_from="2026-09-01", date_to="2026-09-19", supplier_id=sx)
    check("Per 19/09: invoice X belum ada -> Sisa Hutang 0", fin(d, "payable").get("value") == 0, fin(d, "payable"))
    check("Per 19/09: DO 18/09 = Invoice Belum Diterima 1.000.000", fin(d, "invoice_unbilled").get("count") == 1
          and abs(fin(d, "invoice_unbilled").get("value", 0) - 1_000_000) < 0.01, fin(d, "invoice_unbilled"))
    d = cc(date_from="2026-09-01", date_to="2026-09-22", supplier_id=sx)
    check("Per 22/09: Jatuh Tempo <= 7 hari (27/09 dibanding cut-off, bukan hari ini)", fin(d, "due_soon").get("count") == 1
          and fin(d, "overdue").get("count") == 0, (fin(d, "due_soon"), fin(d, "overdue")))
    d = cc(date_from="2026-09-01", date_to="2026-09-30", supplier_id=sx)
    check("Per 30/09: posisi historis (as_of=30/09, historical)", d.get("as_of") == "2026-09-30" and d.get("historical") is True, (d.get("as_of"), d.get("historical")))
    check("Per 30/09: Sisa Hutang = 1.000.000 (pembayaran 05/10 belum terjadi)", abs(fin(d, "payable").get("value", -1) - 1_000_000) < 0.01, fin(d, "payable"))
    check("Per 30/09: Invoice Belum Dibayar 1 / 1.000.000", fin(d, "invoice_unpaid").get("count") == 1
          and abs(fin(d, "invoice_unpaid").get("value", 0) - 1_000_000) < 0.01, fin(d, "invoice_unpaid"))
    check("Per 30/09: Lewat Jatuh Tempo (27/09 < 30/09)", fin(d, "overdue").get("count") == 1 and fin(d, "due_soon").get("count") == 0,
          (fin(d, "overdue"), fin(d, "due_soon")))
    for kind, card in (("unpaid", "invoice_unpaid"), ("overdue", "overdue")):
        lst = drill("vendor-invoices", rf_kind=kind, date_to="2026-09-30", rf_asof="2026-09-30", rf_supplier_id=sx)
        check(f"Drill {kind} per 30/09 (rf_asof) = kartu = invoice X", lst["total"] == fin(d, card).get("count") == 1 and ids(lst["items"]) == {iX["id"]},
              (lst["total"], fin(d, card)))
    lst = drill("vendor-invoices", rf_kind="unpaid", date_to="2026-09-19", rf_asof="2026-09-19", rf_supplier_id=sx)
    check("Drill unpaid per 19/09 -> kosong (invoice 20/09 belum ada)", lst["total"] == 0, lst["total"])
    d = cc(date_from="2026-10-01", date_to="2026-10-04", supplier_id=sx)
    check("Per 04/10 (Oktober): invoice September yang menggantung tetap tampil, Sisa 1.000.000", abs(fin(d, "payable").get("value", -1) - 1_000_000) < 0.01,
          fin(d, "payable"))
    d = cc(date_from="2026-10-01", date_to="2026-10-06", supplier_id=sx)
    check("Per 06/10: Sisa Hutang = 600.000 (pembayaran 05/10 mengurangi)", abs(fin(d, "payable").get("value", -1) - 600_000) < 0.01, fin(d, "payable"))
    d = cc(date_from="2026-10-01", date_to="2026-10-31", supplier_id=sx)
    check("Bulan berjalan (s/d 31/10): Sisa Hutang = 600.000, invoice bulan lalu tetap tampil", abs(fin(d, "payable").get("value", -1) - 600_000) < 0.01
          and fin(d, "invoice_unpaid").get("count") == 1, fin(d, "payable"))
    check("Bulan berjalan: as_of = hari ini (bukan historis)", d.get("as_of") == TODAY and d.get("historical") is False, (d.get("as_of"), d.get("historical")))
    check("Aktivitas: Invoice diterima periode Oktober = 0 (invoice X bertanggal September)", fin(d, "invoice_received").get("count") == 0,
          fin(d, "invoice_received"))
    lst = drill("vendor-invoices", rf_kind="unpaid", date_to="2026-10-31", rf_supplier_id=sx)
    check("Drill unpaid bulan berjalan (date_to saja) memuat invoice September", iX["id"] in ids(lst["items"]), lst["total"])

    # ================= Finance — alokasi DP setelah cut-off (supplier Y)
    pY = mkpo(10, 100_000, "2026-09-10", supplier="supY", dp_enabled=True, dp_type="nominal", dp_value=300_000)
    SD.pay_dp(pY)  # pembayaran DP tgl 05/06
    dY = mkdo(pY, 10, "2026-09-18", supplier="supY")
    bY = inv_body(f"INV-Y-{uuid.uuid4().hex[:4]}", dY, 1_000_000, "2026-09-20", "2026-12-31", dp=[(pY, 300_000)], supplier="supY")
    sc, iY = call("POST", "vendor-invoices", bY)
    check("Invoice Y 1.000.000 tgl 20/09 + alokasi DP 300.000 tercatat", sc == 200, (sc, iY))
    d = cc(date_from="2026-09-01", date_to="2026-09-30", supplier_id=sy)
    check("Per 30/09: Sisa Hutang Y = 1.000.000 (alokasi DP dicatat setelah cut-off)", abs(fin(d, "payable").get("value", -1) - 1_000_000) < 0.01, fin(d, "payable"))
    check("Per 30/09: DP Belum Dialokasikan = 300.000", abs((fin(d, "dp_unallocated") or {}).get("value", -1) - 300_000) < 0.01, fin(d, "dp_unallocated"))
    d = cc(date_from="2026-10-01", date_to="2026-10-31", supplier_id=sy)
    check("Per 31/10: Sisa Hutang Y = 700.000", abs(fin(d, "payable").get("value", -1) - 700_000) < 0.01, fin(d, "payable"))
    check("Per 31/10: DP Belum Dialokasikan = 0", (fin(d, "dp_unallocated") or {}).get("value") == 0, fin(d, "dp_unallocated"))
    d = cc(date_from="2026-06-01", date_to="2026-06-30", supplier_id=sy)
    check("Aktivitas DP Sudah Dibayar Juni = 300.000 (tanggal bayar DP 05/06)", abs((fin(d, "dp_paid") or {}).get("value", -1) - 300_000) < 0.01, fin(d, "dp_paid"))
    d = cc(date_from="2026-10-01", date_to="2026-10-31", supplier_id=sy)
    check("Aktivitas DP Sudah Dibayar Oktober = 0", (fin(d, "dp_paid") or {}).get("value") == 0, fin(d, "dp_paid"))

    cn = db_conn()
    if cn:
        try:
            n = cn.cursor().execute("UPDATE `vendor_invoice_dp_allocations` SET doc = JSON_SET(doc, '$.created_at', %s) "
                                    "WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.invoice_id')) = %s", ("2026-10-03T03:00:00+00:00", iY["id"]))
            check("Simulasi alokasi DP dicatat 03/10", n == 1, n)
            d = cc(date_from="2026-10-01", date_to="2026-10-02", supplier_id=sy)
            check("Per 02/10: Sisa Hutang Y = 1.000.000 (DP efektif 03/10)", abs(fin(d, "payable").get("value", -1) - 1_000_000) < 0.01, fin(d, "payable"))
            d = cc(date_from="2026-10-01", date_to="2026-10-04", supplier_id=sy)
            check("Per 04/10: Sisa Hutang Y = 700.000", abs(fin(d, "payable").get("value", -1) - 700_000) < 0.01, fin(d, "payable"))
            sc, r = call("PUT", f"vendor-invoices/{iY['id']}", {**{k: v for k, v in bY.items() if k != "dp_allocations"}, "notes": "edit QA",
                                                                 "edit_reason": "QA edit tanpa ubah DP"})
            check("Edit invoice Y tanpa mengubah DP", sc == 200, (sc, r))
            cur = cn.cursor()
            cur.execute("SELECT doc FROM `vendor_invoice_dp_allocations` WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.invoice_id')) = %s", (iY["id"],))
            docs = [json.loads(x[0]) for x in cur.fetchall()]
            check("Edit invoice mempertahankan waktu alokasi DP asli (03/10)", [x.get("created_at") for x in docs] == ["2026-10-03T03:00:00+00:00"], docs)
            d = cc(date_from="2026-10-01", date_to="2026-10-02", supplier_id=sy)
            check("Setelah edit: per 02/10 tetap 1.000.000", abs(fin(d, "payable").get("value", -1) - 1_000_000) < 0.01, fin(d, "payable"))
        finally:
            cn.close()
    else:
        print("  info: DATABASE_URL tidak tersedia — simulasi tanggal alokasi DP 03/10 dilewati")

    # ================= Procurement — approval & penerimaan per cut-off
    a1 = A.mk_user("l1", [M["div"]["id"]])
    call("PUT", "settings/approval_modules", {"modules": {**off, "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}]}}}, 200)
    pA = mkpo(1, 20_000, "2026-09-15", submit=False)
    call("POST", f"po/{pA['id']}/submit", {}, 200)
    t = A.task(a1, pA["id"], 1)
    sc, r = a1("POST", f"approvals/{t['id']}/approve", {"note": "ok"})
    check("PO A disetujui Approval 1 hari ini", sc == 200 and call("GET", f"po/{pA['id']}")[1].get("status") == "Approved", (sc, r))
    call("PUT", "settings/approval_modules", {"modules": off}, 200)
    call("DELETE", f"users/{a1.uid}", None, 200)

    pR = mkpo(10, 10_000, "2026-09-12", eta="2026-09-20")
    mkdo(pR, 10, "2026-10-02")
    check("PO R saat ini Ditutup (diterima penuh 02/10)", call("GET", f"po/{pR['id']}")[1].get("receipt_status") == "Diterima Penuh")

    def card_drill(df, dt, kind, asof=True):
        d = cc(date_from=df, date_to=dt)
        q = {"rf_kind": kind, "date_to": dt, **({"rf_asof": dt} if asof else {})}
        lst = drill("po", **q)
        return proc(d, kind).get("count"), lst["total"], ids(lst["items"]), d

    c, t_, s, d = card_drill("2026-09-01", "2026-09-30", "waiting_a1")
    check("Per 30/09: PO A 'Menunggu Approval 1' (disetujui setelah cut-off); kartu = drill", pA["id"] in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-10-01", "2026-10-31", "waiting_a1", asof=False)
    check("Saat ini: PO A tidak lagi Menunggu Approval 1; kartu = drill", pA["id"] not in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-09-01", "2026-09-30", "not_received")
    check("Per 30/09: PO R Belum Diterima (DO 02/10 setelah cut-off); kartu = drill", pR["id"] in s and pA["id"] not in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-09-01", "2026-09-30", "late")
    check("Per 30/09: PO R Terlambat (ETA 20/09 < cut-off)", pR["id"] in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-09-01", "2026-09-18", "late")
    check("Per 18/09: PO R belum terlambat (ETA 20/09 > cut-off)", pR["id"] not in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-09-01", "2026-09-18", "not_received")
    check("Per 18/09: PO R Belum Diterima", pR["id"] in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-10-01", "2026-10-03", "not_received")
    check("Per 03/10: PO R sudah diterima penuh -> tidak Belum Diterima (PO September tetap dievaluasi)", pR["id"] not in s and c == t_, (c, t_))
    c, t_, s, _ = card_drill("2026-10-01", "2026-10-31", "not_received", asof=False)
    check("Saat ini: PO R tidak Belum Diterima", pR["id"] not in s and c == t_, (c, t_))

    d = cc(date_from="2026-10-01", date_to="2026-10-31")
    lst = drill("po", date_from="2026-10-01", date_to="2026-10-31")
    check("Aktivitas: Total PO Oktober = PO bertanggal Oktober saja (fixture September tidak ikut) = list periode",
          proc(d, "po_total").get("count") == lst["total"] and not ({pA["id"], pR["id"], pX["id"]} & ids(lst["items"])), (proc(d, "po_total"), lst["total"]))
    d = cc(date_from="2026-09-01", date_to="2026-09-30")
    lst = drill("po", date_from="2026-09-01", date_to="2026-09-30")
    check("Aktivitas: Total PO September memuat fixture September = list periode",
          proc(d, "po_total").get("count") == lst["total"] and {pA["id"], pR["id"], pX["id"]} <= ids(lst["items"]), (proc(d, "po_total"), lst["total"]))
    check("Attention table per 30/09 memuat PO R (Belum Diterima / Terlambat)", any(r.get("id") == pR["id"] or r.get("doc_id") == pR["id"]
                                                                                    for r in (d.get("attention") or {}).get("rows", [])),
          [r.get("no") for r in (d.get("attention") or {}).get("rows", [])][:10])

    # ================= MRO Belum Diproses per cut-off
    sc, mro = call("POST", "mro", {"no": f"MRO-{uuid.uuid4().hex[:6]}", "date": "2026-09-05", "division_id": M["div"]["id"], "requester": "Budi",
                                   "submitted": True, "lines": [{"item_id": M["item"]["id"], "qty": 3, "warehouse_id": M["wh"]["id"],
                                                                 "project_id": M["pa"]["id"]}]}, 200)
    call("POST", f"mro/{mro['id']}/submit", {})
    sc, ro = call("POST", "ro", {"division_id": M["div"]["id"], "date": "2026-10-02", "submitted": True,
                                 "lines": [{"item_id": M["item"]["id"], "qty": 3, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"],
                                            "sources": [{"mro_id": mro["id"], "line_id": mro["lines"][0]["id"], "qty": 3}]}]}, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    d = cc(date_from="2026-09-01", date_to="2026-09-30")
    lst = drill("mro", rf_kind="open", date_to="2026-09-30", rf_asof="2026-09-30")
    check("Per 30/09: MRO 05/09 Belum Diproses (RO 02/10 setelah cut-off); kartu = drill", mro["id"] in ids(lst["items"])
          and proc(d, "mro_open").get("count") == lst["total"], (proc(d, "mro_open"), lst["total"]))
    lst = drill("ro", rf_kind="open", date_to="2026-09-30", rf_asof="2026-09-30")
    check("Per 30/09: RO 02/10 belum ada di posisi RO; kartu = drill", ro["id"] not in ids(lst["items"]) and proc(d, "ro_open").get("count") == lst["total"],
          (proc(d, "ro_open"), lst["total"]))
    d = cc(date_from="2026-10-01", date_to="2026-10-31")
    lst = drill("mro", rf_kind="open", date_to="2026-10-31")
    check("Saat ini: MRO sudah diproses -> tidak Belum Diproses; kartu = drill", mro["id"] not in ids(lst["items"])
          and proc(d, "mro_open").get("count") == lst["total"], (proc(d, "mro_open"), lst["total"]))
    lst = drill("ro", rf_kind="open", date_to="2026-10-31")
    check("Saat ini: RO 02/10 Belum Menjadi PO", ro["id"] in ids(lst["items"]) and proc(d, "ro_open").get("count") == lst["total"], (proc(d, "ro_open"), lst["total"]))


if __name__ == "__main__":
    main()
    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)
