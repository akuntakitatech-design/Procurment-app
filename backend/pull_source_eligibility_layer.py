"""Robust source eligibility for MRO -> RO / MI, RO -> PO and PO -> DO.

This layer fixes a legacy compatibility gap where list/detail treated request docs
without a `submitted` field as Open, while pull endpoints required
`submitted: true` explicitly. It also centralizes approval/cancel/outstanding
checks and keeps UOM display conversion plus source-header inheritance intact.
"""
from fastapi import Depends, Query

import uom_layer
import source_inheritance_layer
import doc_procurement


WAITING_OR_REJECTED = ["Waiting Approval", "Rejected"]


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _request_query():
    # Legacy request documents may not have `submitted`; list/detail historically
    # treated them as submitted/Open. Keep them eligible unless approval explicitly
    # says they are waiting/rejected.
    return {
        "cancelled": {"$ne": True},
        "approval_status": {"$nin": WAITING_OR_REJECTED},
        "$or": [
            {"submitted": True},
            {"submitted": {"$exists": False}},
        ],
    }


async def _attach_source_header(server, rows, collection, id_key):
    cache = {}
    for row in rows:
        did = row.get(id_key)
        if not did:
            continue
        if did not in cache:
            cache[did] = await getattr(server.db, collection).find_one({"id": did}, {"_id": 0}) or {}
        row["source_header"] = source_inheritance_layer._header(cache[did])
    return rows


async def _mro_rows(server, target_type, user):
    m = await doc_procurement.maps()
    out = []
    docs = await server.db.mro.find(_request_query(), {"_id": 0}).to_list(3000)
    for d in docs:
        lines = await server.db.mro_lines.find({"mro_id": d["id"]}, {"_id": 0}).to_list(2000)
        for line in lines:
            processed = await server.alloc_out(line["id"], target_type)
            outstanding = float(line.get("qty") or 0) - float(processed or 0)
            if outstanding <= 1e-9:
                continue
            doc_procurement.enrich_line(line, m)
            row = {
                "mro_id": d["id"], "mro_no": d.get("no"), "line_id": line["id"],
                "item_id": line.get("item_id"), "item_code": line.get("item_code"),
                "item_name": line.get("item_name"), "unit": line.get("unit"),
                "requested": line.get("qty", 0), "outstanding": outstanding,
                "warehouse_id": line.get("warehouse_id"), "project_id": line.get("project_id"),
                "unit_id": line.get("unit_id"), "warehouse_name": line.get("warehouse_name"),
                "project_name": line.get("project_name"), "unit_name": line.get("unit_name"),
            }
            if target_type == "ro":
                row["processed"] = processed
            else:
                row["issued"] = processed
                row["available"] = await server.stock_balance(line.get("item_id"), line.get("warehouse_id"))
            out.append(row)
    keys = ["requested", "outstanding", "processed"] if target_type == "ro" else ["requested", "issued", "outstanding", "available"]
    out = await uom_layer._convert_pull_rows(server, out, "mro_lines", keys)
    return await _attach_source_header(server, out, "mro", "mro_id")


async def _ro_rows(server, user):
    m = await doc_procurement.maps()
    out = []
    docs = await server.db.ro.find(_request_query(), {"_id": 0}).to_list(3000)
    for d in docs:
        lines = await server.db.ro_lines.find({"ro_id": d["id"]}, {"_id": 0}).to_list(2000)
        for line in lines:
            ordered = await server.alloc_out(line["id"], "po")
            outstanding = float(line.get("qty") or 0) - float(ordered or 0)
            if outstanding <= 1e-9:
                continue
            doc_procurement.enrich_line(line, m)
            srcs = await server.db.allocations.find(
                {"target_line_id": line["id"], "source_type": "mro"}, {"_id": 0}
            ).to_list(100)
            mro_no = None
            if srcs:
                mh = await server.db.mro.find_one({"id": srcs[0].get("source_doc_id")}, {"_id": 0})
                mro_no = (mh or {}).get("no")
            out.append({
                "ro_id": d["id"], "ro_no": d.get("no"), "mro_no": mro_no,
                "line_id": line["id"], "item_id": line.get("item_id"),
                "item_code": line.get("item_code"), "item_name": line.get("item_name"),
                "unit": line.get("unit"), "qty_ro": line.get("qty", 0),
                "ordered": ordered, "outstanding": outstanding,
                "warehouse_id": line.get("warehouse_id"), "project_id": line.get("project_id"),
                "unit_id": line.get("unit_id"), "warehouse_name": line.get("warehouse_name"),
                "project_name": line.get("project_name"), "unit_name": line.get("unit_name"),
                "supplier_id": d.get("supplier_id"),
            })
    out = await uom_layer._convert_pull_rows(server, out, "ro_lines", ["qty_ro", "ordered", "outstanding"])
    return await _attach_source_header(server, out, "ro", "ro_id")


async def _po_rows(server, supplier_id, user):
    m = await doc_procurement.maps()
    out = []
    query = {
        "status": {"$in": ["Approved", "Partially Received"]},
        "cancelled": {"$ne": True},
        "approval_status": {"$nin": WAITING_OR_REJECTED},
    }
    if supplier_id:
        query["supplier_id"] = supplier_id
    docs = await server.db.po.find(query, {"_id": 0}).to_list(3000)
    for d in docs:
        lines = await server.db.po_lines.find({"po_id": d["id"]}, {"_id": 0}).to_list(2000)
        for line in lines:
            received = await server.alloc_out(line["id"], "do")
            outstanding = float(line.get("qty") or 0) - float(received or 0)
            if outstanding <= 1e-9:
                continue
            doc_procurement.enrich_line(line, m)
            out.append({
                "po_id": d["id"], "po_no": d.get("no"), "supplier_id": d.get("supplier_id"),
                "supplier_name": m["suppliers"].get(d.get("supplier_id"), {}).get("name"),
                "line_id": line["id"], "item_id": line.get("item_id"),
                "item_code": line.get("item_code"), "item_name": line.get("item_name"),
                "unit": line.get("unit"), "spk": d.get("spk") or line.get("spk"),
                "qty_po": line.get("qty", 0), "received": received, "outstanding": outstanding,
                "warehouse_id": line.get("warehouse_id"), "project_id": line.get("project_id"),
                "unit_id": line.get("unit_id"), "warehouse_name": line.get("warehouse_name"),
                "project_name": line.get("project_name"), "unit_name": line.get("unit_name"),
            })
    out = await uom_layer._convert_pull_rows(server, out, "po_lines", ["qty_po", "received", "outstanding"])
    return await _attach_source_header(server, out, "po", "po_id")


def install(server):
    app = server.app
    paths = [
        "/api/pull/mro-for-ro",
        "/api/pull/mro-for-mi",
        "/api/pull/ro-for-po",
        "/api/pull/po-for-do",
    ]
    for path in paths:
        route = _find_route(app, path, "GET")
        if route:
            app.router.routes.remove(route)

    async def pull_mro_for_ro(user=Depends(server.current_user)):
        return await _mro_rows(server, "ro", user)

    async def pull_mro_for_mi(user=Depends(server.current_user)):
        return await _mro_rows(server, "mi", user)

    async def pull_ro_for_po(user=Depends(server.current_user)):
        return await _ro_rows(server, user)

    async def pull_po_for_do(supplier_id: str = Query(None), user=Depends(server.current_user)):
        return await _po_rows(server, supplier_id, user)

    app.add_api_route("/api/pull/mro-for-ro", pull_mro_for_ro, methods=["GET"], tags=["pull-source"])
    app.add_api_route("/api/pull/mro-for-mi", pull_mro_for_mi, methods=["GET"], tags=["pull-source"])
    app.add_api_route("/api/pull/ro-for-po", pull_ro_for_po, methods=["GET"], tags=["pull-source"])
    app.add_api_route("/api/pull/po-for-do", pull_po_for_do, methods=["GET"], tags=["pull-source"])
