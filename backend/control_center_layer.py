"""Dashboard Procurement & Finance v1 — GET /api/dashboard/control-center + drill-down filter list.

Dipasang setelah access control / Invoice Vendor / DP Supplier / Approval 2 dan sebelum isolasi tenant.
/api/dashboard dan /api/dashboard-premium existing tidak diubah.
"""
from fastapi import Depends, Query

from reporting import service


def install(server):
    app = server.app
    current_user = Depends(server.current_user)  # singleton dependency (B008)

    @app.get("/api/dashboard/control-center", tags=["dashboard"])
    async def control_center(date_from: str = Query(None), date_to: str = Query(None), division_id: str = Query(None),
                             project_id: str = Query(None), supplier_id: str = Query(None), period: str = Query(None),
                             user=current_user):
        return await service.build(server, user, date_from, date_to, division_id, project_id, supplier_id, period)

    # Drill-down SPK / Kontrak (POSISI: hanya date_to) dan Price Control (TRANSAKSI: date_from + date_to).
    # Fungsi & predikat sama dengan kartu Dashboard -> jumlah/nilai drill = jumlah/nilai KPI.
    @app.get("/api/dashboard/drill/spk", tags=["dashboard"])
    async def drill_spk(date_to: str = Query(None), division_id: str = Query(None), project_id: str = Query(None),
                        kind: str = Query("active"), user=current_user):
        return await service.drill_spk(server, user, date_to, division_id, project_id, kind)

    @app.get("/api/dashboard/drill/vendor-contracts", tags=["dashboard"])
    async def drill_contracts(date_to: str = Query(None), supplier_id: str = Query(None), kind: str = Query("active"),
                              user=current_user):
        return await service.drill_contracts(server, user, date_to, supplier_id, kind)

    @app.get("/api/dashboard/drill/price-control", tags=["dashboard"])
    async def drill_price(date_from: str = Query(None), date_to: str = Query(None), division_id: str = Query(None),
                          project_id: str = Query(None), supplier_id: str = Query(None), status: str = Query("all"),
                          period: str = Query(None), user=current_user):
        return await service.drill_price(server, user, date_from, date_to, division_id, project_id, supplier_id, status, period)

    async def report_list_filter(module, rows, qp):
        return await service.apply_list_filters(server, module, rows, qp)

    server.REPORT_LIST_FILTER = report_list_filter
