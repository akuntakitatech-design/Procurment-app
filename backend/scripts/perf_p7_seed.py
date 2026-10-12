"""P7 — seed basis dataset parity/benchmark lewat API NYATA (MRO -> RO -> PO -> DO -> MI) untuk satu tenant `perf_*`.

HANYA untuk backend uji terisolasi dengan DB *_itest (mis. backend port 8031 + proc_perf_itest). Setelah seed:
  P7_DB=proc_perf_itest P7_SRC_DB=proc_perf_itest python scripts/perf_p7_dataset.py clone K   # gandakan transaksi
  P7_DB=proc_perf_itest P7_SRC_DB=proc_perf_itest python scripts/perf_p7_dataset.py extra N   # SPK/kontrak/invoice/pinjaman
Pakai: TEST_API_URL=http://127.0.0.1:8031/api python scripts/perf_p7_seed.py --flows 40 --out /root/perf/cred_parity.json
Menulis kredensial (global + 2 user terbatas) ke --out (chmod 600, di luar repo). Tidak mencetak password.
"""
import argparse
import json
import os
import secrets
import sys
import uuid

import requests

ap = argparse.ArgumentParser()
ap.add_argument("--flows", type=int, default=40)
ap.add_argument("--out", default="/root/perf/cred_parity.json")
ap.add_argument("--login-email", default="", help="pakai akun admin yang sudah ada (mis. sandbox) alih-alih registrasi tenant baru")
ap.add_argument("--login-password-file", default="", help="file berisi password akun --login-email (tidak dicetak)")
ap.add_argument("--allow-preview-sandbox", action="store_true",
                help="izinkan backend preview :8001 HANYA bila /app/backend/.env menunjuk DB lokal proc_sandbox")
a = ap.parse_args()
API = os.environ.get("TEST_API_URL", "").rstrip("/")
if not API:
    sys.exit("TEST_API_URL wajib diisi")
if ":8001" in API:
    envtxt = open("/app/backend/.env").read() if os.path.exists("/app/backend/.env") else ""
    if not (a.allow_preview_sandbox and "@127.0.0.1:3306/proc_sandbox" in envtxt):
        sys.exit("menolak backend preview :8001 (bukan backend uji terisolasi / bukan sandbox lokal)")
S = requests.Session()


def call(method, path, body=None, expect=200, sess=None):
    r = (sess or S).request(method, f"{API}/{path}", json=body, timeout=120)
    if expect is not None and r.status_code != expect:
        raise SystemExit(f"{method} {path} -> {r.status_code} {r.text[:300]}")
    return r.json() if r.content else {}


u = uuid.uuid4().hex[:6]
if a.login_email:
    email, PW = a.login_email, open(a.login_password_file).read().strip()
    res = {"token": call("POST", "auth/login", {"email": email, "password": PW})["token"]}
else:
    PW = "Perf-" + secrets.token_urlsafe(12)
    email = f"perf_{u}@example.com"
    res = call("POST", "saas/register", {"company_name": f"QA PERF {u}", "pic_name": "QA", "email": email, "whatsapp": "+628123456789",
                                     "workspace_slug": f"perf-{u}", "plan_code": "starter", "password": PW, "address": "x",
                                     "terms_accepted": True})
tok = res.get("token") or call("POST", "auth/login", {"email": email, "password": PW})["token"]
S.headers["Authorization"] = f"Bearer {tok}"
M = {}
for key, coll, body in [("wh", "warehouses", {"code": f"WA{u}", "name": "Gudang Utama", "is_active": True}),
                        ("wh2", "warehouses", {"code": f"WB{u}", "name": "Gudang Proyek", "is_active": True}),
                        ("div", "divisions", {"code": f"DV{u}", "name": "Divisi Teknik"}),
                        ("div2", "divisions", {"code": f"DW{u}", "name": "Divisi Produksi"}),
                        ("cat", "item_categories", {"code": f"KC{u}", "name": "Kategori Umum"}),
                        ("uom", "uoms", {"code": f"PCS{u}", "name": "Pieces"}),
                        ("scat", "supplier_categories", {"code": f"KS{u}", "name": "Supplier Umum"})]:
    M[key] = call("POST", f"master/{coll}", body)
items, sups, projs = [], [], []
for i in range(6):
    div = M["div"] if i % 2 == 0 else M["div2"]
    items.append(call("POST", "master/items", {"code": f"IT{u}{i}", "name": f"Barang {i}", "unit": "PCS", "is_active": True,
                                               "category_id": M["cat"]["id"], "division_id": div["id"], "base_uom_id": M["uom"]["id"]}))
for i in range(3):
    sups.append(call("POST", "master/suppliers", {"code": f"SP{u}{i}", "name": f"Supplier {i}", "supplier_category_id": M["scat"]["id"]}))
    projs.append(call("POST", "master/projects", {"code": f"PJ{u}{i}", "name": f"Project {i}"}))

for n in range(a.flows):
    div = M["div"] if n % 2 == 0 else M["div2"]
    item, sup, prj = items[n % len(items)], sups[n % len(sups)], projs[n % len(projs)]
    wh = M["wh"] if n % 3 else M["wh2"]
    qty = 5 + n % 7
    date = (__import__("datetime").date(2026, 1, 1) + __import__("datetime").timedelta(days=n * 4)).isoformat()  # monoton (guard posting mundur)
    mro = call("POST", "mro", {"no": f"MRO-P{u}-{n:04d}", "date": date, "division_id": div["id"], "requester": "Budi", "submitted": True,
                               "lines": [{"item_id": item["id"], "qty": qty, "warehouse_id": wh["id"], "project_id": prj["id"], "notes": "perf"}]})
    call("POST", f"mro/{mro['id']}/submit", {}, expect=None)
    ml = mro["lines"][0]
    ro = call("POST", "ro", {"date": date, "division_id": div["id"], "submitted": True,
                             "lines": [{"item_id": item["id"], "qty": qty, "warehouse_id": wh["id"], "project_id": prj["id"], "notes": "perf",
                                        "sources": [{"mro_id": mro["id"], "line_id": ml["id"], "qty": qty}]}]})
    call("POST", f"ro/{ro['id']}/submit", {}, expect=None)
    if n % 10 == 9:
        continue  # sebagian berhenti di RO (outstanding)
    po = call("POST", "po", {"date": date, "supplier_id": sup["id"], "division_id": div["id"],
                             "final_discount_type": "percent" if n % 4 == 0 else None, "final_discount_value": 2 if n % 4 == 0 else None,
                             "lines": [{"item_id": item["id"], "qty": qty, "uom_id": M["uom"]["id"], "price": 1000 + 137 * n,
                                        "discount": 0, "tax": 11 if n % 2 else 0, "warehouse_id": wh["id"], "project_id": prj["id"],
                                        "notes": "perf", "price_change_reason": "perf",
                                        "sources": [{"ro_id": ro["id"], "line_id": ro["lines"][0]["id"], "qty": qty}]}]})
    call("POST", f"po/{po['id']}/submit", {}, expect=None)
    d = call("GET", f"po/{po['id']}")
    if d.get("status") != "Approved":
        call("POST", f"po/{po['id']}/approve", {}, expect=None)
        d = call("GET", f"po/{po['id']}")
    if n % 10 == 8:
        continue  # PO approved belum diterima
    pl = d["lines"][0]
    recv = qty if n % 5 else qty - 2  # sebagian parsial
    call("POST", "do", {"date": date, "supplier_id": sup["id"], "supplier_dn": f"SJ-{u}-{n}", "default_warehouse_id": wh["id"],
                        "lines": [{"po_id": po["id"], "po_line_id": pl["id"], "item_id": item["id"], "qty": recv, "uom_id": pl.get("uom_id"),
                                   "warehouse_id": wh["id"], "project_id": prj["id"], "condition": "Baik", "exception_qty": 0,
                                   "sources": [{"po_id": po["id"], "line_id": pl["id"], "qty": recv}]}]})
    if n % 3 == 0:
        call("POST", "mi", {"date": date, "division_id": div["id"], "default_warehouse_id": wh["id"], "receiver": "Perf",
                            "department": "Workshop", "source_type": "MRO",
                            "lines": [{"mro_id": mro["id"], "mro_line_id": ml["id"], "item_id": item["id"], "qty": min(recv, 3),
                                       "warehouse_id": wh["id"]}]}, expect=None)
    print(f"flow {n + 1}/{a.flows}", flush=True)


def mk_user(role, overrides=None, divs=None):
    em = f"perf_{role}_{uuid.uuid4().hex[:5]}@example.com"
    pw = "Perf-" + secrets.token_urlsafe(12)
    usr = call("POST", "users", {"email": em, "password": pw, "name": f"Perf {role}", "role": role})
    body = {"overrides": overrides or {}}
    if divs:
        body["division_override"] = {"mode": "selected", "divisions": divs}
    call("PUT", f"access/users/{usr['id']}", body)
    return {"email": em, "password": pw}


creds = {"global": {"email": email, "password": PW},
         "terbatas_divisi": mk_user("warehouse", divs=[M["div"]["id"]]),
         "tanpa_harga": mk_user("purchasing", overrides={"view_purchase_price": "deny"})}
os.makedirs(os.path.dirname(a.out), exist_ok=True)
for k, v in creds.items():
    p = a.out.replace(".json", f"_{k}.json")
    with open(p, "w") as f:
        json.dump(v, f)
    os.chmod(p, 0o600)
print(f"selesai: {a.flows} alur; kredensial -> {a.out.replace('.json', '_*.json')} (tidak dicetak)")
