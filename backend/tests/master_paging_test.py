"""Server-side pagination 14 Master Data: kontrak API, search/filter/sort backend, kompatibilitas lama,
permission, cakupan divisi, tenant isolation, Hapus Massal (tenant QA sementara)."""
import sys
import uuid

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402

call, check, API = T.call, T.check, T.API
MASTERS = ["items", "item_categories", "uoms", "taxes", "supplier_categories", "warehouses", "projects", "units",
           "suppliers", "divisions", "contacts"]


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


def page(path, caller=call):
    sc, r = caller("GET", path)
    return sc, (r if isinstance(r, dict) else {})


def codes(r):
    return [x.get("code") for x in r.get("items") or []]


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:5]
    dA = M["div"]
    dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": f"Divisi B {u}"}, 200)[1]
    cats = [call("POST", "master/item_categories", {"code": f"KC{u}{i}", "name": f"Kat{u} {n}"}, 200)[1] for i, n in enumerate(("Alfa", "Beta"))]
    for m, b in (("uoms", {"code": f"S{u}", "name": f"Sat {u}", "symbol": "s"}), ("taxes", {"code": f"T{u}", "name": f"Pajak {u}", "rate": 11}),
                 ("supplier_categories", {"code": f"KS{u}", "name": f"KatSup {u}"}), ("units", {"code": f"UN{u}", "name": f"Unit {u}", "division_id": dA["id"]}),
                 ("contacts", {"code": f"KT{u}", "name": f"Kontak {u}", "division_id": dB["id"]})):
        call("POST", f"master/{m}", {**b, "is_active": True}, 200)
    items = []
    for i in range(30):
        items.append(call("POST", "master/items", {"code": f"PG{u}-{i:02d}", "name": f"Barang Paging {i:02d}", "unit": "PCS", "is_active": True,
                                                   "category_id": cats[i % 2]["id"], "division_id": (dA if i < 20 else dB)["id"]}, 200)[1])
    print(f"setup: tenant + 30 barang ({u})")

    # --- kompatibilitas lama: tanpa page -> array
    for m in MASTERS:
        sc, r = call("GET", f"master/{m}")
        check(f"{m}: tanpa page tetap array", sc == 200 and isinstance(r, list), f"{sc} {type(r)}")
    sc, r = call("GET", "item-warehouse")
    check("item-warehouse: tanpa page tetap array", sc == 200 and isinstance(r, list))
    sc, r = call("GET", f"master/items?q=PG{u}-0")
    check("items: ?q lama (tanpa page) tetap array tersaring", sc == 200 and isinstance(r, list) and len(r) == 10, f"{len(r) if isinstance(r, list) else r}")
    sc, r = call("GET", "lookup/items")
    check("lookup/items tetap array ringan (tanpa envelope)", sc == 200 and isinstance(r, list) and "spec" not in (r[0] if r else {}))

    # --- envelope + page size
    for m in MASTERS:
        sc, r = page(f"master/{m}?page=1&page_size=25")
        check(f"{m}: envelope {{items,total,page,page_size}}", sc == 200 and {"items", "total", "page", "page_size"} <= set(r), f"{sc} {list(r)[:5]}")
    sc, r = page("master/items?page=1&page_size=25")
    check("items: default 25 per halaman", r.get("page_size") == 25 and len(r["items"]) == 25 and r["total"] == 32, f"{r.get('page_size')} {r.get('total')}")
    check("items: default urut terbaru dahulu", r["items"][0]["created_at"] >= r["items"][1]["created_at"] and r["items"][0]["code"] == f"PG{u}-29")
    for n in (50, 100):
        sc, r = page(f"master/items?page=1&page_size={n}")
        check(f"items: page_size {n} diterima", r.get("page_size") == n and len(r["items"]) == 32)
    sc, r = page("master/items?page=1&page_size=7")
    check("items: page_size tidak valid -> 25", r.get("page_size") == 25)
    sc, r = page("master/items?page=99&page_size=25")
    check("items: halaman di luar jangkauan -> halaman terakhir", r.get("page") == 2 and len(r["items"]) == 7, f"{r.get('page')} {len(r.get('items', []))}")

    # --- search seluruh dataset (bukan hanya halaman aktif)
    sc, r = page(f"master/items?page=1&page_size=25&q=PG{u}-01")
    check("search: data di halaman 2 tetap ditemukan", r.get("total") == 1 and codes(r) == [f"PG{u}-01"], f"{codes(r)}")
    sc, r = page(f"master/items?page=1&page_size=25&q=Kat{u} Beta")
    check("search: berdasarkan nama referensi (Kategori)", r.get("total") == 15, f"{r.get('total')}")
    sc, r = page(f"master/items?page=1&page_size=25&q=tidakada{u}")
    check("search: tidak cocok -> total 0", r.get("total") == 0 and r["items"] == [])

    # --- sort backend
    sc, r = page(f"master/items?page=1&page_size=100&q=PG{u}&sort=code&dir=asc")
    check("sort: kode naik", codes(r) == sorted(codes(r)) and codes(r)[0] == f"PG{u}-00")
    sc, r2 = page(f"master/items?page=1&page_size=100&q=PG{u}&sort=code&dir=desc")
    check("sort: kode turun", codes(r2) == list(reversed(codes(r))))
    sc, r = page(f"master/items?page=1&page_size=100&q=PG{u}&sort=category_label&dir=asc")
    labels = [x.get("category_label") for x in r["items"]]
    check("sort: kolom referensi (Kategori) naik", labels == sorted(labels) and labels[0] == f"Kat{u} Alfa", f"{labels[:3]}")
    sc, r = page(f"master/items?page=2&page_size=25&sort=code&dir=asc")
    check("sort + page: halaman 2 lanjutan urutan global", codes(r)[0] == f"PG{u}-23" if codes(r) else False, f"{codes(r)[:2]}")

    # --- filter status
    call("PUT", f"master/items/{items[5]['id']}", {**items[5], "is_active": False}, 200)
    sc, r = page("master/items?page=1&page_size=25&f_status_label=Nonaktif")
    check("filter: Status Nonaktif", r.get("total") == 1 and codes(r) == [f"PG{u}-05"], f"{codes(r)}")
    sc, r = page("master/items?page=1&page_size=100&f_status_label=Aktif")
    check("filter: Status Aktif", r.get("total") == 31 and f"PG{u}-05" not in codes(r))
    sc, r = page(f"master/items?page=1&page_size=25&f_status_label=Aktif&q=PG{u}-0&sort=code&dir=desc")
    check("filter + search + sort digabung", codes(r) == [f"PG{u}-{i:02d}" for i in (9, 8, 7, 6, 4, 3, 2, 1, 0)], f"{codes(r)}")

    # --- Stok Min/Max
    for it, mn, cur in ((items[0], 5, 0), (items[1], 5, 3), (items[2], 1, 0)):
        call("POST", "item-warehouse", {"item_id": it["id"], "warehouse_id": M["wh"]["id"], "min_stock": mn, "max_stock": 50, "current_stock": cur}, 200)
    sc, r = page("item-warehouse?page=1&page_size=25")
    check("Stok Min/Max: envelope", sc == 200 and r.get("total") == 3 and r.get("page_size") == 25, f"{sc} {r.get('total')}")
    sc, r = page("item-warehouse?page=1&page_size=25&q=Paging 01")
    check("Stok Min/Max: search barang", r.get("total") == 1 and r["items"][0]["item_id"] == items[1]["id"])
    allst = [x["status"] for x in page("item-warehouse?page=1&page_size=25")[1]["items"]]
    sc, r = page("item-warehouse?page=1&page_size=25&f_status=Out of Stock")
    sc, r2 = page("item-warehouse?page=1&page_size=25&f_status=Overstock")
    check("Stok Min/Max: filter status", r.get("total") == allst.count("Out of Stock") and all(x["status"] == "Out of Stock" for x in r["items"])
          and r2.get("total") == allst.count("Overstock"), f"{r.get('total')} {allst}")
    sc, r = page("item-warehouse?page=1&page_size=25&sort=item_name&dir=desc")
    check("Stok Min/Max: sort nama barang", [x["item_name"] for x in r["items"]] == sorted([x["item_name"] for x in r["items"]], reverse=True))

    # --- SPK & Kontrak Harga Vendor
    for i in range(3):
        call("POST", "spk", {"spk_number": f"SPK-{u}-{i}", "project_name": f"Pekerjaan {i}", "spk_value": 10 + i, "procurement_budget": 5,
                             "status": "active", "division_id": dA["id"]}, 200)
    sc, r = page("spk?page=1&page_size=7")
    check("SPK: page_size tidak valid -> 25", sc == 200 and r.get("page_size") == 25 and r.get("total") == 3)
    sc, r = page("spk?page=1&page_size=50&sort=spk_value")
    check("SPK: page_size 50 + sort backend", r.get("page_size") == 50 and [x["spk_value"] for x in r["items"]] == [10, 11, 12])
    sc, r = page(f"spk?page=1&page_size=25&q=SPK-{u}-2")
    check("SPK: search backend", r.get("total") == 1)
    sc, r = page("spk")
    check("SPK: tanpa page tetap envelope lama", sc == 200 and r.get("total") == 3 and "items" in r)
    sc, vc = call("POST", "vendor-contracts", {"supplier_id": M["supX"]["id"], "contract_number": f"KHV-{u}", "start_date": "2026-01-01",
                                               "end_date": "2026-12-31", "items": [{"item_id": items[0]["id"], "uom_id": "", "price": 100}]})
    sc, r = page("vendor-contracts?page=1&page_size=100")
    det = call("GET", f"vendor-contracts/{vc.get('id')}")[1] if vc.get("id") else {}
    row = next((x for x in r.get("items", []) if x["id"] == vc.get("id")), {})
    check("Kontrak: page_size 100 + jumlah item (batch) sesuai detail", r.get("page_size") == 100 and row.get("item_count") == len(det.get("items") or []),
          f"{row.get('item_count')} vs {len(det.get('items') or [])}")
    sc, r = page(f"vendor-contracts?page=1&page_size=25&q=KHV-{u}")
    check("Kontrak: search backend", r.get("total") == 1)

    # --- permission + cakupan divisi
    call("PUT", "access/roles/manager", {"permissions": ["items.view", "contacts.view", "units.view", "spk.view", "stock_minmax.view"],
                                         "division_scope": {"mode": "all"}}, 200)
    us = {}
    for tag, divs in (("A", [dA["id"]]), ("B", [dB["id"]])):
        email = f"mp_{tag}_{u}@example.com"
        nu = call("POST", "users", {"email": email, "password": "TestPass123!", "name": tag, "role": "manager"}, 200)[1]
        call("PUT", f"access/users/{nu['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": divs}}, 200)
        us[tag] = U(email)
    A, B = us["A"], us["B"]
    sc, r = page(f"master/items?page=1&page_size=100&q=PG{u}", A)
    check("divisi A: hanya barang divisi A (total & items)", sc == 200 and r.get("total") == 20 and all(x["division_id"] == dA["id"] for x in r["items"]), f"{sc} {r.get('total')}")
    sc, r = page(f"master/items?page=1&page_size=25&q=PG{u}-25", A)
    check("divisi A: search tidak membocorkan barang divisi B", r.get("total") == 0)
    sc, r = page(f"master/items?page=1&page_size=100&q=PG{u}", B)
    check("divisi B: hanya barang divisi B", r.get("total") == 10 and all(x["division_id"] == dB["id"] for x in r["items"]))
    sc, r = page(f"master/contacts?page=1&page_size=25&q=Kontak {u}", A)
    check("divisi A: kontak divisi B tersembunyi", r.get("total") == 0)
    sc, r = page(f"spk?page=1&page_size=25&q=SPK-{u}", B)
    check("divisi B: SPK divisi A tersembunyi", sc == 200 and r.get("total") == 0, f"{sc} {r.get('total')}")
    sc, r = page("item-warehouse?page=1&page_size=25", B)
    check("divisi B: Stok Min/Max gudang/barang divisi lain tersembunyi", sc == 200 and r.get("total") == 0, f"{sc} {r.get('total')}")
    sc, r = page("master/suppliers?page=1&page_size=25", A)
    check("permission: tanpa izin Lihat Supplier -> 403 (paging)", sc == 403, f"{sc}")
    sc, r = page("master/suppliers", A)
    check("permission: tanpa izin Lihat Supplier -> 403 (lama)", sc == 403, f"{sc}")

    # --- tenant isolation
    Tb = requests.Session()
    v = uuid.uuid4().hex[:8]
    Tb.post(f"{API}/saas/register", json={"company_name": f"MP {v}", "pic_name": "QA", "email": f"mp_{v}@example.com", "whatsapp": "+628123456789",
                                          "workspace_slug": f"mp-{v}", "plan_code": "starter", "password": "TestPass123!", "address": "x", "terms_accepted": True})
    tok = Tb.post(f"{API}/auth/login", json={"email": f"mp_{v}@example.com", "password": "TestPass123!"}).json().get("token")
    Tb.headers.update({"Authorization": f"Bearer {tok}"})
    other = lambda m, p: Tb.request(m, f"{API}/{p}").json()  # noqa: E731
    r = other("GET", f"master/items?page=1&page_size=100&q=PG{u}")
    check("tenant lain: search barang tenant A -> 0", r.get("total") == 0, f"{r}")
    r = other("GET", "item-warehouse?page=1&page_size=25")
    check("tenant lain: Stok Min/Max tenant A tidak terlihat", r.get("total") == 0)
    r = other("GET", f"spk?page=1&page_size=25&q=SPK-{u}")
    check("tenant lain: SPK tenant A tidak terlihat", r.get("total") == 0)
    r = other("GET", f"vendor-contracts?page=1&page_size=25&q=KHV-{u}")
    check("tenant lain: Kontrak tenant A tidak terlihat", r.get("total") == 0)
    for m in MASTERS:
        r = other("GET", f"master/{m}?page=1&page_size=100&q={u}")
        check(f"tenant lain: {m} tenant A tidak terlihat", r.get("total") == 0, f"{r.get('total')}")

    # --- Hapus Massal dari pilihan halaman aktif tetap aman (all-or-nothing)
    sc, r = page(f"master/items?page=1&page_size=25&q=PG{u}&sort=code&dir=desc")
    pick = [x["id"] for x in r["items"][:2]]
    sc, mro = call("POST", "mro", {"no": f"MRO-{u}", "division_id": dA["id"], "lines": [{"item_id": items[10]["id"], "qty": 1, "warehouse_id": M["wh"]["id"]}]})
    sc, res = call("POST", "master-bulk-delete/items", {"ids": pick + [items[10]["id"]]})
    sc2, after = page(f"master/items?page=1&page_size=100&q=PG{u}&f_status_label=Aktif")
    check("Hapus Massal campuran (ada yang dipakai) -> 409, tidak ada yang terhapus", sc == 409 and after.get("total") == 29, f"{sc} {after.get('total')}")
    sc, res = call("POST", "master-bulk-delete/items", {"ids": pick})
    sc2, after = page(f"master/items?page=1&page_size=100&q=PG{u}&f_status_label=Aktif")
    check("Hapus Massal pilihan halaman -> terhapus & total berkurang", sc == 200 and after.get("total") == 27 and not set(pick) & {x["id"] for x in after["items"]}, f"{sc} {after.get('total')}")

    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\nTOTAL {ok}/{len(T.RESULTS)} passed")
    sys.exit(0 if ok == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
