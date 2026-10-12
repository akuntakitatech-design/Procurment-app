"""P7 — benchmark performa p50/p95 via HTTP ke backend TERISOLASI (scripts/perf_p7_backend.sh; DB uji volume proc_perf_itest).

  python scripts/perf_bench_p7.py --cred /root/perf/cred_x20.json --label before [--reps 7] [--conc 10]
Hasil: tabel Markdown (stdout) + JSON docs/perf/p7-<label>.json. Read-only (hanya GET). Tidak untuk preview/sandbox/production.
Kolom: p50/p95 ms (klien HTTP lokal, termasuk serialisasi), db ms & jumlah query (header Server-Timing), total baris, status HTTP.
"""
import argparse
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import requests

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FINAL_DIR = os.path.join(REPO, "docs", "perf")  # laporan final (masuk Git)
ARTIFACT_DIR = os.environ.get("PERF_ARTIFACT_DIR") or os.path.join(tempfile.gettempdir(), "procureflow-perf")  # sementara (tidak di-commit)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("P7_API", "http://127.0.0.1:8031/api"))
    ap.add_argument("--cred", required=True, help="file JSON {email,password} user uji")
    ap.add_argument("--label", required=True)
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--conc", type=int, default=10)
    ap.add_argument("--only", default="", help="filter label (substring, koma)")
    ap.add_argument("--skip", type=int, default=0, help="lewati N endpoint pertama (lanjutan run yang terputus)")
    ap.add_argument("--conc-only", action="store_true", help="hanya uji paralel")
    ap.add_argument("--pid", type=int, default=0, help="PID backend uji: catat puncak RSS per endpoint")
    ap.add_argument("--rss-limit-mb", type=int, default=3500, help="pengaman kontainer: hentikan backend uji bila RSS melewati batas")
    ap.add_argument("--exclude", default="", help="lewati label (substring, koma)")
    a = ap.parse_args()
    peak = {"mb": 0, "killed": False}

    def rss_mb():
        try:
            for ln in open(f"/proc/{a.pid}/status"):
                if ln.startswith("VmRSS:"):
                    return int(ln.split()[1]) // 1024
        except OSError:
            return 0
        return 0

    def watch():
        while a.pid:
            m = rss_mb()
            peak["mb"] = max(peak["mb"], m)
            if m > a.rss_limit_mb and not peak["killed"]:
                peak["killed"] = True
                os.kill(a.pid, 9)  # lindungi kontainer (batas memori) — endpoint dicatat ABORT, bukan hasil
            time.sleep(0.2)
    if a.pid:
        import threading
        threading.Thread(target=watch, daemon=True).start()
    cred = json.load(open(a.cred))

    def login():
        s = requests.Session()
        s.headers["Authorization"] = "Bearer " + s.post(f"{a.api}/auth/login", json=cred, timeout=60).json()["token"]
        return s
    S = login()

    def first(path, key="id"):
        r = S.get(f"{a.api}/{path}", timeout=600).json()
        items = r.get("items") if isinstance(r, dict) else r
        return (items or [{}])[0].get(key)
    po1, mro1, do1, mi1 = first("po?page=1&page_size=25"), first("mro?page=1&page_size=25"), first("do?page=1&page_size=25"), first("mi?page=1&page_size=25")
    P = "page=1&page_size=25"
    ep = [
        ("Dashboard", "dashboard"), ("Dashboard Premium", "dashboard-premium"),
        ("Control Center (bulan)", "dashboard/control-center?date_from=2026-09-01&date_to=2026-09-30"),
        ("MRO hal.1 (+counts)", f"mro?{P}&counts=lifecycle_stage"), ("MRO hal.40", "mro?page=40&page_size=25"),
        ("MRO cari", f"mro?{P}&q=Barang"), ("MRO sort no", f"mro?{P}&sort=no&dir=asc"),
        ("MRO filter periode", f"mro?{P}&date_from=2025-01-01&date_to=2025-06-30"), ("MRO detail", f"mro/{mro1}"),
        ("RO hal.1", f"ro?{P}"), ("RO cari", f"ro?{P}&q=Barang"),
        ("PO hal.1", f"po?{P}"), ("PO cari", f"po?{P}&q=Supplier"), ("PO filter penerimaan", f"{'po'}?{P}&f_receipt_status=Belum+Diterima"),
        ("PO sort nilai", f"po?{P}&sort=grand_total&dir=desc"), ("PO sort Approval 2", f"po?{P}&sort=approval2_at&dir=asc"),
        ("PO hal.100 (size 100)", "po?page=100&page_size=100"), ("PO detail", f"po/{po1}"),
        ("DO hal.1", f"do?{P}"), ("DO detail", f"do/{do1}"), ("MI hal.1", f"mi?{P}"), ("MI detail", f"mi/{mi1}"),
        ("Transfer hal.1", f"transfers?{P}"), ("Pinjam hal.1", f"loans?{P}"), ("Penyesuaian hal.1", f"adjustments?{P}"),
        ("Opname hal.1", f"opname?{P}"),
        ("Inventory item-stock", f"inventory/item-stock?{P}"), ("Inventory ledger", "inventory/ledger"),
        ("Gudang item-warehouse", f"item-warehouse?{P}"), ("Master barang hal.1", f"master/items?{P}"),
        ("SPK hal.1", f"spk?{P}"), ("SPK cari", f"spk?{P}&q=Customer+7"), ("Kontrak Vendor hal.1", f"vendor-contracts?{P}"),
        ("Invoice Vendor hal.1", f"vendor-invoices?{P}"), ("Tagihan DO", f"vendor-invoices/do-billing?{P}"),
        ("Approval inbox", "approvals/inbox?scope=mine"), ("Lookup batch", "lookup-batch?names=item_categories,items,units,warehouses"),
        ("Pusat Laporan katalog", "report-center/catalog"), ("Lap. Register PO", "report-center/register-po?page=1&page_size=50"),
        ("Lap. posisi stok", "report-center/posisi-stok?page=1&page_size=50"),
        ("Lap. MRO traceability", "report-center/mro-traceability?page=1&page_size=50"),
        ("Lap. AP outstanding", "report-center/ap-outstanding?page=1&page_size=50"),
        ("Export daftar PO Excel", "report-center/txn-po/export.xlsx"), ("Export daftar MRO Excel", "report-center/txn-mro/export.xlsx"),
        ("Export daftar PO PDF (periode)", "report-center/txn-po/export.pdf?date_from=2026-09-01&date_to=2026-09-30"),
        ("Export Register PO Excel", "report-center/register-po/export.xlsx"),
    ]
    only = [x.strip().lower() for x in a.only.split(",") if x.strip()]
    if only:
        ep = [e for e in ep if any(o in e[0].lower() for o in only)]
    excl = [x.strip().lower() for x in a.exclude.split(",") if x.strip()]
    if excl:
        ep = [e for e in ep if not any(o in e[0].lower() for o in excl)]
    ep = [] if a.conc_only else ep[a.skip:]

    def get(path):
        for attempt in range(2):
            try:
                return S.get(f"{a.api}/{path}", timeout=1800)
            except requests.exceptions.ConnectionError:
                if attempt:
                    raise
                time.sleep(1)
    res = []
    print("| Area | p50 ms | p95 ms | db ms | query | total | HTTP | RSS puncak MB |\n|---|---|---|---|---|---|---|---|", flush=True)
    for label, path in ep:
        heavy = "export" in path or "traceability" in path
        ts, dbs, nq, sc, tot = [], [], None, None, None
        peak["mb"] = rss_mb() if a.pid else 0
        t0 = time.perf_counter()
        get(path)  # warm-up
        slow = (time.perf_counter() - t0) > 20  # >20 s: cukup 1 sampel terukur (dicatat apa adanya, bukan dipotong)
        for _ in range(1 if slow else max(3, a.reps // 2) if heavy else a.reps):
            t0 = time.perf_counter()
            r = get(path)
            ts.append((time.perf_counter() - t0) * 1000)
            sc = r.status_code
            m = re.search(r'db;dur=([\d.]+);desc="(\d+) q', r.headers.get("server-timing", ""))
            if m:
                dbs.append(float(m.group(1))); nq = int(m.group(2))
        try:
            j = r.json()
            tot = j.get("total") if isinstance(j, dict) and "total" in j else (len(j) if isinstance(j, list) else None)
        except Exception:
            tot = r.headers.get("x-report-rows")
        row = {"label": label, "path": path, "status": sc, "p50": round(pct(ts, 50)), "p95": round(pct(ts, 95)), "bytes": len(r.content),
               "total": tot, "db_ms": round(pct(dbs, 50)) if dbs else None, "queries": nq,
               "peak_rss_mb": peak["mb"] or None}
        res.append(row)
        print(f"| {label} | {row['p50']} | {row['p95']} | {row['db_ms']} | {nq} | {tot} | {sc} | {row['peak_rss_mb']} |", flush=True)
        json.dump({"label": a.label, "endpoints": res}, open(os.path.join(ARTIFACT_DIR, f"p7-{a.label}.partial.json"), "w"), indent=1)

    conc = {}
    if not only and not a.skip:
        # login berulang user yang sama mencabut token sebelumnya (kebijakan sesi) -> N klien paralel memakai token yang sama
        sess = []
        for _ in range(a.conc):
            x = requests.Session(); x.headers["Authorization"] = S.headers["Authorization"]; sess.append(x)
        errs = []

        def hit(i, path):
            t0 = time.perf_counter()
            try:
                r = sess[i % len(sess)].get(f"{a.api}/{path}", timeout=1800)
            except requests.exceptions.ConnectionError:  # koneksi keep-alive idle ditutup server -> ulang sekali
                t0 = time.perf_counter()
                r = sess[i % len(sess)].get(f"{a.api}/{path}", timeout=1800)
            if r.status_code != 200:
                errs.append((path, r.status_code))
            return (time.perf_counter() - t0) * 1000
        mix = [f"po?{P}", f"mro?{P}&counts=lifecycle_stage", f"do?{P}", "dashboard", f"po/{po1}", f"mi?{P}", "auth/me"]
        for label, paths in ((f"{a.conc} user paralel — PO hal.1", [f"po?{P}"]), (f"{a.conc} user paralel — campuran menu", mix)):
            t0 = time.perf_counter()
            with ThreadPoolExecutor(a.conc) as ex:
                ts = list(ex.map(lambda i: hit(i, paths[i % len(paths)]), range(a.conc * 4)))
            conc[label] = {"p50": round(pct(ts, 50)), "p95": round(pct(ts, 95)), "rps": round(len(ts) / (time.perf_counter() - t0), 1)}
        with ThreadPoolExecutor(a.conc + 2) as ex:
            exp = [ex.submit(hit, 0, "report-center/txn-mro/export.xlsx") for _ in range(2)]
            time.sleep(0.3)
            ts = list(ex.map(lambda i: hit(i, "auth/me" if i % 2 else f"po/{po1}"), range(a.conc * 2)))
            [f.result() for f in exp]
        conc["auth/me & PO detail saat 2 export Excel besar berjalan"] = {"p50": round(pct(ts, 50)), "p95": round(pct(ts, 95))}
        conc["_errors"] = len(errs)
        for k, v in conc.items():
            print(f"| {k} | {v} |", flush=True)
    os.makedirs(FINAL_DIR, exist_ok=True)
    json.dump({"label": a.label, "endpoints": res, "concurrency": conc, "reps": a.reps, "conc": a.conc},
              open(os.path.join(FINAL_DIR, f"p7-{a.label}{'-part' + str(a.skip) if a.skip else ''}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
