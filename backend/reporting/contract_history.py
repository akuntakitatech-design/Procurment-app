"""Rekonstruksi versi harga kontrak historis (READ-ONLY) — satu perhitungan bersama Dashboard Price Control & Laporan C.

Latar: perubahan harga resmi (`POST /api/vendor-contracts/{cid}/items/{rid}/price-change`) MENIMPA baris item
(harga baru + effective_start = tanggal efektif) dan mencatat `vendor_contract_price_history` (harga lama, harga baru,
tanggal efektif, `at`). Resolver existing hanya membaca baris kini -> PO bertanggal sebelum tanggal efektif tidak lagi
bertemu kontraknya. Modul ini TIDAK mengubah resolver input PO, engine kontrak, data, maupun histori; ia hanya
menyusun versi-versi lama sebagai baris virtual lalu memanggil aturan resolver existing (`server.pick_vendor_contract_price`
= vendor_contract_layer._pick_price: kontrak active, periode efektif, tier min_qty, tie-break) apa adanya.

Aturan (disetujui user, Opsi A):
  - Perubahan diterapkan berurutan menurut `at` (waktu pencatatan). Perubahan k: harga = harga baru mulai tanggal efektif
    e_k; sebelum e_k tetap mengikuti keadaan sebelum perubahan k (harga lama berlaku s/d H-1 tanggal efektif).
    -> beberapa perubahan, perubahan pada tanggal yang sama (yang tercatat terakhir menang), dan urutan tanggal
    mundur ditangani tanpa asumsi.
  - Versi PERTAMA (sebelum perubahan pertama): harga lama tercatat, tetapi TANGGAL AWAL-nya tidak tercatat di sistem
    (effective_start asli tertimpa; audit item tidak menyimpannya) -> rentang itu = "Riwayat Harga Tidak Lengkap".
    Tidak mengarang tanggal/harga, tidak backfill.
  - Rantai tidak konsisten (harga lama perubahan k != harga baru perubahan k-1 -> ada perubahan tak tercatat) ->
    seluruh rentang sebelum e_k = "Riwayat Harga Tidak Lengkap".
  - Batas akhir versi lama = effective_end baris (tidak diubah price-change) / akhir kontrak; batas awal versi kini tetap
    aturan existing. min_qty, tolerance, diskon/UOM baris tidak diubah price-change -> dipakai apa adanya.
  - Bila tanggal PO jatuh pada rentang "tidak lengkap" sebuah kandidat (kontrak active, qty >= min_qty) -> hasil =
    INCOMPLETE (status sendiri, bukan Sesuai / Melebihi / Tanpa Kontrak), agar dapat diperiksa.
"""
from __future__ import annotations

from datetime import date, timedelta

FAR_PAST, FAR_FUTURE = "0000-01-01", "9999-12-31"


def _d(v) -> str:
    return str(v or "")[:10]


def _prev(day: str) -> str:
    try:
        return (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    except ValueError:
        return FAR_PAST


def index(history) -> dict:
    """{item_row_id: [perubahan urut `at`]}"""
    out = {}
    for h in history or []:
        if h.get("item_row_id"):
            out.setdefault(h["item_row_id"], []).append(h)
    for v in out.values():
        v.sort(key=lambda h: (str(h.get("at") or ""), str(h.get("id") or "")))
    return out


def segments(changes):
    """Segmen versi sebelum/antara perubahan: [(lo, hi, known, base, net, change)] — lo/hi inklusif, None = tak terbatas.
    Segmen terakhir (harga baru perubahan terakhir, mulai e_n) = keadaan baris kini."""
    first = changes[0]
    segs = [(None, None, False, first.get("previous_base_price"), first.get("previous_net_price"), None)]
    prev_new = None
    for h in changes:
        e = _d(h.get("effective_date"))
        try:
            date.fromisoformat(e)
        except ValueError:
            return [(None, None, False, None, None, h)]  # tanggal efektif tidak valid -> tidak dapat direkonstruksi
        if prev_new is not None and int(h.get("previous_net_price") or 0) != prev_new:
            segs = [(lo, hi, False, b, n, c) for lo, hi, _k, b, n, c in segs]  # ada perubahan tak tercatat
        cap = _prev(e)
        nxt = []
        for lo, hi, k, b, n, c in segs:
            h2 = cap if hi is None or hi > cap else hi
            if lo is None or lo <= h2:
                nxt.append((lo, h2, k, b, n, c))
        nxt.append((e, None, True, h.get("new_base_price"), h.get("new_net_price"), h))
        segs = nxt
        prev_new = int(h.get("new_net_price") or 0)
    return segs


def _period(it, oc):
    s = it.get("effective_start") or (oc or {}).get("start_date") or FAR_PAST
    e = it.get("effective_end") or (oc or {}).get("end_date") or FAR_FUTURE
    return _d(s), _d(e)


def expand(pairs, hidx):
    """Pasangan (item, kontrak) + versi lama virtual. Return (pairs_baru, rentang_tidak_lengkap, info_virtual)."""
    out, unknown, virt = [], [], {}
    for it, oc in pairs:
        out.append((it, oc))
        ch = hidx.get(it.get("id")) if hidx else None
        if not ch or not oc:
            continue
        cs, ce = _period(it, oc)
        top = min(_prev(cs), ce)  # versi lama hanya sebelum awal versi kini & tidak melewati akhir baris/kontrak
        for lo, hi, known, base, net, c in segments(ch):
            hi2 = top if hi is None or hi > top else hi
            if lo is not None and lo > hi2:
                continue
            if not known:
                unknown.append((it, oc, lo or FAR_PAST, hi2))
                continue
            v = {**it, "base_price": int(base or 0), "net_price": int(net or 0), "effective_start": lo,
                 "effective_end": hi2, "discount_type": None, "discount_value": None}
            out.append((v, oc))
            virt[(oc.get("id"), lo, hi2, it.get("id"))] = c
    return out, unknown, virt


def resolve(pick, supplier_id, item_id, uom_id, pairs, d, qty, hidx):
    """Harga kontrak pada tanggal `d` dengan aturan resolver existing + versi historis.
    Return None (tanpa kontrak) | dict hasil resolver (+ price_version, history_changes) | {"incomplete": True, ...}."""
    exp, unknown, virt = expand(pairs, hidx)
    for it, oc, lo, hi in unknown:
        if oc.get("status") == "active" and lo <= d <= hi and (qty is None or float(qty) >= float(it.get("min_qty") or 0)):
            return {"incomplete": True, "contract_id": oc.get("id"), "contract_number": oc.get("contract_number"),
                    "item_row_id": it.get("id")}
    res = pick(supplier_id, item_id, uom_id, exp, d, qty)
    if not res:
        return None
    rs, re_ = _d(res.get("effective_start")), _d(res.get("effective_end"))
    hit = next((k for k in virt if k[0] == res["contract_id"] and k[1] == rs and k[2] == re_), None)
    if hit:
        row_id = hit[3]
    else:
        row_id = next((it.get("id") for it, oc in pairs if oc and oc.get("id") == res["contract_id"]
                       and float(it.get("min_qty") or 0) == float(res.get("min_qty") or 0)
                       and _period(it, oc)[0] <= d <= _period(it, oc)[1]), None)
    return {**res, "item_row_id": row_id, "price_version": "historical" if hit else "current",
            "history_changes": (hidx or {}).get(row_id) or []}
