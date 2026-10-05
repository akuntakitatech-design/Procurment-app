"""Opening inventory Excel import.

Adds a dedicated dataset to the generic Excel import center without bypassing
inventory controls. The file uses human-readable codes and stores quantity in
the item's canonical/base UOM while preserving the entered UOM, project and
purchase price as opening-balance snapshots.

Re-importing the same item + warehouse + project updates that opening-balance
slice by delta, so corrections do not blindly duplicate stock.
"""

from fastapi import HTTPException

DATASET_KEY = "opening_inventory"
DATASET_SPEC = {
    "label": "Saldo Awal Persediaan",
    "columns": [
        "item_code", "item_name", "uom_code", "warehouse_code", "project_code",
        "qty", "purchase_price",
    ],
    "required": ["item_code", "item_name", "uom_code", "warehouse_code", "qty", "purchase_price"],
    "example": [
        "BRG-00001", "RANTAI BESI 5/8 PANJANG 8 M", "PCS", "GDG-00001", "PRJ-00001",
        10, 3280000,
    ],
}


VALUED_MSG = ("Nilai awal persediaan untuk barang {item} di gudang {wh} sudah ditetapkan. "
              "Saldo awal tidak dapat diubah.")
OPENING_DOC_TYPES = ["Opening Balance", "Opening Balance Import"]


async def valued_pairs(server, pairs):
    """Pool (barang, gudang) yang Opening Valuation-nya sudah ditetapkan (ledger 'Opening Valuation'
    atau penanda opening_valuation_id pada pool). Tenant-scoped via proxy DB."""
    pairs = set(pairs)
    if not pairs:
        return set()
    items = sorted({p[0] for p in pairs})
    out = {(o.get("item_id"), o.get("warehouse_id")) for o in await server.db.valuation_ledger.find(
        {"doc_type": "Opening Valuation", "item_id": {"$in": items}}, {"_id": 0, "item_id": 1, "warehouse_id": 1}).to_list(100000)}
    out |= {(r.get("item_id"), r.get("warehouse_id")) for r in await server.db.item_warehouse.find(
        {"item_id": {"$in": items}}, {"_id": 0}).to_list(100000) if r.get("opening_valuation_id")}
    return out & pairs


def _txt(v):
    return "" if v is None else str(v).strip()


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def _uom_label(u):
    return (u or {}).get("symbol") or (u or {}).get("name") or (u or {}).get("code") or ""


async def _resolve_row(server, maps, row, errors):
    n = row.get("__row__")
    item_code = _txt(row.get("item_code")).upper()
    wh_code = _txt(row.get("warehouse_code")).upper()
    project_code = _txt(row.get("project_code")).upper()
    uom_code = _txt(row.get("uom_code")).upper()

    item = maps.get("items", {}).get(item_code)
    wh = maps.get("warehouses", {}).get(wh_code)
    project = maps.get("projects", {}).get(project_code) if project_code else None
    uom = maps.get("uoms", {}).get(uom_code)

    if not _txt(row.get("item_name")):
        errors.append(f"Baris {n}: item_name wajib diisi")
    if not item:
        errors.append(f"Baris {n}: item_code '{row.get('item_code')}' tidak ditemukan")
    if not wh:
        errors.append(f"Baris {n}: warehouse_code '{row.get('warehouse_code')}' tidak ditemukan")
    if project_code and not project:
        errors.append(f"Baris {n}: project_code '{row.get('project_code')}' tidak ditemukan")
    if not uom:
        errors.append(f"Baris {n}: uom_code '{row.get('uom_code')}' tidak ditemukan")

    qty = _num(row.get("qty"))
    price = _num(row.get("purchase_price"))
    if qty is None or qty < 0:
        errors.append(f"Baris {n}: qty harus berupa angka >= 0")
    if price is None or price < 0:
        errors.append(f"Baris {n}: purchase_price harus berupa angka >= 0")
    if not item or not wh or not uom or qty is None or price is None or qty < 0 or price < 0:
        return None

    base_uom_id = item.get("base_uom_id")
    base_uom = await server.db.uoms.find_one({"id": base_uom_id}, {"_id": 0}) if base_uom_id else None
    factor = 1.0
    if base_uom_id and uom.get("id") != base_uom_id:
        cfg = next((x for x in (item.get("uoms") or []) if x.get("uom_id") == uom.get("id")), None)
        if not cfg:
            errors.append(f"Baris {n}: satuan {uom_code} belum terdaftar sebagai satuan barang {item_code}")
            return None
        factor = float(cfg.get("factor") or 0)
        if factor <= 0:
            errors.append(f"Baris {n}: faktor konversi satuan {uom_code} tidak valid")
            return None

    base_qty = qty * factor
    base_unit_cost = (price / factor) if factor else price
    value = qty * price
    return {
        "item_id": item["id"],
        "item_code": item.get("code"),
        "item_name": item.get("name"),
        "warehouse_id": wh["id"],
        "warehouse_code": wh.get("code"),
        "project_id": project.get("id") if project else None,
        "project_code": project.get("code") if project else None,
        "uom_id": uom.get("id"),
        "uom_code": uom.get("code") or uom_code,
        "display_unit": _uom_label(uom),
        "base_uom_id": base_uom_id,
        "base_unit": _uom_label(base_uom) or item.get("unit"),
        "conversion_factor": factor,
        "display_qty": qty,
        "base_qty": base_qty,
        "purchase_price": price,
        "base_unit_cost": base_unit_cost,
        "opening_value": value,
        "source_item_name": _txt(row.get("item_name")),
        "excel_row": n,
    }


async def _append_value_ledger(server, user, rec, qty_delta, value_delta, running_before):
    running = running_before + qty_delta
    await server.db.stock_ledger.insert_one({
        "id": server.gid(),
        "doc_type": "Opening Balance Import",
        "doc_no": "SALDO-AWAL",
        "doc_id": rec["id"],
        "item_id": rec["item_id"],
        "warehouse_id": rec["warehouse_id"],
        "project_id": rec.get("project_id"),
        "unit_id": None,
        "division_id": None,
        "qty_in": qty_delta if qty_delta > 0 else 0,
        "qty_out": -qty_delta if qty_delta < 0 else 0,
        "running_balance": running,
        "uom_id": rec.get("uom_id"),
        "display_unit": rec.get("display_unit"),
        "conversion_factor": rec.get("conversion_factor", 1),
        "unit_cost": rec.get("base_unit_cost", 0),
        "purchase_price": rec.get("purchase_price", 0),
        "value_adjustment": value_delta,
        "opening_balance": True,
        "user": user.get("email"),
        "at": server.now_iso(),
    })
    return running


async def _import_opening(server, rows, user, maps):
    # Saldo awal changes inventory; keep this stricter than a normal master upload.
    server.require(user, "stock_adjustment")
    errors = []
    prepared = []
    seen = set()
    for row in rows:
        rec = await _resolve_row(server, maps, row, errors)
        if not rec:
            continue
        key = (rec["item_id"], rec["warehouse_id"], rec.get("project_id"))
        if key in seen:
            errors.append(
                f"Baris {row.get('__row__')}: kombinasi item + gudang + proyek duplikat di file. "
                "Gabungkan menjadi satu baris."
            )
            continue
        seen.add(key)
        prepared.append(rec)

    if errors:
        return {"ok": False, "imported": 0, "created": 0, "updated": 0, "errors": errors[:200]}

    # Read all previous opening slices before any write so deltas are deterministic.
    old_by_key = {}
    affected_pairs = set()
    for rec in prepared:
        key = (rec["item_id"], rec["warehouse_id"], rec.get("project_id"))
        old = await server.db.opening_inventory.find_one({
            "item_id": rec["item_id"], "warehouse_id": rec["warehouse_id"], "project_id": rec.get("project_id")
        }, {"_id": 0})
        old_by_key[key] = old
        affected_pairs.add((rec["item_id"], rec["warehouse_id"]))

    # Pool yang Opening Valuation-nya sudah ditetapkan: saldo awal TERKUNCI. Perubahan qty/nilai
    # ditolak (tidak ada reversal resmi Opening Valuation); baris identik = tanpa perubahan (dilewati).
    locked = await valued_pairs(server, affected_pairs)
    skip = set()
    for rec in prepared:
        key = (rec["item_id"], rec["warehouse_id"], rec.get("project_id"))
        pair = key[:2]
        if pair not in locked:
            continue
        old = old_by_key.get(key) or {}
        if abs(rec["base_qty"] - float(old.get("base_qty") or 0)) > 1e-9 or abs(rec["opening_value"] - float(old.get("opening_value") or 0)) > 0.005:
            errors.append(VALUED_MSG.format(item=rec.get("item_code"), wh=rec.get("warehouse_code")))
        else:
            skip.add(key)
    if errors:
        return {"ok": False, "imported": 0, "created": 0, "updated": 0, "errors": errors[:200]}
    prepared = [r for r in prepared if (r["item_id"], r["warehouse_id"], r.get("project_id")) not in skip]
    affected_pairs -= locked

    # On a brand-new opening balance for an item/warehouse with no operational
    # ledger, the import becomes authoritative. This avoids doubling a legacy
    # manually-entered current_stock value.
    for item_id, warehouse_id in affected_pairs:
        existing_opening = await server.db.opening_inventory.count_documents({"item_id": item_id, "warehouse_id": warehouse_id})
        operational = await server.db.stock_ledger.count_documents({
            "item_id": item_id,
            "warehouse_id": warehouse_id,
            "doc_type": {"$nin": ["Opening Balance", "Opening Balance Import"]},
            "reversed": {"$ne": True},
        })
        if existing_opening == 0 and operational == 0:
            await server.db.item_warehouse.update_one(
                {"item_id": item_id, "warehouse_id": warehouse_id},
                {"$set": {"item_id": item_id, "warehouse_id": warehouse_id, "current_stock": 0}},
                upsert=True,
            )

    created = 0
    updated = 0
    imported = 0
    # Keep ledger running balance correct when several project rows hit one item/warehouse.
    running = {}
    for pair in affected_pairs:
        iw = await server.db.item_warehouse.find_one({"item_id": pair[0], "warehouse_id": pair[1]}, {"_id": 0}) or {}
        running[pair] = float(iw.get("current_stock") or 0)

    async def pool_set(pair, fields, code, wh):
        """Tulis pool HANYA bila Opening Valuation belum ditetapkan (guard atomik vs Tetapkan bersamaan).
        _ver dinaikkan agar Tetapkan yang membaca pool sebelum import ini gagal CAS (409), bukan menilai
        data lama."""
        exists = await server.db.item_warehouse.find_one({"item_id": pair[0], "warehouse_id": pair[1]}, {"_id": 0, "item_id": 1})
        if not exists:
            await server.db.item_warehouse.update_one({"item_id": pair[0], "warehouse_id": pair[1]}, {"$set": fields}, upsert=True)
            return
        ok = await server.db.item_warehouse.find_one_and_update(
            {"item_id": pair[0], "warehouse_id": pair[1],
             "$or": [{"opening_valuation_id": {"$exists": False}}, {"opening_valuation_id": None}]},
            {"$set": fields, "$inc": {"_ver": 1}}, return_document=True)
        if ok is None:
            raise HTTPException(409, VALUED_MSG.format(item=code, wh=wh))

    # 1) Hitung keadaan AKHIR tiap pool (qty fisik + opening slice) lalu tulis pool SEKALI di awal dengan
    #    guard. Bila pool ternyata sudah ditetapkan (bersamaan), import berhenti sebelum slice/ledger
    #    ditulis -> tidak ada opening slice yang menyimpang dari pool/valuasi.
    deltas = {}
    final_slices = {}
    for pair in affected_pairs:
        for x in await server.db.opening_inventory.find({"item_id": pair[0], "warehouse_id": pair[1]}, {"_id": 0}).to_list(10000):
            final_slices[(pair[0], pair[1], x.get("project_id"))] = (float(x.get("base_qty") or 0), float(x.get("opening_value") or 0))
    for rec in prepared:
        key = (rec["item_id"], rec["warehouse_id"], rec.get("project_id"))
        old = old_by_key.get(key) or {}
        d = deltas.setdefault(key[:2], [0.0, False])
        dq = rec["base_qty"] - float(old.get("base_qty") or 0)
        d[0] += dq
        d[1] = d[1] or abs(dq) > 1e-12 or abs(rec["opening_value"] - float(old.get("opening_value") or 0)) > 0.005
        final_slices[key] = (rec["base_qty"], rec["opening_value"])
    codes = {(r["item_id"], r["warehouse_id"]): (r.get("item_code"), r.get("warehouse_code")) for r in prepared}
    for pair in affected_pairs:
        oq = sum(v[0] for k, v in final_slices.items() if k[:2] == pair)
        ov = sum(v[1] for k, v in final_slices.items() if k[:2] == pair)
        fields = {"opening_qty": oq, "opening_value": ov, "opening_average_cost": (ov / oq if oq else 0),
                  "opening_updated_at": server.now_iso()}
        if deltas.get(pair, [0.0, False])[1]:
            fields["current_stock"] = running[pair] + deltas[pair][0]
        c = codes.get(pair, ("", ""))
        await pool_set(pair, fields, c[0], c[1])

    # 2) Slice saldo awal + ledger (stock_ledger 'Opening Balance Import') per baris.
    for rec in prepared:
        key = (rec["item_id"], rec["warehouse_id"], rec.get("project_id"))
        pair = (rec["item_id"], rec["warehouse_id"])
        old = old_by_key.get(key) or {}
        old_qty = float(old.get("base_qty") or 0)
        old_value = float(old.get("opening_value") or 0)
        qty_delta = rec["base_qty"] - old_qty
        value_delta = rec["opening_value"] - old_value

        now = server.now_iso()
        if old:
            rec_id = old["id"]
            patch = {**rec, "updated_at": now, "updated_by": user.get("email")}
            patch.pop("excel_row", None)
            await server.db.opening_inventory.update_one({"id": rec_id}, {"$set": patch})
            updated += 1
        else:
            rec_id = server.gid()
            doc = {**rec, "id": rec_id, "created_at": now, "created_by": user.get("email")}
            doc.pop("excel_row", None)
            await server.db.opening_inventory.insert_one(doc)
            created += 1
        imported += 1

        stored = await server.db.opening_inventory.find_one({"id": rec_id}, {"_id": 0})
        if abs(qty_delta) > 1e-12 or abs(value_delta) > 0.005:
            running[pair] = await _append_value_ledger(server, user, stored, qty_delta, value_delta, running[pair])

    await server.audit(user, "excel_import", DATASET_KEY, "batch", after={
        "imported": imported, "created": created, "updated": updated,
    })
    return {"ok": True, "imported": imported, "created": created, "updated": updated, "errors": []}


def install(server, excel_module):
    # Register the dataset before excel_module.install(server) creates routes.
    excel_module.MASTER_DATASETS[DATASET_KEY] = DATASET_SPEC
    excel_module.ALL_DATASETS[DATASET_KEY] = DATASET_SPEC

    original_import_master = excel_module._import_master

    async def import_master(server_arg, key, rows, user):
        if key != DATASET_KEY:
            return await original_import_master(server_arg, key, rows, user)
        maps = await excel_module._maps(server_arg)
        return await _import_opening(server_arg, rows, user, maps)

    excel_module._import_master = import_master
