"""Baseline performa P6 — endpoint daftar transaksi & export daftar (Excel/PDF) SEBELUM Performance Optimization.

HANYA untuk DB test terisolasi (*itest*) & backend test (default http://localhost:8013/api). Tidak mengoptimasi apa pun.
1. (opsional --seed N) menanam N dokumen MRO (+1 baris) & N PO (+1 baris) langsung ke tenant admin uji (volume).
2. Mengukur (repetisi R, default 5): GET daftar halaman 1 (page_size 25), JSON Pusat Laporan txn-*, export.xlsx, export.pdf.
   Mencatat median/p95 waktu (ms), jumlah baris, & header Server-Timing (jumlah/durasi query DB) bila tersedia.
Hasil: Markdown ke stdout (disalin ke docs/perf-baseline-p6.md).

Pemakaian: DATABASE_URL=<itest> python backend/scripts/perf_baseline_p6.py --email <admin uji> --password <pw> [--seed 5100]
"""
import argparse
import json
import os
import statistics
import sys
import time
import uuid

import requests

sys.path.insert(0, "/app/backend/tests")

LISTS = [("txn-mro", "mro"), ("txn-ro", "ro"), ("txn-po", "po"), ("txn-do", "do"), ("txn-mi", "mi"), ("txn-transfer", "transfers"),
         ("txn-loan", "loans"), ("txn-adjustment", "adjustments"), ("txn-opname", "opname"), ("txn-spk", "spk"),
         ("txn-vendor-contract", "vendor-contracts"), ("txn-invoice", "vendor-invoices"), ("txn-do-billing", "vendor-invoices/do-billing"),
         ("txn-supplier-dp", "supplier-dp")]


def seed(n, tenant, div, item, wh):
    from opening_correction_test import conn, ins
    cn = conn()
    try:
        tag = uuid.uuid4().hex[:4]
        for i in range(n):
            mid, pid = f"pf-m-{tag}-{i}", f"pf-p-{tag}-{i}"
            day = f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}"
            ins(cn, "mro", {"id": mid, "tenant_id": tenant, "no": f"PF-MRO-{tag}-{i:05d}", "date": day, "division_id": div, "requester": f"Perf {i % 7}",
                            "status": "Draft", "created_at": f"{day}T01:00:00+00:00"})
            ins(cn, "mro_lines", {"id": f"{mid}-l", "tenant_id": tenant, "mro_id": mid, "item_id": item, "qty": 1 + i % 5, "warehouse_id": wh})
            ins(cn, "po", {"id": pid, "tenant_id": tenant, "no": f"PF-PO-{tag}-{i:05d}", "date": day, "division_id": div, "status": "Draft",
                           "document_status": "Draft", "receipt_status": "Open", "grand_total": 1000 * (1 + i % 50), "created_at": f"{day}T02:00:00+00:00"})
            ins(cn, "po_lines", {"id": f"{pid}-l", "tenant_id": tenant, "po_id": pid, "item_id": item, "qty": 1, "price": 1000, "warehouse_id": wh})
    finally:
        cn.close()


def timed(s, url, reps):
    out, rows, st = [], None, []
    for _ in range(reps):
        t = time.perf_counter()
        r = s.get(url)
        out.append((time.perf_counter() - t) * 1000)
        rows = r.headers.get("X-Report-Rows") or rows
        st.append(r.headers.get("Server-Timing", ""))
        code = r.status_code
        if code == 200 and "json" in r.headers.get("content-type", ""):
            j = r.json()
            rows = len(j) if isinstance(j, list) else j.get("total_rows", j.get("total", rows))
    q = sorted(out)
    p95 = q[min(len(q) - 1, int(round(0.95 * (len(q) - 1))))]
    db = st[-1].split(",")[0] if st and st[-1] else "-"
    return code, statistics.median(out), p95, rows, db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("TEST_API_URL", "http://localhost:8013/api"))
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()
    if "itest" not in os.environ.get("DATABASE_URL", ""):
        sys.exit("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
    s = requests.Session()
    tok = s.post(f"{a.api}/auth/login", json={"email": a.email, "password": a.password}).json()["token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    if a.seed:
        me = s.get(f"{a.api}/auth/me").json()
        div = s.get(f"{a.api}/lookup/divisions").json()[0]["id"]
        item = s.get(f"{a.api}/master/items").json()[0]["id"]
        wh = s.get(f"{a.api}/master/warehouses").json()[0]["id"]
        seed(a.seed, me["tenant_id"], div, item, wh)
    print(f"| Daftar | Endpoint daftar (hal. 1, 25 baris) median / p95 ms | Total daftar | JSON export median / p95 ms | Baris export "
          f"| Excel median / p95 ms | PDF median / p95 ms | Query DB (Excel) |")
    print("|---|---|---|---|---|---|---|---|")
    for key, path in LISTS:
        lst = f"{a.api}/{path}" + ("" if path == "supplier-dp" else "?page=1&page_size=25")
        c1, m1, p1, n1, _ = timed(s, lst, a.reps)
        c2, m2, p2, n2, _ = timed(s, f"{a.api}/report-center/{key}?page_size=50" + ("&tab=all" if key == "txn-supplier-dp" else ""), a.reps)
        c3, m3, p3, n3, db3 = timed(s, f"{a.api}/report-center/{key}/export.xlsx" + ("?tab=all" if key == "txn-supplier-dp" else ""), a.reps)
        c4, m4, p4, _, _ = timed(s, f"{a.api}/report-center/{key}/export.pdf" + ("?tab=all" if key == "txn-supplier-dp" else ""), a.reps)
        pdf = f"{m4:.0f} / {p4:.0f}" if c4 == 200 else f"{c4} (batas PDF 5.000) {m4:.0f} / {p4:.0f}"
        print(f"| {key} | {m1:.0f} / {p1:.0f} | {n1} | {m2:.0f} / {p2:.0f} | {n2} | {m3:.0f} / {p3:.0f} | {pdf} | {db3} |")
    print(json.dumps({"reps": a.reps, "seed": a.seed}))


if __name__ == "__main__":
    main()
