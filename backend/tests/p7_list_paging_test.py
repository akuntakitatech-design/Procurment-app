"""P7 — daftar transaksi ber-halaman tanpa batas muat 1.000 dokumen + jalur cepat (hasil identik) — DB test terisolasi *itest*.

Membuktikan:
- L1 total daftar ber-halaman = SELURUH dokumen tenant (> 1.000), sama dengan baris export daftar (P6);
- L2 pencarian & filter periode menemukan dokumen lama di luar 1.000 terbaru (dulu tersembunyi);
- L3 jalur cepat (user global, tanpa cari/filter enrichment) == jalur penuh (dipaksa via `date_field=date`, tanpa efek pada hasil):
      items/total/page/facets identik untuk 9 daftar, banyak halaman, ukuran halaman, sort header, periode, counts & filter tahap MRO;
- L4 cakupan divisi user terbatas: melihat SELURUH dokumen divisinya walau di luar 1.000 terbaru tenant, tanpa bocor divisi lain;
- L5 respons lama tanpa `page` tetap array (batas muat existing, kompatibel pemanggil lama);
- L6 pinjaman/opname/penyesuaian/transfer: parity juga saat tanpa dokumen;
- L7 /api/dashboard (N+1 pinjaman diganti batch) tetap memberi angka yang sama dengan perhitungan referensi.
"""
import json
import os
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
import vendor_invoice_test as V  # noqa: E402
from opening_correction_test import conn, ins  # noqa: E402

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:5]
LISTS = ["mro", "ro", "po", "do", "mi", "transfers", "loans", "adjustments", "opname"]
N_A, N_B = 1080, 40  # dokumen MRO divisi A (baru) & divisi B (lama) -> total > 1.000


def get(fn, path):
    sc, r = fn("GET", path)
    return sc, r


def main():
    if "itest" not in os.environ.get("DATABASE_URL", ""):
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    M = T.setup()
    T.M = V.M = M
    call("PUT", "settings/approval_modules", {"modules": {k: {"enabled": False, "levels": []} for k in ("mro", "ro", "po")}}, 200)
    tenant = call("GET", "auth/me")[1].get("tenant_id")
    sc, divB = call("POST", "master/divisions", {"code": f"PB{u}", "name": f"Divisi PB {u}"}, 200)
    cn = conn()
    try:
        for i in range(N_A + N_B):
            old = i >= N_A  # divisi B = dokumen tertua (di luar 1.000 terbaru)
            day = f"2024-0{1 + i % 6}-1{i % 10}" if old else f"2026-0{1 + i % 9}-{10 + i % 18}"
            mid = f"p7l-{u}-{i}"
            ins(cn, "mro", {"id": mid, "tenant_id": tenant, "no": f"P7L-{u}-{i:05d}", "date": day, "requester": f"Peminta {i % 7}",
                            "division_id": (divB if old else M["div"])["id"], "submitted": True, "status": "Approved",
                            "created_at": f"{day}T0{i % 10}:{i % 60:02d}:00+00:00"})
            ins(cn, "mro_lines", {"id": f"{mid}-l", "tenant_id": tenant, "mro_id": mid, "item_id": M["item"]["id"], "qty": 1 + i % 4,
                                  "warehouse_id": M["wh"]["id"]})
        for i in range(30):
            pid = f"p7p-{u}-{i}"
            ins(cn, "po", {"id": pid, "tenant_id": tenant, "no": f"P7P-{u}-{i:03d}", "date": f"2026-0{1 + i % 9}-1{i % 10}",
                           "division_id": M["div"]["id"], "supplier_id": M["supX"]["id"], "status": "Draft", "grand_total": 1000.0 * (i + 1),
                           "created_at": f"2026-0{1 + i % 9}-1{i % 10}T01:00:00+00:00"})
            ins(cn, "po_lines", {"id": f"{pid}-l", "tenant_id": tenant, "po_id": pid, "item_id": M["item"]["id"], "qty": 2, "price": 500,
                                 "warehouse_id": M["wh"]["id"]})
        for i in range(12):
            lid = f"p7n-{u}-{i}"
            ins(cn, "loans", {"id": lid, "tenant_id": tenant, "no": f"P7N-{u}-{i:03d}", "date": "2026-02-0" + str(1 + i % 9),
                              "from_warehouse_id": M["wh"]["id"], "to_warehouse_id": M["wh2"]["id"], "division_id": M["div"]["id"],
                              "requester": "QA", "created_at": f"2026-02-0{1 + i % 9}T02:00:00+00:00"})
            ins(cn, "loan_lines", {"id": f"{lid}-l", "tenant_id": tenant, "loan_id": lid, "item_id": M["item"]["id"], "qty": 3,
                                   "returned": i % 4})
    finally:
        cn.close()
    for i in range(3):  # beberapa MRO nyata via API (alur existing)
        call("POST", "mro", {"no": f"P7A-{u}-{i}", "division_id": M["div"]["id"], "requester": "API",
                             "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]})
    n_mro = N_A + N_B + 3

    # L1 total = seluruh dokumen = export
    sc, r = get(call, "mro?page=1&page_size=25")
    check("L1a total daftar MRO ber-halaman = seluruh dokumen tenant (> 1.000, tanpa batas muat)", sc == 200 and r.get("total") == n_mro,
          (sc, r.get("total"), n_mro))
    sc, rj = call("GET", "report-center/txn-mro?page_size=50")
    check("L1b total daftar = total baris export daftar (P6)", sc == 200 and rj.get("total_rows") == r.get("total"), (rj.get("total_rows"),))
    # L2 dokumen lama ditemukan
    oldest = f"P7L-{u}-{N_A + N_B - 1:05d}"
    sc, r = get(call, f"mro?page=1&page_size=25&q={oldest}")
    check("L2a pencarian menemukan MRO tertua (di luar 1.000 terbaru)", sc == 200 and r.get("total") == 1 and r["items"][0]["no"] == oldest,
          (sc, r.get("total")))
    sc, r = get(call, "mro?page=1&page_size=25&date_from=2024-01-01&date_to=2024-12-31")
    check("L2b filter periode 2024 menemukan seluruh MRO lama", sc == 200 and r.get("total") == N_B, (sc, r.get("total")))

    # L3 parity jalur cepat vs penuh
    combos = ["page=1&page_size=25", "page=2&page_size=25", "page=44&page_size=25", "page=999&page_size=25", "page=3&page_size=100",
              "page=1&page_size=50&sort=no&dir=asc", "page=2&page_size=50&sort=no&dir=desc", "page=1&page_size=25&sort=date&dir=asc",
              "page=5&page_size=25&sort=created_at&dir=desc", "page=1&page_size=25&date_from=2026-03-01&date_to=2026-05-31",
              "page=1&page_size=25&q="]
    mro_extra = ["page=1&page_size=25&counts=lifecycle_stage", "page=2&page_size=25&counts=lifecycle_stage&f_lifecycle_stage=MRO",
                 "page=1&page_size=25&counts=lifecycle_stage&f_lifecycle_stage=Completed"]
    bad = []
    n = 0
    for lst in LISTS:
        for qs in combos + (mro_extra if lst == "mro" else []):
            s1, fast = get(call, f"{lst}?{qs}")
            s2, full = get(call, f"{lst}?{qs}&date_field=date")
            n += 1
            if s1 != 200 or s2 != 200 or json.dumps(fast, sort_keys=True, default=str) != json.dumps(full, sort_keys=True, default=str):
                bad.append((lst, qs, s1, s2, (fast or {}).get("total") if isinstance(fast, dict) else None,
                            (full or {}).get("total") if isinstance(full, dict) else None))
    check(f"L3 jalur cepat == jalur penuh (items/total/page/facets identik) — {n} kombinasi, 9 daftar", not bad, bad[:4])

    # L4 cakupan divisi user terbatas
    mgB = V.mk_user("manager", divs=[divB["id"]])
    sc, r = mgB("GET", "mro?page=1&page_size=100")
    nos = [x.get("no") for x in (r.get("items") or [])] if isinstance(r, dict) else []
    check("L4a Manajer Divisi PB: total = seluruh MRO divisinya (dokumen lama di luar 1.000 terbaru tenant)",
          sc == 200 and r.get("total") == N_B and oldest in nos, (sc, r.get("total") if isinstance(r, dict) else r))
    check("L4b tanpa bocor divisi lain", all(x.get("division_id") == divB["id"] for x in r.get("items") or []))
    sc, r = mgB("GET", f"mro?page=1&page_size=25&q=P7L-{u}-00000")
    check("L4c pencarian user terbatas tidak menemukan dokumen divisi lain", sc == 200 and r.get("total") == 0, (sc, r))

    # L5 respons lama tanpa page
    sc, arr = call("GET", "mro")
    check("L5 GET /api/mro tanpa page tetap array lama (batas muat existing 1.000)", sc == 200 and isinstance(arr, list) and len(arr) == 1000,
          (sc, type(arr).__name__, len(arr) if isinstance(arr, list) else None))

    # L7 dashboard pinjaman (batch) = referensi
    sc, dash = call("GET", "dashboard")
    sc2, loans = call("GET", "loans")
    exp = sum(1 for ln in loans if float(ln.get("outstanding_total") or 0) > 0) if isinstance(loans, list) else None
    check("L7 /api/dashboard loan_outstanding = pinjaman dengan sisa > 0 (batch, angka sama)",
          sc == 200 and sc2 == 200 and dash.get("loan_outstanding") == exp, (dash.get("loan_outstanding"), exp))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
