"""Seed a throwaway tenant for Master Data UI QA. Prints login email (password TestPass123!)."""
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402

call = T.call


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:4].upper()
    for i, n in enumerate(["Kosong Satu", "Kosong Dua", "Kosong Tiga"]):
        call("POST", "master/item_categories", {"code": f"KK{i}{u}", "name": n}, 200)
    sc, used = call("POST", "master/item_categories", {"code": f"KD{u}", "name": "Kategori Dipakai"}, 200)
    call("PUT", f"master/items/{M['item2']['id']}", {**M["item2"], "category_id": used["id"]}, 200)
    po, _, _ = T.make_po(M, "supX", 10)
    call("POST", "do", T.do_body(M, po, 4, "supX"), 200)
    call("POST", "item-warehouse", {"item_id": M["item"]["id"], "warehouse_id": M["wh"]["id"], "min_stock": 2, "max_stock": 20}, 200)
    call("POST", "spk", {"spk_number": f"SPK-QA{u}", "project_name": "SPK Kosong", "spk_value": 10, "procurement_budget": 5, "status": "active"}, 200)
    me = call("GET", "auth/me")[1]
    print("EMAIL", me["email"])


if __name__ == "__main__":
    main()
