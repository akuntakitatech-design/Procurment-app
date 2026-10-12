"""P7 — ekuivalensi daftar ber-halaman user TERBATAS DIVISI: jalur pra-saring cakupan + jalur cepat scoped (default)
vs jalur penuh tanpa pra-saring (backend referensi P7_SCOPE_PREFILTER=0 P7_SCOPED_FAST=0). Read-only (GET).

Dua backend P7 identik (kode & DB sama) — beda hanya flag. Untuk tiap persona (kred JSON) x daftar (mro/ro/po/do/mi) x variasi
query (halaman 1/2/terakhir/di luar rentang, ukuran 25/50/100, sort no/date/created_at asc/desc, pencarian q, periode,
hitungan & filter tahap MRO): status HTTP & body JSON identik byte-per-byte (json.dumps sort_keys).

Pakai: TEST_API_URL=http://127.0.0.1:8034/api TEST_REF_API_URL=http://127.0.0.1:8035/api \
       SCOPE_CREDS=/root/perf/cred_parity_terbatas_divisi.json,/root/perf/cred_parity_tanpa_harga.json \
       python tests/p7_scope_prefilter_equivalence_test.py
"""
import json
import os
import sys

import requests

NEW = os.environ.get("TEST_API_URL", "http://127.0.0.1:8034/api")
REF = os.environ.get("TEST_REF_API_URL", "http://127.0.0.1:8035/api")
RES = {"pass": 0, "fail": 0}
LISTS = ("mro", "ro", "po", "do", "mi")


def check(name, cond, info=""):
    RES["pass" if cond else "fail"] += 1
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


def variants(module, sample_no):
    v = [{"page": 1, "page_size": 25}, {"page": 2, "page_size": 25}, {"page": 1, "page_size": 50}, {"page": 3, "page_size": 100},
         {"page": 999, "page_size": 25}]
    for s in ("no", "date", "created_at"):
        for d in ("asc", "desc"):
            v.append({"page": 1, "page_size": 25, "sort": s, "dir": d})
    v += [{"page": 1, "page_size": 25, "date_from": "2025-01-01", "date_to": "2025-12-31"},
          {"page": 2, "page_size": 50, "date_from": "2024-06-01"},
          {"page": 1, "page_size": 25, "q": sample_no[:6] if sample_no else "PO"},
          {"page": 1, "page_size": 25, "q": "zzz-tidak-ada"},
          {"page": 1, "page_size": 25, "q": sample_no or "a", "sort": "no", "dir": "asc"}]
    if module == "mro":
        v += [{"page": 1, "page_size": 25, "counts": "lifecycle_stage"},
              {"page": 1, "page_size": 25, "counts": "lifecycle_stage", "f_lifecycle_stage": "Open"},
              {"page": 1, "page_size": 25, "f_lifecycle_stage": "Closed"}]
    return v


def main():
    creds = [p for p in os.environ.get("SCOPE_CREDS", "").split(",") if p]
    assert creds, "SCOPE_CREDS kosong"
    for cp in creds:
        cred = json.load(open(cp))
        label = os.path.basename(cp).replace("cred_parity_", "").replace(".json", "")
        tok = requests.post(f"{NEW}/auth/login", json=cred, timeout=60).json()["token"]
        S = requests.Session()
        S.headers["Authorization"] = "Bearer " + tok  # token sama untuk kedua backend (DB & JWT secret sama)
        for m in LISTS:
            first = S.get(f"{NEW}/{m}", params={"page": 1, "page_size": 25}, timeout=600)
            items = (first.json() or {}).get("items") if first.status_code == 200 else None
            sample = (items[0].get("no") if items else "") or ""
            for qp in variants(m, sample):
                a = S.get(f"{NEW}/{m}", params=qp, timeout=600)
                b = S.get(f"{REF}/{m}", params=qp, timeout=600)
                ja = json.dumps(a.json(), sort_keys=True, default=str) if a.headers.get("content-type", "").startswith("application/json") else a.text
                jb = json.dumps(b.json(), sort_keys=True, default=str) if b.headers.get("content-type", "").startswith("application/json") else b.text
                tot = (a.json() or {}).get("total") if a.status_code == 200 and isinstance(a.json(), dict) else None
                check(f"[{label}] {m} {qp} -> {a.status_code}/{b.status_code} total={tot}", a.status_code == b.status_code and ja == jb,
                      f"status {a.status_code} vs {b.status_code}, len {len(ja)} vs {len(jb)}")
    print(f"\n{RES['pass']}/{RES['pass'] + RES['fail']} passed")
    sys.exit(0 if RES["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
