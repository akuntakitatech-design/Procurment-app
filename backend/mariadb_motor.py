"""
mariadb_motor — lapisan kompatibel Motor (MongoDB async) di atas MariaDB.

Tujuan: memindahkan seluruh penyimpanan ProcureFlow ke MariaDB TANPA mengubah
logika bisnis yang tersebar di ~36 modul (455 pemanggilan `db.<koleksi>.<metode>`).

Model penyimpanan (mudah dibaca di phpMyAdmin):
  - Satu TABEL per koleksi (nama = nama koleksi, mis. `items`, `po_lines`).
  - Kolom fisik : pk VARCHAR(64) PRIMARY KEY (= doc.id bila ada, jika tidak UUID),
                  doc LONGTEXT JSON (isi dokumen lengkap), created_at, updated_at.
  - Kolom generated STORED dari JSON untuk field skalar top-level (id, code, no,
    status, *_id, dst) + INDEX → terlihat sebagai kolom nyata di phpMyAdmin dan
    dipakai untuk pushdown filter ke SQL.

Semantik query:
  - Filter sederhana (kesetaraan / $in pada field skalar top-level yang punya kolom)
    di-pushdown ke SQL, sisanya (dan SELALU sebagai verifikasi ulang) dievaluasi
    dengan matcher Python yang mengikuti semantik MongoDB untuk subset operator
    yang dipakai aplikasi: eq (termasuk array-contains), $ne, $in, $nin, $exists,
    $gt/$gte/$lt/$lte, $regex/$options, $not, $and, $or, $nor, path bertitik.
  - Update: $set, $unset, $inc, $setOnInsert, $push (dasar), upsert. Dilakukan dalam
    transaksi dengan SELECT ... FOR UPDATE agar counter/nomor dokumen aman (atomik).
  - Aggregate: $match, $group ($sum/$count/$avg/$min/$max/$first/$last/$push),
    $sort, $skip, $limit, $project (inklusi), $unwind (dasar).

Yang TIDAK di-emulasi: ObjectId (`_id` tidak pernah dikembalikan; aplikasi memang
selalu memproyeksikan {"_id": 0} atau melakukan pop), session/transaksi Mongo.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import time
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

import aiomysql
import pymysql

logger = logging.getLogger("mariadb_motor")
# Statistik query per request [jumlah, total detik, query terlama] — diisi DbStatsMiddleware.
DB_STATS: contextvars.ContextVar = contextvars.ContextVar("db_stats", default=None)
_REQ_CACHED = {"users", "tenants"}
# Cache referensi per request GET (mis. maps()) agar tidak dimuat berulang oleh beberapa layer.
REQ_CACHE: contextvars.ContextVar = contextvars.ContextVar("req_cache", default=None)
# P7 — memo baca massal per request GET: SELECT identik (SQL + parameter sama) dalam satu request dibaca sekali dari DB.
# Baris disimpan apa adanya (tuple string/datetime, immutable) dan setiap pemanggil mem-parse JSON sendiri (tanpa objek
# bersama). Setiap tulis (INSERT/UPDATE/DELETE, termasuk di transaksi) mengosongkan memo; memo ditutup saat request selesai
# (task background turunan request tidak memakai memo lama). Batas baris agar memori tetap terkendali.
REQ_READS: contextvars.ContextVar = contextvars.ContextVar("req_reads", default=None)
_READ_MEMO_MAX_ROWS = int(os.environ.get("DB_READ_MEMO_MAX_ROWS") or 2_000_000)
# Anggaran memori memo GLOBAL (seluruh request bersamaan dalam satu proses), perkiraan byte isi baris.
_READ_MEMO_BUDGET = int(os.environ.get("DB_READ_MEMO_BUDGET_MB") or 256) * 1024 * 1024
_READ_MEMO_USED = [0]
# P7 — jalur baca adaptif per BENTUK SQL (teks SQL dengan placeholder; parameter tidak ikut). Bentuk yang rata-rata
# hasilnya kecil (<= MARIADB_SYNC_MIN_ROWS, default 64) dibaca aiomysql langsung (tanpa thread hop) dan tidak memakai
# top-k 2 tahap; bentuk besar tetap PyMySQL di thread. Hanya memilih JALUR; SQL, konverter & hasil identik.
_SHAPE_SMALL_ROWS = int(os.environ.get("MARIADB_SYNC_MIN_ROWS") or 64)
_SHAPE_MAX = 8192
_SHAPE_ROWS: Dict[str, float] = {}


def _shape_is_small(sql: str) -> bool:
    v = _SHAPE_ROWS.get(sql)
    return v is not None and v <= _SHAPE_SMALL_ROWS


def _shape_note(sql: str, n: int) -> None:
    v = _SHAPE_ROWS.get(sql)
    if v is None and len(_SHAPE_ROWS) >= _SHAPE_MAX:
        _SHAPE_ROWS.clear()  # batas memori sederhana; statistik terbentuk ulang dalam beberapa query
    _SHAPE_ROWS[sql] = float(n) if v is None else v * 0.7 + n * 0.3




def _rows_bytes(rows) -> int:
    return sum(len(v) for r in rows for v in r if isinstance(v, (str, bytes)))


def _memo_clear(memo: dict) -> None:
    _READ_MEMO_USED[0] = max(0, _READ_MEMO_USED[0] - memo["bytes"])
    memo["data"].clear(); memo["rows"] = 0; memo["bytes"] = 0; memo["gen"] += 1


def _reads_invalidate() -> None:
    memo = REQ_READS.get()
    if memo is not None:
        _memo_clear(memo)


def _reads_tx(delta: int) -> None:
    memo = REQ_READS.get()
    if memo is not None:
        memo["tx"] = max(0, memo["tx"] + delta)
        _memo_clear(memo)


def new_read_memo() -> dict:
    return {"data": {}, "inflight": {}, "rows": 0, "bytes": 0, "gen": 0, "tx": 0, "open": True}


def close_read_memo(memo: dict) -> None:
    memo["open"] = False
    _memo_clear(memo)


# P7 — urutan dasar `ORDER BY created_at ASC, pk ASC` dihitung di Python (MariaDB filesort baris lebar / lookup acak jauh
# lebih lambat). Identik dengan SQL: created_at DATETIME(6) dibandingkan sebagai datetime; pk hanya menentukan urutan bila
# created_at sama, dan untuk pk berkarakter [0-9a-z-] urutan kode-titik Python == urutan collation utf8mb4_unicode_ci
# (PAD SPACE: spasi < '-' < digit < huruf, case-insensitive tidak relevan untuk huruf kecil). Bila ada created_at kembar
# dengan pk di luar pola tsb -> None (pemanggil memakai ORDER BY SQL asli).
_PK_SAFE = re.compile(r"[0-9a-z-]*\Z")
_PK_SAFE_CH = frozenset("0123456789abcdefghijklmnopqrstuvwxyz-")


def _pk_pair_safe(a: str, b: str) -> bool:
    """True bila urutan kode-titik Python a vs b PASTI sama dengan utf8mb4_unicode_ci: prefiks bersama identik (bobot sama),
    lalu karakter pembeda pertama (atau akhir string = PAD SPACE) keduanya dari [0-9a-z-] (bobot primer berbeda & urutan sama)."""
    i = len(os.path.commonprefix((a, b)))
    ca = a[i] if i < len(a) else None
    cb = b[i] if i < len(b) else None
    if ca is None and cb is None:
        return False
    return (ca is None or ca in _PK_SAFE_CH) and (cb is None or cb in _PK_SAFE_CH)


_INDEX_ORDERED = {"", "`tenant_id` = %s"}  # idx_<t>_created (created_at, pk) / idx_<t>_tenant (tenant_id, created_at[, pk])


def _py_order_wanted(where: str) -> bool:
    """Urutan Python hanya bila SQL butuh filesort. Tanpa WHERE / hanya tenant: indeks sudah memberi urutan (scan berurutan
    lebih cepat daripada scan tak berurut + sort Python) -> ORDER BY SQL tetap dipakai."""
    # Default NONAKTIF (opt-in MARIADB_PY_ORDER=1): pada benchmark terkontrol 2026-10-12 (buffer pool memadai) ORDER BY SQL
    # lebih murah — Control Center -11%, Invoice Vendor -9%, endpoint lain setara. Urutan Python tetap tersedia & teruji
    # (identik) untuk server dengan buffer pool kecil, di mana filesort baris lebar memicu baca disk acak.
    return os.environ.get("MARIADB_PY_ORDER", "0") == "1" and (where or "").strip() not in _INDEX_ORDERED


# created_at dibaca sebagai teks tetap-lebar 'YYYY-MM-DD HH:MM:SS.ffffff' (DATETIME(6) -> CAST CHAR selalu 6 digit pecahan):
# urutan & kesamaan leksikografis == urutan & kesamaan datetime, tanpa biaya konversi datetime per baris di Python
# (±1,8 µs/baris; Control Center memuat ±55.000 baris). Hanya dipakai untuk mengurutkan; tidak dikembalikan ke pemanggil.
_CREATED_TXT = "CAST(created_at AS CHAR)"


def _py_order(rows):
    """rows: urutan bebas, kolom 0 = pk, kolom 1 = created_at. Hasil terurut (created_at, pk) atau None (pakai SQL)."""
    if any(r[1] is None for r in rows):
        return None
    out = sorted(rows, key=lambda r: (r[1], r[0]))
    safe = _PK_SAFE.match
    for i in range(1, len(out)):
        if out[i][1] == out[i - 1][1]:
            a, b = out[i - 1][0], out[i][0]
            # Jalur cepat (hasil sama dengan _pk_pair_safe): kedua pk seluruhnya [0-9a-z-] dan berbeda -> karakter pembeda /
            # akhir string pasti dari himpunan aman. Selain itu pemeriksaan per karakter (commonprefix).
            if a != b and isinstance(a, str) and isinstance(b, str) and safe(a) and safe(b):
                continue
            if not _pk_pair_safe(a, b):
                return None
    return out


_LOG_SQL = os.environ.get("DB_LOG_SQL") == "1"


def _track(t0: float, sql: str = "") -> None:
    st = DB_STATS.get()
    if st is not None:
        dt = time.perf_counter() - t0
        st[0] += 1; st[1] += dt; st[2] = max(st[2], dt)
        if _LOG_SQL:
            logger.warning("SQL %.0fms %s", dt * 1000, sql[:160])


_SCALAR = (str, int, float, bool, type(None))
_MISSING = object()


# ---------------------------------------------------------------------------
# Hasil operasi (kompatibel pymongo)
# ---------------------------------------------------------------------------
class InsertOneResult:
    def __init__(self, inserted_id): self.inserted_id = inserted_id; self.acknowledged = True

class InsertManyResult:
    def __init__(self, ids): self.inserted_ids = ids; self.acknowledged = True

class UpdateResult:
    def __init__(self, matched, modified, upserted_id=None):
        self.matched_count = matched; self.modified_count = modified
        self.upserted_id = upserted_id; self.acknowledged = True
    @property
    def raw_result(self): return {"n": self.matched_count, "nModified": self.modified_count}

class DeleteResult:
    def __init__(self, deleted): self.deleted_count = deleted; self.acknowledged = True

class ReturnDocument:
    BEFORE = False
    AFTER = True


# ---------------------------------------------------------------------------
# Matcher: semantik filter MongoDB (subset) di Python
# ---------------------------------------------------------------------------
def _get_path(doc: Any, path: str):
    """Ambil nilai path bertitik. Mengembalikan _MISSING jika tidak ada.
    Jika melewati array, mengembalikan list nilai (semantik Mongo)."""
    if type(doc) is dict and "." not in path:  # P7: jalur cepat field top-level (identik dengan loop di bawah)
        return doc[path] if path in doc else _MISSING
    cur = doc
    parts = path.split(".")
    for i, part in enumerate(parts):
        if isinstance(cur, dict):
            if part not in cur:
                return _MISSING
            cur = cur[part]
        elif isinstance(cur, list):
            if part.isdigit():
                idx = int(part)
                if idx >= len(cur):
                    return _MISSING
                cur = cur[idx]
            else:
                rest = ".".join(parts[i:])
                vals = []
                for el in cur:
                    v = _get_path(el, rest)
                    if v is not _MISSING:
                        vals.extend(v if isinstance(v, list) else [v])
                return vals if vals else _MISSING
        else:
            return _MISSING
    return cur


def _type_rank(v: Any) -> int:
    # urutan perbandingan BSON (disederhanakan)
    if v is _MISSING or v is None: return 0
    if isinstance(v, bool): return 3
    if isinstance(v, (int, float)): return 1
    if isinstance(v, str): return 2
    if isinstance(v, dict): return 4
    if isinstance(v, list): return 5
    return 6


def _cmp_ok(a: Any, b: Any) -> bool:
    """Perbandingan relasional hanya berlaku untuk tipe yang sama (semantik Mongo)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)): return True
    if isinstance(a, str) and isinstance(b, str): return True
    return False


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _value_matches(value: Any, cond: Any) -> bool:
    """value = nilai field (bisa _MISSING / list). cond = nilai literal atau dict operator."""
    if type(cond) is _OpDict or (isinstance(cond, dict) and cond and all(isinstance(k, str) and k.startswith("$") for k in cond)):
        for op, arg in cond.items():
            if not _op_matches(value, op, arg):
                return False
        return True
    # kesetaraan literal
    if cond is None:
        return value is _MISSING or value is None or (isinstance(value, list) and None in value)
    if value is _MISSING:
        return False
    if isinstance(value, list) and not isinstance(cond, list):
        return any(_eq(el, cond) for el in value)
    return _eq(value, cond)


_IN_FAST_TYPES = (str, int, float, bool, type(None))


class _InList(list):
    """Daftar argumen `$in`/`$nin` hasil `_compile_filter` (sekali per query) + lookup set O(1).

    `lookup` berisi kunci `(is_bool, nilai)` agar semantik `_eq` identik (True ≠ 1, 1 == 1.0). `lookup` = None
    (fallback ke perbandingan linear lama) bila ada elemen di luar str/int/float/bool/None (mis. `$regex` dict,
    list, datetime) atau NaN.
    """
    __slots__ = ("lookup", "has_none")

    def __init__(self, items):
        super().__init__(items)
        self.has_none = None in self
        ok = all(type(a) in _IN_FAST_TYPES for a in self) and not any(type(a) is float and a != a for a in self)
        self.lookup = frozenset((isinstance(a, bool), a) for a in self) if ok else None


class _OpDict(dict):
    """Dict operator (`{"$in": .., "$ne": ..}`) hasil `_compile_filter`: tidak kosong & semua kunci str berawalan `$`.
    Hanya penanda agar `_value_matches` tidak memeriksa ulang kunci per dokumen (P7); isi & semantik sama dengan dict biasa."""
    __slots__ = ()


def _compile_filter(flt: Any) -> Any:
    """Salinan filter dengan argumen `$in`/`$nin` dibungkus `_InList`. Filter asli tidak diubah."""
    if isinstance(flt, dict):
        out = {k: (_InList(v) if k in ("$in", "$nin") and isinstance(v, (list, tuple)) else _compile_filter(v))
               for k, v in flt.items()}
        if out and all(isinstance(k, str) and k.startswith("$") for k in out):
            return _OpDict(out)
        return out
    if isinstance(flt, list):
        return [_compile_filter(x) for x in flt]
    return flt


def _in_fast(value: Any, arg: "_InList") -> bool:
    """Ekuivalen dengan cabang `$in` linear untuk `arg.lookup` yang valid."""
    if value is _MISSING:
        return arg.has_none
    lookup = arg.lookup
    if not isinstance(value, list):  # P7: skalar tanpa membuat list sementara (identik)
        try:
            return (isinstance(value, bool), value) in lookup
        except TypeError:
            return False
    for v in value:
        try:
            if (isinstance(v, bool), v) in lookup:
                return True
        except TypeError:  # nilai tak-hashable (dict/list) tidak pernah == skalar
            continue
    return False


def _op_matches(value: Any, op: str, arg: Any) -> bool:
    if op == "$eq":
        return _value_matches(value, arg)
    if op == "$ne":
        return not _value_matches(value, arg)
    if op == "$in":
        if isinstance(arg, _InList) and arg.lookup is not None:
            return _in_fast(value, arg)
        arg = list(arg or [])
        if value is _MISSING:
            return None in arg
        vals = value if isinstance(value, list) else [value]
        for a in arg:
            if isinstance(a, dict) and "$regex" in a:
                if any(isinstance(v, str) and _regex(a).search(v) for v in vals): return True
            elif any(_eq(v, a) for v in vals) or (a is None and value is None):
                return True
        return False
    if op == "$nin":
        return not _op_matches(value, "$in", arg)
    if op == "$exists":
        exists = value is not _MISSING
        return exists if arg else not exists
    if op in ("$gt", "$gte", "$lt", "$lte"):
        if value is _MISSING: return False
        vals = value if isinstance(value, list) else [value]
        for v in vals:
            if not _cmp_ok(v, arg): continue
            if op == "$gt" and v > arg: return True
            if op == "$gte" and v >= arg: return True
            if op == "$lt" and v < arg: return True
            if op == "$lte" and v <= arg: return True
        return False
    if op == "$regex":
        if value is _MISSING: return False
        vals = value if isinstance(value, list) else [value]
        rx = _regex({"$regex": arg})
        return any(isinstance(v, str) and rx.search(v) for v in vals)
    if op == "$options":
        return True  # ditangani bersama $regex
    if op == "$not":
        return not _value_matches(value, arg)
    if op == "$size":
        return isinstance(value, list) and len(value) == arg
    if op == "$elemMatch":
        return isinstance(value, list) and any(_match(el, arg) if isinstance(el, dict) else _value_matches(el, arg) for el in value)
    if op == "$all":
        return isinstance(value, list) and all(any(_eq(v, a) for v in value) for a in arg)
    if op == "$type":
        return True
    raise NotImplementedError(f"Operator filter belum didukung: {op}")


_regex_cache: Dict[Tuple[str, str], re.Pattern] = {}
def _regex(cond: dict) -> re.Pattern:
    pat = cond.get("$regex"); opts = cond.get("$options", "") or ""
    if isinstance(pat, re.Pattern): return pat
    key = (pat, opts)
    if key not in _regex_cache:
        flags = 0
        if "i" in opts: flags |= re.IGNORECASE
        if "m" in opts: flags |= re.MULTILINE
        if "s" in opts: flags |= re.DOTALL
        if "x" in opts: flags |= re.VERBOSE
        _regex_cache[key] = re.compile(pat, flags)
    return _regex_cache[key]


def _match(doc: dict, flt: Optional[dict]) -> bool:
    if not flt:
        return True
    for key, cond in flt.items():
        if type(cond) is str and key[:1] != "$":
            # P7: jalur cepat kesetaraan literal string (tenant_id/item_id/status...). Identik dengan
            # _value_matches(_get_path(doc, key), cond): hilang -> False; list -> ada elemen == cond (bool/angka/dict tidak
            # pernah == str); skalar -> v == cond.
            v = _get_path(doc, key)
            if not ((cond in v) if type(v) is list else v == cond): return False
            continue
        if key == "$and":
            for c in cond:
                if not _match(doc, c): return False
        elif key == "$or":
            if not any(_match(doc, c) for c in cond): return False
        elif key == "$nor":
            if any(_match(doc, c) for c in cond): return False
        elif key == "$expr" or key == "$where":
            raise NotImplementedError(f"Operator {key} belum didukung")
        else:
            cond2 = cond
            if isinstance(cond, dict) and "$regex" in cond:
                # gabungkan $regex + $options
                cond2 = dict(cond)
                rx = _regex(cond2); cond2.pop("$options", None); cond2["$regex"] = rx
            if not _value_matches(_get_path(doc, key), cond2): return False
    return True


# ---------------------------------------------------------------------------
# Sort (semantik urutan tipe BSON disederhanakan)
# ---------------------------------------------------------------------------
def _sort_key(v: Any):
    if v is _MISSING or v is None: return (0, 0)
    if isinstance(v, bool): return (3, int(v))
    if isinstance(v, (int, float)): return (1, v)
    if isinstance(v, str): return (2, v)
    if isinstance(v, dict): return (4, json.dumps(v, sort_keys=True, default=str))
    if isinstance(v, list):
        return (5, [_sort_key(x) for x in v])
    return (6, str(v))


def _normalize_sort(key_or_list, direction=None) -> List[Tuple[str, int]]:
    if key_or_list is None: return []
    if isinstance(key_or_list, str):
        return [(key_or_list, int(direction or 1))]
    if isinstance(key_or_list, dict):
        return [(k, int(v)) for k, v in key_or_list.items()]
    out = []
    for item in key_or_list:
        if isinstance(item, str): out.append((item, 1))
        else: out.append((item[0], int(item[1])))
    return out


def _apply_sort(docs: List[dict], spec: List[Tuple[str, int]]) -> List[dict]:
    for field, direction in reversed(spec):
        docs.sort(key=lambda d: _sort_key(_get_path(d, field)), reverse=(direction < 0))
    return docs


def _apply_sort_rows(rows: List[Tuple[str, dict]], spec: List[Tuple[str, int]]) -> List[Tuple[str, dict]]:
    """`_apply_sort` untuk pasangan (pk, dokumen) — urutan stabil identik."""
    for field, direction in reversed(spec):
        rows.sort(key=lambda r: _sort_key(_get_path(r[1], field)), reverse=(direction < 0))
    return rows


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------
def _project(doc: dict, projection, copy: bool = True) -> dict:
    """copy=False hanya untuk dokumen yang baru di-parse dari DB dan tidak dipakai di tempat lain (P7: tanpa deepcopy)."""
    if not projection:
        return doc
    if isinstance(projection, (list, tuple, set)):
        projection = {k: 1 for k in projection}
    keys = {k: v for k, v in projection.items() if k != "_id"}
    if not keys:
        return doc
    include = any(bool(v) for v in keys.values())
    if include:
        out: dict = {}
        for k, v in keys.items():
            if not v: continue
            val = _get_path(doc, k)
            if val is _MISSING: continue
            _set_path(out, k, deepcopy(val) if copy else val)
        return out
    out = deepcopy(doc) if copy else doc
    for k in keys:
        _unset_path(out, k)
    return out


# ---------------------------------------------------------------------------
# Update operators
# ---------------------------------------------------------------------------
def _set_path(doc: dict, path: str, value: Any):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        if isinstance(cur, list) and p.isdigit():
            idx = int(p)
            while len(cur) <= idx: cur.append(None)
            if not isinstance(cur[idx], (dict, list)): cur[idx] = {}
            cur = cur[idx]
            continue
        if p not in cur or not isinstance(cur[p], (dict, list)):
            cur[p] = {}
        cur = cur[p]
    last = parts[-1]
    if isinstance(cur, list) and last.isdigit():
        idx = int(last)
        while len(cur) <= idx: cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


def _unset_path(doc: dict, path: str):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        if isinstance(cur, dict) and p in cur: cur = cur[p]
        else: return
    if isinstance(cur, dict): cur.pop(parts[-1], None)


def _apply_update(doc: dict, update: dict, *, is_insert: bool = False) -> dict:
    if not update:
        return doc
    if not any(k.startswith("$") for k in update):
        # replacement document
        new = deepcopy(update)
        if "id" in doc and "id" not in new: new["id"] = doc["id"]
        return new
    for op, args in update.items():
        if op == "$set":
            for k, v in args.items(): _set_path(doc, k, deepcopy(v))
        elif op == "$unset":
            for k in args: _unset_path(doc, k)
        elif op == "$inc":
            for k, v in args.items():
                cur = _get_path(doc, k)
                base = 0 if cur is _MISSING or cur is None else cur
                _set_path(doc, k, base + v)
        elif op == "$setOnInsert":
            if is_insert:
                for k, v in args.items(): _set_path(doc, k, deepcopy(v))
        elif op == "$push":
            for k, v in args.items():
                cur = _get_path(doc, k)
                arr = [] if cur is _MISSING or cur is None else list(cur)
                if isinstance(v, dict) and "$each" in v: arr.extend(deepcopy(v["$each"]))
                else: arr.append(deepcopy(v))
                _set_path(doc, k, arr)
        elif op == "$addToSet":
            for k, v in args.items():
                cur = _get_path(doc, k)
                arr = [] if cur is _MISSING or cur is None else list(cur)
                items = v["$each"] if isinstance(v, dict) and "$each" in v else [v]
                for it in items:
                    if it not in arr: arr.append(deepcopy(it))
                _set_path(doc, k, arr)
        elif op == "$pull":
            for k, v in args.items():
                cur = _get_path(doc, k)
                if isinstance(cur, list):
                    _set_path(doc, k, [el for el in cur if not _value_matches(el, v)])
        elif op == "$currentDate":
            for k in args: _set_path(doc, k, datetime.now(timezone.utc).isoformat())
        elif op in ("$min", "$max"):
            for k, v in args.items():
                cur = _get_path(doc, k)
                if cur is _MISSING or cur is None or (op == "$min" and v < cur) or (op == "$max" and v > cur):
                    _set_path(doc, k, v)
        else:
            raise NotImplementedError(f"Operator update belum didukung: {op}")
    return doc


def _upsert_seed(flt: dict) -> dict:
    """Dokumen dasar untuk upsert: field kesetaraan dari filter (semantik Mongo)."""
    seed: dict = {}
    for k, v in (flt or {}).items():
        if k.startswith("$"):
            if k == "$and":
                for c in v: seed.update(_upsert_seed(c))
            continue
        if isinstance(v, dict) and any(str(x).startswith("$") for x in v):
            if "$eq" in v: _set_path(seed, k, deepcopy(v["$eq"]))
            continue
        _set_path(seed, k, deepcopy(v))
    return seed


# ---------------------------------------------------------------------------
# Aggregate (subset)
# ---------------------------------------------------------------------------
def _expr(doc: dict, expr: Any):
    if isinstance(expr, str) and expr.startswith("$"):
        v = _get_path(doc, expr[1:])
        return None if v is _MISSING else v
    if isinstance(expr, dict):
        out = {}
        for k, v in expr.items():
            if k.startswith("$"):
                if k in ("$sum", "$add"):
                    vals = [_expr(doc, x) for x in (v if isinstance(v, list) else [v])]
                    return sum(x for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool))
                if k == "$multiply":
                    r = 1
                    for x in v: r *= (_expr(doc, x) or 0)
                    return r
                if k == "$ifNull":
                    a = _expr(doc, v[0]); return _expr(doc, v[1]) if a is None else a
                if k == "$toLower": return str(_expr(doc, v) or "").lower()
                if k == "$toUpper": return str(_expr(doc, v) or "").upper()
                if k == "$literal": return v
                raise NotImplementedError(f"Ekspresi aggregate belum didukung: {k}")
            out[k] = _expr(doc, v)
        return out
    return expr


def _aggregate(docs: List[dict], pipeline: List[dict]) -> List[dict]:
    rows = docs
    for stage in pipeline:
        (name, spec), = stage.items()
        if name == "$match":
            cspec = _compile_filter(spec)
            rows = [d for d in rows if _match(d, cspec)]
        elif name == "$sort":
            rows = _apply_sort(list(rows), _normalize_sort(spec))
        elif name == "$skip":
            rows = rows[spec:]
        elif name == "$limit":
            rows = rows[:spec]
        elif name == "$project":
            rows = [_project(d, spec) if all(v in (0, 1, True, False) for v in spec.values()) else {k: _expr(d, v) if not v in (0, 1, True, False) else _get_path(d, k) for k, v in spec.items() if v} for d in rows]
        elif name == "$unwind":
            path = spec if isinstance(spec, str) else spec["path"]
            out = []
            for d in rows:
                arr = _get_path(d, path[1:])
                if isinstance(arr, list):
                    for el in arr:
                        nd = deepcopy(d); _set_path(nd, path[1:], el); out.append(nd)
            rows = out
        elif name == "$group":
            groups: Dict[str, dict] = {}
            order: List[str] = []
            for d in rows:
                gid_val = _expr(d, spec["_id"]) if spec["_id"] is not None else None
                gk = json.dumps(gid_val, sort_keys=True, default=str)
                if gk not in groups:
                    groups[gk] = {"_id": gid_val}; order.append(gk)
                    for field, acc in spec.items():
                        if field == "_id": continue
                        (op, arg), = acc.items()
                        groups[gk][field] = 0 if op in ("$sum", "$count") else ([] if op in ("$push", "$addToSet") else None)
                        if op == "$avg": groups[gk][f"__avg_{field}"] = [0, 0]
                g = groups[gk]
                for field, acc in spec.items():
                    if field == "_id": continue
                    (op, arg), = acc.items()
                    if op == "$sum":
                        v = _expr(d, arg)
                        if isinstance(v, (int, float)) and not isinstance(v, bool): g[field] += v
                    elif op == "$count":
                        g[field] += 1
                    elif op == "$avg":
                        v = _expr(d, arg)
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            g[f"__avg_{field}"][0] += v; g[f"__avg_{field}"][1] += 1
                    elif op == "$min":
                        v = _expr(d, arg)
                        if v is not None and (g[field] is None or v < g[field]): g[field] = v
                    elif op == "$max":
                        v = _expr(d, arg)
                        if v is not None and (g[field] is None or v > g[field]): g[field] = v
                    elif op == "$first":
                        if g[field] is None: g[field] = _expr(d, arg)
                    elif op == "$last":
                        g[field] = _expr(d, arg)
                    elif op == "$push":
                        g[field].append(_expr(d, arg))
                    elif op == "$addToSet":
                        v = _expr(d, arg)
                        if v not in g[field]: g[field].append(v)
                    else:
                        raise NotImplementedError(f"Akumulator belum didukung: {op}")
            out = []
            for gk in order:
                g = groups[gk]
                for k in [k for k in g if k.startswith("__avg_")]:
                    s, n = g.pop(k); g[k[6:]] = (s / n) if n else None
                out.append(g)
            rows = out
        elif name == "$count":
            rows = [{spec: len(rows)}]
        else:
            raise NotImplementedError(f"Stage aggregate belum didukung: {name}")
    return rows


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------
class MariaCursor:
    def __init__(self, coll: "MariaCollection", flt: Optional[dict], projection=None):
        self._coll = coll; self._filter = flt or {}; self._projection = projection
        self._sort: List[Tuple[str, int]] = []; self._skip = 0; self._limit = 0
        self._result: Optional[List[dict]] = None; self._idx = 0

    def sort(self, key_or_list, direction=None):
        self._sort = _normalize_sort(key_or_list, direction); return self
    def skip(self, n: int): self._skip = int(n or 0); return self
    def limit(self, n: int): self._limit = int(n or 0); return self
    def batch_size(self, n): return self
    def hint(self, *_): return self

    async def _run(self) -> List[dict]:
        if self._result is None:
            pf = _include_fields(self._projection)
            ff = _filter_fields(self._filter or {}) if pf else None
            if pf and ff is not None and all(_FIELD.match(f) for f, _ in self._sort):
                # P7: projection include top-level -> hanya field filter+sort+projection yang dimuat (JSON_EXTRACT), bukan dokumen penuh.
                # `_project` atas dokumen-mini == `_project` atas dokumen penuh (field yang sama, field hilang tetap hilang).
                rows = await self._coll._select_fields(self._filter, ff | pf | {f for f, _ in self._sort})
                docs = [d for _, d in rows]
            else:
                docs = await self._coll._select(self._filter)
            if self._sort: docs = _apply_sort(docs, self._sort)
            self._n_matched = len(docs)
            if self._skip: docs = docs[self._skip:]
            if self._limit: docs = docs[: self._limit]
            self._result = [_project(d, self._projection, copy=False) for d in docs]
        return self._result

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if self._result is None and (self._limit or length) and (self._sort or not _has_id_eq(self._filter)):
            # P7: (sort +) batas -> top-k dua tahap (identik), tanpa memuat/mem-parse seluruh dokumen yang cocok.
            # Lookup by id/pk tanpa sort tetap jalur lama (1 baris, 1 query).
            k = min(x for x in (self._limit or None, length) if x)
            hint: dict = {}
            docs = await self._coll._select_topk(self._filter, self._sort, self._skip + k, hint) if self._skip + k <= _TOPK_MAX else None
            if docs is not None:
                return [_project(d, self._projection, copy=False) for d in docs[self._skip:self._skip + k]]
            if hint.get("shape"):
                docs = await self._run()
                # statistik bentuk top-k tetap diperbarui dari jumlah dokumen cocok (jalur penuh) -> bila data tumbuh,
                # top-k 2 tahap dipakai lagi. Hanya memilih JALUR; hasil identik.
                _shape_note(hint["shape"], getattr(self, "_n_matched", len(docs)))
                return docs[:length] if length is not None else docs
        docs = await self._run()
        if length is not None:
            docs = docs[:length]
        return docs

    def __aiter__(self): return self
    async def __anext__(self):
        docs = await self._run()
        if self._idx >= len(docs): raise StopAsyncIteration
        d = docs[self._idx]; self._idx += 1; return d

    async def count(self): return len(await self._run())
    async def distinct(self, key):
        return _distinct(await self._run(), key)
    def clone(self):
        c = MariaCursor(self._coll, self._filter, self._projection); c._sort = list(self._sort); c._skip = self._skip; c._limit = self._limit; return c


class _ListCursor:
    def __init__(self, rows: List[dict]): self._rows = rows; self._idx = 0
    async def to_list(self, length=None): return self._rows[:length] if length is not None else list(self._rows)
    def __aiter__(self): return self
    async def __anext__(self):
        if self._idx >= len(self._rows): raise StopAsyncIteration
        r = self._rows[self._idx]; self._idx += 1; return r


def _distinct(docs: List[dict], key: str) -> list:
    seen = []; out = []
    for d in docs:
        v = _get_path(d, key)
        if v is _MISSING: continue
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            k = json.dumps(x, sort_keys=True, default=str)
            if k not in seen: seen.append(k); out.append(x)
    return out


# ---------------------------------------------------------------------------
# Koleksi
# ---------------------------------------------------------------------------
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def _q(name: str) -> str:
    if not _IDENT.match(name): raise ValueError(f"Nama identifier tidak valid: {name}")
    return f"`{name}`"


def _json_dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, default=str)


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, str) and len(value) >= 10:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is not None: dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            return None
    return None


def _sql_value(v: Any):
    """Nilai parameter untuk dibandingkan dengan kolom generated (hasil JSON_VALUE = string)."""
    if isinstance(v, bool): return "true" if v else "false"
    return v


def _pick_pk(doc: dict) -> str:
    """Primary key deterministik untuk dokumen baru.

    - `id` string → pk = id (kompatibel dengan data lama, lookup by id cepat).
    - Bila dokumen ber-`tenant_id` (multi-tenant), pk = "<tenant_id>:<id>" karena `id` yang sama
      (mis. settings `numbering`, `company`) boleh ada di tiap tenant.
    - Panjang dibatasi 64 karakter (kolom pk); bila lebih, dipadatkan dengan sha1.
    - Tanpa `id` → UUID.
    """
    doc_id = doc.get("id")
    if not (isinstance(doc_id, str) and doc_id):
        return str(uuid.uuid4())
    tenant = doc.get("tenant_id")
    pk = f"{tenant}:{doc_id}" if isinstance(tenant, str) and tenant else doc_id
    if len(pk) > 64:
        import hashlib
        pk = pk[:23] + "~" + hashlib.sha1(pk.encode("utf-8")).hexdigest()
    return pk


# Kolom fisik (bukan generated dari doc) — tidak dipakai untuk pushdown operator P7 di bawah.
_PHYSICAL_COLS = {"pk", "doc", "created_at", "updated_at"}
_RANGE_SQL = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_LOGICAL = {"$and", "$or", "$nor"}
_TOPK_MAX = 5000  # di atas ini (mis. to_list(200000) = "semua") jalur penuh satu query lebih murah
# Top-k 2 tahap hanya bila rata-rata kandidat bentuk SQL > _TOPK_GAIN x k (dokumen penuh yang tidak dimuat sebanding biaya ekstra).
_TOPK_GAIN = float(os.environ.get("MARIADB_TOPK_GAIN") or 4)


def _include_fields(projection) -> Optional[set]:
    """Field projection include top-level sederhana (mis. {"_id": 0, "id": 1, "qty": 1}); None bila bukan pola tsb."""
    if not projection:
        return None
    if isinstance(projection, (list, tuple, set)):
        projection = {k: 1 for k in projection}
    if not isinstance(projection, dict):
        return None
    keys = {k: v for k, v in projection.items() if k != "_id"}
    if not keys or not all(v is True or v == 1 for v in keys.values()):
        return None
    if not all(isinstance(k, str) and _FIELD.match(k) for k in keys):
        return None
    return set(keys)


def _has_id_eq(flt: Any) -> bool:
    """Filter memuat kesetaraan skalar `id`/`pk` (langsung atau di dalam `$and`, mis. hasil proxy tenant)."""
    if not isinstance(flt, dict):
        return False
    return any((k in ("id", "pk") and not isinstance(v, dict)) or (k == "$and" and isinstance(v, (list, tuple)) and any(_has_id_eq(c) for c in v))
               for k, v in flt.items())


def _filter_fields(flt: Any) -> Optional[set]:
    """Nama field top-level yang dibaca `_match(doc, flt)`; None bila filter tidak bisa dievaluasi dari field tsb saja
    (path bertitik, operator top-level selain $and/$or/$nor, nama field tidak aman untuk path JSON)."""
    out = set()
    if not isinstance(flt, dict):
        return None
    for k, v in flt.items():
        if k in _LOGICAL:
            if not isinstance(v, (list, tuple)):
                return None
            for c in v:
                sub = _filter_fields(c)
                if sub is None:
                    return None
                out |= sub
        elif k.startswith("$") or not _FIELD.match(k):
            return None
        else:
            out.add(k)
    return out


def _pushdown_superset(col: str, cond: dict) -> Tuple[List[str], list]:
    """P7 — pre-filter SQL tambahan yang SELALU superset dari semantik Mongo (baris tetap diverifikasi ulang `_match`).

    - `{"$exists": False}` -> `col IS NULL` (field hilang => JSON_VALUE NULL). `$exists: True` TIDAK di-pushdown
      (field ber-nilai null/array/objek juga NULL di kolom generated).
    - `$gt/$gte/$lt/$lte` dengan argumen string -> perbandingan kode-titik (`utf8mb4_nopad_bin`, identik urutan str Python,
      tanpa PAD SPACE) + `col IS NULL` (array/objek/hilang tetap diverifikasi Python) + nilai >= 191 karakter
      (kolom generated dipotong LEFT 191). Argumen non-string (angka/bool/None/dict) tidak di-pushdown.
    """
    where, params = [], []
    if cond.get("$exists") is False:
        where.append(f"{col} IS NULL")
    for op, sym in _RANGE_SQL.items():
        arg = cond.get(op)
        if type(arg) is str:
            where.append(f"({col} IS NULL OR CHAR_LENGTH({col}) >= 191 OR {col} COLLATE utf8mb4_nopad_bin {sym} %s)")
            params.append(arg)
    return where, params


def _is_duplicate_pk(exc: Exception) -> bool:
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == 1062


# Collections whose logical identity is encoded in a DETERMINISTIC primary key. For these we
# MUST NOT fall back to a random UUID pk on a duplicate-key error (that would create a second
# logical row for the same key). Instead the duplicate is re-raised so the caller re-reads the
# canonical row and continues through its optimistic/versioned flow. This guarantees exactly one
# logical inventory/valuation pool per tenant+item+warehouse(+base_uom).
STRICT_PK_COLLECTIONS = {"item_warehouse"}


class MariaCollection:
    def __init__(self, db: "MariaDatabase", name: str):
        self.database = db; self.name = name; self.full_name = name

    def __repr__(self): return f"MariaCollection({self.name})"

    # ---- helper SQL ----
    async def _columns(self) -> set:
        return await self.database._ensure_table(self.name)

    def _pushdown(self, flt: dict, cols: set) -> Tuple[str, list]:
        where = []; params: list = []
        for k, v in (flt or {}).items():
            if k.startswith("$"):
                if k == "$and":
                    for c in v:
                        w, p = self._pushdown(c, cols)
                        if w: where.append(w); params.extend(p)
                continue
            if "." in k or k not in cols or k == "pk":
                continue
            col = _q(k)
            # Boolean tidak di-pushdown: JSON_VALUE MariaDB mengembalikan '1'/'0' untuk true/false,
            # sedangkan semantik Mongo membedakan bool dari angka. Filter bool ditangani di Python.
            if isinstance(v, bool):
                continue
            if isinstance(v, _SCALAR) and not isinstance(v, dict):
                if v is None:
                    where.append(f"{col} IS NULL")
                else:
                    where.append(f"{col} = %s"); params.append(_sql_value(v))
            elif isinstance(v, dict):
                if "$in" in v and isinstance(v["$in"], (list, tuple)) and v["$in"] and all(isinstance(x, _SCALAR) and not isinstance(x, (dict, bool)) for x in v["$in"]):
                    vals = [x for x in v["$in"] if x is not None]
                    parts = []
                    if vals:
                        parts.append(f"{col} IN ({', '.join(['%s'] * len(vals))})"); params.extend(_sql_value(x) for x in vals)
                    if None in v["$in"]: parts.append(f"{col} IS NULL")
                    where.append("(" + " OR ".join(parts) + ")")
                elif "$eq" in v and isinstance(v["$eq"], _SCALAR) and v["$eq"] is not None and not isinstance(v["$eq"], (dict, bool)):
                    where.append(f"{col} = %s"); params.append(_sql_value(v["$eq"]))
                if k not in _PHYSICAL_COLS:
                    w, p = _pushdown_superset(col, v)
                    where.extend(w); params.extend(p)
        return (" AND ".join(where), params)

    async def _select(self, flt: Optional[dict], *, for_update: bool = False, conn=None) -> List[dict]:
        rows = await self._select_rows(flt, for_update=for_update, conn=conn)
        return [doc for _, doc in rows]

    async def _select_fields(self, flt: Optional[dict], fields, *, conn=None) -> List[Tuple[str, dict]]:
        """P7 — seperti `_select_rows`, tetapi hanya memuat field top-level `fields` (JSON_EXTRACT) sebagai dokumen-mini.

        `_match` hanya membaca field yang disebut filter, sehingga hasil penyaringan identik dengan dokumen penuh.
        Field hilang -> tidak ada di dokumen-mini (=_MISSING); null -> None. Urutan dasar sama (created_at, pk)."""
        cols = await self._columns()
        where, params = self._pushdown(flt or {}, cols)
        fl = sorted(fields)
        sel = "".join(f", JSON_EXTRACT(doc, '$.\"{f}\"')" for f in fl)
        rows = await self._fetch_base_order(sel, where, params, conn=conn)
        cflt = _compile_filter(flt) if flt else flt
        out = []
        for row in rows:
            mini = {f: json.loads(v) for f, v in zip(fl, row[1:]) if v is not None}
            if _match(mini, cflt):
                out.append((row[0], mini))
        return out

    async def _select_topk(self, flt: Optional[dict], spec, k: int, hint: Optional[dict] = None) -> Optional[List[dict]]:
        """P7 — `find(flt).sort(spec)[:k]` dua tahap dalam SATU snapshot konsisten (REPEATABLE READ, satu koneksi):
        (1) field filter+sort saja (JSON_EXTRACT) -> `_match` + `_apply_sort` (stabil, urutan dasar sama) -> pk top-k;
        (2) dokumen penuh hanya untuk pk tsb. Hasil identik dengan jalur penuh. None = tidak berlaku (pakai jalur penuh)."""
        fields = _filter_fields(flt or {})
        if fields is None or not all(_FIELD.match(f) for f, _ in spec):
            return None
        fields |= {f for f, _ in spec}
        cols = await self._columns()
        where, params = self._pushdown(flt or {}, cols)
        fl = sorted(fields)
        sel = "".join(f", JSON_EXTRACT(doc, '$.\"{f}\"')" for f in fl)
        sql1 = f"SELECT pk{sel} FROM {_q(self.name)}" + (f" WHERE {where}" if where else "") + " ORDER BY created_at ASC, pk ASC"
        sql1u = f"SELECT pk, {_CREATED_TXT}{sel} FROM {_q(self.name)}" + (f" WHERE {where}" if where else "")
        seen = _SHAPE_ROWS.get(sql1)
        if _shape_is_small(sql1) or (seen is not None and seen <= _TOPK_GAIN * k):
            # Kandidat terbukti sedikit (mis. find_one({"po_id": x}) berulang) ATAU tidak jauh lebih banyak dari k
            # (mis. find({"id": {"$in": ids}}).to_list(len(ids))): top-k tidak memangkas dokumen yang dimuat, sehingga jalur
            # penuh 1 query lebih murah daripada snapshot 2 tahap (5 statement + thread hop). Hasil identik -> None.
            if hint is not None:
                hint["shape"] = sql1
            return None
        py_order = _py_order_wanted(where)
        cflt = _compile_filter(flt) if flt else flt
        table = _q(self.name)
        db = self.database
        await db._get_pool()

        def run():
            with db._sync_lock:
                c = db._sync_conns.pop() if db._sync_conns else None
            if c is None:
                c = db._sync_connect()
            ok = False
            try:
                c.ping(reconnect=True)
                with c.cursor() as cur:
                    cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    base = None
                    if py_order:  # urutan dasar di Python (identik; lihat _py_order), fallback ORDER BY SQL
                        cur.execute(sql1u, params or None)
                        base = _py_order(list(cur.fetchall()))
                        if base is not None:
                            base = [(r[0],) + tuple(r[2:]) for r in base]
                    if base is None:
                        cur.execute(sql1, params or None)
                        base = cur.fetchall()
                    _shape_note(sql1, len(base))
                    minis = []
                    for row in base:
                        mini = {f: json.loads(v) for f, v in zip(fl, row[1:]) if v is not None}
                        if _match(mini, cflt):
                            minis.append((row[0], mini))
                    ranked = [pk for pk, _ in _apply_sort_rows(minis, spec)[:k]]
                    docs = {}
                    for i in range(0, len(ranked), 1000):
                        part = ranked[i:i + 1000]
                        cur.execute(f"SELECT pk, doc FROM {table} WHERE pk IN ({', '.join(['%s'] * len(part))})", part)
                        for pk, raw in cur.fetchall():
                            docs[pk] = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
                    cur.execute("COMMIT")
                ok = True
                return [docs[pk] for pk in ranked if pk in docs]
            finally:
                with db._sync_lock:
                    if ok and len(db._sync_conns) < db._pool_size:
                        db._sync_conns.append(c); c = None
                if c is not None:
                    c.close()
        if os.environ.get("MARIADB_SYNC_READS", "1") == "0":
            return None
        t0 = time.perf_counter()
        try:
            if db._sync_exec is None:
                db._sync_exec = ThreadPoolExecutor(max_workers=db._pool_size, thread_name_prefix="mariadb-read")
            return await asyncio.get_running_loop().run_in_executor(db._sync_exec, run)
        finally:
            _track(t0, sql1)

    async def _fetch_base_order(self, sel: str, where: str, params, conn=None):
        """Baris `SELECT pk{sel} ... WHERE` dalam urutan dasar (created_at ASC, pk ASC) — identik dengan ORDER BY SQL.
        Di luar transaksi (P7): diambil tanpa ORDER BY lalu diurutkan di Python (`_py_order`); fallback ORDER BY SQL."""
        base = f" FROM {_q(self.name)}" + (f" WHERE {where}" if where else "")
        sorted_sql = f"SELECT pk{sel}{base} ORDER BY created_at ASC, pk ASC"
        if conn is not None or not _py_order_wanted(where) or (sel != ", doc" and os.environ.get("MARIADB_PY_ORDER_NARROW", "0") != "1"):
            # Kolom sempit (JSON_EXTRACT field tertentu): filesort MariaDB atas baris kecil lebih murah daripada mengurutkan
            # di Python; urutan Python hanya untuk baris lebar (dokumen penuh). Hasil identik di kedua jalur.
            return await self.database._fetchall_bulk(sorted_sql, params, conn=conn)
        rows = _py_order(list(await self.database._fetchall_bulk(f"SELECT pk, {_CREATED_TXT}{sel}{base}", params)))
        if rows is None:
            return await self.database._fetchall_bulk(sorted_sql, params)
        return [(r[0],) + tuple(r[2:]) for r in rows]

    async def _select_rows(self, flt: Optional[dict], *, for_update: bool = False, conn=None) -> List[Tuple[str, dict]]:
        cols = await self._columns()
        where, params = self._pushdown(flt or {}, cols)
        if for_update:
            sql = f"SELECT pk, doc FROM {_q(self.name)}" + (f" WHERE {where}" if where else "") + " ORDER BY created_at ASC, pk ASC FOR UPDATE"
            rows = await self.database._fetchall(sql, params, conn=conn)
        else:
            rows = await self._fetch_base_order(", doc", where, params, conn=conn)
        out = []
        cflt = _compile_filter(flt) if flt else flt  # sekali per query: `$in` O(1) per baris (bukan O(panjang daftar))
        for pk, raw in rows:
            doc = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
            if _match(doc, cflt):   # verifikasi ulang dengan semantik Mongo (aman bila pushdown parsial)
                out.append((pk, doc))
        return out

    # ---- API Motor ----
    def find(self, filter: Optional[dict] = None, projection=None, *args, **kwargs) -> MariaCursor:
        cur = MariaCursor(self, filter, projection)
        if kwargs.get("sort"): cur.sort(kwargs["sort"])
        if kwargs.get("skip"): cur.skip(kwargs["skip"])
        if kwargs.get("limit"): cur.limit(kwargs["limit"])
        return cur

    async def find_one(self, filter: Optional[dict] = None, projection=None, *args, **kwargs) -> Optional[dict]:
        if isinstance(filter, str):  # find_one("id-value") → by pk/id
            filter = {"id": filter}
        cache = REQ_CACHE.get() if self.name in _REQ_CACHED else None
        if cache is not None and isinstance(filter, dict) and set(filter) == {"id"} and isinstance(filter["id"], str) and not kwargs:
            key = ("find_one", self.name, filter["id"])  # identitas user/tenant dibaca beberapa middleware per request GET
            if key not in cache:
                hit = await MariaCursor(self, filter, None).limit(1).to_list(1)
                cache[key] = hit[0] if hit else None
            return _project(deepcopy(cache[key]), projection) if cache[key] else None
        cur = MariaCursor(self, filter, projection).limit(1 if not kwargs.get("sort") else 0)
        if kwargs.get("sort"): cur.sort(kwargs["sort"])
        docs = await cur.to_list(1)
        return docs[0] if docs else None

    async def insert_one(self, document: dict, *args, **kwargs) -> InsertOneResult:
        await self._columns()
        doc = dict(document); doc.pop("_id", None)
        pk = _pick_pk(doc)
        created = _parse_dt(doc.get("created_at")) or _parse_dt(doc.get("at")) or datetime.utcnow()
        try:
            await self.database._execute(
                f"INSERT INTO {_q(self.name)} (pk, doc, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                [pk, _json_dumps(doc), created, datetime.utcnow()])
        except Exception as exc:  # noqa: BLE001
            # Mongo mengizinkan beberapa dokumen dengan `id` sama (mis. settings per tenant);
            # bila pk deterministik bentrok, pakai UUID agar semantik Mongo tetap terjaga.
            # KECUALI koleksi strict-pk (mis. item_warehouse): duplikat di-raise agar caller
            # membaca ulang pool kanonik, bukan membuat pool kedua.
            if not _is_duplicate_pk(exc) or self.name in STRICT_PK_COLLECTIONS: raise
            pk = str(uuid.uuid4())
            await self.database._execute(
                f"INSERT INTO {_q(self.name)} (pk, doc, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                [pk, _json_dumps(doc), created, datetime.utcnow()])
        return InsertOneResult(pk)

    async def insert_many(self, documents: Iterable[dict], *args, **kwargs) -> InsertManyResult:
        ids = []
        for d in documents:
            ids.append((await self.insert_one(d)).inserted_id)
        return InsertManyResult(ids)

    async def _update(self, flt: dict, update: dict, *, upsert: bool, many: bool, return_doc=None, projection=None, sort=None):
        db = self.database
        await self._columns()
        async with db._transaction() as conn:
            rows = await self._select_rows(flt, for_update=True, conn=conn)
            if sort:
                spec = _normalize_sort(sort)
                rows.sort(key=lambda r: [_sort_key(_get_path(r[1], f)) for f, _ in spec])
                for f, direction in reversed(spec):
                    rows.sort(key=lambda r: _sort_key(_get_path(r[1], f)), reverse=direction < 0)
            if not rows:
                if upsert:
                    seed = _upsert_seed(flt)
                    new = _apply_update(seed, update, is_insert=True)
                    new.pop("_id", None)
                    pk = _pick_pk(new)
                    created = _parse_dt(new.get("created_at")) or datetime.utcnow()
                    try:
                        await db._execute(f"INSERT INTO {_q(self.name)} (pk, doc, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                                          [pk, _json_dumps(new), created, datetime.utcnow()], conn=conn)
                    except Exception as exc:  # noqa: BLE001
                        if not _is_duplicate_pk(exc) or self.name in STRICT_PK_COLLECTIONS: raise
                        pk = str(uuid.uuid4())
                        await db._execute(f"INSERT INTO {_q(self.name)} (pk, doc, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                                          [pk, _json_dumps(new), created, datetime.utcnow()], conn=conn)
                    if return_doc is not None:
                        return (None if return_doc == ReturnDocument.BEFORE else _project(new, projection)), UpdateResult(0, 0, pk)
                    return None, UpdateResult(0, 0, pk)
                return None, UpdateResult(0, 0)
            targets = rows if many else rows[:1]
            modified = 0; first_before = None; first_after = None
            pending = []
            now = datetime.utcnow()
            for i, (pk, doc) in enumerate(targets):
                before = deepcopy(doc)
                after = _apply_update(deepcopy(doc), update)
                after.pop("_id", None)
                if i == 0: first_before, first_after = before, after
                if after != before:
                    pending.append([_json_dumps(after), now, pk])
                    modified += 1
            if pending:
                # satu baris → execute biasa; banyak baris (update_many) → batch agar cepat walau latensi tinggi
                if len(pending) == 1:
                    await db._execute(f"UPDATE {_q(self.name)} SET doc = %s, updated_at = %s WHERE pk = %s", pending[0], conn=conn)
                else:
                    await db._executemany(f"UPDATE {_q(self.name)} SET doc = %s, updated_at = %s WHERE pk = %s", pending, conn=conn)
            result = UpdateResult(len(targets), modified)
            if return_doc is not None:
                chosen = first_before if return_doc == ReturnDocument.BEFORE else first_after
                return _project(chosen, projection), result
            return None, result

    async def update_one(self, filter: dict, update: dict, upsert: bool = False, *args, **kwargs) -> UpdateResult:
        _, res = await self._update(filter, update, upsert=upsert, many=False)
        return res

    async def update_many(self, filter: dict, update: dict, upsert: bool = False, *args, **kwargs) -> UpdateResult:
        _, res = await self._update(filter, update, upsert=upsert, many=True)
        return res

    async def replace_one(self, filter: dict, replacement: dict, upsert: bool = False, *args, **kwargs) -> UpdateResult:
        _, res = await self._update(filter, {k: v for k, v in replacement.items() if k != "_id"}, upsert=upsert, many=False)
        return res

    async def find_one_and_update(self, filter: dict, update: dict, projection=None, sort=None, upsert: bool = False,
                                  return_document=ReturnDocument.BEFORE, *args, **kwargs) -> Optional[dict]:
        doc, _ = await self._update(filter, update, upsert=upsert, many=False, return_doc=return_document, projection=projection, sort=sort)
        return doc

    async def find_one_and_delete(self, filter: dict, projection=None, sort=None, *args, **kwargs) -> Optional[dict]:
        db = self.database
        await self._columns()
        async with db._transaction() as conn:
            rows = await self._select_rows(filter, for_update=True, conn=conn)
            if sort: rows = [(pk, d) for pk, d in zip([r[0] for r in rows], _apply_sort([r[1] for r in rows], _normalize_sort(sort)))]
            if not rows: return None
            pk, doc = rows[0]
            await db._execute(f"DELETE FROM {_q(self.name)} WHERE pk = %s", [pk], conn=conn)
            return _project(doc, projection)

    async def delete_one(self, filter: dict, *args, **kwargs) -> DeleteResult:
        return await self._delete(filter, many=False)

    async def delete_many(self, filter: dict, *args, **kwargs) -> DeleteResult:
        return await self._delete(filter, many=True)

    async def _delete(self, flt: dict, *, many: bool) -> DeleteResult:
        db = self.database
        await self._columns()
        async with db._transaction() as conn:
            rows = await self._select_rows(flt, for_update=True, conn=conn)
            targets = rows if many else rows[:1]
            pks = [pk for pk, _ in targets]
            # Batch per 500 pk (baris sudah terkunci FOR UPDATE di transaksi yang sama) -> hasil identik dengan
            # DELETE per baris, tetapi round-trip jauh lebih sedikit untuk delete_many besar.
            for i in range(0, len(pks), 500):
                part = pks[i:i + 500]
                await db._execute(f"DELETE FROM {_q(self.name)} WHERE pk IN ({', '.join(['%s'] * len(part))})", part, conn=conn)
            return DeleteResult(len(targets))

    async def count_documents(self, filter: Optional[dict] = None, *args, **kwargs) -> int:
        flt = filter or {}
        cols = await self._columns()
        where, params = self._pushdown(flt, cols)
        # pushdown penuh hanya jika seluruh filter adalah kesetaraan skalar top-level yang tercakup kolom
        full = all((not k.startswith("$")) and "." not in k and k in cols and (
            (isinstance(v, _SCALAR) and not isinstance(v, dict)) or
            (isinstance(v, dict) and set(v) <= {"$in", "$eq"} and all(isinstance(x, _SCALAR) for x in (v.get("$in") or [v.get("$eq")])))
        ) for k, v in flt.items())
        if full:
            sql = f"SELECT COUNT(*) FROM {_q(self.name)}" + (f" WHERE {where}" if where else "")
            rows = await self.database._fetchall(sql, params)
            return int(rows[0][0])
        fields = _filter_fields(flt)
        if fields is not None:  # P7: hitung dari field filter saja (tanpa memuat & mem-parse dokumen penuh); semantik _match sama
            return len(await self._select_fields(flt, fields))
        return len(await self._select(flt))

    async def estimated_document_count(self, *args, **kwargs) -> int:
        return await self.count_documents({})

    async def distinct(self, key: str, filter: Optional[dict] = None, *args, **kwargs) -> list:
        return _distinct(await self._select(filter), key)

    def aggregate(self, pipeline: List[dict], *args, **kwargs):
        return _AggregateCursor(self, pipeline)

    async def create_index(self, keys, **kwargs) -> str:
        # Indeks fisik dikelola oleh schema.sql (kolom generated). No-op agar kompatibel.
        if isinstance(keys, str): return f"{keys}_1"
        return "_".join(f"{k}_{d}" for k, d in keys)

    async def create_indexes(self, indexes): return [str(i) for i in indexes]
    async def drop_index(self, *a, **k): return None
    async def index_information(self): return {}
    async def drop(self):
        await self.database._execute(f"DELETE FROM {_q(self.name)}", [])

    async def bulk_write(self, requests, ordered=True):
        for req in requests:
            kind = type(req).__name__
            if kind == "InsertOne": await self.insert_one(req._doc)
            elif kind == "UpdateOne": await self.update_one(req._filter, req._doc, upsert=req._upsert)
            elif kind == "UpdateMany": await self.update_many(req._filter, req._doc, upsert=req._upsert)
            elif kind == "DeleteOne": await self.delete_one(req._filter)
            elif kind == "DeleteMany": await self.delete_many(req._filter)
            elif kind == "ReplaceOne": await self.replace_one(req._filter, req._doc, upsert=req._upsert)
            else: raise NotImplementedError(kind)
        return None


class _AggregateCursor:
    def __init__(self, coll: MariaCollection, pipeline: List[dict]):
        self._coll = coll; self._pipeline = pipeline; self._rows: Optional[List[dict]] = None; self._idx = 0
    async def _run(self):
        if self._rows is None:
            first_match = self._pipeline[0]["$match"] if self._pipeline and "$match" in self._pipeline[0] else None
            docs = await self._coll._select(first_match)
            self._rows = _aggregate(docs, self._pipeline[1:] if first_match is not None else self._pipeline)
        return self._rows
    async def to_list(self, length=None):
        rows = await self._run(); return rows[:length] if length is not None else list(rows)
    def __aiter__(self): return self
    async def __anext__(self):
        rows = await self._run()
        if self._idx >= len(rows): raise StopAsyncIteration
        r = rows[self._idx]; self._idx += 1; return r


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
class _Tx:
    def __init__(self, db: "MariaDatabase"): self.db = db; self.conn = None
    async def __aenter__(self):
        pool = await self.db._get_pool()
        self.conn = await pool.acquire()
        await self.conn.begin()
        _reads_tx(+1)  # P7: selama transaksi terbuka memo baca request tidak dipakai/diisi
        return self.conn
    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type: await self.conn.rollback()
            else: await self.conn.commit()
        finally:
            _reads_tx(-1)
            (await self.db._get_pool()).release(self.conn)


class MariaDatabase:
    """Objek pengganti `AsyncIOMotorDatabase`: `db.items`, `db["items"]`, getattr(db, name)."""

    def __init__(self, dsn: str, *, schema_path: Optional[str] = None, auto_schema: bool = True,
                 pool_size: int = 10, name: str = "default"):
        self._dsn = dsn; self._pool: Optional[aiomysql.Pool] = None; self._pool_lock = asyncio.Lock()
        self._collections: Dict[str, MariaCollection] = {}
        self._tables: Dict[str, set] = {}
        self._schema_path = schema_path; self._auto_schema = auto_schema; self._pool_size = pool_size
        self._schema_applied = False
        self.name = name
        self._sync_conns: List[Any] = []; self._sync_lock = threading.Lock(); self._sync_exec = None

    def __getattr__(self, name: str) -> MariaCollection:
        if name.startswith("_"): raise AttributeError(name)
        return self[name]

    def __getitem__(self, name: str) -> MariaCollection:
        if name not in self._collections:
            self._collections[name] = MariaCollection(self, name)
        return self._collections[name]

    def get_collection(self, name: str) -> MariaCollection: return self[name]

    async def list_collection_names(self) -> List[str]:
        # Hanya tabel berformat koleksi (memiliki kolom pk + doc); tabel internal seperti
        # `_schema_meta` atau tabel bantu lain tidak dianggap koleksi Mongo.
        rows = await self._fetchall(
            "SELECT t.TABLE_NAME FROM information_schema.TABLES t"
            " WHERE t.TABLE_SCHEMA = DATABASE() AND t.TABLE_TYPE = 'BASE TABLE'"
            "   AND t.TABLE_NAME NOT LIKE '\\_%%'"
            "   AND EXISTS (SELECT 1 FROM information_schema.COLUMNS c WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME AND c.COLUMN_NAME = 'pk')"
            "   AND EXISTS (SELECT 1 FROM information_schema.COLUMNS c WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME AND c.COLUMN_NAME = 'doc')", [])
        return [r[0] for r in rows]

    async def command(self, cmd, *a, **k):
        if cmd == "ping" or (isinstance(cmd, dict) and "ping" in cmd):
            await self._fetchall("SELECT 1", []); return {"ok": 1}
        return {"ok": 1}

    # ---- koneksi ----
    async def _get_pool(self) -> aiomysql.Pool:
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    u = urlparse(self._dsn)
                    self._pool = await aiomysql.create_pool(
                        host=u.hostname, port=u.port or 3306,
                        user=unquote(u.username or ""), password=unquote(u.password or ""),
                        db=unquote(u.path.lstrip("/")), charset="utf8mb4", autocommit=True,
                        minsize=1, maxsize=self._pool_size, pool_recycle=3600)
                    if self._auto_schema and not self._schema_applied:
                        await self._apply_schema()
        return self._pool

    def _transaction(self) -> _Tx: return _Tx(self)

    # ---- P7: baca massal non-transaksi lewat PyMySQL di thread terpisah --------------------------------------------------
    # aiomysql men-decode baris di event loop (±40 µs/baris dokumen besar) dan memblok request lain; PyMySQL (konverter tipe
    # yang SAMA — aiomysql dibangun di atas PyMySQL) membaca ±10x lebih cepat dan tidak memblok event loop. Hanya untuk SELECT
    # di luar transaksi (conn=None, autocommit -> data ter-commit sama). Transaksi/FOR UPDATE tetap koneksi aiomysql.
    def _sync_connect(self):
        u = urlparse(self._dsn.replace("mariadb://", "mysql://"))
        return pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                               database=unquote(u.path.lstrip("/")), charset="utf8mb4", autocommit=True)

    def _sync_fetchall(self, sql: str, params: Sequence):
        with self._sync_lock:
            c = self._sync_conns.pop() if self._sync_conns else None
        if c is None:
            c = self._sync_connect()
        try:
            try:
                with c.cursor() as cur:
                    cur.execute(sql, params or None); rows = cur.fetchall()
            except (pymysql.err.OperationalError, pymysql.err.InterfaceError):
                c.close(); c = self._sync_connect()
                with c.cursor() as cur:
                    cur.execute(sql, params or None); rows = cur.fetchall()
        except BaseException:
            try: c.close()
            except Exception: pass  # noqa: E701
            raise
        with self._sync_lock:
            if len(self._sync_conns) < self._pool_size: self._sync_conns.append(c); c = None
        if c is not None: c.close()
        return rows

    async def _fetchall_bulk(self, sql: str, params: Sequence, conn=None):
        if conn is not None or os.environ.get("MARIADB_SYNC_READS", "1") == "0":
            return await self._fetchall(sql, params, conn=conn)
        small = _shape_is_small(sql)
        memo = REQ_READS.get()
        if memo is not None and (not memo["open"] or memo["tx"]):
            memo = None
        key = None
        if memo is not None:
            try:
                key = (sql, tuple(params or ()))
                hash(key)
            except TypeError:
                key = None
            if key is not None and key in memo["data"]:
                _track(time.perf_counter(), sql)
                return list(memo["data"][key])
            fl = memo["inflight"].get(key) if key is not None else None
            if fl is not None and fl[0] == memo["gen"]:  # query identik sedang berjalan & belum ada tulis sejak dimulai
                rows = await asyncio.shield(fl[1])
                _track(time.perf_counter(), sql)
                return list(rows)
        gen = memo["gen"] if memo is not None else 0
        fut = None
        if key is not None:
            fut = asyncio.get_running_loop().create_future()
            memo["inflight"][key] = (gen, fut)
        if not small:
            await self._get_pool()  # skema/pool siap (urutan inisialisasi sama; jalur kecil menyiapkan pool sendiri)
        t0 = time.perf_counter()
        try:
            if small:
                # Bentuk SQL yang terbukti kecil (pola N+1 / lookup titik): aiomysql langsung di event loop. Thread hop
                # pymysql (±0,3 ms/query) justru mendominasi untuk ribuan query kecil berurutan. SQL & konverter identik.
                rows = await self._small_fetchall(sql, params)
            else:
                if self._sync_exec is None:
                    self._sync_exec = ThreadPoolExecutor(max_workers=self._pool_size, thread_name_prefix="mariadb-read")
                rows = await asyncio.get_running_loop().run_in_executor(self._sync_exec, self._sync_fetchall, sql, list(params or []))
            _shape_note(sql, len(rows))
        except BaseException as e:
            if fut is not None:
                if memo["inflight"].get(key, (None, None))[1] is fut:
                    memo["inflight"].pop(key, None)
                fut.set_exception(e if isinstance(e, Exception) else RuntimeError("query dibatalkan"))
                fut.exception()  # tandai sudah diambil (tanpa warning bila tak ada penunggu)
            raise
        finally:
            _track(t0, sql)
        rows = tuple(rows)
        if fut is not None:
            if memo["inflight"].get(key, (None, None))[1] is fut:
                memo["inflight"].pop(key, None)
            fut.set_result(rows)
        if key is not None and memo["open"] and not memo["tx"] and memo["gen"] == gen and memo["rows"] + len(rows) <= _READ_MEMO_MAX_ROWS:
            nb = _rows_bytes(rows)
            if _READ_MEMO_USED[0] + nb <= _READ_MEMO_BUDGET:
                memo["data"][key] = rows; memo["rows"] += len(rows); memo["bytes"] += nb; _READ_MEMO_USED[0] += nb
        return list(rows)

    async def _small_fetchall(self, sql: str, params: Sequence):
        """SELECT kecil di luar transaksi lewat pool aiomysql (tanpa thread hop); dipakai _fetchall_bulk untuk bentuk SQL kecil."""
        pool = await self._get_pool()
        async with pool.acquire() as c:
            async with c.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()

    async def _fetchall(self, sql: str, params: Sequence, conn=None):
        t0 = time.perf_counter()
        try:
            if conn is not None:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params); return await cur.fetchall()
            pool = await self._get_pool()
            async with pool.acquire() as c:
                async with c.cursor() as cur:
                    await cur.execute(sql, params); return await cur.fetchall()
        finally:
            _track(t0, sql)

    async def _execute(self, sql: str, params: Sequence, conn=None) -> int:
        _reads_invalidate()  # P7: tulis -> memo baca request tidak dipakai lagi
        t0 = time.perf_counter()
        try:
            if conn is not None:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params); return cur.rowcount
            pool = await self._get_pool()
            async with pool.acquire() as c:
                async with c.cursor() as cur:
                    await cur.execute(sql, params); return cur.rowcount
        finally:
            _reads_invalidate()
            _track(t0, sql)

    async def _executemany(self, sql: str, seq_params: Sequence[Sequence], conn=None, chunk: int = 200) -> int:
        """Eksekusi batch (executemany per chunk) — memangkas round-trip untuk update_many/backfill."""
        _reads_invalidate()
        total = 0
        rows = list(seq_params)
        if not rows: return 0
        async def run(cur):
            nonlocal total
            for i in range(0, len(rows), chunk):
                await cur.executemany(sql, rows[i:i + chunk]); total += cur.rowcount or 0
        if conn is not None:
            async with conn.cursor() as cur: await run(cur)
            _reads_invalidate()
            return total
        pool = await self._get_pool()
        async with pool.acquire() as c:
            async with c.cursor() as cur: await run(cur)
        _reads_invalidate()
        return total

    async def ping(self):
        await self._fetchall("SELECT 1", []); return True

    async def close(self):
        if self._pool: self._pool.close(); await self._pool.wait_closed(); self._pool = None

    # ---- skema ----
    async def _apply_schema(self):
        self._schema_applied = True
        path = self._schema_path or str(Path(__file__).parent / "database" / "schema.sql")
        if not Path(path).exists():
            logger.warning("schema.sql tidak ditemukan (%s); tabel dibuat otomatis saat dipakai.", path); return
        sql = Path(path).read_text(encoding="utf-8")
        import hashlib
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        pool = self._pool
        async with pool.acquire() as c:
            async with c.cursor() as cur:
                await cur.execute("CREATE TABLE IF NOT EXISTS `_schema_meta` (`key` VARCHAR(64) PRIMARY KEY, `value` VARCHAR(255) NOT NULL, applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) ENGINE=InnoDB")
                await cur.execute("SELECT `value` FROM `_schema_meta` WHERE `key` = 'schema_sha256'")
                row = await cur.fetchone()
        if row and row[0] == digest and not os.environ.get("DB_FORCE_SCHEMA"):
            logger.info("Skema MariaDB sudah sesuai (sha256 %s…), dilewati.", digest[:12]); return
        statements = [s.strip() for s in re.split(r";\s*(?:\r?\n|$)", sql)]
        statements = ["\n".join(l for l in s.split("\n") if not l.strip().startswith("--")).strip() for s in statements]
        statements = [s for s in statements if s]
        pool = self._pool
        async with pool.acquire() as c:
            async with c.cursor() as cur:
                for st in statements:
                    try:
                        await cur.execute(st)
                    except Exception as exc:  # noqa: BLE001
                        # kolom generated yang sudah ada → abaikan (idempoten)
                        if "Duplicate column" in str(exc) or "already exists" in str(exc) or "Duplicate key name" in str(exc):
                            continue
                        logger.error("Gagal menjalankan statement skema: %s\n%s", exc, st[:200]); raise
                await cur.execute("REPLACE INTO `_schema_meta` (`key`, `value`) VALUES ('schema_sha256', %s)", [digest])
        logger.info("Skema MariaDB diterapkan (%d statement).", len(statements))

    async def _ensure_table(self, name: str) -> set:
        if name in self._tables: return self._tables[name]
        await self._get_pool()
        _q(name)
        cols = await self._table_columns(name)
        if cols is None:
            await self._execute(
                f"CREATE TABLE IF NOT EXISTS {_q(name)} ("
                " pk VARCHAR(64) NOT NULL PRIMARY KEY,"
                " doc LONGTEXT NOT NULL CHECK (JSON_VALID(doc)),"
                " id VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED,"
                " created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
                " updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),"
                " KEY idx_id (id), KEY idx_created (created_at, pk)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci", [])
            cols = await self._table_columns(name) or set()
            logger.info("Tabel `%s` dibuat otomatis (koleksi baru).", name)
        self._tables[name] = cols
        return cols

    async def _table_columns(self, name: str) -> Optional[set]:
        rows = await self._fetchall(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", [name])
        if not rows: return None
        return {r[0] for r in rows} - {"pk", "doc", "created_at", "updated_at"}

    def invalidate_schema_cache(self): self._tables.clear()

    async def ensure_pool_unique_index(self, name: str, columns: Sequence[str], index_name: str) -> dict:
        """Idempotently ensure a composite UNIQUE index on generated columns for `name`.

        Safe migration per spec: ensures the generated columns exist, then PRE-SCANS for existing
        duplicate logical keys. If duplicates exist it SKIPS index creation and returns the
        conflicting keys (no silent merge/delete/auto-repair). Otherwise it creates the index.
        """
        await self._ensure_table(name)
        # ensure generated columns exist (idempotent)
        for c in columns:
            try:
                await self._execute(
                    f"ALTER TABLE {_q(name)} ADD COLUMN IF NOT EXISTS {_q(c)} "
                    f"VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.{c}'), 191)) STORED", [])
            except Exception as exc:  # noqa: BLE001
                if "Duplicate column" not in str(exc) and "exists" not in str(exc):
                    raise
        self.invalidate_schema_cache()
        # already present?
        rows = await self._fetchall(
            "SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME=%s AND INDEX_NAME=%s LIMIT 1", [name, index_name])
        if rows:
            return {"created": False, "exists": True}
        col_list = ", ".join(_q(c) for c in columns)
        dups = await self._fetchall(
            f"SELECT {col_list}, COUNT(*) c FROM {_q(name)} GROUP BY {col_list} HAVING c > 1 LIMIT 50", [])
        if dups:
            return {"created": False, "duplicates": [list(r) for r in dups]}
        await self._execute(f"ALTER TABLE {_q(name)} ADD UNIQUE INDEX {_q(index_name)} ({col_list})", [])
        self.invalidate_schema_cache()
        return {"created": True}


class MariaClient:
    """Pengganti AsyncIOMotorClient: client[db_name] → MariaDatabase (nama diabaikan, DB dari DSN)."""
    def __init__(self, dsn: str, **kwargs):
        self._db = MariaDatabase(dsn, **kwargs)
    def __getitem__(self, name: str) -> MariaDatabase: self._db.name = name; return self._db
    def get_database(self, name: str = None) -> MariaDatabase: return self._db
    def close(self): pass
    @property
    def admin(self): return self._db


def database_from_env() -> MariaDatabase:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL wajib diisi (mysql://user:pass@host:3306/db).")
    auto = os.environ.get("DB_AUTO_SCHEMA", "true").strip().lower() not in ("0", "false", "no")
    return MariaDatabase(dsn, auto_schema=auto, pool_size=int(os.environ.get("DATABASE_POOL_SIZE", "10")),
                         name=os.environ.get("DB_NAME", "default"))


class DbStatsMiddleware:
    """ASGI: tambahkan header Server-Timing (jumlah & durasi query DB) per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        st = [0, 0.0, 0.0]
        tok = DB_STATS.set(st)
        ctok = REQ_CACHE.set({} if scope.get("method") == "GET" else None)
        memo = new_read_memo() if scope.get("method") == "GET" and os.environ.get("DB_READ_MEMO", "1") != "0" else None
        rtok = REQ_READS.set(memo)

        async def _send(msg):
            if msg["type"] == "http.response.start":
                val = f'db;dur={st[1] * 1000:.0f};desc="{st[0]} q max {st[2] * 1000:.0f}ms"'
                msg = {**msg, "headers": list(msg.get("headers") or []) + [(b"server-timing", val.encode())]}
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        finally:
            DB_STATS.reset(tok)
            REQ_CACHE.reset(ctok)
            if memo is not None:
                close_read_memo(memo)
            REQ_READS.reset(rtok)
