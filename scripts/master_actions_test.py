"""Master Data Tahap 1 E2E on throwaway tenants: dependency protection, preflight, all-or-nothing bulk delete,
permission (403), audit trail. Single tenant per run; cross-tenant covered by backend/tests/master_tenant_isolation_test.py."""
import sys
import uuid

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402

call, check, API = T.call, T.check, T.API


def audit(entity, rid):
    sc, rows = call("GET", f"audit?entity={entity}&entity_id={rid}")
    return rows if sc == 200 else []


def as_user(perms, u):
    email = f"perm_{u}@example.com"
    call("POST", "users", {"email": email, "password": "TestPass123!", "name": "Terbatas", "role": "warehouse",
                           "permissions": perms, "scope": "global"}, 200)
    s = requests.Session()
    tok = s.post(f"{API}/auth/login", json={"email": email, "password": "TestPass123!"}).json().get("token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:6]
    me = call("GET", "auth/me")[1]
    sc, cat = call("POST", "master/item_categories", {"code": f"KC{u}", "name": "Kategori Kosong"}, 200)
    sc, pre = call("POST", "master-delete-check/item_categories", {"ids": [cat["id"]]})
    check("T1 preflight unused ok", sc == 200 and pre[0]["ok"] is True, pre)
    sc, r = call("PUT", f"master/item_categories/{cat['id']}", {**cat, "name": "Kategori Kosong 2"})
    check("T1 edit unused", sc == 200 and r.get("name") == "Kategori Kosong 2", f"{sc} {r}")
    a = audit("item_categories", cat["id"])
    ed = next((x for x in a if x["action"] == "edit"), {})
    check("A1 edit audit before/after + user", ed.get("before", {}).get("name") == "Kategori Kosong" and ed.get("after", {}).get("name") == "Kategori Kosong 2" and ed.get("user") == me["email"] and ed.get("at"), ed)
    sc, r = call("DELETE", f"master/item_categories/{cat['id']}")
    check("T1 delete unused", sc == 200, f"{sc} {r}")
    a = audit("item_categories", cat["id"])
    dl = next((x for x in a if x["action"] == "delete"), {})
    check("A2 delete audit entity/code/user/time/before", dl.get("doc_no") == f"KC{u}" and dl.get("user") == me["email"] and dl.get("at") and dl.get("before", {}).get("id") == cat["id"] and "Kategori Barang" in (dl.get("reason") or ""), dl)

    sc, cat2 = call("POST", "master/item_categories", {"code": f"KD{u}", "name": "Kategori Dipakai"}, 200)
    sc, uom = call("POST", "master/uoms", {"code": f"U{u}", "name": f"Sat{u}", "symbol": "s"}, 200)
    sc, tax = call("POST", "master/taxes", {"code": f"TX{u}", "name": f"PPN {u}", "rate": 11}, 200)
    sc, scat = call("POST", "master/supplier_categories", {"code": f"SC{u}", "name": f"KatSup {u}"}, 200)
    call("POST", "master/items", {"code": f"IC{u}", "name": "Barang Berkategori", "unit": "PCS", "category_id": cat2["id"], "base_uom_id": uom["id"], "is_active": True}, 200)
    call("POST", "master/suppliers", {"code": f"SP{u}", "name": "Supplier Berpajak", "default_tax_id": tax["id"], "supplier_category_id": scat["id"]}, 200)
    sc, r = call("DELETE", f"master/item_categories/{cat2['id']}")
    check("T5 category with items blocked", sc == 409 and "1 barang" in str(r), f"{sc} {r}")
    for coll, rec in (("uoms", uom), ("taxes", tax), ("supplier_categories", scat)):
        sc, r = call("DELETE", f"master/{coll}/{rec['id']}")
        check(f"T5 used {coll} blocked 409 (Indonesian)", sc == 409 and "tidak dapat dihapus" in str(r), f"{sc} {r}")

    sc, e1 = call("POST", "master/item_categories", {"code": f"KE{u}", "name": "Kosong A"}, 200)
    sc, e2 = call("POST", "master/item_categories", {"code": f"KF{u}", "name": "Kosong B"}, 200)
    ids = [e1["id"], e2["id"], cat2["id"]]
    sc, pre = call("POST", "master-delete-check/item_categories", {"ids": ids})
    check("B1 bulk preflight lists ok/blocked + reason", [p["ok"] for p in pre] == [True, True, False] and "barang" in pre[2]["reason"], pre)
    sc, r = call("POST", "master-bulk-delete/item_categories", {"ids": ids})
    check("B2 bulk with blocked rejected 409, nothing deleted", sc == 409 and "Tidak ada data yang dihapus" in str(r), f"{sc} {r}")
    sc, lst = call("GET", "master/item_categories")
    check("B3 no silent partial delete", {e1["id"], e2["id"], cat2["id"]} <= {x["id"] for x in lst})
    sc, r = call("POST", "master-bulk-delete/item_categories", {"ids": ids[:2]})
    sc2, lst = call("GET", "master/item_categories")
    check("B4 bulk of valid only deleted", sc == 200 and r.get("deleted") == 2 and not ({e1["id"], e2["id"]} & {x["id"] for x in lst}), f"{sc} {r}")
    check("B5 bulk delete audited per record", all(any(x["action"] == "delete" for x in audit("item_categories", i)) for i in ids[:2]))

    po, _, _ = T.make_po(M, "supX", 10)
    for key, coll in (("item", "items"), ("supX", "suppliers"), ("pa", "projects"), ("div", "divisions")):
        sc, r = call("DELETE", f"master/{coll}/{M[key]['id']}")
        check(f"T2 used {coll} blocked 409", sc == 409 and "tidak dapat dihapus" in str(r), f"{sc} {r}")
    call("POST", "do", T.do_body(M, po, 4, "supX"), 200)
    sc, iw0 = call("GET", "item-warehouse")
    pool = next((x for x in iw0 if x.get("item_id") == M["item"]["id"] and x.get("warehouse_id") == M["wh"]["id"]), {})
    sc, r = call("DELETE", f"master/items/{M['item']['id']}")
    check("T3 item with stock blocked", sc == 409, f"{sc} {r}")
    sc, r = call("DELETE", f"master/warehouses/{M['wh']['id']}")
    check("T4 warehouse with stock blocked", sc == 409 and "saldo stok" in str(r), f"{sc} {r}")
    sc, r = call("DELETE", f"transactions/po/{po['id']}")
    check("T16 PO with DO cannot be deleted even by admin", sc in (400, 409), f"{sc} {r}")
    sc, pre = call("POST", "master-delete-check/warehouses", {"ids": [M["wh"]["id"], M["wh2"]["id"]]})
    check("T7 preflight distinguishes ok/blocked", sc == 200 and [p["ok"] for p in pre] == [False, True], pre)
    sc, r = call("POST", "master-bulk-delete/warehouses", {"ids": [M["wh"]["id"], M["wh2"]["id"]]})
    check("T7b bulk warehouses with stock rejected", sc == 409, f"{sc} {r}")

    key = f"{M['item']['id']}|{M['wh']['id']}"
    call("POST", "item-warehouse", {"item_id": M["item"]["id"], "warehouse_id": M["wh"]["id"], "min_stock": 2, "max_stock": 20}, 200)
    check("MM1 Min/Max edit audited", any(x["action"] == "edit" and x["after"].get("max_stock") == 20 for x in audit("stok_min_max", key)))
    sc, r = call("POST", "item-warehouse", {"item_id": "tidak-ada", "warehouse_id": M["wh"]["id"], "min_stock": 1})
    check("MM2 Min/Max for unknown item -> 404", sc == 404, f"{sc} {r}")
    sc, pre = call("POST", "master-delete-check/item_warehouse", {"ids": [key]})
    check("MM3 Min/Max preflight ok", pre[0]["ok"] is True and "Baut" in pre[0]["label"], pre)
    sc, r = call("POST", "master-bulk-delete/item_warehouse", {"ids": [key]})
    sc2, iw1 = call("GET", "item-warehouse")
    pool1 = next((x for x in iw1 if x.get("item_id") == M["item"]["id"] and x.get("warehouse_id") == M["wh"]["id"]), {})
    check("MM4 Stok Min/Max cleared, stock unchanged", sc == 200 and float(pool1.get("min_stock") or 0) == 0 and pool1.get("current_stock") == pool.get("current_stock"), (r, pool, pool1))
    check("MM5 Min/Max delete audited", any(x["action"] == "delete" for x in audit("stok_min_max", key)))
    sc, pre = call("POST", "master-delete-check/item_warehouse", {"ids": [key]})
    check("MM6 empty Min/Max blocked with reason", pre[0]["ok"] is False and "Min/Max" in pre[0]["reason"], pre)

    sc, spk = call("POST", "spk", {"spk_number": f"SPK-U{u}", "project_name": "Kosong", "spk_value": 10, "procurement_budget": 5, "status": "active"}, 200)
    sc, r = call("POST", "master-bulk-delete/spk", {"ids": [spk["id"]]})
    check("S1 SPK unused deleted", sc == 200, f"{sc} {r}")
    check("S2 SPK delete audited", any(x["action"] == "delete" for x in audit("spk", spk["id"])))
    sc, spk2 = call("POST", "spk", {"spk_number": f"SPK-D{u}", "project_name": "Dipakai", "spk_value": 10, "procurement_budget": 5, "status": "active"}, 200)
    sc, mro = call("POST", "mro", {"no": f"MRO-S{u}", "division_id": M["div"]["id"], "lines": [{"item_id": M["item2"]["id"], "qty": 5, "warehouse_id": M["wh"]["id"]}]}, 200)
    call("PUT", f"spk-allocations/mro/line/{mro['lines'][0]['id']}", {"allocations": [{"spk_id": spk2["id"], "allocated_qty": 2}]}, 200)
    sc, r = call("DELETE", f"spk/{spk2['id']}")
    check("S3 SPK used by allocation blocked", sc == 409 and "alokasi SPK" in str(r), f"{sc} {r}")

    sc, vc = call("POST", "vendor-contracts", {"supplier_id": M["supY"]["id"], "contract_number": f"KHV-{u}", "start_date": "2026-01-01", "end_date": "2026-12-31"}, 200)
    sc, pre = call("POST", "master-delete-check/vendor_contracts", {"ids": [vc["id"]]})
    check("V1 Kontrak preflight ok", pre[0]["ok"] is True, pre)
    sc, r = call("DELETE", f"master/suppliers/{M['supY']['id']}")
    check("V2 supplier with Kontrak blocked", sc == 409 and "Kontrak Harga Vendor" in str(r), f"{sc} {r}")
    sc, r = call("POST", "master-bulk-delete/vendor_contracts", {"ids": [vc["id"]]})
    check("V3 Kontrak unused deleted + audited", sc == 200 and any(x["action"] == "delete" for x in audit("vendor_contracts", vc["id"])), f"{sc} {r}")

    sc, unit = call("POST", "master/units", {"code": f"UN{u}", "name": "Unit Kosong"}, 200)
    sc, ct = call("POST", "master/contacts", {"code": f"CT{u}", "name": "Kontak Kosong"}, 200)
    sc, r = call("POST", "master-bulk-delete/units", {"ids": [unit["id"]]})
    check("U1 Unit/Aset unused deleted", sc == 200, f"{sc} {r}")
    sc, r = call("POST", "master-bulk-delete/contacts", {"ids": [ct["id"]]})
    check("C1 Kontak Internal unused deleted", sc == 200, f"{sc} {r}")

    ro = as_user(["view"], u)
    sc_ = lambda r: (r.status_code, r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else "")
    st, d = sc_(ro.put(f"{API}/master/divisions/{M['div']['id']}", json={"name": "X"}))
    check("P1 edit without izin -> 403 Indonesian", st == 403 and "tidak memiliki izin" in str(d), f"{st} {d}")
    st, d = sc_(ro.delete(f"{API}/master/warehouses/{M['wh2']['id']}"))
    check("P2 delete without izin -> 403", st == 403 and "menghapus" in str(d), f"{st} {d}")
    st, d = sc_(ro.post(f"{API}/master-bulk-delete/warehouses", json={"ids": [M["wh2"]["id"]]}))
    check("P3 bulk delete without izin -> 403", st == 403, f"{st} {d}")
    st, d = sc_(ro.post(f"{API}/master-delete-check/warehouses", json={"ids": [M["wh2"]["id"]]}))
    check("P4 preflight without izin -> 403", st == 403, f"{st} {d}")
    st, d = sc_(ro.post(f"{API}/item-warehouse/clear-minmax", json={"item_id": M["item"]["id"], "warehouse_id": M["wh"]["id"]}))
    check("P5 clear Min/Max without izin -> 403", st == 403, f"{st} {d}")
    st, d = sc_(ro.delete(f"{API}/spk/{spk2['id']}"))
    check("P6 SPK delete without izin -> 403", st == 403, f"{st} {d}")
    sc, lst = call("GET", "master/warehouses")
    check("P7 record intact after denied delete", any(x["id"] == M["wh2"]["id"] and x.get("is_active") is not False for x in lst))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
