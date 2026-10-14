"""Golden test Tax Engine v2 (backend) — fixture BERSAMA dengan frontend: backend/tests/fixtures/tax_engine_golden.json.
Modul murni: tanpa DB/API/server. Jalankan: python3 backend/tests/tax_engine_golden_test.py
  --dump <file>  : tulis seluruh output (dinormalisasi) per kasus, dipakai tax_engine_parity_test.py."""
import json
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tax_engine as TE  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "tax_engine_golden.json")
fail = 0


def check(name, cond, info=""):
    global fail
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond or not info else ' — ' + str(info)}")
    if not cond:
        fail += 1


def norm(v):
    """Decimal -> string (skala dipertahankan), rekursif — format sama dengan mirror JS."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    return v


def subset_diff(exp, act, path=""):
    """Hanya field yang dicantumkan di expected dibandingkan; list wajib sama panjang. Tipe ketat (str/int/bool/None)."""
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return [f"{path}: bukan objek ({act!r})"]
        out = []
        for k, v in exp.items():
            if k not in act:
                out.append(f"{path}.{k}: tidak ada")
            else:
                out += subset_diff(v, act[k], f"{path}.{k}")
        return out
    if isinstance(exp, list):
        if not isinstance(act, list) or len(exp) != len(act):
            return [f"{path}: panjang list {len(exp)} != {len(act) if isinstance(act, list) else act!r}"]
        out = []
        for i, (e, a) in enumerate(zip(exp, act)):
            out += subset_diff(e, a, f"{path}[{i}]")
        return out
    if type(exp) is not type(act) or exp != act:
        return [f"{path}: expected {exp!r} got {act!r}"]
    return []


def prep_lines(fx, lines):
    out = []
    for l in lines:
        x = {k: v for k, v in l.items() if k != "rule"}
        if l.get("rule"):
            x["tax_rule"] = fx["rules"][l["rule"]]
        out.append(x)
    return out


def run_po(fx, c):
    return TE.compute_po(c.get("header") or {}, prep_lines(fx, c["lines"]))


def po_of(fx, c):
    if c.get("po_inline"):
        return run_po(fx, c["po_inline"])
    return run_po(fx, next(p for p in fx["po_cases"] if p["id"] == c["po"]))


def rule_of(fx, name):
    return TE.make_rule(**fx["rules"][name]) if name else None


def attempt(fn):
    try:
        return norm(fn())
    except ValueError as e:
        return {"__error__": True, "message": str(e)}


def compute_all(fx):
    """Satu output per kasus (dipakai golden & parity). Format identik dengan computeAll() di taxEngine.test.mjs."""
    res = {}
    for c in fx.get("rule_cases", []):
        res["rule:" + c["id"]] = attempt(lambda c=c: TE.rule_from_master(c["master"]))
    for c in fx.get("po_cases", []):
        res["po:" + c["id"]] = attempt(lambda c=c: run_po(fx, c))
    for c in fx.get("invoice_cases", []):
        if c.get("sequence"):
            for k, step in enumerate(c["sequence"]):
                res[f"inv:{c['id']}#{k}"] = attempt(lambda c=c, step=step: TE.compute_invoice(po_of(fx, c), step["billed"], step.get("faktur_actual")))
        else:
            res["inv:" + c["id"]] = attempt(lambda c=c: TE.compute_invoice(po_of(fx, c), c["billed"], c.get("faktur_actual")))
    for c in fx.get("dp_cases", []):
        def dp_run(c=c):
            inv = TE.compute_invoice(po_of(fx, c), [{"line_index": i, "qty": l["qty"]} for i, l in enumerate(po_of(fx, c)["lines"])])
            dps = [TE.compute_dp(d["amount"], rule_of(fx, d.get("rule")), d.get("with_faktur")) for d in c["dps"]]
            return {"dps": dps, "settle": TE.settle_with_dp(inv, dps)}
        res["dp:" + c["id"]] = attempt(dp_run)
    for c in fx.get("match_cases", []):
        res["match:" + c["id"]] = attempt(lambda c=c: TE.match_faktur(c["expected"], c["faktur"], c.get("tolerance", "1")))
    return res


def verify(fx, res):
    def one(key, c, exp):
        r = res[key]
        if c.get("error"):
            check(f"{key} {c.get('title', '')} -> ditolak", isinstance(r, dict) and r.get("__error__") is True, r)
            return
        if isinstance(r, dict) and r.get("__error__"):
            check(f"{key} {c.get('title', '')}", False, r["message"])
            return
        d = subset_diff(exp, r)
        check(f"{key} {c.get('title', '')}", not d, "; ".join(d[:6]))

    for c in fx["rule_cases"]:
        one("rule:" + c["id"], c, c.get("expect"))
    for c in fx["po_cases"]:
        one("po:" + c["id"], c, c.get("expect"))
    for c in fx["invoice_cases"]:
        if c.get("sequence"):
            for k, step in enumerate(c["sequence"]):
                one(f"inv:{c['id']}#{k}", step, step.get("expect"))
        else:
            one("inv:" + c["id"], c, c.get("expect"))
    for c in fx["dp_cases"]:
        exp = None if c.get("error") else {"dps": c["expect_dps"], "settle": c["expect"]}
        one("dp:" + c["id"], c, exp)
    for c in fx["match_cases"]:
        one("match:" + c["id"], c, c.get("expect"))


def invariants(fx, res):
    """Invarian lintas kasus (bukan angka spesifik)."""
    Z = Decimal(0)
    for k, r in res.items():
        if not k.startswith("po:") or r.get("__error__"):
            continue
        t = r["totals"]
        D = lambda s: Decimal(s)  # noqa: E731
        ok = all(D(l["total"]) == D(l["dpp"]) + D(l["tax_amount"]) + D(l["ppnbm_amount"]) for l in r["lines"])
        check(f"{k} invarian: total baris = dpp + PPN + PPnBM", ok)
        check(f"{k} invarian: grand_total = jumlah total baris (form = cetak)", D(t["grand_total"]) == sum((D(l["total"]) for l in r["lines"]), Z))
        check(f"{k} invarian: dpp = net setelah diskon (Exclude/Tanpa PPN) — fungsi dpp existing tetap",
              all(l["dpp"] == l["net_amount"] for l in r["lines"] if l["tax_mode"] != "INCLUDE"))
        check(f"{k} invarian: rounding_policy & versi mesin ada", r["tax_engine_version"] == TE.TAX_ENGINE_VERSION and r["rounding_policy"] == TE.ROUNDING_POLICY)
        check(f"{k} invarian: grand_total = DPP + non-PPN + PPN + PPnBM",
              D(t["grand_total"]) == D(t["dpp_total"]) + D(t["non_ppn_total"]) + D(t["tax_total"]) + D(t["ppnbm_total"]))
        check(f"{k} invarian: biaya per jenis = total biaya", sum((D(v) for v in t["cost_by_type"].values()), Z) == D(t["cost_base_total"]))
        check(f"{k} invarian: snapshot aturan = kelompok pajak", [s["group"] for s in r["tax_rules_snapshot"]] == [g["group"] for g in r["tax_groups"]])


def unit_checks():
    R = TE.round_units
    check("HALF_UP 0,005 -> 0,01 (bukan half-even)", R("0.005", 2) == 1 and R("0.015", 2) == 2 and R("0.025", 2) == 3)
    check("HALF_UP negatif simetris (-0,005 -> -0,01)", R("-0.005", 2) == -1 and R("-2.5", 0) == -3 and R("-2.4", 0) == -2)
    check("Rupiah HALF_UP 33.962,50 -> 33.963 ; 16,49 -> 16", R("33962.50", 0) == 33963 and R("16.49", 0) == 16)
    check("Float tidak menyusup: 0.1 + 0.2 dihitung eksak", TE.to_frac(0.1) + TE.to_frac(0.2) == TE.to_frac("0.3"))
    for bad in ("1.000,50", "1,5", "abc", "", "1_000", "NaN", "Infinity", "1e999999", "-", "."):
        if bad == "":
            check("String kosong = 0", TE.to_frac(bad) == 0)
            continue
        try:
            TE.to_frac(bad); ok = False
        except ValueError:
            ok = True
        check(f"Input angka tidak valid ditolak: {bad!r}", ok)
    check("engine_version_of: tanpa versi = v1 legacy", TE.engine_version_of({}) == 1 and TE.engine_version_of({"tax_engine_version": "x"}) == 1)
    check("engine_version_of: v2", TE.engine_version_of({"tax_engine_version": 2}) == 2)
    # snapshot historis: mengubah master setelah hitung tidak mengubah hasil tersimpan
    rule = {"code": "PPN-04", "rate": "12", "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "04"}
    r1 = TE.compute_po({}, [{"qty": "1", "price": "1000000", "tax_mode": "EXCLUDE", "tax_rule": rule}])
    saved = r1["lines"][0]
    rule["rate"] = "15"  # master berubah
    r2 = TE.compute_po({}, [{k: v for k, v in saved.items()}])  # hitung ulang dari snapshot baris tersimpan
    check("Snapshot baris: hitung ulang dari snapshot = nilai historis", r2["lines"][0]["tax_amount"] == saved["tax_amount"] == Decimal("110000.00"))
    check("Input tidak dimutasi (tax_rule tidak bocor ke output)", "tax_rule" not in saved)


if __name__ == "__main__":
    fx = json.load(open(FIXTURE))
    res = compute_all(fx)
    if "--dump" in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index("--dump") + 1], "w"), indent=1, sort_keys=True)
    verify(fx, res)
    invariants(fx, res)
    unit_checks()
    print(f"\n{fail} FAILED" if fail else "\nALL PASSED")
    sys.exit(1 if fail else 0)
