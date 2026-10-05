"""PO — Informasi Harga & Supplier saat Tarik RO (read-only, on-demand).

Endpoint (di bawah /api/pull/ro-for-po -> izin PO 'create' via access control existing):
  GET /api/pull/ro-for-po/price-insight?ro_line_id=..&date=YYYY-MM-DD
      Header barang/kebutuhan + daftar supplier (Kontrak Aktif / Supplier Utama / riwayat beli)
      dengan Harga Kontrak, periode berlaku, Harga Beli Terakhir, PO terakhir, selisih.
  GET /api/pull/ro-for-po/price-history?ro_line_id=..&supplier_id=..&limit=5
      Maksimal 5 pembelian terakhir Barang + Supplier (hanya dibuka saat "Lihat Riwayat").

Aturan:
- Harga Kontrak: resolver Kontrak Harga Vendor existing (server.resolve_vendor_item_prices ==
  aturan resolve_vendor_contract_price: status active, periode efektif, tier min_qty) — batch.
- Harga Beli Terakhir: harga satuan net PO valid terakhir (status Approved / Partially Received /
  Fully Received, tidak cancelled — definisi yang sama dengan /purchase-price-history existing)
  untuk Barang + Supplier. Effective net = DPP baris / qty dasar, DPP dihitung ulang dengan engine
  uang PO canonical doc_procurement.compute_po_totals atas SELURUH baris PO tsb: diskon item ->
  Diskon Final PO diprorata ke net tiap baris -> PPN dikeluarkan bila harga termasuk pajak.
  Normalisasi ke satuan dasar hanya bila faktor konversi TERBUKTI (UOM dasar = 1, atau faktor
  tersimpan pada baris dari normalisasi UOM existing); selain itu "Tidak dapat dibandingkan"
  (tanpa harga, bukan kandidat Harga terendah).
- Keamanan: tenant (proxy DB) -> izin (access control + view_purchase_price untuk harga)
  -> cakupan divisi (RO & PO pembanding) -> business rule. Pesan 404 generik.
- Read-only: tidak ada tulis ke PO/RO/kontrak/master/stok/valuasi/SPK.
"""
from fastapi import Depends, HTTPException

import doc_procurement as _dp
from po_ro_split_layer import _Ctx, _allowed_divisions, ro_line_state

EPS = 1e-6
VALID_PO = ("Approved", "Partially Received", "Fully Received")
NOT_FOUND = "Kebutuhan RO tidak ditemukan atau tidak dapat diakses."
SUP_NOT_FOUND = "Supplier tidak ditemukan atau tidak dapat diakses."
NO_PRICE = "Anda tidak memiliki akses untuk melihat harga beli."
ST_BOTH, ST_CONTRACT, ST_PRIMARY, ST_HISTORY = "Kontrak Aktif + Supplier Utama", "Kontrak Aktif", "Supplier Utama", "Riwayat Pembelian"
_ORDER = {ST_BOTH: 0, ST_CONTRACT: 1, ST_PRIMARY: 2, ST_HISTORY: 3}


def _r(v, nd=4):
    return None if v is None else round(float(v), nd)


def _inactive(s):
    return not s or s.get("is_active") is False or s.get("active") is False


def _pct_text(p):
    t = f"{abs(p):.1f}".rstrip("0").rstrip(".")
    return t.replace(".", ",")


def diff_info(contract_base, last_base):
    """Selisih informatif Harga Kontrak vs Harga Beli Terakhir (relatif terhadap harga terakhir)."""
    if contract_base is None or not last_base:
        return None, None
    pct = (float(contract_base) - float(last_base)) / float(last_base) * 100.0
    if abs(pct) < 0.05:
        return 0.0, "Kontrak sama dengan harga terakhir"
    return round(pct, 2), f"Kontrak {_pct_text(pct)}% lebih {'rendah' if pct < 0 else 'tinggi'}"


async def _scoped_line(server, ro_line_id, user):
    db = server.db
    rl = await db.ro_lines.find_one({"id": ro_line_id}, {"_id": 0}) if ro_line_id else None  # tenant-scoped proxy
    head = await db.ro.find_one({"id": rl.get("ro_id")}, {"_id": 0}) if rl else None
    alw = _allowed_divisions(server, user)
    if not head or head.get("cancelled") or (alw is not None and head.get("division_id") not in alw):
        raise HTTPException(404, NOT_FOUND)
    return rl, head, alw


def _uom_tools(item, uoms):
    base_id = item.get("base_uom_id")
    cfg = {x.get("uom_id"): float(x.get("factor") or 0) for x in (item.get("uoms") or []) if x.get("uom_id")}

    def factor(uid):
        if not uid or uid == base_id:
            return 1.0
        f = cfg.get(uid)
        return f if f and f > 0 else None

    def label(uid):
        u = uoms.get(uid) or {}
        return u.get("symbol") or u.get("code") or u.get("name") or ""

    base_label = label(base_id) or item.get("unit") or ""
    return factor, label, base_label


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def proven_factor(ln, item, uoms):
    """Faktor UOM baris PO historis -> satuan dasar, HANYA bila dapat dibuktikan; else None.

    - uom_id baris == base UOM barang -> 1.
    - uom_id beda base -> faktor tersimpan (conversion_factor > 0) dari normalisasi UOM existing,
      dan konsisten dengan display_qty x faktor == qty dasar tersimpan.
    - baris legacy tanpa uom_id -> 1 hanya bila teks satuannya = satuan dasar barang.
    Tidak pernah menebak faktor = 1 untuk satuan yang berbeda."""
    base_id = item.get("base_uom_id")
    uid = ln.get("uom_id")
    if uid:
        if base_id and uid == base_id:
            return 1.0
        f, dq, q = _f(ln.get("conversion_factor")), ln.get("display_qty"), _f(ln.get("qty"))
        if base_id and f > 0 and dq is not None and abs(_f(dq) * f - q) <= max(1e-6, 1e-6 * abs(q)):
            return f
        return None
    unit = str(ln.get("unit") or "").strip().lower()
    bu = uoms.get(base_id) or {}
    labels = {str(x).strip().lower() for x in (bu.get("code"), bu.get("name"), bu.get("symbol"), item.get("unit")) if x}
    return 1.0 if unit and unit in labels else None


async def approved_purchases(server, item, alw, uoms):
    """Baris PO valid (Approved/Final) untuk barang, terbaru dulu. 3 query batch (po_lines barang,
    po, seluruh po_lines PO tsb untuk alokasi Diskon Final canonical)."""
    db = server.db
    item_id = item.get("id")
    lines = await db.po_lines.find({"item_id": item_id}, {"_id": 0}).to_list(20000)
    ids = sorted({x.get("po_id") for x in lines if x.get("po_id")})
    if not ids:
        return []
    pos = {p["id"]: p for p in await db.po.find({"id": {"$in": ids}, "status": {"$in": list(VALID_PO)}, "cancelled": {"$ne": True}},
                                                {"_id": 0}).to_list(len(ids) + 10)
           if p.get("supplier_id") and p.get("status") in VALID_PO and p.get("cancelled") is not True
           and (alw is None or p.get("division_id") in alw)}  # PO divisi di luar cakupan tidak dipakai
    if not pos:
        return []
    # DPP per baris via engine canonical (diskon item -> prorata Diskon Final -> keluarkan PPN inklusif)
    all_lines = await db.po_lines.find({"po_id": {"$in": sorted(pos)}}, {"_id": 0}).to_list(50000)
    by_po = {}
    for ln in all_lines:
        by_po.setdefault(ln.get("po_id"), []).append(ln)
    dpp = {}
    for pid, pls in by_po.items():
        computed, _tot = _dp.compute_po_totals(pos[pid], pls)
        for ln, c in zip(pls, computed):
            dpp[ln.get("id")] = float(c.get("dpp") or 0)
    rows = []
    for ln in lines:
        p = pos.get(ln.get("po_id"))
        qty = _f(ln.get("qty"))
        if not p or qty <= EPS or ln.get("id") not in dpp:
            continue
        net_line = dpp[ln["id"]] / qty  # net per satuan baris tersimpan (dasar bila sudah dinormalisasi)
        f = proven_factor(ln, item, uoms)
        unit = ln.get("display_unit") or (uoms.get(ln.get("uom_id")) or {}).get("code") or ln.get("unit") or ""
        comparable = f is not None
        rows.append({"date": p.get("date"), "po_id": p.get("id"), "po_no": p.get("no"), "supplier_id": p.get("supplier_id"),
                     "qty": _r(ln.get("display_qty") if ln.get("display_qty") is not None else (qty / f if comparable else qty)),
                     "unit": unit, "uom_id": ln.get("uom_id"), "comparable": comparable,
                     "unit_net_price": _r(net_line * f, 2) if comparable else None,
                     "qty_base": _r(qty) if comparable else None,
                     "unit_net_price_base": _r(net_line, 4) if comparable else None,
                     "_k": (str(p.get("date") or ""), str(p.get("approved_at") or p.get("created_at") or ""), str(p.get("no") or ""))})
    rows.sort(key=lambda r: r["_k"], reverse=True)
    for r in rows:
        r.pop("_k", None)
    return rows


def _pick_contract(cands, factor):
    """Satu baris per supplier: utamakan kontrak dalam satuan dasar, lalu yang faktornya diketahui."""
    cands = sorted(cands, key=lambda c: (factor(c.get("uom_id")) != 1.0, factor(c.get("uom_id")) is None, str(c.get("contract_number") or "")))
    return cands[0]


def install(server):
    app = server.app

    async def _uoms():
        return {u["id"]: u for u in await server.db.uoms.find({}, {"_id": 0}).to_list(2000)}

    @app.get("/api/pull/ro-for-po/price-insight", tags=["po-price-insight"])
    async def ro_price_insight(ro_line_id: str, date: str = "", user=Depends(server.current_user)):
        rl, head, alw = await _scoped_line(server, ro_line_id, user)
        show_price = server.has_perm(user, "view_purchase_price")
        item = await server.db.items.find_one({"id": rl.get("item_id")}, {"_id": 0}) or {}
        uoms = await _uoms()
        factor, label, base_label = _uom_tools(item, uoms)
        st = await ro_line_state(_Ctx(server), rl, None)
        remaining = float(st["remaining"])
        d = (date or "")[:10] or None
        resolver = getattr(server, "resolve_vendor_item_prices", None)
        contracts = []
        if resolver:
            contracts = await resolver(item.get("id") or rl.get("item_id"), d,
                                       lambda uid: (remaining / factor(uid)) if factor(uid) else remaining)
        by_sup = {}
        for c in contracts:
            by_sup.setdefault(c.get("supplier_id"), []).append(c)
        history = await approved_purchases(server, {**item, "id": item.get("id") or rl.get("item_id")}, alw, uoms) if show_price else []
        last_by_sup = {}
        for h in history:
            last_by_sup.setdefault(h["supplier_id"], h)
        primary_id = item.get("primary_supplier_id")
        sids = set(by_sup) | set(last_by_sup) | ({primary_id} if primary_id else set())
        sups = {s["id"]: s for s in await server.db.suppliers.find({"id": {"$in": sorted(x for x in sids if x)}}, {"_id": 0}).to_list(len(sids) + 10)} if sids else {}
        div = await server.db.divisions.find_one({"id": head.get("division_id")}, {"_id": 0}) if head.get("division_id") else None
        rows = []
        for sid in sids:
            s = sups.get(sid)
            if not sid or _inactive(s):
                continue
            c = _pick_contract(by_sup[sid], factor) if sid in by_sup else None
            last = last_by_sup.get(sid)
            is_primary = sid == primary_id
            status = ST_BOTH if (c and is_primary) else ST_CONTRACT if c else ST_PRIMARY if is_primary else ST_HISTORY
            row = {"supplier_id": sid, "supplier_name": s.get("name"), "supplier_code": s.get("code"), "status": status,
                   "is_contract": bool(c), "is_primary": is_primary, "contract_count": len(by_sup.get(sid) or [])}
            if c:
                f = factor(c.get("uom_id"))
                row.update({"contract_id": c.get("contract_id"), "contract_number": c.get("contract_number"), "contract_status": "Aktif",
                            "effective_start": c.get("effective_start"), "effective_end": c.get("effective_end"),
                            "contract_uom": c.get("uom_name") or label(c.get("uom_id")), "contract_uom_id": c.get("uom_id"),
                            "contract_price": c.get("net_contract_price") if show_price else None,
                            "contract_price_base": _r(float(c.get("net_contract_price") or 0) / f, 4) if (show_price and f) else None})
            if last:
                row.update({"last_price_base": last["unit_net_price_base"], "last_price": last["unit_net_price"], "last_unit": last["unit"], "last_uom_id": last.get("uom_id"), "last_comparable": last["comparable"],
                            "last_qty": last["qty"], "last_po_date": last["date"], "last_po_no": last["po_no"], "last_po_id": last["po_id"]})
            row["diff_pct"], row["diff_label"] = diff_info(row.get("contract_price_base"), row.get("last_price_base"))
            ref = row.get("contract_price_base") if row.get("contract_price_base") is not None else row.get("last_price_base")
            row["_ref"] = ref
            rows.append(row)
        priced = [r["_ref"] for r in rows if r["_ref"] is not None]
        low = min(priced) if len(priced) >= 2 else None
        for r in rows:
            r["is_lowest"] = bool(low is not None and r["_ref"] is not None and r["_ref"] <= low + EPS)
            r["reference_price_base"] = r.pop("_ref")
        rows.sort(key=lambda r: (_ORDER[r["status"]], str(r.get("supplier_name") or "").lower()))
        return {"ro_line_id": rl["id"], "ro_id": head.get("id"), "ro_no": head.get("no"),
                "division_id": head.get("division_id"), "division_name": (div or {}).get("name"),
                "item_id": rl.get("item_id"), "item_code": item.get("code"), "item_name": item.get("name"),
                "qty_ro": _r(rl.get("qty")), "sudah_po": st["ordered_other"], "sisa_po": st["remaining"],
                "base_unit": base_label, "base_uom_id": item.get("base_uom_id"), "date": d, "price_visible": bool(show_price),
                "primary_supplier_id": primary_id, "contract_supplier_count": sum(1 for r in rows if r["is_contract"]),
                "suppliers": rows}

    @app.get("/api/pull/ro-for-po/price-history", tags=["po-price-insight"])
    async def ro_price_history(ro_line_id: str, supplier_id: str, limit: int = 5, user=Depends(server.current_user)):
        rl, _head, alw = await _scoped_line(server, ro_line_id, user)
        if not server.has_perm(user, "view_purchase_price"):
            raise HTTPException(403, NO_PRICE)
        sup = await server.db.suppliers.find_one({"id": supplier_id}, {"_id": 0}) if supplier_id else None
        if not sup:
            raise HTTPException(404, SUP_NOT_FOUND)
        item = await server.db.items.find_one({"id": rl.get("item_id")}, {"_id": 0}) or {"id": rl.get("item_id")}
        rows = [r for r in await approved_purchases(server, item, alw, await _uoms()) if r["supplier_id"] == supplier_id]
        n = max(1, min(int(limit or 5), 5))
        for r in rows:
            r["supplier_name"] = sup.get("name")
        return {"supplier_id": supplier_id, "supplier_name": sup.get("name"), "count": len(rows), "rows": rows[:n]}

    server.logger.info("PO price insight (Tarik RO) layer installed")
