"""Configurable master-code formats used by all reusable master data.

Admins can customize the format for each master in System Settings without
renaming existing records, and can set the last used sequence number so new
codes continue after imported data. Only new suggestions / newly created master
records use the updated format and starting number.
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


def _format_regex(fmt: str):
    """Regex yang menangkap nomor urut dari kode yang sudah ada (sesuai format aktif)."""
    match = TOKEN_RE.search(_validate_format(fmt))
    width = int(match.group(1)) if match and match.group(1) else 0
    body = r"(\d{%d})" % width if width else r"(\d+)"
    return re.compile("^" + re.escape(fmt[:match.start()]) + body + re.escape(fmt[match.end():]) + "$")


def _validate_sequence(value) -> int:
    try:
        seq = int(str(value).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Nomor urut terakhir harus berupa angka bulat")
    if seq < 0:
        raise HTTPException(status_code=400, detail="Nomor urut terakhir tidak boleh negatif")
    if seq > 999_999_999:
        raise HTTPException(status_code=400, detail="Nomor urut terakhir maksimal 999999999")
    return seq


async def _counter_seq(server, name: str) -> int:
    row = await server.db.counters.find_one({"id": f"MASTER-{name}"}, {"_id": 0}) or {}
    try:
        return int(row.get("seq", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def _set_counter_seq(server, name: str, seq: int) -> None:
    await server.db.counters.update_one(
        {"id": f"MASTER-{name}"},
        {"$set": {"id": f"MASTER-{name}", "seq": int(seq)}},
        upsert=True,
    )


async def _sequences(server) -> dict:
    out = {}
    for name in master_auto.MASTER_PREFIX:
        out[name] = await _counter_seq(server, name)
    return out


async def highest_sequence(server, name: str, fmt: str) -> int:
    """Nomor urut terbesar dari kode yang sudah ada dan cocok dengan format aktif."""
    rx = _format_regex(fmt)
    highest = 0
    async for doc in server._mc(name).find({}, {"_id": 0, "code": 1}):
        match = rx.match(str((doc or {}).get("code") or ""))
        if not match:
            continue
        try:
            highest = max(highest, int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return highest


async def bump_sequence_for_codes(server, name: str, codes) -> int:
    """Setelah impor: pastikan counter minimal sama dengan nomor terbesar yang diimpor."""
    if name not in master_auto.MASTER_PREFIX or name in getattr(master_auto, "MANUAL_CODE_MASTERS", set()):
        return 0
    formats = await _formats(server)
    rx = _format_regex(formats[name])
    highest = 0
    for code in codes:
        match = rx.match(str(code or ""))
        if not match:
            continue
        try:
            highest = max(highest, int(match.group(1)))
        except (TypeError, ValueError):
            continue
    if highest <= 0:
        return 0
    current = await _counter_seq(server, name)
    if highest > current:
        await _set_counter_seq(server, name, highest)
        return highest
    return current


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
        sequences = await _sequences(server)
        rows = []
        for name in master_auto.MASTER_PREFIX:
            if name in getattr(master_auto, "MANUAL_CODE_MASTERS", set()):
                continue  # kode manual, tidak memakai format otomatis
            last_seq = int(sequences.get(name, 0) or 0)
            rows.append({
                "key": name,
                "label": LABELS.get(name, name),
                "format": formats[name],
                "example": _render(formats[name], 1),
                "last_seq": last_seq,
                "next_code": _render(formats[name], last_seq + 1),
            })
        return {"formats": formats, "sequences": sequences, "rows": rows}

    async def put_master_code_settings(body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        body = body or {}
        current = await _formats(server)
        requested = body.get("formats") or {}
        clean = {}
        for name in master_auto.MASTER_PREFIX:
            clean[name] = _validate_format(requested.get(name, current.get(name) or _defaults()[name]))

        manual = getattr(master_auto, "MANUAL_CODE_MASTERS", set())
        current_sequences = await _sequences(server)
        target_sequences = dict(current_sequences)
        requested_sequences = body.get("sequences")
        if requested_sequences is not None:
            if not isinstance(requested_sequences, dict):
                raise HTTPException(status_code=400, detail="sequences harus berupa objek nama master ke nomor urut")
            for name, value in requested_sequences.items():
                if name not in master_auto.MASTER_PREFIX:
                    raise HTTPException(status_code=400, detail=f"Master '{name}' tidak dikenal")
                if name in manual:
                    continue  # master berkode manual tidak memakai nomor urut
                target_sequences[name] = _validate_sequence(value)

        before = await server.db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {
            "id": SETTINGS_ID, "formats": current,
        }
        await server.db.settings.update_one(
            {"id": SETTINGS_ID},
            {"$set": {"id": SETTINGS_ID, "formats": clean, "updated_at": server.now_iso()}},
            upsert=True,
        )
        changed_sequences = {}
        for name, seq in target_sequences.items():
            if seq != current_sequences.get(name):
                await _set_counter_seq(server, name, seq)
                changed_sequences[name] = {"before": current_sequences.get(name, 0), "after": seq}

        await server.audit(
            user, "edit", "settings", SETTINGS_ID,
            reason="Format/nomor urut kode master diperbarui",
            before={"formats": before.get("formats") or current, "sequences": current_sequences},
            after={"formats": clean, "sequences": target_sequences},
        )
        rows = []
        for name in master_auto.MASTER_PREFIX:
            if name in manual:
                continue
            last_seq = int(target_sequences.get(name, 0) or 0)
            rows.append({
                "key": name,
                "label": LABELS.get(name, name),
                "format": clean[name],
                "example": _render(clean[name], 1),
                "last_seq": last_seq,
                "next_code": _render(clean[name], last_seq + 1),
            })
        return {"formats": clean, "sequences": target_sequences, "rows": rows, "changed_sequences": changed_sequences}

    async def post_sync_master_sequence(name: str, user=Depends(server.current_user)):
        server.require(user, "edit")
        if name not in master_auto.MASTER_PREFIX:
            raise HTTPException(status_code=404, detail="Master tidak ditemukan")
        if name in getattr(master_auto, "MANUAL_CODE_MASTERS", set()):
            raise HTTPException(status_code=400, detail=f"{LABELS.get(name, name)} memakai kode manual")
        formats = await _formats(server)
        fmt = formats[name]
        highest = await highest_sequence(server, name, fmt)
        current = await _counter_seq(server, name)
        target = max(highest, current)
        changed = target != current
        if changed:
            await _set_counter_seq(server, name, target)
            await server.audit(
                user, "edit", "settings", SETTINGS_ID,
                reason=f"Nomor urut {LABELS.get(name, name)} disinkronkan dari data",
                before={"seq": current}, after={"seq": target},
            )
        return {
            "key": name,
            "last_seq": target,
            "highest_code": highest,
            "changed": changed,
            "next_code": _render(fmt, target + 1),
        }

    server.app.add_api_route("/api/settings/master_codes", get_master_code_settings, methods=["GET"], tags=["settings"])
    server.app.add_api_route("/api/settings/master_codes", put_master_code_settings, methods=["PUT"], tags=["settings"])
    server.app.add_api_route("/api/settings/master_codes/{name}/sync-sequence", post_sync_master_sequence, methods=["POST"], tags=["settings"])
