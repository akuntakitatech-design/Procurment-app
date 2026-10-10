"""P4 Reporting SPK & Kontrak Harga Vendor pada Pusat Laporan (backend + DB test terisolasi *itest*, tenant QA).

Membuktikan: A Realisasi Anggaran SPK (nilai kontrak vs anggaran procurement: awal/addendum efektif/akhir; commitment ledger;
realisasi DO partial/berulang/batal; PO multi-SPK tanpa hitung ganda; RELEASE; status & kondisi; paritas KPI/drill Dashboard;
detail PO/DO = rekap), B Daftar Kontrak (status cut-off Aktif ⊃ Akan Berakhir / Expired / Belum Berlaku / Draft / Cancelled =
Dashboard; resolver cut-off), C Kepatuhan Harga (harga kontrak pada TANGGAL PO dengan rekonstruksi riwayat harga: beberapa
perubahan, perubahan di tanggal sama, PO sebelum/sesudah tanggal efektif, histori legacy tidak lengkap/tidak konsisten ->
"Riwayat Harga Tidak Lengkap"; perbandingan sebelum (resolver existing) / sesudah; paritas Dashboard), redaksi server-side
(spk:view / vendor_contract:view / view_purchase_price) pada JSON, total, Excel, PDF; paritas JSON = Excel = PDF; read-only.
"""
import io
import os
import sys
import uuid

from openpyxl import load_workbook
from pypdf import PdfReader

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/backend")
import receipt_control_test as T
from opening_correction_test import conn, ins
from po_price_insight_test import manual_po, pl

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:5]
PRICE_C = {"po_price", "contract_price", "tolerance_pct", "allowed_max", "diff_unit", "diff", "diff_pct", "contract_changes"}


def near(a, b, eps=0.01):
    return abs(float(a or 0) - float(b or 0)) <= eps


def rc(fn, key, qs=""):
    return fn("GET", f"report-center/{key}?page_size=500&{qs}")


def rows(res):
    return (res or {}).get("rows", [])


def xl(sess, key, qs, first):
    r = sess.get(f"{API}/report-center/{key}/export.xlsx?{qs}")
    if not r.ok:
        return r.status_code, [], [], []
    vals = [list(v) for v in load_workbook(io.BytesIO(r.content), read_only=True).worksheets[0].iter_rows(values_only=True)]
    hi = next((i for i, v in enumerate(vals) if v and v[0] == first), None)
    if hi is None:
        return r.status_code, [], [], []
    body = [v for v in vals[hi + 1:] if v and v[0] not in (None, "TOTAL")]
    return r.status_code, [str(x) for x in vals[hi]], body, next((v for v in vals[hi + 1:] if v and v[0] == "TOTAL"), [])


def pdf(sess, key, qs):
    r = sess.get(f"{API}/report-center/{key}/export.pdf?{qs}")
    return r.status_code, (" ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages).split()) if r.ok else "")


def at(day, hh="03"):
    return f"{day}T{hh}:00:00+00:00"


def main():
    if not os.environ.get("DATABASE_URL") or "itest" not in os.environ.get("DATABASE_URL", ""):
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    M = T.setup()
    T.M = M
    call("PUT", "settings/approval_modules", {"modules": {k: {"enabled": False, "levels": []} for k in ("mro", "ro", "po")}}, 200)
    tenant = call("GET", "auth/me")[1].get("tenant_id")
    div, pa = M["div"]["id"], M["pa"]["id"]
    from po_ro_split_test import mk_item
    IS = mk_item(M, f"IS{u}", "Besi SPK")

    # ------------------------------------------------------------------ A. fixture SPK (ditanam, engine SPK hanya dibaca)
    A, Mx, C, E, G = (f"spk-{k}-{u}" for k in ("A", "M", "C", "E", "G"))
    cn = conn()
    try:
        def spk(i, no, status, budget, value):
            ins(cn, "spk", {"id": i, "tenant_id": tenant, "spk_number": no, "project_id": pa, "project_name": "Proyek A",
                            "division_id": div, "status": status, "start_date": "2025-01-01", "end_date": "2026-12-31",
                            "spk_value": value, "procurement_budget": budget})
        spk(A, f"SPK-A-{u}", "active", 1_200_000, 3_500_000)   # header kini SUDAH termasuk addendum efektif 05/10
        spk(Mx, f"SPK-M-{u}", "active", 500_000, 800_000)
        spk(C, f"SPK-C-{u}", "draft", 300_000, 300_000)
        spk(E, f"SPK-E-{u}", "cancelled", 900_000, 900_000)
        spk(G, f"SPK-G-{u}", "active", 400_000, 400_000)
        for st, bc, vc, eff in (("effective", 200_000, 500_000, "2025-10-05"), ("draft", 999, 999, "2025-06-01")):
            ins(cn, "spk_addendums", {"id": f"ad-{st}-{u}", "tenant_id": tenant, "spk_id": A, "status": st, "budget_change": bc,
                                      "spk_value_change": vc, "effective_date": eff, "addendum_type": "BOTH"})
        po1, pl1, pog, plg = f"po1-{u}", f"pl1-{u}", f"pog-{u}", f"plg-{u}"
        for pid, no in ((po1, f"PO-SPK1-{u}"), (pog, f"PO-SPKG-{u}")):
            ins(cn, "po", {"id": pid, "tenant_id": tenant, "no": no, "date": "2025-09-15", "status": "Approved",
                           "supplier_name": "Supplier SPK", "division_id": div})
        ins(cn, "po_lines", {"id": pl1, "tenant_id": tenant, "po_id": po1, "qty": 10, "item_id": IS["id"], "unit": "PCS"})
        ins(cn, "po_lines", {"id": plg, "tenant_id": tenant, "po_id": pog, "qty": 3, "item_id": IS["id"], "unit": "PCS"})
        for sid, line, q in ((A, pl1, 6), (Mx, pl1, 4), (G, plg, 3)):   # PO multi-SPK: 1 baris PO dibagi A=6, M=4
            ins(cn, "procurement_item_spk_allocations", {"id": f"al-{sid}-{line}", "tenant_id": tenant, "source_type": "po",
                                                         "item_line_id": line, "spk_id": sid, "allocated_qty": q})
        led = (("COMMIT", A, po1, pl1, 600_000, 6, "2025-09-20"), ("COMMIT", Mx, po1, pl1, 400_000, 4, "2025-09-20"),
               ("COMMIT", G, pog, plg, 300_000, 3, "2025-09-05"), ("RELEASE", G, pog, plg, 300_000, None, "2025-10-02"))
        for i, (ev, sid, pid, line, amt, q, day) in enumerate(led):
            row = {"id": f"led-{i}-{u}", "tenant_id": tenant, "event": ev, "spk_id": sid, "po_id": pid, "po_no": "x",
                   "po_line_id": line, "item_id": IS["id"], "amount": amt, "created_at": at(day)}
            if q is not None:
                row["qty"] = q
            ins(cn, "spk_commitment_ledger", row)
        dos = (("DO1", "2025-09-25", 5, {A: 3, Mx: 2}, False), ("DO2", "2025-09-26", 5, {A: 5}, True),   # DO2 batal
               ("DO3", "2025-10-15", 3, None, False), ("DO4", "2025-11-05", 4, {A: 4}, False))            # DO3 proporsional
        for no, day, q, alloc, cancelled in dos:
            did = f"{no}-{u}"
            ins(cn, "do", {"id": did, "tenant_id": tenant, "no": did, "date": day, "status": "Cancelled" if cancelled else "Received",
                           **({"cancelled": True} if cancelled else {})})
            ins(cn, "do_lines", {"id": f"{did}-l", "tenant_id": tenant, "do_id": did, "po_line_id": pl1, "qty": q, "item_id": IS["id"]})
            for sid, aq in (alloc or {}).items():
                ins(cn, "procurement_item_spk_allocations", {"id": f"al-{did}-{sid}", "tenant_id": tenant, "source_type": "do",
                                                             "item_line_id": f"{did}-l", "spk_id": sid, "allocated_qty": aq})
    finally:
        cn.close()

    def a1(dt, qs=""):
        sc, d = rc(call, "spk-budget", f"date_to={dt}&{qs}")
        assert sc == 200, (sc, str(d)[:300])
        return {r["no"]: r for r in rows(d)}, d

    r1, _ = a1("2025-09-30")
    ra = r1.get(f"SPK-A-{u}", {})
    check("A1 30/09: default Active+Closed (Draft C & Cancelled E tidak tampil)", f"SPK-C-{u}" not in r1 and f"SPK-E-{u}" not in r1
          and {f"SPK-A-{u}", f"SPK-M-{u}", f"SPK-G-{u}"} <= set(r1), sorted(r1))
    check("A1 30/09: Anggaran awal 1 jt, addendum (05/10) belum -> akhir 1 jt; Nilai Kontrak awal 3 jt = akhir (terpisah)",
          (ra.get("budget_initial"), ra.get("budget_add"), ra.get("budget_final"), ra.get("spk_value_initial"), ra.get("spk_value_add"),
           ra.get("spk_value_final")) == (1_000_000, 0, 1_000_000, 3_000_000, 0, 3_000_000), ra)
    check("A1 30/09: A commitment 600 rb (porsi 6/10 PO multi-SPK), realisasi DO1 3 unit = 300 rb, open 300 rb, sisa = B − C = 400 rb, 60%",
          (ra.get("commitment"), ra.get("realization"), ra.get("open_commitment"), ra.get("remaining"), ra.get("usage_pct"))
          == (600_000, 300_000, 300_000, 400_000, 60.0), ra)
    r2, d2 = a1("2025-10-31")
    ra2, rm2, rg2 = r2.get(f"SPK-A-{u}", {}), r2.get(f"SPK-M-{u}", {}), r2.get(f"SPK-G-{u}", {})
    check("A1 31/10: addendum efektif masuk sekali -> anggaran 1 jt + 200 rb = 1,2 jt; nilai kontrak 3 jt + 500 rb (draft addendum diabaikan)",
          (ra2.get("budget_initial"), ra2.get("budget_add"), ra2.get("budget_final"), ra2.get("spk_value_final"), ra2.get("addendum_count"))
          == (1_000_000, 200_000, 1_200_000, 3_500_000, 1), ra2)
    check("A1 31/10: DO3 tanpa alokasi -> proporsional (A 1,8 / M 1,2); DO2 batal diabaikan; realisasi A 480 rb, M 320 rb",
          ra2.get("realization") == 480_000 and rm2.get("realization") == 320_000 and ra2.get("remaining") == 600_000, (ra2, rm2))
    check("A1 31/10: PO multi-SPK tidak dihitung ganda: commitment A + M = 1 jt (nilai baris PO)",
          ra2.get("commitment") + rm2.get("commitment") == 1_000_000, (ra2.get("commitment"), rm2.get("commitment")))
    check("A1 31/10: RELEASE (cancel) -> G commitment 0, sisa = anggaran 400 rb", rg2.get("commitment") == 0 and rg2.get("remaining") == 400_000, rg2)
    r3, _ = a1("2025-11-30")
    check("A1 30/11: DO berulang kumulatif A 8,8 > commit 6 -> realisasi dibatasi 600 rb, open 0",
          r3[f"SPK-A-{u}"]["realization"] == 600_000 and r3[f"SPK-A-{u}"]["open_commitment"] == 0, r3[f"SPK-A-{u}"])
    ra_all, _ = a1("2025-10-31", "status=all")
    rcan, _ = a1("2025-10-31", "status=cancelled")
    check("A1 filter status: Semua -> Draft & Cancelled tampil; Cancelled -> hanya E", f"SPK-C-{u}" in ra_all and f"SPK-E-{u}" in ra_all
          and set(rcan) == {f"SPK-E-{u}"} and ra_all[f"SPK-E-{u}"]["status"] == "Cancelled", (sorted(ra_all), sorted(rcan)))
    # paritas Dashboard (fungsi & predikat sama)
    _, dsh = call("GET", "dashboard/control-center?date_from=2025-01-01&date_to=2025-10-31")
    kpi = (dsh.get("spk") or {}).get("kpi", {})
    ract, dact = a1("2025-10-31", "kondisi=active")
    check("Paritas Dashboard: kondisi Aktif -> jumlah SPK & Σ Budget/Commitment/Realisasi/Open/Sisa = KPI SPK Dashboard",
          len(ract) == kpi.get("active") and all(near(dact["totals"][k2], kpi.get(k1)) for k1, k2 in (
              ("budget", "budget_final"), ("commitment", "commitment"), ("realization", "realization"),
              ("open_commitment", "open_commitment"), ("remaining", "remaining"))), (len(ract), dact.get("totals"), kpi))
    for kind, kk in (("over", "over_budget"), ("critical", "critical"), ("attention", "attention"), ("expiring", "expiring")):
        _, dd = call("GET", f"dashboard/drill/spk?date_to=2025-10-31&kind={kind}")
        rk, _ = a1("2025-10-31", f"kondisi={kind}")
        check(f"Paritas drill Dashboard '{kind}': daftar SPK identik", sorted(rk) == sorted(x["spk_number"] for x in dd.get("rows", [])) and len(rk) == kpi.get(kk),
              (sorted(rk), dd.get("count"), kpi.get(kk)))
    # detail PO & DO = rekap
    _, dpo = rc(call, "spk-budget-po", "date_to=2025-10-31")
    po_by = {(r["spk_no"], r["no"]): r for r in rows(dpo)}
    pa_, pm_ = po_by.get((f"SPK-A-{u}", f"PO-SPK1-{u}"), {}), po_by.get((f"SPK-M-{u}", f"PO-SPK1-{u}"), {})
    check("A2 detail PO: baris PO multi-SPK = 2 baris porsi (A 6 / 600 rb, M 4 / 400 rb), drill ke /po/:id",
          (pa_.get("qty_commit"), pa_.get("commitment"), pm_.get("qty_commit"), pm_.get("commitment")) == (6, 600_000, 4, 400_000)
          and (pa_.get("_drill") or {}).get("to") == f"/po/{po1}" and f"DO1-{u}" in pa_.get("do_refs", "") and f"DO2-{u}" not in pa_.get("do_refs", ""), (pa_, pm_))
    pg_ = po_by.get((f"SPK-G-{u}", f"PO-SPKG-{u}"), {})
    check("A2 detail PO: commitment yang di-RELEASE tampil 0, status 'Dirilis'", pg_.get("commitment") == 0 and "Dirilis" in pg_.get("commit_state", ""), pg_)
    for sno in (f"SPK-A-{u}", f"SPK-M-{u}", f"SPK-G-{u}"):
        sc_ = sum(r["commitment"] for r in rows(dpo) if r["spk_no"] == sno)
        sr_ = sum(r["realization"] for r in rows(dpo) if r["spk_no"] == sno)
        check(f"A2 Σ commitment & realisasi per SPK = rekap A1 ({sno[-7:]})", near(sc_, r2[sno]["commitment"]) and near(sr_, r2[sno]["realization"]), (sc_, sr_, r2[sno]))
    _, ddo = rc(call, "spk-budget-do", "date_to=2025-11-30")
    da = [r for r in rows(ddo) if r["spk_no"] == f"SPK-A-{u}"]
    check("A3 detail DO (30/11): A = DO1 3, DO3 1,8 (proporsional), DO4 4 -> dihitung 1,2 (sisa cap); DO batal tidak ada; drill /do/:id",
          [(r["no"], round(r["qty_do"], 4), round(r["qty_counted"], 4)) for r in da] == [(f"DO1-{u}", 3, 3), (f"DO3-{u}", 1.8, 1.8), (f"DO4-{u}", 4, 1.2)]
          and da[1]["basis"].startswith("Proporsional") and (da[0].get("_drill") or {}).get("to") == f"/do/DO1-{u}", da)
    check("A3 Σ realisasi DO per SPK = rekap A1 (A 600 rb, M 320 rb)", near(sum(r["realization"] for r in da), 600_000)
          and near(sum(r["realization"] for r in rows(ddo) if r["spk_no"] == f"SPK-M-{u}"), 320_000))
    # Halaman detail SPK (/spk/:id) memakai laporan yang SAMA via filter tersembunyi spk_id (bukan placeholder budget_summary)
    _, dA = rc(call, "spk-budget", f"date_to=2025-10-31&status=all&spk_id={A}")
    _, dAp = rc(call, "spk-budget-po", f"date_to=2025-10-31&status=all&spk_id={A}")
    fA = next((f for f in dA.get("filters", []) if f["key"] == "spk_id"), {})
    keys_ = ("commitment", "realization", "open_commitment", "remaining", "usage_pct", "budget_final")
    check("A4 filter spk_id: 1 baris = baris SPK-A rekap (commitment/realisasi/open/sisa/%), detail PO hanya SPK-A, filter hidden, label No. SPK",
          [r["no"] for r in rows(dA)] == [f"SPK-A-{u}"] and all(rows(dA)[0][k] == r2[f"SPK-A-{u}"][k] for k in keys_)
          and {r["spk_no"] for r in rows(dAp)} == {f"SPK-A-{u}"} and len(rows(dAp)) == sum(1 for r in rows(dpo) if r["spk_no"] == f"SPK-A-{u}")
          and fA.get("hidden") is True and any(f["key"] == "spk_id" and f["value"] == f"SPK-A-{u}" for f in dA.get("filters_applied", [])),
          (rows(dA), fA, dA.get("filters_applied")))
    # Tanggal Indonesia: PDF & label periode DD-MM-YYYY; JSON & sel Excel tetap nilai ISO yang sama (kontrak paritas Excel = JSON)
    qd = f"date_to=2025-10-31&status=all&spk_id={A}"
    xr = T.S.get(f"{API}/report-center/spk-budget/export.xlsx?{qd}")
    ws_ = load_workbook(io.BytesIO(xr.content)).worksheets[0]
    hrow = next(r for r in ws_.iter_rows() if r[0].value == "No. SPK")
    ci = [c.value for c in hrow].index("Mulai")
    dcell = ws_.cell(row=hrow[0].row + 1, column=ci + 1)
    _, ptd = pdf(T.S, "spk-budget", qd)
    check("Tanggal Indonesia: PDF '01-01-2025' & periode 's/d 31-10-2025'; JSON ISO = sel Excel (paritas)",
          xr.ok and dcell.value == rows(dA)[0]["start_date"] == "2025-01-01"
          and "01-01-2025" in ptd and "2025-01-01" not in ptd and "s/d 31-10-2025" in ptd and rows(dA)[0]["start_date"] == "2025-01-01"
          and any(f["key"] == "period" and f["value"] == "awal s/d 31-10-2025" for f in dA.get("filters_applied", [])),
          (dcell.value, dcell.number_format, ptd[:300]))


    # ------------------------------------------------------------------ B. Kontrak + C. riwayat harga
    supX, U_ = M["supX"], M["uom"]
    IH, IL, IB = mk_item(M, f"IH{u}", "Kabel Riwayat"), mk_item(M, f"IL{u}", "Pipa Legacy"), mk_item(M, f"IB{u}", "Baut")

    def vc(no, item, price, start, end, tol=5, activate=True):
        _, c = call("POST", "vendor-contracts", {"supplier_id": supX["id"], "contract_number": no, "start_date": start, "end_date": end,
                                                 "default_tolerance_pct": tol}, 200)
        _, it = call("POST", f"vendor-contracts/{c['id']}/items", {"item_id": item["id"], "uom_id": U_["id"], "base_price": price}, 200)
        if activate:
            call("POST", f"vendor-contracts/{c['id']}/activate", {}, 200)
        return c, it
    KH, ih = vc(f"KH-{u}", IH, 10_000, "2026-01-01", "2026-12-31")
    KL, il = vc(f"KL-{u}", IL, 18_000, "2026-01-01", "2026-12-31")
    KS, _ = vc(f"KS-{u}", IB, 1_000, "2026-01-01", "2026-07-20")      # akan berakhir per 30/06
    KX, _ = vc(f"KX-{u}", IB, 1_100, "2025-01-01", "2025-12-31")      # expired
    KF, _ = vc(f"KF-{u}", IB, 1_200, "2027-01-01", "2027-12-31")      # belum berlaku
    KD, _ = vc(f"KD-{u}", IB, 900, "2026-01-01", "2026-12-31", activate=False)
    KC, _ = vc(f"KC-{u}", IB, 950, "2026-08-01", "2026-12-31")
    call("POST", f"vendor-contracts/{KC['id']}/cancel", {"reason": "uji"})
    for eff, price in (("2026-04-01", 12_000), ("2026-04-01", 12_500), ("2026-06-01", 13_000)):   # 2 perubahan di tanggal sama
        call("POST", f"vendor-contracts/{KH['id']}/items/{ih['id']}/price-change", {"base_price": price, "effective_date": eff, "reason": "uji"}, 200)
    call("POST", f"vendor-contracts/{KL['id']}/items/{il['id']}/price-change", {"base_price": 20_000, "effective_date": "2026-05-01", "reason": "uji"}, 200)
    cn = conn()
    try:  # histori legacy: perubahan lama 15.000 -> 16.000 (03/01) tidak nyambung ke harga 18.000 -> rantai tidak lengkap
        ins(cn, "vendor_contract_price_history", {"id": f"lg-{u}", "tenant_id": tenant, "contract_id": KL["id"], "item_row_id": il["id"],
                                                  "item_id": IL["id"], "previous_base_price": 15_000, "new_base_price": 16_000,
                                                  "previous_net_price": 15_000, "new_net_price": 16_000, "effective_date": "2026-03-01",
                                                  "at": "2026-01-15T00:00:00+00:00", "reason": "legacy"})
    finally:
        cn.close()
    _, hist0 = call("GET", f"vendor-contracts/{KH['id']}/price-history")

    # B
    _, b = rc(call, "vendor-contract-list", "date_to=2026-06-30")
    bst = {r["no"]: r["status"] for r in rows(b)}
    check("B status cut-off 30/06: Aktif / Aktif·Akan Berakhir / Expired / Belum Berlaku / Draft / Cancelled",
          [bst.get(f"{k}-{u}") for k in ("KH", "KS", "KX", "KF", "KD", "KC")] ==
          ["Aktif", "Aktif · Akan Berakhir", "Expired", "Belum Berlaku", "Draft", "Cancelled"], bst)
    _, dshc = call("GET", "dashboard/control-center?date_from=2026-06-01&date_to=2026-06-30")
    ck = (dshc.get("vendor_contract") or {}).get("contracts", {})
    nums = lambda qs: {r["no"] for r in rows(rc(call, "vendor-contract-list", f"date_to=2026-06-30&{qs}")[1])}  # noqa: E731
    check("Paritas Dashboard kontrak: Aktif (termasuk Akan Berakhir, tidak ganda) / Akan Berakhir / Expired = KPI",
          (len(nums("status=active")), len(nums("status=expiring")), len(nums("status=expired"))) == (ck.get("active"), ck.get("expiring"), ck.get("expired"))
          and nums("status=expiring") <= nums("status=active"), (nums("status=active"), ck))
    bh = next(r for r in rows(b) if r["no"] == f"KH-{u}")
    check("B baris KH: harga kontrak kini 13.000, tolerance 5%, 3 perubahan + riwayat (tgl efektif: lama → baru), drill /vendor-contracts/:id",
          bh.get("net_price") == 13_000 and bh.get("tolerance_pct") == 5 and bh.get("price_changes") == 3
          and "01-06-2026: 12.500 → 13.000" in bh.get("changes_text", "") and (bh.get("_drill") or {}).get("to") == f"/vendor-contracts/{KH['id']}", bh)
    check("B resolver cut-off 30/06: KH baris ini 13.000; cut-off 15/05 -> versi riwayat 12.500; 15/03 -> Riwayat Harga Tidak Lengkap",
          (bh.get("resolver"), bh.get("price_at_cut")) == ("Baris ini", 13_000)
          and next(r for r in rows(rc(call, "vendor-contract-list", "date_to=2026-05-15")[1]) if r["no"] == f"KH-{u}")["price_at_cut"] == 12_500
          and next(r for r in rows(rc(call, "vendor-contract-list", "date_to=2026-03-15")[1]) if r["no"] == f"KH-{u}")["resolver"] == "Riwayat Harga Tidak Lengkap")

    # C
    def po(item, price, day):
        return manual_po(M, supX, item, 1, price, day, lines=[pl(M, item, 1, price)])
    H1, H2, H3, H4 = po(IH, 10_000, "2026-03-15"), po(IH, 12_400, "2026-04-10"), po(IH, 13_200, "2026-05-20"), po(IH, 13_000, "2026-06-10")
    L1, L2 = po(IL, 16_000, "2026-03-20"), po(IL, 20_000, "2026-05-10")
    W = manual_po(M, supX, IH, 1, 50_000, "2026-04-12", lines=[pl(M, IH, 1, 50_000)], approve=False)   # Waiting/Draft -> tidak dinilai
    qs = "date_from=2026-03-01&date_to=2026-06-30"
    _, c = rc(call, "price-compliance", qs)
    st = {r["no"]: r for r in rows(c)}
    pos_no = {x["id"]: x.get("no") for x in (H1, H2, H3, H4, L1, L2, W)}
    exp = {H1["id"]: "Riwayat Harga Tidak Lengkap", H2["id"]: "Sesuai", H3["id"]: "Melebihi Tolerance", H4["id"]: "Sesuai",
           L1["id"]: "Riwayat Harga Tidak Lengkap", L2["id"]: "Sesuai"}
    got = {k: (st.get(pos_no[k]) or {}).get("status") for k in exp}
    check("C status: H1 sebelum perubahan pertama (tgl awal versi tidak tercatat) & L1 (rantai legacy tidak nyambung) -> Riwayat Harga "
          "Tidak Lengkap; H2 12.400 vs 12.500 (perubahan kedua tgl sama menang) Sesuai; H3 13.200 > 13.125 Melebihi; H4/L2 Sesuai", got == exp, got)
    h2, h3, h4 = st[pos_no[H2["id"]]], st[pos_no[H3["id"]]], st[pos_no[H4["id"]]]
    check("C harga pembanding = harga pada TANGGAL PO: H2 12.500 (riwayat, berlaku mulai 01-04-2026), H3 12.500 selisih 700 (5,6%), H4 13.000 (saat ini)",
          (h2["contract_price"], h3["contract_price"], h4["contract_price"]) == (12_500, 12_500, 13_000) and h2["price_version"] == "Riwayat — berlaku mulai 01-04-2026"
          and h4["price_version"] == "Saat ini" and near(h3["diff"], 700) and near(h3["diff_pct"], 5.6), (h2, h3, h4))
    check("C info PO existing: Status PO (Approved) terpisah dari status kepatuhan; alasan perubahan harga & riwayat harga kontrak tampil",
          h3["po_status"] == "Approved" and h3["price_change_reason"] == "uji harga" and "01-04-2026: 10.000 → 12.000" in h3["contract_changes"]
          and pos_no[W["id"]] not in st, h3)
    # sebelum / sesudah (resolver existing = dasar Dashboard pra-P4)
    before, item_of = {}, {x["id"]: it for it, xs in ((IH, (H1, H2, H3, H4)), (IL, (L1, L2))) for x in xs}
    for pid in exp:
        r_ = st[pos_no[pid]]
        _, rr = call("GET", f"vendor-contracts/resolve-price?vendor_id={supX['id']}&item_id={item_of[pid]['id']}&uom_id={U_['id']}&date={r_['po_date']}&qty=1")
        before[pos_no[pid]] = "Tanpa Kontrak" if not rr.get("found") else ("Sesuai" if r_["po_price"] <= rr["net_contract_price"] * (1 + rr.get("tolerance_pct", 0) / 100) + 1e-6 else "Melebihi Tolerance")
    print("  SEBELUM -> SESUDAH (per baris PO):", {k: f"{before[k]} -> {st[k]['status']}" for k in before})
    check("Sebelum P4 (resolver kini saja): H1/H2/H3/L1 = Tanpa Kontrak; sesudah: koreksi klasifikasi historis (H4/L2 tetap Sesuai)",
          [before[pos_no[x["id"]]] for x in (H1, H2, H3, L1, H4, L2)] == ["Tanpa Kontrak"] * 4 + ["Sesuai"] * 2, before)
    # paritas Dashboard
    _, dc2 = call("GET", f"dashboard/control-center?{qs}")
    kp = ((dc2.get("vendor_contract") or {}).get("price_control") or {}).get("kpi", {})
    lab = [r["status"] for r in rows(c)]
    check("Paritas Dashboard Price Control: jumlah baris per status & Nilai Selisih = Laporan C",
          (kp.get("lines"), kp.get("lines_over"), kp.get("lines_no_contract"), kp.get("lines_history_incomplete"), kp.get("po_history_incomplete"))
          == (len(lab), lab.count("Melebihi Tolerance"), lab.count("Tanpa Kontrak"), lab.count("Riwayat Harga Tidak Lengkap"), 2)
          and near(kp.get("diff_value"), sum(r["diff"] or 0 for r in rows(c) if r["status"] == "Melebihi Tolerance")), (kp, lab))
    _, dh = call("GET", f"dashboard/drill/price-control?{qs}&status=history_incomplete")
    _, cx = rc(call, "price-compliance", f"{qs}&status=history_incomplete")
    check("Paritas drill 'Riwayat Harga Tidak Lengkap' = filter Laporan C; label Dashboard 'Melebihi Tolerance'",
          sorted(r["po_no"] for r in dh.get("rows", [])) == sorted(r["no"] for r in rows(cx)) == sorted([pos_no[H1["id"]], pos_no[L1["id"]]])
          and any(e.get("status_label") == "Melebihi Tolerance" for e in ((dc2.get("vendor_contract") or {}).get("price_control") or {}).get("exceptions", [])))
    _, cex = rc(call, "price-compliance", f"{qs}&status=exceptions")
    check("C filter Pengecualian = semua selain Sesuai", {r["status"] for r in rows(cex)} == {"Melebihi Tolerance", "Riwayat Harga Tidak Lengkap"}
          and len(rows(cex)) == 3)
    # paritas JSON = Excel = PDF (admin)
    for key, q, first in (("price-compliance", qs, "No. PO"), ("spk-budget", "date_to=2025-10-31", "No. SPK"), ("vendor-contract-list", "date_to=2026-06-30", "No. Kontrak")):
        _, j = rc(call, key, q)
        sc, hdr, body, tot = xl(T.S, key, q, first)
        sp, pt = pdf(T.S, key, q)
        tcols = [cc for cc in j["columns"] if cc["total"]]
        ok_tot = all(near(tot[hdr.index(cc["label"])], j["totals"][cc["key"]]) for cc in tcols) if tot else not tcols
        check(f"Paritas {key}: JSON = Excel (baris, urutan, TOTAL) = PDF", sc == 200 and sp == 200 and len(body) == j["total_rows"]
              and [str(v[0]) for v in body] == [str(r["no"]) for r in rows(j)] and ok_tot and all(str(r["no"]) in pt for r in rows(j)), (len(body), j["total_rows"]))

    # ------------------------------------------------------------------ redaksi (matrix izin)
    import po_approval2_batch_test as AP
    AP.M = M
    made = []

    def mk(name, ov):
        x = AP.mk_user(name, [div])
        AP.set_ov(x, {"export": "allow", **ov})
        made.append(x)
        return x
    u0 = mk("p4ns", {"spk.view": "deny", "vendor_contracts.view": "deny", "view_purchase_price": "allow"})
    check("Tanpa spk:view: laporan SPK 403 (JSON & export); tanpa vendor_contract:view: Daftar Kontrak 403",
          rc(u0, "spk-budget", "date_to=2025-10-31")[0] == 403 and u0.S.get(f"{API}/report-center/spk-budget/export.xlsx").status_code == 403
          and rc(u0, "vendor-contract-list")[0] == 403)
    call("DELETE", f"users/{u0.uid}", None, 200)
    made.remove(u0)
    u1 = mk("p4np", {"spk.view": "allow", "vendor_contracts.view": "allow", "view_purchase_price": "deny"})
    _, j1 = rc(u1, "spk-budget-po", "date_to=2025-10-31")
    check("spk:view tanpa harga: nominal SPK tampil (paritas Dashboard), Harga Satuan Commit dibuang", "unit_price" not in {cc["key"] for cc in j1["columns"]}
          and any(r.get("commitment") == 600_000 for r in rows(j1)) and not any("unit_price" in r for r in rows(j1)))
    _, j2 = rc(u1, "vendor-contract-list", "date_to=2026-06-30")
    _, hb, _, _ = xl(u1.S, "vendor-contract-list", "date_to=2026-06-30", "No. Kontrak")
    _, pb_ = pdf(u1.S, "vendor-contract-list", "date_to=2026-06-30")
    check("Kontrak tanpa view_purchase_price: harga/diskon/riwayat harga dibuang dari JSON, Excel, PDF",
          not ({cc["key"] for cc in j2["columns"]} & {"base_price", "net_price", "discount", "changes_text", "price_at_cut"})
          and not any(k in r for r in rows(j2) for k in ("net_price", "price_at_cut")) and hb and "Harga Kontrak (Net)" not in hb
          and "13.000" not in pb_ and "Harga Kontrak" not in pb_, hb)
    call("DELETE", f"users/{u1.uid}", None, 200)
    made.remove(u1)
    for name, ov, vis in (("p4c1", {"vendor_contracts.view": "deny", "view_purchase_price": "allow"}, False),
                          ("p4c2", {"vendor_contracts.view": "allow", "view_purchase_price": "deny"}, False),
                          ("p4c3", {"vendor_contracts.view": "allow", "view_purchase_price": "allow"}, True)):
        us = mk(name, ov)
        sc, jj = rc(us, "price-compliance", qs)
        keys_ = {cc["key"] for cc in jj.get("columns", [])} | {k for r in rows(jj) for k in r} | set(jj.get("totals") or {})
        _, hx, _, tx = xl(us.S, "price-compliance", qs, "No. PO")
        _, px = pdf(us.S, "price-compliance", qs)
        leak = keys_ & PRICE_C
        if vis:
            check(f"C {name}: vendor_contract:view + harga -> kolom harga & total selisih tampil", sc == 200 and {"po_price", "diff"} <= keys_
                  and "Harga PO Net / Unit" in hx and "Harga Kontrak / Unit" in px and jj.get("price_visible") is True)
        else:
            check(f"C {name}: {ov} -> harga/selisih/riwayat harga dibuang (JSON, total, Excel, PDF) + catatan disembunyikan; status tetap",
                  sc == 200 and not leak and "Harga PO Net / Unit" not in hx and "Selisih Total" not in hx and "Harga Kontrak / Unit" not in px
                  and "Selisih Total" not in px and "12.500" not in px and len(rows(jj)) == len(rows(c)) and jj.get("price_visible") is False
                  and "disembunyikan" in px,
                  (sc, sorted(leak), hx, "Harga Kontrak" in px, "12.500" in px, len(rows(jj)), len(rows(c)), px[:600]))
        call("DELETE", f"users/{us.uid}", None, 200)  # batas seat paket tenant uji
        made.remove(us)
    # read-only
    _, hist1 = call("GET", f"vendor-contracts/{KH['id']}/price-history")
    _, kh1 = call("GET", f"vendor-contracts/{KH['id']}")
    check("Read-only: histori harga & item kontrak tidak berubah oleh laporan/Dashboard", len(hist1) == len(hist0) == 3
          and (kh1.get("items") or [{}])[0].get("net_price") == 13_000 and (kh1.get("items") or [{}])[0].get("effective_start") == "2026-06-01",
          (len(hist1), (kh1.get("items") or [{}])[0].get("effective_start")))
    _, cat = call("GET", "report-center/catalog")
    g = next(x for x in cat["groups"] if x["key"] == "spk")
    check("Katalog: 5 kategori tetap; card SPK = 5 laporan P4, tautan hanya Monitoring SPK (/spk), tanpa placeholder",
          len(cat["groups"]) == 5 and [r["key"] for r in g["reports"]] == ["spk-budget", "spk-budget-po", "spk-budget-do", "vendor-contract-list", "price-compliance"]
          and [lk["to"] for lk in g["links"]] == ["/spk"] and not g["planned"], g)
    for x in made:
        call("DELETE", f"users/{x.uid}", None, 200)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — error fixture/assert tidak boleh tersamarkan sebagai PASS
        import traceback
        traceback.print_exc()
        T.RESULTS.append((f"EXCEPTION {e!r}", False))
    finally:
        failed = [r for r in T.RESULTS if not r[1]]
        print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
        sys.exit(1 if failed else 0)
