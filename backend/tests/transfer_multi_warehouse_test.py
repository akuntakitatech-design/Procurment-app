"""Transfer Antar Gudang — multi gudang per item (HEADER = default, LINE = sumber posting).
Tenant QA sementara (paket business: >2 gudang). Tidak menyentuh tenant lain."""
import io
import os
import sys
import uuid
from urllib.parse import urlparse

import pymysql
import receipt_control_test as T
import requests
from dotenv import dotenv_values
from vendor_invoice_test import PW, U

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:6]


def register(plan="business"):
    v = uuid.uuid4().hex[:8]
    email = f"trf_{v}@example.com"
    call("POST", "saas/register", {"company_name": f"TRF {v}", "pic_name": "QA", "email": email, "whatsapp": "+628123456789",
                                   "workspace_slug": f"trf-{v}", "plan_code": plan, "password": "TestPass123!", "address": "x",
                                   "terms_accepted": True}, 200)
    T.S.cookies.clear()
    tok = requests.post(f"{API}/auth/login", json={"email": email, "password": "TestPass123!"}).json().get("token")
    T.S.headers.update({"Authorization": f"Bearer {tok}"})
    return email


def m(coll, body):
    return call("POST", f"master/{coll}", body, 200)[1]


def stock(item_id, wh_id):
    _, r = call("GET", f"stock/by-warehouse/{item_id}")
    row = next((w for w in (r or {}).get("warehouses", []) if w.get("warehouse_id") == wh_id), None)
    return float((row or {}).get("stock") or 0)


def opening(wh, div, item, qty, cost):
    return call("POST", "adjustments", {"date": "2026-09-20", "warehouse_id": wh, "division_id": div, "adj_type": "Opening",
                                        "reason": "QA opening transfer", "notes": "TRF MULTI TEST",
                                        "lines": [{"item_id": item, "adjustment": qty, "reason": "QA", "approved_unit_cost": cost}]}, 200)


def db_conn():
    url = urlparse(dotenv_values("/app/backend/.env").get("DATABASE_URL"))
    return pymysql.connect(host=url.hostname, port=url.port or 3306, user=url.username, password=url.password,
                           database=url.path.lstrip("/"), autocommit=True)


def main():
    # ---------------- Tenant lain (untuk uji isolasi)
    register()
    other_wh = m("warehouses", {"code": f"OX{u}", "name": "Gudang Tenant Lain", "is_active": True})
    other_hdr = dict(T.S.headers)

    # ---------------- Tenant QA
    T.S.headers.pop("Authorization", None)
    register()
    asset = m("divisions", {"code": f"AS{u}", "name": "Asset"})
    ops = m("divisions", {"code": f"OP{u}", "name": "Operasional"})
    cat = m("item_categories", {"code": f"KC{u}", "name": "Umum"})
    uom = m("uoms", {"code": f"PC{u}", "name": "Pcs"})
    W = {k: m("warehouses", {"code": f"W{k}{u}", "name": f"Gudang {k}", "is_active": True,
                             "division_id": (asset if k in "AB" else ops)["id"]}) for k in "ABCD"}
    pa = m("projects", {"code": f"PA{u}", "name": "Project A"})
    pb = m("projects", {"code": f"PB{u}", "name": "Project B"})
    unit = m("units", {"code": f"UN{u}", "name": "Excavator 01", "is_active": True})
    ref = {"category_id": cat["id"], "division_id": asset["id"], "base_uom_id": uom["id"], "unit": "PCS", "is_active": True}
    I = {n: m("items", {"code": f"{n[:2].upper()}{u}", "name": n, **ref}) for n in ("Bearing", "Oli", "Helm")}
    opening(W["A"]["id"], asset["id"], I["Bearing"]["id"], 10, 1000)
    opening(W["A"]["id"], asset["id"], I["Oli"]["id"], 20, 500)
    opening(W["D"]["id"], ops["id"], I["Helm"]["id"], 5, 2000)
    check("Setup: stok opening", stock(I["Bearing"]["id"], W["A"]["id"]) == 10 and stock(I["Helm"]["id"], W["D"]["id"]) == 5)

    def L(item, qty, frm, to, project=None, unit_id=None):
        return {"item_id": I[item]["id"], "qty": qty, "uom_id": uom["id"], "from_warehouse_id": W[frm]["id"] if frm else None,
                "to_warehouse_id": W[to]["id"] if to else None, "project_id": project, "unit_id": unit_id, "notes": f"{item} {frm}->{to}"}
    head = {"date": __import__("datetime").date.today().isoformat(), "division_id": asset["id"], "project_id": pa["id"], "from_warehouse_id": W["A"]["id"],
            "to_warehouse_id": W["B"]["id"], "notes": "Transfer multi gudang"}

    # ---------------- Hard-block (sebelum ada penulisan apa pun)
    n0 = len(call("GET", "transfers")[1])
    sc, r = call("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "B"), L("Helm", 1, "A", "B")]})
    check("11. Qty > stok gudang asal LINE (Helm di A = 0) -> 400 hard-block", sc == 400 and "Baris 2" in str(r.get("detail")) and "Gudang A" in str(r.get("detail")), r)
    check("11. Gagal = atomic: tidak ada dokumen & stok baris 1 tidak berubah", len(call("GET", "transfers")[1]) == n0 and stock(I["Bearing"]["id"], W["A"]["id"]) == 10)
    sc, r = call("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "A")]})
    check("12. Gudang Asal == Tujuan pada line -> 400", sc == 400 and "tidak boleh sama" in str(r.get("detail")), r)
    sc, r = call("POST", "transfers", {"date": "2026-09-21", "division_id": asset["id"], "lines": [L("Bearing", 1, None, None)]})
    check("Line tanpa gudang & tanpa default header -> 400 Gudang Asal wajib", sc == 400 and "Gudang Asal wajib" in str(r.get("detail")), r)
    sc, r = call("POST", "transfers", {**head, "lines": [{**L("Bearing", 1, "A", "B"), "to_warehouse_id": other_wh["id"]}]})
    check("14. Gudang tenant lain pada line ditolak (tidak ditemukan)", sc == 400 and "tidak ditemukan" in str(r.get("detail")), r)

    # ---------------- Draft lampiran sebelum posting
    sc, draft = call("POST", "attachment-drafts", {"module": "transfer"})
    check("16. Draft lampiran dibuat (UUID)", sc == 200 and len(draft.get("id", "")) == 36, sc)
    up = T.S.post(f"{API}/attachments", files={"file": ("surat-jalan.pdf", io.BytesIO(b"%PDF-1.4 qa"), "application/pdf")},
                  data={"entity": "transfer_draft", "entity_id": draft["id"], "category": "Surat Jalan"})
    check("16. Upload SEBELUM posting berhasil", up.status_code == 200, up.text[:120])
    bad = T.S.post(f"{API}/attachments", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
                   data={"entity": "transfer_draft", "entity_id": draft["id"]})
    check("16. Rule tipe file existing tetap berlaku pada draft (.exe ditolak)", bad.status_code == 400)
    sc, lst = call("GET", f"attachments?entity=transfer_draft&entity_id={draft['id']}")
    check("16. Pemilik dapat melihat lampiran draft", sc == 200 and len(lst) == 1)

    # ---------------- Posting multi gudang (UAT): A->B, A->C, D->B dalam 1 dokumen
    lines = [L("Bearing", 5, "A", "B", pa["id"]), L("Oli", 10, "A", "C", pb["id"], unit["id"]), L("Helm", 3, "D", "B", pa["id"])]
    sc, trf = call("POST", "transfers", {**head, "lines": lines, "attachment_draft_id": draft["id"]})
    check("6. Satu Transfer dengan beberapa pasangan gudang -> 200", sc == 200 and trf.get("no", "").startswith("TRF"), trf)
    tl = trf.get("lines") or []
    check("7. Line tersimpan dengan gudang LINE (bukan header)", [(x["from_name"], x["to_name"]) for x in tl] ==
          [("Gudang A", "Gudang B"), ("Gudang A", "Gudang C"), ("Gudang D", "Gudang B")], [(x.get("from_name"), x.get("to_name")) for x in tl])
    check("Project & Unit per line tersimpan", tl[1]["project_id"] == pb["id"] and tl[1]["unit_id"] == unit["id"] and tl[1]["project_name"] == "Project B")
    check("Header = default/snapshot + penanda warehouse_source=line", trf.get("warehouse_source") == "line" and trf.get("from_warehouse_id") == W["A"]["id"])
    check("8. Stok A/B Bearing = 5/5", stock(I["Bearing"]["id"], W["A"]["id"]) == 5 and stock(I["Bearing"]["id"], W["B"]["id"]) == 5)
    check("8. Stok A/C Oli = 10/10 (Oli TIDAK masuk Gudang B header)", stock(I["Oli"]["id"], W["A"]["id"]) == 10 and stock(I["Oli"]["id"], W["C"]["id"]) == 10 and stock(I["Oli"]["id"], W["B"]["id"]) == 0)
    check("8. Stok D/B Helm = 2/3 (Helm TIDAK keluar dari Gudang A header)", stock(I["Helm"]["id"], W["D"]["id"]) == 2 and stock(I["Helm"]["id"], W["B"]["id"]) == 3 and stock(I["Helm"]["id"], W["A"]["id"]) == 0)
    sc, led = call("GET", "inventory/ledger?limit=200")
    mine = [x for x in led if x.get("doc_id") == trf["id"]]
    legs = sorted((x.get("item_name"), x.get("warehouse_name"), float(x.get("qty_in") or 0), float(x.get("qty_out") or 0)) for x in mine)
    check("8. Stock ledger: 6 leg pada gudang line yang benar", legs == sorted([("Bearing", "Gudang A", 0, 5), ("Bearing", "Gudang B", 5, 0), ("Oli", "Gudang A", 0, 10),
                                                                            ("Oli", "Gudang C", 10, 0), ("Helm", "Gudang D", 0, 3), ("Helm", "Gudang B", 3, 0)]), legs)
    sc, vl = call("GET", "reports/valuation-ledger")
    vrows = [x for x in (vl if isinstance(vl, list) else vl.get("rows", [])) if x.get("doc_id") == trf["id"] or x.get("doc_no") == trf["no"]]
    val = {(x.get("item_name"), x.get("warehouse_name")): float(x.get("value_in") or 0) for x in vrows if float(x.get("value_in") or 0) > 0}
    check("8. Valuasi MWA dibawa ke gudang tujuan line (Bearing B=5000, Oli C=5000, Helm B=6000)",
          val == {("Bearing", "Gudang B"): 5000, ("Oli", "Gudang C"): 5000, ("Helm", "Gudang B"): 6000}, val)
    sc, lst = call("GET", "transfers")
    row = next(x for x in lst if x["id"] == trf["id"])
    check("9. Laporan/list membaca gudang line (Dari 'Gudang A +1', Ke 'Gudang B +1', multi)", row.get("from_name") == "Gudang A +1" and row.get("to_name") == "Gudang B +1" and row.get("multi_warehouse") is True, row)

    # ---------------- Lampiran terikat ke transaksi final
    sc, att = call("GET", f"attachments?entity=transfer&entity_id={trf['id']}")
    check("17. Lampiran draft terikat ke Transfer final", sc == 200 and len(att) == 1 and att[0].get("bound_from_draft") == draft["id"])
    sc, dl = call("GET", f"attachments?entity=transfer_draft&entity_id={draft['id']}")
    check("17. Draft kosong setelah bind", sc == 200 and len(dl) == 0)
    sc, r = call("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "B")], "attachment_draft_id": draft["id"]})
    check("17. Draft yang sudah terikat tidak bisa dipakai ulang (409)", sc == 409, sc)

    # ---------------- Edit/repost: ganti tujuan line 2 C -> D (reversal lalu posting ulang per line)
    sc, d = call("GET", f"transfers/{trf['id']}")
    new_lines = [{k: x.get(k) for k in ("item_id", "qty", "uom_id", "from_warehouse_id", "to_warehouse_id", "project_id", "unit_id", "notes")} for x in d["lines"]]
    new_lines[1]["to_warehouse_id"] = W["D"]["id"]
    sc, r = call("PUT", f"transactions/transfer/{trf['id']}", {**head, "lines": new_lines, "reason": "QA ganti tujuan"})
    check("Edit transfer per line -> 200", sc == 200, r)
    check("Edit: Oli pindah C -> D (C=0, D=10), lainnya tetap", stock(I["Oli"]["id"], W["C"]["id"]) == 0 and stock(I["Oli"]["id"], W["D"]["id"]) == 10
          and stock(I["Bearing"]["id"], W["B"]["id"]) == 5 and stock(I["Helm"]["id"], W["B"]["id"]) == 3)
    bad = [dict(x) for x in new_lines]; bad[2]["qty"] = 99
    sc, r = call("PUT", f"transactions/transfer/{trf['id']}", {**head, "lines": bad, "reason": "QA"})
    check("Edit: qty > stok gudang asal line (+kredit reversal) -> 400", sc == 400 and "Gudang D" in str(r.get("detail")), r)

    # ---------------- Header default diisi ke line bila API tidak mengirim gudang line
    sc, t2 = call("POST", "transfers", {**head, "lines": [{"item_id": I["Bearing"]["id"], "qty": 1, "uom_id": uom["id"]}]})
    check("API tanpa gudang line -> diisi default header & disimpan eksplisit", sc == 200 and t2["lines"][0]["from_warehouse_id"] == W["A"]["id"]
          and t2["lines"][0]["to_warehouse_id"] == W["B"]["id"] and t2["lines"][0]["legacy_header_warehouse"] is False, t2)

    # ---------------- Legacy: line tanpa gudang (data lama) tetap terbaca via fallback header
    sc, t3 = call("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "B")]})
    lid = t3["lines"][0]["id"]
    with db_conn() as cx, cx.cursor() as cur:
        cur.execute("UPDATE transfer_lines SET doc = JSON_REMOVE(doc, '$.from_warehouse_id', '$.to_warehouse_id') WHERE id=%s", (lid,))
        cur.execute("UPDATE transfers SET doc = JSON_REMOVE(doc, '$.warehouse_source', '$.line_warehouse_ids') WHERE id=%s", (t3["id"],))
    sc, lg = call("GET", f"transfers/{t3['id']}")
    check("15. Legacy transfer terbaca (fallback header, ditandai legacy)", sc == 200 and lg["lines"][0]["from_name"] == "Gudang A"
          and lg["lines"][0]["to_name"] == "Gudang B" and lg["lines"][0]["legacy_header_warehouse"] is True, lg.get("lines"))
    sc, lst = call("GET", "transfers")
    check("15. Legacy transfer muncul di list dengan gudang header", any(x["id"] == t3["id"] and x["from_name"] == "Gudang A" for x in lst))
    with db_conn() as cx, cx.cursor() as cur:
        cur.execute("UPDATE transfer_lines SET doc = JSON_REMOVE(doc, '$.project_id') WHERE id=%s", (lid,))
    sc, lg = call("GET", f"transfers/{t3['id']}")
    check("16. Legacy: project baris kosong -> fallback Project Default header (hanya saat baca)", lg["lines"][0]["project_name"] == "Project A" and lg.get("legacy_header_warehouse") is True, lg.get("lines"))
    with db_conn() as cx, cx.cursor() as cur:
        cur.execute("SELECT JSON_EXTRACT(doc,'$.from_warehouse_id'), JSON_EXTRACT(doc,'$.project_id') FROM transfer_lines WHERE id=%s", (lid,))
        raw = cur.fetchone()
    check("16. Legacy: data asli TIDAK diubah oleh pembacaan (tanpa migrasi destruktif)", raw[0] is None and raw[1] is None, raw)
    sc, t4 = call("POST", "transfers", {**head, "lines": [{**L("Bearing", 1, "A", "B"), "project_id": None}]})
    check("11/16. Transaksi BARU: project baris kosong TIDAK di-fallback ke header", sc == 200 and t4["lines"][0]["project_id"] is None and t4["lines"][0]["project_name"] is None
          and t4.get("legacy_header_warehouse") is False, t4.get("lines"))
    sc, led = call("GET", "inventory/ledger?limit=400")
    legs4 = {x.get("warehouse_name") for x in led if x.get("doc_id") == t4["id"]}
    check("11. Ledger transaksi baru memakai gudang baris", legs4 == {"Gudang A", "Gudang B"}, legs4)

    # ---------------- Scope divisi per line (14)
    email = f"trfw_{u}@example.com"
    _, usr = call("POST", "users", {"email": email, "password": PW, "name": "QA Gudang Asset", "role": "warehouse"}, 200)
    call("PUT", f"access/users/{usr['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": [asset["id"]]}}, 200)
    C = U(email)
    sc, r = C("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "C")]})
    check("14. User divisi Asset: gudang tujuan line di divisi lain -> 403", sc == 403, (sc, r))
    sc, r = C("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "B")]})
    check("14. User divisi Asset: A->B (dalam scope) -> 200", sc == 200, (sc, r))
    sc, r = C("GET", f"transfers/{trf['id']}")
    check("14. Transfer berisi gudang line divisi lain tidak terlihat oleh user divisi Asset", sc in (403, 404), sc)
    sc, lst = C("GET", "transfers")
    check("14. List user divisi Asset tidak memuat transfer multi-divisi", sc == 200 and all(x["id"] != trf["id"] for x in lst))
    sc, r = C("GET", f"attachments?entity=transfer_draft&entity_id={draft['id']}")
    check("18. User lain (tenant sama) tidak bisa membaca draft orang lain", sc == 404, sc)

    # ---------------- Draft dibatalkan + isolasi tenant lain
    sc, d2 = call("POST", "attachment-drafts", {"module": "transfer"})
    T.S.post(f"{API}/attachments", files={"file": ("foto.png", io.BytesIO(b"\x89PNG qa"), "image/png")}, data={"entity": "transfer_draft", "entity_id": d2["id"]})
    mine_hdr = dict(T.S.headers)
    T.S.headers.clear(); T.S.headers.update(other_hdr)
    sc, r = call("GET", f"attachments?entity=transfer_draft&entity_id={d2['id']}")
    check("18. Tenant lain tidak bisa membaca draft (404)", sc == 404, sc)
    up = T.S.post(f"{API}/attachments", files={"file": ("x.pdf", io.BytesIO(b"%PDF qa"), "application/pdf")}, data={"entity": "transfer_draft", "entity_id": d2["id"]})
    check("18. Tenant lain tidak bisa upload ke draft (404)", up.status_code == 404, up.status_code)
    sc, r = call("GET", f"transfers/{trf['id']}")
    check("18/14. Tenant lain tidak bisa membuka Transfer (404)", sc == 404, sc)
    T.S.headers.clear(); T.S.headers.update(mine_hdr)
    sc, r = call("DELETE", f"attachment-drafts/{d2['id']}")
    sc2, _ = call("GET", f"attachments?entity=transfer_draft&entity_id={d2['id']}")
    check("Batal: draft dihapus -> lampiran draft tidak bisa diakses lagi", sc == 200 and sc2 == 404, (sc, sc2))

    # ================= Draft lampiran: lifecycle + keamanan (wajib) =================
    import datetime as _dt
    store_root = dotenv_values("/app/backend/.env").get("STORAGE_LOCAL_PATH") or "/app/data/uploads"

    def obj_exists(path):
        return os.path.exists(os.path.join(store_root, path))

    def sql(q, args=()):
        with db_conn() as cx, cx.cursor() as cur:
            cur.execute(q, args)
            return cur.fetchall()

    def upload(draft_id, name="bukti.pdf", data=b"%PDF-1.4 qa", ctype="application/pdf", session=None):
        return (session or T.S).post(f"{API}/attachments", files={"file": (name, io.BytesIO(data), ctype)},
                                     data={"entity": "transfer_draft", "entity_id": draft_id, "category": "Lainnya"})

    def att_rows(draft_id):
        return sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.storage_path')), JSON_UNQUOTE(JSON_EXTRACT(doc,'$.tenant_id')) "
                   "FROM attachments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity_id'))=%s", (draft_id,))

    def age_draft(draft_id, hours=25):
        old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)).isoformat()
        sql("UPDATE attachment_drafts SET doc = JSON_SET(doc, '$.created_at', %s), created_at=%s WHERE id=%s",
            (old, (_dt.datetime.utcnow() - _dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S"), draft_id))

    _, me = call("GET", "auth/me")
    sc, d3 = call("POST", "attachment-drafts", {"module": "transfer", "tenant_id": "tenant-palsu", "owner_id": "user-palsu"})
    check("D1. Draft UUID valid (v4)", sc == 200 and uuid.UUID(d3["id"]).version == 4, d3)
    row = sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.tenant_id')), JSON_UNQUOTE(JSON_EXTRACT(doc,'$.owner_id')), "
              "JSON_UNQUOTE(JSON_EXTRACT(doc,'$.module')) FROM attachment_drafts WHERE id=%s", (d3["id"],))
    check("D2. Draft tersimpan untuk tenant+user AKTIF (payload tenant/owner diabaikan)",
          len(row) == 1 and row[0][1] == (me.get("id") or (me.get("user") or {}).get("id")) and row[0][0] not in (None, "tenant-palsu") and row[0][2] == "transfer", row)
    up = upload(d3["id"])
    check("D2. Upload ke draft milik sendiri -> 200", up.status_code == 200, up.text[:120])
    aid3 = up.json().get("id")
    # MIME / size / kosong existing tetap berlaku
    check("D5. MIME tidak sesuai ekstensi ditolak (.pdf sebagai image/png)", upload(d3["id"], "a.pdf", b"%PDF", "image/png").status_code == 400)
    check("D5. File kosong ditolak", upload(d3["id"], "a.pdf", b"").status_code == 400)
    check("D5. File > batas ukuran ditolak", upload(d3["id"], "big.pdf", b"0" * (16 * 1024 * 1024)).status_code == 400)

    # User lain (tenant sama) tidak bisa baca / download / hapus / bind / batal draft orang lain
    sc, _ = C("GET", f"attachments?entity=transfer_draft&entity_id={d3['id']}")
    check("D3. User lain tidak bisa list draft (404)", sc == 404, sc)
    sc, _ = C("GET", f"attachments/{aid3}/download")
    check("D3. User lain tidak bisa download lampiran draft (404)", sc == 404, sc)
    sc, _ = C("DELETE", f"attachments/{aid3}")
    check("D3. User lain tidak bisa hapus lampiran draft (404)", sc == 404, sc)
    sc, _ = C("DELETE", f"attachment-drafts/{d3['id']}")
    check("D3. User lain tidak bisa batalkan draft (404)", sc == 404, sc)
    sc, _ = C("POST", "transfers", {**head, "lines": [L("Bearing", 1, "A", "B")], "attachment_draft_id": d3["id"]})
    check("D3. User lain tidak bisa bind draft orang lain (404) & tidak membuat transaksi", sc == 404, sc)
    dl = T.S.get(f"{API}/attachments/{aid3}/download")
    check("D3. Pemilik dapat download lampiran draft", dl.status_code == 200 and dl.content.startswith(b"%PDF"), dl.status_code)
    # Tenant lain
    mine_hdr = dict(T.S.headers)
    T.S.headers.clear(); T.S.headers.update(other_hdr)
    sc, _ = call("GET", f"attachments/{aid3}/download")
    check("D4. Tenant lain tidak bisa download lampiran draft (404)", sc == 404, sc)
    sc, _ = call("DELETE", f"attachment-drafts/{d3['id']}")
    check("D4. Tenant lain tidak bisa batalkan draft (404)", sc == 404, sc)
    sc, _ = call("POST", "transfers", {"date": head["date"], "from_warehouse_id": other_wh["id"], "to_warehouse_id": other_wh["id"],
                                       "lines": [], "attachment_draft_id": d3["id"]})
    check("D4. Tenant lain tidak bisa bind draft", sc in (400, 404), sc)
    T.S.headers.clear(); T.S.headers.update(mine_hdr)

    # Posting gagal (validasi) -> draft tetap draft, retry berhasil
    n_before = len(call("GET", "transfers")[1])
    sc, r = call("POST", "transfers", {**head, "lines": [L("Bearing", 999, "A", "B")], "attachment_draft_id": d3["id"]})
    check("D7. Posting gagal (stok) -> 400, transaksi tidak terbentuk", sc == 400 and len(call("GET", "transfers")[1]) == n_before, r)
    sc, lst = call("GET", f"attachments?entity=transfer_draft&entity_id={d3['id']}")
    check("D7. Lampiran tetap draft setelah posting gagal", sc == 200 and len(lst) == 1)

    # Posting gagal DI TENGAH engine (baris 1 terposting, baris 2 backdate) -> rollback penuh + draft tetap
    I["Kunci"] = m("items", {"code": f"KU{u}", "name": "Kunci", **ref})
    today = _dt.date.today()
    call("POST", "adjustments", {"date": (today - _dt.timedelta(days=3)).isoformat(), "warehouse_id": W["A"]["id"], "division_id": asset["id"],
                                 "adj_type": "Opening", "reason": "QA", "lines": [{"item_id": I["Kunci"]["id"], "adjustment": 4, "reason": "QA", "approved_unit_cost": 300}]}, 200)
    n_before = len(call("GET", "transfers")[1])
    sc, r = call("POST", "transfers", {**head, "date": (today - _dt.timedelta(days=1)).isoformat(),
                                       "lines": [L("Kunci", 2, "A", "C"), L("Bearing", 1, "A", "B")], "attachment_draft_id": d3["id"]})
    check("D7. Kegagalan engine di baris 2 -> error, transaksi TIDAK terbentuk", sc >= 400 and len(call("GET", "transfers")[1]) == n_before, (sc, r))
    check("D7. Rollback: stok Kunci A=4 / C=0 (baris 1 dibalik lewat reversal engine)", stock(I["Kunci"]["id"], W["A"]["id"]) == 4 and stock(I["Kunci"]["id"], W["C"]["id"]) == 0)
    revs = sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.doc_type')) FROM stock_ledger WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.item_id'))=%s", (I["Kunci"]["id"],))
    kinds = sorted(x[0] for x in revs)
    check("D7. Baris 1 sempat terposting lalu dibalik oleh engine reversal (bukan pre-check)",
          "Reversal Transfer In" in kinds and "Reversal Transfer Out" in kinds and "mundur" in str(r), (kinds, r))
    st = sql("SELECT JSON_EXTRACT(doc,'$.bound_to') FROM attachment_drafts WHERE id=%s", (d3["id"],))
    check("D7. Draft dilepas kembali (bound_to null) setelah gagal", st and st[0][0] in (None, "null"), st)
    sc, t_ok = call("POST", "transfers", {**head, "lines": [L("Kunci", 1, "A", "C")], "attachment_draft_id": d3["id"]})
    check("D6/D7. Retry posting dengan draft yang sama -> 200 & lampiran ter-bind", sc == 200 and
          len(call("GET", f"attachments?entity=transfer&entity_id={t_ok['id']}")[1]) == 1, (sc, t_ok))
    sc, det = call("GET", f"transfers/{t_ok['id']}")
    sc2, att = call("GET", f"attachments?entity=transfer&entity_id={t_ok['id']}")
    check("D13. Lampiran muncul pada detail Transfer setelah posting", sc == 200 and sc2 == 200 and att[0]["original_filename"] == "bukti.pdf")
    sc, _ = call("POST", "transfers", {**head, "lines": [L("Kunci", 1, "A", "C")], "attachment_draft_id": d3["id"]})
    check("D12. Draft tidak bisa di-bind dua kali / ke transaksi lain (409)", sc == 409, sc)
    up = upload(d3["id"])
    check("D12. Draft yang sudah terikat tidak bisa diberi lampiran baru (409)", up.status_code == 409, up.status_code)

    # Batal -> row draft + row lampiran + object storage terhapus
    sc, d4 = call("POST", "attachment-drafts", {"module": "transfer"})
    upload(d4["id"], "batal.pdf")
    path4 = att_rows(d4["id"])[0][0]
    check("D8. (pre) object draft tersimpan di storage", obj_exists(path4), path4)
    sc, r = call("DELETE", f"attachment-drafts/{d4['id']}")
    check("D8. Batal -> draft row & lampiran row & object terhapus", sc == 200 and not att_rows(d4["id"]) and not obj_exists(path4)
          and not sql("SELECT id FROM attachment_drafts WHERE id=%s", (d4["id"],)), (sc, r))

    # Cleanup otomatis > 24 jam (via endpoint draft)
    sc, d5 = call("POST", "attachment-drafts", {"module": "transfer"}); upload(d5["id"], "lama.pdf")
    sc, d6 = call("POST", "attachment-drafts", {"module": "transfer"}); upload(d6["id"], "hilang.pdf")
    sc, d7 = call("POST", "attachment-drafts", {"module": "transfer"}); upload(d7["id"], "baru.pdf")
    p5, p6, p7 = att_rows(d5["id"])[0][0], att_rows(d6["id"])[0][0], att_rows(d7["id"])[0][0]
    os.remove(os.path.join(store_root, p6))  # object sudah hilang sebelum cleanup
    age_draft(d5["id"]); age_draft(d6["id"]); age_draft(d3["id"])  # d3 = draft yang SUDAH ter-bind (final)
    final_path = sql("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.storage_path')) FROM attachments WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.entity_id'))=%s", (t_ok["id"],))[0][0]
    sc, _ = call("POST", "attachment-drafts", {"module": "transfer"})  # memicu cleanup tenant aktif
    sc2, _ = call("POST", "attachment-drafts", {"module": "transfer"})  # dijalankan ulang (idempotent)
    check("D9. Draft > 24 jam: row + lampiran + object terhapus", sc == 200 and sc2 == 200 and not att_rows(d5["id"]) and not obj_exists(p5)
          and not sql("SELECT id FROM attachment_drafts WHERE id=%s", (d5["id"],)))
    check("D11. Cleanup aman walau object sudah hilang (row tetap dibersihkan)", not att_rows(d6["id"]) and not sql("SELECT id FROM attachment_drafts WHERE id=%s", (d6["id"],)))
    check("D9. Draft < 24 jam tidak ikut terhapus", len(att_rows(d7["id"])) == 1 and obj_exists(p7))
    check("D10. Lampiran FINAL (draft lama yang sudah ter-bind) tidak ikut cleanup",
          len(call("GET", f"attachments?entity=transfer&entity_id={t_ok['id']}")[1]) == 1 and obj_exists(final_path))

    # Cleanup jalur STARTUP (raw db lintas tenant, filter tenant per draft) — fungsi yang sama dipanggil on_event("startup")
    import asyncio
    import types
    sys.path.insert(0, "/app/backend")
    T.S.headers.clear(); T.S.headers.update(other_hdr)
    sc, dx = call("POST", "attachment-drafts", {"module": "transfer"}); upload(dx["id"], "tenant-lain.pdf")
    px = att_rows(dx["id"])[0][0]
    T.S.headers.clear(); T.S.headers.update(mine_hdr)
    age_draft(dx["id"]); age_draft(d7["id"])

    async def _startup_cleanup():
        import mariadb_motor
        import transfer_lines as TL
        env = dotenv_values("/app/backend/.env")
        cl = mariadb_motor.MariaClient(env["DATABASE_URL"], auto_schema=False, pool_size=2)
        n1 = await TL.cleanup_expired_drafts(types.SimpleNamespace(db=cl[env.get("DB_NAME", "default")]), all_tenants=True)
        n2 = await TL.cleanup_expired_drafts(types.SimpleNamespace(db=cl[env.get("DB_NAME", "default")]), all_tenants=True)
        return n1, n2
    n1, n2 = asyncio.run(_startup_cleanup())
    check("D9. Cleanup startup lintas tenant: draft lama tenant lain & tenant ini terhapus (row+object)",
          n1 >= 2 and not att_rows(dx["id"]) and not obj_exists(px) and not att_rows(d7["id"]) and not obj_exists(p7), (n1, n2))
    check("D9. Cleanup startup idempotent (run ke-2 tidak menghapus apa pun lagi milik test)", n2 == 0 or not att_rows(d7["id"]), n2)
    check("D10. Lampiran final tetap ada setelah cleanup startup",
          len(call("GET", f"attachments?entity=transfer&entity_id={t_ok['id']}")[1]) == 1 and obj_exists(final_path))

    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
