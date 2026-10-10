"""Orkestrasi Dashboard Procurement & Finance (GET /api/dashboard/control-center).

Strategi query: setiap sumber dimuat SEKALI (batch) lalu dihitung di memori untuk semua kartu/chart/tabel;
sumber independen dimuat paralel. Tidak ada query per kartu / per PO / per invoice.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from . import attention as A
from . import charts as C
from . import finance as F
from . import price_control as PC
from . import procurement as P
from . import scope as S
from . import spk as SPK


async def _none():
    return None


async def _inventory(server, user, f, perm):
    """KPI Persediaan dari ringkasan canonical per BARANG aktif (stock_summary = Master Barang = Inventory).
    Jumlah/status stok = snapshot hari ini; ikut filter Divisi dashboard. Nilai Persediaan = engine valuation/MWA existing
    PER TANGGAL AKHIR FILTER (valuation ledger; hari ini = Valuation Summary), hanya bila berhak `view_purchase_price`."""
    import stock_summary as SS
    try:
        res = await SS.compute(server, user, division_id=f.division_id or "", active="Aktif", with_value=bool(perm["price"]),
                               value_as_of=f.date_to)
    except Exception:  # noqa: BLE001 — bagian opsional, jangan gagalkan dashboard
        return None
    return {"stock": SS.dashboard_stock(res["summary"]), "warehouse_count": res["warehouse_count"],
            "inventory_value": res.get("inventory_value") if perm["price"] else None,
            "inventory_value_as_of": res.get("inventory_value_as_of") if perm["price"] else None,
            "unvalued_items": res.get("unvalued_items") if perm["price"] else None,
            "unreconstructable_items": res.get("unreconstructable_items") if perm["price"] else None,
            "unreconstructable_pools": res.get("unreconstructable_pools") if perm["price"] else None}


async def _spk_section(server, user, f, perm, cut):
    """SPK & Budget Control — posisi s/d cut-off; nominal & daftar SPK hanya bila spk:view (tidak dikirim bila tidak)."""
    try:
        data = await SPK.load(server)
    except Exception:  # noqa: BLE001 — bagian opsional, jangan gagalkan dashboard
        return None
    return SPK.compute(data, f, cut, user=user, server=server, with_value=bool(perm["spk"]))


def price_visible(perm):
    """Nominal harga kontrak / harga PO / selisih: vendor_contract:view AND view_purchase_price (bukan OR)."""
    return bool(perm["vendor_contract"] and perm["price"])


async def _item_names(rows):
    if rows:
        import doc_procurement
        items = (await doc_procurement.maps())["items"]
        for r in rows:
            it = items.get(r.get("item_id")) or {}
            r.update(item_name=r.get("item_name") or it.get("name"), item_code=it.get("code"))
    return rows


async def _contract_section(server, user, f, perm, cut, po_rows):
    """Kontrak Harga Vendor: status kontrak (posisi s/d cut-off) + Price Control PO Approved final (transaksi periode)."""
    pick = getattr(server, "pick_vendor_contract_price", None)
    try:
        data = await PC.load(server, [r["id"] for r in po_rows] if perm["po"] and pick else [])
    except Exception:  # noqa: BLE001
        return None
    with_value = price_visible(perm)
    out = {"as_of": cut, "period": {"date_from": f.date_from, "date_to": f.date_to},
           "contracts": PC.contract_kpis(data["contracts"], data["items"], f, cut, pick), "price_control": None,
           "with_value": with_value}
    if perm["po"] and pick:
        pc = PC.price_control(po_rows, data, pick, with_value)
        pc.pop("_lines", None)
        await _item_names(pc["exceptions"])
        out["price_control"] = pc
    return out


async def _po_period_rows(server, user, f, perm):
    """PO aktivitas periode (predikat SAMA dengan build): tanggal date_from..date_to + dimensi + status pada cut-off."""
    po_all = await P.load_po_rows(server, user, None, f.date_to, perm["price"]) or []
    rows = [r for r in po_all if S.in_period(r, "date", f) and S.match_dims(r, f)]
    if S.is_historical(f) and rows:
        from . import history as H
        at = {r["id"]: r for r in await H.po_rows_as_of(server, rows, S.asof(f))}
        rows = [at.get(r["id"], r) for r in rows]
    return rows


# ------------------------------------------------------------------ drill-down SPK / Kontrak / Price Control
async def drill_spk(server, user, date_to, division_id, project_id, kind):
    """Daftar SPK posisi s/d date_to — fungsi & predikat SAMA dengan KPI (parity). Wajib spk:view."""
    server.require(user, "spk:view")
    if kind not in SPK.DRILL_KINDS:
        kind = "active"
    f = S.resolve_filters(server, user, None, date_to or S.today().isoformat(), division_id, project_id, None, None)
    cut = S.asof(f)
    rows = SPK.rows_at(await SPK.load(server), f, cut, user, server)
    sel = SPK.drill(rows, kind)
    return {"as_of": cut, "kind": kind, "count": len(sel), "rows": [SPK.public(x, True) for x in sel],
            "totals": {k: sum(x[k] for x in sel) for k in SPK.VALUE_KEYS}}


async def drill_contracts(server, user, date_to, supplier_id, kind):
    """Daftar kontrak posisi s/d date_to (parity dengan KPI). Wajib vendor_contract:view."""
    server.require(user, "vendor_contract:view")
    if kind not in PC.CONTRACT_KINDS:
        kind = "active"
    f = S.resolve_filters(server, user, None, date_to or S.today().isoformat(), None, None, supplier_id, None)
    cut = S.asof(f)
    data = await PC.load(server, [])
    sel = PC.contract_drill(PC.contract_rows(data["contracts"], data["items"], f, cut), kind)
    return {"as_of": cut, "kind": kind, "count": len(sel), "rows": sel}


async def drill_price(server, user, date_from, date_to, division_id, project_id, supplier_id, status, period=None):
    """Baris Price Control transaksi periode date_from..date_to (parity dengan KPI). Nominal: vendor_contract:view AND
    view_purchase_price; tanpa itu hanya status / count."""
    perm = S.permissions(server, user)
    if not perm["po"]:
        raise HTTPException(403, "Tidak memiliki izin melihat PO.")
    if status not in (*PC.PRICE_STATUSES, "all"):
        status = "all"
    f = S.resolve_filters(server, user, date_from, date_to, division_id, project_id, supplier_id, period)
    po_rows = await _po_period_rows(server, user, f, perm)
    pick = server.pick_vendor_contract_price
    data = await PC.load(server, [r["id"] for r in po_rows])
    lines = PC.price_lines(po_rows, data, pick)
    sel = PC.price_drill(lines, status)
    wv = price_visible(perm)
    out = {"period": {"date_from": f.date_from, "date_to": f.date_to}, "status": status, "with_value": wv,
           "po_count": len({r["po_id"] for r in sel}), "count": len(sel),
           "rows": await _item_names([PC.redact(dict(r), wv) for r in sel])}
    if wv:
        out["diff_value"] = round(sum(r["diff"] or 0 for r in sel if r["status"] == "over"), 2)
    return out


async def build(server, user, date_from=None, date_to=None, division_id=None, project_id=None, supplier_id=None, period=None):
    t0 = time.perf_counter()
    f = S.resolve_filters(server, user, date_from, date_to, division_id, project_id, supplier_id, period)
    perm = S.permissions(server, user)
    _t_lo, _t_hi = C.trend_window(f)
    # PO dimuat sekali untuk rentang gabungan periode KPI + jendela tren 12 bulan
    lo = None  # saldo/outstanding membutuhkan seluruh PO s/d tanggal akhir filter (termasuk periode sebelumnya)
    hi = max(f.date_to, _t_hi) if f.date_to else None
    VI = getattr(server, "VENDOR_INVOICE_REPORT", None)
    DP = getattr(server, "SUPPLIER_DP_REPORT", None)
    po_all, mro_rows, ro_rows, invs_all, dos_all, dps_all, inventory = await asyncio.gather(
        P.load_po_rows(server, user, lo, hi, perm["price"]) if perm["po"] else _none(),
        P.open_requests(server, user, "mro", f) if perm["mro"] else _none(),
        P.open_requests(server, user, "ro", f) if perm["ro"] else _none(),
        VI["invoices"](user) if perm["invoice"] and VI else _none(),
        VI["do_billing"](user) if perm["invoice"] and VI else _none(),
        DP(user=user) if perm["supplier_dp"] and DP else _none(),
        _inventory(server, user, f, perm))
    t_load = time.perf_counter()
    po_all = po_all or []
    hist, cut = S.is_historical(f), S.asof(f)
    po_rows = [r for r in po_all if S.in_period(r, "date", f) and S.match_dims(r, f)]      # aktivitas periode
    po_backlog = [r for r in po_all if S.upto(r, "date", f) and S.match_dims(r, f)]        # saldo s/d tanggal akhir
    if hist and perm["po"]:  # status approval / penerimaan PADA cut-off (bukan status saat ini)
        from . import history as H
        at = {r["id"]: r for r in await H.po_rows_as_of(server, po_backlog, cut)}
        po_backlog = [at.get(r["id"], r) for r in po_backlog]
        po_rows = [at.get(r["id"], r) for r in po_rows]
    procurement = P.kpis(po_backlog, po_rows, mro_rows or [], ro_rows or [], f, perm) if perm["po"] else None
    finance = None
    invs = dos = None
    if perm["invoice"]:
        invs, dos = F.filter_invoices(invs_all or [], f), F.filter_dos(dos_all or [], f)
        po_by_id = {r["id"]: r for r in po_all}
        dps = F.filter_dps(dps_all or [], f, po_by_id) if dps_all is not None else None
        # Aktivitas "DP Sudah Dibayar": pembayaran DP bertanggal bayar DI DALAM periode
        dps_period = await F.dps_as_of(server, F.filter_dps(dps_all, f, po_by_id, dated=False), f.date_to or "9999-12-31",
                                       lo=f.date_from) if dps is not None else None
        if hist:  # posisi historis persis per cut-off: pembayaran/alokasi setelah cut-off tidak mengurangi saldo
            invs, dos = await F.invoices_as_of(server, invs, cut), await F.dos_as_of(server, dos, cut)
            dps = await F.dps_as_of(server, dps, cut) if dps is not None else None
        finance = F.kpis(invs, dos, dps, invs_period=F.filter_invoices_period(invs_all or [], f), dps_period=dps_period)
    spk_sec, contract_sec = await asyncio.gather(
        _spk_section(server, user, f, perm, cut) if (perm["spk"] or perm["po"]) else _none(),
        _contract_section(server, user, f, perm, cut, po_rows) if (perm["vendor_contract"] or perm["po"]) else _none())
    charts = {"trend": C.trend(po_all, invs_all if perm["invoice"] else None, f, perm),
              "composition": C.composition(po_rows) if perm["po"] else None}
    return {
        "filters": f.dict(),
        "permissions": perm,
        "scope": {"divisions": S.division_scope(server, user)},
        "procurement": procurement,
        "finance": finance,
        "inventory": inventory,
        "charts": charts,
        "supplier_rank": C.supplier_rank(po_rows, perm) if perm["po"] else None,
        "attention": A.build(po_backlog if perm["po"] else [], invs, dos, f, perm),
        "spk": spk_sec,
        "vendor_contract": contract_sec,
        "as_of": cut, "historical": hist,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timing_ms": {"load": round((t_load - t0) * 1000, 1), "total": round((time.perf_counter() - t0) * 1000, 1),
                      "po_rows": len(po_all)},
    }


# ------------------------------------------------------------------ drill-down list (rf_* query params)
async def apply_list_filters(server, module, rows, qp):
    """Filter ringan & backward-compatible untuk list existing: predikat SAMA dengan kartu Dashboard.
    rf_kind, rf_division_id, rf_project_id, rf_supplier_id (tanggal tetap via date_from/date_to existing)."""
    td = S.today().isoformat()
    ao = str(qp.get("rf_asof") or "")[:10]
    ao = ao if len(ao) == 10 and ao < td else None  # posisi historis (kartu saldo dari tanggal lampau)
    f = S.Filters(division_id=qp.get("rf_division_id") or None, project_id=qp.get("rf_project_id") or None,
                  supplier_id=qp.get("rf_supplier_id") or None, today=td)
    rows = [r for r in rows if S.match_dims(r, f, supplier=module not in ("mro",))]
    kind = qp.get("rf_kind")
    if not kind:
        return rows
    if module == "po" and kind in P.PO_KINDS:
        if ao:  # posisi historis: status approval/penerimaan PADA cut-off (sama dengan kartu)
            from . import history as H
            at = {r["id"]: r for r in await H.po_rows_as_of(server, [r for r in rows if S.day(r, "date") <= ao], ao)}
            return [r for r in rows if r.get("id") in at and P.PO_KINDS[kind](at[r["id"]], ao)]
        return [r for r in rows if P.PO_KINDS[kind](r, td)]
    if module == "invoice" and kind in F.INV_KINDS:
        if ao:  # posisi historis: hanya invoice <= cut-off, pembayaran/DP efektif <= cut-off, jatuh tempo vs cut-off
            chk = {r["id"]: r for r in await F.invoices_as_of(server, rows, ao)}
            return [r for r in rows if r.get("id") in chk and F.INV_KINDS[kind](chk[r["id"]])]
        return [r for r in rows if F.INV_KINDS[kind](r)]
    if module == "do_billing" and kind in F.DO_KINDS:
        if ao:
            chk = {r["do_id"]: r for r in await F.dos_as_of(server, rows, ao)}
            return [r for r in rows if r.get("do_id") in chk and F.DO_KINDS[kind](chk[r["do_id"]])]
        return [r for r in rows if F.DO_KINDS[kind](r)]
    if module in ("mro", "ro") and kind == "open":
        import pull_source_eligibility_layer as PSE
        elig = {d["id"] for d in await getattr(server.db, module).find(PSE._request_query(), {"_id": 0, "id": 1}).to_list(200000)}
        cand = [r["id"] for r in rows if r.get("id") in elig and (not ao or S.day(r, "date") <= ao)]
        if ao:
            from . import history as H
            ids = await H.outstanding_doc_ids_as_of(server, module, cand, ao)
        else:
            ids = await P.outstanding_doc_ids(server, module, cand)
        return [r for r in rows if r.get("id") in ids]
    return rows
