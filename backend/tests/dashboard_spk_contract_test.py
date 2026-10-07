"""Dashboard — SPK & Budget Control + Kontrak Harga Vendor / Price Control (throwaway tenant, localhost, dev DB).

SPK: dokumen SPK/addendum/ledger/alokasi/DO ditanam langsung di tenant uji (engine SPK tidak dipanggil, hanya dibaca
dashboard). Kontrak & PO dibuat lewat API existing (resolver & engine PO existing dipakai apa adanya).
Mencakup: cut-off historis, COMMIT/RELEASE/ADJUST, partial & multiple DO, Open Commitment, Sisa Budget = Budget -
Commitment, scope divisi/project/tenant, PO Approved final saja, Effective Price Resolver existing (parity endpoint
resolve-price), harga efektif sebelum pajak (diskon item, diskon final prorata, PPN), qty tier, redaksi nominal
rekursif (matrix izin), drill-down parity.
"""
import os
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/backend")
import receipt_control_test as T
from opening_correction_test import conn, ins
from po_price_insight_test import contract, manual_po, pl

call, check = T.call, T.check
CC = "dashboard/control-center"
SPK_VALUE_KEYS = {"budget", "commitment", "realization", "open_commitment", "remaining", "spk_value", "procurement_budget",
                  "over_budget_amount", "totals"}
PRICE_KEYS = {"contract_price", "net_contract_price", "base_price", "po_price", "allowed_max", "tolerance_pct", "diff",
              "diff_pct", "diff_unit", "diff_value"}


def at(day, hh="03"):
    return f"{day}T{hh}:00:00+00:00"


def dash(df, dt, extra="", fn=None):
    sc, d = (fn or call)("GET", f"{CC}?date_from={df}&date_to={dt}{extra}")
    assert sc == 200, (sc, str(d)[:300])
    return d


def keys(obj):
    """Semua key pada seluruh tree JSON (rekursif: object & list anak)."""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= keys(v)
    return out


def main():
    if not os.environ.get("DATABASE_URL"):
        print("SKIP: DATABASE_URL tidak tersedia")
        return
    M = T.setup()
    T.M = M
    call("PUT", "settings/approval_modules", {"modules": {k: {"enabled": False, "levels": []} for k in ("mro", "ro", "po")}}, 200)
    tenant = call("GET", "auth/me")[1].get("tenant_id")
    u = uuid.uuid4().hex[:5]
    div, pa, pb = M["div"]["id"], M["pa"]["id"], M["pb"]["id"]
    _, dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)

    # ------------------------------------------------------------------ fixture SPK (tanggal lampau: 2025)
    A, B, Cd, D, E, F, G, H, I = (f"spk-{k}-{u}" for k in "ABCDEFGHI")
    cn = conn()
    try:
        def spk(i, no, status, start, end, budget, division=div, project=pa):
            ins(cn, "spk", {"id": i, "tenant_id": tenant, "spk_number": no, "project_id": project, "project_name": f"Project {no}",
                            "division_id": division, "status": status, "start_date": start, "end_date": end, "spk_value": budget * 2,
                            "procurement_budget": budget, "original_procurement_budget": budget})
        spk(A, f"SPK-A-{u}", "active", "2025-01-01", "2026-12-31", 1_200_000)       # 1 M + addendum 200 jt efektif 05/10
        spk(B, f"SPK-B-{u}", "active", "2025-01-01", "2025-10-15", 100_000, division=dB["id"], project=pb)
        spk(Cd, f"SPK-C-{u}", "draft", "2025-01-01", "2026-12-31", 500_000)
        spk(D, f"SPK-D-{u}", "active", "2025-11-01", "2026-12-31", 700_000)       # belum mulai s/d 31/10
        spk(E, f"SPK-E-{u}", "cancelled", "2025-01-01", "2026-12-31", 900_000)
        spk(F, f"SPK-F-{u}", "active", "2025-01-01", "2026-12-31", 120_000_000, project=pb)
        spk(G, f"SPK-G-{u}", "active", "2025-01-01", "2026-12-31", 400_000)
        spk(H, f"SPK-H-{u}", "active", "2025-01-01", "2026-12-31", 150_000)
        spk(I, f"SPK-I-{u}", "active", "2025-01-01", "2026-12-31", 500_000)       # tanpa commitment
        for st, chg, eff in (("effective", 200_000, "2025-10-05"), ("draft", 999, "2025-06-01"), ("cancelled", 5_000, "2025-06-01")):
            ins(cn, "spk_addendums", {"id": f"ad-{st}-{u}", "tenant_id": tenant, "spk_id": A, "status": st, "budget_change": chg,
                                      "spk_value_change": 0, "effective_date": eff, "addendum_type": "PROCUREMENT_BUDGET"})
        L = {k: f"pl-{k}-{u}" for k in ("a1", "a2", "b1", "f1", "g1", "h1")}
        ledger = (("COMMIT", A, "a1", 600_000, 10, "2025-09-20"), ("COMMIT", A, "a2", 100_000, 2, "2025-10-10"),
                  ("COMMIT", B, "b1", 120_000, 1, "2025-06-01"),
                  ("COMMIT", F, "f1", 100_000_000, 100, "2025-09-01"),
                  ("COMMIT", G, "g1", 300_000, 3, "2025-09-05"), ("RELEASE", G, "g1", 300_000, None, "2025-10-02"),
                  ("COMMIT", H, "h1", 200_000, 2, "2025-09-01"), ("ADJUST", H, "h1", -20_000, None, "2025-09-12"),
                  ("ADJUST", H, "h1", 5_000, None, "2025-10-20"))
        for i, (ev, sid, lk, amt, q, day) in enumerate(ledger):
            row = {"id": f"led-{i}-{u}", "tenant_id": tenant, "event": ev, "spk_id": sid, "po_id": f"po-{lk}-{u}",
                   "po_line_id": L[lk], "amount": amt, "created_at": at(day)}
            if q is not None:
                row["qty"] = q
            ins(cn, "spk_commitment_ledger", row)
        for lk, sid, q in (("a1", A, 10), ("a2", A, 2), ("b1", B, 1), ("f1", F, 100), ("g1", G, 3), ("h1", H, 2)):
            ins(cn, "po_lines", {"id": L[lk], "tenant_id": tenant, "po_id": f"po-{lk}-{u}", "qty": q})
            ins(cn, "procurement_item_spk_allocations", {"id": f"al-{lk}-{u}", "tenant_id": tenant, "source_type": "po",
                                                         "item_line_id": L[lk], "spk_id": sid, "allocated_qty": q})
        dos = (("a1", "2025-09-25", 5, True, False), ("a1", "2025-09-26", 2, True, True),      # DO batal diabaikan
               ("a2", "2025-10-15", 2, False, False),
               ("a1", "2025-11-05", 3, False, False), ("a1", "2025-11-20", 4, True, False),    # kumulatif 12 > 10
               ("f1", "2025-09-10", 40, True, False), ("f1", "2025-09-25", 30, False, False))
        for i, (lk, day, q, alloc, cancelled) in enumerate(dos):
            did = f"do-{i}-{u}"
            ins(cn, "do", {"id": did, "tenant_id": tenant, "no": did, "date": day, **({"cancelled": True, "status": "Cancelled"} if cancelled else {})})
            ins(cn, "do_lines", {"id": f"{did}-l", "tenant_id": tenant, "do_id": did, "po_line_id": L[lk], "qty": q})
            if alloc:
                ins(cn, "procurement_item_spk_allocations", {"id": f"al-{did}", "tenant_id": tenant, "source_type": "do",
                                                             "item_line_id": f"{did}-l", "spk_id": A if lk.startswith("a") else F,
                                                             "allocated_qty": q})
    finally:
        cn.close()

    def spk_sec(dt, extra="", fn=None):
        return dash("2025-01-01", dt, extra, fn).get("spk") or {}

    def drill_spk(dt, kind="active", extra="", fn=None):
        return (fn or call)("GET", f"dashboard/drill/spk?date_to={dt}&kind={kind}{extra}")

    def row_of(dt, sid, kind="active", extra=""):
        _, d = drill_spk(dt, kind, extra)
        return next((x for x in d.get("rows", []) if x["id"] == sid), {})

    # --- contoh user: cut-off 30/09
    s1 = spk_sec("2025-09-30")
    k1 = s1.get("kpi", {})
    check("SPK: section ada, posisi = date_to (date_from tidak dipakai)", s1.get("as_of") == "2025-09-30" and s1.get("with_value") is True, s1.get("as_of"))
    k1b = (dash("2025-09-01", "2025-09-30").get("spk") or {}).get("kpi", {})
    check("date_from berbeda -> KPI posisi SPK identik", k1b == k1, (k1b, k1))
    check("SPK aktif 30/09 = A,B,F,G,H,I (draft/cancelled/belum mulai tidak)", k1.get("active") == 6, k1)
    a = row_of("2025-09-30", A)
    check("A 30/09: Budget 1 M (addendum 05/10 belum)", a.get("budget") == 1_000_000, a)
    check("A 30/09: Commitment 600 jt, Realisasi 300 jt (partial DO 5/10; DO batal diabaikan)",
          a.get("commitment") == 600_000 and a.get("realization") == 300_000, a)
    check("A 30/09: Open Commitment 300 jt, Sisa Budget 400 jt (Budget - Commitment)",
          a.get("open_commitment") == 300_000 and a.get("remaining") == 400_000, a)
    a2 = row_of("2025-10-31", A)
    check("A 31/10: Budget 1,2 M, Commitment 700 jt, Realisasi 400 jt", a2.get("budget") == 1_200_000 and a2.get("commitment") == 700_000
          and a2.get("realization") == 400_000, a2)
    check("A 31/10: Open 300 jt, Sisa 500 jt (BUKAN Budget - Commitment - Realisasi = 100 jt)",
          a2.get("open_commitment") == 300_000 and a2.get("remaining") == 500_000, a2)
    a3 = row_of("2025-11-30", A)
    check("A 30/11: multiple DO kumulatif 12 > qty commit 10 -> realisasi dibatasi commitment (700 jt), open 0",
          a3.get("realization") == 700_000 and a3.get("open_commitment") == 0, a3)
    f0 = row_of("2025-09-15", F)
    f1 = row_of("2025-09-30", F)
    check("Partial DO: 40/100 -> Realisasi 40 jt", f0.get("realization") == 40_000_000, f0)
    check("DO kedua 30 -> kumulatif 70 jt (bukan 110 jt)", f1.get("realization") == 70_000_000 and f1.get("open_commitment") == 30_000_000, f1)
    g1, g2 = row_of("2025-09-30", G), row_of("2025-10-31", G)
    check("PO Approved lalu RELEASE (cancel): 30/09 commitment 300 jt, 31/10 = 0", g1.get("commitment") == 300_000 and g2.get("commitment") == 0
          and g2.get("open_commitment") == 0 and g2.get("remaining") == 400_000, (g1, g2))
    h1, h2 = row_of("2025-09-30", H), row_of("2025-10-31", H)
    check("ADJUST bertanda: 200 - 20 = 180 (30/09); +5 setelah cut-off tidak bocor -> 185 (31/10)",
          h1.get("commitment") == 180_000 and h2.get("commitment") == 185_000, (h1, h2))
    check("Over Budget: H 120% -> level over, Sisa Budget negatif", h1.get("level") == "over" and h1.get("remaining") == -30_000, h1)
    i1 = row_of("2025-09-30", I)
    check("SPK tanpa commitment: 0%, sisa = budget", i1.get("commitment") == 0 and i1.get("usage_pct") == 0 and i1.get("remaining") == 500_000, i1)
    exp_b = 1_000_000 + 100_000 + 120_000_000 + 400_000 + 150_000 + 500_000
    exp_c = 600_000 + 120_000 + 100_000_000 + 300_000 + 180_000
    exp_r = 300_000 + 70_000_000
    check("KPI total 30/09: Budget / Commitment / Realisasi", (k1.get("budget"), k1.get("commitment"), k1.get("realization")) == (exp_b, exp_c, exp_r), k1)
    check("KPI total 30/09: Open = C - R, Sisa = B - C", k1.get("open_commitment") == exp_c - exp_r and k1.get("remaining") == exp_b - exp_c, k1)
    check("Over Budget count 30/09 = B (120%) + H (120%)", k1.get("over_budget") == 2, k1)
    k2 = spk_sec("2025-10-31").get("kpi", {})
    check("31/10: B sudah berakhir -> tidak aktif; D belum mulai -> tidak dihitung", k2.get("active") == 5, k2)
    att2 = spk_sec("2025-10-31").get("attention", [])
    check("Perlu Perhatian 31/10: B berakhir tapi masih open commitment", any(x["id"] == B and "Berakhir, masih ada open commitment" in x["flags"]
                                                                              for x in att2), att2)
    att1 = spk_sec("2025-09-30").get("attention", [])
    check("Perlu Perhatian 30/09: Over Budget di urutan teratas; B juga 'Masa berlaku ≤ 30 hari'",
          att1 and "Over Budget" in att1[0]["flags"] and any(x["id"] == B and "Masa berlaku ≤ 30 hari" in x["flags"] for x in att1), att1)
    top = spk_sec("2025-09-30").get("top", [])
    check("Top 5 pemakaian budget: urut usage desc, maks 5", len(top) <= 5 and [x["usage_pct"] for x in top] == sorted([x["usage_pct"] for x in top], reverse=True), top)
    k4 = spk_sec("2025-11-30").get("kpi", {})
    check("30/11: D sudah mulai -> dihitung aktif", k4.get("active") == 6, k4)
    # scope
    sD = spk_sec("2025-09-30", f"&division_id={dB['id']}").get("kpi", {})
    check("Filter Divisi B: hanya SPK B", sD.get("active") == 1 and sD.get("budget") == 100_000, sD)
    sP = spk_sec("2025-09-30", f"&project_id={pb}").get("kpi", {})
    check("Filter Project B: hanya B & F", sP.get("active") == 2 and sP.get("budget") == 120_100_000, sP)
    sS = spk_sec("2025-09-30", f"&supplier_id={M['supY']['id']}").get("kpi", {})
    check("Filter Supplier tidak dipaksakan ke SPK", sS.get("active") == 6, sS)
    # drill-down parity (fungsi & predikat sama)
    for kind, kk in (("active", "active"), ("over", "over_budget"), ("attention", "attention"), ("expiring", "expiring")):
        sc, dd = drill_spk("2025-09-30", kind)
        check(f"Drill SPK '{kind}' count = KPI", sc == 200 and dd.get("count") == k1.get(kk) and dd.get("as_of") == "2025-09-30", (dd.get("count"), k1.get(kk)))
    sc, dd = drill_spk("2025-09-30", "active")
    check("Drill SPK aktif: Σ budget/commitment/realisasi/open/sisa = KPI", all(dd["totals"][k] == k1[k] for k in
                                                                                ("budget", "commitment", "realization", "open_commitment", "remaining")), dd.get("totals"))
    sc, ddp = drill_spk("2025-09-30", "active", f"&project_id={pb}")
    check("Drill SPK + filter project parity", ddp.get("count") == sP.get("active") and ddp["totals"]["budget"] == sP.get("budget"), ddp.get("totals"))

    # ------------------------------------------------------------------ fixture Kontrak & PO
    supX, supY = M["supX"], M["supY"]
    from po_ro_split_test import mk_item
    I1, I2, I3 = mk_item(M, f"I1{u}", "Kabel NYM"), mk_item(M, f"I2{u}", "Pipa PVC"), mk_item(M, f"I3{u}", "Lampu LED")
    I4, I5 = mk_item(M, f"I4{u}", "Semen (tier min 50)"), mk_item(M, f"I5{u}", "Cat Tembok")
    U = M["uom"]

    def vc(sup, no, item, price, start, end, tol=5, min_qty=None):
        _, c = call("POST", "vendor-contracts", {"supplier_id": sup["id"], "contract_number": no, "start_date": start, "end_date": end,
                                                 "default_tolerance_pct": tol}, 200)
        body = {"item_id": item["id"], "uom_id": U["id"], "base_price": price}
        if min_qty:
            body["min_qty"] = min_qty
        call("POST", f"vendor-contracts/{c['id']}/items", body, 200)
        call("POST", f"vendor-contracts/{c['id']}/activate", {}, 200)
        return c
    vc(supX, f"K1-{u}", I1, 10_000, "2026-01-01", "2026-07-20")
    vc(supX, f"K2-{u}", I2, 50_000, "2026-05-01", "2026-12-31")
    contract(supX, f"K3-DRAFT-{u}", I3, U, 1_000, start="2026-01-01", end="2026-12-31", activate=False)
    k4 = contract(supX, f"K4-CANCEL-{u}", I3, U, 1_000, start="2026-01-01", end="2026-12-31")
    call("POST", f"vendor-contracts/{k4['id']}/cancel", {"reason": "uji"})
    contract(supY, f"K5-EXP-{u}", I1, U, 10_000, start="2026-01-01", end="2026-03-31")
    vc(supX, f"K6-TIER-{u}", I4, 8_000, "2026-01-01", "2026-12-31", min_qty=50)
    vc(supX, f"K7-{u}", I5, 100_000, "2026-01-01", "2026-12-31", tol=0)

    def contracts(dt, extra="", fn=None):
        return (dash("2026-06-01", dt, extra, fn).get("vendor_contract") or {}).get("contracts", {})
    c1 = contracts("2026-06-30")
    check("Kontrak aktif 30/06 = K1, K2, K6, K7 (draft/cancelled/expired tidak)", c1.get("active") == 4, c1)
    check("Akan berakhir ≤ 30 hari dari cut-off = K1 (20/07)", c1.get("expiring") == 1, c1)
    check("Kedaluwarsa per cut-off = K5 (31/03)", c1.get("expired") == 1, c1)
    check("Item dalam kontrak aktif (resolver existing) = I1, I2, I5 (I4 tier min 50 tetap aktif) = 4", c1.get("items_active") == 4, c1)
    check("date_from tidak memengaruhi posisi kontrak", contracts("2026-06-30") == (dash("2026-01-01", "2026-06-30").get("vendor_contract") or {}).get("contracts"))
    c2 = contracts("2026-08-31")
    check("Cut-off 31/08: K1 sudah kedaluwarsa (relatif cut-off)", c2.get("active") == 3 and c2.get("expired") == 2, c2)
    cY = contracts("2026-06-30", f"&supplier_id={supY['id']}")
    check("Filter Supplier Y: 0 aktif, 1 kedaluwarsa", cY.get("active") == 0 and cY.get("expired") == 1, cY)
    for kind in ("active", "expiring", "expired"):
        sc, dc = call("GET", f"dashboard/drill/vendor-contracts?date_to=2026-06-30&kind={kind}")
        check(f"Drill kontrak '{kind}' count = KPI", sc == 200 and dc.get("count") == c1.get(kind), (dc.get("count"), c1.get(kind)))

    def po(item, qty, price, day, sup=supX, **kw):
        return manual_po(M, sup, item, qty, price, day, lines=[pl(M, item, qty, price, kw.pop("discount", 0), kw.pop("tax", 0))], **kw)
    p1 = po(I1, 10, 10_400, "2026-06-10")                    # <= 10.500 -> Sesuai
    p2 = po(I1, 10, 11_000, "2026-06-12")                    # > 10.500 -> Di Atas Tolerance, selisih 10.000
    p3 = po(I1, 100, 11_500, "2026-06-14")                   # > 10.500 -> Di Atas, selisih 1.500 x 100 = 150.000
    p4 = po(I3, 1, 1_000, "2026-06-15")                      # hanya kontrak draft/cancelled -> Tanpa Kontrak
    p5 = po(I2, 1, 52_000, "2026-06-16", discount=2_000)     # diskon item -> efektif 50.000 -> Sesuai
    p6 = po(I2, 1, 55_500, "2026-06-17", tax=11, inclusive=True)  # pajak inclusive diekstrak -> 50.000 -> Sesuai
    po(I1, 1, 99_999, "2026-06-18", approve=False)           # draft -> tidak dievaluasi
    p8 = po(I1, 1, 10_000, "2026-06-20", sup=supY)           # kontrak Y expired -> Tanpa Kontrak
    po(I1, 1, 10_000, "2026-07-02")                          # di luar periode
    p9 = po(I4, 10, 8_000, "2026-06-21")                     # qty < min tier 50 -> resolver tidak memberi harga -> Tanpa Kontrak
    p10 = po(I4, 60, 8_100, "2026-06-22")                    # qty >= 50 -> tier 8.000 (maks 8.400) -> Sesuai
    p11 = po(I5, 1, 110_000, "2026-06-23", discount=10_000, tax=11)   # 110.000 - 10.000, PPN 11% eksklusif -> 100.000 Sesuai
    p12 = manual_po(M, supX, I2, 2, 55_000, "2026-06-24", lines=[pl(M, I2, 2, 55_000)], final=("percent", 10))  # 49.500 Sesuai

    def pcs(df="2026-06-01", dt="2026-06-30", extra="", fn=None):
        return (dash(df, dt, extra, fn).get("vendor_contract") or {}).get("price_control") or {}
    pc = pcs()
    kp = pc.get("kpi", {})
    check("Price Control: PO Sesuai = 6 (P1, P5 diskon item, P6 pajak inclusive, P10 tier, P11 PPN, P12 diskon final)",
          kp.get("po_ok") == 6, (kp, pc.get("exceptions")))
    check("Price Control: PO Di Atas Tolerance = 2 (P2, P3)", kp.get("po_over") == 2, kp)
    check("Price Control: PO Tanpa Kontrak Aktif = 3 (P4 draft/cancelled, P8 expired, P9 di bawah min tier)", kp.get("po_no_contract") == 3, kp)
    check("Nilai Selisih Harga = 10.000 + 150.000", abs((kp.get("diff_value") or 0) - 160_000) < 0.01, kp.get("diff_value"))
    check("Hanya PO Approved final: draft & di luar periode tidak dievaluasi", kp.get("po_evaluated") == 11, kp)
    ex = pc.get("exceptions", [])
    check("Exception: Di Atas Tolerance dulu, selisih terbesar (P3) teratas; lalu Tanpa Kontrak",
          [e["po_id"] for e in ex[:2]] == [p3["id"], p2["id"]] and {e["po_id"] for e in ex[2:]} == {p4["id"], p8["id"], p9["id"]}, [(e["po_no"], e["status"]) for e in ex])
    e3 = ex[0] if ex else {}
    check("Exception P3: kontrak 10.000, PO 11.500, toleransi 5%, selisih 150.000, badge 'Di Atas Tolerance'",
          e3.get("contract_price") == 10_000 and abs(e3.get("po_price", 0) - 11_500) < 0.01 and abs(e3.get("diff", 0) - 150_000) < 0.01 and e3.get("tolerance_pct") == 5
          and e3.get("status_label") == "Di Atas Tolerance" and e3.get("item_name"), e3)
    check("PO yang sesuai tidak masuk exception", not {p1["id"], p5["id"], p6["id"], p10["id"], p11["id"], p12["id"]} & {e["po_id"] for e in ex})
    sc, dall = call("GET", "dashboard/drill/price-control?date_from=2026-06-01&date_to=2026-06-30&status=all")
    rows = {r["po_id"]: r for r in dall.get("rows", [])}
    check("Effective PO price P11 = 100.000 (diskon item, PPN 11% tidak ikut) bukan 111.000",
          abs(rows.get(p11["id"], {}).get("po_price", 0) - 100_000) < 0.01 and rows.get(p11["id"], {}).get("status") == "ok", rows.get(p11["id"]))
    check("Effective PO price P12 = 49.500 (diskon final 10% diprorata engine PO existing)",
          abs(rows.get(p12["id"], {}).get("po_price", 0) - 49_500) < 0.01, rows.get(p12["id"]))
    check("Effective PO price P6 (pajak inclusive) = 50.000", abs(rows.get(p6["id"], {}).get("po_price", 0) - 50_000) < 0.01, rows.get(p6["id"]))
    mism = []
    for r in dall.get("rows", []):  # parity: setiap baris = hasil endpoint resolver existing
        _, rr = call("GET", f"vendor-contracts/resolve-price?vendor_id={r['supplier_id']}&item_id={r['item_id']}&uom_id={r['uom_id']}"
                            f"&date={r['po_date']}&qty={r['qty']}")
        exp = (rr.get("contract_id"), rr.get("net_contract_price")) if rr.get("found") else (None, None)
        got = (r.get("contract_id"), int(r["contract_price"]) if r.get("contract_price") is not None else None)
        if exp != got:
            mism.append((r["po_no"], exp, got))
    check("Resolver parity: kontrak & net price tiap baris = /vendor-contracts/resolve-price existing", not mism and len(dall.get("rows", [])) == 11, mism)
    for stt, kk in (("over", "po_over"), ("no_contract", "po_no_contract"), ("ok", "po_ok")):
        sc, dp = call("GET", f"dashboard/drill/price-control?date_from=2026-06-01&date_to=2026-06-30&status={stt}")
        check(f"Drill Price Control '{stt}': jumlah PO = KPI", sc == 200 and dp.get("po_count") == kp.get(kk), (dp.get("po_count"), kp.get(kk)))
    sc, dpo = call("GET", "dashboard/drill/price-control?date_from=2026-06-01&date_to=2026-06-30&status=over")
    check("Drill 'over': Σ selisih = Nilai Selisih Harga KPI", abs((dpo.get("diff_value") or 0) - kp.get("diff_value", -1)) < 0.01, dpo.get("diff_value"))
    k15 = pcs("2026-06-15", "2026-06-30").get("kpi", {})
    check("Price Control memakai periode date_from..date_to (15–30/06 -> P1–P3 tidak ikut)", k15.get("po_evaluated") == 8 and k15.get("po_over") == 0, k15)
    pcY = pcs(extra=f"&supplier_id={supY['id']}")
    check("Filter Supplier Y: hanya P8 (Tanpa Kontrak)", pcY["kpi"].get("po_evaluated") == 1 and pcY["kpi"].get("po_no_contract") == 1, pcY["kpi"])
    pcD = pcs(extra=f"&division_id={dB['id']}")
    check("Filter Divisi B: PO divisi lain tidak dievaluasi", pcD["kpi"].get("po_evaluated") == 0, pcD["kpi"])
    from reporting import price_control as PCm
    nonfinal = [{"status": st, "document_status": ds} for st, ds in (("Draft", "Draft"), ("Waiting Approval", "Waiting Approval 1"),
                                                                     ("Waiting Approval", "Ready Approval 2"), ("Waiting Approval", "Waiting Approval 2"),
                                                                     ("Rejected", "Rejected"), ("Approved", "Cancelled"))]
    nonfinal.append({"status": "Approved", "cancelled": True})
    final = [{"status": s} for s in ("Approved", "Partially Received", "Fully Received")]
    check("Definisi Approved final: Draft/Waiting A1/Ready A2/Waiting A2/Rejected/Cancelled ditolak; Approved/Received diterima",
          not any(PCm.po_in_scope(r) for r in nonfinal) and all(PCm.po_in_scope(r) for r in final))
    call("POST", f"po/{p2['id']}/cancel", {"reason": "uji"})
    kpc = pcs().get("kpi", {})
    check("PO Approved lalu dibatalkan tidak dievaluasi", kpc.get("po_over") == 1 and kpc.get("po_evaluated") == 10, kpc)

    # ------------------------------------------------------------------ redaksi nominal (matrix izin, rekursif)
    import po_approval2_batch_test as AP
    AP.M = M
    users = []

    def mk(name, ov):
        x = AP.mk_user(name, [div])
        AP.set_ov(x, ov)
        users.append(x)
        return x
    u_ns = mk("dspk0", {"spk.view": "deny", "view_purchase_price": "allow", "vendor_contracts.view": "allow"})
    sn = spk_sec("2025-09-30", fn=u_ns)
    check("Tanpa spk:view: count SPK ada, nominal & daftar SPK TIDAK ada di JSON (rekursif)", sn.get("with_value") is False
          and sn.get("kpi", {}).get("active") == 5 and not (keys(sn) & SPK_VALUE_KEYS) and "top" not in sn and "attention" not in sn, sn)
    sc, _ = drill_spk("2025-09-30", fn=u_ns)
    check("Tanpa spk:view: drill SPK ditolak 403", sc == 403, sc)
    matrix = {("deny", "deny"): False, ("allow", "deny"): False, ("deny", "allow"): False, ("allow", "allow"): True}
    for i, ((vcv, vpp), allowed) in enumerate(matrix.items()):
        us = mk(f"dvc{i}", {"spk.view": "allow", "vendor_contracts.view": vcv, "view_purchase_price": vpp})
        d = dash("2026-06-01", "2026-06-30", fn=us)
        v = d.get("vendor_contract") or {}
        leak = keys(v) & PRICE_KEYS
        _, dp = us("GET", "dashboard/drill/price-control?date_from=2026-06-01&date_to=2026-06-30&status=all")
        leak_d = keys(dp) & PRICE_KEYS
        cnt = v.get("contracts", {}).get("active") == 4 and (v.get("price_control") or {}).get("kpi", {}).get("po_evaluated") == 10
        if allowed:
            check(f"vendor_contract:view={vcv} & view_purchase_price={vpp}: nominal dikirim", v.get("with_value") is True and cnt
                  and {"contract_price", "po_price", "diff_value"} <= keys(v) and "po_price" in keys(dp), sorted(leak))
        else:
            check(f"vendor_contract:view={vcv} & view_purchase_price={vpp}: count only, tanpa nominal (dashboard + drill, rekursif)",
                  v.get("with_value") is False and cnt and not leak and not leak_d and dp.get("count", 0) > 0, (sorted(leak), sorted(leak_d)))
        if i == 3:
            check("User terbatas Divisi Teknik + izin nominal: SPK divisi lain (B) tidak terlihat", spk_sec("2025-09-30", fn=us).get("kpi", {}).get("active") == 5)
            sc, _ = us("GET", f"{CC}?date_from=2026-06-01&date_to=2026-06-30&division_id={dB['id']}")
            check("Izin harga tidak memberi akses divisi lain (403)", sc == 403, sc)
        call("DELETE", f"users/{us.uid}", None, 200)  # batas user paket tenant uji
        users.remove(us)

    # ------------------------------------------------------------------ isolasi tenant
    import requests
    s1 = T.S
    T.S = requests.Session()
    T.setup()
    dt = dash("2025-01-01", "2025-09-30")
    dt2 = dash("2026-06-01", "2026-06-30")
    _, dsp = call("GET", "dashboard/drill/spk?date_to=2025-09-30&kind=active")
    check("Tenant lain: SPK & kontrak & price control tenant ini tidak terlihat",
          (dt.get("spk") or {}).get("kpi", {}).get("active") == 0 and (dt2.get("vendor_contract") or {}).get("contracts", {}).get("active") == 0
          and ((dt2.get("vendor_contract") or {}).get("price_control") or {}).get("kpi", {}).get("po_evaluated") == 0 and dsp.get("count") == 0,
          (dt.get("spk"), dt2.get("vendor_contract")))
    T.S = s1
    for us in users:
        call("DELETE", f"users/{us.uid}", None, 200)


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
