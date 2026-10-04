"""Tahap 3 tambahan — Info Stok per Gudang + shortcut Tambah Master (throwaway tenants, localhost)."""
import sys
import uuid

import requests

import receipt_control_test as T
from vendor_invoice_test import mk_user, PW

call, check, API = T.call, T.check, T.API


def main():
    M = T.setup()
    T.M = M
    import vendor_invoice_test as V
    V.M = M
    sc, dB = call("POST", "master/divisions", {"code": f"DB{uuid.uuid4().hex[:4]}", "name": "Divisi B"}, 200)
    call("PUT", f"master/warehouses/{M['wh']['id']}", {**M["wh"], "division_id": M["div"]["id"]}, 200)
    sc, whB = call("POST", "master/warehouses", {"code": f"WC{uuid.uuid4().hex[:4]}", "name": "Gudang Divisi B", "division_id": dB["id"], "is_active": True}, 200)
    sc, itB = call("POST", "master/items", {"code": f"IB{uuid.uuid4().hex[:4]}", "name": "Barang Divisi B", "unit": "PCS", "is_active": True, **T.item_ref(M, division_id=dB["id"])}, 200)
    po, _, _ = T.make_po(M, "supX", 25)
    call("POST", "do", T.do_body(M, po, 25, "supX"), 200)

    sc, s = call("GET", f"stock/by-warehouse/{M['item']['id']}")
    rows = {w["warehouse_id"]: w for w in s.get("warehouses") or []}
    check("stok per gudang: Gudang A = 25 (sumber item_warehouse)", sc == 200 and rows.get(M["wh"]["id"], {}).get("stock") == 25, s)
    check("stok per gudang: gudang lain tampil (Gudang B = 0)", rows.get(M["wh2"]["id"], {}).get("stock") == 0)
    check("stok per gudang: satuan ada, tanpa harga/HPP/nilai", all(w.get("unit") for w in rows.values()) and not any(k in str(s) for k in ("avg_cost", "total_value", "price", "hpp")), s)
    sc, m = call("GET", f"stock/warehouse/{M['wh']['id']}")
    check("stok satu gudang (untuk pemilih Barang): 1 panggilan, Barang = 25", sc == 200 and m.get(M["item"]["id"]) == 25, m)
    sc, m2 = call("GET", f"stock/warehouse/{M['wh2']['id']}")
    check("ganti gudang -> stok mengikuti Gudang B", sc == 200 and (m2.get(M["item"]["id"]) or 0) == 0, m2)

    mg = mk_user("manager", divs=[M["div"]["id"]])
    sc, s = mg("GET", f"stock/by-warehouse/{M['item']['id']}")
    ids = {w["warehouse_id"] for w in s.get("warehouses") or []}
    check("scope: user Divisi A tidak melihat Gudang Divisi B", sc == 200 and M["wh"]["id"] in ids and whB["id"] not in ids, s)
    check("scope: stok Gudang Divisi B -> 403", mg("GET", f"stock/warehouse/{whB['id']}")[0] == 403)
    check("scope: stok Barang Divisi B -> 403", mg("GET", f"stock/by-warehouse/{itB['id']}")[0] == 403)
    sc, lk = mg("GET", "lookup/items")
    check("scope: pencarian Barang (lookup) tanpa Barang Divisi B", sc in (200, 403) and itB["id"] not in {x.get("id") for x in (lk if isinstance(lk, list) else [])}, sc)

    other = requests.Session()
    u = uuid.uuid4().hex[:8]
    res = other.post(f"{API}/saas/register", json={"company_name": f"ST {u}", "pic_name": "QA", "email": f"st_{u}@example.com", "whatsapp": "+628123456789",
                                                   "workspace_slug": f"st-{u}", "plan_code": "starter", "password": PW, "address": "x", "terms_accepted": True}).json()
    if not res.get("token"):
        other.post(f"{API}/auth/login", json={"email": f"st_{u}@example.com", "password": PW})
    check("tenant: stok Barang tenant lain -> 404", other.get(f"{API}/stock/by-warehouse/{M['item']['id']}").status_code == 404)
    check("tenant: stok Gudang tenant lain -> 404", other.get(f"{API}/stock/warehouse/{M['wh']['id']}").status_code == 404)

    # shortcut Tambah Barang / Supplier memakai endpoint master existing
    nd = mk_user("manager", overrides={"items.create": "deny", "suppliers.create": "deny"}, divs=[M["div"]["id"]])
    sc, _ = nd("POST", "master/items", {"name": "Barang Liar", "base_uom_id": None})
    check("permission: tanpa Barang.Tambah -> create Barang 403", sc == 403, sc)
    sc, _ = nd("POST", "master/suppliers", {"name": "Supplier Liar"})
    check("permission: tanpa Supplier.Tambah -> create Supplier 403", sc == 403, sc)
    pn = f"I8-{uuid.uuid4().hex[:5]}-897-A"
    sc, nw = call("POST", "master/items", {"code": f"QK{uuid.uuid4().hex[:4]}", "name": "Fuel Filter FVZ", "part_number": pn, "brand": "Isuzu", "unit": "PCS", "is_active": True, **T.item_ref(M)})
    sc2, lk = call("GET", "lookup/items")
    hit = next((x for x in lk or [] if x.get("id") == nw.get("id")), {})
    check("Tambah Barang -> langsung tersedia di pilihan Barang (lookup)", sc == 200 and sc2 == 200 and hit.get("name") == "Fuel Filter FVZ", (sc, sc2))
    check("pilihan Barang memuat Kode, Nama, Part Number, Merk", hit.get("code") and hit.get("part_number") == pn and hit.get("brand") == "Isuzu", hit)
    sc, logs = call("GET", f"audit?entity=items&entity_id={nw.get('id')}")
    check("audit create Barang tercatat (mekanisme existing)", sc == 200 and any(x.get("action") == "create" for x in logs or []), [x.get("action") for x in logs or []])

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
