"""Revaluasi Saldo Awal / Valuation Replay — inti murni (tanpa DB), dipakai endpoint & script audit read-only.

Masalah: pool dari Import Saldo Awal Persediaan punya qty tetapi nilai 0 (nilai import baru masuk valuasi setelah
"Tetapkan"). Bila sudah ada mutasi sesudahnya, OUT/HPP dinilai dengan rata-rata 0 / terdilusi.

Replay mengikuti aturan engine MWA existing (server.post_movement) persis:
  - IN : reversal_value > cost_snapshot > value_in > unit_cost_in ; tanpa sumber biaya -> avg lama (estimated)
  - OUT: qty x avg sebelum posting (reversal_value menimpa) ; saldo 0 -> nilai 0 (tanpa residu)
  - pembulatan: nilai 4 desimal, avg 6 desimal, HALF_UP — sama dengan engine.
Yang TIDAK diubah: qty, tanggal, sumber transaksi, harga IN yang tercatat (DO/adjustment/opname dengan biaya).
Yang dihitung ulang: nilai OUT/HPP, IN 'estimated' (memakai avg), IN yang membawa nilai OUT pool lain
(Transfer/Loan/Loan Return/Reversal) dan saldo sesudahnya.

Gerbang fidelity: replay dengan nilai opening = 0 WAJIB mereproduksi ledger tercatat persis; bila tidak, pool
diblokir (tidak ada nilai karangan).
Sumber nilai opening HANYA slice Import Saldo Awal Persediaan (opening_inventory) — lihat opening_sources().
Modul ini murni (tanpa DB / tanpa tulis): dipakai status, dry-run, dan script audit read-only.
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP as RHU
from decimal import Decimal as D

Q4, Q6 = D("0.0001"), D("0.000001")
OPENING_TYPES = ("Opening Balance", "Opening Balance Import")
CARRY_IN = {"Transfer In": "Transfer Out", "Loan In": "Loan Out"}
TOL_V, TOL_A = 0.00011, 0.0000011

ST_VALUED, ST_READY, ST_REPLAY, ST_NOSRC = "valued", "ready", "needs_replay", "no_source"
STATUS_LABEL = {ST_VALUED: "Sudah Dinilai", ST_READY: "Siap Ditetapkan", ST_REPLAY: "Perlu Revaluasi",
                ST_NOSRC: "Tidak Ada Nilai Sumber"}
# Prioritas penentuan status (kecil = menang): Sudah Dinilai > Perlu Revaluasi > Siap Ditetapkan > Tidak Ada Nilai Sumber.
STATUS_PRIORITY = {ST_VALUED: 0, ST_REPLAY: 1, ST_READY: 2, ST_NOSRC: 3}
# Urutan tampilan: yang perlu tindakan dulu.
DISPLAY_ORDER = {ST_READY: 0, ST_REPLAY: 1, ST_NOSRC: 2, ST_VALUED: 3}
ACTION_LABEL = {ST_VALUED: "Sudah Dinilai", ST_READY: "Tetapkan (Massal)", ST_REPLAY: "Perlu Valuation Replay",
                ST_NOSRC: "Tidak Ada Nilai Sumber"}
# Keluar antar-pool (nilai pindah ke pool lain, bukan HPP/pemakaian).
INTERNAL_OUT = ("Transfer Out", "Loan Out", "Loan Return Out", "Reversal Transfer In")
SOURCE_LABEL = "Import Saldo Awal Persediaan (opening_inventory: Σ base_qty, Σ opening_value)"


def vd(x):
    try:
        return D(str(x if x is not None else 0))
    except Exception:  # noqa: BLE001
        return D(0)


def f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def key(r):
    return (r.get("item_id"), r.get("warehouse_id"))


def order(e):
    return (str(e.get("at") or e.get("txn_at") or ""), str(e.get("id") or ""))


# ------------------------------------------------------------------ sumber nilai (HANYA Import Saldo Awal)
def opening_sources(slices):
    """Agregasi slice Import Saldo Awal Persediaan per (barang, gudang) — semua slice proyek dijumlahkan:
    qty = Σ base_qty, value = Σ opening_value, cost = value / qty. Tidak ada fallback harga lain (PO, kontrak,
    master, avg_cost/total_value saat ini). Slice yang tidak reconcile (purchase_price x display_qty atau
    base_unit_cost x base_qty != opening_value) membuat sumber pool tidak valid."""
    acc = {}
    for s in slices or []:
        k = key(s)
        if not k[0] or not k[1]:
            continue
        a = acc.setdefault(k, {"qty": D(0), "value": D(0), "slices": 0, "inconsistent": []})
        q, v = vd(s.get("base_qty")), vd(s.get("opening_value"))
        a["qty"] += q
        a["value"] += v
        a["slices"] += 1
        checks = []
        if s.get("purchase_price") is not None and s.get("display_qty") is not None:
            checks.append(vd(s.get("purchase_price")) * vd(s.get("display_qty")))
        if s.get("base_unit_cost") is not None and q > 0:
            checks.append(vd(s.get("base_unit_cost")) * q)
        if q < 0 or v < 0 or any(abs(c - v) > D("0.01") for c in checks):
            a["inconsistent"].append(s.get("project_code") or s.get("project_id") or s.get("id"))
    out = {}
    for k, a in acc.items():
        qty, value = float(a["qty"]), float(a["value"])
        valid = qty > 1e-9 and value > 0 and not a["inconsistent"]
        out[k] = {"qty": qty, "value": round(value, 4), "slices": a["slices"], "inconsistent": a["inconsistent"],
                  "cost": (value / qty) if valid else None}
    return out


# ------------------------------------------------------------------ klasifikasi
def classify(pools, opened_keys, moved_keys, sources):
    """Status per pool (deterministik, satu status, prioritas STATUS_PRIORITY):
    - Sudah Dinilai     : opening valuation sudah ada (ledger 'Opening Valuation' / penanda pool);
    - Perlu Revaluasi   : sumber Import Saldo Awal valid, tetapi sudah ada mutasi non-saldo-awal / qty pool != qty
                          saldo awal -> TIDAK boleh direct apply;
    - Siap Ditetapkan   : sumber valid & belum ada mutasi yang memblokir;
    - Tidak Ada Nilai Sumber : stok belum bernilai / slice saldo awal tanpa nilai valid dari Import Saldo Awal.
    Pool tanpa slice saldo awal yang sudah bernilai tidak relevan (tidak didaftar)."""
    out = []
    for p in pools:
        k = key(p)
        qty, avg = f(p.get("current_stock")), f(p.get("avg_cost"))
        src = (sources or {}).get(k)
        valued = k in opened_keys or bool(p.get("opening_valuation_id"))
        unvalued = qty > 1e-9 and avg <= 0
        if not src and not unvalued:
            continue
        if not src and valued:
            continue
        cost = src["cost"] if src else None
        if valued:
            st, reason = ST_VALUED, None
        elif cost is None:
            st = ST_NOSRC
            if not src:
                reason = "Tidak ada data Import Saldo Awal untuk pool ini."
            elif src["inconsistent"]:
                reason = f"Nilai Import Saldo Awal tidak konsisten (slice: {', '.join(str(x) for x in src['inconsistent'])})."
            else:
                reason = "Import Saldo Awal tidak memiliki qty/nilai yang valid (> 0)."
        elif k in moved_keys or abs(src["qty"] - qty) > 1e-9:
            st = ST_REPLAY
            reason = ("Sudah ada mutasi stok setelah saldo awal." if k in moved_keys
                      else "Qty pool berbeda dari qty saldo awal.")
        else:
            st, reason = ST_READY, None
        out.append({"item_id": k[0], "warehouse_id": k[1], "qty": qty, "avg_cost": avg,
                    "total_value": f(p.get("total_value")), "opening_qty": src["qty"] if src else None,
                    "opening_slices": src["slices"] if src else 0,
                    "opening_cost": round(cost, 6) if cost is not None else None,
                    "opening_value": src["value"] if cost is not None else None,
                    "status": st, "status_label": STATUS_LABEL[st], "action": ACTION_LABEL[st], "reason": reason,
                    "unvalued": unvalued})
    return out


def summarize(rows):
    s = {x: 0 for x in STATUS_LABEL}
    v = {ST_READY: 0.0, ST_REPLAY: 0.0}
    for r in rows:
        s[r["status"]] += 1
        if r["status"] in v:
            v[r["status"]] += r.get("opening_value") or 0
    return {"valued": s[ST_VALUED], "ready": s[ST_READY], "needs_replay": s[ST_REPLAY], "no_source": s[ST_NOSRC],
            "ready_opening_value": round(v[ST_READY], 4), "replay_opening_value": round(v[ST_REPLAY], 4),
            "unvalued_pools": sum(1 for r in rows if r["unvalued"]), "total": len(rows)}


def ready_after(row):
    """Nilai pool sesudah Tetapkan untuk pool Siap Ditetapkan (qty pool == qty saldo awal): Σ opening_value."""
    return round(f(row.get("opening_value")), 4)


# ------------------------------------------------------------------ replay
class Blocked(Exception):
    pass


def closure(seed_keys, entries):
    """Seed pool + pool tujuan Transfer/Loan/Loan Return yang menerima nilai OUT dari pool dalam set (berantai)."""
    by_doc = {}
    for e in entries:
        by_doc.setdefault((e.get("doc_id"), e.get("line_id")), []).append(e)
    keys, queue = set(seed_keys), list(seed_keys)
    while queue:
        k = queue.pop()
        for e in entries:
            if key(e) != k or f(e.get("qty_out")) <= 0:
                continue
            dt = e.get("doc_type")
            if dt not in ("Transfer Out", "Loan Out"):
                continue
            partners = by_doc.get((e.get("doc_id"), e.get("line_id")), [])
            for p in partners:
                if f(p.get("qty_in")) > 0 and key(p) not in keys:
                    keys.add(key(p))
                    queue.append(key(p))
        # Loan Out -> Loan Return (Out dari peminjam, In ke pemberi) memakai cost_snapshot Loan Out (line_id sama)
        for e in entries:
            if key(e) == k and e.get("doc_type") == "Loan Out":
                for r in entries:
                    if r.get("doc_type") in ("Loan Return Out", "Loan Return In", "Loan In") and r.get("line_id") == e.get("line_id") \
                            and key(r) not in keys:
                        keys.add(key(r))
                        queue.append(key(r))
    return keys


def _run(keys, entries, pools, openings, with_opening):
    """Satu pass replay global (urut waktu posting) atas pool `keys`. openings[k] = {qty, value} saldo awal."""
    ev = sorted([e for e in entries if key(e) in keys], key=order)
    st = {k: {"qty": 0.0, "val": D(0), "avg": D(0), "inj": D(0)} for k in keys}
    out = {}
    loan_uc = {}

    def inject(k, gap, at_entry):
        o = openings.get(k)
        s = st[k]
        if gap < -1e-6 or (gap > 1e-6 and not o):
            raise Blocked(f"Qty pool berubah di luar ledger valuasi (selisih {round(gap, 6)}) sebelum "
                          f"{(at_entry or {}).get('doc_type') or 'saldo akhir'} {(at_entry or {}).get('doc_no') or ''}".strip())
        if gap <= 1e-6:
            return
        s["inj"] += vd(gap)
        if s["inj"] > vd(o["qty"]) + D("0.000001"):
            raise Blocked("Qty di luar ledger valuasi melebihi qty saldo awal.")
        prev_qty = s["qty"]
        s["qty"] = float(vd(prev_qty) + vd(gap))
        rec = {"qty_before": prev_qty, "gap": gap, "value_before": float(s["val"]), "avg_before": float(s["avg"])}
        if with_opening:
            v_open = (vd(gap) * vd(o["value"]) / vd(o["qty"])) if o["qty"] else D(0)
            base = s["val"] if prev_qty > 0 else D(0)
            nv = (base + v_open).quantize(Q4, rounding=RHU)
            s["val"] = nv
            s["avg"] = (nv / vd(s["qty"])).quantize(Q6, rounding=RHU) if s["qty"] > 0 else D(0)
            rec.update(opening_value=float(v_open.quantize(Q4, rounding=RHU)))
        rec.update(qty_after=s["qty"], value_after=float(s["val"]), avg_after=float(s["avg"]),
                   at=(at_entry or {}).get("at"))
        out.setdefault(("__inj__", k), []).append(rec)

    for e in ev:
        k = key(e)
        s = st[k]
        if e.get("doc_type") == "Opening Valuation":  # penetapan absolut existing (Tetapkan): qty saldo awal dinilai di sini
            gap = f(e.get("qty_before")) - s["qty"]
            if gap < -1e-6:
                raise Blocked("Qty pool berubah di luar ledger valuasi sebelum Opening Valuation.")
            s["qty"] = float(vd(s["qty"]) + vd(max(gap, 0)))
            s["val"], s["avg"] = vd(e.get("value_after")), vd(e.get("avg_after"))
            out[e["id"]] = {"value_in": f(e.get("value_in")), "value_out": 0.0, "unit_cost": e.get("unit_cost"),
                            "qty_before": s["qty"], "value_before": f(e.get("value_before")), "avg_before": f(e.get("avg_before")),
                            "qty_after": s["qty"], "value_after": float(s["val"]), "avg_after": float(s["avg"])}
            continue
        inject(k, f(e.get("qty_before")) - s["qty"], e)
        bal = vd(s["qty"])
        old_val = s["val"] if bal > 0 else D(0)
        old_avg = s["avg"]
        qin, qout = f(e.get("qty_in")), f(e.get("qty_out"))
        v_in = v_out = D(0)
        unit = None
        dt = e.get("doc_type") or ""
        orig = out.get(e.get("reversal_of")) if e.get("reversal_of") else None
        if qin > 0:
            q = vd(qin)
            if e.get("is_reversal") and e.get("reversal_of"):
                v_in = vd(orig["value_out"]) if orig else vd(e.get("value_in"))
                unit = v_in / q
            elif dt in CARRY_IN or dt == "Reversal Transfer Out":
                src = next((out[x["id"]] for x in ev if x.get("doc_type") == CARRY_IN.get(dt, "Transfer Out")
                            and x.get("doc_id") == e.get("doc_id") and x.get("line_id") == e.get("line_id") and x["id"] in out), None)
                v_in = vd(src["value_out"]) if src else vd(e.get("value_in"))
                unit = v_in / q
            elif dt == "Loan Return In":
                uc = loan_uc.get(e.get("line_id"))
                v_in = vd(qin * uc) if uc is not None else vd(e.get("value_in"))
                unit = v_in / q
            elif e.get("valuation_estimated"):
                unit = old_avg
                v_in = q * old_avg
            else:
                uc = e.get("unit_cost")
                if uc is not None and (q * vd(uc)).quantize(Q4, rounding=RHU) == vd(e.get("value_in")).quantize(Q4, rounding=RHU):
                    unit = vd(uc)
                    v_in = q * unit
                else:
                    v_in = vd(e.get("value_in"))
                    unit = v_in / q
            new_qty = bal + q
            new_val = old_val + v_in
        else:
            q = vd(qout)
            if e.get("is_reversal") and e.get("reversal_of"):
                v_out = vd(orig["value_in"]) if orig else vd(e.get("value_out"))
                unit = (v_out / q) if q > 0 else D(0)
            elif dt == "Loan Return Out":
                uc = loan_uc.get(e.get("line_id"))
                v_out = vd(qout * uc) if uc is not None else vd(e.get("value_out"))
                unit = (v_out / q) if q > 0 else D(0)
            else:
                unit = old_avg if bal > 0 else D(0)
                v_out = q * unit
            new_qty = bal - q
            new_val = old_val - v_out
            if new_qty <= 0:
                new_qty, new_val = D(0), D(0)
        new_avg = (new_val / new_qty) if new_qty > 0 else D(0)
        nv, na = new_val.quantize(Q4, rounding=RHU), new_avg.quantize(Q6, rounding=RHU)
        rec = {"value_in": float(v_in.quantize(Q4, rounding=RHU)), "value_out": float(v_out.quantize(Q4, rounding=RHU)),
               "unit_cost": float(unit) if unit is not None else None,
               "qty_before": float(bal), "value_before": float(old_val.quantize(Q4, rounding=RHU)),
               "avg_before": float(old_avg.quantize(Q6, rounding=RHU)),
               "qty_after": float(new_qty), "value_after": float(nv), "avg_after": float(na)}
        out[e["id"]] = rec
        if dt == "Loan Out":
            loan_uc[e.get("line_id")] = rec["unit_cost"]
        s["qty"] = float(bal + vd(qin) - vd(qout))
        s["val"], s["avg"] = nv, na
    for k in keys:  # sisa qty di luar ledger setelah transaksi terakhir (import sesudah mutasi terakhir)
        inject(k, f((pools.get(k) or {}).get("current_stock")) - st[k]["qty"], None)
    return out, st


def _same(a, b):
    return all(abs(f(a.get(x)) - f(b.get(x))) <= (TOL_A if x.startswith("avg") else TOL_V)
               for x in ("value_in", "value_out", "value_after", "avg_after"))


def replay(seed_keys, entries, pools, openings):
    """Dry-run satu closure (satu barang). Return dict hasil; status 'blocked' bila tidak dapat direplay persis."""
    keys = closure(seed_keys, entries)
    res = {"keys": sorted(keys, key=lambda k: (str(k[0]), str(k[1]))), "blocked": None}
    try:
        fid, fst = _run(keys, entries, pools, openings, with_opening=False)
        by_id = {e["id"]: e for e in entries if key(e) in keys}
        for eid, r in fid.items():
            if isinstance(eid, tuple):
                continue
            if not _same(r, by_id[eid]):
                e = by_id[eid]
                fields = ("qty_before", "qty_after", "unit_cost", "value_in", "value_out", "value_before", "avg_before",
                          "value_after", "avg_after")
                prev = [x for x in sorted((x for x in entries if key(x) == key(e)), key=order) if order(x) < order(e)]
                res["blocked_detail"] = {
                    "id": eid, "doc_type": e.get("doc_type"), "doc_no": e.get("doc_no"), "doc_id": e.get("doc_id"),
                    "warehouse_id": e.get("warehouse_id"), "at": e.get("txn_at") or e.get("at"), "posted_at": e.get("at"),
                    "qty_in": f(e.get("qty_in")), "qty_out": f(e.get("qty_out")), "user": e.get("user"),
                    "valuation_estimated": e.get("valuation_estimated"), "source_key": e.get("source_key"),
                    "recorded": {x: e.get(x) for x in fields}, "replay": {x: r.get(x) for x in fields},
                    "previous": ({x: prev[-1].get(x) for x in ("doc_type", "doc_no", "at", "qty_after", "value_after", "avg_after")}
                                 if prev else None),
                    "recorded_arithmetic_ok": abs(f(e.get("value_before")) + f(e.get("value_in")) - f(e.get("value_out"))
                                                  - f(e.get("value_after"))) <= TOL_V}
                raise Blocked(f"Riwayat valuasi tidak dapat direproduksi persis pada {e.get('doc_type')} {e.get('doc_no') or ''} "
                              f"(tercatat {f(e.get('value_after'))}, replay {r['value_after']}).")
        for k in keys:
            p = pools.get(k) or {}
            if abs(fst[k]["qty"] - f(p.get("current_stock"))) > 1e-6 or abs(float(fst[k]["val"]) - f(p.get("total_value"))) > TOL_V:
                raise Blocked("Saldo pool saat ini berbeda dari hasil ledger valuasi (pool berubah di luar ledger).")
        new, nst = _run(keys, entries, pools, openings, with_opening=True)
    except Blocked as exc:
        res["blocked"] = str(exc)
        return res
    changed = []
    for eid, r in new.items():
        if isinstance(eid, tuple):
            continue
        e = by_id[eid]
        if not _same(r, e) or abs(f(r["value_before"]) - f(e.get("value_before"))) > TOL_V:
            changed.append({"id": eid, "doc_type": e.get("doc_type"), "doc_no": e.get("doc_no"), "doc_id": e.get("doc_id"),
                            "line_id": e.get("line_id"), "item_id": e.get("item_id"), "warehouse_id": e.get("warehouse_id"),
                            "txn_at": e.get("txn_at"), "qty_in": f(e.get("qty_in")), "qty_out": f(e.get("qty_out")),
                            "before": {x: e.get(x) for x in ("unit_cost", "value_in", "value_out", "value_before", "avg_before",
                                                             "value_after", "avg_after")},
                            "after": {x: r[x] for x in ("unit_cost", "value_in", "value_out", "value_before", "avg_before",
                                                        "value_after", "avg_after")}})
    def _is_out(c):
        return c["qty_out"] > 0 and abs(f(c["after"]["value_out"]) - f(c["before"]["value_out"])) > TOL_V

    changed_ids = {c["id"] for c in changed}
    pools_out = []
    for k in keys:
        p = pools.get(k) or {}
        inj = new.get(("__inj__", k), [])
        mine = [c for c in changed if key(c) == k]
        # Urutan simulasi pool: Opening -> movement kronologis (MWA sesudah tiap movement, nilai keluar/HPP).
        tl = [{"kind": "opening", "at": i.get("at"), "qty_after": i["qty_after"], "opening_value": i.get("opening_value", 0),
               "value_after": i["value_after"], "avg_after": i["avg_after"], "_o": (str(i.get("at") or "~"), 0, "")} for i in inj]
        for e in sorted((x for x in entries if key(x) == k), key=order):
            r = new.get(e["id"])
            if r is None:
                continue
            tl.append({"kind": "movement", "id": e["id"], "doc_type": e.get("doc_type"), "doc_no": e.get("doc_no"),
                       "at": e.get("txn_at") or e.get("at"), "qty_in": f(e.get("qty_in")), "qty_out": f(e.get("qty_out")),
                       "value_in": r["value_in"], "value_out": r["value_out"], "recorded_value_out": f(e.get("value_out")),
                       "qty_after": r["qty_after"], "value_after": r["value_after"], "avg_after": r["avg_after"],
                       "recorded_value_after": f(e.get("value_after")), "changed": e["id"] in changed_ids,
                       "_o": order(e)[0:1] + (1, str(e.get("id") or ""))})
        tl.sort(key=lambda x: x.pop("_o"))
        pools_out.append({"item_id": k[0], "warehouse_id": k[1], "seed": k in seed_keys,
                          "qty": f(p.get("current_stock")), "before_value": f(p.get("total_value")), "before_avg": f(p.get("avg_cost")),
                          "after_value": float(nst[k]["val"]), "after_avg": float(nst[k]["avg"]),
                          "opening_qty": (openings.get(k) or {}).get("qty"), "opening_value": sum(i.get("opening_value", 0) for i in inj),
                          "affected_txns": len(mine), "affected_in": sum(1 for c in mine if c["qty_in"] > 0),
                          "affected_out": sum(1 for c in mine if _is_out(c)),
                          "affected_hpp": sum(1 for c in mine if _is_out(c) and c["doc_type"] not in INTERNAL_OUT),
                          "injections": inj, "timeline": tl, "_ver": p.get("_ver")})
    res.update(pools=pools_out, changed=changed,
               affected_txns=len(changed), affected_in=sum(1 for c in changed if c["qty_in"] > 0),
               affected_out=sum(1 for c in changed if _is_out(c)),
               affected_hpp=sum(1 for c in changed if _is_out(c) and c["doc_type"] not in INTERNAL_OUT),
               before_value=round(sum(p["before_value"] for p in pools_out), 4),
               after_value=round(sum(p["after_value"] for p in pools_out), 4),
               opening_value=round(sum(p["opening_value"] for p in pools_out), 4))
    return res


def fingerprint(results):
    """Sidik jari deterministik dry-run (state pool + entri terdampak) untuk apply idempotent / deteksi perubahan."""
    payload = []
    for r in results:
        payload.append([[p["item_id"], p["warehouse_id"], p.get("_ver"), p["qty"], p["before_value"], p["after_value"]]
                        for p in r.get("pools", [])])
        payload.append([[c["id"], c["before"].get("value_after"), c["after"].get("value_after")] for c in r.get("changed", [])])
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


# ------------------------------------------------------------------ analisis gabungan (status + dry-run + audit)
def movement_index(stock_rows):
    """Tanggal saldo awal (Opening Balance [Import] paling awal) + mutasi non-saldo-awal per pool (jumlah, pertama)."""
    odate, moves = {}, {}
    for e in stock_rows or []:
        k = key(e)
        d = str(e.get("txn_at") or e.get("at") or "")
        if e.get("doc_type") in OPENING_TYPES:
            if d and (k not in odate or d < odate[k]):
                odate[k] = d
            continue
        m = moves.setdefault(k, {"count": 0, "first": None})
        m["count"] += 1
        if d and (m["first"] is None or d < m["first"]["at"]):
            m["first"] = {"at": d, "doc_type": e.get("doc_type"), "doc_no": e.get("doc_no")}
    return odate, moves


def analyze(pools, slices, opened_keys, stock_rows, ledger_by_item=None, item_pools=None, in_scope=None,
            want=None, do_replay=True):
    """Murni & read-only. pools = pool dalam cakupan; slices = opening_inventory; ledger_by_item / item_pools = semua
    entri valuasi / pool barang yang direplay (closure transfer/pinjaman lintas gudang). Return (rows, replay, summary)."""
    sources = opening_sources(slices)
    odate, moves = movement_index(stock_rows)
    rows = classify(pools, opened_keys, set(moves), sources)
    by_key = {(r["item_id"], r["warehouse_id"]): r for r in rows}
    for r in rows:
        k = (r["item_id"], r["warehouse_id"])
        mv = moves.get(k) or {}
        r.update(opening_date=odate.get(k), moves_after_opening=mv.get("count", 0), first_move_after_opening=mv.get("first"),
                 after_value=None, after_avg=None, delta=None, affected_txns=0, affected_in=0, affected_out=0, affected_hpp=0,
                 replay_blocked=None)
        if r["status"] == ST_READY:
            r.update(after_value=ready_after(r), after_avg=r["opening_cost"])
        elif r["status"] == ST_VALUED:
            r.update(after_value=r["total_value"], after_avg=r["avg_cost"])
        if r["after_value"] is not None:
            r["delta"] = round(r["after_value"] - r["total_value"], 4)
    results = []
    if do_replay:
        seeds = {}
        for r in rows:
            if r["status"] == ST_REPLAY and (not want or (r["item_id"], r["warehouse_id"]) in want):
                seeds.setdefault(r["item_id"], set()).add((r["item_id"], r["warehouse_id"]))
        for item_id in sorted(seeds, key=str):
            ip = (item_pools or {}).get(item_id) or {}
            opened_item = {k for k in opened_keys if k[0] == item_id}
            openings = {k: {"qty": s["qty"], "value": s["value"], "at": odate.get(k)} for k, s in sources.items()
                        if k[0] == item_id and s["cost"] is not None and k not in opened_item
                        and not (ip.get(k) or {}).get("opening_valuation_id")}
            res = replay(seeds[item_id], (ledger_by_item or {}).get(item_id, []), ip, openings)
            if not res["blocked"] and in_scope and any(not in_scope(k[1]) for k in res["keys"]):
                res["blocked"] = "Replay melibatkan gudang di luar cakupan akses Anda."
            res["item_id"] = item_id
            for p in res.get("pools", []):
                p["opening_at"] = (openings.get((p["item_id"], p["warehouse_id"])) or {}).get("at")
            for k in seeds[item_id]:
                r = by_key[k]
                if res["blocked"]:
                    r.update(replay_blocked=res["blocked"], action="Diblokir — telusuri manual")
                    continue
                p = next((x for x in res["pools"] if (x["item_id"], x["warehouse_id"]) == k), None)
                if p:
                    r.update(after_value=round(p["after_value"], 4), after_avg=round(p["after_avg"], 6),
                             delta=round(p["after_value"] - p["before_value"], 4),
                             **{x: p[x] for x in ("affected_txns", "affected_in", "affected_out", "affected_hpp")})
            results.append(res)
    s = summarize(rows)
    ok = [x for x in results if not x["blocked"]]
    now = round(sum(f(p.get("total_value")) for p in pools), 4)
    ready_delta = round(sum(r["delta"] or 0 for r in rows if r["status"] == ST_READY), 4)
    replay_delta = round(sum(x["after_value"] - x["before_value"] for x in ok), 4)
    s.update(inventory_value_now=now, ready_delta=ready_delta, inventory_value_after_mass=round(now + ready_delta, 4),
             replay_items=len(results), replay_ok=len(ok), replay_blocked=len(results) - len(ok), replay_delta=replay_delta,
             inventory_value_after_all=round(now + ready_delta + replay_delta, 4), total_delta=round(ready_delta + replay_delta, 4),
             replay_affected_txns=sum(x["affected_txns"] for x in ok), replay_affected_in=sum(x["affected_in"] for x in ok),
             replay_affected_out=sum(x["affected_out"] for x in ok), replay_affected_hpp=sum(x["affected_hpp"] for x in ok),
             no_source_qty=round(sum(r["qty"] for r in rows if r["status"] == ST_NOSRC), 4),
             source=SOURCE_LABEL)
    return rows, results, s
