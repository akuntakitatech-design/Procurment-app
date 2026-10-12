"""P7 — ekuivalensi matcher filter Mongo (`mariadb_motor._match` + `_compile_filter`) vs SALINAN BEKU matcher sebelum
optimasi jalur cepat (`tests/_ref_matcher_pre_p7opt.py`): field top-level `_get_path`, penanda `_OpDict`, `$in` skalar
tanpa list sementara, loop operator tanpa generator.

Uji in-process murni (tanpa DB). Dokumen & filter acak: field hilang / None / list / dict bersarang / bool vs int vs float /
NaN / str unicode & kosong; operator $eq $ne $in $nin $exists $gt $gte $lt $lte $regex(+$options) $not $size $elemMatch
$all $type; logika $and $or $nor; path bertitik & indeks array; dict literal & dict kosong.
Kriteria: hasil (True/False ATAU jenis exception) identik — filter terkompilasi & mentah — dan filter asli tidak dimutasi.
"""
import copy
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import mariadb_motor as mm  # noqa: E402
import _ref_matcher_pre_p7opt as ref  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


SCALARS = [None, 0, 1, 2, 1.0, 2.5, -1, True, False, "", "a", "A", "b", "Approved", "approved", "ä", "x" * 50,
           float("nan"), "2026-01-01", "1"]
FIELDS = ["a", "b", "c", "status", "id", "x.y", "arr.0", "arr.k", "n.m.o", ""]


def rval(rnd, depth=0):
    r = rnd.random()
    if depth < 2 and r < 0.12:
        return [rval(rnd, depth + 1) for _ in range(rnd.randint(0, 3))]
    if depth < 2 and r < 0.2:
        return {rnd.choice(["y", "k", "m", "o", "a"]): rval(rnd, depth + 1) for _ in range(rnd.randint(0, 2))}
    return rnd.choice(SCALARS)


def rdoc(rnd):
    d = {}
    for f in ["a", "b", "c", "status", "id", "x", "arr", "n", ""]:
        if rnd.random() < 0.75:
            d[f] = rval(rnd)
    if rnd.random() < 0.3:
        d["n"] = {"m": {"o": rval(rnd)}}
    if rnd.random() < 0.3:
        d["arr"] = [rval(rnd), {"k": rval(rnd)}, rval(rnd)]
    return d


def rcond(rnd, depth=0):
    r = rnd.random()
    if r < 0.25:
        return rval(rnd)  # literal (termasuk list/dict literal)
    if r < 0.3:
        return {}
    ops = {}
    for _ in range(rnd.randint(1, 3)):
        op = rnd.choice(["$eq", "$ne", "$in", "$nin", "$exists", "$gt", "$gte", "$lt", "$lte", "$regex", "$not", "$size",
                         "$elemMatch", "$all", "$type", "$in", "$ne"])
        if op in ("$in", "$nin", "$all"):
            arg = [rval(rnd) for _ in range(rnd.randint(0, 4))]
            if rnd.random() < 0.1:
                arg.append({"$regex": "^a", "$options": "i"})
            if rnd.random() < 0.1:
                arg = tuple(arg)
        elif op == "$exists":
            arg = rnd.choice([True, False, 0, 1])
        elif op == "$regex":
            arg = rnd.choice(["^a", "A", "pp", ".*", "^$"])
            if rnd.random() < 0.5:
                ops["$options"] = rnd.choice(["i", "", "m"])
        elif op == "$not":
            arg = rcond(rnd, depth + 1) if depth < 2 else {"$eq": rval(rnd)}
        elif op == "$size":
            arg = rnd.randint(0, 3)
        elif op == "$elemMatch":
            arg = rnd.choice([{"k": rval(rnd)}, {"$gt": 0}, {"$in": [1, "a", None]}, {"$eq": rval(rnd)}])
        else:
            arg = rval(rnd)
        ops[op] = arg
    return ops


def rfilter(rnd, depth=0):
    f = {}
    for _ in range(rnd.randint(0, 3)):
        r = rnd.random()
        if depth < 2 and r < 0.15:
            f[rnd.choice(["$and", "$or", "$nor"])] = [rfilter(rnd, depth + 1) for _ in range(rnd.randint(1, 3))]
        else:
            f[rnd.choice(FIELDS)] = rcond(rnd)
    if rnd.random() < 0.3:  # bentuk proxy tenant
        f = {"$and": [{"tenant_id": rnd.choice(["t1", "t2"])}, f]}
    return f


def outcome(fn, doc, flt):
    try:
        return ("ok", bool(fn(doc, flt)))
    except Exception as e:  # noqa: BLE001
        return ("err", type(e).__name__)


def main():
    rnd = random.Random(20261012)
    n = bad = muts = 0
    for _ in range(4000):
        flt = rfilter(rnd)
        before = repr(flt)
        cnew = mm._compile_filter(flt)
        cref = ref._compile_filter(flt)
        for _ in range(12):
            doc = rdoc(rnd)
            if rnd.random() < 0.5:
                doc["tenant_id"] = rnd.choice(["t1", "t2"])
            dcopy = copy.deepcopy(doc)
            exp = outcome(ref._match, doc, cref)
            got = outcome(mm._match, doc, cnew)
            exp_raw = outcome(ref._match, doc, flt)
            got_raw = outcome(mm._match, doc, flt)
            n += 1
            if not (exp == got and exp_raw == got_raw):
                bad += 1
                if bad <= 5:
                    print("  beda:", flt, doc, exp, got, exp_raw, got_raw)
            if repr(doc) != repr(dcopy):
                muts += 1
        if repr(flt) != before:
            muts += 1
    check(f"M1 {n} pasangan (dokumen, filter) acak: hasil/exception identik dgn referensi (terkompilasi & mentah)", bad == 0, f"{bad} beda")
    check("M2 filter & dokumen tidak dimutasi", muts == 0, f"{muts}")

    # M3 _get_path jalur cepat == referensi pada path top-level, bertitik, indeks, dokumen non-dict
    gp_bad = 0
    for _ in range(20000):
        doc = rnd.choice([rdoc(rnd), [rdoc(rnd)], None, "s", 5])
        path = rnd.choice(FIELDS + ["arr.1", "arr.5", "n.m", "zz", "a.b"])
        a, b = ref._get_path(doc, path), mm._get_path(doc, path)
        if not ((a is ref._MISSING and b is mm._MISSING) or repr(a) == repr(b)):
            gp_bad += 1
    check("M3 _get_path identik (20.000 kasus)", gp_bad == 0, f"{gp_bad}")

    # M4 _compile_filter: penanda _OpDict hanya untuk dict operator tak kosong; isi == dict referensi
    samples = [{"a": {"$in": [1, 2]}}, {"a": {}}, {"a": {"b": 1}}, {"$and": [{"a": 1}]}, {"a": {"$ne": None, "$in": ("x",)}},
               {"a": {"$regex": "^a", "$options": "i"}}, {"a": {"$elemMatch": {"$gt": 1}}}]
    ok = True
    for s in samples:
        c, r = mm._compile_filter(s), ref._compile_filter(s)
        ok = ok and c == r and repr(dict(c)) == repr(dict(r))
    ok = ok and type(mm._compile_filter({"a": {"$in": [1]}})["a"]) is mm._OpDict and type(mm._compile_filter({"a": {}})["a"]) is dict \
        and type(mm._compile_filter({"a": {"b": 1}})["a"]) is dict
    check("M4 _compile_filter: isi identik referensi; _OpDict hanya dict operator tak kosong", ok)

    # M5 sapuan sistematis: satu field x setiap nilai katalog (termasuk field hilang) x ribuan kondisi acak
    values = [mm._MISSING] + SCALARS + [[], [None], [1, "a"], [True], [[1]], {}, {"y": 1}, {"k": None}, [{"k": 1}, 2]]
    conds = [rcond(rnd) for _ in range(3000)] + [{"$exists": True}, {"$exists": False}, None, {"$in": [None]}, {"$ne": None},
                                                 {"$nin": [None, 1]}, {"$in": []}, {"$eq": None}]
    sw = sw_bad = 0
    for cond in conds:
        for path in ("a", "x.y", "arr.0"):
            flt = {path: cond}
            cn, cr = mm._compile_filter(flt), ref._compile_filter(flt)
            for v in values:
                top = path.split(".")[0]
                doc = {} if v is mm._MISSING else ({"a": v} if path == "a" else {"x": {"y": v}} if path == "x.y" else {"arr": [v]})
                sw += 1
                if outcome(ref._match, doc, cr) != outcome(mm._match, doc, cn) or outcome(ref._match, doc, flt) != outcome(mm._match, doc, flt):
                    sw_bad += 1
                    if sw_bad <= 3:
                        print("  beda:", flt, doc, top)
    check(f"M5 sapuan sistematis {sw} kasus (field hilang/None/list/dict x kondisi): identik", sw_bad == 0, f"{sw_bad}")

    print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
