"""Fixture UAT Stock Opname (Staff Asset tanpa harga + Approver Asset dengan harga) — idempotensi + RBAC.

Throwaway tenant (saas/register). Menjalankan scripts/uat_fixture_stock_opname.run() BERULANG lalu memvalidasi:
tanpa duplikasi, izin/cakupan konsisten, redaksi harga server-side (detail, baris, cetak, template, item-warehouse,
audit, manipulasi query), penolakan lintas divisi, workflow staff -> approver, dan user berizin harga tetap normal.
Jalankan: backend aktif (default :8001) atau via scripts/run_regression_itest.sh (proc_itest terisolasi).
"""
import io
import json
import sys
import uuid
from pathlib import Path

import requests
from openpyxl import load_workbook

import receipt_control_test as T
import transfer_multi_warehouse_test as TM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import uat_fixture_stock_opname as FX  # noqa: E402

call, check, API = T.call, T.check, T.API
PRICE = ("avg_cost", "unit_price", "net_value", "surplus_value", "shortage_value", "posted_value", "posted_unit_cost",
         "approved_unit_cost", "total_value", "value_in", "value_out", "unit_cost")


def leaks(obj):
    t = json.dumps(obj)
    return [k for k in PRICE if f'"{k}"' in t]


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw})
    if r.status_code == 200:
        s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s, r.status_code


def main():
    TM.register()
    adm = FX.Api(API, T.S)
    spw, apw = f"Uat-{uuid.uuid4().hex[:10]}!", f"Uat-{uuid.uuid4().hex[:10]}!"
    r1 = FX.run(adm, spw, apw)
    r2 = FX.run(adm, spw, apw)
    check("F1. Fixture run ke-1 membuat master + 2 user + saldo awal", {"user:staff", "user:approver"} <= set(r1["created"]) and
          sum(1 for x in r1["created"] if x.startswith("opening:")) == 3, r1["created"])
    check("F2. Fixture run ke-2 idempotent: tidak membuat apa pun, ID sama",
          r2["created"] == [] and all(r1[k] == r2[k] for k in ("staff_id", "approver_id", "wh_asset", "wh_ops", "division_asset", "items")), (r2["created"],))
    users = call("GET", "users")[1]
    check("F3. Tanpa duplikasi user", sum(u["email"] == FX.STAFF_EMAIL for u in users) == 1 and sum(u["email"] == FX.APPROVER_EMAIL for u in users) == 1)
    whs = call("GET", "master/warehouses")[1]
    whs = whs.get("items", whs) if isinstance(whs, dict) else whs
    check("F4. Tanpa duplikasi gudang/barang", sum(w.get("code") == "UAT-GA" for w in whs) == 1 and sum(w.get("code") == "UAT-GO" for w in whs) == 1)
    check("F5. Saldo awal tidak berlipat (UAT-BRG01@UAT-GA = 50)", TM.stock(r1["items"]["UAT-BRG01"], r1["wh_asset"]) == 50)

    ss, sc = login(FX.STAFF_EMAIL, spw)
    check("S1. Staff Asset login", sc == 200)
    me = ss.get(f"{API}/access/me").json()
    eff = me.get("effective") or {}
    effk = set(eff if isinstance(eff, list) else [k for k, v in eff.items() if v])
    check("S2. Staff: tanpa view_purchase_price & tanpa opname.post; cakupan divisi = Asset saja",
          "view_purchase_price" not in effk and "opname.post" not in effk and "opname.edit" in effk
          and me.get("division_scope") == {"mode": "selected", "divisions": [r1["division_asset"]]}, (sorted(effk)[:40], me.get("division_scope")))
    sw = ss.get(f"{API}/master/warehouses").json()
    sw = sw.get("items", sw) if isinstance(sw, dict) else sw
    codes = {w.get("code") for w in sw}
    check("S3. Staff hanya melihat gudang divisi Asset", "UAT-GA" in codes and "UAT-GO" not in codes, codes)
    r = ss.post(f"{API}/opname", json={"warehouse_id": r1["wh_ops"], "division_id": r1["division_ops"], "mode": "live", "scope": "all"})
    check("S4. Staff membuat Opname di gudang divisi lain -> ditolak", r.status_code in (400, 403, 404), (r.status_code, r.text[:200]))
    r = ss.post(f"{API}/opname", json={"warehouse_id": r1["wh_asset"], "division_id": r1["division_asset"], "mode": "freeze", "scope": "all"})
    check("S5. Staff membuat Opname di gudang Asset -> 200", r.status_code == 200, (r.status_code, r.text[:200]))
    op = r.json()
    did = op["id"]
    det = ss.get(f"{API}/opname/{did}").json()
    check("S6. Detail Opname staff: tanpa harga/nilai (baris + ringkasan)", not leaks(det) and det.get("permissions", {}).get("view_price") in (False, None), leaks(det))
    for q in ("?show_price=1", "?include_prices=true&view_price=1", "?price=1&with_value=1"):
        x = ss.get(f"{API}/opname/{did}{q}")
        if leaks(x.json()):
            check(f"S7. Manipulasi query {q} tetap diredaksi", False, leaks(x.json()))
            break
    else:
        check("S7. Manipulasi query (show_price/include_prices/...) tetap diredaksi", True)
    ln = ss.get(f"{API}/opname/{did}/lines?page=1&page_size=50")
    pr = ss.get(f"{API}/opname/{did}/print-data")
    check("S8. Endpoint baris & data cetak staff: tanpa harga", ln.status_code == 200 and pr.status_code == 200 and not leaks(ln.json()) and not leaks(pr.json()),
          (ln.status_code, pr.status_code, leaks(ln.json()), leaks(pr.json())))
    tp = ss.get(f"{API}/opname/{did}/template.xlsx")
    hdr = [str(c.value or "") for c in load_workbook(io.BytesIO(tp.content)).active[6]] if tp.status_code == 200 else []
    check("S9. Template Excel staff: tanpa kolom harga/nilai", tp.status_code == 200 and "Stok Fisik" in hdr and not [h for h in hdr if "Harga" in h or "Nilai" in h], hdr)
    lines = {x["item_code"]: x for x in det["lines"]}
    r = ss.put(f"{API}/opname/{did}/count", json={"lines": [{"line_id": lines["UAT-BRG01"]["id"], "approved_unit_cost": 1}]})
    check("S10. Staff mengisi Harga Satuan -> 403", r.status_code == 403, r.status_code)
    iw = ss.get(f"{API}/item-warehouse").json()
    iw = iw.get("items", iw) if isinstance(iw, dict) else iw
    check("S11. /item-warehouse staff: tanpa avg_cost/total_value, hanya gudang Asset",
          iw and not leaks(iw) and r1["wh_ops"] not in {x.get("warehouse_id") for x in iw}, (leaks(iw), len(iw)))
    au = ss.get(f"{API}/audit")
    dp = ss.get(f"{API}/dashboard-premium")
    check("S12. Audit & feed dashboard staff: harga override (approved_unit_cost) diredaksi",
          au.status_code in (200, 403) and (au.status_code == 403 or not leaks(au.json())) and (dp.status_code != 200 or not leaks(dp.json().get("recent"))),
          (au.status_code, leaks(au.json()) if au.status_code == 200 else None))
    check("S13. Admin (berizin harga) tetap melihat harga di audit", "approved_unit_cost" in json.dumps(call("GET", "audit")[1]))

    sc, og = call("POST", "opname", {"warehouse_id": r1["wh_ops"], "division_id": r1["division_ops"], "mode": "live", "scope": "all"})
    x = ss.get(f"{API}/opname/{og.get('id')}")
    lst = ss.get(f"{API}/opname?page_size=500").json()
    lst = lst.get("items", lst.get("rows", [])) if isinstance(lst, dict) else lst
    check("S14. Opname divisi lain (dibuat admin) tidak terbaca staff & tidak ada di daftar",
          sc == 200 and x.status_code in (403, 404) and og.get("id") not in {o.get("id") for o in lst}, (sc, x.status_code))
    x = ss.post(f"{API}/opname/{og.get('id')}/workflow", json={"action": "cancel", "reason": "coba lintas divisi"})
    check("S15. Staff membatalkan Opname divisi lain -> ditolak", x.status_code in (403, 404), x.status_code)

    # Iterasi 8 temuan 5.3: Review saat baris belum dihitung = 400 (readiness), bukan 409.
    x = ss.post(f"{API}/opname/{did}/workflow", json={"action": "review"})
    check("S15b. Review dengan baris belum dihitung -> 400 (readiness), status tetap Counting",
          x.status_code == 400 and ss.get(f"{API}/opname/{did}").json().get("status") == "Counting", (x.status_code, x.text[:200]))
    r = ss.put(f"{API}/opname/{did}/count", json={"lines": [{"line_id": lines["UAT-BRG01"]["id"], "counted": 48, "reason": "Rusak 2"},
                                                            {"line_id": lines["UAT-BRG02"]["id"], "counted": 200}]})
    check("S16. Staff menyimpan hasil hitung", r.status_code == 200, (r.status_code, r.text[:200]))
    rv = ss.post(f"{API}/opname/{did}/workflow", json={"action": "review"})
    rv2 = ss.post(f"{API}/opname/{did}/workflow", json={"action": "review"})
    check("S16b. Review dari Counting -> 200; Review ulang dari status Review -> 409 (transisi tidak sah)",
          rv.status_code == 200 and rv.json().get("status") == "Review" and rv2.status_code == 409, (rv.status_code, rv2.status_code))
    check("S17. Staff Review -> Submit (Waiting Approval)",
          ss.post(f"{API}/opname/{did}/submit").json().get("status") == "Waiting Approval")
    check("S18. Staff Approve/Posting -> 403; Reject -> 403",
          ss.post(f"{API}/opname/{did}/post").status_code == 403
          and ss.post(f"{API}/opname/{did}/workflow", json={"action": "reject", "reason": "x"}).status_code == 403)
    check("S19. Freeze aktif: Adjustment di UAT-GA ditolak 409", call("POST", "adjustments", {
        "warehouse_id": r1["wh_asset"], "division_id": r1["division_asset"], "adj_type": "Koreksi", "reason": "QA",
        "lines": [{"item_id": r1["items"]["UAT-BRG02"], "adjustment": -1, "reason": "QA", "warehouse_id": r1["wh_asset"]}]})[0] == 409)
    # Iterasi 8 temuan 4.3: gudang lain (UAT-GO, tidak Freeze) tetap bisa mutasi; 400 tanpa avg cost = validasi valuasi, bukan Freeze.
    go_adj = lambda item, q: call("POST", "adjustments", {  # noqa: E731
        "warehouse_id": r1["wh_ops"], "division_id": r1["division_ops"], "adj_type": "Koreksi", "reason": "QA",
        "lines": [{"item_id": r1["items"][item], "adjustment": q, "reason": "QA", "warehouse_id": r1["wh_ops"]}]})
    s_go = TM.stock(r1["items"]["UAT-BRG03"], r1["wh_ops"])
    a1, a2 = go_adj("UAT-BRG03", 1), go_adj("UAT-BRG03", -1)
    check("S19b. Saat UAT-GA Freeze, Adjustment +1/-1 di UAT-GO (ada avg cost) -> 200, saldo kembali",
          a1[0] == 200 and a2[0] == 200 and TM.stock(r1["items"]["UAT-BRG03"], r1["wh_ops"]) == s_go, (a1[0], a2[0]))
    sc_nc, r_nc = go_adj("UAT-BRG01", 1)
    check("S19c. Surplus tanpa avg cost & tanpa Harga Satuan -> 400 validasi valuasi (bukan pesan Freeze)",
          sc_nc == 400 and "Approved Unit Cost" in str(r_nc) and "Opname" not in str(r_nc), (sc_nc, r_nc))

    sa, sc = login(FX.APPROVER_EMAIL, apw)
    ad = sa.get(f"{API}/opname/{did}").json()
    check("A1. Approver (izin harga) melihat Harga Satuan & nilai selisih", sc == 200 and "avg_cost" in json.dumps(ad) and ad.get("summary", {}).get("net_value") == -2000,
          (sc, ad.get("summary")))
    check("A2. Approver: data cetak memuat nilai", "net_value" in json.dumps(sa.get(f"{API}/opname/{did}/print-data").json()))
    iwa = sa.get(f"{API}/item-warehouse").json()
    iwa = iwa.get("items", iwa) if isinstance(iwa, dict) else iwa
    check("A3. Approver: /item-warehouse memuat avg_cost", any("avg_cost" in x for x in iwa))
    x = sa.post(f"{API}/opname/{did}/post")
    check("A4. Approver Approve & Posting -> Posted; stok UAT-BRG01 = 48", x.status_code == 200 and x.json().get("status") == "Posted"
          and TM.stock(r1["items"]["UAT-BRG01"], r1["wh_asset"]) == 48, (x.status_code, x.text[:200]))
    # Iterasi 8 temuan 6.3: staff berizin edit mengubah dokumen Posted -> 409 (status terkunci), stok tidak berubah.
    x = ss.put(f"{API}/opname/{did}/count", json={"lines": [{"line_id": lines["UAT-BRG01"]["id"], "counted": 1, "reason": "x"}]})
    check("A4b. Staff ubah hitungan dokumen Posted -> 409; stok tetap 48", x.status_code == 409
          and TM.stock(r1["items"]["UAT-BRG01"], r1["wh_asset"]) == 48, x.status_code)
    x = sa.get(f"{API}/opname/{og.get('id')}")
    check("A5. Approver Asset juga tidak dapat membaca Opname divisi Operasional", x.status_code in (403, 404), x.status_code)
    call("POST", f"opname/{og['id']}/workflow", {"action": "cancel", "reason": "QA fixture"})

    # Seseorang mengubah izin/cakupan secara manual -> run fixture lagi mengembalikan kondisi baku.
    call("PUT", f"access/users/{r1['staff_id']}", {"overrides": {"view_purchase_price": "allow"}, "division_override": {"mode": "all", "divisions": []}})
    r3 = FX.run(adm, spw, apw)
    acc = call("GET", f"access/users/{r1['staff_id']}")[1]
    check("F6. Run ulang memulihkan izin & cakupan baku (konsisten)", r3["created"] == [] and acc.get("overrides") == FX.STAFF_OVERRIDES
          and acc.get("division_override") == {"mode": "selected", "divisions": [r1["division_asset"]]}, (acc.get("overrides"), acc.get("division_override")))
    ss2, sc = login(FX.STAFF_EMAIL, spw)
    check("F7. Setelah run ulang staff kembali tanpa harga", sc == 200 and not leaks(ss2.get(f"{API}/opname/{did}").json()))

    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
