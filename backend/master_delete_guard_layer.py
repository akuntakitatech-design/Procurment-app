"""Safe deletion for master data.

Unused master records may be permanently removed. Records already referenced by
transactions, transaction lines, ledgers, users, or dependent master data are
protected so historical documents and operational references never become
orphaned.
"""
from fastapi import Depends, HTTPException


MASTER_LABELS = {
    "items": "Barang",
    "item_categories": "Kategori Barang",
    "uoms": "Satuan",
    "taxes": "Pajak",
    "supplier_categories": "Kategori Supplier",
    "warehouses": "Gudang",
    "projects": "Proyek",
    "units": "Unit / Aset",
    "suppliers": "Supplier",
    "divisions": "Divisi",
    "contacts": "Kontak Internal",
}

TRANSACTION_COLLECTIONS = [
    "mro", "ro", "po", "do", "mi", "transfers", "loans", "loan_returns",
    "adjustments", "opname",
]

TRANSACTION_LINE_COLLECTIONS = [
    "mro_lines", "ro_lines", "po_lines", "do_lines", "mi_lines",
    "transfer_lines", "loan_lines", "loan_return_lines",
    "adjustment_lines", "opname_lines",
]


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _first_reference(server, collection, query, label):
    row = await server.db[collection].find_one(
        query,
        {"_id": 0, "id": 1, "no": 1, "code": 1, "name": 1,
         "mro_id": 1, "ro_id": 1, "po_id": 1, "do_id": 1, "mi_id": 1,
         "transfer_id": 1, "loan_id": 1, "return_id": 1,
         "adjustment_id": 1, "opname_id": 1},
    )
    if row:
        ref = (
            row.get("no") or row.get("code") or row.get("name")
            or row.get("mro_id") or row.get("ro_id") or row.get("po_id")
            or row.get("do_id") or row.get("mi_id") or row.get("transfer_id")
            or row.get("loan_id") or row.get("return_id")
            or row.get("adjustment_id") or row.get("opname_id")
            or row.get("id") or "data terkait"
        )
        return f"{label}: {ref}"
    return None


async def _transaction_reference(server, rid, fields):
    query = {"$or": [{field: rid} for field in fields]}
    for collection in TRANSACTION_COLLECTIONS:
        hit = await _first_reference(server, collection, query, collection.upper())
        if hit:
            return hit
    return None


async def _transaction_line_reference(server, rid, fields):
    query = {"$or": [{field: rid} for field in fields]}
    for collection in TRANSACTION_LINE_COLLECTIONS:
        hit = await _first_reference(server, collection, query, collection.upper())
        if hit:
            return hit
    return None


async def _dependency(server, name, rid):
    # Direct references stored on transaction headers.
    header_fields = {
        "warehouses": ["warehouse_id", "default_warehouse_id", "from_warehouse_id", "to_warehouse_id"],
        "projects": ["project_id", "default_project_id"],
        "units": ["unit_id", "default_unit_id"],
        "suppliers": ["supplier_id"],
        "divisions": ["division_id"],
        "contacts": ["buyer_contact_id", "requester_contact_id", "receiver_contact_id"],
        "taxes": ["default_tax_id"],
    }
    if name in header_fields:
        hit = await _transaction_reference(server, rid, header_fields[name])
        if hit:
            return hit

    # Historical references stored on transaction line collections. These must
    # be checked separately because procurement documents do not embed lines in
    # their headers.
    line_fields = {
        "items": ["item_id"],
        "warehouses": ["warehouse_id", "from_warehouse_id", "to_warehouse_id"],
        "projects": ["project_id"],
        "units": ["unit_id"],
        "suppliers": ["supplier_id"],
        "divisions": ["division_id"],
        "contacts": ["buyer_contact_id", "requester_contact_id", "receiver_contact_id"],
        "uoms": ["uom_id", "base_uom_id"],
        "taxes": ["tax_id"],
    }
    if name in line_fields:
        hit = await _transaction_line_reference(server, rid, line_fields[name])
        if hit:
            return hit

    # Operational ledgers / allocations are also transaction history.
    operational = {
        "items": [("stock_ledger", {"item_id": rid}, "Stock Ledger"), ("allocations", {"item_id": rid}, "Allocation")],
        "warehouses": [("stock_ledger", {"warehouse_id": rid}, "Stock Ledger")],
        "projects": [("stock_ledger", {"project_id": rid}, "Stock Ledger")],
        "units": [("stock_ledger", {"unit_id": rid}, "Stock Ledger")],
        "divisions": [("stock_ledger", {"division_id": rid}, "Stock Ledger")],
    }
    for collection, query, label in operational.get(name, []):
        hit = await _first_reference(server, collection, query, label)
        if hit:
            return hit

    # Master-to-master dependencies. These are blocked too, otherwise dropdown
    # references and access-control assignments would become invalid.
    master_refs = {
        "item_categories": [("items", {"category_id": rid}, "Barang"), ("suppliers", {"supplied_category_ids": rid}, "Supplier")],
        "uoms": [("items", {"$or": [{"base_uom_id": rid}, {"uoms.uom_id": rid}]}, "Barang")],
        "taxes": [("suppliers", {"default_tax_id": rid}, "Supplier")],
        "supplier_categories": [("suppliers", {"supplier_category_id": rid}, "Supplier")],
        "warehouses": [("users", {"warehouses": rid}, "User")],
        "divisions": [
            ("items", {"division_id": rid}, "Barang"),
            ("warehouses", {"division_id": rid}, "Gudang"),
            ("units", {"division_id": rid}, "Unit / Aset"),
            ("contacts", {"division_id": rid}, "Kontak Internal"),
            ("users", {"divisions": rid}, "User"),
        ],
    }
    for collection, query, label in master_refs.get(name, []):
        hit = await _first_reference(server, collection, query, label)
        if hit:
            return hit

    # Inventory balance/configuration is removable together with an item or
    # warehouse only when it has no stock. Non-zero stock is always protected.
    if name == "items":
        row = await server.db.item_warehouse.find_one(
            {"item_id": rid, "current_stock": {"$ne": 0}},
            {"_id": 0, "warehouse_id": 1, "current_stock": 1},
        )
        if row:
            return f"Persediaan masih memiliki saldo {row.get('current_stock', 0)}"
    if name == "warehouses":
        row = await server.db.item_warehouse.find_one(
            {"warehouse_id": rid, "current_stock": {"$ne": 0}},
            {"_id": 0, "item_id": 1, "current_stock": 1},
        )
        if row:
            return f"Gudang masih memiliki saldo persediaan {row.get('current_stock', 0)}"

    return None


def install(server):
    app = server.app
    old = _find_route(app, "/api/master/{name}/{rid}", "DELETE")
    if old:
        app.router.routes.remove(old)

    async def delete_master_safe(name: str, rid: str, user=Depends(server.current_user)):
        server.require(user, "delete")
        if name not in server.MASTER_COLLECTIONS:
            raise HTTPException(status_code=404, detail="Master tidak ditemukan")
        col = server._mc(name)
        existing = await col.find_one({"id": rid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Data master tidak ditemukan")

        used_by = await _dependency(server, name, rid)
        if used_by:
            label = MASTER_LABELS.get(name, "Data master")
            raise HTTPException(
                status_code=409,
                detail=f"{label} tidak dapat dihapus karena sudah digunakan / direferensikan oleh {used_by}",
            )

        # Clean non-historical configuration rows that point to an otherwise
        # unused item/warehouse. Transaction ledgers are never deleted here.
        if name == "items":
            await server.db.item_warehouse.delete_many({
                "item_id": rid,
                "$or": [{"current_stock": 0}, {"current_stock": {"$exists": False}}],
            })
        elif name == "warehouses":
            await server.db.item_warehouse.delete_many({
                "warehouse_id": rid,
                "$or": [{"current_stock": 0}, {"current_stock": {"$exists": False}}],
            })

        await col.delete_one({"id": rid})
        await server.audit(
            user, "delete", name, rid, existing.get("code"),
            before=existing,
            reason="Master dihapus karena belum pernah digunakan",
        )
        return {"ok": True, "deleted": True}

    app.add_api_route(
        "/api/master/{name}/{rid}",
        delete_master_safe,
        methods=["DELETE"],
        tags=["master"],
    )
