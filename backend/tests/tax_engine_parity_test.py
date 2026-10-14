"""Parity Tax Engine: backend (sumber kebenaran) vs mirror frontend + kesetaraan v1 legacy. Modul murni, tanpa DB/API.
Jalankan: python3 backend/tests/tax_engine_parity_test.py   (butuh `node`)
1. Seluruh kasus golden: output Python == output JS, SEMUA field (bukan hanya yang di-expect).
2. Fuzz deterministik (seed tetap) PO/Invoice/DP/match acak, termasuk kasus invalid: hasil & status error identik.
3. compute_v1 (salinan beku) identik dengan doc_procurement.compute_po_totals produksi (diekstrak via AST, tanpa import server/DB).
"""
import ast
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
import tax_engine as TE  # noqa: E402
import tax_engine_golden_test as G  # noqa: E402

JS_TEST = os.path.join(ROOT, "frontend", "src", "lib", "taxEngine.test.mjs")
fail = 0


def check(name, cond, info=""):
    global fail
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond or not info else ' — ' + str(info)[:600]}")
    if not cond:
        fail += 1


def js_compute(fx):
    with tempfile.TemporaryDirectory() as d:
        i, o = os.path.join(d, "in.json"), os.path.join(d, "out.json")
        json.dump(fx, open(i, "w"))
        p = subprocess.run(["node", JS_TEST, "--cases", i, "--out", o], capture_output=True, text=True, timeout=120)
        if p.returncode:
            raise RuntimeError(p.stderr[-2000:])
        return json.load(open(o))


def first_diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: hanya di {'py' if k in a else 'js'}"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: panjang {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if type(a) is not type(b) or a != b:
        return f"{path}: py={a!r} js={b!r}"
    return None


def compare(label, fx):
    py, js = G.compute_all(fx), js_compute(fx)
    check(f"{label}: jumlah kasus sama ({len(py)})", set(py) == set(js), set(py) ^ set(js))
    bad = []
    for k in py:
        a, b = py[k], js.get(k)
        if isinstance(a, dict) and a.get("__error__"):
            if not (isinstance(b, dict) and b.get("__error__")):
                bad.append(f"{k}: py error ({a['message']}) js tidak")
            continue
        if isinstance(b, dict) and b.get("__error__"):
            bad.append(f"{k}: js error ({b['message']}) py tidak")
            continue
        d = first_diff(a, b)
        if d:
            bad.append(f"{k}{d}")
    check(f"{label}: output Python == JS untuk seluruh field", not bad, "; ".join(bad[:5]))
    return py


# ----------------------------------------------------------------------------- fuzz
RULES = {"U04": {"code": "PPN-04", "name": "PPN DPP Nilai Lain", "rate": "12", "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "04"},
         "P01": {"code": "PPN-01", "name": "PPN 12% penuh", "rate": "12", "dpp_factor_num": 1, "dpp_factor_den": 1, "trx_code": "01"},
         "BT05": {"code": "PPN-05", "name": "Besaran tertentu", "rate": "12", "dpp_factor_num": 1, "dpp_factor_den": 10, "trx_code": "05"},
         "R11": {"code": "PPN-11K", "name": "Khusus 11%", "rate": "11", "dpp_factor_num": 1, "dpp_factor_den": 1, "trx_code": "01"},
         "TD07": {"code": "PPN-07TD", "rate": "12", "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "07", "facility": "TIDAK_DIPUNGUT"},
         "DTP07": {"code": "PPN-07DTP", "rate": "12", "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "07", "facility": "DTP"},
         "BB08": {"code": "PPN-08", "rate": "12", "dpp_factor_num": 11, "dpp_factor_den": 12, "trx_code": "08", "facility": "DIBEBASKAN"},
         "NOCODE": {"code": "PPN-X", "rate": "12", "dpp_factor_num": 11, "dpp_factor_den": 12}}
FAC = {"TD07", "DTP07", "BB08"}


def money(rng):
    return rng.choice([f"{rng.randint(0, 99999999)}", f"{rng.randint(0, 999999)}.{rng.randint(0, 99):02d}", f"{rng.randint(1, 999)}.{rng.randint(0, 9999):04d}",
                       "33333", "1005", "0.5", "1.5", "150"])


def gen_line(rng, invalid_ok):
    mode = rng.choice(["EXCLUDE", "EXCLUDE", "INCLUDE", "NONE"])
    rule = rng.choice(["U04", "U04", "P01", "BT05", "R11", "TD07", "DTP07", "BB08"] + (["NOCODE"] if invalid_ok else []))
    if not invalid_ok and rule in FAC and mode == "INCLUDE":
        mode = "EXCLUDE"
    l = {"qty": rng.choice([str(rng.randint(1, 50)), f"{rng.randint(0, 20)}.{rng.randint(1, 999):03d}", "3", "1"]), "price": money(rng), "tax_mode": mode}
    if mode != "NONE" or rng.random() < 0.3:
        l["rule"] = rule
    r = rng.random()
    if r < 0.25:
        l["discount"] = str(rng.randint(0, 50000))
    elif r < 0.45:
        l["discount_percent"] = rng.choice(["5", "10", "12.5", "33.333", "100", "0"])
    if rule == "P01" and rng.random() < 0.4 and (invalid_ok or True):
        l["ppnbm_rate"] = rng.choice(["10", "15", "20", "40"])
    if invalid_ok and rng.random() < 0.05:
        l["ppnbm_rate"] = "10"
    if rng.random() < 0.3:
        l["input_vat_creditable"] = rng.choice([True, False])
    if rng.random() < 0.3:
        l["cost_treatment"] = rng.choice(["CAPITALIZE_TAX", "EXCLUDE_TAX"])
    l["acquisition_type"] = rng.choice(["INVENTORY", "ASSET", "SERVICE"])
    return l


def gen_fixture(seed, n_po=250):
    rng = random.Random(seed)
    po_cases, inv_cases, dp_cases, match_cases = [], [], [], []
    for k in range(n_po):
        invalid_ok = rng.random() < 0.15
        hdr = {}
        r = rng.random()
        if r < 0.3:
            hdr = {"final_discount_type": "percent", "final_discount_value": rng.choice(["5", "2.5", "10", "33.33", "100", "150"])}
        elif r < 0.5:
            hdr = {"final_discount_type": "amount", "final_discount_value": rng.choice(["1", "100", "12345.67", "999999999"])}
        if invalid_ok and rng.random() < 0.3:
            hdr["supplier_pkp"] = False
        lines = [gen_line(rng, invalid_ok) for _ in range(rng.randint(1, 7))]
        cid = f"F{k}"
        po_cases.append({"id": cid, "header": hdr, "lines": lines})
        # invoice: tagihan parsial/multi-DO acak
        billed = []
        for i, l in enumerate(lines):
            if rng.random() < 0.7:
                q = rng.choice([l["qty"], "1"])
                billed.append({"line_index": i, "qty": q})
                if rng.random() < 0.3:
                    billed.append({"line_index": i, "qty": "1"})  # DO kedua baris sama (bisa melebihi -> error di kedua sisi)
        if billed:
            fa = rng.choice([None, {"ppn": str(rng.randint(0, 999999))}, {"dpp": "1000", "ppn": "1"}])
            inv_cases.append({"id": f"I{cid}", "po": cid, "billed": billed, "faktur_actual": fa})
        if rng.random() < 0.3:
            dp_cases.append({"id": f"D{cid}", "po": cid, "dps": [{"amount": money(rng), "rule": rng.choice(["U04", "P01", "R11"]), "with_faktur": rng.random() < 0.6}
                                                                 for _ in range(rng.randint(1, 3))]})
    for k in range(60):
        e = {"ppn": str(rng.randint(0, 200000)), "dpp": str(rng.randint(0, 2000000))}
        f = {key: str(int(v) + rng.choice([0, 0, 1, -1, 2, 1000])) for key, v in e.items()}
        match_cases.append({"id": f"M{k}", "expected": e, "faktur": f, "tolerance": rng.choice(["1", "0", "0.5"])})
    return {"rules": RULES, "rule_cases": [], "po_cases": po_cases, "invoice_cases": inv_cases, "dp_cases": dp_cases, "match_cases": match_cases}


# ----------------------------------------------------------------------------- v1 legacy
def load_prod_v1():
    src = open(os.path.join(BACKEND, "doc_procurement.py")).read()
    mod = ast.parse(src)
    want = {"_po_final_discount_amount", "_compute_po_totals_v1"}  # F2: compute_po_totals = dispatcher versi
    nodes = [n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name in want]
    ns = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "doc_procurement.py", "exec"), ns)  # noqa: S102
    return ns["_compute_po_totals_v1"]


def v1_checks():
    prod = load_prod_v1()
    rng = random.Random(7)
    same = True
    first = None
    for k in range(400):
        hdr = {"tax_inclusive": rng.random() < 0.4}
        if rng.random() < 0.5:
            hdr.update({"final_discount_type": rng.choice(["percent", "amount", "%"]), "final_discount_value": rng.choice([5, 2.5, 100, 12345.67, 0])})
        lines = [{"qty": rng.choice([1, 3, 2.5, 10]), "price": rng.choice([33333, 1005, 100000, 1.5, 267900000]),
                  "discount": rng.choice([0, 0, 500, 12.34]), "tax": rng.choice([0, 11, 12])} for _ in range(rng.randint(1, 5))]
        a, b = prod(hdr, [dict(x) for x in lines]), TE.compute_v1(hdr, [dict(x) for x in lines])
        if a != b:
            same, first = False, (hdr, lines)
            break
    check("v1 legacy: compute_v1 identik dengan _compute_po_totals_v1 produksi (400 kasus acak)", same, first)
    check("v1 legacy: compute_document tanpa versi -> v1 (dokumen historis stabil)",
          TE.compute_document({"tax_inclusive": False}, [{"qty": 1, "price": 100, "tax": 11}]) == prod({"tax_inclusive": False}, [{"qty": 1, "price": 100, "tax": 11}]))
    r = TE.compute_document({"tax_engine_version": 2}, [{"qty": "1", "price": "100", "tax_mode": "NONE"}])
    check("v2: compute_document versi 2 -> mesin v2", isinstance(r, dict) and r["tax_engine_version"] == 2)


if __name__ == "__main__":
    fx = json.load(open(G.FIXTURE))
    compare("golden", fx)
    for seed in (1, 2, 3):
        ffx = gen_fixture(seed)
        py = compare(f"fuzz seed={seed}", ffx)
        n_err = sum(1 for v in py.values() if isinstance(v, dict) and v.get("__error__"))
        check(f"fuzz seed={seed}: mencakup kasus valid & invalid (error={n_err}/{len(py)})", 0 < n_err < len(py) / 2)
    v1_checks()
    print(f"\n{fail} FAILED" if fail else "\nALL PASSED")
    sys.exit(1 if fail else 0)
