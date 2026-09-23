"""Apply supplier master defaults and supplier snapshots to new Purchase Orders."""
from copy import deepcopy
from datetime import datetime, timedelta

from fastapi import Depends


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _eta_from(date_value, lead_days):
    if not date_value or not lead_days:
        return None
    try:
        base = datetime.fromisoformat(str(date_value)[:10])
        return (base + timedelta(days=int(lead_days))).date().isoformat()
    except Exception:
        return None


def install(server):
    app = server.app
    route = _find_route(app, "/api/po", "POST")
    if not route:
        return

    original = route.endpoint
    app.router.routes.remove(route)

    async def create_po_with_supplier_defaults(body: dict, user=Depends(server.current_user)):
        payload = deepcopy(body)
        supplier = None
        supplier_id = payload.get("supplier_id")
        if supplier_id:
            supplier = await server.db.suppliers.find_one({"id": supplier_id}, {"_id": 0})

        if supplier:
            if not payload.get("payment_term") and supplier.get("payment_term"):
                payload["payment_term"] = supplier.get("payment_term")
            if not payload.get("delivery_term"):
                payload["delivery_term"] = supplier.get("delivery_term") or supplier.get("delivery_days") or ""
            if not payload.get("currency"):
                payload["currency"] = supplier.get("currency") or "IDR"
            if not payload.get("eta"):
                eta = _eta_from(payload.get("date"), supplier.get("lead_time_days"))
                if eta:
                    payload["eta"] = eta

            default_tax_id = supplier.get("default_tax_id")
            if default_tax_id:
                for line in payload.get("lines", []) or []:
                    # Empty string means the user explicitly selected Tanpa Pajak.
                    if "tax_id" not in line:
                        line["tax_id"] = default_tax_id

            banks = supplier.get("banks") or []
            if not payload.get("supplier_bank_id") and banks:
                primary = next((b for b in banks if b.get("is_primary")), banks[0])
                payload["supplier_bank_id"] = primary.get("id")

        result = await original(payload, user)
        if not isinstance(result, dict) or not result.get("id"):
            return result

        # PO keeps its own snapshot/default values so later supplier changes do not
        # silently alter historical purchase orders.
        snap = {"delivery_term": payload.get("delivery_term") or ""}
        if supplier:
            banks = supplier.get("banks") or []
            selected_bank = next((b for b in banks if b.get("id") == payload.get("supplier_bank_id")), None)
            snap.update({
                "supplier_category_id": supplier.get("supplier_category_id"),
                "supplier_category_name": supplier.get("supplier_category_name"),
                "supplier_bank_id": selected_bank.get("id") if selected_bank else None,
                "supplier_bank_name": selected_bank.get("bank_name") if selected_bank else None,
                "supplier_bank_account_no": selected_bank.get("account_no") if selected_bank else None,
                "supplier_bank_account_name": selected_bank.get("account_name") if selected_bank else None,
                "supplier_bank_currency": selected_bank.get("currency") if selected_bank else None,
                "supplier_npwp": supplier.get("npwp"),
                "supplier_pkp": bool(supplier.get("pkp")),
            })
        await server.db.po.update_one({"id": result["id"]}, {"$set": snap})

        get_route = _find_route(app, "/api/po/{did}", "GET")
        if get_route:
            return await get_route.endpoint(result["id"], user)
        return result

    app.add_api_route("/api/po", create_po_with_supplier_defaults, methods=["POST"], tags=["supplier"])
