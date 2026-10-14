"""Tax Calculation Engine bersama (PPN) — F1: modul murni, BELUM dipasang ke alur transaksi mana pun.

Desain disepakati pemilik (audit PPN Tahap 1 + desain form PO revisi 3):
- `dpp` TETAP = nilai komersial tanpa PPN setelah diskon item + Diskon Final = dasar nilai perolehan
  (dibaca `resolve_do_acq_cost`). DPP Nilai Lain disimpan TERPISAH di `dpp_other`.
- Purchasing memilih per baris: mode harga (INCLUDE | EXCLUDE | NONE) + jenis transaksi PPN (master Accounting:
  tarif, faktor DPP Nilai Lain, KODE TRANSAKSI FAKTUR, fasilitas). Pengaturan lanjutan: fasilitas & PPnBM.
- Status PPN Masukan dapat/tidak dapat dikreditkan + perlakuan biaya = pengaturan Accounting (input, bukan pilihan Purchasing).
- Kode transaksi faktur WAJIB dari master (mengikuti ketentuan jenis transaksi) — tidak diturunkan dari tarif.
- Supplier Non-PKP: baris ber-PPN ditolak (koreksi status via Master Supplier).
- PO (compute_po): presisi Decimal per sen. Per baris berantai HALF_UP 2 desimal:
    DPP -> DPP Nilai Lain = DPP x faktor -> PPN = DPP NL x tarif ; PPnBM = DPP x tarif PPnBM ; Total = DPP + PPN + PPnBM.
  Tidak ada pembulatan rupiah di PO. Total dokumen = jumlah baris (identik dengan form & cetak).
- Invoice (compute_invoice): nilai barang yang ditagih (parsial / multi-DO; tagihan terakhir memakai sisa) lalu
  nilai Faktur Pajak per kelompok kode transaksi = jumlah baris dibulatkan ke rupiah penuh HALF_UP
  (PER-11/PJ/2025 Pasal 129 ayat 3) + rekonsiliasi faktur aktual (toleransi Rp1: WARNING, lebih = NEEDS_APPROVAL).
- Supplier DP: dengan/tanpa faktur uang muka; pelunasan = invoice - DP sehingga PPN tidak dihitung ganda.
- Versi mesin: dokumen tanpa `tax_engine_version` (atau 1) = v1 legacy (rumus `compute_po_totals`, dibekukan).
Semua nilai uang keluar sebagai `Decimal`; perhitungan antara rasional eksak (`Fraction`) agar identik dengan
mirror frontend `frontend/src/lib/taxEngine.js` (golden test bersama `backend/tests/fixtures/tax_engine_golden.json`).
"""
from __future__ import annotations

import re
from decimal import Decimal
from fractions import Fraction

TAX_ENGINE_VERSION = 2
LEGACY_ENGINE_VERSION = 1
MODES = ("INCLUDE", "EXCLUDE", "NONE")
FACILITIES = ("NORMAL", "TIDAK_DIPUNGUT", "DTP", "DIBEBASKAN")
COST_TREATMENTS = ("CAPITALIZE_TAX", "EXCLUDE_TAX")
ACQ_TYPES = ("INVENTORY", "ASSET", "SERVICE")
DEFAULT_TOLERANCE = Decimal("1")
_NUM_RE = re.compile(r"^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$")  # sama persis dengan mirror JS
ROUNDING_POLICY = {"po": "Decimal per sen (2 desimal) HALF_UP berantai; tanpa pembulatan rupiah",
                   "invoice_faktur": "jumlah baris per kode transaksi -> rupiah penuh HALF_UP (PER-11/PJ/2025 Ps.129(3))",
                   "final_discount": "prorata, sisa terbesar per sen"}


# ----------------------------------------------------------------------------- angka
def to_frac(v) -> Fraction:
    if v is None or v == "":
        return Fraction(0)
    if isinstance(v, bool):
        raise ValueError("angka tidak valid")
    if isinstance(v, (int, Fraction)):
        return Fraction(v)
    if isinstance(v, Decimal):
        return Fraction(v)
    s = repr(v) if isinstance(v, float) else str(v).strip()
    m = _NUM_RE.match(s)  # pemisah ribuan/koma desimal (mis. "1.000,50") DITOLAK, tidak ditebak
    if not m or (m.group(2) == "" and not m.group(3)):
        raise ValueError(f"angka tidak valid: {v!r}")
    frac = m.group(3) or ""
    exp = int(m.group(4) or "0") - len(frac)
    if abs(exp) > 40 or len(m.group(2)) + len(frac) > 40:  # batas wajar, sama dengan mirror JS
        raise ValueError(f"angka tidak valid: {v!r}")
    return Fraction(Decimal(s))


def round_units(x, scale: int) -> int:
    """ROUND_HALF_UP (setengah menjauhi nol) ke satuan 10^-scale; hasil integer satuan."""
    y = to_frac(x) * (10 ** scale)
    return int((y + Fraction(1, 2)).__floor__()) if y >= 0 else -int((-y + Fraction(1, 2)).__floor__())


def dec(units: int, scale: int) -> Decimal:
    return Decimal(units).scaleb(-scale).quantize(Decimal(1).scaleb(-scale))


def c2(x) -> int:  # -> sen
    return round_units(x, 2)


def allocate_units(raws, target: int, scale: int = 2) -> list[int]:
    """Bagi target (integer satuan) proporsional, sisa terbesar (seri -> indeks terkecil)."""
    n = len(raws)
    if not n:
        return []
    m = 10 ** scale
    base = [int((r * m).__floor__()) for r in raws]
    rem = [r * m - b for r, b in zip(raws, base)]
    diff = target - sum(base)
    order = sorted(range(n), key=lambda i: (-rem[i], i))
    k = 0
    while diff > 0:
        base[order[k % n]] += 1; diff -= 1; k += 1
    return base


# ----------------------------------------------------------------------------- aturan pajak (master Accounting)
def make_rule(code="PPN", name=None, rate=0, dpp_factor_num=1, dpp_factor_den=1, trx_code=None, facility="NORMAL") -> dict:
    r = to_frac(rate)
    num, den = int(dpp_factor_num), int(dpp_factor_den)
    if r < 0 or r > 100:
        raise ValueError("tarif pajak harus 0..100")
    if den <= 0 or num < 0:
        raise ValueError("faktor DPP Nilai Lain tidak valid")
    fac = str(facility or "NORMAL").upper()
    if fac not in FACILITIES:
        raise ValueError(f"fasilitas pajak tidak dikenal: {fac}")
    return {"code": str(code or "PPN"), "name": name or str(code or "PPN"),
            "rate": str(Decimal(r.numerator) / Decimal(r.denominator)), "dpp_factor_num": num, "dpp_factor_den": den,
            "trx_code": (str(trx_code) if trx_code not in (None, "") else None), "facility": fac}


def rule_from_master(tax: dict | None) -> dict | None:
    """Master `taxes` -> aturan. Master lama (hanya tarif) -> faktor 1/1, kode transaksi KOSONG (tidak ditebak)."""
    if not tax:
        return None
    return make_rule(code=tax.get("code") or tax.get("id") or "PPN", name=tax.get("name"), rate=tax.get("rate") or 0,
                     dpp_factor_num=tax.get("dpp_factor_num") or 1, dpp_factor_den=tax.get("dpp_factor_den") or 1,
                     trx_code=tax.get("coretax_trx_code") or tax.get("trx_code"), facility=tax.get("facility") or "NORMAL")


def snapshot_rule(rule: dict | None) -> dict:
    """Snapshot aturan untuk disimpan per baris (nilai historis tidak berubah bila master diubah)."""
    r = rule or {}
    return {"tax_code": r.get("code"), "tax_name": r.get("name"), "tax_rate": r.get("rate", "0"),
            "tax_dpp_factor_num": r.get("dpp_factor_num", 1), "tax_dpp_factor_den": r.get("dpp_factor_den", 1),
            "tax_trx_code": r.get("trx_code"), "tax_facility": r.get("facility", "NORMAL")}


def rule_from_line(line: dict) -> dict | None:
    if line.get("tax_rule"):
        return make_rule(**{k: v for k, v in line["tax_rule"].items() if k in ("code", "name", "rate", "dpp_factor_num", "dpp_factor_den", "trx_code", "facility")})
    if not line.get("tax_code"):
        return None
    return make_rule(code=line.get("tax_code"), name=line.get("tax_name"), rate=line.get("tax_rate") or 0,
                     dpp_factor_num=line.get("tax_dpp_factor_num") or 1, dpp_factor_den=line.get("tax_dpp_factor_den") or 1,
                     trx_code=line.get("tax_trx_code"), facility=line.get("tax_facility") or "NORMAL")


def _acct(line: dict) -> tuple[bool, str, str]:
    cred = line.get("input_vat_creditable")
    cred = True if cred is None else bool(cred)
    ct = str(line.get("cost_treatment") or "CAPITALIZE_TAX").upper()
    if ct not in COST_TREATMENTS:
        raise ValueError(f"perlakuan biaya tidak dikenal: {ct}")
    acq = str(line.get("acquisition_type") or "INVENTORY").upper()
    if acq not in ACQ_TYPES:
        raise ValueError(f"jenis perolehan tidak dikenal: {acq}")
    return cred, ct, acq


_GROUP_FIELDS = ("tax_trx_code", "tax_code", "tax_rate", "tax_dpp_factor_num", "tax_dpp_factor_den", "tax_facility")


def _group_key(line: dict) -> str:
    """Kunci kelompok faktur (None -> "" agar identik dengan mirror JS)."""
    return "|".join("" if line.get(k) is None else str(line[k]) for k in _GROUP_FIELDS)


def _rules_snapshot(groups: list[dict], lines: list[dict]) -> list[dict]:
    """Snapshot aturan pajak level dokumen (unik per kelompok, urut kemunculan) — disimpan saat integrasi (F2+)."""
    out = []
    for g in groups:
        l = lines[g["line_indexes"][0]]
        out.append({"group": g["group"], **{k: l.get(k) for k in ("tax_code", "tax_name", "tax_rate", "tax_dpp_factor_num",
                                                                   "tax_dpp_factor_den", "tax_trx_code", "tax_facility")}})
    return out


# ----------------------------------------------------------------------------- baris (rantai sen)
def _line_values(i: int, mode: str, net_c: int, rule: dict | None, ppnbm_rate) -> dict:
    """Nilai pajak satu baris dari nilai setelah diskon (sen). Berantai HALF_UP 2 desimal."""
    if mode == "NONE" or rule is None:
        return {"taxable": False, "billed": False, "dpp_c": net_c, "nl_c": 0, "ppn_c": 0, "bm_c": 0}
    rate = to_frac(rule["rate"]) / 100
    f = Fraction(rule["dpp_factor_num"], rule["dpp_factor_den"])
    bm = to_frac(ppnbm_rate) / 100
    billed = rule["facility"] == "NORMAL"
    if not rule.get("trx_code"):
        raise ValueError(f"baris {i + 1}: kode transaksi faktur wajib diisi di master jenis transaksi PPN")
    if not billed and mode == "INCLUDE":
        raise ValueError(f"baris {i + 1}: fasilitas PPN tidak dapat dikombinasikan dengan harga Include")
    if not billed and bm:
        raise ValueError(f"baris {i + 1}: PPnBM tidak berlaku untuk baris dengan fasilitas PPN")
    if bm < 0 or bm > 2:
        raise ValueError(f"baris {i + 1}: tarif PPnBM tidak valid")
    dpp_c = c2(Fraction(net_c, 100) / (1 + rate * f + bm)) if mode == "INCLUDE" else net_c
    nl_c = c2(Fraction(dpp_c, 100) * f)
    ppn_c = c2(Fraction(nl_c, 100) * rate)
    bm_c = c2(Fraction(dpp_c, 100) * bm)
    return {"taxable": True, "billed": billed, "dpp_c": dpp_c, "nl_c": nl_c, "ppn_c": ppn_c, "bm_c": bm_c}


def _finish_line(src: dict, i: int, mode: str, rule, qty: Fraction, gross_c, disc_c, fd_c, net_c, v: dict) -> dict:
    cred, ct, acq = _acct(src)
    tax_c = v["ppn_c"] if v["billed"] else 0
    fac_c = 0 if v["billed"] else v["ppn_c"]
    total_c = v["dpp_c"] + tax_c + v["bm_c"]
    cap = v["billed"] and not cred and ct == "CAPITALIZE_TAX"
    cost_c = v["dpp_c"] + v["bm_c"] + (tax_c if cap else 0)
    x = {k: val for k, val in src.items() if k != "tax_rule"}
    x.update(snapshot_rule(rule if v["taxable"] else None))
    x.update({"tax_mode": mode, "input_vat_creditable": cred, "cost_treatment": ct, "acquisition_type": acq,
              "gross": dec(gross_c, 2), "discount_amount": dec(disc_c, 2), "final_discount_share": dec(fd_c, 2),
              "net_amount": dec(net_c, 2), "dpp": dec(v["dpp_c"], 2), "dpp_other": dec(v["nl_c"], 2),
              "tax_amount": dec(tax_c, 2), "tax_facility_amount": dec(fac_c, 2), "ppnbm_amount": dec(v["bm_c"], 2),
              "total": dec(total_c, 2), "include_rounding_diff": dec(total_c - net_c if mode == "INCLUDE" else 0, 2),
              "cost_base": dec(cost_c, 2), "unit_cost": dec(round_units(Fraction(cost_c, 100) / qty, 6), 6) if qty else Decimal("0.000000"),
              "taxable": v["taxable"], "tax_engine_version": TAX_ENGINE_VERSION})
    return x


def _summarize(lines: list[dict]) -> tuple[dict, list[dict]]:
    Z = Decimal("0.00")
    s = lambda k, pred=None: sum((l[k] for l in lines if pred is None or pred(l)), Z)  # noqa: E731
    groups: dict[str, dict] = {}
    for idx, l in enumerate(lines):
        if not l["taxable"]:
            continue
        key = _group_key(l)
        g = groups.setdefault(key, {"group": key, "trx_code": l["tax_trx_code"], "tax_code": l["tax_code"], "tax_name": l.get("tax_name"),
                                    "facility": l["tax_facility"], "line_indexes": [], "dpp": Z, "dpp_other": Z, "ppn": Z, "ppn_facility": Z, "ppnbm": Z})
        g["line_indexes"].append(idx)
        g["dpp"] += l["dpp"]; g["dpp_other"] += l["dpp_other"]; g["ppn"] += l["tax_amount"]
        g["ppn_facility"] += l["tax_facility_amount"]; g["ppnbm"] += l["ppnbm_amount"]
    tax = lambda l: l["taxable"]  # noqa: E731
    totals = {"gross_total": s("gross"), "item_discount_total": s("discount_amount"), "final_discount_amount": s("final_discount_share"),
              "subtotal_after_discount": s("net_amount"), "dpp_total": s("dpp", tax), "non_ppn_total": s("total", lambda l: not l["taxable"]),
              "dpp_other_total": s("dpp_other"), "tax_total": s("tax_amount"), "ppnbm_total": s("ppnbm_amount"),
              "tax_facility_total": s("tax_facility_amount"), "grand_total": s("total"), "cost_base_total": s("cost_base"),
              "cost_by_type": {t: s("cost_base", lambda l, t=t: l["acquisition_type"] == t) for t in ACQ_TYPES},
              "input_vat_creditable_total": s("tax_amount", lambda l: l["input_vat_creditable"]),
              "input_vat_non_creditable_total": s("tax_amount", lambda l: not l["input_vat_creditable"])}
    totals["subtotal_after_item_discount"] = totals["gross_total"] - totals["item_discount_total"]
    return totals, list(groups.values())


def _check_pkp(header: dict, mode: str, i: int):
    if header.get("supplier_pkp") is False and mode != "NONE":
        raise ValueError(f"baris {i + 1}: supplier Non-PKP tidak boleh dikenakan PPN (koreksi status di Master Supplier)")


# ----------------------------------------------------------------------------- PO (v2)
def compute_po(header: dict, lines: list[dict]) -> dict:
    work = []
    for i, l in enumerate(lines):
        mode = str(l.get("tax_mode") or "EXCLUDE").upper()
        if mode not in MODES:
            raise ValueError(f"baris {i + 1}: mode pajak tidak dikenal {mode}")
        _check_pkp(header, mode, i)
        qty, price = to_frac(l.get("qty")), to_frac(l.get("price"))
        if qty < 0 or price < 0:
            raise ValueError(f"baris {i + 1}: qty/harga tidak boleh negatif")
        gross_c = c2(qty * price)
        disc_c = c2(Fraction(gross_c, 100) * to_frac(l.get("discount_percent")) / 100) if l.get("discount_percent") not in (None, "") else c2(l.get("discount"))
        disc_c = max(0, min(gross_c, disc_c))
        work.append((l, i, mode, qty, gross_c, disc_c, gross_c - disc_c))
    sub_c = sum(w[6] for w in work)
    fv = to_frac(header.get("final_discount_value"))
    if fv <= 0 or sub_c <= 0:
        fd_c = 0
    elif str(header.get("final_discount_type") or "").lower() in ("percent", "%", "persen", "pct"):
        fd_c = min(sub_c, c2(Fraction(sub_c, 100) * fv / 100))
    else:
        fd_c = min(sub_c, c2(fv))
    shares = allocate_units([Fraction(w[6], 100) * Fraction(fd_c, sub_c) for w in work], fd_c) if fd_c else [0] * len(work)
    out = []
    for (l, i, mode, qty, gross_c, disc_c, net0_c), fd in zip(work, shares):
        rule = None if mode == "NONE" else rule_from_line(l)
        if mode != "NONE" and rule is None:
            raise ValueError(f"baris {i + 1}: jenis transaksi PPN wajib dipilih")
        net_c = net0_c - fd
        out.append(_finish_line(l, i, mode, rule, qty, gross_c, disc_c, fd, net_c, _line_values(i, mode, net_c, rule, l.get("ppnbm_rate"))))
    totals, groups = _summarize(out)
    totals["final_discount_type"] = header.get("final_discount_type") or None
    return {"tax_engine_version": TAX_ENGINE_VERSION, "rounding_policy": dict(ROUNDING_POLICY), "lines": out, "totals": totals,
            "tax_groups": groups, "tax_rules_snapshot": _rules_snapshot(groups, out)}


# ----------------------------------------------------------------------------- Invoice (tagihan + faktur)
def compute_invoice(po_result: dict, billed: list[dict], faktur_actual: dict | None = None, tolerance=DEFAULT_TOLERANCE) -> dict:
    """billed: [{line_index, qty, prev_qty?, prev_net?}] — satu invoice bisa banyak DO / parsial.
    prev_qty/prev_net = kumulatif yang sudah ditagih di invoice SEBELUMNYA. Entri berulang untuk baris PO yang sama
    (multi-DO dalam satu invoice) diakumulasi otomatis; prev entri berikutnya harus kosong atau sama dengan entri pertama.
    Net ditagih = net PO x qty/qty PO (sen HALF_UP); bila kumulatif = qty PO -> sisa (tanpa drift)."""
    out = []
    seen: dict[int, list] = {}  # line_index -> [prev_q, prev_n, q_in_call, n_in_call]
    for i, b in enumerate(billed):
        li = int(b["line_index"])
        if li < 0 or li >= len(po_result["lines"]):
            raise ValueError(f"baris tagihan {i + 1}: baris PO tidak ditemukan")
        pl = po_result["lines"][li]
        qty_po, qty = to_frac(pl["qty"]), to_frac(b.get("qty"))
        prev_q, prev_n = to_frac(b.get("prev_qty")), to_frac(b.get("prev_net"))
        if li in seen:
            st = seen[li]
            if (b.get("prev_qty") not in (None, "") and prev_q != st[0]) or (b.get("prev_net") not in (None, "") and prev_n != st[1]):
                raise ValueError(f"baris tagihan {i + 1}: prev_qty/prev_net tidak konsisten untuk baris PO yang sama")
            prev_q, prev_n = st[0] + st[2], st[1] + st[3]
        else:
            st = seen[li] = [prev_q, prev_n, Fraction(0), Fraction(0)]
        if qty <= 0 or prev_q + qty > qty_po:
            raise ValueError("qty ditagih tidak valid / melebihi qty PO")
        net_po = to_frac(pl["net_amount"])
        net_c = c2(net_po - prev_n) if prev_q + qty == qty_po else c2(net_po * qty / qty_po)
        st[2] += qty; st[3] += Fraction(net_c, 100)
        rule = rule_from_line(pl) if pl["taxable"] else None
        mode = pl["tax_mode"]
        src = {"po_line_index": li, "qty": str(b.get("qty")), "input_vat_creditable": pl["input_vat_creditable"],
               "cost_treatment": pl["cost_treatment"], "acquisition_type": pl["acquisition_type"]}
        if pl.get("ppnbm_rate") is not None:
            src["ppnbm_rate"] = pl["ppnbm_rate"]
        v = _line_values(i, mode, net_c, rule, pl.get("ppnbm_rate") if rule else 0)
        x = _finish_line(src, i, mode, rule, qty, net_c, 0, 0, net_c, v)
        out.append(x)
    totals, groups = _summarize(out)
    faktur = []
    for g in groups:
        R = lambda d: dec(round_units(d, 0), 0)  # noqa: E731
        faktur.append({"trx_code": g["trx_code"], "tax_code": g["tax_code"], "facility": g["facility"], "line_indexes": g["line_indexes"],
                       "dpp": R(g["dpp"]), "dpp_other": R(g["dpp_other"]), "ppn": R(g["ppn"]), "ppn_facility": R(g["ppn_facility"]), "ppnbm": R(g["ppnbm"])})
    f_ppn = sum((f["ppn"] for f in faktur), Decimal(0))
    f_bm = sum((f["ppnbm"] for f in faktur), Decimal(0))
    payable = (totals["dpp_total"] + totals["non_ppn_total"] + f_ppn + f_bm).quantize(Decimal("0.01"))
    res = {"tax_engine_version": TAX_ENGINE_VERSION, "rounding_policy": dict(ROUNDING_POLICY), "lines": out, "totals": totals,
           "tax_groups": groups, "tax_rules_snapshot": _rules_snapshot(groups, out), "faktur": faktur,
           "faktur_totals": {"dpp": sum((f["dpp"] for f in faktur), Decimal(0)), "dpp_other": sum((f["dpp_other"] for f in faktur), Decimal(0)),
                             "ppn": f_ppn, "ppnbm": f_bm, "ppn_facility": sum((f["ppn_facility"] for f in faktur), Decimal(0))},
           "expected_payable": payable, "rounding_adjustment": payable - totals["grand_total"]}
    if faktur_actual is not None:
        res["faktur_match"] = match_faktur(res["faktur_totals"], faktur_actual, tolerance)
    return res


# ----------------------------------------------------------------------------- Supplier DP
def compute_dp(amount, rule: dict | None, with_faktur: bool) -> dict:
    """DP bruto (termasuk PPN). Dengan faktur uang muka: DPP/PPN DP dihitung (faktur rupiah HALF_UP)."""
    amt_c = c2(amount)
    if not with_faktur or rule is None:
        return {"with_faktur": False, "amount": dec(amt_c, 2), "dpp": None, "dpp_other": None, "ppn": dec(0, 0)}
    v = _line_values(0, "INCLUDE", amt_c, rule, 0)
    R = lambda c: dec(round_units(Fraction(c, 100), 0), 0)  # noqa: E731
    return {"with_faktur": True, "amount": dec(amt_c, 2), "dpp": R(v["dpp_c"]), "dpp_other": R(v["nl_c"]), "ppn": R(v["ppn_c"])}


def settle_with_dp(invoice: dict, dps: list[dict]) -> dict:
    """Pelunasan: faktur pelunasan = faktur invoice - faktur DP; PPN diakui total == PPN invoice (tidak ganda)."""
    ft = invoice["faktur_totals"]
    total = to_frac(invoice["expected_payable"])
    dp_amt = sum((to_frac(d["amount"]) for d in dps), Fraction(0))
    wf = [d for d in dps if d.get("with_faktur")]
    dp_dpp = sum((to_frac(d["dpp"]) for d in wf), Fraction(0))
    dp_nl = sum((to_frac(d["dpp_other"]) for d in wf), Fraction(0))
    dp_ppn = sum((to_frac(d["ppn"]) for d in wf), Fraction(0))
    if dp_amt > total:
        raise ValueError("DP melebihi nilai invoice")
    if dp_ppn > to_frac(ft["ppn"]):
        raise ValueError("PPN DP melebihi PPN invoice")
    fin = to_frac(ft["ppn"]) - dp_ppn
    q = lambda x: dec(c2(x), 2)  # noqa: E731
    return {"invoice_total": q(total), "dp_amount": q(dp_amt), "payable": q(total - dp_amt),
            "final_faktur": {"dpp": q(to_frac(ft["dpp"]) - dp_dpp), "dpp_other": q(to_frac(ft["dpp_other"]) - dp_nl), "ppn": q(fin)},
            "dp_ppn": q(dp_ppn), "ppn_recognized_total": q(dp_ppn + fin), "invoice_ppn": q(to_frac(ft["ppn"])),
            "double_counted": (dp_ppn + fin) != to_frac(ft["ppn"])}


def match_faktur(expected: dict, faktur: dict, tolerance=DEFAULT_TOLERANCE) -> dict:
    """0 = MATCH; <= toleransi (Rp1) = WARNING; > toleransi = NEEDS_APPROVAL (wajib alasan + persetujuan)."""
    tol = to_frac(tolerance)
    diffs, worst = {}, Fraction(0)
    for k in ("dpp", "dpp_other", "ppn", "ppnbm", "total"):
        if expected.get(k) is None or faktur.get(k) is None:
            continue
        d = to_frac(faktur[k]) - to_frac(expected[k])
        diffs[k] = dec(c2(d), 2)
        worst = max(worst, abs(d))
    st = "MATCH" if worst == 0 else ("WARNING" if worst <= tol else "NEEDS_APPROVAL")
    return {"status": st, "max_abs_diff": dec(c2(worst), 2), "diffs": diffs, "tolerance": dec(c2(tol), 2), "requires_reason": st == "NEEDS_APPROVAL"}


# ----------------------------------------------------------------------------- v1 legacy (DIBEKUKAN)
def compute_v1(header: dict, lines: list[dict]):
    """Salinan beku `doc_procurement.compute_po_totals` (float) untuk dokumen historis. JANGAN diubah —
    `tests/tax_engine_test.py` memastikan identik dengan implementasi produksi."""
    def fd_amount(sub, ftype, fvalue):
        fv = float(fvalue or 0); base = max(0.0, float(sub or 0))
        if fv <= 0 or base <= 0:
            return 0.0
        if str(ftype or "").lower() in ("percent", "%", "persen", "pct"):
            return min(base, base * fv / 100.0)
        return min(base, fv)
    inclusive = bool(header.get("tax_inclusive"))
    nets = []; gross_total = 0.0; item_disc_total = 0.0
    for l in lines:
        qty = float(l.get("qty") or 0); price = float(l.get("price") or 0); disc = float(l.get("discount") or 0)
        gross = qty * price; net = max(0.0, gross - disc)
        gross_total += gross; item_disc_total += disc; nets.append(net)
    sub = sum(nets)
    fd = fd_amount(sub, header.get("final_discount_type"), header.get("final_discount_value"))
    factor = ((sub - fd) / sub) if sub > 0 else 1.0
    out = []; grand = 0.0; tax_total = 0.0; sub_final = 0.0
    for l, net in zip(lines, nets):
        rate = float(l.get("tax") or 0); net_final = net * factor
        if inclusive and rate:
            dpp = net_final / (1 + rate / 100.0); tax_amount = net_final - dpp; total = net_final
        else:
            dpp = net_final; tax_amount = dpp * rate / 100.0; total = dpp + tax_amount
        sub_final += net_final; tax_total += tax_amount; grand += total
        x = dict(l)
        x["gross"] = float(l.get("qty") or 0) * float(l.get("price") or 0)
        x["dpp"] = dpp; x["tax_amount"] = tax_amount; x["total"] = total; x["tax_inclusive"] = inclusive
        out.append(x)
    totals = {"gross_total": gross_total, "item_discount_total": item_disc_total, "subtotal_after_item_discount": sub,
              "final_discount_type": (header.get("final_discount_type") or None),
              "final_discount_value": float(header.get("final_discount_value") or 0),
              "final_discount_amount": fd, "subtotal_after_discount": sub_final, "tax_total": tax_total, "grand_total": grand}
    return out, totals


def engine_version_of(doc: dict | None) -> int:
    try:
        v = int((doc or {}).get("tax_engine_version") or LEGACY_ENGINE_VERSION)
    except (TypeError, ValueError):
        return LEGACY_ENGINE_VERSION
    return v if v == TAX_ENGINE_VERSION else LEGACY_ENGINE_VERSION


def compute_document(header: dict, lines: list[dict]):
    """Pilih mesin dari versi yang TERSIMPAN di dokumen (bukan versi kode) -> nilai historis stabil."""
    return compute_po(header, lines) if engine_version_of(header) == TAX_ENGINE_VERSION else compute_v1(header, lines)
