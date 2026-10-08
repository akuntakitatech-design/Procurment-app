"""Pinjam Barang multi-gudang — UAT backend lanjutan: Return (R1-R9), Draft lampiran (D1-D9), Legacy (LG1-LG14),
Ledger/Valuasi/Permission (V1-V8). Tenant QA sementara (paket business) — tidak menyentuh tenant lain / tidak reset DB.

Contoh transaksi sesuai UAT:
  Line 1: Item A  qty 10  Gudang A -> Gudang B  (P1, U1)
  Line 2: Item B  qty 8   Gudang A -> Gudang C  (P2, U2)
  Line 3: Item C  qty 6   Gudang D -> Gudang B  (P3, U3)
"""
import io
import os
import sys
import uuid
from pathlib import Path

from dotenv import dotenv_values

import receipt_control_test as T
import transfer_multi_warehouse_test as TM
from vendor_invoice_test import PW, U

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:6]
m, stock, opening, db_conn = TM.m, TM.stock, TM.opening, TM.db_conn
_ENV = dotenv_values("/app/backend/.env")
STORAGE_LOCAL = (_ENV.get("STORAGE_DRIVER") or "local").lower() == "local"
LOCAL_PATH = Path(_ENV.get("STORAGE_LOCAL_PATH") or "/app/data/uploads")


def sql(q, args=()):
    with db_conn() as cx, cx.cursor() as cur:
        cur.execute(q, args)
        return cur.fetchall()


def ledger(doc_id):
    _, led = call("GET", "inventory/ledger?limit=2000")
    return sorted((x.get("doc_type"), x.get("item_name"), x.get("warehouse_name"), float(x.get("qty_in") or 0), float(x.get("qty_out") or 0))
                  for x in led if x.get("doc_id") == doc_id and not x.get("is_reversal") and not x.get("reversed"))


def raw_ledger(doc_id):
    return sql("SELECT id, doc FROM stock_ledger WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.doc_id'))=%s ORDER BY id", (doc_id,))


def vrows(doc_no=None):
    _, vl = call("GET", "reports/valuation-ledger")
    rows = vl.get("rows", []) if isinstance(vl, dict) else vl
    return [x for x in rows if doc_no is None or x.get("doc_no") == doc_no]


def total_value():
    return round(sum(float(x.get("value_in") or 0) - float(x.get("value_out") or 0) for x in vrows()), 4)


def wh_value():
    out = {}
    for x in vrows():
        k = f"{x.get('item_name')}@{x.get('warehouse_name')}"
        out[k] = round(out.get(k, 0.0) + float(x.get("value_in") or 0) - float(x.get("value_out") or 0), 4)
    return {k: v for k, v in out.items() if abs(v) > 1e-9}


def att_rows(entity_id):
    return [tuple(r) for r in sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity')), JSON_UNQUOTE(JSON_EXTRACT(doc,'$.storage_path')) FROM attachments "
               "WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity_id'))=%s", (entity_id,))]


def pools_reconcile(item_ids):
    """Rekonsiliasi kronologis (urut 'at' insert): qty_after valuation ledger terakhir == stok fisik pool."""
    import json as _j
    bad = []
    for (doc,) in sql("SELECT doc FROM item_warehouse WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.item_id')) IN (" + ",".join(["%s"] * len(item_ids)) + ")", tuple(item_ids)):
        p = _j.loads(doc)
        rows = [_j.loads(d) for (d,) in sql("SELECT doc FROM valuation_ledger WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.item_id'))=%s AND JSON_UNQUOTE(JSON_EXTRACT(doc,'$.warehouse_id'))=%s", (p["item_id"], p["warehouse_id"]))]
        rows.sort(key=lambda r: r.get("at") or "")
        last = rows[-1] if rows else {}
        if abs(float(last.get("qty_after") or 0) - float(p.get("current_stock") or 0)) > 1e-9 or float(last.get("value_after") or 0) < -1e-9:
            bad.append((p["item_id"][:8], p.get("current_stock"), last.get("qty_after")))
    return bad


def obj_exists(path):
    return (LOCAL_PATH / path).exists() if STORAGE_LOCAL and path else None


def main():
    # ---------------- Tenant lain (cross-tenant)
    TM.register()
    other_hdr = dict(T.S.headers)

    # ---------------- Tenant QA
    T.S.headers.pop("Authorization", None)
    TM.register()
    asset = m("divisions", {"code": f"AS{u}", "name": "Asset"})
    ops = m("divisions", {"code": f"OP{u}", "name": "Operasional"})
    cat = m("item_categories", {"code": f"KC{u}", "name": "Umum"})
    uom = m("uoms", {"code": f"PC{u}", "name": "Pcs"})
    W = {k: m("warehouses", {"code": f"W{k}{u}", "name": f"Gudang {k}", "is_active": True,
                             "division_id": (ops if k == "C" else asset)["id"]}) for k in "ABCD"}
    P = {k: m("projects", {"code": f"P{k}{u}", "name": f"Project P{k}"}) for k in "123"}
    UN = {k: m("units", {"code": f"U{k}{u}", "name": f"Unit U{k}", "is_active": True}) for k in "123"}
    ref = {"category_id": cat["id"], "division_id": asset["id"], "base_uom_id": uom["id"], "unit": "PCS", "is_active": True}
    I = {n: m("items", {"code": f"I{n}{u}", "name": f"Item {n}", **ref}) for n in "ABC"}
    opening(W["A"]["id"], asset["id"], I["A"]["id"], 40, 1000)
    opening(W["A"]["id"], asset["id"], I["B"]["id"], 30, 500)
    opening(W["D"]["id"], asset["id"], I["C"]["id"], 20, 2000)
    OPEN_TOTAL = 40 * 1000 + 30 * 500 + 20 * 2000
    S = lambda n, w: stock(I[n]["id"], W[w]["id"])  # noqa: E731
    KEYS = ("A@A", "A@B", "B@A", "B@C", "C@B", "C@D")
    snap = lambda: {k: S(*k.split("@")) for k in KEYS}  # noqa: E731
    dlt = lambda a, b: {k: b[k] - a[k] for k in a if abs(b[k] - a[k]) > 1e-9}  # noqa: E731
    today = __import__("datetime").date.today().isoformat()
    head = {"date": today, "division_id": asset["id"], "project_id": P["1"]["id"], "from_warehouse_id": W["A"]["id"],
            "to_warehouse_id": W["B"]["id"], "due_date": today, "requester": "Budi QA", "notes": "UAT Return"}

    def L(item, qty, frm, to, p=None, un=None):
        return {"item_id": I[item]["id"], "qty": qty, "uom_id": uom["id"], "from_warehouse_id": W[frm]["id"] if frm else None,
                "to_warehouse_id": W[to]["id"] if to else None, "project_id": P[p]["id"] if p else None, "unit_id": UN[un]["id"] if un else None}

    STD = [L("A", 10, "A", "B", "1", "1"), L("B", 8, "A", "C", "2", "2"), L("C", 6, "D", "B", "3", "3")]

    def returns(loan_id):
        return call("GET", f"loans/{loan_id}/returns")[1]

    def lstate(loan_id):
        d = call("GET", f"loans/{loan_id}")[1]
        return {x["item_name"]: (x["qty"], x["returned"], x["outstanding"]) for x in d["lines"]}

    def ret(loan_id, pairs):
        return call("POST", f"loans/{loan_id}/return", {"date": today, "lines": [{"loan_line_id": a, "qty": q} for a, q in pairs]})

    # =============== DRAFT LAMPIRAN (D1, D2, D6) + Loan 1 =================
    sc, draft = call("POST", "attachment-drafts", {"module": "loan"})
    check("D1. Draft Loan dibuat sebelum ada Pinjaman (module loan)", sc == 200 and draft.get("module") == "loan" and not draft.get("bound_to"), draft)
    up = T.S.post(f"{API}/attachments", files={"file": ("bukti.pdf", io.BytesIO(b"%PDF-1.4 uat"), "application/pdf")},
                  data={"entity": "loan_draft", "entity_id": draft["id"], "category": "Lampiran Pinjaman"})
    check("D1. Upload langsung sebagai draft -> 200", up.status_code == 200, up.text[:100])
    path0 = att_rows(draft["id"])[0][1]
    n_loans = len(call("GET", "loans")[1])
    sc, r = call("POST", "loans", {**head, "lines": [L("A", 999, "A", "B")], "attachment_draft_id": draft["id"]})
    dr = sql("SELECT JSON_EXTRACT(doc,'$.bound_to'), JSON_EXTRACT(doc,'$.binding') FROM attachment_drafts WHERE id=%s", (draft["id"],))
    check("D2. Posting gagal -> 400 & Pinjaman tidak terbentuk", sc == 400 and len(call("GET", "loans")[1]) == n_loans, r)
    check("D2/D6. Draft TIDAK di-bind (bound_to null) & file tetap draft", dr and dr[0][0] in (None, "null") and att_rows(draft["id"]) == [("loan_draft", path0)], (dr, att_rows(draft["id"])))
    sc, lst = call("GET", f"attachments?entity=loan_draft&entity_id={draft['id']}")
    check("D2. File tetap terlihat di form (list draft = 1)", sc == 200 and len(lst) == 1, lst)
    s_before = snap(); v_before = total_value()
    sc, loan = call("POST", "loans", {**head, "lines": STD, "attachment_draft_id": draft["id"]})
    check("D2. Retry posting setelah diperbaiki -> 200", sc == 200 and len(loan.get("lines", [])) == 3, loan)
    fin = att_rows(loan["id"])
    check("D1/D2. Bind setelah sukses: tepat 1 lampiran final, path object sama (tanpa duplikat)", fin == [("loan", path0)], fin)
    check("D2. Tidak ada duplikat draft/attachment/object", sql("SELECT COUNT(*) FROM attachment_drafts WHERE id=%s", (draft["id"],))[0][0] == 1
          and len(att_rows(draft["id"])) == 0 and (obj_exists(path0) in (True, None)))
    dr = sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.bound_to')), JSON_EXTRACT(doc,'$.binding') FROM attachment_drafts WHERE id=%s", (draft["id"],))
    check("D1. Draft tidak lagi orphan (bound_to = loan_id, binding false)", dr and dr[0][0] == loan["id"] and dr[0][1] in ("false", 0, False), dr)
    sc, att = call("GET", f"attachments?entity=loan&entity_id={loan['id']}")
    check("D1. Lampiran muncul di detail Pinjaman", sc == 200 and len(att) == 1 and att[0].get("original_filename") == "bukti.pdf", att)
    sc, r = call("POST", "loans", {**head, "lines": [L("A", 1, "A", "B")], "attachment_draft_id": draft["id"]})
    check("D7. Replay: draft ter-bind dipakai Pinjaman lain -> 409", sc == 409, (sc, r))
    up2 = T.S.post(f"{API}/attachments", files={"file": ("x.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
                   data={"entity": "loan_draft", "entity_id": draft["id"]})
    check("D7. Upload ke draft yang sudah ter-bind -> 409", up2.status_code == 409, up2.status_code)
    check("D7. Satu file tidak menjadi lampiran di dua Pinjaman", sql("SELECT COUNT(*) FROM attachments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.storage_path'))=%s", (path0,))[0][0] == 1)

    # =============== LEDGER/VALUASI Loan baru (V1-V3) =================
    ll = {x["item_name"]: x for x in loan["lines"]}
    l1, l2, l3 = ll["Item A"]["id"], ll["Item B"]["id"], ll["Item C"]["id"]
    s0 = snap()
    check("V1. Stok setelah Loan: A@A-10, A@B+10, B@A-8, B@C+8, C@D-6, C@B+6",
          dlt(s_before, s0) == {"A@A": -10, "A@B": 10, "B@A": -8, "B@C": 8, "C@D": -6, "C@B": 6}, dlt(s_before, s0))
    exp = sorted([("Loan Out", "Item A", "Gudang A", 0, 10), ("Loan In", "Item A", "Gudang B", 10, 0),
                  ("Loan Out", "Item B", "Gudang A", 0, 8), ("Loan In", "Item B", "Gudang C", 8, 0),
                  ("Loan Out", "Item C", "Gudang D", 0, 6), ("Loan In", "Item C", "Gudang B", 6, 0)])
    check("V1. Stock ledger per LINE: A->B, A->C, D->B (tanpa duplikat)", ledger(loan["id"]) == exp, ledger(loan["id"]))
    rl = raw_ledger(loan["id"])
    check("V1. Ledger dapat ditelusuri: doc_id loan + line_id per baris", len(rl) == 6 and all(any(x in d for x in (l1, l2, l3)) for _, d in rl))
    vl = vrows(loan["no"])
    vin = {(x["item_name"], x["warehouse_name"]): float(x.get("value_in") or 0) for x in vl if float(x.get("qty_in") or 0) > 0}
    vout = {(x["item_name"], x["warehouse_name"]): float(x.get("value_out") or 0) for x in vl if float(x.get("qty_out") or 0) > 0}
    check("V2. Valuasi: nilai keluar pemberi = nilai masuk peminjam = qty x MWA asal",
          vout == {("Item A", "Gudang A"): 10000, ("Item B", "Gudang A"): 4000, ("Item C", "Gudang D"): 12000}
          and vin == {("Item A", "Gudang B"): 10000, ("Item B", "Gudang C"): 4000, ("Item C", "Gudang B"): 12000}, (vout, vin))
    check("V3. Total nilai persediaan tetap (internal, tanpa nilai tercipta/hilang)", abs(total_value() - OPEN_TOTAL) < 1e-6 and abs(v_before - OPEN_TOTAL) < 1e-6, total_value())

    # =============== RETURN R1-R6 =================
    n_ret = len(returns(loan["id"]))
    sc, r = ret(loan["id"], [(l1, 4)])
    s1 = snap()
    check("R1. Partial Return L1 4 dari 10 -> 200", sc == 200, r)
    check("R1/R6. Movement B -> A: A@B -4, A@A +4", dlt(s0, s1) == {"A@B": -4, "A@A": 4}, dlt(s0, s1))
    check("R1. returned 4, outstanding 6", lstate(loan["id"])["Item A"] == (10, 4, 6), lstate(loan["id"]))
    rs = returns(loan["id"]); r1 = rs[0]
    check("R1. Histori Return mencatat loan_line_id yang benar + arah B->A",
          len(rs) == n_ret + 1 and r1["lines"][0]["loan_line_id"] == l1 and r1["lines"][0]["return_from_name"] == "Gudang B" and r1["lines"][0]["return_to_name"] == "Gudang A", r1)
    check("R1. Ledger Return: OUT Gudang B, IN Gudang A", ledger(r1["id"]) == sorted([("Loan Return Out", "Item A", "Gudang B", 0, 4), ("Loan Return In", "Item A", "Gudang A", 4, 0)]), ledger(r1["id"]))
    rv = vrows(r1["no"])
    check("V4. Valuasi Return = qty x cost snapshot pinjaman (4 x 1000) keluar B, masuk A",
          {(x["warehouse_name"], float(x.get("value_in") or 0), float(x.get("value_out") or 0)) for x in rv} == {("Gudang B", 0.0, 4000.0), ("Gudang A", 4000.0, 0.0)}, rv)

    sc, r = ret(loan["id"], [(l2, 8)])
    s2 = snap()
    check("R2. Full Return L2 8 dari 8 -> 200", sc == 200, r)
    check("R2/R6. Movement C -> A: B@C -8, B@A +8", dlt(s1, s2) == {"B@C": -8, "B@A": 8}, dlt(s1, s2))
    check("R2. returned 8, outstanding 0 (line selesai)", lstate(loan["id"])["Item B"] == (8, 8, 0), lstate(loan["id"]))
    sc, rb = call("GET", f"loans/{loan['id']}/returnable")
    check("R5. Line outstanding 0 tidak muncul sebagai returnable", sc == 200 and all(x["loan_line_id"] != l2 for x in rb) and any(x["loan_line_id"] == l1 for x in rb), rb)
    check("R2. Histori Return L2 tetap ada", any(any(z["loan_line_id"] == l2 for z in x["lines"]) for x in returns(loan["id"])))

    ids3 = []
    for q in (2, 1, 3):
        sc, r = ret(loan["id"], [(l3, q)])
        check(f"R3. Multi-partial L3 Return qty {q} -> 200", sc == 200, r)
    s3 = snap()
    check("R3/R6. Total movement B -> D: C@B -6, C@D +6", dlt(s2, s3) == {"C@B": -6, "C@D": 6}, dlt(s2, s3))
    check("R3. returned kumulatif 6, outstanding 0", lstate(loan["id"])["Item C"] == (6, 6, 0), lstate(loan["id"]))
    r3s = [x for x in returns(loan["id"]) if any(z["loan_line_id"] == l3 for z in x["lines"])]
    led3 = sorted(tuple(ledger(x["id"])) for x in r3s)
    check("R3. 3 dokumen Return terpisah (histori tidak di-collapse), tiap dokumen movement B->D sendiri",
          len(r3s) == 3 and led3 == sorted(tuple(sorted([("Loan Return Out", "Item C", "Gudang B", 0, q), ("Loan Return In", "Item C", "Gudang D", q, 0)])) for q in (2, 1, 3)), led3)

    nr = len(returns(loan["id"])); nled = len(sql("SELECT id FROM stock_ledger"))
    sc, r = ret(loan["id"], [(l1, 7)])
    check("R4. Return 7 > outstanding 6 -> 400 (backend hard-block)", sc == 400 and "outstanding" in str(r.get("detail")).lower(), r)
    check("R4. Tidak ada stock movement / return record / perubahan outstanding",
          snap() == s3 and len(returns(loan["id"])) == nr and len(sql("SELECT id FROM stock_ledger")) == nled and lstate(loan["id"])["Item A"] == (10, 4, 6))
    for lid_, nm in ((l2, "L2"), (l3, "L3")):
        sc, r = ret(loan["id"], [(lid_, 1)])
        check(f"R5. Return manual ke {nm} (outstanding 0) -> 400, tanpa movement", sc == 400 and snap() == s3, (sc, r))
    sc, r = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": "line-palsu", "qty": 1}]})
    check("R5. loan_line_id tidak dikenal -> 400", sc == 400 and snap() == s3, (sc, r))

    # =============== R7 Mixed Return (Loan 2) =================
    sc, loan2 = call("POST", "loans", {**head, "lines": STD})
    k = {x["item_name"]: x["id"] for x in loan2["lines"]}
    s4 = snap()
    sc, r = ret(loan2["id"], [(k["Item A"], 2), (k["Item B"], 3), (k["Item C"], 1)])
    s5 = snap()
    check("R7. Satu Return mixed 3 line -> 200", sc == 200, r)
    check("R7. Tiap line sesuai pasangan gudangnya: B->A (2), C->A (3), B->D (1)",
          dlt(s4, s5) == {"A@B": -2, "A@A": 2, "B@C": -3, "B@A": 3, "C@B": -1, "C@D": 1}, dlt(s4, s5))
    rm = returns(loan2["id"])[0]
    check("R7. Satu dokumen Return berisi 3 arah sekaligus", len(rm["lines"]) == 3 and sorted((z["return_from_name"], z["return_to_name"]) for z in rm["lines"])
          == sorted([("Gudang B", "Gudang A"), ("Gudang C", "Gudang A"), ("Gudang B", "Gudang D")]), rm["lines"])
    check("R7. Ledger mixed 6 movement benar", ledger(rm["id"]) == sorted([
        ("Loan Return Out", "Item A", "Gudang B", 0, 2), ("Loan Return In", "Item A", "Gudang A", 2, 0),
        ("Loan Return Out", "Item B", "Gudang C", 0, 3), ("Loan Return In", "Item B", "Gudang A", 3, 0),
        ("Loan Return Out", "Item C", "Gudang B", 0, 1), ("Loan Return In", "Item C", "Gudang D", 1, 0)]), ledger(rm["id"]))
    check("V5. Return mixed: total nilai persediaan tetap", abs(total_value() - OPEN_TOTAL) < 1e-6, total_value())

    # =============== R8 Edit Return, R9 Hapus Return (Loan 3) =================
    sc, loan3 = call("POST", "loans", {**head, "lines": [L("A", 10, "A", "B", "1", "1")]})
    k3 = loan3["lines"][0]["id"]
    s6 = snap(); wv6 = wh_value()
    sc, r = ret(loan3["id"], [(k3, 4)])
    r8 = returns(loan3["id"])[0]
    check("R8. Return awal 4 -> outstanding 6", sc == 200 and lstate(loan3["id"])["Item A"] == (10, 4, 6))
    sc, cap = call("GET", f"loan-returns/{r8['id']}/capability")
    check("R8. Return baru dapat diedit/dihapus (capability)", sc == 200 and cap.get("can_edit") and cap.get("can_delete"), cap)
    sc, r = call("PUT", f"loan-returns/{r8['id']}", {"date": today, "lines": [{"loan_line_id": k3, "qty": 2}]})
    s7 = snap()
    check("R8. Edit Return 4 -> 2 -> 200", sc == 200, r)
    check("R8. returned 2, outstanding 8", lstate(loan3["id"])["Item A"] == (10, 2, 8), lstate(loan3["id"]))
    check("R8. Stok net vs sebelum Return: A@B -2, A@A +2 (reversal + posting ulang, tanpa double)", dlt(s6, s7) == {"A@B": -2, "A@A": 2}, dlt(s6, s7))
    check("R8. Ledger aktif Return = B->A qty 2", ledger(r8["id"]) == sorted([("Loan Return Out", "Item A", "Gudang B", 0, 2), ("Loan Return In", "Item A", "Gudang A", 2, 0)]), ledger(r8["id"]))
    rev = [d for _, d in raw_ledger(r8["id"]) if '"is_reversal": true' in d]
    check("R8. Reversal movement lama tercatat (2 baris reversal, gudang line asli B & A)", len(rev) == 2 and any(W["B"]["id"] in d for d in rev) and any(W["A"]["id"] in d for d in rev), len(rev))
    check("V6. Edit Return: nilai per gudang = sebelum Return +/- 2 x 1000", wh_value().get("Item A@Gudang B") == round(wv6.get("Item A@Gudang B", 0) - 2000, 4)
          and wh_value().get("Item A@Gudang A") == round(wv6.get("Item A@Gudang A", 0) + 2000, 4) and abs(total_value() - OPEN_TOTAL) < 1e-6, (wv6, wh_value()))
    sc, r = call("DELETE", f"loan-returns/{r8['id']}")
    s8 = snap()
    check("R9. Hapus Return -> 200; returned 0, outstanding 10", sc == 200 and lstate(loan3["id"])["Item A"] == (10, 0, 10), (sc, r, lstate(loan3["id"])))
    check("R9. Reversal ke gudang line asli: stok kembali = setelah Loan", s8 == s6, dlt(s6, s8))
    check("V6. Hapus Return: nilai per gudang kembali persis", wh_value() == wv6 and abs(total_value() - OPEN_TOTAL) < 1e-6, (wv6, wh_value()))

    # =============== Edit Loan reversal valuasi (V7) =================
    sc, e = call("POST", "loans", {**head, "lines": [L("B", 4, "A", "B", "1")]})
    se = snap(); we = wh_value()
    sc, r = call("PUT", f"transactions/loan/{e['id']}", {**head, "lines": [L("B", 4, "A", "C", "2")]})
    se2 = snap()
    check("V7. Edit Loan A->B jadi A->C: reversal gudang LINE asli + posting gudang LINE baru", sc == 200 and dlt(se, se2) == {"B@C": 4}
          and S("B", "B") == 0, (sc, r, dlt(se, se2)))
    check("V7. Edit Loan: ledger aktif tanpa double", ledger(e["id"]) == sorted([("Loan Out", "Item B", "Gudang A", 0, 4), ("Loan In", "Item B", "Gudang C", 4, 0)]), ledger(e["id"]))
    check("V7. Edit Loan: nilai B pindah ke C (2000), total tetap, tanpa orphan valuasi",
          wh_value().get("Item B@Gudang C", 0) == round(we.get("Item B@Gudang C", 0) + 2000, 4) and "Item B@Gudang B" not in wh_value()
          and abs(total_value() - OPEN_TOTAL) < 1e-6, wh_value())
    bad = pools_reconcile([I[n]["id"] for n in "ABC"])
    check("V7. Rekonsiliasi kronologis: qty fisik == qty_after valuasi terakhir di semua pool, tanpa nilai negatif", not bad, bad)

    # =============== LEGACY (LG1-LG14) =================
    def make_legacy(lines, strip_ids):
        sc_, lg_ = call("POST", "loans", {**head, "lines": lines})
        for x in lg_["lines"]:
            if x["id"] in strip_ids(lg_):
                sql("UPDATE loan_lines SET doc = JSON_REMOVE(doc, '$.from_warehouse_id', '$.to_warehouse_id', '$.project_id', '$.unit_id') WHERE id=%s", (x["id"],))
        sql("UPDATE loans SET doc = JSON_REMOVE(doc, '$.warehouse_source', '$.line_warehouse_ids') WHERE id=%s", (lg_["id"],))
        return lg_

    lg = make_legacy([L("A", 5, "A", "B", "1")], lambda d: [x["id"] for x in d["lines"]])
    lgl = lg["lines"][0]["id"]
    raw_before = sql("SELECT doc FROM loan_lines WHERE id=%s", (lgl,))[0][0]
    led_before = raw_ledger(lg["id"])
    sc, d = call("GET", f"loans/{lg['id']}")
    x = d["lines"][0]
    check("LG1/LG2. Legacy tanpa gudang line terbuka; detail fallback header (A->B, P1)", sc == 200 and (x["from_name"], x["to_name"], x["project_name"]) == ("Gudang A", "Gudang B", "Project P1")
          and x["legacy_header_warehouse"] is True and d["legacy_header_warehouse"] is True, x)
    sc, rb = call("GET", f"loans/{lg['id']}/returnable")
    check("LG4. Returnable legacy: arah fallback header B -> A", rb and rb[0]["return_direction"] == "Gudang B → Gudang A", rb)
    check("LG8. Outstanding legacy sama dengan data tersimpan (5 - 0)", (x["qty"], x["returned"], x["outstanding"]) == (5, 0, 5))
    sl = snap()
    sc, r = ret(lg["id"], [(lgl, 2)])
    check("LG5/LG6. Partial Return legacy 2 -> B->A via fallback header", sc == 200 and dlt(sl, snap()) == {"A@B": -2, "A@A": 2}, (sc, r, dlt(sl, snap())))
    sl2 = snap()
    sc, r = ret(lg["id"], [(lgl, 3)])
    check("LG7. Full Return legacy 3 -> outstanding 0, B->A", sc == 200 and dlt(sl2, snap()) == {"A@B": -3, "A@A": 3} and lstate(lg["id"])["Item A"] == (5, 5, 0), (sc, r))
    lrs = returns(lg["id"])
    check("LG5. Ledger Return legacy OUT Gudang B / IN Gudang A", all(ledger(z["id"])[0][2] == "Gudang A" and ledger(z["id"])[1][2] == "Gudang B" for z in lrs), [ledger(z["id"]) for z in lrs])
    raw_after = sql("SELECT JSON_EXTRACT(doc,'$.from_warehouse_id'), JSON_EXTRACT(doc,'$.to_warehouse_id'), JSON_EXTRACT(doc,'$.project_id') FROM loan_lines WHERE id=%s", (lgl,))[0]
    check("LG11. Tidak ada backfill: line legacy tetap tanpa gudang/project setelah baca + return", raw_after == (None, None, None), raw_after)
    hdr = sql("SELECT JSON_EXTRACT(doc,'$.warehouse_source') FROM loans WHERE id=%s", (lg["id"],))[0][0]
    check("LG11. Header legacy tidak ditandai ulang (tetap legacy)", hdr is None, hdr)
    check("LG12. Historical stock ledger Loan legacy tidak berubah (byte-identik)", raw_ledger(lg["id"]) == led_before)
    import json as _json
    _b, _a = _json.loads(raw_before), _json.loads(sql("SELECT doc FROM loan_lines WHERE id=%s", (lgl,))[0][0])
    _b.pop("returned", None); _a.pop("returned", None)
    check("LG11. Line legacy identik dengan data tersimpan (hanya 'returned' yang berubah oleh Return)", _a == _b, (_b, _a))

    # Mixed legacy: line 1 punya gudang line (A->C), line 2 tanpa gudang -> fallback header (A->B)
    mx = make_legacy([L("B", 2, "A", "C", "2"), L("A", 2, "A", "B")], lambda d: [d["lines"][1]["id"]])
    sc, d = call("GET", f"loans/{mx['id']}")
    pr = [(z["from_name"], z["to_name"], z["legacy_header_warehouse"]) for z in d["lines"]]
    check("LG9. Mixed legacy diputuskan PER LINE: line1 A->C (line), line2 A->B (header)", pr == [("Gudang A", "Gudang C", False), ("Gudang A", "Gudang B", True)], pr)
    sm = snap()
    sc, r = ret(mx["id"], [(d["lines"][0]["id"], 1), (d["lines"][1]["id"], 1)])
    check("LG9. Return mixed legacy: line1 C->A, line2 B->A", sc == 200 and dlt(sm, snap()) == {"B@C": -1, "B@A": 1, "A@B": -1, "A@A": 1}, (sc, r, dlt(sm, snap())))

    # Legacy ambiguous: 2 line item sama tanpa jejak return-line -> edit/hapus dikunci
    am = make_legacy([L("A", 2, "A", "B"), L("A", 2, "A", "B")], lambda d: [z["id"] for z in d["lines"]])
    sc, r = ret(am["id"], [(am["lines"][0]["id"], 1)])
    ra = returns(am["id"])[0]
    sql("DELETE FROM loan_return_lines WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.return_id'))=%s", (ra["id"],))
    sa = snap()
    ra = returns(am["id"])[0]
    sc, cap = call("GET", f"loan-returns/{ra['id']}/capability")
    sc1, _ = call("PUT", f"loan-returns/{ra['id']}", {"date": today, "lines": [{"loan_line_id": am["lines"][0]["id"], "qty": 1}]})
    sc2, _ = call("DELETE", f"loan-returns/{ra['id']}")
    check("LG10. legacy_ambiguous tetap terkunci (flag, capability false, PUT/DELETE 409, stok tetap)",
          ra.get("legacy_ambiguous") is True and cap.get("can_edit") is False and cap.get("can_delete") is False and sc1 == 409 and sc2 == 409 and snap() == sa,
          (ra.get("legacy_ambiguous"), cap, sc1, sc2))

    # Edit Loan legacy tanpa Return: reversal dari ledger asli (fallback header), posting ulang ke gudang LINE
    le = make_legacy([L("B", 3, "A", "B")], lambda d: [z["id"] for z in d["lines"]])
    sle = snap()
    sc, cap = call("GET", f"transactions/loan/{le['id']}/capability")
    sc, r = call("PUT", f"transactions/loan/{le['id']}", {**head, "lines": [L("B", 3, "A", "C")]})
    check("LG-edit. Edit Loan legacy (tanpa Return): B@B -3 kembali, B@C +3", cap.get("can_edit") and sc == 200 and dlt(sle, snap()) == {"B@C": 3}, (cap, sc, r, dlt(sle, snap())))
    sc, cap = call("GET", f"transactions/loan/{lg['id']}/capability")
    check("LG-edit. Loan legacy yang sudah punya Return tetap dikunci (guard existing)", sc == 200 and cap.get("can_edit") is False, cap)
    check("LG13. Total nilai persediaan tetap setelah seluruh skenario legacy", abs(total_value() - OPEN_TOTAL) < 1e-6, total_value())

    # =============== PERMISSION / TENANT (V8, R-perm, D4, D5) =================
    email = f"loanr_{u}@example.com"
    _, usr = call("POST", "users", {"email": email, "password": PW, "name": "QA Gudang Asset", "role": "warehouse"}, 200)
    call("PUT", f"access/users/{usr['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": [asset["id"]]}}, 200)
    C = U(email)
    sp = snap()
    sc, r = C("POST", f"loans/{loan2['id']}/return", {"date": today, "lines": [{"loan_line_id": k["Item A"], "qty": 1}]})
    check("R-perm. User divisi Asset: Return pada Pinjaman berisi gudang divisi lain (C) ditolak", sc in (403, 404) and snap() == sp, (sc, r))
    sc, own = C("POST", "loans", {**head, "lines": [L("A", 2, "A", "B", "1")]})
    sc, r = C("POST", f"loans/{own['id']}/return", {"date": today, "lines": [{"loan_line_id": own["lines"][0]["id"], "qty": 1}]})
    check("R-perm. User divisi Asset: Return pada Pinjaman dalam scope -> 200", sc == 200, (sc, r))
    sc, d = C("GET", f"loans/{own['id']}")
    check("V8. User tanpa izin Lihat Harga: API detail Pinjaman tidak membawa cost_snapshot/loan_value",
          sc == 200 and all("cost_snapshot" not in z and "loan_value" not in z for z in d["lines"]), d.get("lines"))
    sc, _ = C("GET", "reports/valuation-ledger")
    check("V8. User tanpa izin Lihat Harga: valuation ledger -> 403", sc == 403, sc)
    _, rows = C("GET", "inventory/ledger?limit=500")
    check("V8. Stock ledger (qty) tetap terlihat tanpa nilai", isinstance(rows, list) and all("value_in" not in z and "unit_cost" not in z for z in rows))
    sc, d = call("GET", f"loans/{own['id']}")
    check("V8. Admin (berizin) tetap melihat nilai pinjaman", sc == 200 and d["lines"][0].get("loan_value") == 2000, d["lines"][0].get("loan_value"))
    _, rr = C("GET", f"loans/{own['id']}/returns")
    sc, r = C("DELETE", f"loan-returns/{rr[0]['id']}")
    check("R-perm. User tanpa izin delete tidak bisa hapus Return (403)", sc == 403, (sc, r))

    # D4 cross-user (tenant sama)
    sc, dA = call("POST", "attachment-drafts", {"module": "loan"})
    upA = T.S.post(f"{API}/attachments", files={"file": ("rahasia-a.pdf", io.BytesIO(b"%PDF-1.4 a"), "application/pdf")},
                   data={"entity": "loan_draft", "entity_id": dA["id"]}).json()
    pathA = att_rows(dA["id"])[0][1]
    sc, r = C("GET", f"attachments?entity=loan_draft&entity_id={dA['id']}")
    check("D4. User B (tenant sama) lihat draft A -> 404", sc == 404, sc)
    upB = C.S.post(f"{API}/attachments", files={"file": ("b.pdf", io.BytesIO(b"%PDF-1.4 b"), "application/pdf")}, data={"entity": "loan_draft", "entity_id": dA["id"]})
    check("D4. User B upload ke draft A -> 404", upB.status_code == 404, upB.status_code)
    sc, r = C("DELETE", f"attachments/{upA['id']}")
    check("D4. User B hapus file draft A -> 404", sc == 404, sc)
    dl = C.S.get(f"{API}/attachments/{upA['id']}/download")
    check("D4. User B download file draft A -> 404", dl.status_code == 404, dl.status_code)
    sc, r = C("DELETE", f"attachment-drafts/{dA['id']}")
    check("D4. User B batalkan draft A -> 404", sc == 404, sc)
    sc, r = C("POST", "loans", {**head, "lines": [L("A", 1, "A", "B")], "attachment_draft_id": dA["id"]})
    check("D4. User B bind draft A ke Pinjaman -> 404 (tanpa Pinjaman terbentuk)", sc == 404, sc)
    check("D4. Draft A utuh setelah percobaan user B", len(att_rows(dA["id"])) == 1)

    # D5 cross-tenant
    mine = dict(T.S.headers)
    T.S.headers.clear(); T.S.headers.update(other_hdr)
    res = [call("GET", f"attachments?entity=loan_draft&entity_id={dA['id']}"), call("DELETE", f"attachments/{upA['id']}"),
           call("DELETE", f"attachment-drafts/{dA['id']}")]
    upX = T.S.post(f"{API}/attachments", files={"file": ("x.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")}, data={"entity": "loan_draft", "entity_id": dA["id"]})
    dlX = T.S.get(f"{API}/attachments/{upA['id']}/download")
    bx = call("POST", "loans", {**head, "lines": [L("A", 1, "A", "B")], "attachment_draft_id": dA["id"]})
    rx = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": l1, "qty": 1}]})
    T.S.headers.clear(); T.S.headers.update(mine)
    codes = [res[0][0], res[2][0], upX.status_code, dlX.status_code]
    check("D5. Tenant lain: read/cancel/upload/download draft -> ditolak (404)", all(c in (403, 404) for c in codes), codes)
    check("D5. Tenant lain: DELETE /attachments/{id} = no-op tenant-scoped (generic existing), tidak menghapus apa pun", res[1][0] in (200, 403, 404), res[1])
    check("D5. Tenant lain: bind draft -> ditolak", bx[0] in (400, 403, 404), bx[0])
    check("R-perm. Tenant lain: Return Pinjaman -> 404", rx[0] == 404, rx[0])
    blob = str(res) + upX.text + dlX.text + str(bx) + str(rx)
    check("D5. Tidak bocor filename / storage path / tenant_id / user_id", "rahasia-a" not in blob and pathA not in blob and usr["id"] not in blob
          and "tenant_id" not in blob)
    check("D5. Draft A tetap utuh (tidak soft-delete) setelah percobaan tenant lain", len(att_rows(dA["id"])) == 1
          and sql("SELECT JSON_EXTRACT(doc,'$.is_deleted') FROM attachments WHERE id=%s", (upA["id"],))[0][0] in ("false", 0, None) and lstate(loan["id"])["Item A"] == (10, 4, 6))

    # D3 batal -> row + object terhapus
    existed = obj_exists(pathA)
    sc, r = call("DELETE", f"attachment-drafts/{dA['id']}")
    check("D3. Batal: draft row & attachment row terhapus", sc == 200 and len(att_rows(dA["id"])) == 0
          and sql("SELECT COUNT(*) FROM attachment_drafts WHERE id=%s", (dA["id"],))[0][0] == 0, (sc, r))
    check("D3. Batal: object storage sementara terhapus" + ("" if STORAGE_LOCAL else " (driver non-local: dilewati)"),
          (existed is True and obj_exists(pathA) is False) if STORAGE_LOCAL else True, (existed, obj_exists(pathA)))
    sc, att = call("GET", f"attachments?entity=loan&entity_id={loan['id']}")
    check("D3. Batal tidak menyentuh lampiran final Pinjaman lain", sc == 200 and len(att) == 1 and obj_exists(path0) in (True, None))

    # D8 cleanup > 24 jam
    import datetime as _dt
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=25)).isoformat()
    sc, dO = call("POST", "attachment-drafts", {"module": "loan"})
    T.S.post(f"{API}/attachments", files={"file": ("lama.pdf", io.BytesIO(b"%PDF-1.4 old"), "application/pdf")}, data={"entity": "loan_draft", "entity_id": dO["id"]})
    pO = att_rows(dO["id"])[0][1]
    sql("UPDATE attachment_drafts SET doc = JSON_SET(doc, '$.created_at', %s) WHERE id IN (%s, %s)", (old, dO["id"], draft["id"]))
    call("POST", "attachment-drafts", {"module": "loan"})  # memicu cleanup
    check("D8. Draft orphan > 24 jam: row + lampiran draft terhapus", sql("SELECT COUNT(*) FROM attachment_drafts WHERE id=%s", (dO["id"],))[0][0] == 0
          and len(att_rows(dO["id"])) == 0)
    check("D8. Object orphan > 24 jam terhapus" + ("" if STORAGE_LOCAL else " (driver non-local: dilewati)"), obj_exists(pO) is False if STORAGE_LOCAL else True)
    check("D8. Draft lama yang SUDAH ter-bind + lampiran final aman dari cleanup",
          sql("SELECT COUNT(*) FROM attachment_drafts WHERE id=%s", (draft["id"],))[0][0] == 1 and att_rows(loan["id"]) == [("loan", path0)] and obj_exists(path0) in (True, None))

    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
