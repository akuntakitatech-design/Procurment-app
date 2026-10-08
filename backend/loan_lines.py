"""Pinjam Barang multi-gudang per item (pola sama dengan Transfer — lihat transfer_lines.py).

HEADER = metadata dokumen + DEFAULT (Project Default, Gudang Pemberi Default, Gudang Peminjam Default,
Target Pengembalian, Pemohon). LINE = sumber kebenaran posting, outstanding, return, ledger, detail, print.

Transaksi BARU (header bertanda warehouse_source=line): gudang/project/unit dibaca MURNI dari line.
Transaksi LAMA (tanpa penanda): fallback ke header HANYA saat dibaca (tanpa migrasi destruktif).
Return selalu membalik arah line asli: Gudang Peminjam line -> Gudang Pemberi line.
Engine stok/MWA/valuasi existing (post_movement) dipakai apa adanya.
"""
from fastapi import HTTPException

WAREHOUSE_SOURCE_LINE = "line"


def is_legacy(head: dict | None) -> bool:
    return (head or {}).get("warehouse_source") != WAREHOUSE_SOURCE_LINE


def _read(line: dict, head: dict | None, key: str):
    v = (line or {}).get(key)
    return v if v or not is_legacy(head) else (head or {}).get(key)


def line_from(line, head):
    """Gudang Pemberi efektif (baca)."""
    return _read(line, head, "from_warehouse_id")


def line_to(line, head):
    """Gudang Peminjam efektif (baca)."""
    return _read(line, head, "to_warehouse_id")


def line_project(line, head):
    return _read(line, head, "project_id")


def line_unit(line, head):
    return _read(line, head, "unit_id")


def resolve_lines(body: dict) -> list[dict]:
    """Gudang line kosong diisi default header SAAT SUBMIT lalu disimpan eksplisit; line yang terisi tidak diubah."""
    out = []
    for raw in body.get("lines") or []:
        ln = dict(raw or {})
        ln["from_warehouse_id"] = ln.get("from_warehouse_id") or body.get("from_warehouse_id") or None
        ln["to_warehouse_id"] = ln.get("to_warehouse_id") or body.get("to_warehouse_id") or None
        ln["project_id"] = ln.get("project_id") or None
        ln["unit_id"] = ln.get("unit_id") or None
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


def _allowed_divisions(server, user):
    is_global = getattr(server, "is_global", None)
    if is_global is None or is_global(user):
        return None
    return {str(x) for x in (user.get("divisions") or []) if x}


async def _check_master(server, coll, mid, idx, label, allowed, cache):
    """Master per line wajib ada di tenant aktif (tenant proxy), aktif, dan dalam cakupan divisi user."""
    if not mid:
        return None
    if (coll, mid) not in cache:
        cache[(coll, mid)] = await getattr(server.db, coll).find_one({"id": mid}, {"_id": 0})
    m = cache[(coll, mid)]
    if not m or m.get("is_active") is False or m.get("deleted") or m.get("is_deleted"):
        raise HTTPException(400, f"Baris {idx}: {label} tidak ditemukan atau tidak aktif")
    div = m.get("division_id")
    if allowed is not None and div and str(div) not in allowed:
        raise HTTPException(403, f"Baris {idx}: {label} berada di luar cakupan divisi Anda")
    return m


async def validate_lines(server, lines, user, reversal_credit=None, item_names=None):
    """Hard-block backend per line: qty>0, Gudang Pemberi/Peminjam wajib & aktif & berbeda, project/unit valid
    dalam tenant + cakupan divisi, stok cukup per (barang, Gudang Pemberi LINE) secara agregat."""
    if not lines:
        raise HTTPException(400, "Minimal satu baris barang wajib diisi")
    allowed = _allowed_divisions(server, user)
    cache = {}
    for idx, ln in enumerate(lines, start=1):
        if not ln.get("item_id"):
            raise HTTPException(400, f"Baris {idx}: Barang wajib dipilih")
        if not float(ln.get("qty") or 0) > 0:
            raise HTTPException(400, f"Baris {idx}: Qty harus lebih besar dari 0")
        frm, to = ln.get("from_warehouse_id"), ln.get("to_warehouse_id")
        if not frm:
            raise HTTPException(400, f"Baris {idx}: Gudang Pemberi wajib dipilih")
        if not to:
            raise HTTPException(400, f"Baris {idx}: Gudang Peminjam wajib dipilih")
        if frm == to:
            raise HTTPException(400, f"Baris {idx}: Gudang Pemberi dan Gudang Peminjam tidak boleh sama")
        await _check_master(server, "warehouses", frm, idx, "Gudang Pemberi", allowed, cache)
        await _check_master(server, "warehouses", to, idx, "Gudang Peminjam", allowed, cache)
        await _check_master(server, "projects", ln.get("project_id"), idx, "Project", allowed, cache)
        await _check_master(server, "units", ln.get("unit_id"), idx, "Unit/Aset", allowed, cache)
    required, first_row = {}, {}
    for idx, ln in enumerate(lines, start=1):
        key = (ln.get("item_id"), ln.get("from_warehouse_id"))
        required[key] = required.get(key, 0.0) + float(ln.get("qty") or 0)
        first_row.setdefault(key, idx)
    # Selalu divalidasi (seperti Transfer): engine existing (post_movement Loan Out) juga memblokir stok minus,
    # sehingga pre-check ini membuat kegagalan ATOMIC & terjadi SEBELUM reversal pada edit.
    credit = reversal_credit or {}
    for key, qty in required.items():
        available = float(await server.stock_balance(*key) or 0) + float(credit.get(key, 0.0))
        if qty > available + 1e-6:
            wname = (cache.get(("warehouses", key[1])) or {}).get("name") or "gudang pemberi"
            iname = (item_names or {}).get(key[0]) or "barang"
            raise HTTPException(400, f"Baris {first_row[key]}: Stok {iname} di {wname} tidak cukup "
                                     f"(tersedia {round(available, 6):g}, diminta {round(qty, 6):g})")


async def post_line(server, no, did, rec, user, txn_at):
    """OUT dari Gudang Pemberi line -> IN ke Gudang Peminjam line (nilai MWA asli dibawa). Source key existing."""
    lid = rec.get("id")
    out = await server.post_movement("Loan Out", no, did, rec["item_id"], rec["from_warehouse_id"], 0, rec["qty"],
                                     project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user,
                                     line_id=lid, source_key=f"LOAN-O::{lid}", txn_at=txn_at)
    lv = float(out.get("value_out") or 0)
    await server.post_movement("Loan In", no, did, rec["item_id"], rec["to_warehouse_id"], rec["qty"], 0,
                               project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), user=user,
                               value_in=lv, line_id=lid, source_key=f"LOAN-I::{lid}", txn_at=txn_at, require_cost=True)
    return out


async def rollback_failed_post(server, did, user):
    """Posting Pinjaman BARU gagal di tengah: reversal semua movement dokumen ini lalu hapus header + line."""
    try:
        await server.reverse_document_valuation(did, user=user, reason="post_failed", block_negative=True)
    except Exception:  # noqa: BLE001
        await server.db.loans.update_one({"id": did}, {"$set": {"status": "Gagal Posting"}})
        return False
    await server.db.loan_lines.delete_many({"loan_id": did})
    await server.db.loans.delete_one({"id": did})
    return True


def return_warehouses(loan_line: dict, loan: dict):
    """Arah Return mengikuti line asli: keluar dari Gudang Peminjam line, masuk ke Gudang Pemberi line.
    Legacy (line tanpa gudang) memakai fallback header existing."""
    return line_to(loan_line, loan), line_from(loan_line, loan)
