"""Dashboard Procurement & Finance v1 — GET /api/dashboard/control-center + drill-down filter list.

Dipasang setelah access control / Invoice Vendor / DP Supplier / Approval 2 dan sebelum isolasi tenant.
/api/dashboard dan /api/dashboard-premium existing tidak diubah.
"""
from fastapi import Depends, Query

from reporting import service


def install(server):
    app = server.app

    @app.get("/api/dashboard/control-center", tags=["dashboard"])
    async def control_center(date_from: str = Query(None), date_to: str = Query(None), division_id: str = Query(None),
                             project_id: str = Query(None), supplier_id: str = Query(None), period: str = Query(None),
                             user=Depends(server.current_user)):
        return await service.build(server, user, date_from, date_to, division_id, project_id, supplier_id, period)

    async def report_list_filter(module, rows, qp):
        return await service.apply_list_filters(server, module, rows, qp)

    server.REPORT_LIST_FILTER = report_list_filter
