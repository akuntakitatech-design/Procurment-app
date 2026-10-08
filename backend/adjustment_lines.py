"""Penyesuaian Stok multi-gudang per item (pola sama dengan Transfer/Pinjam — lihat transfer_lines.py, loan_lines.py).

HEADER = metadata dokumen + DEFAULT (Gudang Default, Project Default, Divisi, Jenis, Alasan, Catatan).
LINE   = sumber kebenaran gudang, project, unit/aset, stok, ledger, valuasi, detail, print.

Transaksi BARU (header bertanda warehouse_source=line): gudang/project/unit dibaca MURNI dari line.
Transaksi LAMA (tanpa penanda): fallback ke header HANYA saat dibaca (tanpa migrasi destruktif).
Engine stok/MWA/valuasi existing (post_movement + _resolve_in_cost) dipakai apa adanya.
"""
from fastapi import HTTPException

import loan_lines as LL

WAREHOUSE_SOURCE_LINE = "line"


def is_legacy(head: dict | None) -> bool:
    return (head or {}).get("warehouse_source") != WAREHOUSE_SOURCE_LINE


def _read(line: dict, head: dict | None, key: str):
    v = (line or {}).get(key)
    return v if v or not is_legacy(head) else (head or {}).get(key)


def line_warehouse(line, head):
    """Gudang efektif baris (baca). Legacy: fallback Gudang header."""
    return _read(line, head, "warehouse_id")


def line_project(line, head):
    return _read(line, head, "project_id")


def line_unit(line, head):
    return _read(line, head, "unit_id")


def resolve_lines(body: dict) -> list[dict]:
    """Default header diterapkan SAAT SUBMIT lalu disimpan eksplisit di line.
    - Gudang: line kosong -> Gudang Default header.
    - Project: hanya bila key project_id TIDAK dikirim (klien lama/Import Excel) -> Project Default header;
      bila dikirim (termasuk kosong) nilai line dihormati (override manual).
    - Unit/Aset: murni per line (tidak ada default header)."""
    out = []
    for raw in body.get("lines") or []:
        ln = dict(raw or {})
        ln["warehouse_id"] = ln.get("warehouse_id") or body.get("warehouse_id") or None
        ln["project_id"] = (ln.get("project_id") or None) if "project_id" in ln else (body.get("project_id") or None)
        ln["unit_id"] = ln.get("unit_id") or None
        out.append(ln)
    return out


def line_warehouse_ids(lines: list[dict]) -> list[str]:
    seen = []
    for ln in lines or []:
        v = ln.get("warehouse_id")
        if v and v not in seen:
            seen.append(v)
    return seen


def _delta(ln, idx):
    try:
        d = float(ln.get("adjustment") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Baris {idx}: Qty Penyesuaian tidak valid")
    if abs(d) < 1e-9:
        raise HTTPException(400, f"Baris {idx}: Qty Penyesuaian tidak boleh 0.")
    return d


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def validate_lines(server, lines, user, reversal_credit=None, item_names=None):
    """Hard-block backend SEBELUM ada penulisan (create) / SEBELUM reversal (edit):
    - barang wajib, qty != 0, gudang line wajib & aktif & dalam tenant + cakupan divisi; project/unit valid;
    - stok tidak boleh minus per (barang, gudang LINE): disimulasikan berurutan sesuai urutan posting baris
      (baris barang+gudang sama diakumulasi) dengan kredit reversal dokumen ini saat edit;
    - qty (+): biaya masuk mengikuti aturan existing _resolve_in_cost (MWA gudang line; tanpa rata-rata ->
      Approved Unit Cost wajib; override beda rata-rata wajib alasan)."""
    if not lines:
        raise HTTPException(400, "Adjustment minimal memiliki satu baris barang")
    allowed = LL._allowed_divisions(server, user)
    cache = {}
    for idx, ln in enumerate(lines, start=1):
        if not ln.get("item_id"):
            raise HTTPException(400, f"Baris {idx}: Barang adjustment wajib dipilih")
        _delta(ln, idx)
        if not ln.get("warehouse_id"):
            raise HTTPException(400, f"Baris {idx}: Gudang wajib dipilih")
        await LL._check_master(server, "warehouses", ln["warehouse_id"], idx, "Gudang", allowed, cache)
        await LL._check_master(server, "projects", ln.get("project_id"), idx, "Project", allowed, cache)
        await LL._check_master(server, "units", ln.get("unit_id"), idx, "Unit/Aset", allowed, cache)
    credit = reversal_credit or {}
    sim = {}  # (item, wh) -> {"qty": saldo simulasi, "avg": rata-rata tersedia?}
    for idx, ln in enumerate(lines, start=1):
        key = (ln["item_id"], ln["warehouse_id"])
        if key not in sim:
            iw = await server.db.item_warehouse.find_one({"item_id": key[0], "warehouse_id": key[1]}, {"_id": 0}) or {}
            qty = float(await server.stock_balance(*key) or 0) + float(credit.get(key, 0.0))
            sim[key] = {"qty": qty, "avg": float(iw.get("avg_cost") or 0) if qty > 1e-9 else 0.0}
        st, delta = sim[key], _delta(ln, idx)
        wname = (cache.get(("warehouses", key[1])) or {}).get("name") or "gudang"
        iname = (item_names or {}).get(key[0]) or "barang"
        if delta > 0:
            ap = _num(ln.get("approved_unit_cost"))
            if st["qty"] > 1e-9 and st["avg"] > 0:
                if ap is not None and ap <= 0:
                    raise HTTPException(400, f"Baris {idx}: Approved Unit Cost tidak valid (harus > 0)")
                if ap is not None and abs(ap - st["avg"]) > 1e-6 and not str(ln.get("reason") or "").strip():
                    raise HTTPException(400, f"Baris {idx}: Alasan wajib diisi karena Approved Unit Cost berbeda dari rata-rata persediaan saat ini.")
            elif ap is None or ap <= 0:
                raise HTTPException(400, f"Baris {idx}: Approved Unit Cost wajib diisi (tidak ada rata-rata persediaan untuk {iname} di {wname}).")
            else:
                st["avg"] = ap
        after = st["qty"] + delta
        if after < -1e-9:
            raise HTTPException(400, f"Baris {idx}: Adjustment {iname} melebihi stok {wname}. "
                                     f"Stok tersedia {round(st['qty'], 6):g}; hasil adjustment {round(after, 6):g}")
        st["qty"] = after
        if after <= 1e-9:
            st["avg"] = 0.0


async def post_line(server, resolve_in_cost, no, did, rec, user, txn_at, division_id=None):
    """Posting satu baris ke gudang LINE memakai engine existing. Return (unit_cost, overridden)."""
    delta = float(rec.get("adjustment") or 0)
    if abs(delta) < 1e-9:
        return None, False
    wh = rec["warehouse_id"]
    unit_cost, overridden = None, False
    if delta > 0:
        unit_cost, overridden = await resolve_in_cost(rec["item_id"], wh, rec.get("approved_unit_cost"), rec.get("reason"))
    await server.post_movement("Stock Adjustment", no, did, rec["item_id"], wh, delta if delta > 0 else 0, -delta if delta < 0 else 0,
                               project_id=rec.get("project_id"), unit_id=rec.get("unit_id"), division_id=division_id, user=user,
                               line_id=rec.get("id"), unit_cost_in=(unit_cost if delta > 0 else None), require_cost=(delta > 0),
                               source_key=f"ADJ::{rec.get('id')}", txn_at=txn_at)
    return unit_cost, overridden


async def rollback_failed_post(server, did, user):
    """Posting Adjustment BARU gagal di tengah: reversal semua movement dokumen ini lalu hapus header + line."""
    try:
        await server.reverse_document_valuation(did, user=user, reason="post_failed", block_negative=True)
    except Exception:  # noqa: BLE001
        await server.db.adjustments.update_one({"id": did}, {"$set": {"status": "Gagal Posting"}})
        return False
    await server.db.adjustment_lines.delete_many({"adjustment_id": did})
    await server.db.adjustments.delete_one({"id": did})
    return True
