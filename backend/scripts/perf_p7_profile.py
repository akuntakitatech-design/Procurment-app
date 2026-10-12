"""P7 — profil cProfile satu endpoint GET in-process (ASGI) terhadap DB uji volume *_itest (read-only).

  cd /app/backend && python scripts/perf_p7_profile.py --cred /root/perf/cred_x20.json "do?page=1&page_size=25" [--top 35]
Menolak DB yang bukan *_itest. MARIADB_SYNC_READS=0 -> baca massal di event loop (terlihat profiler); default jalur produksi (thread).
"""
import argparse
import asyncio
import cProfile
import io
import json
import os
import pstats
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--cred", required=True)
ap.add_argument("--db", default="proc_perf_itest")
ap.add_argument("--top", type=int, default=35)
ap.add_argument("--sort", default="tottime")
a = ap.parse_args()
if not a.db.endswith("_itest"):
    sys.exit("DB harus *_itest")
here = os.path.dirname(os.path.abspath(__file__))
os.environ.update({"DATABASE_URL": subprocess.check_output([sys.executable, os.path.join(here, "itest_url.py"), a.db], text=True).strip(),
                   "DB_NAME": a.db, "STORAGE_DRIVER": "local", "STORAGE_LOCAL_PATH": "/root/perf/uploads", "ALLOW_DEMO_SEED": "false",
                   "WRITE_TEST_CREDENTIALS": "false", "MARIADB_SYNC_READS": os.environ.get("MARIADB_SYNC_READS", "1")})
sys.path.insert(0, os.path.dirname(here))
os.chdir(os.path.dirname(here))
import httpx  # noqa: E402
import production_bootstrap  # noqa: E402,F401
import server  # noqa: E402


async def main():
    await server.app.router.startup()
    tr = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=3600) as c:
        tok = (await c.post("/api/auth/login", json=json.load(open(a.cred)))).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        await c.get(f"/api/{a.path}", headers=h)  # warm-up
        pr = cProfile.Profile()
        t0 = time.perf_counter()
        pr.enable()
        r = await c.get(f"/api/{a.path}", headers=h)
        pr.disable()
        print(f"HTTP {r.status_code} {round((time.perf_counter() - t0) * 1000)} ms  server-timing={r.headers.get('server-timing')}")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats(a.sort).print_stats(a.top)
    print("\n".join(ln[:200] for ln in s.getvalue().splitlines()))

asyncio.run(main())
