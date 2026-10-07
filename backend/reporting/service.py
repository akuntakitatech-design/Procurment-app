"""Orkestrasi Dashboard Procurement & Finance (GET /api/dashboard/control-center).

Strategi query: setiap sumber dimuat SEKALI (batch) lalu dihitung di memori untuk semua kartu/chart/tabel;
sumber independen dimuat paralel. Tidak ada query per kartu / per PO / per invoice.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from . import attention as A
from . import charts as C
from . import finance as F
from . import procurement as P
from . import scope as S


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
