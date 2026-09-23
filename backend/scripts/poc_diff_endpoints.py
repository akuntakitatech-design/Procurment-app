#!/usr/bin/env python3
"""
Differential test: bandingkan respons API backend MongoDB (asli) vs backend MariaDB (shim).

Menjalankan backend kedua (Mongo) di port terpisah dari kode yang sama, login ke keduanya,
memanggil seluruh endpoint GET (tanpa side-effect) termasuk detail dokumen, lalu
membandingkan JSON setelah normalisasi field volatil.

Pakai:
  python scripts/poc_diff_endpoints.py --mariadb http://localhost:8001 --mongo-url mongodb://localhost:27017 --mongo-db proc_inspect \
      --email qa@x --password ... [--start-mongo-backend]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

VOLATILE_KEYS = {"token", "generated_at", "server_time", "now", "timestamp", "uptime", "db", "cookieSecure",
                 "requestProto", "cookieSecureSetting", "storage", "logo_version"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in sorted(value.items()) if k not in VOLATILE_KEYS and k != "_id"}
    if isinstance(value, list):
        items = [normalize(v) for v in value]
        return items
    if isinstance(value, float):
        return round(value, 6)
    return value


def sorted_if_unordered(value):
    """Untuk list dict: urutkan berdasarkan json agar perbedaan urutan natural tidak dianggap mismatch (dilaporkan terpisah)."""
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        return sorted(value, key=lambda d: json.dumps(d, sort_keys=True, default=str))
    return value


def diff_paths(a, b, path="", out=None, limit=25):
    out = out if out is not None else []
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path or '$'}: tipe {type(a).__name__} vs {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a: out.append(f"{path}.{k}: hanya di MariaDB")
            elif k not in b: out.append(f"{path}.{k}: hanya di Mongo")
            else: diff_paths(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: panjang {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff_paths(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: {json.dumps(a, default=str)[:80]} vs {json.dumps(b, default=str)[:80]}")
    return out


def login(base, email, password):
    s = requests.Session()
    r = s.post(f"{base}/api/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mariadb", default="http://localhost:8001")
    ap.add_argument("--mongo", default="http://localhost:8011")
    ap.add_argument("--mongo-url", default="mongodb://localhost:27017")
    ap.add_argument("--mongo-db", default="proc_inspect")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--start-mongo-backend", action="store_true")
    ap.add_argument("--report", default="/tmp/diff_report.json")
    args = ap.parse_args()

    proc = None
    if args.start_mongo_backend:
        env = dict(os.environ)
        env.update({"DATABASE_URL": "", "MONGO_URL": args.mongo_url, "DB_NAME": args.mongo_db,
                    "ALLOW_DEMO_SEED": "false", "WRITE_TEST_CREDENTIALS": "false", "PROCUREFLOW_ENTRY": "bootstrap",
                    "STORAGE_DRIVER": "local", "STORAGE_LOCAL_PATH": "/tmp/proc-local-uploads", "PORT": "8011"})
        backend_dir = Path(__file__).resolve().parents[1]
        proc = subprocess.Popen([sys.executable, "production_bootstrap.py"], cwd=str(backend_dir), env=env,
                                stdout=open("/tmp/mongo_backend.log", "w"), stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                if requests.get(f"{args.mongo}/api/_healthcheck", timeout=2).ok: break
            except requests.RequestException: pass
            time.sleep(1)
        else:
            print("backend Mongo tidak siap; lihat /tmp/mongo_backend.log"); sys.exit(2)

    try:
        s_maria = login(args.mariadb, args.email, args.password)
        s_mongo = login(args.mongo, args.email, args.password)

        spec = requests.get(f"{args.mariadb}/openapi.json", timeout=60).json()
        get_paths = sorted(p for p, m in spec["paths"].items() if "get" in m)
        static = [p for p in get_paths if "{" not in p and not p.endswith(".xlsx") and p not in ("/api/_healthcheck", "/api/_system", "/api/auth/me", "/api/company/logo")]

        # endpoint dengan parameter path → isi dari daftar dokumen
        dynamic = []
        id_sources = {"mro": "/api/mro", "ro": "/api/ro", "po": "/api/po", "do": "/api/do", "mi": "/api/mi", "loans": "/api/loans",
                      "transfers": "/api/transfers", "adjustments": "/api/adjustments", "opname": "/api/opname",
                      "master": None}
        ids = {}
        for key, path in id_sources.items():
            if not path: continue
            try:
                rows = s_maria.get(f"{args.mariadb}{path}", timeout=120).json()
                if isinstance(rows, dict): rows = rows.get("rows") or rows.get("items") or []
                ids[key] = [r["id"] for r in rows if isinstance(r, dict) and r.get("id")][:3]
            except Exception:  # noqa: BLE001
                ids[key] = []
        for p in get_paths:
            m = re.match(r"^/api/(mro|ro|po|do|mi|loans|transfers|adjustments|opname)/\{[a-z_]+\}(/[a-z_-]+)?$", p)
            if m and ids.get(m.group(1)):
                for did in ids[m.group(1)]:
                    dynamic.append(re.sub(r"\{[a-z_]+\}", did, p))
        # master collections
        for name in ["items", "warehouses", "suppliers", "projects", "units", "divisions", "uoms", "taxes", "item_categories", "supplier_categories", "contacts"]:
            dynamic.append(f"/api/master/{name}")

        results = []
        for p in static + dynamic:
            r1 = s_maria.get(f"{args.mariadb}{p}", timeout=300)
            r2 = s_mongo.get(f"{args.mongo}{p}", timeout=300)
            entry = {"path": p, "status_mariadb": r1.status_code, "status_mongo": r2.status_code}
            if r1.status_code != r2.status_code:
                entry["result"] = "STATUS_MISMATCH"
            else:
                try:
                    j1, j2 = r1.json(), r2.json()
                except ValueError:
                    entry["result"] = "SAMA" if r1.content == r2.content else "BEDA_NONJSON"
                    results.append(entry); print(f"{entry['result']:16s} {p}"); continue
                n1, n2 = normalize(j1), normalize(j2)
                if n1 == n2:
                    entry["result"] = "SAMA"
                else:
                    # coba abaikan urutan list
                    def deep_sort(v):
                        if isinstance(v, dict): return {k: deep_sort(x) for k, x in v.items()}
                        if isinstance(v, list): return sorted_if_unordered([deep_sort(x) for x in v])
                        return v
                    if deep_sort(n1) == deep_sort(n2):
                        entry["result"] = "SAMA_BEDA_URUTAN"
                    else:
                        entry["result"] = "BEDA"
                        entry["diff"] = diff_paths(n1, n2)
            results.append(entry)
            print(f"{entry['result']:16s} {p}")
            for d in entry.get("diff", [])[:8]: print("    ", d)

        summary = {"total": len(results)}
        for r in results: summary[r["result"]] = summary.get(r["result"], 0) + 1
        Path(args.report).write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))
        print("\nRINGKASAN:", json.dumps(summary))
        print(f"laporan: {args.report}")
    finally:
        if proc: proc.terminate()


if __name__ == "__main__":
    main()
