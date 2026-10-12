"""P7 — ekuivalensi optimasi adapter MariaDB (mariadb_motor) vs jalur referensi lama (muat semua dokumen + _match Python).

Diuji terhadap DB test terisolasi (DATABASE_URL *itest*) memakai tabel `mro` (kolom generated nyata) dengan dokumen uji ber-tag,
dibersihkan di akhir. Mencakup:
  - pushdown superset `$exists: False` dan `$gt/$gte/$lt/$lte` string (huruf besar/kecil, spasi akhir, unicode, >191 karakter,
    array, angka, bool, null, field hilang);
  - count_documents via dokumen-mini (field filter saja);
  - find().sort().to_list(k) top-k dua tahap (urutan stabil, skip/limit/projection) — identik dengan sort Python penuh;
  - urutan dasar Python (_py_order) == ORDER BY created_at, pk SQL (kembar + fallback pk tak aman);
  - memo baca per request (hit, isolasi objek, invalidasi tulis, bypass transaksi, ditutup).
"""
import asyncio
import json
import os
import random
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mariadb_motor as mm  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


STRS = ["2026-01-01", "2026-01-01 ", "2026-01-01T00:00:00+00:00", "2025-12-31", "2026-1-5", "a", "A", "b", "B", "", " ",
        "ä", "Ä", "z", "Z", "2026-01-01" + "x" * 300, "x" * 190, "x" * 191, "x" * 192, "10", "9", "1e3"]
VALS = STRS + [None, 0, 5, 10, 2.5, True, False, ["2026-01-01", "a"], ["Z"], [], {"a": 1}]


def mkdoc(i, tag, rnd):
    d = {"id": f"p7eq-{tag}-{i}", "p7eq": tag, "seq": rnd.randint(0, 5)}
    for f in ("date", "no", "requester", "need_date", "tenant_id"):
        r = rnd.random()
        if r < 0.15:
            continue  # field hilang
        d[f] = rnd.choice(VALS)
    d["created_at"] = f"2026-0{1 + i % 9}-1{i % 10}T0{i % 10}:00:00+00:00" if i % 7 else "2026-01-01T00:00:00+00:00"
    return d


def filters(rnd, tag):
    out = [{"p7eq": tag}]
    for _ in range(260):
        f = {"p7eq": tag}
        for fld in rnd.sample(["date", "no", "requester", "need_date", "tenant_id", "seq"], rnd.randint(1, 3)):
            kind = rnd.random()
            if kind < 0.25:
                f[fld] = {"$exists": rnd.choice([False, True])}
            elif kind < 0.75:
                ops = rnd.sample(["$gt", "$gte", "$lt", "$lte"], rnd.randint(1, 2))
                f[fld] = {op: rnd.choice(STRS + [5, None, True]) for op in ops}
            elif kind < 0.85:
                f[fld] = {"$in": rnd.sample(STRS, 3) + rnd.choice([[], [None]])}
            else:
                f[fld] = rnd.choice(STRS)
        if rnd.random() < 0.2:
            f = {"$and": [f, {"$or": [{"date": {"$gte": "2026"}}, {"no": {"$exists": False}}]}]}
        out.append(f)
    return out


def _old_full_count(f, cols):
    """count_documents lama memakai COUNT(*) SQL murni untuk filter kesetaraan top-level (perilaku existing, tidak diubah P7)."""
    return all((not k.startswith("$")) and "." not in k and k in cols and (
        (isinstance(v, mm._SCALAR) and not isinstance(v, dict)) or
        (isinstance(v, dict) and set(v) <= {"$in", "$eq"})) for k, v in f.items())


async def main():
    url = os.environ.get("DATABASE_URL", "")
    if "itest" not in url:
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    db = mm.MariaDatabase(url.replace("mariadb://", "mysql://"))
    coll = db["mro"]
    tag, rnd = uuid.uuid4().hex[:8], random.Random(7)
    docs = [mkdoc(i, tag, rnd) for i in range(400)]
    # pk di luar pola [0-9a-z-] (huruf besar / underscore) dengan created_at kembar -> wajib fallback ORDER BY SQL
    for i in range(6):
        d = mkdoc(1000 + i, tag, rnd)
        d["id"] = (f"P7EQ_{tag}_{i}" if i % 2 else f"p7eq_{tag}_{i}")
        d["created_at"] = "2026-01-01T00:00:00+00:00"
        docs.append(d)
    for d in docs:
        await coll.insert_one(d)
    try:
        rows = await db._fetchall("SELECT pk, doc FROM `mro` ORDER BY created_at ASC, pk ASC", [])
        allr = [(pk, json.loads(raw)) for pk, raw in rows]
        allr = [(pk, d) for pk, d in allr if d.get("p7eq") == tag]

        orig_sup = mm._pushdown_superset

        async def ref(flt):
            """Perilaku adapter SEBELUM P7: hanya pushdown lama (kesetaraan/$in) + _match Python atas dokumen penuh."""
            mm._pushdown_superset = lambda col, cond: ([], [])
            try:
                return await coll._select(flt)
            finally:
                mm._pushdown_superset = orig_sup
        fl = filters(rnd, tag)
        n_py = sum(1 for f in fl if [d for _, d in allr if mm._match(d, mm._compile_filter(f))])
        bad_sel, bad_cnt, bad_top = [], [], []
        for f in fl:
            exp = await ref(f)
            got = await coll._select(f)
            if [d["id"] for d in got] != [d["id"] for d in exp]:
                bad_sel.append(f)
            if await coll.count_documents(f) != len(exp) and not _old_full_count(f, await coll._columns()):
                bad_cnt.append(f)
            for spec, skip, k in (([("created_at", -1)], 0, 25), ([("date", 1), ("no", -1)], 3, 10),
                                  ([("seq", -1)], 0, 1000), ([("requester", 1)], 7, 5)):
                e2 = mm._apply_sort([dict(x) for x in exp], spec)[skip:skip + k]
                cur = coll.find(f, {"_id": 0, "id": 1, "date": 1}).sort(spec).skip(skip)
                g2 = await cur.limit(k).to_list(None) if k == 5 else await cur.to_list(k)
                if [d["id"] for d in g2] != [d["id"] for d in e2] or any(set(d) - {"id", "date"} for d in g2):
                    bad_top.append((f, spec, skip, k))
        check("T0 sanity: sebagian filter acak memiliki hasil", n_py > 30, n_py)
        bad_proj = []
        for f in fl[:120]:
            exp = await ref(f)
            for proj, spec in (({"_id": 0, "id": 1, "date": 1, "no": 1}, []), (["id", "requester"], [("need_date", -1)]),
                               ({"id": True, "seq": 1}, [("seq", 1), ("no", -1)])):
                e3 = [mm._project(d, proj) for d in (mm._apply_sort([dict(x) for x in exp], spec) if spec else exp)]
                cur = coll.find(f, proj)
                g3 = await (cur.sort(spec) if spec else cur).to_list(None)
                if g3 != e3:
                    bad_proj.append((f, proj, spec))
        check("T7 projection include top-level via dokumen-mini identik (urutan, field hilang, sort)", not bad_proj, bad_proj[:2])
        check(f"T1 _select dengan pushdown superset ($exists False, range string) identik ({len(fl)} filter acak x 400 dokumen)",
              not bad_sel, bad_sel[:3])
        check("T2 count_documents (dokumen-mini) identik", not bad_cnt, bad_cnt[:3])
        check("T3 find().sort().skip().limit()/to_list(k) top-k dua tahap identik (stabil, projection)", not bad_top, bad_top[:2])
        w, p = mm._pushdown_superset("`date`", {"$gte": "2026", "$lt": 5, "$exists": True})
        check("T4 pushdown hanya untuk argumen string & $exists False", len(w) == 1 and p == ["2026"], (w, p))
        w, _ = coll._pushdown({"created_at": {"$gte": "2026"}}, await coll._columns())
        check("T5 kolom fisik created_at tidak di-pushdown range", w == "", w)
        # T8 urutan dasar Python (_py_order) == ORDER BY created_at, pk SQL (termasuk created_at kembar + fallback pk tak aman)
        bad_ord = []
        prev_po = os.environ.get("MARIADB_PY_ORDER")
        for f in fl[:150]:
            os.environ["MARIADB_PY_ORDER"] = "1"  # urutan Python (opt-in; created_at sebagai teks tetap-lebar)
            try:
                got = [d["id"] for d in await coll._select(f)]
                os.environ["MARIADB_PY_ORDER"] = "0"  # ORDER BY SQL (default)
                exp = [d["id"] for d in await coll._select(f)]
            finally:
                os.environ.pop("MARIADB_PY_ORDER", None)
                if prev_po is not None:
                    os.environ["MARIADB_PY_ORDER"] = prev_po
            if got != exp:
                bad_ord.append(f)
        os.environ["MARIADB_PY_ORDER"] = "1"
        try:
            got_all = [d["id"] for d in await coll._select({"p7eq": tag})]
        finally:
            os.environ.pop("MARIADB_PY_ORDER", None)
            if prev_po is not None:
                os.environ["MARIADB_PY_ORDER"] = prev_po
        check("T8 urutan dasar Python identik dengan ORDER BY SQL (150 filter + seluruh dokumen uji)",
              not bad_ord and got_all == [d["id"] for _, d in allr], bad_ord[:2])
        from datetime import datetime as _dt
        t1, t2 = _dt(2026, 1, 1), _dt(2026, 1, 2)
        check("T9 _py_order: kembar ber-pk aman diurutkan; kembar ber-pk tak aman -> None; unik tak aman tetap diurutkan",
              mm._py_order([("b", t1), ("a-1", t1), ("0", t2)]) == [("a-1", t1), ("b", t1), ("0", t2)]
              and mm._py_order([("B", t1), ("a", t1)]) is None and mm._py_order([("a_b", t1), ("x", t2)]) == [("a_b", t1), ("x", t2)]
              and mm._py_order([("a", None)]) is None
              and mm._py_order([("t~ab", t1), ("t~aa", t1)]) == [("t~aa", t1), ("t~ab", t1)]
              # created_at teks tetap-lebar (CAST DATETIME(6) AS CHAR) — urutan leksikografis == kronologis
              and mm._py_order([("b", "2026-01-02 00:00:00.000000"), ("a", "2026-01-01 23:59:59.999999"),
                                ("c", "2026-01-01 23:59:59.999999")]) == [("a", "2026-01-01 23:59:59.999999"),
                                                                         ("c", "2026-01-01 23:59:59.999999"), ("b", "2026-01-02 00:00:00.000000")])
        # T11 _pk_pair_safe vs collation nyata (utf8mb4_unicode_ci): setiap pasangan yang dinyatakan aman berurutan sama dgn SQL
        rnd2 = random.Random(11)
        alpha = "0123456789abcdefz-~_.ABZ \t"
        strs = sorted({"".join(rnd2.choice(alpha) for _ in range(rnd2.randint(0, 5))).rstrip(" ") for _ in range(4000)})
        await db._execute("CREATE TABLE IF NOT EXISTS `p7_coll_probe` (s VARCHAR(64) COLLATE utf8mb4_unicode_ci) ENGINE=InnoDB", [])
        try:
            await db._execute("DELETE FROM `p7_coll_probe`", [])
            await db._executemany("INSERT INTO `p7_coll_probe` VALUES (%s)", [(x,) for x in strs])
            pos = {}
            for i, (x,) in enumerate(await db._fetchall("SELECT s FROM `p7_coll_probe` ORDER BY s ASC", [])):
                pos.setdefault(x, i)
            pairs = [(a_, b_) for a_, b_ in zip(strs, strs[1:]) if mm._pk_pair_safe(a_, b_)]
            wrong = [(a_, b_) for a_, b_ in pairs if not pos[a_] < pos[b_]]
        finally:
            await db._execute("DROP TABLE IF EXISTS `p7_coll_probe`", [])
        check("T11 _pk_pair_safe konsisten dengan collation utf8mb4_unicode_ci nyata", len(pairs) > 500 and not wrong, (len(pairs), wrong[:3]))
        # T10 memo baca per request: hit identik, invalidasi setelah tulis, tidak dipakai di dalam transaksi, ditutup
        calls = []
        orig_sync = db._sync_fetchall
        orig_small = db._small_fetchall
        db._sync_fetchall = lambda sql, params: (calls.append(sql), orig_sync(sql, params))[1]

        async def _small_counted(sql, params):  # jalur adaptif kecil (aiomysql) ikut dihitung sebagai query DB
            calls.append(sql)
            return await orig_small(sql, params)
        db._small_fetchall = _small_counted
        memo = mm.new_read_memo()
        tok = mm.REQ_READS.set(memo)
        try:
            target = docs[1]["id"]
            a1 = await coll.find({"p7eq": tag}, {"_id": 0}).to_list(None)
            n1 = len(calls)
            a2 = await coll.find({"p7eq": tag}, {"_id": 0}).to_list(None)
            hit = len(calls) == n1 and a1 == a2 and a1 is not a2 and (not a1 or a1[0] is not a2[0])
            a2[0]["mutated"] = 1  # objek hasil tidak berbagi state dengan memo
            a3 = await coll.find({"p7eq": tag}, {"_id": 0}).to_list(None)
            iso = "mutated" not in a3[0]
            await coll.update_one({"id": target}, {"$set": {"p7eq_flag": "x"}})
            a4 = await coll.find({"p7eq": tag}, {"_id": 0}).to_list(None)
            inval = any(d.get("p7eq_flag") == "x" for d in a4) and len(calls) > n1
            async with db._transaction():
                n2 = len(calls)
                await coll.find({"p7eq": tag}, {"_id": 0}).to_list(None)
                in_tx = len(calls) > n2 and memo["tx"] == 1
            mm.close_read_memo(memo)
            n3 = len(calls)
            await coll.find({"p7eq": tag}, {"_id": 0}).to_list(None)
            closed = len(calls) > n3
            # T12 query identik bersamaan -> 1 query DB (in-flight dibagi); setelah tulis tidak bergabung ke query lama
            memo2 = mm.new_read_memo()
            mm.REQ_READS.set(memo2)
            n4 = len(calls)
            r1, r2 = await asyncio.gather(coll.find({"p7eq": tag}, {"_id": 0}).to_list(None), coll.find({"p7eq": tag}, {"_id": 0}).to_list(None))
            shared = len(calls) == n4 + 1 and r1 == r2 and r1 is not r2
            mm.close_read_memo(memo2)
        finally:
            mm.REQ_READS.reset(tok)
            db._sync_fetchall = orig_sync
            db._small_fetchall = orig_small
        check("T10 memo baca request: hit identik & terisolasi, invalidasi setelah tulis, bypass di transaksi, nonaktif setelah ditutup",
              hit and iso and inval and in_tx and closed and mm._READ_MEMO_USED[0] == 0, (hit, iso, inval, in_tx, closed, mm._READ_MEMO_USED[0]))
        check("T12 query identik bersamaan dalam 1 request -> 1 query DB, hasil identik & objek terpisah", shared)
        check("T6 _filter_fields: path bertitik / operator top-level -> None",
              mm._filter_fields({"a.b": 1}) is None and mm._filter_fields({"$where": "x"}) is None
              and mm._filter_fields({"$or": [{"a": 1}, {"b": {"$gt": 1}}]}) == {"a", "b"})
    finally:
        await db._execute("DELETE FROM `mro` WHERE JSON_VALUE(doc, '$.p7eq') = %s", [tag])
        await db.close()
    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    asyncio.run(main())
