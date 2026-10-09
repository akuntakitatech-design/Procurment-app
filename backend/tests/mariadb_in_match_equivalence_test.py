"""H1 — ekuivalensi pencocokan `$in`/`$nin` berbasis set (mariadb_motor._InList) vs jalur linear lama.

Unit murni (tanpa DB/HTTP). Referensi = cabang `$in` lama yang tetap dipakai untuk `list` biasa, sehingga setiap kasus
membandingkan hasil fast-path dengan implementasi sebelumnya secara langsung.
"""
import math
import os
import random
import sys
import time
from enum import IntEnum

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mariadb_motor as mm  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


def ref_op(value, op, arg):
    return mm._op_matches(value, op, list(arg))  # list biasa -> cabang linear lama


def fast_op(value, op, arg):
    return mm._op_matches(value, op, mm._InList(arg))


class Color(IntEnum):
    RED = 1


NAN = float("nan")
VALUES = [mm._MISSING, None, 0, 1, -1, 2, 1.0, 0.0, 2.5, True, False, "", "a", "A", "1", "abc", "ÄbÇ", "x" * 300,
          2 ** 53, 2 ** 53 + 1, float(2 ** 53), NAN, [], [None], [1, "a"], [True], [1.0], [[1]], [{"a": 1}], {"a": 1}, {},
          ["A", "b"], [0, False], Color.RED]
ARGS = [[], [None], [1], [1, 1, 1], [True], [False], [0], [1.0], ["a"], ["A"], [None, "a", 1], [True, 1, "1"],
        [2 ** 53], [float(2 ** 53)], [NAN], [1, NAN], [[1]], [{"a": 1}], [{"$regex": "^a"}], [{"$regex": "^A", "$options": "i"}, 2],
        [Color.RED], ["", None], list(range(50)), [str(i) for i in range(50)] + [None], [0, False, None, ""]]


def main():
    # E1 — matriks penuh nilai x argumen, $in dan $nin
    bad = []
    for op in ("$in", "$nin"):
        for a in ARGS:
            for v in VALUES:
                r, f = ref_op(v, op, a), fast_op(v, op, a)
                if r != f:
                    bad.append((op, repr(v)[:30], repr(a)[:40], r, f))
    check(f"E1 matriks {len(VALUES)}x{len(ARGS)}x2 identik (kosong, duplikat, null/missing, campuran, bool vs angka, NaN, "
          "tak-hashable, regex, enum)", not bad, bad[:5])

    # E2 — fallback untuk elemen yang tidak aman diproses set
    for a, name in (([{"$regex": "^a"}], "regex"), ([NAN], "NaN"), ([[1]], "list"), ([Color.RED], "IntEnum"),
                    ([{"a": 1}], "dict")):
        check(f"E2 fallback linear untuk elemen {name} (lookup=None)", mm._InList(a).lookup is None)
    check("E2 fast-path aktif untuk str/int/float/bool/None", mm._InList(["a", 1, 2.5, True, None]).lookup is not None)

    # E3 — semantik kunci: bool berbeda dari angka; int == float; None/missing
    check("E3 True tidak cocok dengan 1 / 1 tidak cocok dengan True", not fast_op(True, "$in", [1]) and not fast_op(1, "$in", [True]))
    check("E3 1 cocok dengan 1.0 (seperti _eq)", fast_op(1, "$in", [1.0]) and fast_op(1.0, "$in", [1]))
    check("E3 field hilang cocok bila None di daftar; [] tidak cocok None", fast_op(mm._MISSING, "$in", [None])
          and not fast_op([], "$in", [None]) and fast_op(None, "$in", [None, "x"]))
    check("E3 elemen array dicocokkan (any)", fast_op(["x", "a"], "$in", ["a"]) and not fast_op([["a"]], "$in", ["a"]))

    # E4 — _match dengan filter ter-compile identik dengan filter asli (nested $and/$or/$nor/$elemMatch, path bertitik)
    rnd = random.Random(20261009)
    pool = [None, 0, 1, 2, 1.0, True, False, "a", "b", "A", "", "id-1", "id-2", "id-3"]

    def rv(depth=0):
        k = rnd.random()
        if k < 0.6 or depth > 1:
            return rnd.choice(pool)
        if k < 0.8:
            return [rv(depth + 1) for _ in range(rnd.randint(0, 3))]
        return {"k": rv(depth + 1)}

    docs = []
    for i in range(400):
        d = {"id": f"id-{i % 5}"}
        for f in ("a", "b", "c"):
            if rnd.random() < 0.85:
                d[f] = rv()
        if rnd.random() < 0.7:
            d["n"] = {"x": rv(), "arr": [{"y": rnd.choice(pool)} for _ in range(rnd.randint(0, 3))]}
        docs.append(d)

    def rin():
        return [rnd.choice(pool) for _ in range(rnd.randint(0, 6))]
    filters = [
        {"a": {"$in": rin()}}, {"b": {"$nin": rin()}}, {"n.x": {"$in": rin()}}, {"id": {"$in": ["id-1", "id-3", "id-3"]}},
        {"$and": [{"a": {"$in": rin()}}, {"c": {"$nin": rin()}}]}, {"$or": [{"a": {"$in": rin()}}, {"b": {"$in": rin()}}]},
        {"$nor": [{"a": {"$in": rin()}}]}, {"n.arr": {"$elemMatch": {"y": {"$in": rin()}}}},
        {"a": {"$in": rin(), "$ne": None}}, {"a": {"$not": {"$in": rin()}}}, {"zz": {"$in": [None]}}, {"a": {"$in": []}},
        {"a": {"$in": [{"$regex": "^a"}, 1]}}, {"tags": ["a", "b"]}, {"a": {"$in": ("a", 1)}},
    ]
    for _ in range(120):
        filters.append({rnd.choice(["a", "b", "c", "n.x"]): {rnd.choice(["$in", "$nin"]): rin()}})
    mism = []
    for flt in filters:
        orig = repr(flt)
        cf = mm._compile_filter(flt)
        for d in docs:
            if mm._match(d, flt) != mm._match(d, cf):
                mism.append((orig[:60], d)); break
        if repr(flt) != orig:
            mism.append(("filter asli termutasi", orig[:60]))
    check(f"E4 fuzz _match {len(filters)} filter x {len(docs)} dokumen identik + filter asli tidak termutasi", not mism, mism[:3])

    # E5 — aggregate $match memakai compile yang sama, hasil identik
    pipe = [{"$match": {"a": {"$in": ["a", 1, None]}}}]
    exp = [d for d in docs if mm._match(d, pipe[0]["$match"])]
    check("E5 aggregate $match identik dengan _match referensi", mm._aggregate(docs, pipe) == exp)

    # E6 — kompleksitas: 20.000 dokumen x daftar 20.000 id; jalur lama O(N*M) (~4e8 perbandingan)
    ids = [f"doc-{i}" for i in range(20000)]
    big = [{"id": f"doc-{i}"} for i in range(0, 40000, 2)]
    cflt = mm._compile_filter({"id": {"$in": ids}})
    t = time.perf_counter()
    hit = sum(1 for d in big if mm._match(d, cflt))
    dt = time.perf_counter() - t
    sample_ref = sum(1 for d in big[:200] if mm._match(d, {"id": {"$in": ids}}))
    sample_fast = sum(1 for d in big[:200] if mm._match(d, cflt))
    check(f"E6 20k x 20k: hasil benar ({hit} cocok) dan cepat ({dt * 1000:.0f} ms < 2000 ms); sampel = referensi",
          hit == 10000 and dt < 2.0 and sample_ref == sample_fast, (hit, dt, sample_ref, sample_fast))

    n, ok = len(RESULTS), sum(RESULTS)
    print(f"\n{ok}/{n} passed")
    sys.exit(0 if ok == n else 1)


if __name__ == "__main__":
    main()
