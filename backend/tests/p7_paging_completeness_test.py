"""P7 — kelengkapan daftar ber-halaman (tanpa batas 1.000) terhadap SELURUH dataset — read-only, DB uji *itest*.

Kriteria pemilik (perubahan `total` paging by-design): nilai total baru benar berdasarkan seluruh dataset, pagination tidak
kehilangan / menduplikasi dokumen, filter & sorting konsisten pada seluruh halaman.

Untuk tiap persona (kred JSON {email,password}) dan tiap daftar (mro/ro/po/do/mi/vendor-invoices):
  C1 total == jumlah dokumen di DB (persona global: seluruh tenant; persona terbatas divisi: dokumen divisinya)
  C2 gabungan seluruh halaman: jumlah == total, id unik (tanpa duplikat), himpunan id == himpunan id DB (tanpa hilang)
  C3 sort `no` asc & desc: urutan gabungan seluruh halaman terurut monoton (kunci + tie-break `no`), himpunan sama dgn C2
  C4 filter periode (date_from/date_to): seluruh item dalam rentang, total == jumlah DB pada rentang, tanpa duplikat
  C5 ukuran halaman 25/50/100 memberi urutan gabungan identik
Hanya GET; tidak menulis data.

Pakai: TEST_API_URL=http://127.0.0.1:8034/api TEST_DATABASE_URL=mysql://.../proc_perf_itest \
       PAGING_CREDS=/root/perf/cred_parity_global.json,/root/perf/cred_parity_terbatas_divisi.json python p7_paging_completeness_test.py
"""
import json
import os
import sys
from urllib.parse import unquote, urlparse

import requests

API = os.environ.get("TEST_API_URL", "http://127.0.0.1:8034/api")
RES = {"pass": 0, "fail": 0}
LISTS = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi", "vendor-invoices": "vendor_invoices"}
DATE_KEY = {"vendor-invoices": "invoice_date"}


def check(name, cond, info=""):
    RES["pass" if cond else "fail"] += 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {str(info)[:400]}"))


def db_conn():
    url = os.environ["TEST_DATABASE_URL"]
    u = urlparse(url.replace("mariadb://", "mysql://"))
    name = u.path.lstrip("/")
    assert name.endswith("_itest"), f"menolak DB non-uji: {name}"
    import pymysql
    return pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                           database=name)


def db_docs(c, table, tenant, divisions=None):
    with c.cursor() as cur:
        cur.execute(f"SELECT doc FROM `{table}`")
        out = []
        for (doc,) in cur.fetchall():
            d = json.loads(doc)
            if d.get("tenant_id") != tenant or not d.get("id"):
                continue
            if divisions is not None and d.get("division_id") not in divisions:
                continue
            out.append(d)
        return out


def login(cred):
    S = requests.Session()
    r = S.post(f"{API}/auth/login", json=cred, timeout=60)
    r.raise_for_status()
    tok = r.json().get("token")
    if tok:
        S.headers.update({"Authorization": f"Bearer {tok}"})
    me = S.get(f"{API}/auth/me", timeout=60).json()
    return S, me


def all_pages(S, path, size=100, **qp):
    items, page, total = [], 1, None
    while True:
        q = {"page": page, "page_size": size, **qp}
        r = S.get(f"{API}/{path}", params=q, timeout=300)
        assert r.status_code == 200, (path, q, r.status_code, r.text[:200])
        body = r.json()
        total = body["total"] if total is None else total
        assert body["total"] == total, ("total berubah antar halaman", path, page, body["total"], total)
        items += body["items"]
        if page * size >= total or not body["items"]:
            break
        page += 1
    return items, total


def sort_key(v):
    if isinstance(v, (int, float)):
        return (0, v, "")
    return (1, 0, str(v))


def main():
    creds = [p for p in os.environ.get("PAGING_CREDS", "").split(",") if p]
    assert creds, "PAGING_CREDS kosong"
    c = db_conn()
    for cp in creds:
        cred = json.load(open(cp))
        S, me = login({"email": cred["email"], "password": cred["password"]})
        tenant = me.get("tenant_id")
        div = None
        dov = me.get("division_scope") or me.get("division_override") or {}
        if me.get("role") != "admin" and me.get("scope") != "global" and isinstance(dov, dict) and dov.get("mode") == "selected":
            div = set(dov.get("divisions") or [])
        who = f"{me.get('role')}{'/divisi' if div is not None else '/global'}"
        for path, table in LISTS.items():
            sc = S.get(f"{API}/{path}", params={"page": 1, "page_size": 25}, timeout=300).status_code
            if sc in (403, 404):
                check(f"[{who}] {path}: tanpa izin modul ({sc}) — dilewati", True)
                continue
            docs = db_docs(c, table, tenant, div)
            ids_db = {d["id"] for d in docs}
            items, total = all_pages(S, path)
            ids = [x.get("id") for x in items]
            check(f"[{who}] {path} C1 total == dokumen DB ({total} vs {len(ids_db)})", total == len(ids_db), (total, len(ids_db)))
            check(f"[{who}] {path} C2 gabungan halaman: jumlah == total, unik, tanpa hilang",
                  len(ids) == total and len(set(ids)) == len(ids) and set(ids) == ids_db,
                  (len(ids), total, len(set(ids)), len(ids_db - set(ids)), len(set(ids) - ids_db)))
            if div is not None:
                check(f"[{who}] {path} cakupan: seluruh item dalam divisi user", all(x.get("division_id") in div for x in items))
            for direction in ("asc", "desc"):
                s_items, s_total = all_pages(S, path, sort="no", dir=direction)
                keys = [(sort_key(x.get("no") or ""), str(x.get("no") or "")) for x in s_items if x.get("no") not in (None, "")]
                mono = keys == sorted(keys, reverse=direction == "desc")
                check(f"[{who}] {path} C3 sort no {direction}: monoton seluruh halaman, himpunan sama",
                      mono and s_total == total and {x.get("id") for x in s_items} == set(ids), (mono, s_total, total))
            dk = DATE_KEY.get(path, "date")
            dates = sorted(str(d.get(dk) or "")[:10] for d in docs if d.get(dk))
            if dates:
                lo, hi = dates[len(dates) // 4], dates[(3 * len(dates)) // 4]
                f_items, f_total = all_pages(S, path, date_from=lo, date_to=hi)
                n_db = sum(1 for d in docs if lo <= str(d.get(dk) or "")[:10] <= hi)
                inrange = all(lo <= str(x.get(dk) or "")[:10] <= hi for x in f_items)
                fids = [x.get("id") for x in f_items]
                check(f"[{who}] {path} C4 periode {lo}..{hi}: total == DB ({f_total} vs {n_db}), dalam rentang, unik",
                      f_total == n_db and inrange and len(set(fids)) == len(fids) == f_total, (f_total, n_db, inrange))
            orders = [[x.get("id") for x in all_pages(S, path, size=sz, sort="no", dir="asc")[0]] for sz in (25, 50, 100)]
            check(f"[{who}] {path} C5 ukuran halaman 25/50/100: urutan gabungan identik", orders[0] == orders[1] == orders[2],
                  [len(o) for o in orders])
    n = RES["pass"] + RES["fail"]
    print(f"\n{RES['pass']}/{n} passed")
    return 0 if RES["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
