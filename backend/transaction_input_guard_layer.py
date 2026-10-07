"""Validasi global input transaksi: Divisi wajib + Qty transaksi > 0 (backend = source of truth).

Berlaku untuk create (POST /api/<modul>), edit (PUT /api/transactions/<modul>/<id>) dan submit/post dokumen
tersimpan (MRO/RO/PO submit, Opname submit/post). Hanya field INPUT transaksi yang divalidasi:
- MRO/RO/PO/DO/MI/Transfer/Pinjam: lines[].qty wajib angka finite > 0 ("Qty harus lebih besar dari 0.").
- Penyesuaian Stok: lines[].adjustment boleh +/-, tetapi tidak boleh 0/kosong ("Qty Penyesuaian tidak boleh 0.").
- Stock Opname: hasil hitung fisik (counted) boleh 0; yang ditolak hanya nilai negatif/bukan angka.
Field turunan (Sisa, Sudah PO, Stok Tersedia, variance, saldo, dll.) tidak disentuh.

Divisi transaksi berbasis dokumen sumber DIWARISI dan DIKUNCI dari sumber:
MRO -> RO, RO -> PO, PO -> DO, MRO -> MI. Bila sumber berbeda divisi -> diblok (tidak dipilih otomatis).
Bila user mengirim divisi lain dari sumber -> diblok. Sumber yang tidak terlihat oleh user (di luar
kewenangan divisi) tidak diproses di sini agar pesan keamanan layer di dalamnya tetap berlaku.
"""
from __future__ import annotations

import inspect
import math

from fastapi import HTTPException

DIVISION_MSG = "Divisi wajib diisi."
QTY_MSG = "Qty harus lebih besar dari 0."
ADJ_MSG = "Qty Penyesuaian tidak boleh 0."
COUNT_MSG = "Qty hasil hitung fisik tidak boleh minus."
LOCKED_MSG = "Divisi harus mengikuti dokumen sumber dan tidak dapat diubah."
SOURCE_NO_DIV_MSG = "Dokumen sumber tidak memiliki Divisi yang valid. Transaksi tidak dapat diproses."
INCONSISTENT_MSG = {
    "ro": "Satu RO hanya untuk satu Divisi. Dokumen sumber berasal dari Divisi yang berbeda.",
    "po": "Satu PO hanya untuk satu Divisi. Dokumen sumber berasal dari Divisi yang berbeda.",
    "do": "Satu DO hanya boleh berisi PO dari divisi yang sama",
    "mi": "Satu MI hanya untuk satu Divisi. Dokumen sumber berasal dari Divisi yang berbeda.",
}

CREATE_PATHS = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi",
                "transfers": "transfer", "loans": "loan", "adjustments": "adjustment", "opname": "opname"}
HEAD_COLL = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi", "transfer": "transfers",
             "loan": "loans", "adjustment": "adjustments", "opname": "opname"}
# modul -> (tipe sumber, koleksi header sumber, koleksi baris sumber, fk baris -> header)
MI_SOURCE_MSG = "Sumber MI hanya dari MRO (atau Direct bila diizinkan)."
MI_SOURCE_LOCKED_MSG = "Sumber MI tidak dapat diubah."
MI_SOURCES = ("MRO", "Direct")
SOURCE_OF = {"ro": ("mro", "mro", "mro_lines", "mro_id"), "po": ("ro", "ro", "ro_lines", "ro_id"),
             "do": ("po", "po", "po_lines", "po_id"), "mi": ("mro", "mro", "mro_lines", "mro_id")}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def validate_lines(module: str, lines) -> None:
    if lines is None:
        return
    if not isinstance(lines, list):
        raise HTTPException(400, QTY_MSG)
    for line in lines:
        if not isinstance(line, dict):
            raise HTTPException(400, QTY_MSG)
        if module == "adjustment":
            v = _num(line.get("adjustment"))
            if v is None or abs(v) < 1e-12:
                raise HTTPException(400, ADJ_MSG)
        elif module == "opname":
            if line.get("counted") not in (None, ""):
                v = _num(line.get("counted"))
                if v is None or v < 0:
                    raise HTTPException(400, COUNT_MSG)
        else:
            v = _num(line.get("qty"))
            if v is None or v <= 0:
                raise HTTPException(400, QTY_MSG)


def has_division(v) -> bool:
    return bool(str(v or "").strip())


def _is_global(server, user) -> bool:
    try:
        import division_visibility_layer as dvl
        return bool(dvl._is_global(server, user or {}))
    except Exception:
        return False


def _visible(server, user, division_id) -> bool:
    if _is_global(server, user):
        return True
    allowed = {str(x) for x in ((user or {}).get("divisions") or []) if x}
    return bool(division_id) and str(division_id) in allowed


async def _source_doc_ids(server, module, lines, did=None):
    """Kumpulkan id dokumen sumber dari body (sources / field baris). Bila edit tanpa info sumber
    di body, pakai allocation tersimpan dokumen ini."""
    stype, _hc, lcoll, fk = SOURCE_OF[module]
    doc_ids, line_ids = set(), set()
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        for s in (line.get("sources") or []):
            if not isinstance(s, dict):
                continue
            if s.get(f"{stype}_id"):
                doc_ids.add(str(s.get(f"{stype}_id")))
            elif s.get("line_id") or s.get(f"{stype}_line_id"):
                line_ids.add(str(s.get("line_id") or s.get(f"{stype}_line_id")))
        if line.get(f"{stype}_id"):
            doc_ids.add(str(line.get(f"{stype}_id")))
        elif line.get(f"{stype}_line_id"):
            line_ids.add(str(line.get(f"{stype}_line_id")))
    for lid in line_ids:
        row = await getattr(server.db, lcoll).find_one({"id": lid}, {"_id": 0, fk: 1})
        if row and row.get(fk):
            doc_ids.add(str(row.get(fk)))
    if not doc_ids and did:
        rows = await server.db.allocations.find({"target_doc_id": did, "source_type": stype},
                                                {"_id": 0, "source_doc_id": 1}).to_list(5000)
        doc_ids = {str(r.get("source_doc_id")) for r in rows if r.get("source_doc_id")}
    return doc_ids


async def apply_source_division(server, module, body, user, did=None):
    """Isi/kunci division_id dari dokumen sumber. Mengubah body bila divisi kosong.
    Return "defer" bila sumber tidak ditemukan / di luar kewenangan divisi user: validasi Divisi wajib
    ditunda agar layer keamanan di dalamnya memberi respons otorisasi yang tepat (403/404), bukan
    membocorkan aturan bisnis lebih dulu (urutan: tenant -> izin -> scope divisi -> aturan bisnis)."""
    if module not in SOURCE_OF:
        return None
    _stype, hcoll, _l, _fk = SOURCE_OF[module]
    ids = await _source_doc_ids(server, module, body.get("lines"), did)
    if not ids:
        return None
    divisions, missing = set(), False
    for sid in ids:
        head = await getattr(server.db, hcoll).find_one({"id": sid}, {"_id": 0, "division_id": 1})
        if head is None:
            return None  # sumber tidak ditemukan -> tetap wajib Divisi (layer dalam memberi pesan sumber)
        hd = head.get("division_id")
        if module == "do" and not has_division(hd):
            continue  # PO lama tanpa divisi: diturunkan oleh guard DO
        if not has_division(hd):
            missing = True
            continue
        if not _visible(server, user, hd):
            return "defer"  # sumber di luar kewenangan -> pesan keamanan layer dalam berlaku
        divisions.add(str(hd))
    if len(divisions) > 1:
        raise HTTPException(400, INCONSISTENT_MSG[module])
    if missing:
        raise HTTPException(400, SOURCE_NO_DIV_MSG)
    if not divisions:
        return None
    src_div = next(iter(divisions))
    given = body.get("division_id")
    if has_division(given) and str(given) != src_div:
        raise HTTPException(400, LOCKED_MSG)
    body["division_id"] = src_div
    return None


def install(server):
    app = server.app

    def wrap(path, method, check):
        route = next((r for r in list(app.router.routes)
                      if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set())), None)
        if route is None:
            return
        orig = route.endpoint
        app.router.routes.remove(route)

        async def endpoint(*args, **kwargs):
            await check(kwargs)
            return await orig(*args, **kwargs)
        endpoint.__signature__ = inspect.signature(orig)
        endpoint.__name__ = getattr(orig, "__name__", "endpoint")
        app.add_api_route(path, endpoint, methods=[method], tags=list(getattr(route, "tags", []) or []))

    def make_create_check(module):
        async def check(kw):
            body = kw.get("body")
            if not isinstance(body, dict):
                raise HTTPException(400, DIVISION_MSG)
            validate_lines(module, body.get("lines"))
            if module == "mi":
                st = body.get("source_type")
                if st is None or (isinstance(st, str) and not st.strip()):
                    body["source_type"] = st = "MRO"  # default MI = Dari MRO (tanpa celah sumber kosong)
                if st not in MI_SOURCES:
                    raise HTTPException(400, MI_SOURCE_MSG)
            if await apply_source_division(server, module, body, kw.get("user")) == "defer":
                return  # sumber tak terlihat: layer otorisasi di dalam menolak (403/404)
            if not has_division(body.get("division_id")):
                raise HTTPException(400, DIVISION_MSG)
            if module == "mi" and body.get("source_type") == "MRO":
                # Pra-validasi sebelum header MI ditulis: setiap baris wajib dari baris MRO valid
                # (mencegah header MI yatim saat baris ditolak).
                for ln in body.get("lines") or []:
                    if not isinstance(ln, dict):
                        continue
                    if not ln.get("mro_line_id"):
                        raise HTTPException(400, "MI Dari MRO wajib bersumber dari baris MRO")
                    ml = await server.db.mro_lines.find_one({"id": ln["mro_line_id"]}, {"_id": 0, "item_id": 1})
                    if not ml:
                        raise HTTPException(400, "Baris MRO sumber tidak ditemukan")
                    if str(ml.get("item_id")) != str(ln.get("item_id")):
                        raise HTTPException(400, "Barang MI tidak sesuai dengan barang MRO sumber")
        return check

    for path, module in CREATE_PATHS.items():
        wrap(f"/api/{path}", "POST", make_create_check(module))

    async def on_update(kw):
        module = kw.get("module")
        if module not in HEAD_COLL:
            return
        body = kw.get("body")
        if not isinstance(body, dict):
            return
        validate_lines(module, body.get("lines"))
        if module == "mi" and "source_type" in body:
            if body.get("source_type") not in MI_SOURCES:
                raise HTTPException(400, MI_SOURCE_MSG)
            cur = await server.db.mi.find_one({"id": kw.get("did")}, {"_id": 0, "source_type": 1})
            if cur is not None and (cur.get("source_type") or "MRO") != body.get("source_type"):
                raise HTTPException(400, MI_SOURCE_LOCKED_MSG)
        if await apply_source_division(server, module, body, kw.get("user"), kw.get("did")) == "defer":
            return  # sumber tak terlihat: layer otorisasi di dalam menolak (403/404)
        if "division_id" in body:
            if not has_division(body.get("division_id")):
                raise HTTPException(400, DIVISION_MSG)
        elif module != "do":
            doc = await getattr(server.db, HEAD_COLL[module]).find_one({"id": kw.get("did")}, {"_id": 0, "division_id": 1})
            if doc is not None and not has_division(doc.get("division_id")):
                raise HTTPException(400, DIVISION_MSG)
    wrap("/api/transactions/{module}/{did}", "PUT", on_update)

    def make_stored_check(coll):
        async def check(kw):
            doc = await getattr(server.db, coll).find_one({"id": kw.get("did")}, {"_id": 0, "division_id": 1})
            if doc is not None and not has_division(doc.get("division_id")):
                raise HTTPException(400, DIVISION_MSG)
        return check

    for coll in ("mro", "ro", "po", "opname"):
        wrap(f"/api/{coll}/{{did}}/submit", "POST", make_stored_check(coll))
    wrap("/api/opname/{did}/post", "POST", make_stored_check("opname"))

    async def on_count(kw):
        body = kw.get("body")
        if isinstance(body, dict):
            validate_lines("opname", body.get("lines"))
    wrap("/api/opname/{did}/count", "PUT", on_count)
