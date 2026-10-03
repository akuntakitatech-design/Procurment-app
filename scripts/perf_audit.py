"""Audit performa endpoint list transaksi (read-only). Usage: python scripts/perf_audit.py EMAIL PASSWORD [paged]
Mencetak: endpoint | status | detik | record | KB | Server-Timing (jumlah query DB, total & terlama)."""
import json
import sys
import time

import requests

API = (sys.argv[4] if len(sys.argv) > 4 else open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]) + "/api"
PAGED = len(sys.argv) > 3 and sys.argv[3] == "paged"
EPS = ["mro", "reports/mro-traceability", "ro", "po", "do", "mi", "transfers", "loans", "adjustments", "opname",
       "vendor-invoices", "vendor-invoices/do-billing"]

S = requests.Session()
S.post(f"{API}/auth/login", json={"email": sys.argv[1], "password": sys.argv[2]}, timeout=120).raise_for_status()
S.get(f"{API}/auth/me", timeout=120)
for ep in EPS:
    url = f"{API}/{ep}" + ("?page=1&page_size=25" if PAGED and not ep.startswith("reports") else "")
    t0 = time.perf_counter()
    try:
        r = S.get(url, timeout=300)
    except Exception as exc:  # noqa: BLE001
        print(f"{ep:28} ERROR {exc}")
        continue
    dt = time.perf_counter() - t0
    try:
        body = r.json()
        n = len(body["items"]) if isinstance(body, dict) and "items" in body else len(body) if isinstance(body, list) else "-"
        total = body.get("total") if isinstance(body, dict) else None
    except json.JSONDecodeError:
        n, total = "-", None
    print(f"{ep:28} {r.status_code} {dt:6.2f}s rec={n}{'/' + str(total) if total is not None else ''} "
          f"{len(r.content) / 1024:7.1f}KB  {r.headers.get('server-timing', '')}", flush=True)
