"""Regression: perubahan shared layer untuk Transfer multi gudang TIDAK mengubah Loan / Adjustment / Opname / MRO / MWA.
Shared file yang disentuh (semua di-guard khusus Transfer): access_control_layer (line_warehouse_ids & key gudang baris
hanya untuk module transfer), transaction_mutation_layer (cabang module == "transfer"), attachment_integrity_guard_layer
(entity transfer_draft), doc_warehouse (fungsi Transfer + draft). Tenant QA sementara; tidak menyentuh tenant lain."""
import io
import os
import sys

import receipt_control_test as T
import transfer_multi_warehouse_test as TM
from vendor_invoice_test import PW, U

call, check, API = T.call, T.check, T.API
u = TM.u


def main():
    TM.register()
    asset = TM.m("divisions", {"code": f"SA{u}", "name": "Asset"})
    ops = TM.m("divisions", {"code": f"SO{u}", "name": "Operasional"})
    cat = TM.m("item_categories", {"code": f"SC{u}", "name": "Umum"})
    uom = TM.m("uoms", {"code": f"SU{u}", "name": "Pcs"})
    WA = TM.m("warehouses", {"code": f"SWA{u}", "name": "Gudang A", "is_active": True, "division_id": asset["id"]})
    WB = TM.m("warehouses", {"code": f"SWB{u}", "name": "Gudang B", "is_active": True, "division_id": asset["id"]})
    WC = TM.m("warehouses", {"code": f"SWC{u}", "name": "Gudang C Ops", "is_active": True, "division_id": ops["id"]})
    item = TM.m("items", {"code": f"SI{u}", "name": "Filter", "category_id": cat["id"], "division_id": asset["id"],
                          "base_uom_id": uom["id"], "unit": "PCS", "is_active": True})
    proj = TM.m("projects", {"code": f"SP{u}", "name": "Project A"})

    # ---------- Adjustment (Opening) tetap seperti semula
    sc, adj = call("POST", "adjustments", {"date": "2026-09-20", "warehouse_id": WA["id"], "division_id": asset["id"], "adj_type": "Opening",
                                           "reason": "QA", "lines": [{"item_id": item["id"], "adjustment": 10, "reason": "QA", "approved_unit_cost": 1000}]})
    check("ADJ. Opening adjustment -> 200 & stok A = 10", sc == 200 and TM.stock(item["id"], WA["id"]) == 10, adj)
    sc, adjd = call("GET", f"adjustments/{adj['id']}")
    check("ADJ. Detail adjustment terbaca", sc == 200 and adjd.get("lines"))

    # ---------- Loan: header warehouse tetap sumber posting; key gudang pada baris DIABAIKAN (bukan aturan Transfer)
    today = __import__("datetime").date.today().isoformat()
    sc, loan = call("POST", "loans", {"date": today, "from_warehouse_id": WA["id"], "to_warehouse_id": WB["id"], "division_id": asset["id"],
                                      "lines": [{"item_id": item["id"], "qty": 2, "uom_id": uom["id"], "to_warehouse_id": WC["id"], "from_warehouse_id": WC["id"]}]})
    check("LOAN. Loan dibuat -> 200", sc == 200, loan)
    check("LOAN. Stok mengikuti HEADER (A=8, B=2, C=0) — key gudang baris tidak dipakai", TM.stock(item["id"], WA["id"]) == 8 and TM.stock(item["id"], WB["id"]) == 2
          and TM.stock(item["id"], WC["id"]) == 0)
    sc, vl = call("GET", "reports/valuation-ledger")
    rows = [x for x in (vl if isinstance(vl, list) else vl.get("rows", [])) if x.get("doc_id") == loan["id"] or x.get("doc_no") == loan["no"]]
    vin = sum(float(x.get("value_in") or 0) for x in rows if float(x.get("qty_in") or 0) > 0)
    check("MWA. Loan membawa nilai MWA (2 x 1000 = 2000) tanpa formula baru", abs(vin - 2000) < 1e-6, rows)
    ldoc = TM.db_conn
    with ldoc() as cx, cx.cursor() as cur:
        cur.execute("SELECT JSON_EXTRACT(doc,'$.from_warehouse_id'), JSON_EXTRACT(doc,'$.to_warehouse_id') FROM loan_lines WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.loan_id'))=%s", (loan["id"],))
        lr = cur.fetchall()
    check("LOAN. Baris loan tidak menyimpan gudang per baris (skema loan tidak berubah)", lr and all(a is None and b is None for a, b in lr), lr)

    # ---------- MRO + lampiran existing (non-draft): perilaku hapus tetap soft-delete
    sc, mro = call("POST", "mro", {"no": f"MRO-SG{u}", "division_id": asset["id"], "requester": "QA", "lines": [{"item_id": item["id"], "qty": 1, "warehouse_id": WA["id"], "project_id": proj["id"]}]})
    check("MRO. MRO dibuat -> 200", sc == 200, mro)
    up = T.S.post(f"{API}/attachments", files={"file": ("mro.pdf", io.BytesIO(b"%PDF-1.4 mro"), "application/pdf")}, data={"entity": "mro", "entity_id": mro["id"]})
    check("MRO. Upload lampiran MRO -> 200", up.status_code == 200, up.text[:100])
    aid = up.json().get("id")
    dl = T.S.get(f"{API}/attachments/{aid}/download")
    check("MRO. Download lampiran MRO -> 200", dl.status_code == 200)
    sc, _ = call("DELETE", f"attachments/{aid}")
    with ldoc() as cx, cx.cursor() as cur:
        cur.execute("SELECT JSON_EXTRACT(doc,'$.is_deleted') FROM attachments WHERE id=%s OR JSON_UNQUOTE(JSON_EXTRACT(doc,'$.id'))=%s", (aid, aid))
        ar = cur.fetchall()
    check("MRO. Hapus lampiran MRO tetap soft-delete (row tetap ada, is_deleted=true)", sc == 200 and ar and str(ar[0][0]).lower() == "true", ar)
    bad = T.S.post(f"{API}/attachments", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")}, data={"entity": "mro", "entity_id": mro["id"]})
    check("MRO. Rule tipe file existing tetap berlaku (.exe ditolak)", bad.status_code == 400)

    # ---------- Opname
    sc, opn = call("POST", "opname", {"date": today, "warehouse_id": WA["id"], "division_id": asset["id"], "scope": "all"})
    check("OPN. Opname dibuat dengan snapshot stok gudang A (8)", sc == 200 and any(float(x.get("snapshot") or 0) == 8 for x in opn.get("lines", [])), opn)

    # ---------- Scope divisi: aturan baris Transfer TIDAK menempel ke Loan
    email = f"sgr_{u}@example.com"
    _, usr = call("POST", "users", {"email": email, "password": PW, "name": "QA Asset", "role": "warehouse"}, 200)
    call("PUT", f"access/users/{usr['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": [asset["id"]]}}, 200)
    C = U(email)
    sc, r = C("POST", "loans", {"date": today, "from_warehouse_id": WA["id"], "to_warehouse_id": WB["id"], "division_id": asset["id"],
                                "lines": [{"item_id": item["id"], "qty": 1, "uom_id": uom["id"], "from_warehouse_id": WC["id"]}]})
    check("SCOPE. Loan user Asset dengan key from_warehouse_id baris divisi lain tetap 200 (perilaku lama)", sc == 200, (sc, r))
    sc, r = C("POST", "loans", {"date": today, "from_warehouse_id": WA["id"], "to_warehouse_id": WC["id"], "division_id": asset["id"],
                                "lines": [{"item_id": item["id"], "qty": 1, "uom_id": uom["id"]}]})
    check("SCOPE. Loan ke gudang header divisi lain tetap 403 (scope header tidak berubah)", sc == 403, (sc, r))
    sc, r = C("POST", "transfers", {"date": today, "division_id": asset["id"], "from_warehouse_id": WA["id"], "to_warehouse_id": WB["id"],
                                    "lines": [{"item_id": item["id"], "qty": 1, "uom_id": uom["id"], "from_warehouse_id": WA["id"], "to_warehouse_id": WC["id"]}]})
    check("SCOPE. Transfer: gudang baris divisi lain -> 403 (aturan baru khusus Transfer)", sc == 403, (sc, r))
    with ldoc() as cx, cx.cursor() as cur:
        cur.execute("UPDATE loans SET doc = JSON_SET(doc, '$.line_warehouse_ids', JSON_ARRAY(%s)) WHERE id=%s", (WC["id"], loan["id"]))
    sc, lst = C("GET", "loans")
    sc2, _ = C("GET", f"loans/{loan['id']}")
    check("SCOPE. Field line_warehouse_ids pada Loan diabaikan (visibility Loan tetap dari header)", sc == 200 and any(x["id"] == loan["id"] for x in lst) and sc2 == 200, (sc, sc2))

    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
