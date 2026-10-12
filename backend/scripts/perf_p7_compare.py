"""Gabungkan JSON benchmark P7 (perf_bench_p7.py) -> tabel perbandingan before/after (Markdown).

  python scripts/perf_p7_compare.py docs/perf/p7-before-main.json,docs/perf/p7-before-main-p2.json,docs/perf/p7-before-main-conc.json \
      docs/perf/p7-after.json[,...]
"""
import json
import sys


def load(paths):
    rows, conc = {}, {}
    for p in paths.split(","):
        d = json.load(open(p))
        for r in d.get("endpoints") or []:
            rows[r["label"]] = r
        conc.update({k: v for k, v in (d.get("concurrency") or {}).items()})
    return rows, conc


def fmt(ms):
    if ms is None:
        return "–"
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms} ms"


def main():
    (b_rows, b_conc), (a_rows, a_conc) = load(sys.argv[1]), load(sys.argv[2])
    out = ["| Area | Before p50 / p95 | After p50 / p95 | Perubahan p50 | Query before → after | RSS puncak MB before → after | "
           "Total baris before → after |", "|---|---|---|---|---|---|---|"]
    for k in list(b_rows) + [x for x in a_rows if x not in b_rows]:
        b, a = b_rows.get(k), a_rows.get(k)
        if b and a:
            ch = f"{b['p50'] / max(a['p50'], 1):.1f}x lebih cepat" if a["p50"] < b["p50"] else f"{a['p50'] / max(b['p50'], 1):.1f}x lebih lambat"
        else:
            ch = "–"
        g = lambda r, f: (r or {}).get(f)  # noqa: E731
        out.append(f"| {k} | {fmt(g(b, 'p50'))} / {fmt(g(b, 'p95'))} | {fmt(g(a, 'p50'))} / {fmt(g(a, 'p95'))} | {ch} | "
                   f"{g(b, 'queries')} → {g(a, 'queries')} | {g(b, 'peak_rss_mb')} → {g(a, 'peak_rss_mb')} | {g(b, 'total')} → {g(a, 'total')} |")
    out += ["", "| Uji paralel | Before | After |", "|---|---|---|"]
    for k in [x for x in b_conc if x != "_errors"]:
        b, a = b_conc[k], a_conc.get(k) or {}
        s = lambda v: (f"p50 {fmt(v['p50'])} / p95 {fmt(v['p95'])}" + (f" / {v['rps']} req/s" if "rps" in v else "")) if v else "–"  # noqa: E731
        out.append(f"| {k} | {s(b)} | {s(a)} |")
    out.append(f"| error HTTP | {b_conc.get('_errors')} | {a_conc.get('_errors')} |")
    print("\n".join(out))


if __name__ == "__main__":
    main()
