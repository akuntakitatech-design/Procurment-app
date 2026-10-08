"""Transfer Antar Gudang multi-gudang per item.

Konsep:
  HEADER  = metadata dokumen + nilai DEFAULT (from/to warehouse, project) -> tidak dipakai posting bila line punya gudang.
  LINE    = sumber transaksi sebenarnya: from_warehouse_id, to_warehouse_id, project_id, unit_id.

Transaksi BARU: setiap line WAJIB punya gudang asal & tujuan (diisi dari default header bila tidak dikirim,
lalu disimpan eksplisit pada line). Transaksi LAMA (line tanpa gudang) hanya dibaca dengan fallback header.
Engine stok/MWA/valuasi existing (post_movement) dipakai apa adanya; yang berubah hanya sumber gudangnya.
"""
from fastapi import HTTPException

WAREHOUSE_SOURCE_LINE = "line"  # penanda header transaksi baru: gudang posting dibaca dari line


def is_legacy(head: dict | None) -> bool:
    """Transfer lama = header tidak bertanda warehouse_source=line (dibuat sebelum multi gudang per item)."""
    return (head or {}).get("warehouse_source") != WAREHOUSE_SOURCE_LINE


def _read(line: dict, head: dict | None, key: str):
    # NEW: line adalah sumber kebenaran (tanpa fallback header). LEGACY: fallback header hanya untuk BACA.
    v = (line or {}).get(key)
    return v if v or not is_legacy(head) else (head or {}).get(key)


def line_from(line: dict, head: dict | None):
    """Gudang asal efektif untuk MEMBACA."""
    return _read(line, head, "from_warehouse_id")


def line_to(line: dict, head: dict | None):
    return _read(line, head, "to_warehouse_id")


def line_project(line: dict, head: dict | None):
    return _read(line, head, "project_id")


def line_unit(line: dict, head: dict | None):
    return _read(line, head, "unit_id")


def resolve_lines(body: dict) -> list[dict]:
    """Isi gudang line dari default header bila kosong (header = default), tanpa mengubah line yang sudah diisi."""
    out = []
    for raw in body.get("lines") or []:
        ln = dict(raw or {})
        ln["from_warehouse_id"] = ln.get("from_warehouse_id") or body.get("from_warehouse_id") or None
        ln["to_warehouse_id"] = ln.get("to_warehouse_id") or body.get("to_warehouse_id") or None
        out.append(ln)
    return out


def line_warehouse_ids(lines: list[dict]) -> list[str]:
    seen = []
    for ln in lines or []:
        for k in ("from_warehouse_id", "to_warehouse_id"):
            v = ln.get(k)
            if v and v not in seen:
                seen.append(v)
    return seen


async def validate_lines(server, lines: list[dict], user, reversal_credit: dict | None = None, item_names: dict | None = None):
    """Validasi per line (backend hard-block): gudang wajib, asal != tujuan, gudang aktif, stok cukup per (barang, gudang asal LINE).
    reversal_credit: {(item_id, warehouse_id): qty} stok yang akan kembali saat edit (reversal dokumen ini)."""
    if not lines:
        raise HTTPException(400, "Minimal satu baris barang wajib diisi")
    whs = {}
    for idx, ln in enumerate(lines, start=1):
        frm, to = ln.get("from_warehouse_id"), ln.get("to_warehouse_id")
        if not frm:
            raise HTTPException(400, f"Baris {idx}: Gudang Asal wajib dipilih")
        if not to:
            raise HTTPException(400, f"Baris {idx}: Gudang Tujuan wajib dipilih")
        if frm == to:
            raise HTTPException(400, f"Baris {idx}: Gudang Asal dan Gudang Tujuan tidak boleh sama")
        for wid in (frm, to):
            if wid not in whs:
                whs[wid] = await server.db.warehouses.find_one({"id": wid}, {"_id": 0, "id": 1, "name": 1, "is_active": 1})
            w = whs[wid]
            if not w or w.get("is_active") is False:
                raise HTTPException(400, f"Baris {idx}: Gudang tidak ditemukan atau tidak aktif")
    required, first_row = {}, {}
    for idx, ln in enumerate(lines, start=1):
        key = (ln.get("item_id"), ln.get("from_warehouse_id"))
        required[key] = required.get(key, 0.0) + float(ln.get("qty") or 0)
        first_row.setdefault(key, idx)
    # Selalu divalidasi: engine existing (post_movement Transfer Out, allow_negative=False) juga memblokir stok minus,
    # sehingga pre-check ini membuat kegagalan ATOMIC (tidak ada line yang terposting sebagian).
    credit = reversal_credit or {}
    for key, qty in required.items():
        available = float(await server.stock_balance(*key) or 0) + float(credit.get(key, 0.0))
        if qty > available + 1e-6:
            wname = (whs.get(key[1]) or {}).get("name") or "gudang asal"
            iname = (item_names or {}).get(key[0]) or "barang"
            raise HTTPException(400, f"Baris {first_row[key]}: Stok {iname} di {wname} tidak cukup "
                                     f"(tersedia {round(available, 6):g}, diminta {round(qty, 6):g})")


async def post_line(server, no, did, rec, user, txn_at):
    """Posting satu line memakai engine existing: OUT dari gudang asal line -> IN ke gudang tujuan line (nilai MWA dibawa).
    Kegagalan dikompensasi di level DOKUMEN (rollback_failed_post) agar tidak ada reversal ganda."""
    frm, to = rec["from_warehouse_id"], rec["to_warehouse_id"]
    out = await server.post_movement("Transfer Out", no, did, rec["item_id"], frm, 0, rec["qty"],
                                     project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user,
                                     line_id=rec.get("id"), source_key=f"TRF-O::{rec.get('id')}", txn_at=txn_at)
    tv = float(out.get("value_out") or 0)
    await server.post_movement("Transfer In", no, did, rec["item_id"], to, rec["qty"], 0,
                               project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user,
                               value_in=tv, line_id=rec.get("id"), source_key=f"TRF-I::{rec.get('id')}",
                               txn_at=txn_at, require_cost=True)
    return out


async def rollback_failed_post(server, did, user):
    """Posting Transfer BARU gagal di tengah: balik semua movement dokumen ini lewat engine reversal existing
    (nilai snapshot asli, MWA aman), lalu hapus header + line sehingga transaksi tidak terbentuk."""
    try:
        await server.reverse_document_valuation(did, user=user, reason="post_failed", block_negative=True)
    except Exception:  # noqa: BLE001 - jangan hapus jejak bila reversal gagal; tandai untuk audit
        await server.db.transfers.update_one({"id": did}, {"$set": {"status": "Gagal Posting"}})
        return False
    await server.db.transfer_lines.delete_many({"transfer_id": did})
    await server.db.transfers.delete_one({"id": did})
    return True


# ---------------- Draft lampiran (upload sebelum posting) ----------------
# Infrastruktur draft server-side dipakai Transfer dan (dengan guard eksplisit module="loan"/"adjustment")
# Pinjam Barang serta Penyesuaian Stok.
# Default module="transfer" -> perilaku Transfer identik dengan sebelumnya.
DRAFT_MODULE = "transfer"
DRAFT_ENTITY = "transfer_draft"
DRAFT_TTL_HOURS = 24
DRAFT_ENTITY_OF = {"transfer": "transfer_draft", "loan": "loan_draft", "adjustment": "adjustment_draft"}
DRAFT_HEAD_COLL = {"transfer": "transfers", "loan": "loans", "adjustment": "adjustments"}
# Penyesuaian Stok: klaim draft dicap waktu agar draft yang SEDANG diproses (posting berjalan) dilindungi dari cleanup.
CLAIM_STAMP_MODULES = {"adjustment"}
CLAIM_GRACE_MINUTES = 60


async def get_owned_draft(server, draft_id, user, module=DRAFT_MODULE):
    """Draft milik user aktif (tenant otomatis dibatasi tenant proxy). 404 bila bukan milik user/tenant/modul.
    module=None -> draft modul terdaftar mana pun (dipakai endpoint batal draft)."""
    q = {"id": draft_id, "module": module if module else {"$in": list(DRAFT_ENTITY_OF)}}
    d = await server.db.attachment_drafts.find_one(q, {"_id": 0}) if draft_id else None
    if not d or d.get("owner_id") != user.get("id"):
        raise HTTPException(404, "Draft lampiran tidak ditemukan")
    return d


async def assert_draft_owner(server, draft_id, user, module=DRAFT_MODULE):
    if not draft_id:
        return
    d = await get_owned_draft(server, draft_id, user, module)
    if d.get("bound_to"):
        raise HTTPException(409, "Draft lampiran sudah terikat ke transaksi lain")


async def claim_draft(server, draft_id, user, transfer_id, module=DRAFT_MODULE):
    """Kunci draft untuk satu posting (cegah bind ganda / double submit). Return True bila diklaim."""
    if not draft_id:
        return False
    await assert_draft_owner(server, draft_id, user, module)
    patch = {"bound_to": transfer_id, "binding": True}
    if module in CLAIM_STAMP_MODULES:
        patch["claimed_at"] = server.now_iso()
    r = await server.db.attachment_drafts.update_one(
        {"id": draft_id, "module": module, "owner_id": user.get("id"), "bound_to": None},
        {"$set": patch})
    if not getattr(r, "matched_count", 0):
        raise HTTPException(409, "Draft lampiran sudah terikat ke transaksi lain")
    return True


async def release_draft(server, draft_id, transfer_id):
    """Posting gagal -> draft kembali bebas (lampiran tetap draft, user bisa retry)."""
    await server.db.attachment_drafts.update_one({"id": draft_id, "bound_to": transfer_id},
                                                 {"$set": {"bound_to": None, "binding": False}})


async def bind_draft_attachments(server, draft_id, transfer_id, user, module=DRAFT_MODULE):
    """Setelah transaksi BENAR-BENAR sukses: ikat semua lampiran draft ke dokumen final (entity = module)."""
    if not draft_id:
        return 0
    d = await server.db.attachment_drafts.find_one({"id": draft_id, "module": module}, {"_id": 0})
    if not d or d.get("owner_id") != user.get("id") or d.get("bound_to") != transfer_id:
        return 0
    rows = await server.db.attachments.find({"entity": DRAFT_ENTITY_OF[module], "entity_id": draft_id, "is_deleted": False},
                                            {"_id": 0, "id": 1}).to_list(500)
    for r in rows:
        await server.db.attachments.update_one({"id": r["id"]}, {"$set": {"entity": module, "entity_id": transfer_id,
                                                                          "bound_from_draft": draft_id}})
    await server.db.attachment_drafts.update_one({"id": draft_id}, {"$set": {"binding": False, "bound_at": server.now_iso(),
                                                                             "attachment_count": len(rows)}})
    return len(rows)


async def purge_draft(dbh, draft, storage):
    """Hapus row draft + row lampiran draft + object storage. Aman bila object sudah hilang (idempotent)."""
    module = draft.get("module") or DRAFT_MODULE
    q = {"entity": DRAFT_ENTITY_OF.get(module, DRAFT_ENTITY), "entity_id": draft["id"]}
    if draft.get("tenant_id"):
        q["tenant_id"] = draft["tenant_id"]  # jalur global (startup): batasi ke tenant draft itu sendiri
    rows = await dbh.attachments.find(q, {"_id": 0, "id": 1, "storage_path": 1}).to_list(500)
    removed = 0
    for r in rows:
        try:
            if r.get("storage_path"):
                storage.delete_object(r["storage_path"])
        except Exception:  # noqa: BLE001 - file hilang/storage error tidak boleh menggagalkan cleanup
            pass
        await dbh.attachments.delete_one({**q, "id": r["id"]})
        removed += 1
    dq = {"id": draft["id"], "module": module}
    if draft.get("tenant_id"):
        dq["tenant_id"] = draft["tenant_id"]
    await dbh.attachment_drafts.delete_one(dq)
    return removed


def _cutoff_minutes(minutes):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _cutoff(hours=DRAFT_TTL_HOURS):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


async def cleanup_expired_drafts(server, all_tenants=False, module=DRAFT_MODULE):
    """Draft > 24 jam yang BELUM ter-bind ke dokumen final dihapus (row + object). Lampiran final tidak disentuh
    (entity-nya sudah modul final). all_tenants=True dipakai saat startup (raw db, filter tenant per draft)."""
    import storage as S
    dbh = server.db
    if all_tenants:
        raw = getattr(dbh, "_raw", None)
        dbh = raw if raw is not None else dbh
    cutoff = _cutoff()
    head = DRAFT_HEAD_COLL[module]
    olds = await dbh.attachment_drafts.find({"module": module, "created_at": {"$lt": cutoff}}, {"_id": 0}).to_list(2000)
    done = 0
    for d in olds:
        bound = d.get("bound_to")
        if bound and not d.get("binding"):
            continue  # sudah final
        if bound and d.get("binding") and module in CLAIM_STAMP_MODULES and (d.get("claimed_at") or "") >= _cutoff_minutes(CLAIM_GRACE_MINUTES):
            continue  # Penyesuaian Stok: posting sedang berjalan (klaim baru) -> jangan hapus
        if bound and d.get("binding"):
            tq = {"id": bound, **({"tenant_id": d["tenant_id"]} if d.get("tenant_id") else {})}
            if await getattr(dbh, head).find_one(tq, {"_id": 0, "id": 1}):
                continue  # klaim posting sukses tetapi bind belum tercatat: jangan hapus
        try:
            await purge_draft(dbh, d, S)
            done += 1
        except Exception:  # noqa: BLE001 - satu draft gagal tidak menggagalkan job
            continue
    return done
