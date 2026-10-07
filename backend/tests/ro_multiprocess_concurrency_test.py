"""RO concurrency lintas PROSES (bukan hanya lintas coroutine).

Bagian A — named lock MariaDB (ro_source_lock) dari 2 proses OS berbeda dengan pool/koneksi
           berbeda: critical section tidak pernah overlap; urutan kunci berlawanan tidak deadlock.
Bagian B — HTTP ke 2 proses backend berbeda (port berbeda, DB sama): N request RO paralel
           berebut sisa MRO yang sama -> tepat 1 berhasil, total allocation <= Qty MRO.

Dijalankan oleh scripts/run_ro_multiprocess_test.sh terhadap DB test (bukan production):
  LOCK_DSN=mysql://.../procurement_test API_URLS=http://127.0.0.1:8013/api,http://127.0.0.1:8014/api \
  ADMIN_EMAIL=... ADMIN_PASSWORD=... python tests/ro_multiprocess_concurrency_test.py
"""
import asyncio
import multiprocessing as mp
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
RESULTS = []


def check(name, ok, detail=None):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" — {detail}"))


# ----------------------------------------------------------------------------- Bagian A
def _worker(dsn, names, rounds, q):
    import ro_source_lock as L

    async def run():
        spans = []
        for _ in range(rounds):
            async with L.db_named_locks(dsn, L.lock_names(names), timeout=20):
                t0 = time.monotonic(); await asyncio.sleep(0.02); spans.append((t0, time.monotonic()))
        for p in list(L._pools.values()):  # tutup pool sebelum loop berakhir (hindari warning GC)
            p.close(); await p.wait_closed()
        L._pools.clear()
        return spans
    try:
        q.put(("ok", os.getpid(), asyncio.run(run())))
    except Exception as exc:  # noqa: BLE001
        q.put(("err", os.getpid(), repr(exc)))


def part_a(dsn):
    a, b = f"A{uuid.uuid4()}", f"B{uuid.uuid4()}"
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(dsn, [a, b] if i % 2 == 0 else [b, a], 15, q)) for i in range(4)]
    [p.start() for p in procs]
    out = [q.get(timeout=120) for _ in procs]
    [p.join(30) for p in procs]
    errs = [o for o in out if o[0] != "ok"]
    check("A: 4 proses OS, urutan kunci berlawanan -> tanpa deadlock/timeout", not errs and len({o[1] for o in out}) == 4, errs)
    spans = sorted(s for o in out if o[0] == "ok" for s in o[2])
    overlap = any(spans[i + 1][0] < spans[i][1] - 1e-4 for i in range(len(spans) - 1))
    check("A: critical section lintas proses tidak pernah overlap (60 putaran)", len(spans) == 60 and not overlap, len(spans))
    # baris MRO berbeda tidak saling menunggu
    async def independent():
        import ro_source_lock as L
        async with L.db_named_locks(dsn, [f"pfro:{uuid.uuid4()}"]):
            t0 = time.monotonic()
            async with L.db_named_locks(dsn, [f"pfro:{uuid.uuid4()}"], timeout=1):
                dt = time.monotonic() - t0
        for p in list(L._pools.values()):
            p.close(); await p.wait_closed()
        L._pools.clear()
        return dt
    check("A: kunci baris MRO lain tidak tertahan (granular per record)", asyncio.run(independent()) < 0.5)


# ----------------------------------------------------------------------------- Bagian B
def part_b(apis, email, password):
    # Satu sesi aktif per user: login SEKALI lalu pakai token yang sama di semua proses backend
    # (DB & JWT secret sama). Login per-proses akan menggantikan sesi sebelumnya (by design).
    r = requests.post(f"{apis[0]}/auth/login", json={"email": email, "password": password})
    token = r.json().get("token")
    sessions = []
    for api in apis:
        s = requests.Session()
        s.headers["Authorization"] = f"Bearer {token}"
        sessions.append((api, s))
    api0, s0 = sessions[0]

    def mk(path, body):
        r = s0.post(f"{api0}/{path}", json=body)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        return r.json()
    u = uuid.uuid4().hex[:6]
    div = mk("master/divisions", {"code": f"DV{u}", "name": f"Divisi MP {u}"})
    cat = mk("master/item_categories", {"code": f"KC{u}", "name": "Kategori MP"})
    uom = mk("master/uoms", {"code": f"PC{u}", "name": "Pieces"})
    wh = mk("master/warehouses", {"code": f"WH{u}", "name": "Gudang MP", "is_active": True})
    item = mk("master/items", {"code": f"IT{u}", "name": "Barang MP", "unit": "PCS", "is_active": True,
                               "category_id": cat["id"], "division_id": div["id"], "base_uom_id": uom["id"]})
    QTY = 8
    m = mk("mro", {"no": f"MRO-MP-{u}", "division_id": div["id"], "requester": "QA", "submitted": True,
                   "lines": [{"item_id": item["id"], "qty": QTY, "warehouse_id": wh["id"]}]})
    s0.post(f"{api0}/mro/{m['id']}/submit", json={})
    ml = m["lines"][0]
    body = {"division_id": div["id"], "lines": [{"item_id": item["id"], "qty": QTY, "uom_id": uom["id"], "warehouse_id": wh["id"],
            "sources": [{"mro_id": m["id"], "line_id": ml["id"], "qty": QTY, "base_qty": QTY}]}]}

    N = 8
    barrier = __import__("threading").Barrier(N)

    def fire(i):
        api, s = sessions[i % len(sessions)]
        barrier.wait()
        r = s.post(f"{api}/ro", json=body)
        return api, r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
    with ThreadPoolExecutor(max_workers=N) as ex:
        res = list(ex.map(fire, range(N)))
    ok = [x for x in res if x[1] == 200]
    rejected = [x for x in res if x[1] in (400, 409)]
    check(f"B: {N} RO paralel ke {len(apis)} proses backend -> tepat 1 berhasil", len(ok) == 1, [(a[-5:], c) for a, c, _ in res])
    check("B: sisanya ditolak (melebihi sisa / sedang diproses), bukan 500",
          len(rejected) == N - len(ok) and all(("melebihi sisa" in str(b)) or ("sedang diproses" in str(b)) for _, _, b in rejected),
          [b for _, _, b in rejected][:3])
    r = s0.get(f"{api0}/pull/mro-for-ro").json()
    row = next((x for x in r if x.get("line_id") == ml["id"]), None)
    total = 0.0
    for api, s in sessions[:1]:
        for x in s.get(f"{api}/ro").json():
            d = s.get(f"{api}/ro/{x['id']}").json()
            for ln in d.get("lines") or []:
                total += sum(float(sv.get("qty") or 0) for sv in ln.get("sources") or [] if sv.get("line_id") == ml["id"])
    check("B: total allocation baris MRO <= Qty MRO (tanpa over-allocation)", total <= QTY + 1e-6 and row is None, (total, row))

    # ------------------------------------------------------------- Bagian C: RO -> PO lintas proses
    scat = mk("master/supplier_categories", {"code": f"SC{u}", "name": "Kategori Supplier MP"})
    sup = mk("master/suppliers", {"code": f"SP{u}", "name": "Supplier MP", "supplier_category_id": scat["id"]})
    m2 = mk("mro", {"no": f"MRO-MP2-{u}", "division_id": div["id"], "requester": "QA", "submitted": True,
                    "lines": [{"item_id": item["id"], "qty": QTY, "warehouse_id": wh["id"]}]})
    s0.post(f"{api0}/mro/{m2['id']}/submit", json={})
    ro = mk("ro", {"division_id": div["id"], "lines": [{"item_id": item["id"], "qty": QTY, "uom_id": uom["id"], "warehouse_id": wh["id"],
                   "sources": [{"mro_id": m2["id"], "line_id": m2["lines"][0]["id"], "qty": QTY, "base_qty": QTY}]}]})
    s0.post(f"{api0}/ro/{ro['id']}/submit", json={})
    rl = ro["lines"][0]
    po_body = {"supplier_id": sup["id"], "division_id": div["id"], "lines": [{"item_id": item["id"], "qty": QTY, "uom_id": uom["id"], "warehouse_id": wh["id"],
               "price": 1000, "sources": [{"ro_id": ro["id"], "line_id": rl["id"], "qty": QTY, "base_qty": QTY}]}]}
    barrier2 = __import__("threading").Barrier(N)

    def fire_po(i):
        api, s = sessions[i % len(sessions)]
        barrier2.wait()
        r = s.post(f"{api}/po", json=po_body)
        return api, r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
    with ThreadPoolExecutor(max_workers=N) as ex:
        res = list(ex.map(fire_po, range(N)))
    ok = [x for x in res if x[1] == 200]
    check(f"C: {N} PO paralel ke {len(apis)} proses atas Sisa RO {QTY} -> tepat 1 berhasil", len(ok) == 1, [(a[-5:], c) for a, c, _ in res])
    check("C: sisanya ditolak 400/409 (bukan 500)", all(c in (400, 409) for _, c, _ in res if c != 200), [b for _, c, b in res if c != 200][:3])
    rows = s0.get(f"{api0}/pull/ro-for-po").json()
    check("C: baris RO tidak lagi ditawarkan (Sisa PO 0, tanpa over-allocation)", not any(x.get("line_id") == rl["id"] for x in rows))


def main():
    dsn = os.environ.get("LOCK_DSN")
    apis = [x.strip().rstrip("/") for x in os.environ.get("API_URLS", "").split(",") if x.strip()]
    if dsn:
        part_a(dsn)
    if len(apis) >= 2:
        part_b(apis, os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
