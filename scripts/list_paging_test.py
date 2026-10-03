"""Server-side pagination list transaksi (?page=). Usage: python scripts/list_paging_test.py [EMAIL] [PASSWORD]"""
import sys

import requests

API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0] + "/api"
EMAIL = sys.argv[1] if len(sys.argv) > 1 else "rc_a6b3fbea@example.com"
PWD = sys.argv[2] if len(sys.argv) > 2 else "TestPass123!"
S = requests.Session()
S.post(f"{API}/auth/login", json={"email": EMAIL, "password": PWD}, timeout=120).raise_for_status()
ok = fail = 0


def check(name, cond, info=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""), flush=True)


def get(path, **params):
    r = S.get(f"{API}/{path}", params=params, timeout=300)
    return r.status_code, r.json()


for ep in ["mro", "ro", "po", "do", "mi", "transfers", "loans", "adjustments", "opname", "vendor-invoices", "vendor-invoices/do-billing"]:
    sc, full = get(ep)
    sc2, pg = get(ep, page=1, page_size=25)
    check(f"{ep}: tanpa page tetap array", sc == 200 and isinstance(full, list))
    check(f"{ep}: page -> {{items,total,page,page_size}}", sc2 == 200 and isinstance(pg, dict) and set(pg) >= {"items", "total", "page", "page_size"})
    check(f"{ep}: total = jumlah data tanpa page (scope sama)", pg.get("total") == len(full), f"{pg.get('total')} vs {len(full)}")
    check(f"{ep}: page_size invalid -> 25", get(ep, page=1, page_size=7)[1].get("page_size") == 25)

sc, full = get("mro")
n = len(full)
p1 = get("mro", page=1, page_size=25)[1]
check("mro: default terbaru dulu", [r["id"] for r in p1["items"]] == [r["id"] for r in sorted(full, key=lambda r: (r.get("created_at") or "", r.get("no") or ""), reverse=True)][:25])
q = get("mro", page=1, page_size=25, q="tunggal")[1]
check("mro: search backend", q["total"] == sum(1 for r in full if "tunggal" in (r.get("no") or "").lower()) and all("tunggal" in r["no"].lower() for r in q["items"]))
asc = get("mro", page=1, page_size=100, sort="no", dir="asc")[1]["items"]
check("mro: sort no asc", [r["no"] for r in asc] == sorted([r["no"] for r in asc], key=str.lower))
desc = get("mro", page=1, page_size=100, sort="no", dir="desc")[1]["items"]
check("mro: sort no desc", [r["no"] for r in desc] == list(reversed([r["no"] for r in asc])))
c = get("mro", page=1, page_size=25, counts="lifecycle_stage")[1]
cnt = c["facets"].get("count:lifecycle_stage", {})
check("mro: counts tahap = total", sum(cnt.values()) == n)
if cnt:
    st = next(iter(cnt))
    f = get("mro", page=1, page_size=100, f_lifecycle_stage=st)[1]
    check("mro: filter tahap backend", f["total"] == cnt[st] and all(r["lifecycle_stage"] == st for r in f["items"]))
check("mro: lifecycle ada di baris", all("lifecycle" in r for r in p1["items"]))
if n >= 2:
    a, b = get("mro", page=1, page_size=25)[1], get("mro", page=2, page_size=25)[1]
    check("mro: halaman di luar jangkauan dijepit ke halaman terakhir", b["page"] == max(1, -(-n // 25)))
    check("mro: page_size membatasi jumlah baris", len(a["items"]) == min(25, n))
inv = get("vendor-invoices", page=1, page_size=25, facets="supplier_name")[1]
check("invoice: facets supplier dari backend", isinstance(inv["facets"].get("supplier_name"), list))
far = get("vendor-invoices", page=1, page_size=25, date_from="2999-01-01")[1]
check("invoice: filter tanggal backend", far["total"] == 0)
print(f"\n{ok}/{ok + fail} passed")
sys.exit(1 if fail else 0)
