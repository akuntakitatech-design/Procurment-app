"""Publikasikan laporan parity FINAL ke docs/perf/ dari hasil per-run (sementara) perf_p7_parity.py.

Hasil per-run (satu file per persona) disimpan di $PERF_ARTIFACT_DIR (default <tmp>/procureflow-perf) dan TIDAK
di-commit. Skrip ini menggabungkan beberapa file per-run menjadi satu laporan final berformat
{dataset, base, new, summary, rows} dan menolak menulis bila terdeteksi data sensitif (email, token, password, URL DB).

Pakai:
  python scripts/perf_p7_report.py --name p7-syncfix-parity-2026-10-12 --base "85831df (main pasca #68)" \
      --new "feature/p7-performance + sync-fix" --dataset "proc_perf_itest ..." run_global.json run_tanpa_harga.json ...
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FINAL_DIR = os.path.join(REPO, "docs", "perf")
SENSITIVE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}|eyJ[A-Za-z0-9_-]{10,}|ghp_|github_pat_|Bearer |"
                       r"password|passwd|mysql://|mariadb://|AKIA[0-9A-Z]{12}", re.I)
ROW_KEYS = ("user", "label", "path", "base_status", "new_status", "identical", "base_ms", "new_ms", "note")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="file hasil per-run perf_p7_parity.py (list baris)")
    ap.add_argument("--name", required=True, help="nama file final tanpa .json (di docs/perf/)")
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--by-design", default="paging", help="kata kunci label yang selisihnya disengaja (dicatat terpisah)")
    a = ap.parse_args(argv)
    rows = []
    for f in a.runs:
        data = json.load(open(f))
        if not isinstance(data, list) or not data or not all(isinstance(r, dict) and "identical" in r for r in data):
            sys.exit(f"format tidak dikenal / kosong: {f}")
        rows += [{k: r.get(k) for k in ROW_KEYS} for r in data]
    users = sorted({r["user"] for r in rows})
    per_user = {u: {"identical": sum(1 for r in rows if r["user"] == u and r["identical"]),
                    "total": sum(1 for r in rows if r["user"] == u)} for u in users}
    diff = [r for r in rows if not r["identical"]]
    by_design = [r for r in diff if a.by_design and a.by_design.lower() in str(r["label"]).lower()]
    summary = {"identical": len(rows) - len(diff), "total": len(rows), "per_user": per_user,
               "status_mismatch": sum(1 for r in rows if r["base_status"] != r["new_status"]),
               "different_by_design": len(by_design), "different_unexplained": len(diff) - len(by_design)}
    out = {"dataset": a.dataset, "base": a.base, "new": a.new, "summary": summary, "rows": rows}
    txt = json.dumps(out, indent=1, ensure_ascii=False)
    hit = SENSITIVE.search(txt)
    if hit:
        sys.exit(f"MENOLAK menulis: terdeteksi pola sensitif {hit.group(0)[:12]!r}")
    os.makedirs(FINAL_DIR, exist_ok=True)
    path = os.path.join(FINAL_DIR, f"{a.name}.json")
    open(path, "w").write(txt + "\n")
    print(f"{path}: identik {summary['identical']}/{summary['total']}; status beda {summary['status_mismatch']}; "
          f"beda by-design {summary['different_by_design']}; beda tak terjelaskan {summary['different_unexplained']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
