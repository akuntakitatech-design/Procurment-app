"""Benchmark final P7 vs main — SELURUH endpoint Pull (3 persona) + endpoint non-Pull utama, terkendali & berulang.

Metode (stabil terhadap drift beban mesin):
- Kedua backend: 1 worker, entrypoint production, DB & dataset sama (proc_perf_itest), mesin sama, 1 request pada satu waktu.
- Per endpoint: pemanasan WARM request per backend, lalu putaran berpasangan dengan urutan ABBA (main,p7 | p7,main | p7,main |
  main,p7) agar bias cache/urutan/drift beban seimbang.
- Jumlah putaran adaptif: endpoint ringan (p50 pemanasan main < 100 ms) ROUNDS_SMALL putaran, endpoint berat ROUNDS putaran
  (p95 dari sampel kecil sangat sensitif noise; endpoint berat memiliki margin besar).
- Dicatat per backend: p50, p95, mean, min, jumlah query SQL & durasi DB (header Server-Timing), status & ukuran respons.
- Hanya GET (read-only).
Pakai: PERF_BASE=http://127.0.0.1:8032/api PERF_NEW=http://127.0.0.1:8034/api PERF_CRED_DIR=/root/perf \
      python perf_p7_bench_final.py <out.json> [ROUNDS=9] [ROUNDS_SMALL=150] [WARM=10]
Ringkasan beberapa run: python perf_p7_bench_final.py --summary out1.json out2.json ... (gate: Pull p50 & p95 <= main;
non-Pull <= 1,10x main) — dihitung dari sampel gabungan semua run, rasio per run juga ditampilkan.
"""
import json
import os
import re
import statistics
import sys
import time

B = {"main": os.environ.get("PERF_BASE", "http://127.0.0.1:8032/api"), "p7": os.environ.get("PERF_NEW", "http://127.0.0.1:8034/api")}
_CD = os.environ.get("PERF_CRED_DIR", "/root/perf")
NON_PULL = ["dashboard", "dashboard/control-center", "mro?page=1&page_size=25", "ro?page=1&page_size=25", "po?page=1&page_size=25",
            "do?page=1&page_size=25", "mi?page=1&page_size=25", "vendor-invoices?page=1&page_size=25",
            "supplier-dp?page=1&page_size=25", "report-center/register-po?page=1&page_size=50",
            "vendor-invoices/do-billing?page=1&page_size=25", "vendor-invoices/summary"]  # Tagihan DO & ringkasan Invoice
# user terbatas divisi: daftar ber-halaman & Dashboard (jalur cakupan divisi berbeda dari user global)
NON_PULL_SCOPED = ["dashboard", "mro?page=1&page_size=25", "ro?page=1&page_size=25", "po?page=1&page_size=25",
                   "do?page=1&page_size=25", "mi?page=1&page_size=25", "mro?page=2&page_size=50&sort=no&dir=asc"]
ABBA = (("main", "p7"), ("p7", "main"), ("p7", "main"), ("main", "p7"))


def login(base, cred):
    import requests
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + s.post(f"{base}/auth/login", json=cred).json()["token"]
    return s


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    f = int(k)
    return v[f] + (v[min(f + 1, len(v) - 1)] - v[f]) * (k - f)


def pull_eps(s):
    ro = s.get(f"{B['main']}/pull/ro-for-po", timeout=900).json()
    po = s.get(f"{B['main']}/pull/po-for-do", timeout=900).json()
    eps = ["pull/mro-for-ro", "pull/ro-for-po", "pull/po-for-do", "pull/mro-for-mi"]
    sup = next((r.get("supplier_id") for r in po if r.get("supplier_id")), None) if isinstance(po, list) else None
    line = ro[0]["line_id"] if isinstance(ro, list) and ro else None
    if sup:
        eps.append(f"pull/po-for-do?supplier_id={sup}")
    if line:
        eps.append(f"pull/ro-for-po/price-insight?ro_line_id={line}&date=2026-10-12")
        if sup:
            eps.append(f"pull/ro-for-po/price-history?ro_line_id={line}&supplier_id={sup}&limit=10")
    return eps


def _hit(S, k, p):
    t0 = time.perf_counter()
    r = S.get(f"{B[k]}/{p}", timeout=900)
    ms = (time.perf_counter() - t0) * 1000
    h = r.headers.get("server-timing", "") or ""
    mq = re.search(r"desc=\"(\d+) q", h)
    md = re.search(r"dur=([\d.]+)", h)
    return ms, (int(mq.group(1)) if mq else None), (float(md.group(1)) if md else None), r.status_code, len(r.content)


def bench(S, persona, p, rounds, rounds_small, warm):
    wt = {k: [] for k in B}
    for _ in range(2):  # pemanasan dasar
        for k in B:
            wt[k].append(_hit(S, k, p)[0])
    small = min(wt["main"]) < 100
    for _ in range(warm - 2 if small else 0):  # endpoint ringan: pemanasan tambahan (total WARM)
        for k in B:
            wt[k].append(_hit(S, k, p)[0])
    n = rounds_small if small else rounds
    t, dbt, q, st = {k: [] for k in B}, {k: [] for k in B}, {}, {}
    for i in range(n):
        for k in ABBA[i % 4]:
            ms, nq, dms, sc, nb = _hit(S, k, p)
            t[k].append(ms)
            if dms is not None:
                dbt[k].append(dms)
            q[k] = nq
            st[k] = (sc, nb)
    row = {"persona": persona, "endpoint": p, "rounds": n, "warm": len(wt["main"]), "kind": "pull" if p.startswith("pull/") else "non-pull"}
    for k in B:
        row[k] = {"p50": round(statistics.median(t[k]), 2), "p95": round(pct(t[k], 95), 2), "mean": round(statistics.mean(t[k]), 2),
                  "min": round(min(t[k]), 2), "db_ms_p50": round(statistics.median(dbt[k]), 1) if dbt[k] else None,
                  "queries": q.get(k), "status": st[k][0], "bytes": st[k][1], "samples": [round(x, 2) for x in t[k]]}
    row["same_status_bytes"] = st["main"] == st["p7"]
    row["p50_ratio"] = round(row["p7"]["p50"] / max(row["main"]["p50"], 0.1), 3)
    row["p95_ratio"] = round(row["p7"]["p95"] / max(row["main"]["p95"], 0.1), 3)
    return row


def summary(paths):
    runs = [json.load(open(x)) for x in paths]
    keys = [(r["persona"], r["endpoint"]) for r in runs[0]]
    out, worst_pull, worst_np = [], 0.0, 0.0
    for k in keys:
        rows = [x for run in runs for x in run if (x["persona"], x["endpoint"]) == k]
        pooled = {b: [s for x in rows for s in x[b]["samples"]] for b in B}
        p50 = {b: statistics.median(pooled[b]) for b in B}
        p95 = {b: pct(pooled[b], 95) for b in B}
        r50, r95 = p50["p7"] / p50["main"], p95["p7"] / p95["main"]
        pull = rows[0]["kind"] == "pull"
        w = max(r50, r95)
        gate = w <= 1.0 if pull else w <= 1.10
        if pull:
            worst_pull = max(worst_pull, w)
        else:
            worst_np = max(worst_np, w)
        st = sorted({x["main"]["status"] for x in rows} | {x["p7"]["status"] for x in rows})
        o = {"persona": k[0], "endpoint": re.sub(r"=([0-9a-f-]{36})", "=<id>", k[1]), "kind": rows[0]["kind"], "status": st,
             "same_status_bytes": all(x["same_status_bytes"] for x in rows), "n_per_backend": len(pooled["main"]),
             "main_p50": round(p50["main"], 1), "main_p95": round(p95["main"], 1), "p7_p50": round(p50["p7"], 1), "p7_p95": round(p95["p7"], 1),
             "q_main": rows[0]["main"]["queries"], "q_p7": rows[0]["p7"]["queries"],
             "db_ms_main": rows[0]["main"]["db_ms_p50"], "db_ms_p7": rows[0]["p7"]["db_ms_p50"],
             "p50_ratio": round(r50, 3), "p95_ratio": round(r95, 3),
             "per_run_p50_ratio": [x["p50_ratio"] for x in rows], "per_run_p95_ratio": [x["p95_ratio"] for x in rows],
             "gate": "PASS" if gate else "FAIL"}
        out.append(o)
        print(f"{o['persona']:15s} {o['endpoint'][:58]:58s} {'PULL' if pull else 'non '} st{st} n{o['n_per_backend']} "
              f"main {o['main_p50']:8.1f}/{o['main_p95']:8.1f} p7 {o['p7_p50']:8.1f}/{o['p7_p95']:8.1f} q{o['q_main']}->{o['q_p7']} "
              f"| {o['p50_ratio']}/{o['p95_ratio']} run {o['per_run_p50_ratio']}/{o['per_run_p95_ratio']} -> {o['gate']}")
    nf = sum(1 for o in out if o["gate"] == "FAIL")
    print(f"\nterburuk Pull {worst_pull:.3f} (gate <= 1.0) | non-Pull {worst_np:.3f} (gate <= 1.10) | FAIL {nf}/{len(out)}")
    return out


def main():
    if sys.argv[1] == "--summary":
        out = summary(sys.argv[2:])
        json.dump(out, open(os.environ.get("PERF_SUMMARY_OUT", "/tmp/perf-p7-bench-summary.json"), "w"), indent=1)
        return
    out_path = sys.argv[1]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 9
    rounds_small = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    warm = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    persona = {n: json.load(open(f"{_CD}/cred_parity_{n}.json")) for n in ("global", "tanpa_harga", "terbatas_divisi")}
    res = []
    for name, cred in persona.items():
        S = login(B["main"], cred)  # token sama dipakai kedua backend (DB & JWT secret sama)
        extra = NON_PULL if name == "global" else NON_PULL_SCOPED if name == "terbatas_divisi" else []
        for p in pull_eps(S) + extra:
            row = bench(S, name, p, rounds, rounds_small, warm)
            res.append(row)
            print(f"{name:15s} {p[:60]:60s} n{row['rounds']} main {row['main']['p50']:8.1f}/{row['main']['p95']:8.1f} q{row['main']['queries']} "
                  f"st{row['main']['status']} | p7 {row['p7']['p50']:8.1f}/{row['p7']['p95']:8.1f} q{row['p7']['queries']} "
                  f"st{row['p7']['status']} | {row['p50_ratio']}/{row['p95_ratio']}", flush=True)
            json.dump(res, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main()
