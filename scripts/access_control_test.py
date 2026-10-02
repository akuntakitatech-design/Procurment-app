"""Tahap 2 — Hak Akses per Modul/Aksi + Cakupan Divisi E2E (throwaway tenant, localhost)."""
import sys
import uuid

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402

call, check, API = T.call, T.check, T.API


class U:
    def __init__(self, email):
        self.S = requests.Session()
        tok = self.S.post(f"{API}/auth/login", json={"email": email, "password": "TestPass123!"}).json().get("token")
        self.S.headers.update({"Authorization": f"Bearer {tok}"})

    def __call__(self, method, path, body=None):
        r = self.S.request(method, f"{API}/{path}", json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}


def mk_user(tag, role, perms=None):
    email = f"ac_{tag}_{uuid.uuid4().hex[:6]}@example.com"
    body = {"email": email, "password": "TestPass123!", "name": f"User {tag}", "role": role}
    if perms is not None:
        body["permissions"] = perms
    sc, u = call("POST", "users", body, 200)
    return u, U(email)


def set_role(role, perms, scope=None):
    sc, r = call("PUT", f"access/roles/{role}", {"permissions": sorted(perms), "division_scope": scope or {"mode": "all"}})
    assert sc == 200, r


def eff(u):
    return set(u("GET", "auth/me")[1].get("effective_permissions") or [])


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:6]
    po, mro_no, _ = T.make_po(M, "supX", 10)
    mro_a = next(x for x in call("GET", "mro")[1] if x["no"] == mro_no)
    sc, do = call("POST", "do", T.do_body(M, po, 4, "supX"), 200)

    # ---- role matrix
    base = {"items.view", "po.view", "do.view", "do.create", "mi.view", "mi.create", "mi.post", "mro.view", "mro.create"}
    set_role("warehouse", base)
    wu, W = mk_user("wh", "warehouse")
    check("T12 role inheritance -> effective == role matrix", eff(W) == base, eff(W) ^ base)
    sc, r = W("GET", "master/suppliers")
    sc2, r2 = W("GET", "lookup/suppliers")
    check("T1b no suppliers.view + DO Tambah -> full master 403, form lookup 200", sc == 403 and sc2 == 200, f"{sc} {sc2}")
    set_role("warehouse", {"items.view", "po.view"})
    sc, r = W("GET", "master/suppliers")
    check("T1 no suppliers.view -> list 403 Indonesian", sc == 403 and "tidak memiliki izin" in str(r) and "Supplier" in str(r), f"{sc} {r}")
    set_role("warehouse", base)
    sc, r = W("GET", "master/items")
    check("T2a items.view -> list ok", sc == 200)
    sc, r = W("POST", "master/items", {"name": "X", "unit": "PCS"})
    check("T2b no items.create -> 403", sc == 403 and "menambah data Barang" in str(r), f"{sc} {r}")
    sc, r = W("PUT", f"master/items/{M['item']['id']}", {"name": "HACK"})
    check("T3 no items.edit -> 403", sc == 403, f"{sc} {r}")
    for meth, path, body in (("DELETE", f"master/items/{M['item2']['id']}", None),
                             ("POST", "master-bulk-delete/items", {"ids": [M["item2"]["id"]]}),
                             ("POST", "master-delete-check/items", {"ids": [M["item2"]["id"]]})):
        sc, r = W(meth, path, body)
        check(f"T4 no items.delete {path.split('/')[0]} -> 403", sc == 403, f"{sc} {r}")
    sc, r = W("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "lines": []})
    check("T6 po.view without po.create -> 403", sc == 403 and "PO" in str(r), f"{sc} {r}")
    sc, r = W("POST", f"po/{po['id']}/email", {"to": "x@example.com"})
    sc2, r2 = W("GET", f"po/{po['id']}/email-context")
    check("T7 no po.send_email -> email + context 403", sc == 403 and sc2 == 403, f"{sc} {sc2}")
    sc, r = W("POST", "do", T.do_body(M, po, 1, "supX"))
    check("T8 do.create without do.post -> 403 (save == posting)", sc == 403 and "memposting" in str(r), f"{sc} {r}")
    sc, r = W("DELETE", f"transactions/do/{do['id']}")
    check("T11 no do.delete/do.cancel -> reversal 403", sc == 403, f"{sc} {r}")
    set_role("warehouse", base - {"mi.post"})
    sc, r = W("POST", "mi", {"warehouse_id": M["wh"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": M["wh"]["id"]}]})
    check("T9 mi.create without mi.post -> 403", sc == 403 and "memposting" in str(r), f"{sc} {r}")
    set_role("warehouse", base)
    sc, r = W("POST", "mi", {"warehouse_id": M["wh"]["id"], "division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": M["wh"]["id"]}]})
    check("T10 MI Tambah+Posting without mi.direct -> Direct blocked 403", sc == 403, f"{sc} {r}")
    sc, pulls = W("GET", "pull/mro-for-mi")
    check("T10b normal MRO->MI source picker available", sc == 200, f"{sc}")
    sc, r = W("GET", "po")
    check("T6b po.view list ok", sc == 200)
    sc, r = W("GET", "users")
    check("users.view absent -> users list 403", sc == 403, f"{sc}")
    sc, r = W("PUT", f"access/roles/warehouse", {"permissions": ["users.edit"]})
    check("no users.edit -> cannot change role matrix (self-escalation)", sc == 403, f"{sc} {r}")

    # ---- overrides
    sc, r = call("PUT", f"access/users/{wu['id']}", {"overrides": {"items.delete": "allow", "po.view": "deny"}, "division_override": None})
    e = eff(W)
    check("T13 allow override -> effective allowed", "items.delete" in e)
    check("T14 deny override -> effective denied", "po.view" not in e and W("GET", "po")[0] == 403)
    sc, r = W("DELETE", f"master/items/{M['item']['id']}")
    check("T5 Hapus allowed but stock/history -> still 409", sc == 409 and "tidak dapat dihapus" in str(r), f"{sc} {r}")
    sc, info = call("GET", f"access/users/{wu['id']}")
    check("override detail shows role/override/effective", "items.delete" not in info["role_permissions"] and info["overrides"]["items.delete"] == "allow" and "items.delete" in info["effective"])
    call("PUT", f"access/users/{wu['id']}", {"overrides": {}, "division_override": None})
    e = eff(W)
    check("T15 Ikuti Role -> back to role value", "items.delete" not in e and "po.view" in e)

    # ---- audit
    sc, a = call("GET", "audit?entity=role_permission&entity_id=warehouse")
    ra = next((x for x in a if x.get("before")), {})
    check("T16a role audit old/new/actor", ra.get("user") and "mi.post" in (ra.get("before") or {}) and ra.get("at"), ra)
    sc, a = call("GET", f"audit?entity=user_permission&entity_id={wu['id']}")
    ua = a[-1] if a else {}
    check("T16b user override audit old/new", any((x.get("after") or {}).get("items.delete") == "Izinkan" for x in a)
          and any((x.get("after") or {}).get("items.delete") == "Ikuti Role" for x in a), a[:2])
    call("PUT", f"users/{wu['id']}", {"role": "manager"})
    sc, a = call("GET", f"audit?entity=user_role&entity_id={wu['id']}")
    check("T16c role change audit before/after", a and a[0]["before"]["role"] == "warehouse" and a[0]["after"]["role"] == "manager", a)
    sc, r = W("PUT", f"users/{wu['id']}", {"role": "admin"})
    check("non-admin cannot grant admin", sc == 403, f"{sc}")

    # ---- legacy regression (no explicit overrides)
    pu, P = mk_user("pur", "purchasing")
    e = eff(P)
    check("T18a legacy purchasing keeps PO create/post/print/email", {"po.create", "po.post", "po.print", "po.send_email", "po.view"} <= e, e)
    check("T18b legacy purchasing gains no delete / user admin", not any(k.endswith(".delete") for k in e) and "users.edit" not in e)
    lu, L = mk_user("leg", "manager", ["view", "create", "direct_mi"])
    e = eff(L)
    check("T18c legacy custom list preserved as derived override", "mi.direct" in e and "items.create" in e and "items.edit" not in e, e)
    check("T18d legacy warehouse no delete escalation", not any(k.endswith(".delete") or k.endswith(".cancel") for k in e))

    for x in (wu, pu, lu):
        call("DELETE", f"users/{x['id']}", None, 200)  # free tenant user quota

    # ---- division scope
    sc, divB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)
    sc, whB = call("POST", "master/warehouses", {"code": f"WHB{u}", "name": "Gudang B", "division_id": divB["id"]}, 200)
    sc, itB = call("POST", "master/items", {"code": f"IB{u}", "name": "Barang B", "unit": "PCS", "division_id": divB["id"]}, 200)
    sc, mroB = call("POST", "mro", {"no": f"MRO-B{u}", "division_id": divB["id"], "submitted": True,
                                    "lines": [{"item_id": M["item"]["id"], "qty": 3, "warehouse_id": M["wh"]["id"]}]}, 200)
    call("POST", f"mro/{mroB['id']}/submit", {})
    sc, roB = call("POST", "ro", {"division_id": divB["id"], "submitted": True, "lines": [{"item_id": M["item"]["id"], "qty": 3,
                   "warehouse_id": M["wh"]["id"], "sources": [{"mro_id": mroB["id"], "line_id": mroB["lines"][0]["id"], "qty": 3}]}]}, 200)
    call("POST", f"ro/{roB['id']}/submit", {})
    sc, poAB = call("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "lines": [
        {"item_id": M["item"]["id"], "qty": 3, "price": 1000, "warehouse_id": M["wh"]["id"],
         "sources": [{"ro_id": roB["id"], "line_id": roB["lines"][0]["id"], "qty": 3}]}]}, 200)
    allv = {f"{m}.view" for m in ("mro", "ro", "po", "do", "mi", "items", "warehouses", "transfer", "adjustment")} | {"mro.edit", "mro.create", "items.edit", "warehouses.edit", "po.create", "mro.delete"}
    set_role("manager", allv)
    users = {}
    for tag, divs in (("A", [M["div"]["id"]]), ("B", [divB["id"]]), ("AB", [M["div"]["id"], divB["id"]])):
        du, D = mk_user(f"div{tag}", "manager")
        call("PUT", f"access/users/{du['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": divs}}, 200)
        users[tag] = D
    A_, B_, AB = users["A"], users["B"], users["AB"]
    ids = lambda u_, p: {x["id"] for x in (u_("GET", p)[1] or [])}  # noqa: E731
    check("DV1 A sees own MRO, not B", mro_a["id"] in ids(A_, "mro") and mroB["id"] not in ids(A_, "mro"))
    check("DV2 B sees own MRO, not A", mroB["id"] in ids(B_, "mro") and mro_a["id"] not in ids(B_, "mro"))
    for tag, us, other in (("A->B", A_, mroB), ("B->A", B_, mro_a)):
        sc, _ = us("GET", f"mro/{other['id']}")
        sc2, _ = us("PUT", f"transactions/mro/{other['id']}", {"notes": "x"})
        sc3, _ = us("DELETE", f"transactions/mro/{other['id']}")
        sc4, _ = us("POST", f"mro/{other['id']}/cancel", {})
        check(f"DV3 {tag} detail/edit/delete/cancel blocked", all(s in (403, 404) for s in (sc, sc2, sc3, sc4)), (sc, sc2, sc3, sc4))
    sc, r = A_("POST", "mro", {"division_id": divB["id"], "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": M["wh"]["id"]}]})
    check("DV4 A cannot create MRO into Divisi B", sc == 403, f"{sc} {r}")
    check("DV5 multi-division PO hidden from A-only", poAB["id"] not in ids(A_, "po") and A_("GET", f"po/{poAB['id']}")[0] == 403)
    check("DV6 multi-division PO hidden from B-only", poAB["id"] not in ids(B_, "po") and B_("GET", f"po/{poAB['id']}")[0] == 403)
    check("DV7 A+B user sees multi-division PO", poAB["id"] in ids(AB, "po") and AB("GET", f"po/{poAB['id']}")[0] == 200)
    check("DV8 master Barang/Gudang Divisi B hidden from A (list/dropdown)", itB["id"] not in ids(A_, "master/items?active_only=true")
          and whB["id"] not in ids(A_, "master/warehouses") and whB["id"] in ids(B_, "master/warehouses"))
    sc, r = A_("PUT", f"master/warehouses/{whB['id']}", {"name": "HACK"})
    check("DV9 A cannot edit Gudang Divisi B", sc == 403, f"{sc} {r}")
    sc, r = A_("PUT", f"master/items/{M['item2']['id']}", {**M["item2"], "division_id": divB["id"]})
    check("DV10 A cannot move Barang into Divisi B", sc == 403, f"{sc} {r}")
    sc, rows = A_("GET", "pull/ro-for-po")
    check("DV11 source picker hides Divisi B RO", sc == 200 and roB["id"] not in {x.get("ro_id") for x in rows})
    sc, rows = A_("GET", f"search?q=MRO-B{u}")
    check("DV12 global search hides Divisi B", sc == 200 and mroB["id"] not in {x.get("id") for x in rows}, rows)
    sc, r = A_("POST", "master-delete-check/warehouses", {"ids": [whB["id"]]})
    check("DV13 bulk/preflight on Divisi B data blocked", sc == 403, f"{sc}")
    sc, r = call("GET", f"po/{poAB['id']}")
    check("DV14 admin (Semua Divisi) sees all", sc == 200)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
