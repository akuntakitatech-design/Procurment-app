"""Seed a throwaway tenant for UI QA of DO/PO receipt control + global list UX.
Usage: python /app/scripts/seed_receipt_ui.py  (prints login credentials)."""
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402

call = T.call


def main():
    u = uuid.uuid4().hex[:6]
    email = f"ui_rc_{u}@example.com"
    sc, res = call("POST", "saas/register", {"company_name": f"UI RC {u}", "pic_name": "QA UI", "email": email,
                                             "whatsapp": "+628123456789", "workspace_slug": f"ui-rc-{u}", "plan_code": "starter",
                                             "password": "TestPass123!", "address": "x", "terms_accepted": True}, 200)
    tok = res.get("token") or call("POST", "auth/login", {"email": email, "password": "TestPass123!"}, 200)[1].get("token")
    T.S.headers.update({"Authorization": f"Bearer {tok}"})
    M = {}
    for key, coll, body in [
        ("wh", "warehouses", {"code": f"WA{u}", "name": "Gudang A", "is_active": True}),
        ("wh2", "warehouses", {"code": f"WB{u}", "name": "Gudang B", "is_active": True}),
        ("item", "items", {"code": f"BT{u}", "name": "Baut M8", "unit": "PCS", "is_active": True}),
        ("item2", "items", {"code": f"MR{u}", "name": "Mur M8", "unit": "PCS", "is_active": True}),
        ("supX", "suppliers", {"code": f"SX{u}", "name": "Supplier X", "email": "x@example.com"}),
        ("supY", "suppliers", {"code": f"SY{u}", "name": "Supplier Y"}),
        ("div", "divisions", {"code": f"DV{u}", "name": "Divisi Teknik"}),
        ("pa", "projects", {"code": f"PA{u}", "name": "Project A"}),
        ("pb", "projects", {"code": f"PB{u}", "name": "Project B"}),
    ]:
        sc, M[key] = call("POST", f"master/{coll}", body, 200)
    spks = []
    for n in ("SPK-001", "SPK-002"):
        sc, s = call("POST", "spk", {"spk_number": f"{n}-{u}", "project_name": f"Pekerjaan {n}", "spk_value": 100000000,
                                     "procurement_budget": 50000000, "status": "active"}, 200)
        spks.append(s)
    ro_lines = []
    mro_nos = []
    for idx, (proj, item) in enumerate((("pa", "item"), ("pb", "item2"))):
        no = f"MRO-{u}-{idx + 1}"
        mro_nos.append(no)
        sc, mro = call("POST", "mro", {"no": no, "division_id": M["div"]["id"], "requester": "Budi" if idx == 0 else "Sari",
                                       "lines": [{"item_id": M[item]["id"], "qty": 10, "warehouse_id": M["wh" if idx == 0 else "wh2"]["id"],
                                                  "project_id": M[proj]["id"], "notes": f"kebutuhan {idx + 1}"}]}, 200)
        ml = mro["lines"][0]
        call("PUT", f"spk-allocations/mro/line/{ml['id']}", {"allocations": [{"spk_id": spks[idx]["id"], "allocated_qty": 6}]}, 200)
        call("POST", f"mro/{mro['id']}/submit", {})
        sc, ro = call("POST", "ro", {"division_id": M["div"]["id"], "submitted": True,
                                     "lines": [{"item_id": M[item]["id"], "qty": 10, "warehouse_id": ml.get("warehouse_id"),
                                                "project_id": M[proj]["id"], "notes": f"kebutuhan {idx + 1}",
                                                "sources": [{"mro_id": mro["id"], "line_id": ml["id"], "qty": 10}]}]}, 200)
        call("POST", f"ro/{ro['id']}/submit", {})
        ro_lines.append((ro, ro["lines"][0], item, proj))
    sc, po = call("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "lines": [
        {"item_id": M[item]["id"], "qty": 10, "price": 1000, "warehouse_id": rl.get("warehouse_id"), "project_id": M[proj]["id"],
         "notes": rl.get("notes"), "sources": [{"ro_id": ro["id"], "line_id": rl["id"], "qty": 10}]} for ro, rl, item, proj in ro_lines]}, 200)
    call("POST", f"po/{po['id']}/submit", {})
    call("POST", f"po/{po['id']}/approve", {})
    po2, _, _ = T.make_po(M, "supX", 10)
    po3, _, _ = T.make_po(M, "supY", 5, project="pb")
    call("POST", "do", T.do_body(M, po2, 8, "supX"), 200)
    print(f"EMAIL={email}\nPASSWORD=TestPass123!\nMULTI_PO={po.get('no')} MROS={','.join(mro_nos)} SPK={spks[0].get('spk_number')},{spks[1].get('spk_number')}"
          f"\nPARTIAL_PO={po2.get('no')} (8/10 received, Supplier X)\nOTHER_SUPPLIER_PO={po3.get('no')} (Supplier Y)")


if __name__ == "__main__":
    main()
