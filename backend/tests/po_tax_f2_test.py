"""F2 — Integrasi PPN ke PO (itest API + DB, tenant sekali pakai, DB *_itest terisolasi; BUKAN production).

Dua fase agar dokumen historis diuji dengan dokumen ASLI buatan versi lama:
  A) backend `main` sebelum F2:  TEST_API_URL=... python3 po_tax_f2_test.py phase_a   -> PO v1 + state JSON
  B) backend F2 (DB yang sama):  TEST_API_URL=... python3 po_tax_f2_test.py phase_b   -> seluruh skenario F2
State: $F2_STATE (default /tmp/po_tax_f2_state.json).
"""
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import receipt_control_test as T  # noqa: E402

call, check, S = T.call, T.check, T.S
STATE = os.environ.get("F2_STATE", "/tmp/po_tax_f2_state.json")
PW = "TestPass123!"


def login(email):
    sc, r = call("POST", "auth/login", {"email": email, "password": PW}, 200)
    S.headers.update({"Authorization": f"Bearer {r['token']}"})


def line(M, qty, price, tax_id=None, mode=None, discount=0, item="item", **kw):
    x = {"item_id": M[item]["id"], "qty": qty, "uom_id": M["uom"]["id"], "price": price, "discount": discount,
         "warehouse_id": M["wh"]["id"], "price_change_reason": "uji F2", **kw}
    if tax_id is not None:
        x["tax_id"] = tax_id
    if mode is not None:
        x["tax_mode"] = mode
    return x


def po_body(M, lines, sup="supX", **hdr):
    return {"supplier_id": M[sup]["id"], "division_id": M["div"]["id"], "date": hdr.pop("date", "2026-06-01"), "lines": lines, **hdr}


def get(pid):
    return call("GET", f"po/{pid}", None, 200)[1]


def money(d):
    keys = ("grand_total", "tax_total", "subtotal_after_discount", "final_discount_amount", "gross_total", "tax_inclusive")
    return {"h": {k: d.get(k) for k in keys},
            "l": [{k: ln.get(k) for k in ("qty", "price", "discount", "tax", "dpp", "tax_amount", "total", "tax_inclusive", "tax_id")}
                  for ln in d["lines"]]}


# ----------------------------------------------------------------------------- fase A (versi lama)
def phase_a():
    M = T.setup()
    u = uuid.uuid4().hex[:6]
    sc, me = call("GET", "auth/me", None, 200)
    email = me.get("email")
    sc, told = call("POST", "master/taxes", {"code": f"PPN11{u}", "name": "PPN 11% (lama)", "rate": 11}, 200)
    call("PUT", f"master/suppliers/{M['supX']['id']}", {**M["supX"], "pkp": True}, 200)
    sc, p1 = call("POST", "po", po_body(M, [line(M, 3, 33333, told["id"])], final_discount_type="amount", final_discount_value=1), 200)
    call("POST", f"po/{p1['id']}/submit", {}, 200)
    sc, p2 = call("POST", "po", po_body(M, [line(M, 3, 33333, told["id"]), line(M, 2, 1005, told["id"], item="item2")], tax_inclusive=True), 200)
    sc, p3 = call("POST", "po", po_body(M, [line(M, 1, 267900000, told["id"])]), 200)
    call("POST", f"po/{p3['id']}/submit", {}, 200)
    # PO lama ber-PPN pada supplier yang (kemudian) Non-PKP -> harus muncul di audit kesiapan, nominal tidak berubah.
    call("PUT", f"master/suppliers/{M['supY']['id']}", {**M["supY"], "pkp": False}, 200)
    sc, p4 = call("POST", "po", po_body(M, [line(M, 2, 5000, told["id"])], sup="supY"), 200)
    pairs = (("p1", p1), ("p2", p2), ("p3", p3), ("p4", p4))
    st = {"email": email, "M": M, "told": told, "p1": p1["id"], "p2": p2["id"], "p3": p3["id"], "p4": p4["id"], "p4_no": p4.get("no"),
          "snap": {k: money(get(v["id"])) for k, v in pairs},
          "raw": {k: get(v["id"]) for k, v in pairs}}
    check("Fase A: PO v1 dibuat versi lama (tanpa tax_engine_version)", all(not st["raw"][k].get("tax_engine_version") for k in ("p1", "p2", "p3", "p4")))
    check("Fase A: PO v1 PPN 11% (3 x 33.333 - Rp1)", abs(st["snap"]["p1"]["h"]["grand_total"] - 110997.78) < 0.01, st["snap"]["p1"]["h"])
    json.dump(st, open(STATE, "w"))


# ----------------------------------------------------------------------------- fase B (F2)
def tax(body, expect=200):
    return call("POST", "master/taxes", body, expect)


def phase_b():
    import tax_engine as TE  # golden-verified (F1)
    st = json.load(open(STATE))
    M = st["M"]
    login(st["email"])
    u = uuid.uuid4().hex[:6]

    # ---------------------------------------------------------------- 1. dokumen historis tidak berubah
    for k in ("p1", "p2", "p3", "p4"):
        d = get(st[k])
        check(f"Historis {k}: nominal identik setelah F2 aktif", money(d) == st["snap"][k], (money(d), st["snap"][k]))
        check(f"Historis {k}: tetap v1 (tanpa tax_engine_version)", not d.get("tax_engine_version"))

    # ---------------------------------------------------------------- 2. Master Pajak
    sc, t04 = tax({"code": f"P04{u}", "name": "PPN DPP Nilai Lain", "rate": 12, "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "04", "facility": "NORMAL"})
    sc, t01 = tax({"code": f"P01{u}", "name": "PPN 12% penuh", "rate": 12, "dpp_factor_num": 1, "dpp_factor_den": 1, "trx_code": "01"})
    sc, t08 = tax({"code": f"P08{u}", "name": "PPN Dibebaskan", "rate": 12, "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "08", "facility": "DIBEBASKAN"})
    sc, t07 = tax({"code": f"P07{u}", "name": "PPN Tidak Dipungut", "rate": 12, "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "07", "facility": "TIDAK_DIPUNGUT"})
    sc, texp = tax({"code": f"PX{u}", "name": "PPN kedaluwarsa", "rate": 12, "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "04", "valid_from": "2025-01-01", "valid_to": "2025-12-31"})
    sc, tinc = tax({"code": f"PI{u}", "name": "PPN belum lengkap", "rate": 12})
    check("Master Pajak: field F2 tersimpan", (t04.get("trx_code"), t04.get("dpp_factor_num"), t04.get("dpp_factor_den"), t04.get("facility")) == ("04", 11, 12, "NORMAL"), t04)
    for name, body, msg in [
        ("Dibebaskan wajib kode 08", {"name": "x", "rate": 12, "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "04", "facility": "DIBEBASKAN"}, "08"),
        ("Tidak Dipungut wajib kode 07", {"name": "x", "rate": 12, "dpp_factor_num": 1, "dpp_factor_den": 1, "trx_code": "01", "facility": "TIDAK_DIPUNGUT"}, "07"),
        ("Faktor DPP > 1 ditolak", {"name": "x", "rate": 12, "dpp_factor_num": 13, "dpp_factor_den": 12, "trx_code": "04"}, "Faktor"),
        ("Faktor DPP setengah diisi ditolak", {"name": "x", "rate": 12, "dpp_factor_num": 11, "trx_code": "04"}, "pembilang"),
        ("Kode transaksi tidak dikenal ditolak", {"name": "x", "rate": 12, "trx_code": "99"}, "tidak dikenal"),
        ("Tarif > 100 ditolak", {"name": "x", "rate": 150, "trx_code": "04"}, "0..100"),
        ("Berlaku sampai < dari ditolak", {"name": "x", "rate": 12, "valid_from": "2026-02-01", "valid_to": "2026-01-01"}, "Berlaku"),
        ("Format tanggal salah ditolak", {"name": "x", "rate": 12, "valid_from": "01/02/2026"}, "YYYY-MM-DD"),
    ]:
        sc, r = tax(body, None)
        check(f"Master Pajak: {name}", sc == 400 and msg in str(r.get("detail")), (sc, r))
    sc, upd = call("PUT", f"master/taxes/{t01['id']}", {"notes": "catatan saja"}, 200)
    check("Master Pajak: update parsial tidak menghapus konfigurasi", (upd.get("trx_code"), upd.get("dpp_factor_den")) == ("01", 1), upd)

    sc, opts = call("GET", "po/tax-options?date=2026-06-01", None, 200)
    by = {o["id"]: o for o in opts["items"]}
    check("tax-options: master lengkap ready, label kode + tarif x faktor", by[t04["id"]]["ready"] and by[t04["id"]]["label"].startswith("04 · ") and "12% × 11/12" in by[t04["id"]]["label"], by[t04["id"]])
    check("tax-options: tarif efektif 11% (12 x 11/12) / 12% penuh / fasilitas 0", (by[t04["id"]]["effective_rate"], by[t01["id"]]["effective_rate"], by[t08["id"]]["effective_rate"]) == (11.0, 12.0, 0.0))
    check("tax-options: master lama / belum lengkap ditandai", not by[tinc["id"]]["ready"] and not by[st["told"]["id"]]["ready"] and "kode transaksi faktur" in by[tinc["id"]]["issues"])
    check("tax-options: masa berlaku dievaluasi per tanggal PO", by[texp["id"]]["valid_on_date"] is False and by[t04["id"]]["valid_on_date"] is True)
    check("tax-options: PPnBM belum diaktifkan", opts.get("ppnbm_enabled") is False)

    # ---------------------------------------------------------------- 3. PO campuran (simulasi desain, tanpa PPnBM)
    call("PUT", f"master/suppliers/{M['supX']['id']}", {**M["supX"], "pkp": True}, 200)
    sim = [line(M, 10, 100000, t04["id"], "EXCLUDE", discount=50000), line(M, 4, 55500, t04["id"], "INCLUDE", item="item2"),
           line(M, 2, 39000, t08["id"], "EXCLUDE"), line(M, 1, 50000000, t01["id"], "EXCLUDE"),
           line(M, 5, 200000, t07["id"], "EXCLUDE"), line(M, 1, 100000, None, "NONE")]
    hdr = {"final_discount_type": "percent", "final_discount_value": 5}
    sc, pv = call("POST", "po/tax-preview", po_body(M, sim, **hdr), 200)
    t = pv.get("totals") or {}
    check("Preview: v2 + kebijakan pembulatan", pv.get("tax_engine_version") == 2 and pv.get("rounding_policy"), pv.get("tax_engine_version"))
    check("Preview: Grand Total 55.531.775 (= golden SIM 62.656.775 - PPnBM 7.125.000)", t.get("grand_total") == 55531775.0, t.get("grand_total"))
    check("Preview: PPN 5.820.175 · DPP 49.616.600 · Tanpa PPN 95.000 · Diskon Final 2.617.500 · fasilitas 112.651",
          (t.get("tax_total"), t.get("dpp_total"), t.get("non_ppn_total"), t.get("final_discount_amount"), t.get("tax_facility_total"))
          == (5820175.0, 49616600.0, 95000.0, 2617500.0, 112651.0), t)
    L = pv["lines"]
    exp = [(902500.0, 827291.67, 99275.0, 1001775.0), (190000.0, 174166.67, 20900.0, 210900.0), (74100.0, 67925.0, 0.0, 74100.0),
           (47500000.0, 47500000.0, 5700000.0, 53200000.0), (950000.0, 870833.33, 0.0, 950000.0), (95000.0, 0.0, 0.0, 95000.0)]
    check("Preview: nilai per baris = golden F1 (DPP, DPP NL, PPN, Total)", [(l["dpp"], l["dpp_other"], l["tax_amount"], l["total"]) for l in L] == exp,
          [(l["dpp"], l["dpp_other"], l["tax_amount"], l["total"]) for l in L])
    eng = TE.compute_po({**hdr, "supplier_pkp": True}, [{"qty": x["qty"], "price": x["price"], "discount": x["discount"], "tax_mode": x["tax_mode"],
                                                        "tax_rule": TE.rule_from_master(tt) if tt else None}
                                                       for x, tt in zip(sim, [t04, t04, t08, t01, t07, None])])
    check("Preview == Tax Engine F1 langsung (grand/tax/dpp_other)", (t["grand_total"], t["tax_total"], t["dpp_other_total"]) ==
          (float(eng["totals"]["grand_total"]), float(eng["totals"]["tax_total"]), float(eng["totals"]["dpp_other_total"])))
    check("Preview: kelompok faktur 04/08/01/07", [g["trx_code"] for g in t["tax_groups"]] == ["04", "08", "01", "07"] and t["tax_groups"][0]["dpp_other"] == 1001458.34, t.get("tax_groups"))

    sc, pa = call("POST", "po", po_body(M, sim, **hdr), 200)
    d = get(pa["id"])
    check("Simpan: PO baru v2 + snapshot aturan dokumen", d.get("tax_engine_version") == 2 and len(d.get("tax_rules_snapshot") or []) == 4 and d.get("supplier_pkp") is True)
    check("Simpan: nominal = preview (form = simpan)", (d["grand_total"], d["tax_total"], d["dpp_total"]) == (t["grand_total"], t["tax_total"], t["dpp_total"]), (d["grand_total"], d["tax_total"]))
    dl = d["lines"]
    check("Simpan: per baris dpp/tax_amount/total = preview", [(l["dpp"], l["tax_amount"], l["total"]) for l in dl] == [(l["dpp"], l["tax_amount"], l["total"]) for l in L])
    check("Simpan: snapshot baris (kode, tarif, faktor, kode faktur, fasilitas)",
          (dl[0]["tax_code"], dl[0]["tax_rate"], dl[0]["tax_dpp_factor_num"], dl[0]["tax_dpp_factor_den"], dl[0]["tax_trx_code"], dl[0]["tax_facility"])
          == (t04["code"], "12", 11, 12, "04", "NORMAL") and dl[2]["tax_facility"] == "DIBEBASKAN", dl[0])
    check("Kontrak legacy: tax_inclusive per baris (Include) + tax = tarif efektif", [l["tax_inclusive"] for l in dl] == [False, True, False, False, False, False]
          and [l["tax"] for l in dl] == [11.0, 11.0, 0.0, 12.0, 0.0, 0.0], [(l["tax_inclusive"], l["tax"]) for l in dl])
    check("Kontrak legacy: fungsi dpp tetap = nilai tanpa PPN setelah diskon (Include: dikeluarkan PPN)", dl[1]["dpp"] == 190000.0 and dl[0]["dpp"] == 902500.0)
    check("Kontrak legacy: Σ total baris = Grand Total (commitment SPK)", round(sum(l["total"] for l in dl), 2) == d["grand_total"])
    check("Header tax_inclusive v2 = False (perlakuan per baris)", d.get("tax_inclusive") is False)

    # ---------------------------------------------------------------- 4. validasi
    def post_err(lines, msg, name, sup="supX", **h):
        sc, r = call("POST", "po", po_body(M, lines, sup=sup, **h))
        check(name, sc == 400 and msg in str(r.get("detail")), (sc, r))
        sc2, r2 = call("POST", "po/tax-preview", po_body(M, lines, sup=sup, **h))
        check(name + " (preview sama)", sc2 == 400 and msg in str(r2.get("detail")), (sc2, r2))
    call("PUT", f"master/suppliers/{M['supY']['id']}", {**M["supY"], "pkp": False}, 200)
    post_err([line(M, 1, 1000, t04["id"], "EXCLUDE")], "Non-PKP", "Supplier Non-PKP + PPN ditolak", sup="supY")
    sc, lgn = call("POST", "po", po_body(M, [{**line(M, 1, 1000), "tax": 11}], sup="supY"))
    check("Supplier Non-PKP + tarif numerik API lama ditolak (aturan Non-PKP mutlak)", sc == 400 and "Non-PKP" in str(lgn.get("detail")), (sc, lgn))
    sc, pn = call("POST", "po", po_body(M, [line(M, 1, 1000, None, "NONE")], sup="supY"), 200)
    check("Supplier Non-PKP + Tanpa PPN diterima", pn.get("grand_total") == 1000.0 and pn.get("supplier_pkp") is False, pn.get("grand_total"))
    post_err([line(M, 1, 1000, tinc["id"], "EXCLUDE")], "belum lengkap", "Master belum lengkap ditolak (tidak fallback v1)")
    post_err([line(M, 1, 1000, st["told"]["id"], "EXCLUDE")], "belum lengkap", "Master lama (hanya tarif) ditolak untuk PO v2")
    post_err([line(M, 1, 1000, texp["id"], "EXCLUDE")], "tidak berlaku", "Jenis PPN di luar masa berlaku ditolak")
    post_err([line(M, 1, 1000, None, "EXCLUDE")], "wajib dipilih", "Exclude tanpa Jenis PPN ditolak")
    post_err([line(M, 1, 1000, t08["id"], "INCLUDE")], "Include", "Fasilitas + Include ditolak")
    post_err([line(M, 1, 1000, t01["id"], "EXCLUDE", ppnbm_rate=20)], "PPnBM belum diaktifkan", "PPnBM belum diaktifkan di F2")
    post_err([line(M, 1, 1000, t04["id"], "SEBAGIAN")], "tidak dikenal", "Mode tidak dikenal ditolak")
    sc, _ = call("POST", "po", po_body(M, [line(M, 1, 0, t04["id"], "EXCLUDE")]))
    check("Kontrol harga existing: harga 0 tetap ditolak", sc == 400, sc)

    # ---------------------------------------------------------------- 4b. audit kesiapan PPN (read-only)
    call("PUT", f"master/suppliers/{M['supY']['id']}", {**M["supY"], "pkp": False, "default_tax_id": t04["id"]}, 200)
    sc, rd = call("GET", "po/tax-readiness", None, 200)
    rs = {r["id"]: r for r in rd.get("non_pkp_suppliers") or []}
    y = rs.get(M["supY"]["id"]) or {}
    check("Audit PPN: read-only + Master Pajak belum lengkap terdaftar", rd.get("read_only") is True and rd.get("ready") is False
          and tinc["id"] in {t["id"] for t in rd.get("incomplete_taxes") or []} and t04["id"] not in {t["id"] for t in rd.get("incomplete_taxes") or []}, rd.get("incomplete_taxes"))
    check("Audit PPN: supplier Non-PKP dengan Default Pajak bertarif + PO lama ber-PPN", "Default Pajak bertarif PPN" in (y.get("reasons") or [])
          and "Memiliki PO ber-PPN" in (y.get("reasons") or []) and st["p4_no"] in (y.get("po_numbers") or []), y)
    check("Audit PPN: supplier PKP tidak terdaftar", M["supX"]["id"] not in rs)
    check("Audit PPN: tanpa nominal harga", not any(k in str(rd) for k in ("grand_total", "tax_total", "dpp")), list(y))
    from opening_inventory_valuation_test import dbq
    pkp_y = dbq("SELECT JSON_EXTRACT(doc,'$.pkp') FROM suppliers WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.id'))=%s", [M["supY"]["id"]])
    check("Audit PPN: tidak mengubah data (supplier tetap Non-PKP, PO lama identik)", str(pkp_y).lower() in ("false", "0") and money(get(st["p4"])) == st["snap"]["p4"], pkp_y)
    call("PUT", f"master/suppliers/{M['supY']['id']}", {**M["supY"], "pkp": False, "default_tax_id": None}, 200)

    # ---------------------------------------------------------------- 5. Include pembulatan + diskon item + Diskon Final Rp
    sc, pi = call("POST", "po", po_body(M, [line(M, 1, 1005, t04["id"], "INCLUDE"), line(M, 3, 33333, t04["id"], "EXCLUDE", discount=0.5, item="item2")],
                                         final_discount_type="amount", final_discount_value=1), 200)
    a, b = pi["lines"]
    check("Include Rp1.005 (porsi Diskon Final 0,01): DPP/DPP NL/PPN sesuai engine", (a["dpp"], a["dpp_other"], a["tax_amount"]) == (905.4, 829.95, 99.59) and a["include_rounding_diff"] == 0.0, (a["dpp"], a["dpp_other"], a["tax_amount"], a["include_rounding_diff"]))
    check("Exclude + diskon item Rp0,50 + porsi Diskon Final", (b["dpp"], b["tax_amount"], b["total"]) == (99997.51, 10999.73, 110997.24), (b["dpp"], b["tax_amount"], b["total"]))
    check("Grand Total Include+Exclude", pi["grand_total"] == round(a["total"] + b["total"], 2) == 112002.23, pi["grand_total"])

    # ---------------------------------------------------------------- 6. edit v2: snapshot historis dipertahankan
    call("PUT", f"master/taxes/{t04['id']}", {**t04, "rate": 11}, 200)  # aturan master berubah
    d = get(pa["id"])
    body = {k: d.get(k) for k in ("date", "supplier_id", "division_id", "payment_term", "currency", "final_discount_type", "final_discount_value")}
    body["lines"] = [{**{k: l.get(k) for k in ("id", "item_id", "qty", "uom_id", "price", "discount", "tax_id", "tax_mode", "warehouse_id", "price_change_reason")}} for l in d["lines"]]
    sc, e1 = call("PUT", f"transactions/po/{pa['id']}", body, 200)
    e1 = get(pa["id"])
    check("Edit v2 tanpa ubah Jenis PPN: snapshot lama (tarif 12) dipakai, nominal tetap", e1["grand_total"] == 55531775.0 and e1["lines"][0]["tax_rate"] == "12" and e1.get("tax_engine_version") == 2, (e1["grand_total"], e1["lines"][0].get("tax_rate")))
    body2 = {**body, "lines": body["lines"] + [line(M, 1, 120000, t04["id"], "EXCLUDE")]}
    for x, ol in zip(body2["lines"], e1["lines"]):
        x["id"] = ol["id"]
    sc, _ = call("PUT", f"transactions/po/{pa['id']}", body2, 200)
    e2 = get(pa["id"])
    nl = e2["lines"][-1]
    check("Edit v2 baris baru: aturan master terbaru (11 x 11/12), ikut Diskon Final 5%", (nl["tax_rate"], nl["net_amount"], nl["dpp_other"], nl["tax_amount"]) == ("11", 114000.0, 104500.0, 11495.0), (nl.get("tax_rate"), nl.get("net_amount"), nl.get("dpp_other"), nl.get("tax_amount")))
    check("Edit v2: baris lama tetap snapshot 12 (nominal tidak berubah)", (e2["lines"][0]["tax_rate"], e2["lines"][0]["tax_amount"]) == ("12", 99275.0), e2["lines"][0].get("tax_amount"))
    call("PUT", f"master/taxes/{t04['id']}", {**t04, "rate": 12}, 200)
    sc, sw = call("PUT", f"transactions/po/{pi['id']}", {"date": "2026-06-01", "supplier_id": M["supX"]["id"], "division_id": M["div"]["id"],
                                                         "lines": [line(M, 1, 1005, t04["id"], "EXCLUDE")]}, 200)
    check("Edit v2: ubah Include -> Exclude dihitung ulang backend", get(pi["id"])["grand_total"] == 1115.55, get(pi["id"])["grand_total"])

    # ---------------------------------------------------------------- 7. approval + cetak data
    sc, pb = call("POST", "po", po_body(M, [line(M, 2, 250000, t04["id"], "EXCLUDE")]), 200)
    sc, sub = call("POST", f"po/{pb['id']}/submit", {}, 200)
    ab = get(pb["id"])
    check("Approval: status lanjut, nominal tetap (500.000 + PPN 55.000)", ab["status"] in ("Approved", "Waiting Approval") and ab["grand_total"] == 555000.0 and ab["tax_total"] == 55000.0, (ab["status"], ab["grand_total"]))
    check("Approval: snapshot versi tetap v2", ab.get("tax_engine_version") == 2 and ab["lines"][0]["tax_trx_code"] == "04")

    # ---------------------------------------------------------------- 8. DO memakai rumus lama dpp/qty
    check("Approval: tanpa approver -> Approved", ab["status"] == "Approved", ab["status"])
    if ab["status"] == "Approved":
        sc, do = call("POST", "do", T.do_body(M, ab, 2, "supX"), 200)
        from opening_inventory_valuation_test import dbq
        rows = dbq("SELECT JSON_EXTRACT(doc,'$.unit_cost') FROM valuation_ledger WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.doc_id'))=%s", [do.get("id")])
        uc = float(rows) if rows is not None else None  # dbq -> skalar
        check("DO dari PO v2: biaya perolehan = dpp/qty (250.000, tanpa PPN) — rumus DO tidak berubah", uc == 250000.0, rows)

    # ---------------------------------------------------------------- 9. hak akses + redaksi harga
    from vendor_invoice_test import mk_user
    nop = mk_user("manager", divs=[M["div"]["id"]], overrides={"view_purchase_price": "deny", "po.view": "allow"})
    sc, r = nop("GET", f"po/{pa['id']}")
    ln0 = (r.get("lines") or [{}])[0]
    check("Redaksi: tanpa izin harga, nominal v2 disembunyikan (DPP NL, kelompok faktur, DPP total)",
          sc == 200 and ln0.get("dpp_other") is None and r.get("tax_groups") is None and r.get("dpp_total") is None and r.get("grand_total") is None, (sc, ln0.get("dpp_other"), r.get("tax_groups")))
    check("Redaksi: snapshot non-nominal tetap tampil (kode faktur / mode)", ln0.get("tax_trx_code") == "04" and ln0.get("tax_mode") == "EXCLUDE", ln0)
    sc, r = nop("POST", "po/tax-preview", po_body(M, sim, **hdr))
    check("Preview ditolak tanpa izin lihat harga", sc == 403, sc)
    sc, r = nop("GET", "po/tax-readiness")
    check("Audit PPN: dapat dibaca tanpa izin harga (tidak memuat nominal)", sc == 200 and "non_pkp_suppliers" in r, sc)
    nov = mk_user("warehouse", overrides={"po.view": "deny"})
    sc, r = nov("GET", "po/tax-options")
    check("tax-options ditolak tanpa izin modul PO", sc == 403, sc)
    sc, r = nov("GET", "po/tax-readiness")
    check("Audit PPN ditolak tanpa izin modul PO", sc == 403, sc)

    # ---------------------------------------------------------------- 10. PO lama v1 setelah master berubah
    call("PUT", f"master/taxes/{st['told']['id']}", {**st["told"], "rate": 12, "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "04"}, 200)
    for k in ("p1", "p3", "p4"):
        check(f"Historis {k}: tetap identik setelah master dilengkapi/diubah", money(get(st[k])) == st["snap"][k])
    d2 = get(st["p2"])
    b2 = {k: d2.get(k) for k in ("date", "supplier_id", "division_id", "payment_term", "currency", "tax_inclusive", "final_discount_type", "final_discount_value")}
    b2["lines"] = [{k: l.get(k) for k in ("id", "item_id", "qty", "uom_id", "price", "discount", "tax_id", "warehouse_id", "price_change_reason")} for l in d2["lines"]]
    b2["lines"][0]["qty"] = 4
    b2["lines"][0]["tax"] = 12  # klien mencoba tarif master baru -> dikunci ke tarif tersimpan
    sc, _ = call("PUT", f"transactions/po/{st['p2']}", b2, 200)
    e = get(st["p2"])
    check("Edit PO v1 (Draft): tetap v1, tarif baris dikunci 11%", not e.get("tax_engine_version") and [l["tax"] for l in e["lines"]] == [11.0, 11.0], [l.get("tax") for l in e["lines"]])
    exp_v1 = 4 * 33333 + 2 * 1005  # Include: total = net
    check("Edit PO v1 (Include header): Grand Total rumus v1", abs(e["grand_total"] - exp_v1) < 1e-6 and e.get("tax_inclusive") is True, e["grand_total"])
    sc, lg = call("POST", "po", po_body(M, [{**line(M, 1, 1000), "tax": 11}]), 200)
    check("Kompatibilitas API lama (tarif numerik tanpa Jenis PPN) -> v1", not lg.get("tax_engine_version") and lg["grand_total"] == 1110.0, (lg.get("tax_engine_version"), lg.get("grand_total")))
    sc, lx = call("POST", "po", po_body(M, [line(M, 1, 1000, st["told"]["id"])]), 200)
    check("Jenis PPN tanpa tax_mode (impor Excel) -> v2 Exclude dari master", lx.get("tax_engine_version") == 2 and lx["lines"][0]["tax_mode"] == "EXCLUDE" and lx["grand_total"] == 1110.0, (lx.get("tax_engine_version"), lx.get("grand_total")))

    # ---------------------------------------------------------------- 11. alur MRO -> RO -> PO v2 + tracking lifecycle
    sc, mro = call("POST", "mro", {"no": f"MRO-F2{u}", "division_id": M["div"]["id"], "requester": "Budi", "submitted": True,
                                   "lines": [{"item_id": M["item"]["id"], "qty": 4, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]}, 200)
    call("POST", f"mro/{mro['id']}/submit", {})
    sc, ro = call("POST", "ro", {"division_id": M["div"]["id"], "submitted": True,
                                 "lines": [{"item_id": M["item"]["id"], "qty": 4, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"],
                                            "sources": [{"mro_id": mro["id"], "line_id": mro["lines"][0]["id"], "qty": 4}]}]}, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    sc, pr = call("POST", "po", po_body(M, [line(M, 4, 250000, t04["id"], "EXCLUDE", project_id=M["pa"]["id"],
                                                 sources=[{"ro_id": ro["id"], "line_id": ro["lines"][0]["id"], "qty": 4}])]), 200)
    check("PO v2 dari RO: v2 + PPN DPP NL (1.000.000 x 11/12 x 12% = 110.000)", pr.get("tax_engine_version") == 2 and pr["grand_total"] == 1110000.0, (pr.get("tax_engine_version"), pr.get("grand_total")))
    sc, lc = call("GET", f"lifecycle/po/{pr['id']}")
    stg = {s["key"]: s for s in (lc or {}).get("stages") or []}
    check("Lifecycle PO v2 ber-sumber RO: 200 + tahap MRO/RO/PO terhubung (qty 4)", sc == 200 and stg.get("po", {}).get("qty") == 4 and stg.get("ro", {}).get("qty") == 4, (sc, lc))
    sc, lc1 = call("GET", f"lifecycle/po/{st['p1']}")
    check("Lifecycle PO langsung tanpa MRO: 404 'Sumber MRO' (perilaku main, bukan F2; UI menyembunyikan tracker)", sc == 404 and "Sumber MRO" in str(lc1), (sc, lc1))

    # ---------------------------------------------------------------- 12. isolasi divisi & tenant pada route PPN
    sc, divb = call("POST", "master/divisions", {"code": f"DVB{u}", "name": "Divisi Lain"}, 200)
    other_div = mk_user("manager", divs=[divb["id"]])
    same_div = mk_user("manager", divs=[M["div"]["id"]])
    pv_body = {**po_body(M, [line(M, 1, 1000, t04["id"], "EXCLUDE")]), "po_id": pa["id"]}
    sc, r = other_div("POST", "po/tax-preview", pv_body)
    check("Preview po_id PO divisi lain ditolak 403", sc == 403, (sc, r))
    sc, r = same_div("POST", "po/tax-preview", pv_body)
    check("Preview po_id PO divisi sendiri 200 (v2)", sc == 200 and r.get("tax_engine_version") == 2, (sc, r.get("detail")))
    import requests
    ut = uuid.uuid4().hex[:8]
    reg = requests.post(f"{T.API}/saas/register", json={"company_name": f"F2X {ut}", "pic_name": "QA", "email": f"f2x_{ut}@example.com",
                                                        "whatsapp": "+628123456789", "workspace_slug": f"f2x-{ut}", "plan_code": "starter",
                                                        "password": PW, "address": "x", "terms_accepted": True}).json()
    X = requests.Session()
    X.headers["Authorization"] = "Bearer " + (reg.get("token") or requests.post(f"{T.API}/auth/login", json={"email": f"f2x_{ut}@example.com", "password": PW}).json()["token"])
    r = X.post(f"{T.API}/po/tax-preview", json=pv_body)
    check("Preview po_id PO tenant lain -> 404 (tidak bocor)", r.status_code == 404, (r.status_code, r.text[:200]))
    ox = X.get(f"{T.API}/po/tax-options").json()
    check("tax-options tenant lain tidak memuat Master Pajak tenant ini", t04["id"] not in {o["id"] for o in ox.get("items") or []})
    rx = X.get(f"{T.API}/po/tax-readiness").json()
    check("tax-readiness tenant lain tidak memuat supplier tenant ini", M["supY"]["id"] not in {s["id"] for s in rx.get("non_pkp_suppliers") or []}
          and tinc["id"] not in {t["id"] for t in rx.get("incomplete_taxes") or []})


if __name__ == "__main__":
    {"phase_a": phase_a, "phase_b": phase_b}[sys.argv[1]]()
    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} PASS")
    sys.exit(1 if failed else 0)
