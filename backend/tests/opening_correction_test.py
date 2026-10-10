"""Koreksi Nilai Awal Persediaan: status, Tetapkan Massal, Revaluasi Saldo Awal / Valuation Replay (dry-run + apply).

Throwaway tenant, localhost:8001, butuh DATABASE_URL (simulasi Import Saldo Awal langsung ke tabel, seperti import
existing: qty masuk pool + slice opening_qty/opening_value + stock_ledger 'Opening Balance Import', TANPA valuation ledger).

  P @ Gudang A : saldo awal 10 @ 5.000 (50.000), belum ada mutasi            -> Siap Ditetapkan
  Q @ Gudang A : saldo awal 10 @ 10.000 (100.000), lalu (engine existing):
                 DO 10 @ 20.000 -> qty 20 nilai 200.000 avg 10.000 (terdilusi; seharusnya 15.000)
                 Penyesuaian keluar 5 -> HPP 50.000 (seharusnya 75.000)
                 Transfer 5 ke Gudang B -> 50.000 (seharusnya 75.000); Gudang B keluar 2 -> 20.000 (seharusnya 30.000)
                 -> Perlu Revaluasi; replay: A 150.000, B 45.000 (sebelum 100.000 + 30.000)
  N @ Gudang A : stok 4 tanpa nilai & tanpa slice saldo awal                -> Tidak Ada Nilai Sumber
  R @ Gudang A : saldo awal + entri ledger yang tidak konsisten              -> replay diblokir (tanpa nilai karangan)
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import dashboard_historical_cutoff_test as H
import receipt_control_test as T

call, check = T.call, T.check
M = None


def conn():
    from urllib.parse import unquote, urlparse

    import pymysql
    u = urlparse(os.environ["DATABASE_URL"].replace("mariadb://", "mysql://"))
    return pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                           database=u.path.lstrip("/"), autocommit=True)


def ins(cn, table, doc):
    sys.path.insert(0, "/app/backend")
    from mariadb_motor import _pick_pk
    # DB test kosong (runner terisolasi): buat koleksi bila belum ada — DDL identik mariadb_motor._ensure_table
    cn.cursor().execute(f"CREATE TABLE IF NOT EXISTS `{table}` (pk VARCHAR(64) NOT NULL PRIMARY KEY, doc LONGTEXT NOT NULL CHECK "
                        "(JSON_VALID(doc)), id VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED, created_at DATETIME(6) "
                        "NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE "
                        "CURRENT_TIMESTAMP(6), KEY idx_id (id), KEY idx_created (created_at, pk)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 "
                        "COLLATE=utf8mb4_unicode_ci")
    cn.cursor().execute(f"INSERT INTO `{table}` (pk, doc) VALUES (%s, %s)", (_pick_pk(doc), json.dumps(doc)))


def sim_import(cn, tenant, item, wh, qty, value, slices=None, iw_extra=None):
    """Seperti Import Saldo Awal existing: slice opening_inventory (per proyek) + pool (qty, opening_qty/value agregat,
    nilai 0) + stock_ledger 'Opening Balance Import', TANPA valuation ledger. slices = [(qty, value), ...]."""
    at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    for i, (sq, sv) in enumerate(slices or [(qty, value)]):
        ins(cn, "opening_inventory", {"id": f"oi-{uuid.uuid4().hex[:10]}", "tenant_id": tenant, "item_id": item, "warehouse_id": wh,
                                      "project_id": f"prj-{i}" if slices else None, "project_code": f"PRJ{i}" if slices else None,
                                      "display_qty": float(sq), "base_qty": float(sq), "conversion_factor": 1.0,
                                      "purchase_price": (sv / sq) if sq else 0.0, "base_unit_cost": (sv / sq) if sq else 0.0,
                                      "opening_value": float(sv), "created_at": at})
    ins(cn, "item_warehouse", {"id": f"iw::{item}::{wh}", "tenant_id": tenant, "item_id": item, "warehouse_id": wh, "current_stock": float(qty),
                               "avg_cost": 0.0, "total_value": 0.0, "opening_qty": float(qty), "opening_value": float(value),
                               "opening_average_cost": (value / qty) if qty else 0, "min_stock": 0, "max_stock": 0, **(iw_extra or {})})
    ins(cn, "stock_ledger", {"id": f"sl-open-{uuid.uuid4().hex[:8]}", "tenant_id": tenant, "doc_type": "Opening Balance Import", "doc_no": "SALDO-AWAL",
                             "doc_id": uuid.uuid4().hex, "item_id": item, "warehouse_id": wh, "qty_in": float(qty), "qty_out": 0,
                             "running_balance": float(qty), "opening_balance": True, "at": at})


SNAP_TABLES = ("opening_inventory", "item_warehouse", "valuation_ledger", "stock_ledger", "audit_logs", "valuation_replays",
               "transfer_lines", "loan_lines")


def snapshot(tenant):
    """Row count + checksum seluruh dokumen tenant pada tabel valuasi/stok/audit (bukti zero-write)."""
    c = conn()
    try:
        cur = c.cursor()
        out = {}
        cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
        existing = {r[0] for r in cur.fetchall()}
        for t in SNAP_TABLES:
            if t not in existing:  # tabel dibuat lazy (auto-schema) saat tulis pertama -> belum ada = 0 baris
                out[t] = (0, 0)
                continue
            cur.execute(f"SELECT COUNT(*), COALESCE(SUM(CRC32(doc)), 0) FROM `{t}` WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.tenant_id')) = %s", (tenant,))
            out[t] = tuple(int(x) for x in cur.fetchone())
        return out
    finally:
        c.close()


def pool(item, wh):
    rows = call("GET", f"valuation/opening-candidates?warehouse_id={wh}")[1].get("rows", [])
    return next((r for r in rows if r["item_id"] == item), {})


def row(rows, item, wh):
    return next((r for r in rows if r["item_id"] == item and r["warehouse_id"] == wh), None)


def adj(wh, item, delta, cost=None):
    ln = {"item_id": item, "adjustment": delta}
    if cost:
        ln["approved_unit_cost"] = cost
    sc, r = call("POST", "adjustments", {"warehouse_id": wh, "division_id": M["div"]["id"], "reason": "QA", "lines": [ln]})
    check(f"Penyesuaian {delta} tercatat", sc == 200, (sc, r))


def main():
    global M
    if not os.environ.get("DATABASE_URL"):
        print("SKIP: DATABASE_URL tidak tersedia")
        return
    M = T.setup()
    H.M = M
    call("PUT", "settings/approval_modules", {"modules": {k: {"enabled": False, "levels": []} for k in ("mro", "ro", "po")}}, 200)
    tenant = call("GET", "auth/me")[1].get("tenant_id")
    wa, wb = M["wh"]["id"], M["wh2"]["id"]
    ref = {"unit": "PCS", "category_id": M["item"].get("category_id"), "base_uom_id": M["item"].get("base_uom_id"), "division_id": M["div"]["id"]}
    u = uuid.uuid4().hex[:5]

    def mk(code, name, **extra):
        return call("POST", "master/items", {"code": f"{code}{u}", "name": name, "is_active": True, **ref, **extra}, 200)[1]
    P, N, R = mk("OP", "Barang P (siap)"), mk("ON", "Barang N (tanpa sumber)"), mk("OR", "Barang R (tidak konsisten)")
    S = mk("OS", "Barang S (sumber import 100)", price=500, purchase_price=500, standard_cost=500)
    Tt = mk("OT", "Barang T (import tanpa nilai)", price=500, purchase_price=500, standard_cost=500)
    V = mk("OV", "Barang V (divisi lain)")
    Q = M["item"]
    sc, dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)
    sc, whC = call("POST", "master/warehouses", {"code": f"WC{u}", "name": "Gudang C", "is_active": True, "division_id": dB["id"]}, 200)
    wc = whC["id"]
    # Harga PO terakhir 700 untuk S & T (tidak boleh dipakai sebagai kandidat)
    for it in (S, Tt):
        call("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "date": "2026-10-01",
                            "lines": [{"item_id": it["id"], "qty": 1, "price": 700, "warehouse_id": wa, "project_id": M["pa"]["id"]}]}, 200)
    cn = conn()
    try:
        sim_import(cn, tenant, P["id"], wa, 10, 50_000, slices=[(6, 30_000), (4, 20_000)])  # 2 slice proyek -> agregasi
        sim_import(cn, tenant, Q["id"], wa, 10, 100_000)
        sim_import(cn, tenant, R["id"], wa, 5, 25_000)
        sim_import(cn, tenant, S["id"], wa, 10, 1_000, iw_extra={"avg_cost": 900.0, "total_value": 9_000.0})  # avg sekarang 900
        sim_import(cn, tenant, Tt["id"], wa, 5, 0)  # import tanpa nilai
        sim_import(cn, tenant, V["id"], wc, 8, 20_000)  # gudang divisi B
        ins(cn, "item_warehouse", {"id": f"iw::{N['id']}::{wa}", "tenant_id": tenant, "item_id": N["id"], "warehouse_id": wa, "current_stock": 4.0,
                                   "avg_cost": 0.0, "total_value": 0.0, "min_stock": 0, "max_stock": 0})
        # Tanggal transaksi WAJIB satu konvensi dengan default server (now_iso() = UTC) & frontend (todayISO() =
        # toISOString() UTC). Memakai tanggal WIB di sini membuat DO/Transfer bertanggal "besok" relatif Adjustment
        # (tanpa field date -> default UTC) pada jendela 00:00-07:00 WIB -> backdate guard menolak (flaky).
        today = datetime.now(timezone.utc).date().isoformat()
        po = H.mkpo(10, 20_000, today)
        H.mkdo(po, 10, today)
        adj(wa, Q["id"], -5)
        sc, trf = call("POST", "transfers", {"from_warehouse_id": wa, "to_warehouse_id": wb, "division_id": M["div"]["id"], "date": today,
                                            "lines": [{"item_id": Q["id"], "qty": 5}]})
        check("Transfer 5 Gudang A -> B", sc == 200, (sc, trf))
        adj(wb, Q["id"], -2)
        adj(wa, R["id"], 2, cost=7_000)
        cur = cn.cursor()
        n = cur.execute("UPDATE `valuation_ledger` SET doc = JSON_SET(doc, '$.value_after', 99999) WHERE "
                        "JSON_UNQUOTE(JSON_EXTRACT(doc, '$.item_id')) = %s", (R["id"],))
        check("Simulasi entri ledger R tidak konsisten", n == 1, n)
        cur.execute("UPDATE `item_warehouse` SET doc = JSON_SET(doc, '$.total_value', 99999) WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.item_id')) = %s", (R["id"],))
    finally:
        cn.close()

    if os.environ.get("OC_SEED_ONLY"):  # fixture UAT browser: berhenti sebelum Tetapkan/Revaluasi
        return
    qa = pool(Q["id"], wa)
    check("Engine existing: Q@A terdilusi (qty 10, nilai 100.000, avg 10.000)", qa.get("qty_existing") == 10 and abs(qa.get("inventory_value", 0) - 100_000) < 0.01, qa)
    d0 = call("GET", "dashboard/control-center?period=this_month")[1]["inventory"]

    # ---------------- status / sumber nilai
    sc, st = call("GET", "valuation/opening-status")
    rows, s = st.get("rows", []), st.get("summary", {})
    check("Status 200", sc == 200, (sc, str(st)[:200]))
    rp, rq, rn, rs, rt, rv = (row(rows, i["id"], w) for i, w in ((P, wa), (Q, wa), (N, wa), (S, wa), (Tt, wa), (V, wc)))
    check("P = Siap Ditetapkan; 2 slice proyek diagregasi: qty 10, nilai 50.000, harga 5.000",
          rp and rp["status"] == "ready" and rp["status_label"] == "Siap Ditetapkan" and rp["opening_slices"] == 2
          and abs(rp["opening_cost"] - 5000) < 1e-6 and abs(rp["opening_value"] - 50_000) < 0.01 and rp["opening_qty"] == 10, rp)
    check("S: kandidat = Import Saldo Awal Rp100 (bukan master 500 / PO 700 / avg sekarang 900)",
          rs and rs["status"] == "ready" and abs(rs["opening_cost"] - 100) < 1e-9 and abs(rs["opening_value"] - 1_000) < 0.01 and rs["avg_cost"] == 900, rs)
    check("T: import tanpa nilai valid -> Tidak Ada Nilai Sumber (tanpa fallback PO/master)",
          rt and rt["status"] == "no_source" and rt["opening_cost"] is None and rt["opening_value"] is None and rt["after_value"] is None, rt)
    check("V@Gudang C (Divisi B) = Siap Ditetapkan untuk admin (cakupan semua divisi)", rv and rv["status"] == "ready", rv)
    check("Q@A = Perlu Revaluasi (sudah ada mutasi) walau avg > 0", rq and rq["status"] == "needs_replay" and rq["status_label"] == "Perlu Revaluasi"
          and rq["avg_cost"] > 0 and not rq["unvalued"] and rq["moves_after_opening"] >= 3 and rq["first_move_after_opening"], rq)
    check("N = Tidak Ada Nilai Sumber (tanpa data import)", rn and rn["status"] == "no_source" and rn["opening_cost"] is None, rn)
    check("Q@B (tujuan transfer, bernilai, tanpa import) tidak didaftar", row(rows, Q["id"], wb) is None)
    check("Ringkasan: siap 3 (P,S,V), revaluasi 2 (Q,R), tanpa sumber 2 (N,T), sudah dinilai 0",
          (s.get("ready"), s.get("needs_replay"), s.get("no_source"), s.get("valued")) == (3, 2, 2, 0), s)
    check("Ringkasan: Direct Apply = sekarang + (50.000 + (1.000 - 9.000) + 20.000)",
          abs(s["inventory_value_after_mass"] - s["inventory_value_now"] - 62_000) < 0.01 and abs(s["ready_delta"] - 62_000) < 0.01, s)
    check("Tanggal saldo awal terisi", bool(rp.get("opening_date")), rp.get("opening_date"))
    check("Sumber nilai = Import Saldo Awal", "Import Saldo Awal" in (st.get("source") or ""), st.get("source"))
    sc, onlyr = call("GET", "valuation/opening-status?status=needs_replay")
    check("Filter status needs_replay", {r["item_id"] for r in onlyr["rows"]} == {Q["id"], R["id"]}, [r["item_name"] for r in onlyr["rows"]])

    # ---------------- dry-run: kalkulasi + ZERO WRITE
    snap0 = snapshot(tenant)
    sc, dr = call("POST", "valuation/replay/dry-run", {})
    call("POST", "valuation/replay/dry-run", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}]})
    call("GET", "valuation/opening-status")
    check("Dry run + status: database identik (opening_inventory, item_warehouse, valuation_ledger, stock_ledger, audit_logs, ...)",
          snapshot(tenant) == snap0, {k: (snap0[k], v) for k, v in snapshot(tenant).items() if v != snap0[k]})
    check("Dry run 200", sc == 200 and dr.get("dry_run") is True, (sc, str(dr)[:300]))
    iq = next((i for i in dr["items"] if i["item_id"] == Q["id"]), {})
    ir = next((i for i in dr["items"] if i["item_id"] == R["id"]), {})
    check("Dry run hanya pool Perlu Revaluasi (T/N tanpa sumber & pool siap tidak ikut / tanpa nilai fallback)",
          {i["item_id"] for i in dr["items"]} == {Q["id"], R["id"]}, [i.get("item_name") for i in dr["items"]])
    bd = ir.get("blocked_detail") or {}
    check("Dry run R diblokir + detail investigasi (Stock Adjustment, tercatat 99.999 vs replay 14.000)",
          bool(ir.get("blocked")) and bd.get("doc_type") == "Stock Adjustment" and bd["recorded"]["value_after"] == 99999
          and abs(bd["replay"]["value_after"] - 14_000) < 0.01 and bd.get("recorded_arithmetic_ok") is False, (ir.get("blocked"), bd))
    check("Dry run Q tidak diblokir", iq and not iq.get("blocked"), iq.get("blocked"))
    pa = next((p for p in iq.get("pools", []) if p["warehouse_id"] == wa), {})
    pb = next((p for p in iq.get("pools", []) if p["warehouse_id"] == wb), {})
    check("Nilai sebelum Q = 100.000 + 30.000", abs(iq.get("before_value", 0) - 130_000) < 0.01, iq.get("before_value"))
    check("Nilai opening yang dimasukkan = 100.000", abs(iq.get("opening_value", 0) - 100_000) < 0.01, iq.get("opening_value"))
    check("Sesudah replay: Gudang A 150.000 (avg 15.000), Gudang B 45.000 (berantai via transfer)",
          abs(pa.get("after_value", 0) - 150_000) < 0.01 and abs(pa.get("after_avg", 0) - 15_000) < 1e-6 and abs(pb.get("after_value", 0) - 45_000) < 0.01,
          (pa.get("after_value"), pa.get("after_avg"), pb.get("after_value")))
    check("Transaksi terdampak 5, keluar 3, HPP 2 (transfer keluar bukan HPP)",
          (iq.get("affected_txns"), iq.get("affected_out"), iq.get("affected_hpp")) == (5, 3, 2),
          (iq.get("affected_txns"), iq.get("affected_out"), iq.get("affected_hpp"), [(c["doc_type"]) for c in iq.get("changed", [])]))
    tl = pa.get("timeline") or []
    check("Timeline simulasi Gudang A: Opening -> DO -> keluar, MWA tiap langkah",
          tl and tl[0]["kind"] == "opening" and abs(tl[0]["value_after"] - 100_000) < 0.01
          and [x.get("doc_type") for x in tl[1:]][:1] == ["DO"] and abs(tl[1]["avg_after"] - 15_000) < 1e-6, [(x["kind"], x.get("doc_type")) for x in tl])
    do_c = next((c for c in iq["changed"] if c["doc_type"] == "DO"), {})
    check("Harga IN DO tercatat tidak berubah (200.000) — hanya saldo sesudahnya", do_c and do_c["before"]["value_in"] == do_c["after"]["value_in"] == 200_000
          and abs(do_c["after"]["avg_after"] - 15_000) < 1e-6, do_c)
    outs = sorted(c["after"]["value_out"] for c in iq["changed"] if c["qty_out"] > 0)
    check("Nilai keluar sesudah replay: 30.000, 75.000, 75.000", outs == [30_000, 75_000, 75_000], outs)
    check("Ringkasan dry run (hanya yang bisa direplay)", abs(dr["summary"]["after_value"] - 195_000) < 0.01 and dr["summary"]["blocked"] == 1
          and dr["summary"]["affected_out"] == 3 and abs(dr["summary"]["delta"] - 65_000) < 0.01, dr["summary"])

    # ---------------- matriks izin: view_purchase_price x stock_adjustment
    import po_approval2_batch_test as A
    A.M = M
    users = {}
    for vp in (False, True):
        for sa in (False, True):
            us = A.mk_user(f"oc{int(vp)}{int(sa)}", [M["div"]["id"]])
            A.set_ov(us, {"view_purchase_price": "allow" if vp else "deny", "adjustment.create": "allow" if sa else "deny",
                          "adjustment.post": "allow" if sa else "deny"})
            users[(vp, sa)] = us
    pkey = [{"item_id": P["id"], "warehouse_id": wa}]
    snap1 = snapshot(tenant)
    for (vp, sa), us in users.items():
        if vp and sa:
            continue
        tag = f"view_purchase_price={vp}, stock_adjustment={sa}"
        res = {
            "individual": us("POST", "valuation/opening", {"item_id": P["id"], "warehouse_id": wa, "opening_avg_cost": 5000})[0],
            "mass": us("POST", "valuation/opening-mass/apply", {})[0],
            "mass_keys": us("POST", "valuation/opening-mass/apply", {"keys": pkey})[0],
            "dry": us("POST", "valuation/replay/dry-run", {})[0],
            "replay_apply": us("POST", "valuation/replay/apply", {"fingerprint": dr["fingerprint"], "confirm": dr["confirm_phrase"]})[0]}
        check(f"Izin [{tag}]: individual/massal/dry-run/replay apply = 403", set(res.values()) == {403}, res)
    check("Request tidak berizin: database sebelum = sesudah (403 sebelum mutasi)", snapshot(tenant) == snap1,
          {k: (snap1[k], v) for k, v in snapshot(tenant).items() if v != snap1[k]})
    check("Status (read-only) butuh view_purchase_price: tanpa harga 403, dengan harga 200",
          [users[k]("GET", "valuation/opening-status")[0] for k in ((False, False), (False, True), (True, False))] == [403, 403, 200])
    ok_u = users[(True, True)]
    sc, d11 = ok_u("POST", "valuation/replay/dry-run", {})
    check("Izin lengkap: dry-run 200 (dalam cakupan divisi)", sc == 200 and {i["item_id"] for i in d11["items"]} == {Q["id"], R["id"]}, (sc, str(d11)[:200]))
    check("Izin lengkap: replay apply fingerprint salah -> 409 (validasi bisnis, bukan 403)",
          ok_u("POST", "valuation/replay/apply", {"fingerprint": "x", "confirm": dr["confirm_phrase"]})[0] == 409)
    check("Izin lengkap: Tetapkan individual pool Perlu Revaluasi -> 400 (diblokir)",
          ok_u("POST", "valuation/opening", {"item_id": Q["id"], "warehouse_id": wa, "opening_avg_cost": 10000})[0] == 400)

    # ---------------- isolasi divisi / gudang (user Divisi Teknik, Gudang C milik Divisi B)
    vkey = [{"item_id": V["id"], "warehouse_id": wc}]
    snap2 = snapshot(tenant)
    sc, st11 = ok_u("GET", "valuation/opening-status")
    check("Divisi: user Divisi Teknik tidak melihat pool Gudang C (Divisi B)", sc == 200 and row(st11["rows"], V["id"], wc) is None
          and row(st11["rows"], P["id"], wa) is not None, [r["item_name"] for r in st11.get("rows", [])])
    sc, mv = ok_u("POST", "valuation/opening-mass/apply", {"keys": vkey})
    check("Divisi: Tetapkan Massal pool divisi lain -> 0 diterapkan", sc == 200 and mv["applied"] == 0 and mv["skipped"], (sc, mv))
    check("Divisi: Tetapkan individual pool divisi lain -> 404",
          ok_u("POST", "valuation/opening", {"item_id": V["id"], "warehouse_id": wc, "opening_avg_cost": 2500})[0] == 404)
    sc, dv = ok_u("POST", "valuation/replay/dry-run", {"keys": vkey})
    check("Divisi: dry-run pool divisi lain kosong", sc == 200 and not dv["items"], dv.get("summary"))
    check("Divisi: tidak ada perubahan database", snapshot(tenant) == snap2)

    # ---------------- isolasi tenant
    import requests
    s1 = T.S
    T.S = requests.Session()  # sesi terpisah (tanpa cookie tenant pertama)
    T.setup()
    check("Tenant kedua aktif", call("GET", "auth/me")[1].get("tenant_id") not in (None, tenant))
    snap3 = snapshot(tenant)
    sc, other = call("GET", "valuation/opening-status")
    check("Tenant lain tidak melihat pool tenant ini", sc == 200 and not {r["item_id"] for r in other["rows"]} & {P["id"], Q["id"], N["id"], R["id"], S["id"]},
          len(other.get("rows", [])))
    sc, od = call("POST", "valuation/replay/dry-run", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}]})
    check("Tenant lain: dry-run pool tenant ini kosong", sc == 200 and not od.get("items"), od.get("summary"))
    sc, om = call("POST", "valuation/opening-mass/apply", {"keys": pkey})
    check("Tenant lain: Tetapkan Massal pool tenant ini -> 0", sc == 200 and om.get("applied") == 0, om)
    check("Tenant lain: Tetapkan individual pool tenant ini -> 404",
          call("POST", "valuation/opening", {"item_id": P["id"], "warehouse_id": wa, "opening_avg_cost": 5000})[0] == 404)
    check("Tenant lain: replay apply fingerprint tenant ini ditolak",
          call("POST", "valuation/replay/apply", {"fingerprint": dr["fingerprint"], "confirm": dr["confirm_phrase"]})[0] in (400, 409))
    check("Tenant lain: data tenant ini tidak berubah", snapshot(tenant) == snap3)
    T.S = s1

    # ---------------- Freeze Stock Opname: Tetapkan Massal / individual pada gudang Freeze -> tidak ada tulis sama sekali
    snapF = snapshot(tenant)
    sc, opm = call("POST", "opname", {"warehouse_id": wa, "division_id": M["div"]["id"], "mode": "freeze", "scope": "all"})
    sc, mf = call("POST", "valuation/opening-mass/apply", {"keys": pkey})
    check("Freeze: Tetapkan Massal pool gudang Freeze -> 0 diterapkan, dilewati dgn nomor Opname",
          sc == 200 and mf.get("applied") == 0 and opm.get("no", "?") in json.dumps(mf.get("skipped")), (sc, mf))
    sc, r = call("POST", "valuation/opening", {"item_id": P["id"], "warehouse_id": wa, "opening_avg_cost": 5000})
    check("Freeze: Tetapkan individual pool gudang Freeze -> 409", sc == 409 and opm.get("no", "?") in json.dumps(r), (sc, r))
    call("POST", f"opname/{opm.get('id')}/workflow", {"action": "cancel", "reason": "QA freeze tetapkan"})
    check("Freeze: tidak ada perubahan pool/ledger/audit valuasi (tanpa partial)",
          {k: v for k, v in snapshot(tenant).items() if k != "audit_logs"} == {k: v for k, v in snapF.items() if k != "audit_logs"},
          {k: (snapF[k], v) for k, v in snapshot(tenant).items() if v != snapF[k]})

    # ---------------- Tetapkan Massal (subset terpilih) + idempotensi
    sc, ma = call("POST", "valuation/opening-mass/apply", {"keys": [*pkey, {"item_id": Q["id"], "warehouse_id": wa}, {"item_id": Tt["id"], "warehouse_id": wa}]})
    sk = {x["item_id"]: x.get("status") for x in ma.get("skipped", [])}
    check("Tetapkan Massal terpilih: hanya P; Q (Perlu Revaluasi) & T (tanpa sumber) dilewati tanpa tulis",
          sc == 200 and ma.get("applied") == 1 and sk.get(Q["id"]) == "needs_replay" and sk.get(Tt["id"]) == "no_source", (sc, ma))
    pp = pool(P["id"], wa)
    check("P bernilai 50.000 (avg 5.000), qty tidak berubah", abs(pp.get("inventory_value", 0) - 50_000) < 0.01 and pp.get("qty_existing") == 10 and pp.get("status") == "valued", pp)
    sc, mall = call("POST", "valuation/opening-mass/apply", {})
    check("Tetapkan Massal semua: S & V", sc == 200 and mall.get("applied") == 2, mall)
    ps = pool(S["id"], wa)
    check("S bernilai dari import: 10 x 100 = 1.000 (bukan 500/700/900)", abs(ps.get("inventory_value", 0) - 1_000) < 0.01 and abs(ps.get("avg_cost", 0) - 100) < 1e-6, ps)
    snap4 = snapshot(tenant)
    sc, ma2 = call("POST", "valuation/opening-mass/apply", {})
    check("Tetapkan Massal idempotent: kedua kali 0", sc == 200 and ma2.get("applied") == 0, ma2)
    check("Idempotent: tidak ada ledger/audit/nilai ganda", snapshot(tenant) == snap4, {k: (snap4[k], v) for k, v in snapshot(tenant).items() if v != snap4[k]})
    sc, st1 = call("GET", "valuation/opening-status")
    check("Prioritas status: pool yang sudah dinilai = Sudah Dinilai", all((row(st1["rows"], i["id"], w) or {}).get("status") == "valued"
                                                                        for i, w in ((P, wa), (S, wa), (V, wc))), [(r["item_name"], r["status"]) for r in st1["rows"]])
    d1 = call("GET", "dashboard/control-center?period=this_month")[1]["inventory"]
    check("Dashboard: 'belum bernilai' turun 2 (P & V) setelah Tetapkan Massal", d1["unvalued_items"] == d0["unvalued_items"] - 2, (d0["unvalued_items"], d1["unvalued_items"]))

    # ---------------- apply replay
    sc, dr2 = call("POST", "valuation/replay/dry-run", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}]})
    fp = dr2.get("fingerprint")
    sc, r = call("POST", "valuation/replay/apply", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}], "fingerprint": fp, "confirm": "ya"})
    check("Apply tanpa frasa konfirmasi -> 400", sc == 400, (sc, r))
    sc, r = call("POST", "valuation/replay/apply", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}], "fingerprint": "x", "confirm": dr2["confirm_phrase"]})
    check("Apply dengan fingerprint salah -> 409", sc == 409, (sc, r))

    def sl_snapshot():
        c = conn()
        try:
            cur = c.cursor()
            cur.execute("SELECT doc FROM `stock_ledger` WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.item_id')) = %s", (Q["id"],))
            return sorted((d.get("id"), d.get("doc_type"), d.get("qty_in"), d.get("qty_out"), d.get("txn_at"), d.get("doc_id"))
                          for d in (json.loads(x[0]) for x in cur.fetchall()))
        finally:
            c.close()

    def db_doc(table, field, val):
        c = conn()
        try:
            cur = c.cursor()
            try:
                cur.execute(f"SELECT doc FROM `{table}` WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.{field}')) = %s", (val,))
            except Exception as exc:  # tabel lazy belum pernah ditulis -> tidak ada dokumen
                if getattr(exc, "args", None) and exc.args[0] == 1146:
                    return []
                raise
            return [json.loads(x[0]) for x in cur.fetchall()]
        finally:
            c.close()
    # Freeze Stock Opname di gudang yang TERDAMPAK berantai (B) -> revaluasi ditolak SEBELUM satu pool pun ditulis.
    qa0, qb0 = pool(Q["id"], wa), pool(Q["id"], wb)
    sc, opf = call("POST", "opname", {"warehouse_id": wb, "division_id": M["div"]["id"], "mode": "freeze", "scope": "all"})
    sc, r = call("POST", "valuation/replay/apply", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}], "fingerprint": fp, "confirm": dr2["confirm_phrase"]})
    check("Apply revaluasi saat gudang terdampak Freeze -> 409 + nomor Opname, tanpa partial (pool A & B tetap)",
          sc == 409 and opf.get("no", "?") in json.dumps(r) and pool(Q["id"], wa) == qa0 and pool(Q["id"], wb) == qb0
          and not [d for d in db_doc("valuation_replays", "fingerprint", fp) if d.get("status") in ("applying", "applied")], (sc, r))
    call("POST", f"opname/{opf['id']}/workflow", {"action": "cancel", "reason": "QA freeze replay"})
    sl_before = sl_snapshot()
    vl_before = {d["id"]: d for d in db_doc("valuation_ledger", "item_id", Q["id"])}
    sc, ap = call("POST", "valuation/replay/apply", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}], "fingerprint": fp, "confirm": dr2["confirm_phrase"]})
    check("Apply revaluasi 200", sc == 200 and ap.get("applied") is True, (sc, ap))
    qa2, qb2 = pool(Q["id"], wa), pool(Q["id"], wb)
    check("Sesudah apply: A 150.000 / avg 15.000, B 45.000; qty tetap 10 & 3",
          abs(qa2.get("inventory_value", 0) - 150_000) < 0.01 and abs(qa2.get("avg_cost", 0) - 15_000) < 1e-6 and qa2.get("qty_existing") == 10
          and abs(qb2.get("inventory_value", 0) - 45_000) < 0.01 and qb2.get("qty_existing") == 3, (qa2, qb2))
    check("Stock ledger (qty/tanggal/sumber) tidak berubah", len(sl_before) >= 5 and sl_snapshot() == sl_before, len(sl_before))
    vl_after = {d["id"]: d for d in db_doc("valuation_ledger", "item_id", Q["id"])}
    same_src = all(all(vl_after[i].get(x) == d.get(x) for x in ("qty_in", "qty_out", "txn_at", "doc_type", "doc_id", "line_id", "source_key"))
                   for i, d in vl_before.items())
    check("Valuation ledger: qty/tanggal/sumber entri lama tidak berubah", same_src and set(vl_before) <= set(vl_after))
    marks = [d for d in vl_after.values() if d.get("doc_type") == "Opening Valuation" and d.get("warehouse_id") == wa]
    check("Penanda Opening Valuation 100.000 dibuat pada waktu saldo awal (replay id tercatat)", len(marks) == 1 and abs(marks[0]["value_after"] - 100_000) < 0.01
          and marks[0].get("valuation_replay_id") == ap.get("run_id"), marks)
    chg = [d for d in vl_after.values() if d.get("valuation_replay_before")]
    check("Entri terdampak menyimpan nilai sebelum (audit) = 5", len(chg) == 5, len(chg))
    snap5 = snapshot(tenant)
    sc, ap2 = call("POST", "valuation/replay/apply", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}], "fingerprint": fp, "confirm": dr2["confirm_phrase"]})
    check("Apply ulang fingerprint sama -> idempotent (already_applied)", sc == 200 and ap2.get("already_applied") is True, (sc, ap2))
    sc, dr3 = call("POST", "valuation/replay/dry-run", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}]})
    check("Dry run sesudah apply: tidak ada lagi yang direplay untuk Q", not [i for i in dr3.get("items", []) if i["item_id"] == Q["id"]], dr3.get("summary"))
    sc, ap3 = call("POST", "valuation/replay/apply", {"keys": [{"item_id": Q["id"], "warehouse_id": wa}], "fingerprint": dr3.get("fingerprint"),
                                                       "confirm": dr2["confirm_phrase"]})
    check("Replay kedua atas state yang sudah direvaluasi -> ditolak (400)", sc == 400, (sc, ap3))
    check("Replay ulang: tidak ada efek ekonomi ganda (database identik)", snapshot(tenant) == snap5,
          {k: (snap5[k], v) for k, v in snapshot(tenant).items() if v != snap5[k]})
    sc, runs = call("GET", "valuation/replay/runs")
    run = (runs.get("rows") or [{}])[0]
    check("Audit run: siapa, kapan, sumber, ringkasan before/after", run.get("status") == "applied" and run.get("executed_by") and run.get("executed_at")
          and "Import Saldo Awal" in (run.get("source") or "") and abs(run["summary"]["after_value"] - 195_000) < 0.01, run)
    sc, st2 = call("GET", "valuation/opening-status")
    check("Sesudah apply: Q = Sudah Dinilai (tidak kembali Perlu Revaluasi walau punya histori mutasi)",
          (row(st2["rows"], Q["id"], wa) or {}).get("status") == "valued", row(st2["rows"], Q["id"], wa))
    tl2 = db_doc("transfer_lines", "transfer_id", trf["id"])
    check("Transfer line ikut nilai replay (75.000 / 15.000)", len(tl2) == 1 and abs(tl2[0].get("transfer_value", 0) - 75_000) < 0.01
          and abs(tl2[0].get("cost_snapshot", 0) - 15_000) < 1e-6, tl2)

    adj(wa, Q["id"], -1)
    qa3 = pool(Q["id"], wa)
    check("Engine MWA lanjut normal sesudah replay: keluar 1 @ 15.000 -> 135.000", abs(qa3.get("inventory_value", 0) - 135_000) < 0.01, qa3)
    inv = call("GET", "dashboard/control-center?period=this_month")[1]["inventory"]
    vs = call("GET", "reports/valuation-summary")[1]["total_value"]
    check("Nilai Persediaan hari ini = Valuation Summary sesudah koreksi", abs(inv["inventory_value"] - vs) < 0.01, (inv["inventory_value"], vs))
    for us in users.values():
        call("DELETE", f"users/{us.uid}", None, 200)


if __name__ == "__main__":
    main()
    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)
