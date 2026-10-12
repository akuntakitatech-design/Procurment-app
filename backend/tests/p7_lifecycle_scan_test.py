"""P7 — tahap/lifecycle MRO: jalur 1-scan alokasi (banyak MRO) == jalur 4 query `$in` per tipe (jalur lama) — DB test *itest*.

Data acak berantai MRO line -> RO -> PO -> DO dan MRO line -> MI, termasuk kasus tepi: source_line_id array / string kosong /
None / hilang, target_type array / tak dikenal, qty hilang / string, alokasi yatim, multi-alokasi per baris. Dibersihkan di akhir.
"""
import asyncio
import os
import random
import sys
import types
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mariadb_motor as mm  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


async def main():
    url = os.environ.get("DATABASE_URL", "")
    if "itest" not in url:
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    db = mm.MariaDatabase(url.replace("mariadb://", "mysql://"))
    sys.modules.setdefault("server", types.ModuleType("server")).db = db  # _mro_lifecycle: `from server import db`
    import txn_list_paging_layer as L
    tag, rnd = uuid.uuid4().hex[:8], random.Random(5)
    mros = [{"id": f"p7lc-{tag}-m{i}"} for i in range(60)]
    lines, allocs = [], []
    for m in mros:
        for j in range(rnd.randint(0, 3)):
            lid = f"{m['id']}-l{j}"
            lines.append({"id": lid, "mro_id": m["id"], "qty": rnd.choice([1, 2, 5, "3", None]), "p7lc": tag})
            for k in range(rnd.randint(0, 2)):
                rl = f"{lid}-ro{k}"
                allocs.append({"source_line_id": lid, "target_line_id": rl, "target_type": "ro", "qty": rnd.choice([1, 2, None]),
                               "source_type": rnd.choice(["mro", "mro", ["mro"], None]), "source_doc_id": m["id"]})
                for q in range(rnd.randint(0, 2)):
                    pl = f"{rl}-po{q}"
                    allocs.append({"source_line_id": rl, "target_line_id": pl, "target_type": rnd.choice(["po", ["po", "x"]]), "qty": 1,
                                   "source_type": "ro", "source_doc_id": rnd.choice([f"ro-{tag}", None])})
                    for d in range(rnd.randint(0, 2)):
                        allocs.append({"source_line_id": rnd.choice([pl, [pl, "zz"]]), "target_line_id": f"{pl}-do{d}", "target_type": "do",
                                       "qty": rnd.choice([1, 0.5, "2"])})
            if rnd.random() < 0.5:
                allocs.append({"source_line_id": lid, "target_line_id": f"{lid}-mi", "target_type": "mi", "qty": rnd.choice([1, 3])})
    allocs += [{"source_line_id": "", "target_line_id": "", "target_type": "ro", "qty": 9},
               {"source_line_id": None, "target_line_id": None, "target_type": "po", "qty": 9},
               {"target_line_id": "orphan", "target_type": "do", "qty": 9},
               {"source_line_id": "nope", "target_line_id": "x", "target_type": "other", "qty": 9}]
    lines.append({"id": "", "mro_id": mros[0]["id"], "qty": 4, "p7lc": tag})  # baris ber-id kosong
    for ln in lines:
        await db.mro_lines.insert_one(ln)
    for a in allocs:
        await db.allocations.insert_one({"id": f"p7lc-{tag}-{uuid.uuid4().hex[:10]}", "p7lc": tag, **a})
    try:
        import copy
        r_old, r_new = copy.deepcopy(mros), copy.deepcopy(mros)
        L.FULL_ALLOC_SCAN_MIN = 10 ** 9
        await L._mro_lifecycle(r_old)
        L.FULL_ALLOC_SCAN_MIN = 0
        await L._mro_lifecycle(r_new)
        diff = [(a["id"], a.get("lifecycle"), b.get("lifecycle")) for a, b in zip(r_old, r_new) if a != b]
        check("LC1 lifecycle & tahap per MRO identik: 1-scan alokasi == 4 query $in per tipe (60 MRO, kasus tepi)", not diff, diff[:2])
        stages = {r["lifecycle_stage"] for r in r_old}
        check("LC2 sanity: data uji menghasilkan beberapa tahap berbeda", len(stages) >= 3, stages)
        # LC3 peta 1-scan == allocs_from()/mro_monitor_batch: find({"source_line_id": {"$in": ids}, "target_type": t}) per kunci
        allx = await L._allocs_by_type(("ro", "mi", "po", "do"))
        keys = sorted({a.get("source_line_id") for a in allocs if isinstance(a.get("source_line_id"), str)} | {"", "zz", "nope"})
        bad = []
        for t in ("ro", "mi", "po", "do"):
            ref = {}
            for a in await db.allocations.find({"source_line_id": {"$in": [k for k in keys if k]}, "target_type": t}, {"_id": 0}).to_list(None):
                ref.setdefault(a.get("source_line_id"), []).append(a)
            for k in keys:
                got = [(a.get("target_line_id"), a.get("qty")) for a in allx[t].get(k, [])]
                exp = [(a.get("target_line_id"), a.get("qty")) for a in ref.get(k, [])] if k else []
                if got != exp:
                    bad.append((t, k, got, exp))
        check("LC3 peta alokasi 1-scan identik per kunci & urutan dengan query $in per tipe (allocs_from)", not bad, bad[:2])
        # LC4 receipt_control._upstream_lineage (1 scan ro/mro) == _upstream (target_line_id $in + source_type) per kunci
        import receipt_control_layer as RC
        fake = types.SimpleNamespace(db=db)
        tl = sorted({a.get("target_line_id") for a in allocs if isinstance(a.get("target_line_id"), str)}) + ["", None, "zz"]
        bad4 = []
        for st in ("ro", "mro", "po"):
            RC.UPSTREAM_BULK_MIN = 10 ** 9
            ref = await RC._upstream(fake, tl, st)
            RC.UPSTREAM_BULK_MIN = -1
            got = await RC._upstream_lineage(fake, tl, st) if st in ("ro", "mro") else ref
            for k in [x for x in tl if isinstance(x, str)]:
                g = [(a.get("source_line_id"), a.get("source_doc_id")) for a in got.get(k, [])]
                e = [(a.get("source_line_id"), a.get("source_doc_id")) for a in ref.get(k, [])]
                if g != e:
                    bad4.append((st, k, g, e))
        RC.UPSTREAM_BULK_MIN = 6000
        n_up = sum(len(v) for v in (await RC._upstream(fake, tl, "ro")).values())
        check("LC4 _upstream_lineage 1-scan identik per kunci & urutan dengan _upstream ($in + source_type)", not bad4 and n_up > 10,
              (bad4[:2], n_up))
    finally:
        L.FULL_ALLOC_SCAN_MIN = 2000
        await db._execute("DELETE FROM `allocations` WHERE JSON_VALUE(doc, '$.p7lc') = %s", [tag])
        await db._execute("DELETE FROM `mro_lines` WHERE JSON_VALUE(doc, '$.p7lc') = %s", [tag])
        await db.close()
    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    asyncio.run(main())
