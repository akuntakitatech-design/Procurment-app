"""Header defaults for MRO/RO/PO/DO/MI.

SPK lives at header level. Project/unit/warehouse headers are defaults only; the
actual accounting/reporting dimension remains the value stored on each line.
For PO, tax_inclusive controls whether entered prices already include tax.
"""
from copy import deepcopy
from fastapi import Depends


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _normalized(body):
    out = deepcopy(body or {})
    wh = out.get("default_warehouse_id")
    project = out.get("default_project_id")
    unit = out.get("default_unit_id")
    spk = out.get("spk")
    for line in out.get("lines", []):
        if not line.get("warehouse_id") and wh:
            line["warehouse_id"] = wh
        if not line.get("project_id") and project:
            line["project_id"] = project
        if not line.get("unit_id") and unit:
            line["unit_id"] = unit
        # Kept as a hidden snapshot for backward compatibility with old pull/report
        # logic. SPK is no longer edited per item in the UI.
        if spk:
            line["spk"] = spk
    return out


async def _save_header(server, collection, did, body):
    fields = {
        "spk": body.get("spk"),
        "default_warehouse_id": body.get("default_warehouse_id"),
        "default_project_id": body.get("default_project_id"),
        "default_unit_id": body.get("default_unit_id"),
    }
    # RO keeps the relevant planning context inherited from MRO so users do not
    # have to re-enter it and downstream documents can carry the same context.
    if collection == "ro":
        fields["department"] = body.get("department")
        fields["need_date"] = body.get("need_date")
    if collection == "po":
        fields["tax_inclusive"] = bool(body.get("tax_inclusive", False))
        fields["supplier_bank_id"] = body.get("supplier_bank_id")
        fields["default_tax_id"] = body.get("default_tax_id")
    await getattr(server.db, collection).update_one({"id": did}, {"$set": fields})


async def _recalc_po(server, did, inclusive):
    grand = 0.0
    lines = await server.db.po_lines.find({"po_id": did}, {"_id": 0}).to_list(2000)
    for line in lines:
        qty = float(line.get("qty") or 0)
        price = float(line.get("price") or 0)
        discount = float(line.get("discount") or 0)
        rate = float(line.get("tax") or 0)
        gross = qty * price
        net = max(0.0, gross - discount)
        if inclusive and rate:
            dpp = net / (1.0 + rate / 100.0)
            tax_amount = net - dpp
            total = net
        else:
            dpp = net
            tax_amount = dpp * rate / 100.0
            total = dpp + tax_amount
        await server.db.po_lines.update_one({"id": line["id"]}, {"$set": {
            "gross": gross,
            "dpp": dpp,
            "tax_amount": tax_amount,
            "total": total,
            "tax_inclusive": bool(inclusive),
        }})
        grand += total
    await server.db.po.update_one({"id": did}, {"$set": {"grand_total": grand, "tax_inclusive": bool(inclusive)}})


def install(server):
    app = server.app

    async def refresh(kind, did, user):
        route = _find_route(app, f"/api/{kind}/{{did}}", "GET")
        return await route.endpoint(did, user) if route else {"id": did}

    for path, collection in (("/api/mro", "mro"), ("/api/ro", "ro"), ("/api/po", "po"), ("/api/do", "do"), ("/api/mi", "mi")):
        route = _find_route(app, path, "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_create(original_endpoint, kind):
            async def wrapped(body: dict, user=Depends(server.current_user)):
                normalized = _normalized(body)
                result = await original_endpoint(normalized, user)
                if not isinstance(result, dict) or not result.get("id"):
                    return result
                did = result["id"]
                await _save_header(server, kind, did, normalized)
                if kind == "po":
                    await _recalc_po(server, did, bool(normalized.get("tax_inclusive", False)))
                return await refresh(kind, did, user)
            return wrapped

        app.add_api_route(path, make_create(original, collection), methods=["POST"], tags=["documents"])

    # MRO is the only one of these documents that supports direct draft editing.
    route = _find_route(app, "/api/mro/{did}", "PUT")
    if route:
        original = route.endpoint
        app.router.routes.remove(route)

        async def update_mro_defaults(did: str, body: dict, user=Depends(server.current_user)):
            normalized = _normalized(body)
            result = await original(did, normalized, user)
            await _save_header(server, "mro", did, normalized)
            return await refresh("mro", did, user)

        app.add_api_route("/api/mro/{did}", update_mro_defaults, methods=["PUT"], tags=["documents"])
