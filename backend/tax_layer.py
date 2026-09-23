"""Tax-master compatibility layer for Purchase Orders.

Users select a tax master in the UI. The backend resolves the current master rate,
uses that rate for PO calculation, and stores both the stable tax id and a rate/name
snapshot on each PO line so historical documents do not change when the master is edited.
"""
from copy import deepcopy
from fastapi import Depends, HTTPException


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def install(server):
    app = server.app
    route = _find_route(app, "/api/po", "POST")
    if not route:
        return

    original = route.endpoint
    app.router.routes.remove(route)

    async def create_po_with_tax_master(body: dict, user=Depends(server.current_user)):
        normalized = deepcopy(body)
        snapshots = []

        for line in normalized.get("lines", []):
            tax_id = line.get("tax_id")
            if tax_id:
                tax = await server.db.taxes.find_one({"id": tax_id, "is_active": {"$ne": False}}, {"_id": 0})
                if not tax:
                    raise HTTPException(status_code=400, detail="Pajak yang dipilih tidak ditemukan / nonaktif")
                rate = float(tax.get("rate") or 0)
                line["tax"] = rate
                snapshots.append({
                    "tax_id": tax_id,
                    "tax_name": tax.get("name"),
                    "tax_rate": rate,
                })
            else:
                # No tax selected. Legacy numeric tax input is intentionally not
                # accepted from the new UI; keeping this fallback preserves old API callers.
                rate = float(line.get("tax") or 0)
                snapshots.append({
                    "tax_id": None,
                    "tax_name": None,
                    "tax_rate": rate,
                })

        result = await original(normalized, user)
        if not isinstance(result, dict) or not result.get("id"):
            return result

        stored = await server.db.po_lines.find({"po_id": result["id"]}, {"_id": 0}).to_list(1000)
        for row, snap in zip(stored, snapshots):
            await server.db.po_lines.update_one({"id": row["id"]}, {"$set": snap})

        # Return the fully refreshed PO so tax metadata is immediately available.
        refreshed = await server.db.po.find_one({"id": result["id"]}, {"_id": 0})
        if refreshed is None:
            return result

        # Reuse the existing GET handler's enrichment/permission logic.
        get_route = _find_route(app, "/api/po/{did}", "GET")
        if get_route:
            return await get_route.endpoint(result["id"], user)
        return result

    app.add_api_route("/api/po", create_po_with_tax_master, methods=["POST"], tags=["tax"])
