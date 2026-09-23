"""Buyer Contact and supplier-reference support for Purchase Orders.

PO stores a reference to the reusable internal contact master plus a snapshot of
name/position/phone/email. The snapshot keeps historical PO documents stable
when the contact master is edited later.
"""
from copy import deepcopy
from fastapi import Depends, HTTPException


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _snapshot(server, contact_id):
    if not contact_id:
        return {
            "buyer_contact_id": None,
            "buyer_contact_name": None,
            "buyer_contact_position": None,
            "buyer_contact_phone": None,
            "buyer_contact_email": None,
            "buyer_contact_division_id": None,
        }
    row = await server.db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not row:
        raise HTTPException(400, "Buyer Contact tidak ditemukan di Master Kontak Internal")
    return {
        "buyer_contact_id": row.get("id"),
        "buyer_contact_name": row.get("name"),
        "buyer_contact_position": row.get("position") or row.get("role"),
        "buyer_contact_phone": row.get("phone"),
        "buyer_contact_email": row.get("email"),
        "buyer_contact_division_id": row.get("division_id"),
    }


def install(server):
    app = server.app

    create_route = _find_route(app, "/api/po", "POST")
    if create_route:
        original_create = create_route.endpoint
        app.router.routes.remove(create_route)

        async def create_po_with_buyer(body: dict, user=Depends(server.current_user)):
            payload = deepcopy(body or {})
            snap = await _snapshot(server, payload.get("buyer_contact_id"))
            result = await original_create(payload, user)
            did = result.get("id") if isinstance(result, dict) else None
            if did:
                snap.update({
                    "supplier_ref": payload.get("supplier_ref") or "",
                })
                await server.db.po.update_one({"id": did}, {"$set": snap})
                get_route = _find_route(app, "/api/po/{did}", "GET")
                if get_route:
                    return await get_route.endpoint(did, user)
            return result

        app.add_api_route("/api/po", create_po_with_buyer, methods=["POST"], tags=["po-buyer"])

    edit_route = _find_route(app, "/api/transactions/{module}/{did}", "PUT")
    if edit_route:
        original_edit = edit_route.endpoint
        app.router.routes.remove(edit_route)

        async def edit_transaction_with_buyer(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module != "po":
                return await original_edit(module, did, body, user)
            payload = deepcopy(body or {})
            snap = await _snapshot(server, payload.get("buyer_contact_id"))
            before = await server.db.po.find_one({"id": did}, {"_id": 0, "buyer_contact_id": 1, "buyer_contact_name": 1, "delivery_term": 1, "supplier_ref": 1})
            result = await original_edit(module, did, payload, user)
            update = dict(snap)
            if "delivery_term" in payload:
                update["delivery_term"] = payload.get("delivery_term") or ""
            if "supplier_ref" in payload:
                update["supplier_ref"] = payload.get("supplier_ref") or ""
            await server.db.po.update_one({"id": did}, {"$set": update})
            changed_buyer = before and (before.get("buyer_contact_id") != snap.get("buyer_contact_id") or before.get("buyer_contact_name") != snap.get("buyer_contact_name"))
            changed_delivery = before and "delivery_term" in payload and before.get("delivery_term") != (payload.get("delivery_term") or "")
            changed_supplier_ref = before and "supplier_ref" in payload and before.get("supplier_ref") != (payload.get("supplier_ref") or "")
            if changed_buyer or changed_delivery or changed_supplier_ref:
                await server.audit(user, "edit", "po", did, reason="Buyer Contact / Delivery Term / Supplier Ref diperbarui", before=before, after={
                    "buyer_contact_id": snap.get("buyer_contact_id"),
                    "buyer_contact_name": snap.get("buyer_contact_name"),
                    "delivery_term": update.get("delivery_term", before.get("delivery_term") if before else None),
                    "supplier_ref": update.get("supplier_ref", before.get("supplier_ref") if before else None),
                })
            return result

        app.add_api_route("/api/transactions/{module}/{did}", edit_transaction_with_buyer, methods=["PUT"], tags=["po-buyer"])
