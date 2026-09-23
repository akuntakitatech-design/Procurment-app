"""Division-aware report/control hardening for limited tenant users."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

import report_trace_detail


def _find_route(app, path: str, method: str):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _global(server, user: dict) -> bool:
    return bool(server.is_global(user))


def _divisions(user: dict) -> set[str]:
    return {str(x) for x in (user.get("divisions") or []) if x}


def _warehouses(server, user: dict) -> set[str]:
    if _global(server, user) or "view_all_warehouse" in (user.get("permissions") or []):
        return set()
    return {str(x) for x in (user.get("warehouses") or []) if x}


def _division_allowed(server, user: dict, division_id) -> bool:
    return _global(server, user) or (bool(division_id) and str(division_id) in _divisions(user))


def _division_query(server, user: dict) -> dict:
    if _global(server, user):
        return {}
    divs = list(_divisions(user))
    return {"division_id": {"$in": divs}} if divs else {"division_id": "__none__"}


async def _visible_item_ids(server, user: dict) -> set[str]:
    q = {} if _global(server, user) else _division_query(server, user)
    rows = await server.db.items.find(q, {"_id": 0, "id": 1}).to_list(50000)
    return {str(x.get("id")) for x in rows if x.get("id")}


async def _visible_mro_ids(server, user: dict) -> set[str]:
    q = {} if _global(server, user) else _division_query(server, user)
    rows = await server.db.mro.find(q, {"_id": 0, "id": 1}).to_list(50000)
    return {str(x.get("id")) for x in rows if x.get("id")}


async def _doc_visible(server, user: dict, collection: str, did: str) -> bool:
    if _global(server, user):
        return True
    doc = await getattr(server.db, collection).find_one({"id": did}, {"_id": 0, "division_id": 1})
    return bool(doc and _division_allowed(server, user, doc.get("division_id")))


async def _loan_visible(server, user: dict, loan_id: str) -> bool:
    if _global(server, user):
        return True
    item_ids = await _visible_item_ids(server, user)
    if not item_ids:
        return False
    line = await server.db.loan_lines.find_one(
        {"loan_id": loan_id, "item_id": {"$in": list(item_ids)}},
        {"_id": 0, "id": 1},
    )
    return bool(line)


async def _audit_visible(server, user: dict, row: dict) -> bool:
    if _global(server, user):
        return True
    if str(row.get("user") or "").lower() == str(user.get("email") or "").lower():
        return True
    entity = str(row.get("entity") or "").lower()
    eid = row.get("entity_id")
    if not eid:
        return False
    mapping = {
        "mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi",
        "adjustment": "adjustments", "opname": "opname",
    }
    if entity in mapping:
        return await _doc_visible(server, user, mapping[entity], str(eid))
    if entity == "loan":
        return await _loan_visible(server, user, str(eid))
    if entity == "loan_return":
        ret = await server.db.loan_returns.find_one({"id": eid}, {"_id": 0, "loan_id": 1})
        return bool(ret and await _loan_visible(server, user, str(ret.get("loan_id"))))
    if entity in ("items", "units"):
        col = server.db.items if entity == "items" else server.db.units
        doc = await col.find_one({"id": eid}, {"_id": 0, "division_id": 1})
        return bool(doc and _division_allowed(server, user, doc.get("division_id")))
    if entity == "divisions":
        return str(eid) in _divisions(user)
    return False


def install(server):
    app = server.app

    # Detailed MRO report and Excel export share this builder.
    original_build_rows = report_trace_detail._build_rows

    async def scoped_build_rows(server_arg, date_from=None, date_to=None, user=None):
        rows = await original_build_rows(server_arg, date_from, date_to, user)
        if not user or _global(server, user):
            return rows
        visible = await _visible_mro_ids(server, user)
        return [r for r in rows if str(r.get("mro_id")) in visible]

    report_trace_detail._build_rows = scoped_build_rows

    # Base dashboard.
    route = _find_route(app, "/api/dashboard", "GET")
    if route:
        original_dashboard = route.endpoint
        app.router.routes.remove(route)

        async def dashboard(user=Depends(server.current_user)):
            if _global(server, user):
                return await original_dashboard(user=user)
            item_ids = await _visible_item_ids(server, user)
            wh_ids = _warehouses(server, user)
            iw_q = {"item_id": {"$in": list(item_ids)}} if item_ids else {"item_id": "__none__"}
            if wh_ids:
                iw_q["warehouse_id"] = {"$in": list(wh_ids)}
            iws = await server.db.item_warehouse.find(iw_q, {"_id": 0}).to_list(50000)
            out_of = low = over = normal = 0
            for iw in iws:
                cur = float(iw.get("current_stock") or 0)
                mn = float(iw.get("min_stock") or 0)
                mx = float(iw.get("max_stock") or 0)
                if cur <= 0:
                    out_of += 1
                elif cur <= mn:
                    low += 1
                elif mx and cur > mx:
                    over += 1
                else:
                    normal += 1
            scope = _division_query(server, user)
            def scoped(extra):
                return {**scope, **extra}
            today = server.now_iso()[:10]
            loans_open = 0
            for loan in await server.db.loans.find({}, {"_id": 0, "id": 1}).to_list(10000):
                if not await _loan_visible(server, user, loan.get("id")):
                    continue
                lines = await server.db.loan_lines.find({"loan_id": loan.get("id")}, {"_id": 0}).to_list(2000)
                if any(str(x.get("item_id")) in item_ids and float(x.get("qty") or 0) - float(x.get("returned") or 0) > 1e-9 for x in lines):
                    loans_open += 1
            warehouse_count = await server.db.warehouses.count_documents({"id": {"$in": list(wh_ids)}}) if wh_ids else await server.db.warehouses.count_documents({})
            user_count = await server.db.users.count_documents({"divisions": {"$in": list(_divisions(user))}}) if _divisions(user) else 0
            return {
                "stock": {"out_of_stock": out_of, "low_stock": low, "overstock": over, "normal": normal, "total": len(iws)},
                "mro_open": await server.db.mro.count_documents(scoped({"submitted": True, "cancelled": {"$ne": True}})),
                "ro_open": await server.db.ro.count_documents(scoped({"submitted": True, "cancelled": {"$ne": True}})),
                "po_waiting_approval": await server.db.po.count_documents(scoped({"status": "Waiting Approval"})),
                "po_outstanding": await server.db.po.count_documents(scoped({"status": {"$in": ["Approved", "Partially Received"]}})),
                "do_today": await server.db.do.count_documents(scoped({"date": {"$gte": today}})),
                "mi_today": await server.db.mi.count_documents(scoped({"date": {"$gte": today}})),
                "loan_outstanding": loans_open,
                "counts": {"items": len(item_ids), "warehouses": warehouse_count, "suppliers": await server.db.suppliers.count_documents({}), "users": user_count},
            }

        app.add_api_route("/api/dashboard", dashboard, methods=["GET"], tags=["report-control-scope"])

    # Inventory ledger.
    route = _find_route(app, "/api/inventory/ledger", "GET")
    if route:
        original_ledger = route.endpoint
        app.router.routes.remove(route)

        async def ledger(item_id: str = None, warehouse_id: str = None, limit: int = 500, user=Depends(server.current_user)):
            rows = await original_ledger(user=user, item_id=item_id, warehouse_id=warehouse_id, limit=limit)
            if _global(server, user):
                return rows
            item_ids = await _visible_item_ids(server, user)
            wh_ids = _warehouses(server, user)
            return [r for r in rows if str(r.get("item_id")) in item_ids and (not wh_ids or str(r.get("warehouse_id")) in wh_ids)]

        app.add_api_route("/api/inventory/ledger", ledger, methods=["GET"], tags=["report-control-scope"])

    # Inventory position.
    route = _find_route(app, "/api/inventory/position", "GET")
    if route:
        original_position = route.endpoint
        app.router.routes.remove(route)

        async def position(user=Depends(server.current_user)):
            rows = await original_position(user=user)
            if _global(server, user):
                return rows
            item_ids = await _visible_item_ids(server, user)
            wh_ids = _warehouses(server, user)
            return [r for r in rows if str(r.get("item_id")) in item_ids and (not wh_ids or str(r.get("warehouse_id")) in wh_ids)]

        app.add_api_route("/api/inventory/position", position, methods=["GET"], tags=["report-control-scope"])

    # Direct traceability.
    route = _find_route(app, "/api/traceability/{mro_id:path}", "GET")
    if route:
        original_traceability = route.endpoint
        app.router.routes.remove(route)

        async def traceability(mro_id: str, user=Depends(server.current_user)):
            doc = await server.db.mro.find_one({"id": mro_id}, {"_id": 0})
            if not doc:
                doc = await server.db.mro.find_one({"no": mro_id}, {"_id": 0})
            if not doc:
                raise HTTPException(404, "MRO tidak ditemukan")
            if not _division_allowed(server, user, doc.get("division_id")):
                raise HTTPException(403, "Laporan MRO berada di divisi lain")
            return await original_traceability(mro_id=mro_id, user=user)

        app.add_api_route("/api/traceability/{mro_id:path}", traceability, methods=["GET"], tags=["report-control-scope"])

    # Lead time.
    route = _find_route(app, "/api/reports/lead-time", "GET")
    if route:
        original_lead = route.endpoint
        app.router.routes.remove(route)

        async def lead_time(user=Depends(server.current_user)):
            rows = await original_lead(user=user)
            if _global(server, user):
                return rows
            docs = await server.db.mro.find(_division_query(server, user), {"_id": 0, "no": 1}).to_list(50000)
            visible = {str(x.get("no")) for x in docs if x.get("no")}
            return [r for r in rows if str(r.get("mro_no")) in visible]

        app.add_api_route("/api/reports/lead-time", lead_time, methods=["GET"], tags=["report-control-scope"])

    # Unit usage.
    route = _find_route(app, "/api/reports/unit-usage", "GET")
    if route:
        app.router.routes.remove(route)

        async def unit_usage(unit_id: str = None, user=Depends(server.current_user)):
            server.require(user, "view")
            q = {"qty_out": {"$gt": 0}, "doc_type": "MI"}
            if unit_id:
                q["unit_id"] = unit_id
            if not _global(server, user):
                divs = list(_divisions(user))
                q["division_id"] = {"$in": divs} if divs else "__none__"
                wh_ids = _warehouses(server, user)
                if wh_ids:
                    q["warehouse_id"] = {"$in": list(wh_ids)}
            rows = await server.db.stock_ledger.find(q, {"_id": 0}).to_list(50000)
            im = {i["id"]: i for i in await server.db.items.find({}, {"_id": 0}).to_list(10000)}
            um = {u["id"]: u for u in await server.db.units.find({}, {"_id": 0}).to_list(5000)}
            agg = defaultdict(float)
            for r in rows:
                if r.get("unit_id"):
                    agg[(r.get("unit_id"), r.get("item_id"))] += float(r.get("qty_out") or 0)
            return [{"unit_id": k[0], "unit_name": um.get(k[0], {}).get("name"), "plate_no": um.get(k[0], {}).get("plate_no"), "item_code": im.get(k[1], {}).get("code"), "item_name": im.get(k[1], {}).get("name"), "unit": im.get(k[1], {}).get("unit"), "qty": v} for k, v in agg.items()]

        app.add_api_route("/api/reports/unit-usage", unit_usage, methods=["GET"], tags=["report-control-scope"])

    # Search.
    route = _find_route(app, "/api/search", "GET")
    if route:
        original_search = route.endpoint
        app.router.routes.remove(route)

        async def search(q: str, user=Depends(server.current_user)):
            rows = await original_search(q=q, user=user)
            if _global(server, user):
                return rows
            mapping = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi"}
            out = []
            item_ids = await _visible_item_ids(server, user)
            for row in rows:
                kind = str(row.get("type") or "")
                rid = str(row.get("id") or "")
                if kind in mapping:
                    if await _doc_visible(server, user, mapping[kind], rid):
                        out.append(row)
                elif kind == "items":
                    if rid in item_ids:
                        out.append(row)
                elif kind == "units":
                    unit = await server.db.units.find_one({"id": rid}, {"_id": 0, "division_id": 1})
                    if unit and _division_allowed(server, user, unit.get("division_id")):
                        out.append(row)
                else:
                    out.append(row)
            return out[:60]

        app.add_api_route("/api/search", search, methods=["GET"], tags=["report-control-scope"])

    # Notification mutations.
    route = _find_route(app, "/api/notifications/{nid}/read", "POST")
    if route:
        app.router.routes.remove(route)

        async def read_notification(nid: str, user=Depends(server.current_user)):
            row = await server.db.notifications.find_one({"id": nid}, {"_id": 0})
            if not row:
                raise HTTPException(404, "Notifikasi tidak ditemukan")
            if not _global(server, user) and row.get("division") is not None and str(row.get("division")) not in _divisions(user):
                raise HTTPException(403, "Notifikasi berada di divisi lain")
            await server.db.notifications.update_one({"id": nid}, {"$set": {"read": True}})
            return {"ok": True}

        app.add_api_route("/api/notifications/{nid}/read", read_notification, methods=["POST"], tags=["report-control-scope"])

    route = _find_route(app, "/api/notifications/read-all", "POST")
    if route:
        app.router.routes.remove(route)

        async def read_all_notifications(user=Depends(server.current_user)):
            q = {}
            if not _global(server, user):
                divs = list(_divisions(user))
                q = {"$or": [{"division": {"$in": divs}}, {"division": None}]}
            await server.db.notifications.update_many(q, {"$set": {"read": True}})
            return {"ok": True}

        app.add_api_route("/api/notifications/read-all", read_all_notifications, methods=["POST"], tags=["report-control-scope"])

    # Audit.
    route = _find_route(app, "/api/audit", "GET")
    if route:
        original_audit = route.endpoint
        app.router.routes.remove(route)

        async def audit_list(entity: str = None, entity_id: str = None, limit: int = 300, user=Depends(server.current_user)):
            if _global(server, user):
                return await original_audit(user=user, entity=entity, entity_id=entity_id, limit=limit)
            rows = await original_audit(user=user, entity=entity, entity_id=entity_id, limit=min(max(limit * 5, 300), 1500))
            out = []
            for row in rows:
                if await _audit_visible(server, user, row):
                    out.append(row)
                    if len(out) >= limit:
                        break
            return out

        app.add_api_route("/api/audit", audit_list, methods=["GET"], tags=["report-control-scope"])

    # Premium dashboard: PO values were already scoped; attention/recent were tenant-wide.
    route = _find_route(app, "/api/dashboard-premium", "GET")
    if route:
        original_premium = route.endpoint
        app.router.routes.remove(route)

        async def dashboard_premium(user=Depends(server.current_user)):
            data = await original_premium(user=user)
            if _global(server, user):
                return data
            pending = 0
            email = str(user.get("email") or "").lower()
            mapping = {"mro": "mro", "ro": "ro", "po": "po"}
            for task in await server.db.approval_tasks.find({"status": "Pending"}, {"_id": 0}).to_list(20000):
                module = str(task.get("module") or "").lower()
                did = task.get("document_id")
                if str(task.get("approver_email") or "").lower() == email:
                    pending += 1
                elif module in mapping and did and await _doc_visible(server, user, mapping[module], str(did)):
                    pending += 1
            today = datetime.now(timezone.utc).date().isoformat()
            overdue_loans = 0
            item_ids = await _visible_item_ids(server, user)
            for loan in await server.db.loans.find({}, {"_id": 0}).to_list(10000):
                due = str(loan.get("due_date") or "")[:10]
                if not due or due >= today or not await _loan_visible(server, user, loan.get("id")):
                    continue
                lines = await server.db.loan_lines.find({"loan_id": loan.get("id")}, {"_id": 0}).to_list(2000)
                if any(str(x.get("item_id")) in item_ids and float(x.get("qty") or 0) - float(x.get("returned") or 0) > 1e-9 for x in lines):
                    overdue_loans += 1
            recent = []
            for row in await server.db.audit_logs.find({}, {"_id": 0}).sort("at", -1).to_list(80):
                if await _audit_visible(server, user, row):
                    recent.append(row)
                    if len(recent) >= 8:
                        break
            data.setdefault("attention", {})["pending_approvals"] = pending
            data["attention"]["overdue_loans"] = overdue_loans
            data["recent"] = recent
            return data

        app.add_api_route("/api/dashboard-premium", dashboard_premium, methods=["GET"], tags=["report-control-scope"])
