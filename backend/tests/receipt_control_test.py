"""DO/PO receipt control + list traceability E2E (throwaway tenant, no shared data touched)."""
import sys
import threading
import uuid

import requests

API = "http://localhost:8001/api"
S = requests.Session()
RESULTS = []


def check(name, cond, info=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


def call(method, path, body=None, expect=None):
    r = S.request(method, f"{API}/{path}", json=body)
    if expect is not None and r.status_code != expect:
        print(f"  !! {method} {path} -> {r.status_code} {r.text[:300]}")
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def setup():
    u = uuid.uuid4().hex[:8]
    sc, res = call("POST", "saas/register", {"company_name": f"RC {u}", "pic_name": "QA", "email": f"rc_{u}@example.com",
                                             "whatsapp": "+628123456789", "workspace_slug": f"rc-{u}", "plan_code": "starter",
                                             "password": "TestPass123!", "address": "x", "terms_accepted": True}, 200)
    tok = res.get("token")
    if not tok:
        sc, res = call("POST", "auth/login", {"email": f"rc_{u}@example.com", "password": "TestPass123!"}, 200)
        tok = res.get("token")
    S.headers.update({"Authorization": f"Bearer {tok}"})
    M = {}
    for key, coll, body in [
        ("wh", "warehouses", {"code": f"WA{u}", "name": "Gudang A", "is_active": True}),
        ("wh2", "warehouses", {"code": f"WB{u}", "name": "Gudang B", "is_active": True}),
        ("div", "divisions", {"code": f"DV{u}", "name": "Divisi Teknik"}),
        ("cat", "item_categories", {"code": f"KC{u}", "name": "Kategori Umum"}),
        ("uom", "uoms", {"code": f"PCS{u}", "name": "Pieces"}),
        ("scat", "supplier_categories", {"code": f"KS{u}", "name": "Kategori Supplier Umum"}),
    ]:
        sc, M[key] = call("POST", f"master/{coll}", body, 200)
    item_ref = {"category_id": M["cat"]["id"], "division_id": M["div"]["id"], "base_uom_id": M["uom"]["id"]}
    for key, coll, body in [
        ("item", "items", {"code": f"IT{u}", "name": "Baut M8", "unit": "PCS", "is_active": True, **item_ref}),
        ("item2", "items", {"code": f"IU{u}", "name": "Mur M8", "unit": "PCS", "is_active": True, **item_ref}),
        ("supX", "suppliers", {"code": f"SX{u}", "name": "Supplier X", "email": "x@example.com", "supplier_category_id": M["scat"]["id"]}),
        ("supY", "suppliers", {"code": f"SY{u}", "name": "Supplier Y", "supplier_category_id": M["scat"]["id"]}),
        ("pa", "projects", {"code": f"PA{u}", "name": "Project A"}),
        ("pb", "projects", {"code": f"PB{u}", "name": "Project B"}),
    ]:
        sc, M[key] = call("POST", f"master/{coll}", body, 200)
    return M


def item_ref(M, **over):
    """Field wajib Master Barang (kategori, divisi, satuan dasar) untuk fixture test."""
    return {"category_id": M["cat"]["id"], "division_id": M["div"]["id"], "base_uom_id": M["uom"]["id"], **over}


def make_po(M, supplier, qty, project="pa", item="item", mro_no=None, wh="wh"):
    mro_no = mro_no or f"MRO-{uuid.uuid4().hex[:6]}"
    sc, mro = call("POST", "mro", {"no": mro_no, "division_id": M["div"]["id"], "requester": "Budi", "submitted": True,
                                   "lines": [{"item_id": M[item]["id"], "qty": qty, "warehouse_id": M[wh]["id"],
                                              "project_id": M[project]["id"], "notes": "untuk mesin"}]}, 200)
    call("POST", f"mro/{mro['id']}/submit", {})
    ml = mro["lines"][0]
    sc, ro = call("POST", "ro", {"division_id": M["div"]["id"], "submitted": True,
                                 "lines": [{"item_id": M[item]["id"], "qty": qty, "warehouse_id": M[wh]["id"],
                                            "project_id": M[project]["id"], "notes": "untuk mesin",
                                            "sources": [{"mro_id": mro["id"], "line_id": ml["id"], "qty": qty}]}]}, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    rl = ro["lines"][0]
    sc, po = call("POST", "po", {"supplier_id": M[supplier]["id"], "division_id": M["div"]["id"],
                                 "lines": [{"item_id": M[item]["id"], "qty": qty, "price": 1000, "warehouse_id": M[wh]["id"],
                                            "project_id": M[project]["id"], "notes": "untuk mesin",
                                            "sources": [{"ro_id": ro["id"], "line_id": rl["id"], "qty": qty}]}]}, 200)
    call("POST", f"po/{po['id']}/submit", {})
    sc, d = call("GET", f"po/{po['id']}")
    if d.get("status") not in ("Approved",):
        call("POST", f"po/{po['id']}/approve", {})
        sc, d = call("GET", f"po/{po['id']}")
    return d, mro_no, ro["no"]


def do_body(M, po, qty, supplier, reason=None, dn=None, **over):
    l = po["lines"][0]
    line = {"po_id": po["id"], "po_line_id": l["id"], "item_id": l["item_id"], "qty": qty, "uom_id": l.get("uom_id"),
            "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"), "notes": l.get("notes"),
            "condition": "Baik", "exception_qty": 0,
            "sources": [{"po_id": po["id"], "line_id": l["id"], "qty": qty}]}
    if reason:
        line["over_receipt_reason"] = reason
    line.update(over)
    return {"supplier_id": M[supplier]["id"], "supplier_dn": dn or f"SJ-{uuid.uuid4().hex[:6]}",
            "default_warehouse_id": M["wh"]["id"], "lines": [line]}


def main():
    M = setup()
    po, mro_no, ro_no = make_po(M, "supX", 10)
    check("PO approved", po.get("status") == "Approved", po.get("status"))
    check("PO receipt Belum Diterima", po.get("receipt_status") == "Belum Diterima", po.get("receipt_status"))
    sc, pull = call("GET", f"pull/po-for-do?supplier_id={M['supX']['id']}")
    row = next((r for r in pull if r["po_id"] == po["id"]), {})
    check("Pull lineage MRO/RO present", row.get("mro_no") == mro_no and row.get("ro_no") == ro_no, row)
    # 47 mixed supplier
    poY, _, _ = make_po(M, "supY", 5)
    b = do_body(M, po, 1, "supX")
    b2 = do_body(M, poY, 1, "supX")
    b["lines"].append(b2["lines"][0])
    sc, r = call("POST", "do", b)
    check("47 mixed supplier DO rejected", sc == 400, f"{sc} {r}")
    # 50 source lock
    for k, v in (("warehouse_id", M["wh2"]["id"]), ("project_id", M["pb"]["id"]), ("notes", "diubah"), ("item_id", M["item2"]["id"])):
        sc, r = call("POST", "do", do_body(M, po, 1, "supX", **{k: v}))
        check(f"50 source lock {k} rejected", sc in (400, 404), f"{sc} {r}")
    sc, r = call("POST", "do", do_body(M, po, -1, "supX"))
    check("22 negative qty rejected", sc == 400, f"{sc}")
    # 51 normal: 6 then 4 -> full/closed
    sc, d1 = call("POST", "do", do_body(M, po, 6, "supX", dn="SJ-DUP-1"), 200)
    sc, p = call("GET", f"po/{po['id']}")
    check("Partial receipt Diterima Sebagian", p.get("receipt_status") == "Diterima Sebagian" and p.get("document_status") == "Approved", (p.get("receipt_status"), p.get("document_status")))
    sc, r = call("POST", "do", do_body(M, po, 1, "supX", dn="sj-dup-1 "))
    check("24 duplicate Supplier+Surat Jalan blocked", sc == 409, f"{sc} {r}")
    sc, d2 = call("POST", "do", do_body(M, po, 4, "supX"), 200)
    sc, p = call("GET", f"po/{po['id']}")
    check("51 full receipt -> Closed / Diterima Penuh", p.get("receipt_status") == "Diterima Penuh" and p.get("document_status") == "Closed", (p.get("receipt_status"), p.get("document_status")))
    check("10 PO qty unchanged", float(p["lines"][0]["qty"]) == 10)
    sc, pull = call("GET", "pull/po-for-do")
    check("53 closed PO not in picker", not any(r["po_id"] == po["id"] for r in pull))
    sc, r = call("POST", "do", do_body(M, po, 1, "supX", reason="lebih"))
    check("53 forced DO on closed PO rejected", sc == 409 and "ditutup" in str(r), f"{sc} {r}")

    # 52 over receipt: PO 10, prev 8, receive 3
    po2, _, _ = make_po(M, "supX", 10)
    call("POST", "do", do_body(M, po2, 8, "supX"), 200)
    sc, r = call("POST", "do", do_body(M, po2, 3, "supX"))
    check("52 over receipt without reason blocked", sc == 400 and "Alasan" in str(r), f"{sc} {r}")
    sc, d3 = call("POST", "do", do_body(M, po2, 3, "supX", reason="Bonus supplier"), 200)
    sc, p = call("GET", f"po/{po2['id']}")
    rc = p["lines"][0].get("receipt", {})
    check("52 received 11 over 1", abs(rc.get("received", 0) - 11) < 1e-6 and abs(rc.get("over", 0) - 1) < 1e-6, rc)
    check("52 Closed / Over Receipt", p.get("receipt_status") == "Over Receipt" and p.get("document_status") == "Closed", (p.get("receipt_status"), p.get("document_status")))
    hist = [h for h in p.get("receipt_history", []) if h.get("over_qty")]
    check("18 over receipt history with reason", hist and hist[0]["reason"] == "Bonus supplier" and hist[0]["do_no"] == d3.get("no"), hist)
    check("10 PO qty unchanged after over", float(p["lines"][0]["qty"]) == 10 and p.get("grand_total") == po2.get("grand_total"))
    sc, dd = call("GET", f"do/{d3['id']}")
    check("DO line stores over qty+reason", abs(float(dd["lines"][0].get("over_receipt_qty") or 0) - 1) < 1e-6 and dd["lines"][0].get("over_receipt_reason") == "Bonus supplier", dd["lines"][0])
    check("49 DO detail lineage", dd["lines"][0].get("lineage", {}).get("mro") and dd["lines"][0]["lineage"].get("ro"), dd["lines"][0].get("lineage"))
    # 54 reversal reopen
    sc, r = call("DELETE", f"transactions/do/{d3['id']}")
    sc, p = call("GET", f"po/{po2['id']}")
    check("54 delete DO reopens PO (Diterima Sebagian)", p.get("receipt_status") == "Diterima Sebagian" and p.get("document_status") == "Approved", (sc, p.get("receipt_status"), p.get("document_status")))
    sc, pull = call("GET", "pull/po-for-do")
    check("54 reopened PO eligible in picker", any(r["po_id"] == po2["id"] for r in pull))
    # 55 concurrency: remaining 2, two posts of 2
    out = []
    def post():
        out.append(S.post(f"{API}/do", json=do_body(M, po2, 2, "supX")).status_code)
    ts = [threading.Thread(target=post) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    sc, p = call("GET", f"po/{po2['id']}")
    rc = p["lines"][0].get("receipt", {})
    check("55 concurrent: exactly one succeeds", sorted(out) == [200, 409], out)
    check("55 no double consumption (received 10)", abs(rc.get("received", 0) - 10) < 1e-6, rc)
    # edit DO keeps working (edit d1 6 -> 6 same)
    sc, d1full = call("GET", f"do/{d1['id']}")
    eb = do_body(M, po, 6, "supX", dn="SJ-DUP-1")
    sc, r = call("PUT", f"transactions/do/{d1['id']}", eb)
    check("DO edit (same qty) allowed + duplicate DN ignores self", sc == 200, f"{sc} {r}")
    # list traceability
    sc, plist = call("GET", "po")
    pr = next((x for x in plist if x["id"] == po["id"]), {})
    check("26 PO list trace MRO/RO/Project/Divisi", pr.get("trace_mro") == mro_no and pr.get("trace_ro") == ro_no and pr.get("trace_project") == "Project A" and "Divisi Teknik" in pr.get("trace_division", ""), {k: pr.get(k) for k in ("trace_mro", "trace_ro", "trace_project", "trace_division")})
    check("19 PO list receipt status", pr.get("receipt_status") == "Diterima Penuh")
    check("33 PO list hover items", pr.get("items") and pr["items"][0]["qty"] == 10 and pr["items"][0]["project"] == "Project A", pr.get("items"))
    for mod in ("mro", "ro", "do", "mi", "transfers", "loans", "adjustments", "opname"):
        sc, rows = call("GET", mod)
        check(f"list {mod} 200 + trace fields", sc == 200 and all("trace_project" in x and "items" in x for x in rows), sc)
    sc, dl = call("GET", "do")
    drow = next((x for x in dl if x["id"] == d1["id"]), {})
    check("27 DO list trace MRO/RO/PO", drow.get("trace_mro") == mro_no and drow.get("trace_ro") == ro_no and drow.get("trace_po") == po.get("no"), {k: drow.get(k) for k in ("trace_mro", "trace_ro", "trace_po")})
    sc, ctx = call("GET", f"po/{po['id']}/email-context")
    check("45 email context default supplier email", sc == 200 and ctx.get("default_to") == "x@example.com", ctx)
    sc, rec = call("GET", "reports/valuation-reconcile")
    check("Valuation reconcile ok", sc == 200 and rec.get("ok") is True, str(rec)[:300])
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
