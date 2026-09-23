"""Automatic-but-editable code handling for master data.

New master forms receive a suggested sequential code. Users may override the
suggestion before saving and may also edit an existing code later. All code
changes remain uniqueness-checked so references keep using the stable master id.

This module extends the generic master registry with item categories, UOM, tax,
and supplier-category masters. It also normalizes item UOM and supplier detail
structures used by the procurement UI.
"""
from fastapi import Depends, HTTPException

MASTER_PREFIX = {
    "items": "BRG",
    "warehouses": "GDG",
    "projects": "PRJ",
    "units": "UNT",
    "suppliers": "SUP",
    "supplier_categories": "KSP",
    "divisions": "DIV",
    "uoms": "SAT",
    "item_categories": "KAT",
    "taxes": "PJK",
}


async def _available_code(server, name: str, start_seq: int) -> str:
    if name not in MASTER_PREFIX:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")
    col = server._mc(name)
    prefix = MASTER_PREFIX[name]
    seq = max(1, int(start_seq))
    while True:
        code = f"{prefix}-{seq:05d}"
        if not await col.find_one({"code": code}):
            return code
        seq += 1


async def preview_master_code(server, name: str) -> str:
    if name not in MASTER_PREFIX:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")
    counter = await server.db.counters.find_one({"id": f"MASTER-{name}"}) or {}
    return await _available_code(server, name, int(counter.get("seq", 0)) + 1)


async def next_master_code(server, name: str) -> str:
    if name not in MASTER_PREFIX:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")

    col = server._mc(name)
    prefix = MASTER_PREFIX[name]
    counter_id = f"MASTER-{name}"
    while True:
        res = await server.db.counters.find_one_and_update(
            {"id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq = (res or {}).get("seq", 1)
        code = f"{prefix}-{seq:05d}"
        if not await col.find_one({"code": code}):
            return code


async def _normalize_item(server, body: dict) -> dict:
    out = {**body}
    base_uom_id = out.get("base_uom_id")
    if not base_uom_id:
        return out

    base = await server.db.uoms.find_one({"id": base_uom_id, "is_active": {"$ne": False}})
    if not base:
        raise HTTPException(status_code=400, detail="Satuan dasar tidak ditemukan / nonaktif")

    raw = out.get("uoms") or []
    seen = {base_uom_id}
    normalized = [{"uom_id": base_uom_id, "factor": 1.0, "is_base": True}]
    for row in raw:
        uid = row.get("uom_id")
        if not uid or uid in seen or uid == base_uom_id:
            continue
        factor = float(row.get("factor") or 0)
        if factor <= 0:
            raise HTTPException(status_code=400, detail="Konversi satuan harus lebih besar dari 0")
        exists = await server.db.uoms.find_one({"id": uid, "is_active": {"$ne": False}})
        if not exists:
            raise HTTPException(status_code=400, detail="Satuan tambahan tidak ditemukan / nonaktif")
        normalized.append({"uom_id": uid, "factor": factor, "is_base": False})
        seen.add(uid)

    out["uoms"] = normalized
    out["unit"] = base.get("symbol") or base.get("name") or base.get("code")
    category_id = out.get("category_id")
    if category_id:
        cat = await server.db.item_categories.find_one({"id": category_id, "is_active": {"$ne": False}})
        if not cat:
            raise HTTPException(status_code=400, detail="Kategori barang tidak ditemukan / nonaktif")
        out["category"] = cat.get("name")
    return out


async def _normalize_tax(body: dict) -> dict:
    out = {**body}
    try:
        rate = float(out.get("rate") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Tarif pajak tidak valid")
    if rate < 0:
        raise HTTPException(status_code=400, detail="Tarif pajak tidak boleh negatif")
    out["rate"] = rate
    return out


def _clean_text(value):
    return str(value or "").strip()


async def _normalize_supplier(server, body: dict) -> dict:
    out = {**body}

    category_id = out.get("supplier_category_id")
    if category_id:
        cat = await server.db.supplier_categories.find_one({"id": category_id, "is_active": {"$ne": False}})
        if not cat:
            raise HTTPException(status_code=400, detail="Kategori supplier tidak ditemukan / nonaktif")
        out["supplier_category_name"] = cat.get("name")
    else:
        out["supplier_category_name"] = None

    default_tax_id = out.get("default_tax_id")
    if default_tax_id:
        tax = await server.db.taxes.find_one({"id": default_tax_id, "is_active": {"$ne": False}})
        if not tax:
            raise HTTPException(status_code=400, detail="Pajak default tidak ditemukan / nonaktif")
        out["default_tax_name"] = tax.get("name")
        out["default_tax_rate"] = float(tax.get("rate") or 0)
    else:
        out["default_tax_name"] = None
        out["default_tax_rate"] = 0.0

    supplied_category_ids = list(dict.fromkeys(out.get("supplied_category_ids") or []))
    if supplied_category_ids:
        found = await server.db.item_categories.count_documents({
            "id": {"$in": supplied_category_ids}, "is_active": {"$ne": False}
        })
        if found != len(supplied_category_ids):
            raise HTTPException(status_code=400, detail="Ada kategori barang supplier yang tidak valid / nonaktif")
    out["supplied_category_ids"] = supplied_category_ids

    contacts = []
    for raw in out.get("contacts") or []:
        name = _clean_text(raw.get("name"))
        phone = _clean_text(raw.get("phone"))
        email = _clean_text(raw.get("email"))
        if not (name or phone or email):
            continue
        contacts.append({
            "id": raw.get("id") or server.gid(),
            "name": name,
            "role": _clean_text(raw.get("role")),
            "phone": phone,
            "email": email,
            "is_primary": bool(raw.get("is_primary")),
        })
    if contacts and not any(x["is_primary"] for x in contacts):
        contacts[0]["is_primary"] = True
    primary_contact_seen = False
    for row in contacts:
        if row["is_primary"] and not primary_contact_seen:
            primary_contact_seen = True
        elif row["is_primary"]:
            row["is_primary"] = False
    out["contacts"] = contacts
    primary_contact = next((x for x in contacts if x["is_primary"]), contacts[0] if contacts else None)
    if primary_contact:
        # Keep legacy fields populated for list/search compatibility.
        out["contact"] = primary_contact.get("name")
        out["phone"] = primary_contact.get("phone")
        out["email"] = primary_contact.get("email")

    banks = []
    for raw in out.get("banks") or []:
        bank_name = _clean_text(raw.get("bank_name"))
        account_no = _clean_text(raw.get("account_no"))
        account_name = _clean_text(raw.get("account_name"))
        if not (bank_name or account_no or account_name):
            continue
        banks.append({
            "id": raw.get("id") or server.gid(),
            "bank_name": bank_name,
            "account_no": account_no,
            "account_name": account_name,
            "branch": _clean_text(raw.get("branch")),
            "currency": _clean_text(raw.get("currency")) or "IDR",
            "is_primary": bool(raw.get("is_primary")),
        })
    if banks and not any(x["is_primary"] for x in banks):
        banks[0]["is_primary"] = True
    primary_bank_seen = False
    for row in banks:
        if row["is_primary"] and not primary_bank_seen:
            primary_bank_seen = True
        elif row["is_primary"]:
            row["is_primary"] = False
    out["banks"] = banks

    try:
        lead_time_days = int(float(out.get("lead_time_days") or 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Lead time supplier tidak valid")
    if lead_time_days < 0:
        raise HTTPException(status_code=400, detail="Lead time tidak boleh negatif")
    out["lead_time_days"] = lead_time_days

    try:
        min_order = float(out.get("min_order") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Minimum order tidak valid")
    if min_order < 0:
        raise HTTPException(status_code=400, detail="Minimum order tidak boleh negatif")
    out["min_order"] = min_order

    out["pkp"] = bool(out.get("pkp"))
    out["country"] = _clean_text(out.get("country")) or "Indonesia"
    out["currency"] = _clean_text(out.get("currency")) or "IDR"
    out["supplier_type"] = _clean_text(out.get("supplier_type")) or "Lokal"
    out["address"] = _clean_text(out.get("address"))
    return out


async def _prepare_body(server, name: str, body: dict) -> dict:
    if name == "items":
        return await _normalize_item(server, body)
    if name == "taxes":
        return await _normalize_tax(body)
    if name == "suppliers":
        return await _normalize_supplier(server, body)
    return {**body}


def install(server):
    server.MASTER_COLLECTIONS.update({
        "uoms": server.db.uoms,
        "item_categories": server.db.item_categories,
        "taxes": server.db.taxes,
        "supplier_categories": server.db.supplier_categories,
    })

    app = server.app

    def should_remove(route):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        return (
            (path == "/api/master/{name}" and "POST" in methods)
            or (path == "/api/master/{name}/{rid}" and "PUT" in methods)
            or (path == "/api/master-code/{name}/preview" and "GET" in methods)
        )

    app.router.routes[:] = [r for r in app.router.routes if not should_remove(r)]

    async def master_code_preview(name: str, user=Depends(server.current_user)):
        server.require(user, "view")
        return {"code": await preview_master_code(server, name)}

    async def master_create_auto(name: str, body: dict, user=Depends(server.current_user)):
        server.require(user, "create")
        col = server._mc(name)
        automatic_code = await next_master_code(server, name)
        requested_code = str(body.get("code") or "").strip()
        code = requested_code or automatic_code
        if await col.find_one({"code": code}):
            raise HTTPException(status_code=400, detail=f"Kode {code} sudah dipakai")

        clean_body = await _prepare_body(server, name, body)
        clean_body.pop("id", None)
        clean_body.pop("_id", None)
        clean_body.pop("code", None)
        doc = {
            **clean_body,
            "id": server.gid(),
            "code": code,
            "is_active": clean_body.get("is_active", True),
            "created_at": server.now_iso(),
        }
        await col.insert_one(doc)
        await server.audit(user, "create", name, doc["id"], code)
        return server.clean(doc)

    async def master_update_editable_code(name: str, rid: str, body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        col = server._mc(name)
        existing = await col.find_one({"id": rid})
        if not existing:
            raise HTTPException(status_code=404, detail="Data master tidak ditemukan")

        update = await _prepare_body(server, name, body)
        update.pop("id", None)
        update.pop("_id", None)
        update.pop("created_at", None)
        code = str(update.get("code") or existing.get("code") or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="Kode wajib diisi")
        duplicate = await col.find_one({"code": code, "id": {"$ne": rid}})
        if duplicate:
            raise HTTPException(status_code=400, detail=f"Kode {code} sudah dipakai")
        update["code"] = code

        await col.update_one({"id": rid}, {"$set": update})
        await server.audit(
            user, "edit", name, rid, code,
            before={"code": existing.get("code")}, after={"code": code},
        )
        return server.clean(await col.find_one({"id": rid}))

    app.add_api_route("/api/master-code/{name}/preview", master_code_preview, methods=["GET"], tags=["master"])
    app.add_api_route("/api/master/{name}", master_create_auto, methods=["POST"], tags=["master"])
    app.add_api_route("/api/master/{name}/{rid}", master_update_editable_code, methods=["PUT"], tags=["master"])
