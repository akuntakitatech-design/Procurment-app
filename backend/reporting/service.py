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
    Snapshot (tidak dipengaruhi periode); ikut filter Divisi dashboard. Nilai Persediaan = Σ item_warehouse.total_value
    dari engine valuation/MWA existing, hanya bila berhak `view_purchase_price`."""
    import stock_summary as SS
    try:
        res = await SS.compute(server, user, division_id=f.division_id or "", active="Aktif", with_value=bool(perm["price"]))
    except Exception:  # noqa: BLE001 — bagian opsional, jangan gagalkan dashboard
        return None
    return {"stock": SS.dashboard_stock(res["summary"]), "warehouse_count": res["warehouse_count"],
            "inventory_value": res.get("inventory_value") if perm["price"] else None}


async def build(server, user, date_from=None, date_to=None, division_id=None, project_id=None, supplier_id=None, period=None):
    t0 = time.perf_counter()
    f = S.resolve_filters(server, user, date_from, date_to, division_id, project_id, supplier_id, period)
    perm = S.permissions(server, user)
    t_lo, _t_hi = C.trend_window(f)
    # PO dimuat sekali untuk rentang gabungan periode KPI + jendela tren 12 bulan
    lo = min(f.date_from, t_lo) if f.date_from else None
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
    po_rows = [r for r in po_all if S.in_period(r, "date", f) and S.match_dims(r, f)]
    procurement = P.kpis(po_rows, mro_rows or [], ro_rows or [], f, perm) if perm["po"] else None
    finance = None
    invs = dos = None
    if perm["invoice"]:
        invs, dos = F.filter_invoices(invs_all or [], f), F.filter_dos(dos_all or [], f)
        dps = F.filter_dps(dps_all or [], f, {r["id"]: r for r in po_all}) if dps_all is not None else None
        finance = F.kpis(invs, dos, dps)
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
        "attention": A.build(po_rows if perm["po"] else [], invs, dos, f, perm),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timing_ms": {"load": round((t_load - t0) * 1000, 1), "total": round((time.perf_counter() - t0) * 1000, 1),
                      "po_rows": len(po_all)},
    }


# ------------------------------------------------------------------ drill-down list (rf_* query params)
async def apply_list_filters(server, module, rows, qp):
    """Filter ringan & backward-compatible untuk list existing: predikat SAMA dengan kartu Dashboard.
    rf_kind, rf_division_id, rf_project_id, rf_supplier_id (tanggal tetap via date_from/date_to existing)."""
    f = S.Filters(division_id=qp.get("rf_division_id") or None, project_id=qp.get("rf_project_id") or None,
                  supplier_id=qp.get("rf_supplier_id") or None, today=S.today().isoformat())
    rows = [r for r in rows if S.match_dims(r, f, supplier=module not in ("mro",))]
    kind = qp.get("rf_kind")
    if not kind:
        return rows
    if module == "po" and kind in P.PO_KINDS:
        return [r for r in rows if P.PO_KINDS[kind](r, f.today)]
    if module == "invoice" and kind in F.INV_KINDS:
        return [r for r in rows if F.INV_KINDS[kind](r)]
    if module == "do_billing" and kind in F.DO_KINDS:
        return [r for r in rows if F.DO_KINDS[kind](r)]
    if module in ("mro", "ro") and kind == "open":
        import pull_source_eligibility_layer as PSE
        elig = {d["id"] for d in await getattr(server.db, module).find(PSE._request_query(), {"_id": 0, "id": 1}).to_list(200000)}
        ids = await P.outstanding_doc_ids(server, module, [r["id"] for r in rows if r.get("id") in elig])
        return [r for r in rows if r.get("id") in ids]
    return rows
