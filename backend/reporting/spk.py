"""SPK & Budget Control (Dashboard) — POSISI per cut-off (tanggal akhir filter / date_to). Read-only.

Source of truth existing (tidak ada engine budget / commitment baru):
  Budget      = procurement_budget SPK (sudah termasuk addendum `effective`, spk_layer.finalize_addendum)
                dikurangi Σ budget_change addendum effective yang effective_date > cut-off
                -> addendum setelah cut-off tidak bocor ke posisi historis.
  Commitment  = spk_commitment_ledger: COMMIT (+) − RELEASE (−) + ADJUST (amount bertanda), created_at (WIB) <= cut-off.
                COMMIT hanya ditulis engine saat PO menjadi Approved final (spk_allocation_layer._commit_po);
                Cancel / Reject / edit sesudah Approved menulis RELEASE (_release_po) -> otomatis ikut ledger.
                Konvensi tanda identik spk_allocation_layer._spk_committed.
  Realisasi   = bagian SPK dari barang yang benar-benar diterima lewat DO valid s/d cut-off:
                qty DO teralokasi ke SPK (alokasi DO hasil inheritance PO->DO existing; DO tanpa alokasi ->
                proporsional porsi SPK di baris PO) / qty SPK yang di-commit pada baris PO (qty COMMIT ledger)
                x nilai commitment (SPK, baris PO). Qty diterima dibatasi qty commit -> partial / multiple DO
                kumulatif tidak pernah melebihi commitment; tidak memakai harga master barang.
  Open Commitment = Commitment − Realisasi (min 0)
  Sisa Budget     = Budget − Commitment   (BUKAN Budget − Commitment − Realisasi: Realisasi ⊂ Commitment)
SPK aktif per cut-off: status 'active' dan start_date <= cut-off <= end_date. (Status 'closed' tidak memiliki riwayat
waktu -> mengikuti status saat ini.) Scope: tenant (proxy DB), divisi user (resolver cakupan existing) + filter
Divisi / Project dashboard pada dokumen sumber SPK. Supplier tidak dipakai (SPK tidak memiliki relasi supplier).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import report_control_scope_layer as RCS
from receipt_control_layer import _is_active as do_is_valid

from . import scope as S

VALUE_KEYS = ("budget", "commitment", "realization", "open_commitment", "remaining")
FLAG_PRIO = {"Over Budget": 0, "Kritis": 1, "Tanpa sisa budget": 2, "Masa berlaku ≤ 30 hari": 3,
             "Berakhir, masih ada open commitment": 4}
DRILL_KINDS = ("active", "over", "critical", "attention", "expiring")


def level(pct):
    """< 80% Normal · 80–90% Perhatian · > 90% Kritis · > 100% Over Budget."""
    if pct is None:
        return "normal", "Normal"
    if pct > 100:
        return "over", "Over Budget"
    if pct > 90:
        return "critical", "Kritis"
    if pct >= 80:
        return "warning", "Perhatian"
    return "normal", "Normal"


def _sign(ev):
    return -1 if ev == "RELEASE" else 1  # COMMIT +, RELEASE −, ADJUST/lainnya: amount bertanda


def _add_day(a):
    return S.local_day(a.get("effective_date")) or S.local_day(a.get("finalized_at"))


def budget_at(spk, adds, cut):
    """Budget efektif s/d cut-off = budget kini − addendum effective yang berlaku SETELAH cut-off."""
    later = sum(int(a.get("budget_change") or 0) for a in adds if a.get("status") == "effective" and _add_day(a) > cut)
    return int(spk.get("procurement_budget") or 0) - later


async def _empty():
    return []


async def load(server):
    """Batch read (tenant-scoped otomatis oleh proxy DB). Tidak ada query per SPK / per kartu."""
    db = server.db
    spks, adds, led, allocs = await asyncio.gather(
        db.spk.find({"status": {"$in": ["active", "closed"]}}, {"_id": 0}).to_list(20000),
        db.spk_addendums.find({"status": "effective"}, {"_id": 0}).to_list(50000),
        db.spk_commitment_ledger.find({}, {"_id": 0}).to_list(500000),
        db.procurement_item_spk_allocations.find({"source_type": {"$in": ["po", "do"]}}, {"_id": 0}).to_list(500000))
    pl_ids = sorted({r.get("po_line_id") for r in led if r.get("po_line_id")})
    do_lines, po_lines = await asyncio.gather(
        db.do_lines.find({"po_line_id": {"$in": pl_ids}}, {"_id": 0}).to_list(500000) if pl_ids else _empty(),
        db.po_lines.find({"id": {"$in": pl_ids}}, {"_id": 0, "id": 1, "qty": 1}).to_list(500000) if pl_ids else _empty())
    do_ids = sorted({x.get("do_id") for x in do_lines if x.get("do_id")})
    dos = await db.do.find({"id": {"$in": do_ids}}, {"_id": 0, "id": 1, "date": 1, "cancelled": 1, "deleted": 1,
                                                     "status": 1}).to_list(200000) if do_ids else []
    return {"spk": spks, "adds": adds, "ledger": led, "allocs": allocs, "do_lines": do_lines, "dos": dos,
            "po_qty": {x["id"]: float(x.get("qty") or 0) for x in po_lines}}


def _scoped_spk(data, f, cut, user, server):
    glob = True if server is None else RCS._global(server, user)
    mydiv = set() if glob else RCS._divisions(user or {})
    return [s for s in data["spk"]
            if s.get("start_date") and S.day(s, "start_date") <= cut          # SPK belum mulai -> tidak dihitung
            and (glob or s.get("division_id") in mydiv)
            and (not f.division_id or s.get("division_id") == f.division_id)
            and (not f.project_id or s.get("project_id") == f.project_id)]


def rows_at(data, f, cut, user=None, server=None):
    """Seluruh baris SPK posisi cut-off (murni, tanpa DB). Dipakai KPI + Top 5 + Perlu Perhatian + drill-down."""
    spks = _scoped_spk(data, f, cut, user, server)
    ids = {s["id"] for s in spks}
    adds = {}
    for a in data["adds"]:
        adds.setdefault(a.get("spk_id"), []).append(a)
    com, cqty = {}, {}  # (spk, baris PO) -> nilai commitment / qty COMMIT terakhir s/d cut-off
    for r in sorted(data["ledger"], key=lambda r: str(r.get("created_at") or "")):
        if r.get("spk_id") not in ids or S.local_day(r.get("created_at")) > cut:
            continue
        k = (r["spk_id"], r.get("po_line_id"))
        com[k] = com.get(k, 0) + _sign(r.get("event")) * int(r.get("amount") or 0)
        if r.get("event") == "COMMIT" and r.get("qty") is not None:
            cqty[k] = float(r.get("qty") or 0)
    po_alloc, do_alloc = {}, {}
    for a in data["allocs"]:
        if a.get("spk_id") not in ids:
            continue
        tgt = po_alloc if a.get("source_type") == "po" else do_alloc
        d = tgt.setdefault(a.get("item_line_id"), {})
        d[a["spk_id"]] = d.get(a["spk_id"], 0) + float(a.get("allocated_qty") or 0)
    ok_do = {d["id"]: S.local_day(d.get("date")) for d in data["dos"] if do_is_valid(d)}
    recv = {}  # (spk, baris PO) -> qty diterima kumulatif s/d cut-off
    for x in data["do_lines"]:
        dd = ok_do.get(x.get("do_id"))
        if not dd or dd > cut:
            continue
        pl, q = x.get("po_line_id"), float(x.get("qty") or 0)
        parts = do_alloc.get(x.get("id"))
        if not parts:  # DO tanpa alokasi SPK: proporsional porsi SPK pada baris PO (porsi non-SPK tidak dihitung)
            pq = data.get("po_qty", {}).get(pl) or 0
            parts = {sid: q * v / pq for sid, v in (po_alloc.get(pl) or {}).items()} if pq > 0 else {}
        for sid, qq in parts.items():
            recv[(sid, pl)] = recv.get((sid, pl), 0) + qq
    real, spk_com = {}, {}
    for (sid, pl), amt in com.items():
        spk_com[sid] = spk_com.get(sid, 0) + amt
        aq = cqty.get((sid, pl)) or (po_alloc.get(pl) or {}).get(sid) or 0
        if amt <= 0 or aq <= 0:
            continue
        real[sid] = real.get(sid, 0) + amt * min(recv.get((sid, pl), 0), aq) / aq
    soon = (date.fromisoformat(cut) + timedelta(days=30)).isoformat()
    out = []
    for s in spks:
        sid = s["id"]
        b = budget_at(s, adds.get(sid, []), cut)
        c = spk_com.get(sid, 0)
        r = min(round(real.get(sid, 0)), max(c, 0))
        end = S.day(s, "end_date") or None
        active = s.get("status") == "active" and (not end or end >= cut)
        pct = round(c * 100.0 / b, 1) if b > 0 else (None if c == 0 else 999.0)
        lv, lv_label = level(pct)
        opn = max(c - r, 0)
        flags = []
        if active:
            if lv in ("over", "critical"):
                flags.append(lv_label)
            if b - c <= 0 and lv != "over":
                flags.append("Tanpa sisa budget")
            if end and end <= soon:
                flags.append("Masa berlaku ≤ 30 hari")
        elif end and end < cut and opn > 0:
            flags.append("Berakhir, masih ada open commitment")
        out.append({"id": sid, "spk_number": s.get("spk_number"), "title": s.get("title") or s.get("name"),
                    "project_id": s.get("project_id"), "project_name": s.get("project_name"),
                    "division_id": s.get("division_id"), "division_name": s.get("division_name"),
                    "status": s.get("status"), "start_date": S.day(s, "start_date"), "end_date": end, "active": active,
                    "expiring": bool(active and end and end <= soon),
                    "budget": b, "commitment": c, "realization": r, "open_commitment": opn, "remaining": b - c,
                    "usage_pct": pct, "level": lv, "level_label": lv_label, "flags": flags})
    return out


def attention_sorted(rows):
    return sorted((x for x in rows if x["flags"]),
                  key=lambda x: (min(FLAG_PRIO.get(fl, 9) for fl in x["flags"]), -(x["usage_pct"] or 0)))


def drill(rows, kind):
    """Predikat drill-down = predikat KPI (parity)."""
    if kind == "attention":
        return attention_sorted(rows)
    act = [x for x in rows if x["active"]]
    if kind == "over":
        act = [x for x in act if x["level"] == "over"]
    elif kind == "critical":
        act = [x for x in act if x["level"] == "critical"]
    elif kind == "expiring":
        act = [x for x in act if x["expiring"]]
    return sorted(act, key=lambda x: -(x["usage_pct"] or 0))


def totals(rows):
    act = [x for x in rows if x["active"]]
    t = {k: sum(x[k] for x in act) for k in VALUE_KEYS}
    t["usage_pct"] = round(t["commitment"] * 100.0 / t["budget"], 1) if t["budget"] > 0 else None
    t["realization_pct"] = round(t["realization"] * 100.0 / t["commitment"], 1) if t["commitment"] > 0 else None
    return t


def public(x, with_value):
    """Proyeksi baris untuk response. Tanpa spk:view nominal TIDAK dikirim (field dihilangkan, bukan 0)."""
    keep = ("id", "spk_number", "title", "project_name", "division_name", "status", "start_date", "end_date", "active",
            "usage_pct", "level", "level_label", "flags")
    return {k: x[k] for k in keep} | ({k: x[k] for k in VALUE_KEYS} if with_value else {})


def compute(data, f, cut, user=None, server=None, with_value=True):
    """Section SPK. with_value=False (tanpa spk:view) -> hanya count; daftar SPK & nominal tidak dikirim."""
    rows = rows_at(data, f, cut, user, server)
    attn = attention_sorted(rows)
    kpi = {"active": len(drill(rows, "active")), "over_budget": len(drill(rows, "over")),
           "critical": len(drill(rows, "critical")), "expiring": len(drill(rows, "expiring")), "attention": len(attn)}
    out = {"as_of": cut, "kpi": kpi, "with_value": with_value}
    if with_value:
        kpi.update(totals(rows))
        top = sorted((x for x in rows if x["active"] and x["usage_pct"] is not None), key=lambda x: -x["usage_pct"])[:5]
        out["top"] = [public(x, True) for x in top]
        out["attention"] = [public(x, True) for x in attn[:8]]
    return out
