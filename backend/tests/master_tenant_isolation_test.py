"""Cross-tenant isolation with two REAL cookie sessions (no bearer, no tenant_id from client)."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("API_BASE") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]
API = f"{BASE}/api"
RESULTS = []
MASTERS = ["warehouses", "items", "suppliers", "divisions", "projects", "units", "item_categories",
           "uoms", "taxes", "supplier_categories", "contacts"]


def check(name, cond, info=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


class Tenant:
    def __init__(self, tag):
        self.S = requests.Session()
        u = uuid.uuid4().hex[:8]
        self.email, self.u = f"iso_{tag}_{u}@example.com", u
        r = self.S.post(f"{API}/saas/register", json={
            "company_name": f"ISO {tag} {u}", "pic_name": "QA", "email": self.email, "whatsapp": "+628123456789",
            "workspace_slug": f"iso-{tag}-{u}", "plan_code": "starter", "password": "TestPass123!",
            "address": "x", "terms_accepted": True})
        assert r.status_code == 200, r.text
        self.S.cookies.clear()
        r = self.S.post(f"{API}/auth/login", json={"email": self.email, "password": "TestPass123!"})
        assert r.status_code == 200 and self.S.cookies.get("access_token"), r.text
        assert "Authorization" not in self.S.headers
        self.me = self.S.get(f"{API}/auth/me").json()
        self.ids = {}

    def call(self, method, path, body=None):
        r = self.S.request(method, f"{API}/{path}", json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}

    def seed(self):
        u = self.u
        bodies = {
            "warehouses": {"name": f"Gudang {u}"}, "items": {"name": f"Barang {u}", "unit": "PCS"},
            "suppliers": {"name": f"Supplier {u}"}, "divisions": {"name": f"Divisi {u}"},
            "projects": {"name": f"Proyek {u}"}, "units": {"name": f"Unit {u}"},
            "item_categories": {"name": f"KatBrg {u}"}, "uoms": {"name": f"Sat{u}", "code": f"S{u[:5]}"},
            "taxes": {"name": f"Pajak {u}", "rate": 11}, "supplier_categories": {"name": f"KatSup {u}"},
            "contacts": {"name": f"Kontak {u}", "email": f"k{u}@example.com"},
        }
        for m, b in bodies.items():
            sc, d = self.call("POST", f"master/{m}", {**b, "is_active": True})
            assert sc == 200, (m, sc, d)
            self.ids[m] = d
        sc, d = self.call("POST", "spk", {"spk_number": f"SPK-{u}", "project_name": "X", "spk_value": 10, "procurement_budget": 5, "status": "active"})
        assert sc == 200, d
        self.ids["spk"] = d
        sc, d = self.call("POST", "vendor-contracts", {"supplier_id": self.ids["suppliers"]["id"], "contract_number": f"KHV-{u}",
                                                       "start_date": "2026-01-01", "end_date": "2026-12-31"})
        self.ids["vc"] = d if sc == 200 else None
        sc, d = self.call("POST", "mro", {"no": f"MRO-{u}", "division_id": self.ids["divisions"]["id"],
                                          "lines": [{"item_id": self.ids["items"]["id"], "qty": 3, "warehouse_id": self.ids["warehouses"]["id"]}]})
        assert sc == 200, d
        self.ids["mro"] = d
        self.call("POST", "item-warehouse", {"item_id": self.ids["items"]["id"], "warehouse_id": self.ids["warehouses"]["id"], "min_stock": 2, "max_stock": 9})


def attack(att, vic, tag):
    for m in MASTERS:
        rec = vic.ids[m]
        sc, lst = att.call("GET", f"master/{m}")
        check(f"{tag} list {m} hides other tenant", sc == 200 and rec["id"] not in [x.get("id") for x in lst])
        sc, lst = att.call("GET", f"master/{m}?q={rec.get('code')}")
        check(f"{tag} search {m} hides other tenant", sc == 200 and rec["id"] not in [x.get("id") for x in lst])
        sc, r = att.call("PUT", f"master/{m}/{rec['id']}", {"name": "HACKED"})
        check(f"{tag} edit {m} -> 404", sc == 404, f"{sc} {r}")
        sc, r = att.call("POST", f"master-delete-check/{m}", {"ids": [rec["id"]]})
        check(f"{tag} preflight {m} not found", sc == 200 and r[0]["ok"] is False and r[0]["reason"] == "Data tidak ditemukan", r)
        sc, r = att.call("DELETE", f"master/{m}/{rec['id']}")
        check(f"{tag} delete {m} -> 404", sc == 404, f"{sc} {r}")
        sc, r = att.call("POST", f"master-bulk-delete/{m}", {"ids": [rec["id"]]})
        check(f"{tag} bulk delete {m} rejected", sc == 409 and "Tidak ada data yang dihapus" in str(r), f"{sc} {r}")
        sc, lst = vic.call("GET", f"master/{m}")
        mine = next((x for x in lst if x.get("id") == rec["id"]), None)
        check(f"{tag} victim {m} intact", mine is not None and mine.get("name") != "HACKED" and mine.get("is_active") is not False, mine)
    spk = vic.ids["spk"]
    sc, lst = att.call("GET", "spk")
    rows = lst if isinstance(lst, list) else lst.get("rows") or lst.get("items") or []
    check(f"{tag} SPK list hides other tenant", spk["id"] not in [x.get("id") for x in rows])
    for meth, path, body in (("GET", f"spk/{spk['id']}", None), ("PUT", f"spk/{spk['id']}", {**spk, "project_name": "HACKED"}),
                             ("DELETE", f"spk/{spk['id']}", None)):
        sc, r = att.call(meth, path, body)
        check(f"{tag} SPK {meth} -> 404", sc == 404, f"{sc} {r}")
    sc, r = att.call("POST", "master-delete-check/spk", {"ids": [spk["id"]]})
    check(f"{tag} SPK preflight not found", r[0]["ok"] is False and r[0]["reason"] == "Data tidak ditemukan", r)
    sc, r = vic.call("GET", f"spk/{spk['id']}")
    check(f"{tag} victim SPK intact", sc == 200 and r.get("project_name") != "HACKED", r)
    vc = vic.ids["vc"]
    if vc:
        sc, lst = att.call("GET", "vendor-contracts")
        rows = lst if isinstance(lst, list) else lst.get("rows") or lst.get("items") or []
        check(f"{tag} Kontrak list hides other tenant", vc["id"] not in [x.get("id") for x in rows])
        for meth, path, body in (("GET", f"vendor-contracts/{vc['id']}", None), ("PUT", f"vendor-contracts/{vc['id']}", {**vc, "notes": "HACKED"}),
                                 ("DELETE", f"vendor-contracts/{vc['id']}", None)):
            sc, r = att.call(meth, path, body)
            check(f"{tag} Kontrak {meth} -> 404", sc == 404, f"{sc} {r}")
        sc, r = vic.call("GET", f"vendor-contracts/{vc['id']}")
        check(f"{tag} victim Kontrak intact", sc == 200, f"{sc}")
    iv = {"item_id": vic.ids["items"]["id"], "warehouse_id": vic.ids["warehouses"]["id"]}
    sc, r = att.call("POST", "item-warehouse", {**iv, "min_stock": 99, "max_stock": 99})
    check(f"{tag} set Min/Max with other tenant ids -> 404", sc == 404, f"{sc} {r}")
    sc, r = att.call("POST", "master-bulk-delete/item_warehouse", {"ids": [f"{iv['item_id']}|{iv['warehouse_id']}"]})
    check(f"{tag} bulk clear Min/Max other tenant rejected", sc == 409, f"{sc} {r}")
    sc, r = att.call("POST", "item-warehouse/clear-minmax", iv)
    check(f"{tag} clear Min/Max other tenant -> 404", sc == 404, f"{sc} {r}")
    sc, lst = att.call("GET", "item-warehouse")
    check(f"{tag} item-warehouse list hides other tenant", not any(x.get("item_id") == iv["item_id"] for x in lst))
    sc, lst = vic.call("GET", "item-warehouse")
    row = next((x for x in lst if x.get("item_id") == iv["item_id"]), {})
    check(f"{tag} victim Min/Max intact", float(row.get("min_stock") or 0) == 2, row)
    mro = vic.ids["mro"]
    sc, lst = att.call("GET", "mro")
    check(f"{tag} MRO list hides other tenant", mro["id"] not in [x.get("id") for x in lst])
    for meth, path, body in (("GET", f"mro/{mro['id']}", None), ("GET", f"transactions/mro/{mro['id']}/capability", None),
                             ("PUT", f"transactions/mro/{mro['id']}", {"notes": "HACKED"}),
                             ("DELETE", f"transactions/mro/{mro['id']}", None)):
        sc, r = att.call(meth, path, body)
        check(f"{tag} MRO {meth} {path.split('/')[-1]} denied", sc in (403, 404), f"{sc} {r}")
    sc, r = vic.call("GET", f"mro/{mro['id']}")
    check(f"{tag} victim MRO intact", sc == 200 and r.get("notes") != "HACKED", f"{sc}")
    vuid = vic.me["id"]
    sc, lst = att.call("GET", "users")
    check(f"{tag} users list hides other tenant", sc == 200 and vuid not in [x.get("id") for x in lst])
    sc, r = att.call("PUT", f"users/{vuid}", {"permissions": ["view"], "role": "warehouse"})
    check(f"{tag} edit other tenant user permissions -> 404", sc == 404, f"{sc} {r}")
    sc, r = att.call("DELETE", f"users/{vuid}")
    check(f"{tag} deactivate other tenant user -> 404", sc == 404, f"{sc} {r}")
    sc, r = att.call("GET", f"access/users/{vuid}")
    check(f"{tag} read other tenant user access -> 404", sc == 404, f"{sc} {r}")
    sc, r = att.call("PUT", f"access/users/{vuid}", {"overrides": {"items.delete": "deny"}, "division_override": None})
    check(f"{tag} set other tenant user override -> 404", sc == 404, f"{sc} {r}")
    sc, before = vic.call("GET", "access/roles")
    sc, r = att.call("PUT", "access/roles/manager", {"permissions": ["items.view"], "division_scope": {"mode": "all"}})
    sc2, after = vic.call("GET", "access/roles")
    check(f"{tag} role matrix change stays in own tenant", sc == 200 and before == after, f"{sc}")
    for sub in ("submit", "cancel"):
        sc, r = att.call("POST", f"mro/{mro['id']}/{sub}", {})
        check(f"{tag} MRO {sub} on other tenant doc denied", sc in (403, 404), f"{sc} {r}")
    sc, me = vic.call("GET", "auth/me")
    check(f"{tag} victim permissions intact", sc == 200 and me.get("role") == vic.me.get("role")
          and sorted(me.get("permissions") or []) == sorted(vic.me.get("permissions") or []), me.get("permissions"))


def main():
    A, B = Tenant("a"), Tenant("b")
    check("two distinct tenants via cookies", A.me.get("tenant_id") and A.me["tenant_id"] != B.me["tenant_id"])
    A.seed()
    B.seed()
    attack(B, A, "B->A")
    attack(A, B, "A->B")
    sc, r = A.call("DELETE", f"master/item_categories/{A.ids['item_categories']['id']}")
    check("own-tenant delete still works", sc == 200, f"{sc} {r}")
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
