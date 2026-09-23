"""Expose source-header metadata on MRO -> RO -> PO -> DO / MI pull endpoints.

Header values are convenience defaults only. Project/unit/warehouse stored on the
line remain the final reporting dimensions, so different per-item allocations are
preserved end-to-end.
"""
from fastapi import Depends


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _header(doc):
    doc = doc or {}
    return {
        "id": doc.get("id"),
        "no": doc.get("no"),
        "division_id": doc.get("division_id"),
        "spk": doc.get("spk"),
        "default_warehouse_id": doc.get("default_warehouse_id"),
        "default_project_id": doc.get("default_project_id"),
        "default_unit_id": doc.get("default_unit_id"),
        "requester": doc.get("requester"),
        "department": doc.get("department"),
        "need_date": doc.get("need_date"),
        "supplier_id": doc.get("supplier_id"),
        "payment_term": doc.get("payment_term"),
        "currency": doc.get("currency"),
        "eta": doc.get("eta"),
        "supplier_bank_id": doc.get("supplier_bank_id"),
        "default_tax_id": doc.get("default_tax_id"),
        "tax_inclusive": bool(doc.get("tax_inclusive", False)),
    }


def install(server):
    app = server.app

    async def enrich_rows(rows, collection, id_key):
        cache = {}
        for row in rows or []:
            did = row.get(id_key)
            if not did:
                continue
            if did not in cache:
                cache[did] = await getattr(server.db, collection).find_one({"id": did}, {"_id": 0}) or {}
            row["source_header"] = _header(cache[did])
        return rows

    # Bind every wrapped endpoint through a factory. Do not close over one shared
    # `original` variable: otherwise the last registered route (PO -> DO) is used
    # by all pull endpoints at request time.
    def install_simple_pull(path, collection, id_key):
        route = _find_route(app, path, "GET")
        if not route:
            return
        original_endpoint = route.endpoint
        app.router.routes.remove(route)

        async def wrapped(user=Depends(server.current_user)):
            rows = await original_endpoint(user=user)
            return await enrich_rows(rows, collection, id_key)

        app.add_api_route(path, wrapped, methods=["GET"], tags=["inheritance"])

    install_simple_pull("/api/pull/mro-for-ro", "mro", "mro_id")
    install_simple_pull("/api/pull/mro-for-mi", "mro", "mro_id")
    install_simple_pull("/api/pull/ro-for-po", "ro", "ro_id")

    # PO -> DO has an optional supplier_id query argument.
    route = _find_route(app, "/api/pull/po-for-do", "GET")
    if route:
        original_po_for_do = route.endpoint
        app.router.routes.remove(route)

        async def pull_po_for_do(supplier_id: str = None, user=Depends(server.current_user)):
            rows = await original_po_for_do(supplier_id=supplier_id, user=user)
            return await enrich_rows(rows, "po", "po_id")

        app.add_api_route("/api/pull/po-for-do", pull_po_for_do, methods=["GET"], tags=["inheritance"])
