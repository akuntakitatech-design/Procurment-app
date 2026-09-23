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
import json
import logging
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

import aiomysql

logger = logging.getLogger("mariadb_motor")

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
    if isinstance(cond, dict) and cond and all(isinstance(k, str) and k.startswith("$") for k in cond):
        return all(_op_matches(value, op, arg) for op, arg in cond.items())
    # kesetaraan literal
    if cond is None:
        return value is _MISSING or value is None or (isinstance(value, list) and None in value)
    if value is _MISSING:
        return False
    if isinstance(value, list) and not isinstance(cond, list):
        return any(_eq(el, cond) for el in value)
    return _eq(value, cond)


def _op_matches(value: Any, op: str, arg: Any) -> bool:
    if op == "$eq":
        return _value_matches(value, arg)
    if op == "$ne":
        return not _value_matches(value, arg)
    if op == "$in":
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
        if key == "$and":
            if not all(_match(doc, c) for c in cond): return False
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


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------
def _project(doc: dict, projection) -> dict:
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
            _set_path(out, k, deepcopy(val))
        return out
    out = deepcopy(doc)
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
            rows = [d for d in rows if _match(d, spec)]
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
            docs = await self._coll._select(self._filter)
            if self._sort: docs = _apply_sort(docs, self._sort)
            if self._skip: docs = docs[self._skip:]
            if self._limit: docs = docs[: self._limit]
            self._result = [_project(d, self._projection) for d in docs]
        return self._result

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
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
        return (" AND ".join(where), params)

    async def _select(self, flt: Optional[dict], *, for_update: bool = False, conn=None) -> List[dict]:
        rows = await self._select_rows(flt, for_update=for_update, conn=conn)
        return [doc for _, doc in rows]

    async def _select_rows(self, flt: Optional[dict], *, for_update: bool = False, conn=None) -> List[Tuple[str, dict]]:
        cols = await self._columns()
        where, params = self._pushdown(flt or {}, cols)
        sql = f"SELECT pk, doc FROM {_q(self.name)}"
        if where: sql += f" WHERE {where}"
        sql += " ORDER BY created_at ASC, pk ASC"
        if for_update: sql += " FOR UPDATE"
        rows = await self.database._fetchall(sql, params, conn=conn)
        out = []
        for pk, raw in rows:
            doc = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
            if _match(doc, flt):   # verifikasi ulang dengan semantik Mongo (aman bila pushdown parsial)
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
        cur = MariaCursor(self, filter, projection).limit(1 if not kwargs.get("sort") else 0)
        if kwargs.get("sort"): cur.sort(kwargs["sort"])
        docs = await cur.to_list(1)
        return docs[0] if docs else None

    async def insert_one(self, document: dict, *args, **kwargs) -> InsertOneResult:
        await self._columns()
        doc = dict(document); doc.pop("_id", None)
        pk = doc.get("id") if isinstance(doc.get("id"), str) and doc.get("id") else str(uuid.uuid4())
        created = _parse_dt(doc.get("created_at")) or _parse_dt(doc.get("at")) or datetime.utcnow()
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
                    pk = new.get("id") if isinstance(new.get("id"), str) and new.get("id") else str(uuid.uuid4())
                    created = _parse_dt(new.get("created_at")) or datetime.utcnow()
                    await db._execute(f"INSERT INTO {_q(self.name)} (pk, doc, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                                      [pk, _json_dumps(new), created, datetime.utcnow()], conn=conn)
                    if return_doc is not None:
                        return (None if return_doc == ReturnDocument.BEFORE else _project(new, projection)), UpdateResult(0, 0, pk)
                    return None, UpdateResult(0, 0, pk)
                return None, UpdateResult(0, 0)
            targets = rows if many else rows[:1]
            modified = 0; first_before = None; first_after = None
            for i, (pk, doc) in enumerate(targets):
                before = deepcopy(doc)
                after = _apply_update(deepcopy(doc), update)
                after.pop("_id", None)
                if i == 0: first_before, first_after = before, after
                if after != before:
                    await db._execute(f"UPDATE {_q(self.name)} SET doc = %s, updated_at = %s WHERE pk = %s",
                                      [_json_dumps(after), datetime.utcnow(), pk], conn=conn)
                    modified += 1
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
            for pk, _ in targets:
                await db._execute(f"DELETE FROM {_q(self.name)} WHERE pk = %s", [pk], conn=conn)
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
        return self.conn
    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type: await self.conn.rollback()
            else: await self.conn.commit()
        finally:
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

    def __getattr__(self, name: str) -> MariaCollection:
        if name.startswith("_"): raise AttributeError(name)
        return self[name]

    def __getitem__(self, name: str) -> MariaCollection:
        if name not in self._collections:
            self._collections[name] = MariaCollection(self, name)
        return self._collections[name]

    def get_collection(self, name: str) -> MariaCollection: return self[name]

    async def list_collection_names(self) -> List[str]:
        rows = await self._fetchall("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'", [])
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

    async def _fetchall(self, sql: str, params: Sequence, conn=None):
        if conn is not None:
            async with conn.cursor() as cur:
                await cur.execute(sql, params); return await cur.fetchall()
        pool = await self._get_pool()
        async with pool.acquire() as c:
            async with c.cursor() as cur:
                await cur.execute(sql, params); return await cur.fetchall()

    async def _execute(self, sql: str, params: Sequence, conn=None) -> int:
        if conn is not None:
            async with conn.cursor() as cur:
                await cur.execute(sql, params); return cur.rowcount
        pool = await self._get_pool()
        async with pool.acquire() as c:
            async with c.cursor() as cur:
                await cur.execute(sql, params); return cur.rowcount

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
