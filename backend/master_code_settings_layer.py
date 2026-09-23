"""Configurable master-code formats used by all reusable master data.

Admins can customize the format for each master in System Settings without
renaming existing records. The current sequence counter is preserved; only new
suggestions / newly created master records use the updated format.
"""
import re
from fastapi import Depends, HTTPException

import master_auto

SETTINGS_ID = "master_code_formats"
TOKEN_RE = re.compile(r"\{seq(?::0?(\d+)d)?\}")

LABELS = {
    "items": "Barang",
    "warehouses": "Gudang",
    "projects": "Proyek",
    "units": "Unit / Aset",
    "suppliers": "Supplier",
    "supplier_categories": "Kategori Supplier",
    "divisions": "Divisi",
    "uoms": "Satuan",
    "item_categories": "Kategori Barang",
    "taxes": "Pajak",
    "contacts": "Kontak Internal",
}


def _defaults():
    return {name: f"{prefix}-{{seq:05d}}" for name, prefix in master_auto.MASTER_PREFIX.items()}


def _validate_format(value: str) -> str:
    fmt = str(value or "").strip()
    if not fmt:
        raise HTTPException(status_code=400, detail="Format kode master tidak boleh kosong")
    if len(fmt) > 80:
        raise HTTPException(status_code=400, detail="Format kode master maksimal 80 karakter")
    matches = list(TOKEN_RE.finditer(fmt))
    if len(matches) != 1:
        raise HTTPException(status_code=400, detail="Format kode master harus memiliki tepat satu placeholder {seq} atau {seq:05d}")
    # Reject unknown brace placeholders so typos do not silently become literal codes.
    stripped = TOKEN_RE.sub("", fmt)
    if "{" in stripped or "}" in stripped:
        raise HTTPException(status_code=400, detail="Placeholder yang didukung hanya {seq} atau {seq:05d}")
    width = matches[0].group(1)
    if width and (int(width) < 1 or int(width) > 12):
        raise HTTPException(status_code=400, detail="Jumlah digit sequence harus 1 sampai 12")
    return fmt


def _render(fmt: str, seq: int) -> str:
    fmt = _validate_format(fmt)
    match = TOKEN_RE.search(fmt)
    width = int(match.group(1)) if match and match.group(1) else 0
    token = str(int(seq)).zfill(width) if width else str(int(seq))
    return TOKEN_RE.sub(token, fmt, count=1)


async def _formats(server):
    defaults = _defaults()
    row = await server.db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {}
    saved = row.get("formats") or {}
    out = {}
    for name, default in defaults.items():
        raw = saved.get(name, default)
        try:
            out[name] = _validate_format(raw)
        except HTTPException:
            out[name] = default
    return out


async def _available_code(server, name: str, start_seq: int) -> str:
    if name not in master_auto.MASTER_PREFIX:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")
    formats = await _formats(server)
    fmt = formats[name]
    col = server._mc(name)
    seq = max(1, int(start_seq))
    while True:
        code = _render(fmt, seq)
        if not await col.find_one({"code": code}):
            return code
        seq += 1


async def preview_master_code(server, name: str) -> str:
    if name not in master_auto.MASTER_PREFIX:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")
    counter = await server.db.counters.find_one({"id": f"MASTER-{name}"}) or {}
    return await _available_code(server, name, int(counter.get("seq", 0)) + 1)


async def next_master_code(server, name: str) -> str:
    if name not in master_auto.MASTER_PREFIX:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")
    formats = await _formats(server)
    fmt = formats[name]
    col = server._mc(name)
    counter_id = f"MASTER-{name}"
    while True:
        res = await server.db.counters.find_one_and_update(
            {"id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq = int((res or {}).get("seq", 1))
        code = _render(fmt, seq)
        if not await col.find_one({"code": code}):
            return code


def install(server):
    # master_auto routes resolve these module globals at request time, so replacing
    # them here upgrades both Preview and Create without duplicating CRUD routes.
    master_auto.preview_master_code = preview_master_code
    master_auto.next_master_code = next_master_code

    async def get_master_code_settings(user=Depends(server.current_user)):
        server.require(user, "view")
        formats = await _formats(server)
        rows = []
        for name in master_auto.MASTER_PREFIX:
            rows.append({
                "key": name,
                "label": LABELS.get(name, name),
                "format": formats[name],
                "example": _render(formats[name], 1),
            })
        return {"formats": formats, "rows": rows}

    async def put_master_code_settings(body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        current = await _formats(server)
        requested = (body or {}).get("formats") or {}
        clean = {}
        for name in master_auto.MASTER_PREFIX:
            clean[name] = _validate_format(requested.get(name, current.get(name) or _defaults()[name]))

        before = await server.db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {"id": SETTINGS_ID, "formats": current}
        await server.db.settings.update_one(
            {"id": SETTINGS_ID},
            {"$set": {"id": SETTINGS_ID, "formats": clean, "updated_at": server.now_iso()}},
            upsert=True,
        )
        await server.audit(
            user, "edit", "settings", SETTINGS_ID,
            reason="Format kode master diperbarui",
            before={"formats": before.get("formats") or current},
            after={"formats": clean},
        )
        rows = [{"key": name, "label": LABELS.get(name, name), "format": clean[name], "example": _render(clean[name], 1)} for name in master_auto.MASTER_PREFIX]
        return {"formats": clean, "rows": rows}

    server.app.add_api_route("/api/settings/master_codes", get_master_code_settings, methods=["GET"], tags=["settings"])
    server.app.add_api_route("/api/settings/master_codes", put_master_code_settings, methods=["PUT"], tags=["settings"])
