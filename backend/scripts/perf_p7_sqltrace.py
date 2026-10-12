"""P7 — jejak query SQL lambat satu endpoint GET in-process terhadap DB uji volume *_itest (read-only).

  cd /app/backend && python scripts/perf_p7_sqltrace.py --cred /root/perf/cred_x20.json "po?page=1&page_size=25&q=po" [--min-ms 300]
Mencetak durasi, jumlah baris, sidik parameter (hash, bukan nilai) dan potongan SQL untuk query >= --min-ms; query identik
(SQL + parameter sama) dalam satu request ditandai `DUP`. Menolak DB yang bukan *_itest.
"""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--cred", required=True)
ap.add_argument("--db", default="proc_perf_itest")
ap.add_argument("--min-ms", type=float, default=300)
ap.add_argument("--reps", type=int, default=1)
a = ap.parse_args()
if not a.db.endswith("_itest"):
    sys.exit("DB harus *_itest")
here = os.path.dirname(os.path.abspath(__file__))
os.environ.update({"DATABASE_URL": subprocess.check_output([sys.executable, os.path.join(here, "itest_url.py"), a.db], text=True).strip(),
                   "DB_NAME": a.db, "STORAGE_DRIVER": "local", "STORAGE_LOCAL_PATH": "/root/perf/uploads", "ALLOW_DEMO_SEED": "false",
                   "WRITE_TEST_CREDENTIALS": "false"})
sys.path.insert(0, os.path.dirname(here))
os.chdir(os.path.dirname(here))
import logging  # noqa: E402
logging.disable(logging.WARNING)
import httpx  # noqa: E402
import mariadb_motor  # noqa: E402
import production_bootstrap  # noqa: E402,F401
import server  # noqa: E402

LOG = []
M = mariadb_motor.MariaDatabase


def _rss_guard(limit_mb=2500):  # pengaman kontainer: proses jejak berhenti sendiri bila memori melewati batas
    import threading

    def run():
        while True:
            for ln in open("/proc/self/status"):
                if ln.startswith("VmRSS:") and int(ln.split()[1]) // 1024 > limit_mb:
                    print(f"ABORT: RSS > {limit_mb} MB", flush=True)
                    os._exit(3)
            time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()


_rss_guard()


def _wrap(name):
    orig = getattr(M, name)

    async def w(self, sql, params, conn=None):
        t0 = time.perf_counter()
        rows = await orig(self, sql, params, conn=conn)
        h = hashlib.sha1((sql + "|" + json.dumps([str(p) for p in (params or [])])).encode()).hexdigest()[:10]
        LOG.append((time.perf_counter() - t0, len(rows or []), h, sql))
        return rows
    setattr(M, name, w)


_wrap("_fetchall_bulk")
_orig_fetch = M._fetchall


async def _fetchall(self, sql, params, conn=None):  # hanya panggilan langsung (bukan dari _fetchall_bulk fallback)
    t0 = time.perf_counter()
    rows = await _orig_fetch(self, sql, params, conn=conn)
    h = hashlib.sha1((sql + "|" + json.dumps([str(p) for p in (params or [])])).encode()).hexdigest()[:10]
    LOG.append((time.perf_counter() - t0, len(rows or []), h, "[async] " + sql))
    return rows
M._fetchall = _fetchall


async def main():
    await server.app.router.startup()
    tr = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=3600) as c:
        tok = (await c.post("/api/auth/login", json=json.load(open(a.cred)))).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        for i in range(a.reps + 1):
            LOG.clear()
            t0 = time.perf_counter()
            r = await c.get(f"/api/{a.path}", headers=h)
            ms = round((time.perf_counter() - t0) * 1000)
            body = r.json() if r.status_code == 200 else {}
            tot = body.get("total") if isinstance(body, dict) else len(body)
            print(f"[{'warm' if i == 0 else 'run'}] HTTP {r.status_code} {ms} ms total={tot} queries={len(LOG)} "
                  f"rows={sum(n for _, n, _, _ in LOG)} server-timing={r.headers.get('server-timing')}", flush=True)
            if i:
                seen = {}
                for _, _, hh, _ in LOG:
                    seen[hh] = seen.get(hh, 0) + 1
                for d, n, hh, sql in sorted(LOG, key=lambda x: -x[0]):
                    if d * 1000 >= a.min_ms:
                        print(f"   {round(d * 1000):>7} ms {n:>7} rows {hh}{' DUPx' + str(seen[hh]) if seen[hh] > 1 else ''}  {sql[:150]}")

asyncio.run(main())
