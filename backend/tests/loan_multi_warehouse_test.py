"""Pinjam Barang — multi gudang per item (HEADER = default, LINE = sumber posting/return).
Tenant QA sementara (paket business). Tidak menyentuh tenant lain. Nomor skenario mengikuti daftar tes wajib (1-30).
Skenario murni UI (10 refresh stok, 13 header tidak menimpa manual, 14 Terapkan Default) diuji di
frontend/src/lib/loanLines.test.mjs + UAT browser; di sini diverifikasi sisi backend-nya."""
import io
import os
import sys
import uuid

import receipt_control_test as T
import transfer_multi_warehouse_test as TM
from vendor_invoice_test import PW, U

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:6]
m, stock, opening, db_conn = TM.m, TM.stock, TM.opening, TM.db_conn


def sql(q, args=()):
    with db_conn() as cx, cx.cursor() as cur:
        cur.execute(q, args)
        return cur.fetchall()


def ledger(doc_id):
    _, led = call("GET", "inventory/ledger?limit=1000")
    return sorted((x.get("doc_type"), x.get("item_name"), x.get("warehouse_name"), float(x.get("qty_in") or 0), float(x.get("qty_out") or 0))
                  for x in led if x.get("doc_id") == doc_id)


def main():
    # ---------------- Tenant lain (isolasi)
    TM.register()
    other_wh = m("warehouses", {"code": f"OX{u}", "name": "Gudang Tenant Lain", "is_active": True})
    other_prj = m("projects", {"code": f"OP{u}", "name": "Project Tenant Lain"})
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
    pa = m("projects", {"code": f"PA{u}", "name": "Project A"})
    pb = m("projects", {"code": f"PB{u}", "name": "Project B"})
    p_ops = m("projects", {"code": f"PO{u}", "name": "Project Ops", "division_id": ops["id"]})
    unit = m("units", {"code": f"UN{u}", "name": "Excavator 01", "is_active": True})
    ref = {"category_id": cat["id"], "division_id": asset["id"], "base_uom_id": uom["id"], "unit": "PCS", "is_active": True}
    I = {n: m("items", {"code": f"{n[:2].upper()}{u}", "name": n, **ref}) for n in ("Bearing", "Oli", "Helm")}
    opening(W["A"]["id"], asset["id"], I["Bearing"]["id"], 10, 1000)
    opening(W["A"]["id"], asset["id"], I["Oli"]["id"], 20, 500)
    opening(W["D"]["id"], asset["id"], I["Helm"]["id"], 5, 2000)
    S = lambda n, w: stock(I[n]["id"], W[w]["id"])  # noqa: E731
    today = __import__("datetime").date.today().isoformat()
    head = {"date": today, "division_id": asset["id"], "project_id": pa["id"], "from_warehouse_id": W["A"]["id"],
            "to_warehouse_id": W["B"]["id"], "due_date": today, "requester": "Budi QA", "notes": "Pinjam multi gudang"}

    def L(item, qty, frm, to, project=None, unit_id=None):
        return {"item_id": I[item]["id"], "qty": qty, "uom_id": uom["id"], "from_warehouse_id": W[frm]["id"] if frm else None,
                "to_warehouse_id": W[to]["id"] if to else None, "project_id": project, "unit_id": unit_id}

    # ---------------- Hard-block sebelum ada penulisan (11, 12, wajib)
    n0 = len(call("GET", "loans")[1])
    sc, r = call("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B"), L("Helm", 1, "A", "B")]})
    check("11. Qty > stok Gudang Pemberi LINE (Helm di A = 0) -> 400", sc == 400 and "Baris 2" in str(r.get("detail")) and "Gudang A" in str(r.get("detail")), r)
    check("11. Gagal = atomic: tidak ada dokumen & stok baris 1 tidak berubah", len(call("GET", "loans")[1]) == n0 and S("Bearing", "A") == 10)
    sc, r = call("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "A")]})
    check("12. Gudang Pemberi == Peminjam pada line -> 400", sc == 400 and "tidak boleh sama" in str(r.get("detail")), r)
    sc, r = call("POST", "loans", {"date": today, "division_id": asset["id"], "lines": [L("Bearing", 1, None, None)]})
    check("Line tanpa gudang & tanpa default header -> 400 Gudang Pemberi wajib", sc == 400 and "Gudang Pemberi wajib" in str(r.get("detail")), r)
    sc, r = call("POST", "loans", {**head, "lines": [{**L("Bearing", 1, "A", "B"), "to_warehouse_id": other_wh["id"]}]})
    check("30. Gudang tenant lain pada line ditolak", sc == 400 and "tidak ditemukan" in str(r.get("detail")), r)
    sc, r = call("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B", project=other_prj["id"])]})
    check("30. Project tenant lain pada line ditolak", sc == 400 and "Project" in str(r.get("detail")), r)
    sc, r = call("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B", unit_id="unit-palsu")]})
    check("30. Unit/Aset tidak dikenal pada line ditolak", sc == 400 and "Unit/Aset" in str(r.get("detail")), r)

    # ---------------- Draft lampiran sebelum posting (25)
    sc, draft = call("POST", "attachment-drafts", {"module": "loan", "tenant_id": "tenant-palsu", "owner_id": "user-palsu"})
    check("25. Draft lampiran Loan dibuat (UUID v4, module loan)", sc == 200 and uuid.UUID(draft["id"]).version == 4 and draft.get("module") == "loan", draft)
    up = T.S.post(f"{API}/attachments", files={"file": ("bukti-pinjam.pdf", io.BytesIO(b"%PDF-1.4 qa"), "application/pdf")},
                  data={"entity": "loan_draft", "entity_id": draft["id"], "category": "Lampiran Pinjaman"})
    check("25. Upload ke draft Loan sebelum posting -> 200", up.status_code == 200, up.text[:120])
    bad = T.S.post(f"{API}/attachments", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
                   data={"entity": "loan_draft", "entity_id": draft["id"]})
    check("25. Rule tipe file existing tetap berlaku untuk draft Loan (.exe ditolak)", bad.status_code == 400)
    sc, r = call("POST", "transfers", {"date": today, "division_id": asset["id"], "from_warehouse_id": W["A"]["id"], "to_warehouse_id": W["B"]["id"],
                                       "lines": [L("Bearing", 1, "A", "B")], "attachment_draft_id": draft["id"]})
    check("29. Draft Loan tidak bisa dipakai modul Transfer (404)", sc == 404, (sc, r))

    # Posting gagal -> draft tetap draft (27)
    sc, r = call("POST", "loans", {**head, "lines": [L("Bearing", 999, "A", "B")], "attachment_draft_id": draft["id"]})
    check("27. Posting gagal (stok) -> 400, Pinjaman tidak terbentuk", sc == 400 and len(call("GET", "loans")[1]) == n0, r)
    sc, lst = call("GET", f"attachments?entity=loan_draft&entity_id={draft['id']}")
    check("27. Lampiran tetap draft setelah posting gagal", sc == 200 and len(lst) == 1, lst)

    # ---------------- Satu Pinjaman A->B, A->C, D->B (6, 7, 8) + bind lampiran (26)
    lines = [L("Bearing", 5, "A", "B", pa["id"]), L("Oli", 10, "A", "C", pa["id"]), L("Helm", 3, "D", "B", pb["id"], unit["id"])]
    sc, loan = call("POST", "loans", {**head, "lines": lines, "attachment_draft_id": draft["id"]})
    check("6. Satu Pinjaman A->B, A->C, D->B -> 200", sc == 200 and len(loan.get("lines", [])) == 3, loan)
    pairs = [(x["from_name"], x["to_name"]) for x in loan["lines"]]
    check("7. Line menyimpan & membaca gudang LINE", pairs == [("Gudang A", "Gudang B"), ("Gudang A", "Gudang C"), ("Gudang D", "Gudang B")], pairs)
    check("7. Stok: A -15, D -3, B +8, C +10",
          (S("Bearing", "A"), S("Oli", "A"), S("Helm", "D"), S("Bearing", "B"), S("Helm", "B"), S("Oli", "C")) == (5, 10, 2, 5, 3, 10))
    led = ledger(loan["id"])
    exp = sorted([("Loan Out", "Bearing", "Gudang A", 0, 5), ("Loan In", "Bearing", "Gudang B", 5, 0), ("Loan Out", "Oli", "Gudang A", 0, 10),
                  ("Loan In", "Oli", "Gudang C", 10, 0), ("Loan Out", "Helm", "Gudang D", 0, 3), ("Loan In", "Helm", "Gudang B", 3, 0)])
    check("8. Stock ledger benar per line", led == exp, led)
    sc, vl = call("GET", "reports/valuation-ledger")
    vrows = [x for x in (vl if isinstance(vl, list) else vl.get("rows", [])) if x.get("doc_id") == loan["id"] or x.get("doc_no") == loan["no"]]
    vin = sum(float(x.get("value_in") or 0) for x in vrows if float(x.get("qty_in") or 0) > 0)
    check("MWA. Nilai Loan In = MWA asal (5x1000 + 10x500 + 3x2000 = 16000), tanpa formula baru", abs(vin - 16000) < 1e-6, vin)
    sc, att = call("GET", f"attachments?entity=loan&entity_id={loan['id']}")
    check("26. Posting sukses: lampiran draft terikat ke Pinjaman final", sc == 200 and len(att) == 1 and att[0].get("original_filename") == "bukti-pinjam.pdf", att)
    sc, lst = call("GET", f"attachments?entity=loan_draft&entity_id={draft['id']}")
    check("26. Draft tidak lagi berisi lampiran (sudah final)", sc == 200 and len(lst) == 0, lst)
    sc, r = call("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B")], "attachment_draft_id": draft["id"]})
    check("26. Draft yang sudah terikat tidak bisa di-bind ulang (409)", sc == 409, (sc, r))
    sc, ln = call("GET", "loans")
    row = next((x for x in ln if x["id"] == loan["id"]), {})
    check("24. List: ringkasan gudang dari LINE (Gudang A +1 / Gudang B +1, multi)", row.get("from_name") == "Gudang A +1" and row.get("to_name") == "Gudang B +1" and row.get("multi_warehouse") is True, row)
    sc, d = call("GET", f"loans/{loan['id']}")
    check("24. Detail/print data: project & unit per line + header default",
          [x.get("project_name") for x in d["lines"]] == ["Project A", "Project A", "Project B"] and d["lines"][2].get("unit_name") == "Excavator 01"
          and d.get("project_name") == "Project A" and d.get("from_name") == "Gudang A" and d.get("requester") == "Budi QA" and d.get("due_date") == today, d)

    # ---------------- Default header -> line (1-4) via API
    sc, l2 = call("POST", "loans", {**head, "lines": [{"item_id": I["Bearing"]["id"], "qty": 1, "uom_id": uom["id"], "project_id": pa["id"]}]})
    check("1/4. Line tanpa gudang -> diisi Gudang Pemberi/Peminjam Default & disimpan eksplisit", sc == 200 and l2["lines"][0]["from_warehouse_id"] == W["A"]["id"]
          and l2["lines"][0]["to_warehouse_id"] == W["B"]["id"] and l2["lines"][0]["legacy_header_warehouse"] is False, l2)
    raw = sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.from_warehouse_id')), JSON_UNQUOTE(JSON_EXTRACT(doc,'$.project_id')) FROM loan_lines WHERE id=%s", (l2["lines"][0]["id"],))
    check("3. Project line tersimpan eksplisit di line", raw and raw[0][0] == W["A"]["id"] and raw[0][1] == pa["id"], raw)
    sc, l3 = call("POST", "loans", {**head, "lines": [{**L("Bearing", 1, "A", "B"), "project_id": None}]})
    check("2/16. Transaksi BARU: project line kosong TIDAK di-fallback ke header", sc == 200 and l3["lines"][0]["project_id"] is None, l3.get("lines"))

    # ---------------- Return (15-20)
    ll = {x["item_name"]: x for x in loan["lines"]}
    sc, rows = call("GET", f"loans/{loan['id']}/returnable")
    rb = next((x for x in rows if x["loan_line_id"] == ll["Bearing"]["id"]), {})
    check("Dialog Return: konteks line (pemberi/peminjam/project/unit/arah)", rb.get("from_name") == "Gudang A" and rb.get("to_name") == "Gudang B"
          and rb.get("project_name") == "Project A" and rb.get("return_direction") == "Gudang B → Gudang A", rb)
    snap = lambda: {k: S(*k.split("@")) for k in ("Bearing@A", "Bearing@B", "Oli@A", "Oli@C", "Helm@B", "Helm@D")}  # noqa: E731
    s0 = snap()
    dlt = lambda a, b: {k: b[k] - a[k] for k in a if b[k] != a[k]}  # noqa: E731
    sc, r = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": ll["Bearing"]["id"], "qty": 2}]})
    check("15/18. Partial return line A->B (2 dari 5) -> 200", sc == 200, r)
    _, rets = call("GET", f"loans/{loan['id']}/returns")
    ret1 = rets[0]
    s1 = snap()
    check("15. Return line A->B = B->A (Bearing B -2, A +2)", dlt(s0, s1) == {"Bearing@B": -2, "Bearing@A": 2}, dlt(s0, s1))
    check("15. Ledger return A->B: OUT Gudang B, IN Gudang A",
          ledger(ret1["id"]) == sorted([("Loan Return Out", "Bearing", "Gudang B", 0, 2), ("Loan Return In", "Bearing", "Gudang A", 2, 0)]), ledger(ret1["id"]))
    check("Histori Return memuat arah gudang line", ret1["lines"][0].get("return_from_name") == "Gudang B" and ret1["lines"][0].get("return_to_name") == "Gudang A", ret1)
    sc, r = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": ll["Oli"]["id"], "qty": 10}, {"loan_line_id": ll["Helm"]["id"], "qty": 1}]})
    check("16/17. Full return line A->C + partial D->B -> 200", sc == 200, r)
    s2 = snap()
    check("16. Return line A->C = C->A (Oli C -10, A +10)", {k: v for k, v in dlt(s1, s2).items() if k.startswith("Oli")} == {"Oli@C": -10, "Oli@A": 10}, dlt(s1, s2))
    check("17. Return line D->B = B->D (Helm B -1, D +1)", {k: v for k, v in dlt(s1, s2).items() if k.startswith("Helm")} == {"Helm@B": -1, "Helm@D": 1}, dlt(s1, s2))
    sc, r = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": ll["Bearing"]["id"], "qty": 4}]})
    check("20. Return > outstanding line (4 > 3) -> 400", sc == 400 and "outstanding" in str(r.get("detail")).lower(), r)
    sc, d = call("GET", f"loans/{loan['id']}")
    outs = {x["item_name"]: (x["returned"], x["outstanding"]) for x in d["lines"]}
    check("18. Outstanding per line terjaga (Bearing 2/3, Oli 10/0, Helm 1/2)", outs == {"Bearing": (2, 3), "Oli": (10, 0), "Helm": (1, 2)}, outs)
    for q in (1, 2):
        sc, r = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": ll["Bearing"]["id"], "qty": q}]})
        check(f"19. Partial return berikutnya Bearing qty {q} -> 200", sc == 200, r)
    sc, d = call("GET", f"loans/{loan['id']}")
    bl = next(x for x in d["lines"] if x["item_name"] == "Bearing")
    s3 = snap()
    check("19. Multiple partial return sampai outstanding 0 (Bearing total B -5, A +5)", bl["outstanding"] == 0 and bl["returned"] == 5
          and dlt(s0, s3).get("Bearing@B") == -5 and dlt(s0, s3).get("Bearing@A") == 5, (bl.get("outstanding"), dlt(s0, s3)))
    sc, r = call("POST", f"loans/{loan['id']}/return", {"date": today, "lines": [{"loan_line_id": ll["Bearing"]["id"], "qty": 1}]})
    check("20. Return saat outstanding 0 -> 400", sc == 400, r)

    # Edit/hapus Return: reversal & posting ulang memakai gudang line asli
    _, rets = call("GET", f"loans/{loan['id']}/returns")
    r_helm = next(x for x in rets if any(l.get("loan_line_id") == ll["Helm"]["id"] for l in x["lines"]))
    sc, r = call("PUT", f"loan-returns/{r_helm['id']}", {"date": today, "lines": [{"loan_line_id": ll["Oli"]["id"], "qty": 10}, {"loan_line_id": ll["Helm"]["id"], "qty": 2}]})
    s4 = snap()
    check("21. Edit Return (Helm 1->2): reversal + posting ulang B->D (Helm B -1, D +1; Oli tetap)", sc == 200 and dlt(s3, s4) == {"Helm@B": -1, "Helm@D": 1}, (sc, r, dlt(s3, s4)))
    sc, r = call("DELETE", f"loan-returns/{r_helm['id']}")
    s5 = snap()
    check("21. Hapus Return: reversal ke gudang line asli (Helm B +2, D -2; Oli C +10, A -10)",
          sc == 200 and dlt(s4, s5) == {"Helm@B": 2, "Helm@D": -2, "Oli@C": 10, "Oli@A": -10}, (sc, r, dlt(s4, s5)))

    # Edit Pinjaman ber-Return dikunci (guard existing)
    sc, cap = call("GET", f"transactions/loan/{loan['id']}/capability")
    check("21. Pinjaman yang sudah punya Return: edit/hapus dikunci (guard existing)", sc == 200 and cap.get("can_edit") is False, cap)

    # Edit Pinjaman tanpa Return: reversal gudang line asli lalu posting gudang line baru (tanpa double movement)
    sc, e = call("POST", "loans", {**head, "lines": [L("Oli", 4, "A", "B", pa["id"])]})
    before = (S("Oli", "A"), S("Oli", "B"), S("Oli", "C"))
    sc, r = call("PUT", f"transactions/loan/{e['id']}", {**head, "lines": [L("Oli", 4, "D", "C", pb["id"])]})
    check("21. Edit gagal (stok Oli di D = 0) -> 400 tanpa perubahan stok", sc == 400 and (S("Oli", "A"), S("Oli", "B"), S("Oli", "C")) == before, (sc, r))
    sc, r = call("PUT", f"transactions/loan/{e['id']}", {**head, "lines": [L("Oli", 4, "A", "C", pb["id"])]})
    check("21. Edit line A->B jadi A->C: B kembali, C bertambah (tanpa double movement)", sc == 200 and (S("Oli", "A"), S("Oli", "B"), S("Oli", "C")) == (before[0], before[1] - 4, before[2] + 4), (sc, r))
    eled = [x for x in ledger(e["id"])]
    sc, ed = call("GET", f"loans/{e['id']}")
    check("21. Setelah edit: line baru A->C, project B", ed["lines"][0]["from_name"] == "Gudang A" and ed["lines"][0]["to_name"] == "Gudang C" and ed["lines"][0]["project_name"] == "Project B", ed["lines"])

    # ---------------- Legacy (22, 23)
    sc, lg = call("POST", "loans", {**head, "lines": [L("Bearing", 2, "A", "B", pa["id"])]})
    lid = lg["lines"][0]["id"]
    sql("UPDATE loan_lines SET doc = JSON_REMOVE(doc, '$.from_warehouse_id', '$.to_warehouse_id', '$.project_id') WHERE id=%s", (lid,))
    sql("UPDATE loans SET doc = JSON_REMOVE(doc, '$.warehouse_source', '$.line_warehouse_ids') WHERE id=%s", (lg["id"],))
    sc, lgd = call("GET", f"loans/{lg['id']}")
    check("22. Legacy Loan terbaca (fallback header, ditandai legacy)", sc == 200 and lgd["lines"][0]["from_name"] == "Gudang A" and lgd["lines"][0]["to_name"] == "Gudang B"
          and lgd["lines"][0]["project_name"] == "Project A" and lgd["lines"][0]["legacy_header_warehouse"] is True and lgd["legacy_header_warehouse"] is True, lgd.get("lines"))
    raw = sql("SELECT JSON_EXTRACT(doc,'$.from_warehouse_id'), JSON_EXTRACT(doc,'$.project_id') FROM loan_lines WHERE id=%s", (lid,))
    check("22. Legacy: data asli TIDAK diubah oleh pembacaan", raw[0][0] is None and raw[0][1] is None, raw)
    b0 = (S("Bearing", "A"), S("Bearing", "B"))
    sc, r = call("POST", f"loans/{lg['id']}/return", {"date": today, "lines": [{"loan_line_id": lid, "qty": 1}]})
    check("23. Legacy Return bekerja via fallback header (B->A)", sc == 200 and (S("Bearing", "A"), S("Bearing", "B")) == (b0[0] + 1, b0[1] - 1), (sc, r))

    # ---------------- Permission / scope (29, 30)
    email = f"loanw_{u}@example.com"
    _, usr = call("POST", "users", {"email": email, "password": PW, "name": "QA Gudang Asset", "role": "warehouse"}, 200)
    call("PUT", f"access/users/{usr['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": [asset["id"]]}}, 200)
    C = U(email)
    sc, r = C("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "C")]})
    check("30. User divisi Asset: Gudang Peminjam line di divisi lain -> 403", sc == 403, (sc, r))
    sc, r = C("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B", project=p_ops["id"])]})
    check("30. User divisi Asset: Project line divisi lain -> 403", sc == 403, (sc, r))
    sc, r = C("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B", pa["id"])]})
    check("30. User divisi Asset: A->B dalam scope -> 200", sc == 200, (sc, r))
    sc, r = C("GET", f"loans/{loan['id']}")
    check("30. Pinjaman berisi gudang line divisi lain tidak terlihat user divisi Asset", sc in (403, 404), sc)
    sc, lst = C("GET", "loans")
    check("30. List user divisi Asset tidak memuat Pinjaman multi-divisi", sc == 200 and all(x["id"] != loan["id"] for x in lst))
    sc, d4 = call("POST", "attachment-drafts", {"module": "loan"})
    sc, r = C("GET", f"attachments?entity=loan_draft&entity_id={d4['id']}")
    check("29. User lain (tenant sama) tidak bisa membaca draft Loan orang lain", sc == 404, sc)
    sc, r = C("POST", "loans", {**head, "lines": [L("Bearing", 1, "A", "B")], "attachment_draft_id": d4["id"]})
    check("29. User lain tidak bisa bind draft Loan orang lain", sc == 404, sc)
    mine = dict(T.S.headers)
    T.S.headers.clear(); T.S.headers.update(other_hdr)
    sc, r = call("GET", f"attachments?entity=loan_draft&entity_id={d4['id']}")
    check("29. Tenant lain tidak bisa membaca draft Loan (404)", sc == 404, sc)
    sc, r = call("GET", f"loans/{loan['id']}")
    check("30. Tenant lain tidak bisa membuka Pinjaman (404)", sc == 404, sc)
    sc, r = call("DELETE", f"attachment-drafts/{d4['id']}")
    check("29. Tenant lain tidak bisa membatalkan draft Loan (404)", sc == 404, sc)
    T.S.headers.clear(); T.S.headers.update(mine)

    # ---------------- Batal (28) + cleanup > 24 jam
    T.S.post(f"{API}/attachments", files={"file": ("foto.png", io.BytesIO(b"\x89PNG qa"), "image/png")}, data={"entity": "loan_draft", "entity_id": d4["id"]})
    paths = [p for (p,) in sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.storage_path')) FROM attachments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity_id'))=%s", (d4["id"],))]
    sc, r = call("DELETE", f"attachment-drafts/{d4['id']}")
    left = sql("SELECT COUNT(*) FROM attachments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity_id'))=%s", (d4["id"],))[0][0]
    dr = sql("SELECT COUNT(*) FROM attachment_drafts WHERE id=%s", (d4["id"],))[0][0]
    check("28. Batal: draft + row lampiran draft dihapus", sc == 200 and left == 0 and dr == 0 and len(paths) == 1, (sc, left, dr))
    import datetime as _dt
    sc, d5 = call("POST", "attachment-drafts", {"module": "loan"})
    T.S.post(f"{API}/attachments", files={"file": ("lama.pdf", io.BytesIO(b"%PDF-1.4 old"), "application/pdf")}, data={"entity": "loan_draft", "entity_id": d5["id"]})
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=25)).isoformat()
    sql("UPDATE attachment_drafts SET doc = JSON_SET(doc, '$.created_at', %s) WHERE id=%s", (old, d5["id"]))
    call("POST", "attachment-drafts", {"module": "loan"})  # memicu cleanup draft loan > 24 jam
    check("28. Cleanup draft Loan > 24 jam: draft & lampiran draft dihapus",
          sql("SELECT COUNT(*) FROM attachment_drafts WHERE id=%s", (d5["id"],))[0][0] == 0
          and sql("SELECT COUNT(*) FROM attachments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity_id'))=%s", (d5["id"],))[0][0] == 0)
    sc, att = call("GET", f"attachments?entity=loan&entity_id={loan['id']}")
    check("28. Lampiran final Pinjaman tidak tersentuh cleanup", sc == 200 and len(att) == 1, att)
    # opname kini resmi memakai draft lampiran (Stock Opname hardening); modul yang tidak terdaftar tetap ditolak.
    sc, r = call("POST", "attachment-drafts", {"module": "invoice"})
    check("Modul draft lain (tidak terdaftar) tetap ditolak", sc == 400, (sc, r))

    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
