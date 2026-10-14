"""F2 — Integrasi Tax Engine (F1, `tax_engine.py`) ke Purchase Order.

Prinsip:
- Versi ditentukan dokumen TERSIMPAN: PO lama (tanpa `tax_engine_version`) tetap v1 (`_compute_po_totals_v1`, tidak
  diubah). PO baru = v2. Klien tidak dapat mengganti versi.
- Backend = sumber perhitungan resmi. Aturan pajak di-resolve di sini dari Master Pajak (aktif + lengkap + berlaku pada
  tanggal PO) lalu disimpan sebagai SNAPSHOT per baris. Saat edit, baris yang Jenis PPN-nya tidak diubah memakai
  snapshot lama (tidak dihitung ulang dengan aturan master terbaru).
- Kontrak field legacy dipertahankan untuk konsumen hilir (DO, Vendor Invoice, DP, SPK, laporan):
  `dpp` (nilai tanpa PPN setelah diskon — fungsi tetap), `tax_amount` (PPN ditagih), `total`, `tax_inclusive`
  per baris, `tax` = tarif efektif (%), header `grand_total`/`tax_total`/dst.
- F2: PPnBM BELUM diaktifkan (Vendor Invoice belum mendukung). Kapitalisasi PPN tidak dapat dikreditkan ditunda.
- Supplier Non-PKP tidak boleh dikenakan PPN (koreksi via Master Supplier).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

import tax_engine as TE

V2 = TE.TAX_ENGINE_VERSION  # 2
MODES = ("INCLUDE", "EXCLUDE", "NONE")
TRX_CODES = ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10")
SNAP_FIELDS = ("tax_code", "tax_name", "tax_rate", "tax_dpp_factor_num", "tax_dpp_factor_den", "tax_trx_code", "tax_facility")
LINE_INPUT_FIELDS = ("tax_mode", "tax_id", "tax_engine_version") + SNAP_FIELDS
LINE_OUTPUT_FIELDS = ("gross", "dpp", "tax_amount", "total", "tax_inclusive", "tax", "dpp_other", "tax_facility_amount",
                      "ppnbm_amount", "include_rounding_diff", "net_amount", "final_discount_share", "taxable",
                      "tax_mode", "tax_engine_version") + SNAP_FIELDS
HEADER_OUTPUT_FIELDS = ("tax_engine_version", "supplier_pkp", "dpp_total", "dpp_other_total", "non_ppn_total", "ppnbm_total",
                        "tax_facility_total", "tax_groups", "tax_rules_snapshot")
# Nominal turunan harga (diredaksi untuk pengguna tanpa view_purchase_price).
PRICE_LINE_KEYS = frozenset({"dpp_other", "tax_facility_amount", "ppnbm_amount", "include_rounding_diff", "net_amount",
                             "final_discount_share"})
PRICE_HEADER_KEYS = frozenset({"dpp_total", "dpp_other_total", "non_ppn_total", "ppnbm_total", "tax_facility_total",
                               "tax_groups"})
FACILITY_LABEL = {"NORMAL": "Tanpa fasilitas", "TIDAK_DIPUNGUT": "Tidak Dipungut", "DTP": "DTP", "DIBEBASKAN": "Dibebaskan"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(msg: str):
    raise HTTPException(400, msg)


def is_v2(doc: dict | None) -> bool:
    try:
        return int((doc or {}).get("tax_engine_version") or 0) == V2
    except (TypeError, ValueError):
        return False


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _date10(v) -> str | None:
    s = str(v or "").strip()[:10]
    return s if _DATE_RE.match(s) else None


# ----------------------------------------------------------------------------- Master Pajak
def normalize_tax_master(body: dict) -> dict:
    """Validasi & normalisasi field PPN pada Master Pajak (create/update). Hanya field yang DIKIRIM yang disentuh
    (update parsial tidak menghapus konfigurasi lain)."""
    out = dict(body or {})
    if "rate" in out:
        try:
            rate = Decimal(str(out.get("rate") if out.get("rate") not in (None, "") else "0"))
        except Exception:  # noqa: BLE001
            bad("Tarif (%) wajib berupa angka")
        if not rate.is_finite() or rate < 0 or rate > 100:
            bad("Tarif (%) harus 0..100")
        out["rate"] = float(rate)
    for k in ("dpp_factor_num", "dpp_factor_den"):
        if k not in out:
            continue
        v = out.get(k)
        if v in (None, ""):
            out[k] = None
            continue
        try:
            out[k] = int(str(v).strip())
        except ValueError:
            bad("Faktor DPP Nilai Lain harus bilangan bulat")
    if "dpp_factor_num" in out or "dpp_factor_den" in out:
        num, den = out.get("dpp_factor_num"), out.get("dpp_factor_den")
        if (num is None) != (den is None):
            bad("Faktor DPP Nilai Lain harus diisi pembilang dan penyebut")
        if den is not None and (den <= 0 or num <= 0 or num > den):
            bad("Faktor DPP Nilai Lain tidak valid (contoh 11/12 atau 1/1)")
    if "trx_code" in out:
        trx = str(out.get("trx_code") or "").strip()
        if trx and trx not in TRX_CODES:
            bad("Kode transaksi faktur tidak dikenal (01..10)")
        out["trx_code"] = trx or None
    if "facility" in out:
        fac = str(out.get("facility") or "NORMAL").strip().upper()
        if fac not in TE.FACILITIES:
            bad("Fasilitas pajak tidak dikenal")
        out["facility"] = fac
    trx, fac = out.get("trx_code"), out.get("facility")
    if trx and fac:
        if fac in ("TIDAK_DIPUNGUT", "DTP") and trx != "07":
            bad("Fasilitas Tidak Dipungut / DTP memakai kode transaksi 07")
        if fac == "DIBEBASKAN" and trx != "08":
            bad("Fasilitas Dibebaskan memakai kode transaksi 08")
        if fac == "NORMAL" and trx in ("07", "08"):
            bad("Kode transaksi 07/08 hanya untuk fasilitas Tidak Dipungut / DTP / Dibebaskan")
    for k in ("valid_from", "valid_to"):
        if k not in out:
            continue
        v = out.get(k)
        if v in (None, ""):
            out[k] = None
        elif not _date10(v):
            bad("Tanggal berlaku harus berformat YYYY-MM-DD")
        else:
            out[k] = _date10(v)
    if out.get("valid_from") and out.get("valid_to") and out["valid_from"] > out["valid_to"]:
        bad("Tanggal 'Berlaku sampai' tidak boleh sebelum 'Berlaku dari'")
    return out


def tax_master_issues(t: dict) -> list[str]:
    """Kelengkapan master untuk PO v2 (Belum lengkap = tidak dapat dipakai; tidak ada fallback ke v1)."""
    issues = []
    if not t.get("trx_code") and not t.get("coretax_trx_code"):
        issues.append("kode transaksi faktur")
    if not t.get("dpp_factor_num") or not t.get("dpp_factor_den"):
        issues.append("faktor DPP Nilai Lain")
    try:
        TE.rule_from_master({**t, "trx_code": t.get("trx_code") or "04"})
    except ValueError as e:
        issues.append(str(e))
    return issues


def valid_on(t: dict, date: str | None) -> bool:
    d = _date10(date)
    if not d:
        return True
    return (not t.get("valid_from") or t["valid_from"] <= d) and (not t.get("valid_to") or d <= t["valid_to"])


def effective_rate(rule: dict | None) -> Decimal:
    """Tarif efektif (%) = tarif x faktor DPP Nilai Lain; 0 bila fasilitas (tidak ditagih)."""
    if not rule or rule.get("facility") != "NORMAL":
        return Decimal(0)
    return Decimal(rule["rate"]) * Decimal(rule["dpp_factor_num"]) / Decimal(rule["dpp_factor_den"])


def tax_option(t: dict, date: str | None = None) -> dict:
    issues = tax_master_issues(t)
    rule = None if issues else TE.rule_from_master(t)
    num, den = t.get("dpp_factor_num"), t.get("dpp_factor_den")
    fac = str(t.get("facility") or "NORMAL").upper()
    rate_txt = f"{Decimal(str(t.get('rate') or 0)).normalize():f}%"
    basis = f"{rate_txt} × {num}/{den}" if num and den and num != den else f"{rate_txt} penuh" if num and den else rate_txt
    label = " · ".join(x for x in (t.get("trx_code"), t.get("name") or t.get("code"), f"({basis})") if x)
    if fac != "NORMAL" and FACILITY_LABEL.get(fac, fac).lower() not in str(t.get("name") or "").lower():
        label += f" · {FACILITY_LABEL.get(fac, fac)}"
    return {"id": t.get("id"), "code": t.get("code"), "name": t.get("name"), "rate": t.get("rate"), "trx_code": t.get("trx_code"),
            "dpp_factor_num": num, "dpp_factor_den": den, "facility": fac, "valid_from": t.get("valid_from"),
            "valid_to": t.get("valid_to"), "label": label, "ready": not issues, "issues": issues,
            "valid_on_date": valid_on(t, date), "effective_rate": float(effective_rate(rule)) if rule else None,
            "notes": t.get("notes")}


# ----------------------------------------------------------------------------- hitung v2 (bentuk kompatibel v1)
def compute_v2(header: dict, lines: list[dict]):
    """(out_lines, totals) dengan kontrak sama seperti compute_po_totals v1 + field v2. Error -> HTTP 400."""
    eng = []
    for l in lines:
        x = {"qty": l.get("qty"), "price": l.get("price"), "discount": l.get("discount"),
             "tax_mode": str(l.get("tax_mode") or "NONE").upper()}
        for k in SNAP_FIELDS:
            x[k] = l.get(k)
        eng.append(x)
    hdr = {"final_discount_type": header.get("final_discount_type"), "final_discount_value": header.get("final_discount_value"),
           "supplier_pkp": header.get("supplier_pkp")}
    try:
        r = TE.compute_po(hdr, eng)
    except ValueError as e:
        bad(f"Perhitungan PPN: {e}")
    out = []
    for l, c in zip(lines, r["lines"]):
        x = dict(l)
        x.pop("tax_rule", None)
        x.pop("ppnbm_rate", None)
        for k in SNAP_FIELDS:
            x[k] = c[k]
        rule = TE.rule_from_line(c) if c["taxable"] else None
        x.update({"tax_mode": c["tax_mode"], "tax_engine_version": V2, "gross": _f(c["gross"]), "dpp": _f(c["dpp"]),
                  "tax_amount": _f(c["tax_amount"]), "total": _f(c["total"]), "tax_inclusive": c["tax_mode"] == "INCLUDE",
                  "tax": float(effective_rate(rule)), "dpp_other": _f(c["dpp_other"]),
                  "tax_facility_amount": _f(c["tax_facility_amount"]), "ppnbm_amount": _f(c["ppnbm_amount"]),
                  "include_rounding_diff": _f(c["include_rounding_diff"]), "net_amount": _f(c["net_amount"]),
                  "final_discount_share": _f(c["final_discount_share"]), "taxable": c["taxable"]})
        if not c["taxable"]:
            x["tax_id"] = None
        out.append(x)
    t = r["totals"]
    totals = {"gross_total": _f(t["gross_total"]), "item_discount_total": _f(t["item_discount_total"]),
              "subtotal_after_item_discount": _f(t["subtotal_after_item_discount"]),
              "final_discount_type": header.get("final_discount_type") or None,
              "final_discount_value": float(header.get("final_discount_value") or 0),
              "final_discount_amount": _f(t["final_discount_amount"]), "subtotal_after_discount": _f(t["subtotal_after_discount"]),
              "tax_total": _f(t["tax_total"]), "grand_total": _f(t["grand_total"]),
              "tax_engine_version": V2, "supplier_pkp": header.get("supplier_pkp"),
              "dpp_total": _f(t["dpp_total"]), "dpp_other_total": _f(t["dpp_other_total"]), "non_ppn_total": _f(t["non_ppn_total"]),
              "ppnbm_total": _f(t["ppnbm_total"]), "tax_facility_total": _f(t["tax_facility_total"]),
              "tax_groups": _jsonable(r["tax_groups"]), "tax_rules_snapshot": _jsonable(r["tax_rules_snapshot"])}
    return out, totals


def line_inputs(line: dict) -> dict:
    """Field input v2 yang ikut disimpan pada baris (kosong untuk v1)."""
    if not is_v2(line):
        return {}
    return {k: line.get(k) for k in LINE_INPUT_FIELDS}


def line_outputs(c: dict) -> dict:
    if not is_v2(c):
        return {}
    return {k: c.get(k) for k in LINE_OUTPUT_FIELDS}


def header_outputs(totals: dict) -> dict:
    if not is_v2(totals):
        return {}
    return {k: totals.get(k) for k in HEADER_OUTPUT_FIELDS}


# ----------------------------------------------------------------------------- resolve aturan (create / edit / preview)
def _derive_mode(header: dict, line: dict) -> str:
    """Klien lama (mis. impor Excel) tanpa tax_mode: dari tax_inclusive header + ada/tidaknya pajak baris."""
    has_tax = bool(line.get("tax_id")) or float(line.get("tax") or 0) > 0
    if not has_tax:
        return "NONE"
    return "INCLUDE" if header.get("tax_inclusive") else "EXCLUDE"


async def prepare_po(db, body: dict, *, doc: dict | None = None, old_lines: list[dict] | None = None) -> int:
    """Mutasi `body` (header + lines) sebelum hitung/simpan. Return versi engine dokumen (1 atau 2)."""
    lines = body.get("lines") or []
    olds = {o.get("id"): o for o in (old_lines or []) if o.get("id")}
    tax_ids = sorted({str(l.get("tax_id")) for l in lines if l.get("tax_id")})
    taxes = {t["id"]: t for t in await db.taxes.find({"id": {"$in": tax_ids}}, {"_id": 0}).to_list(len(tax_ids) + 1)} if tax_ids else {}

    legacy_api = doc is None and lines and not any(l.get("tax_mode") or l.get("tax_id") for l in lines) \
        and any(float(l.get("tax") or 0) > 0 for l in lines)
    if legacy_api:
        # Kompatibilitas API lama: tarif numerik tanpa Jenis PPN (tax_id) & tanpa tax_mode -> kontrak v1 apa adanya.
        # UI & impor Excel selalu mengirim tax_id/tax_mode -> v2. Master Pajak belum lengkap TIDAK pernah jatuh ke v1.
        # Aturan Non-PKP tetap mutlak pada jalur ini (supplier Non-PKP tidak boleh dikenakan PPN).
        sup_id = body.get("supplier_id")
        sup = await db.suppliers.find_one({"id": sup_id}, {"_id": 0, "id": 1, "pkp": 1}) if sup_id else None
        if not (sup or {}).get("pkp"):
            bad("Supplier Non-PKP tidak boleh dikenakan PPN. Hapus tarif pajak baris atau koreksi status PKP di Master Supplier")
        body.pop("tax_engine_version", None)
        return 1
    if doc is not None and not is_v2(doc):
        # ---- PO lama: tetap v1. Tarif tersimpan dikunci bila Jenis PPN baris tidak diubah.
        body.pop("tax_engine_version", None)
        for l in lines:
            l.pop("tax_engine_version", None)
            l.pop("tax_mode", None)
            o = olds.get(l.get("id"))
            if o and (l.get("tax_id") or None) == (o.get("tax_id") or None):
                l["tax"] = o.get("tax")
            elif l.get("tax_id") and taxes.get(l["tax_id"]):
                t = taxes[l["tax_id"]]
                if tax_master_issues(t):
                    l["tax"] = float(t.get("rate") or 0)  # perilaku legacy (master lama hanya tarif)
                else:
                    l["tax"] = float(effective_rate(TE.rule_from_master(t)))
        return 1

    # ---- v2
    body["tax_engine_version"] = V2
    body["tax_inclusive"] = False  # perlakuan harga per baris (tax_mode)
    sup_id = body.get("supplier_id") or (doc or {}).get("supplier_id")
    sup = await db.suppliers.find_one({"id": sup_id}, {"_id": 0, "id": 1, "pkp": 1, "name": 1}) if sup_id else None
    pkp = bool((sup or {}).get("pkp"))
    body["supplier_pkp"] = pkp
    po_date = _date10(body.get("date") or (doc or {}).get("date")) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for i, l in enumerate(lines):
        n = i + 1
        if l.get("ppnbm_rate") not in (None, "", 0, "0"):
            bad(f"Baris {n}: PPnBM belum diaktifkan pada PO (menunggu dukungan Vendor Invoice)")
        l.pop("ppnbm_rate", None)
        l.pop("tax_rule", None)
        mode = str(l.get("tax_mode") or "").strip().upper() or _derive_mode(body, l)
        if mode not in MODES:
            bad(f"Baris {n}: perlakuan PPN tidak dikenal")
        l["tax_mode"] = mode
        l["tax_engine_version"] = V2
        if mode == "NONE":
            l["tax_id"] = None
            for k in SNAP_FIELDS:
                l[k] = None
            continue
        if not pkp:
            bad(f"Baris {n}: supplier Non-PKP tidak boleh dikenakan PPN. Pilih 'Tanpa PPN' atau koreksi status PKP di Master Supplier")
        tid = l.get("tax_id")
        if not tid:
            bad(f"Baris {n}: Jenis PPN wajib dipilih untuk perlakuan {mode.title()}")
        o = olds.get(l.get("id"))
        if o and is_v2(o) and o.get("tax_id") == tid and o.get("tax_code") and o.get("tax_mode") not in (None, "NONE"):
            for k in SNAP_FIELDS:  # snapshot historis — tidak memakai aturan master terbaru
                l[k] = o.get(k)
            continue
        t = taxes.get(str(tid))
        if not t or t.get("is_active") is False:
            bad(f"Baris {n}: Jenis PPN tidak ditemukan atau nonaktif di Master Pajak")
        issues = tax_master_issues(t)
        if issues:
            bad(f"Baris {n}: Jenis PPN '{t.get('name') or t.get('code')}' belum lengkap di Master Pajak ({', '.join(issues)}). "
                "Lengkapi oleh Accounting sebelum dipakai")
        if not valid_on(t, po_date):
            bad(f"Baris {n}: Jenis PPN '{t.get('name') or t.get('code')}' tidak berlaku pada tanggal PO {po_date}")
        l.update(TE.snapshot_rule(TE.rule_from_master(t)))
    compute_v2(body, lines)  # dry-run: semua error perhitungan -> 400 sebelum ada penulisan
    return V2


def preview_payload(out_lines: list[dict], totals: dict, version: int) -> dict:
    keep = ("tax_mode", "tax_id", "tax", "gross", "net_amount", "final_discount_share", "dpp", "dpp_other", "tax_amount",
            "tax_facility_amount", "ppnbm_amount", "total", "include_rounding_diff", "taxable", "tax_inclusive") + SNAP_FIELDS
    return {"tax_engine_version": version, "lines": [{k: _jsonable(x.get(k)) for k in keep if k in x} for x in out_lines],
            "totals": _jsonable(totals), "rounding_policy": dict(TE.ROUNDING_POLICY) if version == V2 else None}
