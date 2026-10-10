"""Kontrak Harga Vendor / Price Control (Dashboard). Read-only.

Status kontrak = POSISI per cut-off (date_to), bukan hari ini:
  aktif        : status 'active' dan start_date <= cut-off <= end_date; draft / cancelled tidak pernah aktif
  akan berakhir: aktif dan end_date <= cut-off + 30 hari
  kedaluwarsa  : status 'active' dan end_date < cut-off (status 'expired' existing diturunkan dari tanggal)
  item aktif   : item yang memiliki harga efektif pada cut-off menurut Effective Price Resolver existing
Price Control = TRANSAKSI periode (PO bertanggal date_from..date_to), HANYA PO Approved final (reporting.procurement
.po_valid: status Approved / Partially Received / Fully Received, tidak cancelled, document_status bukan
Cancelled/Rejected), dinilai per baris barang. Harga kontrak = Effective Price Resolver existing
(vendor_contract_layer._pick_price — aturan yang sama dengan resolve_vendor_contract_price: Vendor + Item + UOM +
Tanggal PO + Qty UOM PO / minimum tier). Tidak ada resolver kedua.
Harga PO efektif (apple-to-apple dengan net_contract_price, sebelum pajak):
  dpp baris dari engine PO existing doc_procurement.compute_po_totals (harga x qty − diskon item, lalu diskon final
  level-PO diprorata ke baris; pajak inklusif diekstrak, pajak eksklusif tidak ditambahkan) / qty UOM PO.
  -> PPN tidak pernah membuat PO terlihat lebih mahal dari kontrak. Formula transaksi PO tidak diubah.
P4 (Opsi A, disetujui user): harga kontrak = harga yang berlaku pada TANGGAL PO -> versi harga historis direkonstruksi
read-only dari `vendor_contract_price_history` (reporting.contract_history; resolver existing tetap satu-satunya aturan
pemilihan). Rentang yang tidak dapat dibuktikan -> status `history_incomplete` ("Riwayat Harga Tidak Lengkap").
Label "Di Atas Tolerance" -> "Melebihi Tolerance" (Dashboard = Laporan C).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from . import contract_history as CH
from . import procurement as P
from . import scope as S

STATUS_LABEL = {"ok": "Sesuai", "over": "Melebihi Tolerance", "no_contract": "Tanpa Kontrak",
                "history_incomplete": "Riwayat Harga Tidak Lengkap"}
PRICE_STATUSES = ("ok", "over", "no_contract", "history_incomplete")
PRICE_KEYS = ("contract_price", "base_price", "po_price", "allowed_max", "tolerance_pct", "diff", "diff_pct",
              "diff_unit")
CONTRACT_KINDS = ("active", "expiring", "expired")


def po_qty(line):
    """Qty dalam UOM PO (UOM kontrak), sama dengan yang dikirim flow PO ke resolver."""
    f = float(line.get("conversion_factor") or 1) or 1
    dq = line.get("display_qty")
    return float(dq) if dq is not None else float(line.get("qty") or 0) / f


def effective_prices(header, lines):
    """{line_id: harga efektif per UOM PO sebelum pajak} — dpp dari engine PO existing (compute_po_totals)."""
    import doc_procurement
    out_lines, _ = doc_procurement.compute_po_totals(header, lines)
    res = {}
    for ln, x in zip(lines, out_lines):
        q = po_qty(ln)
        res[ln.get("id")] = (float(x["dpp"]) / q) if q > 0 else None
    return res


def po_in_scope(r):
    return P.po_valid(r)  # Approved final (definisi existing reporting)


async def _empty():
    return []


async def load(server, po_ids):
    db = server.db
    heads, items, hist, lines, pos = await asyncio.gather(
        db.vendor_contracts.find({}, {"_id": 0}).to_list(50000),
        db.vendor_contract_items.find({}, {"_id": 0}).to_list(500000),
        db.vendor_contract_price_history.find({}, {"_id": 0}).to_list(500000),
        db.po_lines.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(500000) if po_ids else _empty(),
        db.po.find({"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "tax_inclusive": 1, "final_discount_type": 1,
                                            "final_discount_value": 1}).to_list(200000) if po_ids else _empty())
    return {"contracts": heads, "items": items, "history": hist, "po_lines": lines, "po_heads": {p["id"]: p for p in pos}}


def _groups(data):
    heads = {c["id"]: c for c in data["contracts"]}
    groups = {}
    for it in data["items"]:
        if it.get("supplier_id") and it.get("item_id") and it.get("uom_id"):
            groups.setdefault((it["supplier_id"], it["item_id"], it["uom_id"]), []).append((it, heads.get(it.get("contract_id"))))
    return groups


def contract_rows(contracts, items, f, cut):
    """Baris kontrak dengan status posisi cut-off (dipakai KPI dan drill-down)."""
    soon = (date.fromisoformat(cut) + timedelta(days=30)).isoformat()
    n_items = {}
    for it in items:
        n_items[it.get("contract_id")] = n_items.get(it.get("contract_id"), 0) + 1
    out = []
    for c in contracts:
        if f.supplier_id and c.get("supplier_id") != f.supplier_id:
            continue
        if c.get("status") != "active":
            continue  # draft / cancelled tidak pernah aktif / kedaluwarsa
        s0, e0 = S.day(c, "start_date"), S.day(c, "end_date")
        if s0 and s0 > cut:
            continue  # belum mulai pada cut-off
        expired = bool(e0 and e0 < cut)
        out.append({"id": c["id"], "contract_number": c.get("contract_number"), "supplier_id": c.get("supplier_id"),
                    "supplier_name": c.get("supplier_name"), "start_date": s0 or None, "end_date": e0 or None,
                    "items": n_items.get(c["id"], 0), "active": not expired,
                    "expiring": bool(not expired and e0 and e0 <= soon), "expired": expired,
                    "status_at": "expired" if expired else "active"})
    return out


def contract_drill(rows, kind):
    key = {"active": "active", "expiring": "expiring", "expired": "expired"}[kind]
    return sorted((r for r in rows if r[key]), key=lambda r: (r["end_date"] or "9999-12-31", r["contract_number"] or ""))


def contract_kpis(contracts, items, f, cut, pick=None):
    rows = contract_rows(contracts, items, f, cut)
    live = set()
    if pick:  # item dalam kontrak aktif = punya harga efektif pada cut-off menurut resolver existing
        groups = _groups({"contracts": contracts, "items": items})
        for (sup, item, uom), pairs in groups.items():
            if (not f.supplier_id or sup == f.supplier_id) and pick(sup, item, uom, pairs, cut, None):
                live.add(item)
    return {"active": len(contract_drill(rows, "active")), "expiring": len(contract_drill(rows, "expiring")),
            "expired": len(contract_drill(rows, "expired")), "items_active": len(live)}


def price_lines(po_rows, data, pick):
    """Semua baris PO Approved final periode + hasil resolver existing (tanpa redaksi; internal)."""
    groups = _groups(data)
    hidx = CH.index(data.get("history"))
    lines_by_po = {}
    for ln in data["po_lines"]:
        lines_by_po.setdefault(ln.get("po_id"), []).append(ln)
    out = []
    for po in po_rows:
        if not po_in_scope(po):
            continue
        lines = lines_by_po.get(po["id"]) or []
        if not lines:
            continue
        head = {**po, **(data.get("po_heads", {}).get(po["id"]) or {})}
        prices = effective_prices(head, lines)
        d = S.day(po, "date")
        for ln in lines:
            qty = po_qty(ln)
            price = prices.get(ln.get("id"))
            if qty <= 0 or price is None:
                continue
            uom = ln.get("uom_id") or ln.get("unit_id")
            sup = po.get("supplier_id")
            res = CH.resolve(pick, sup, ln.get("item_id"), uom, groups.get((sup, ln.get("item_id"), uom), []), d, qty, hidx)
            row = {"po_id": po["id"], "po_no": po.get("no"), "po_date": d, "supplier_id": sup,
                   "supplier_name": po.get("supplier_name"), "item_id": ln.get("item_id"), "item_name": ln.get("item_name"),
                   "qty": qty, "uom_id": uom, "uom": ln.get("display_unit") or ln.get("unit"), "po_price": price,
                   "po_line_id": ln.get("id"), "po_status": po.get("status"),
                   "price_status_snapshot": ln.get("price_status"), "price_change_reason": ln.get("price_change_reason"),
                   "price_version": None, "item_row_id": None, "history_changes": []}
            if not res:
                st = "no_contract"
                row.update(contract_price=None, tolerance_pct=None, diff=None, contract_number=None, contract_id=None)
            elif res.get("incomplete"):
                st = "history_incomplete"  # tanggal PO pada rentang versi harga yang tidak tercatat -> tidak dinilai
                row.update(contract_price=None, tolerance_pct=None, diff=None, contract_number=res.get("contract_number"),
                           contract_id=res.get("contract_id"), item_row_id=res.get("item_row_id"))
            else:
                net, tol = float(res["net_contract_price"]), float(res.get("tolerance_pct") or 0)
                allowed = net * (1 + tol / 100.0)
                st = "over" if price > allowed + 1e-6 else "ok"
                row.update(contract_price=net, base_price=res.get("base_price"), tolerance_pct=tol, allowed_max=allowed,
                           diff_unit=price - net, diff=(price - net) * qty,
                           diff_pct=round((price - net) * 100.0 / net, 2) if net else None,
                           contract_number=res.get("contract_number"), contract_id=res.get("contract_id"),
                           price_version=res.get("price_version"), price_version_from=res.get("effective_start"),
                           item_row_id=res.get("item_row_id"), history_changes=res.get("history_changes") or [])
            row.update(status=st, status_label=STATUS_LABEL[st])
            out.append(row)
    return out


def po_sets(lines):
    by = {}
    for r in lines:
        by.setdefault(r["po_id"], set()).add(r["status"])
    return {"ok": {k for k, v in by.items() if v == {"ok"}}, "over": {k for k, v in by.items() if "over" in v},
            "no_contract": {k for k, v in by.items() if "no_contract" in v},
            "history_incomplete": {k for k, v in by.items() if "history_incomplete" in v}, "all": set(by)}


INTERNAL_KEYS = ("history_changes", "item_row_id", "po_line_id", "price_version", "price_version_from", "po_status",
                 "price_status_snapshot", "price_change_reason")


def redact(row, with_value):
    """Payload Dashboard: field tambahan internal P4 tidak dikirim (kontrak response Dashboard tetap)."""
    row = {k: v for k, v in row.items() if k not in INTERNAL_KEYS}
    return row if with_value else {k: v for k, v in row.items() if k not in PRICE_KEYS}


def exceptions_sorted(lines):
    ex = [r for r in lines if r["status"] != "ok"]
    return sorted(ex, key=lambda r: (0 if r["status"] == "over" else 1, -abs(r.get("diff") or 0), r["po_date"] or ""))


def price_drill(lines, status):
    sets = po_sets(lines)
    if status == "ok":
        rows = [r for r in lines if r["po_id"] in sets["ok"]]
    elif status in ("over", "no_contract", "history_incomplete"):
        rows = [r for r in lines if r["status"] == status]
    else:
        rows = list(lines)
    return sorted(rows, key=lambda r: (0 if r["status"] == "over" else 1, -abs(r.get("diff") or 0), r["po_date"] or ""))


def price_control(po_rows, data, pick, with_value=True, limit=8):
    lines = price_lines(po_rows, data, pick)
    sets = po_sets(lines)
    ex = exceptions_sorted(lines)
    kpi = {"po_ok": len(sets["ok"]), "po_over": len(sets["over"]), "po_no_contract": len(sets["no_contract"]),
           "po_evaluated": len(sets["all"]), "lines": len(lines),
           "lines_over": sum(1 for r in lines if r["status"] == "over"),
           "lines_no_contract": sum(1 for r in lines if r["status"] == "no_contract"),
           "po_history_incomplete": len(sets["history_incomplete"]),
           "lines_history_incomplete": sum(1 for r in lines if r["status"] == "history_incomplete")}
    if with_value:  # Nilai Selisih Harga = Σ selisih (harga efektif − net kontrak) x qty pada baris di atas tolerance
        kpi["diff_value"] = round(sum(r["diff"] or 0 for r in lines if r["status"] == "over"), 2)
    return {"kpi": kpi, "exceptions": [redact(r, with_value) for r in ex[:limit]], "with_value": with_value,
            "_lines": lines}
