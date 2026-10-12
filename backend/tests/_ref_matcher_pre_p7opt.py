"""Salinan BEKU matcher filter `mariadb_motor` sebelum optimasi jalur cepat P7 — HANYA referensi untuk
p7_matcher_equivalence_test.py. Jangan dipakai di kode aplikasi."""
import re
from typing import Any, Dict, Optional, Tuple

import mariadb_motor as _mm

_MISSING = _mm._MISSING


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


def _compile_filter(flt: Any) -> Any:
    """Salinan filter dengan argumen `$in`/`$nin` dibungkus `_InList`. Filter asli tidak diubah."""
    if isinstance(flt, dict):
        return {k: (_InList(v) if k in ("$in", "$nin") and isinstance(v, (list, tuple)) else _compile_filter(v))
                for k, v in flt.items()}
    if isinstance(flt, list):
        return [_compile_filter(x) for x in flt]
    return flt


def _in_fast(value: Any, arg: "_InList") -> bool:
    """Ekuivalen dengan cabang `$in` linear untuk `arg.lookup` yang valid."""
    if value is _MISSING:
        return arg.has_none
    lookup = arg.lookup
    for v in (value if isinstance(value, list) else [value]):
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


