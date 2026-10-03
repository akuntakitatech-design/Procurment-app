"""Seed MRO (SPK tunggal, split, Non-SPK) pada tenant QA existing untuk uji preview SPK di MI.
Usage: python scripts/seed_mi_spk_ui.py EMAIL  (password TestPass123!)."""
import os
import sys
import uuid

import requests

API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0] + "/api"
S = requests.Session()


def call(m, p, b=None):
    r = S.request(m, f"{API}/{p}", json=b, timeout=120)
    if r.status_code >= 400:
        print("WARN", m, p, r.status_code, r.text[:200])
    return r.json() if r.content else {}


S.post(f"{API}/auth/login", json={"email": sys.argv[1], "password": "TestPass123!"}, timeout=60).raise_for_status()
u = uuid.uuid4().hex[:4]
wh = next(w for w in call("GET", "lookup/warehouses") if w["name"] == "Gudang A")
item = next(i for i in call("GET", "lookup/items") if i["name"] == "Baut M8")
spk = [call("POST", "spk", {"spk_number": f"SPK-{n}-{u}", "project_name": f"Pekerjaan {n}", "spk_value": 100000000,
                            "procurement_budget": 50000000, "status": "active"}) for n in ("A", "B")]
plans = [("tunggal", 10, [(0, 10)]), ("split", 10, [(0, 6), (1, 4)]), ("nonspk", 5, [])]
for name, qty, al in plans:
    mro = call("POST", "mro", {"no": f"MRO-{name}-{u}", "requester": "QA", "lines": [{"item_id": item["id"], "qty": qty, "warehouse_id": wh["id"], "notes": name}]})
    lid = mro["lines"][0]["id"]
    if al:
        call("PUT", f"spk-allocations/mro/line/{lid}", {"allocations": [{"spk_id": spk[i]["id"], "allocated_qty": q} for i, q in al]})
    call("POST", f"mro/{mro['id']}/submit", {})
    call("POST", f"mro/{mro['id']}/approve", {})
    print(name, mro.get("no"))
print("SPK", spk[0].get("spk_number"), spk[1].get("spk_number"))
