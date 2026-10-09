"""Disposable integration test for stock-opname integrity and reversal."""
from integrity_master_fixture import fill_required  # noqa: E402
import os
import sys
import time
import uuid
import requests
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

# fixture: tanggal hari ini (backdate guard valuasi menolak posting mundur relatif transaksi terakhir)
TODAY = _dt.now(_tz.utc).date().isoformat()
DUE = (_dt.now(_tz.utc) + _td(days=7)).date().isoformat()

API = os.environ.get("TEST_API_URL", "http://stock-opname-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


def approx(a, b):
    return abs(float(a) - float(b)) < 1e-6


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend test tidak siap")


def login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    check(r.status_code == 200, "Login admin berhasil")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def master(s, name, payload):
    payload = fill_required(s, API, name, payload)
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    check(r.status_code == 200, f"Master {name} berhasil dibuat")
    return r.json()


def stock(s, item_id, wh_id):
    r = s.get(f"{API}/item-warehouse", params={"warehouse_id": wh_id, "item_id": item_id}, timeout=15)
    check(r.status_code == 200, "Posisi stok dapat dibaca")
    rows = r.json()
    return float(rows[0].get("current_stock", 0)) if rows else 0.0


def adjustment(s, wh, div, item, delta, note):
    return s.post(f"{API}/adjustments", json={
        "date": TODAY, "warehouse_id": wh, "division_id": div,
        "adj_type": "Test", "reason": note, "notes": note,
        "lines": [{"item_id": item, "adjustment": delta, **({"approved_unit_cost": 1000} if delta > 0 else {}), "reason": note}],
    }, timeout=15)


def cancel(s, did, reason):
    return s.post(f"{API}/opname/{did}/workflow", json={"action": "cancel", "reason": reason}, timeout=15)


def create_opname(s, wh, div, note):
    r = s.post(f"{API}/opname", json={
        "date": TODAY, "warehouse_id": wh, "division_id": div,
        "mode": "live", "scope": "division", "notes": note,
    }, timeout=15)
    check(r.status_code == 200, f"{note} berhasil dibuat")
    return r.json()


def detail(s, did):
    r = s.get(f"{API}/opname/{did}", timeout=15)
    check(r.status_code == 200, "Detail Stock Opname dapat dibaca")
    return r.json()


def line_map(doc):
    return {row["item_id"]: row for row in doc.get("lines", [])}


def count(s, did, pairs, status="Review"):
    return s.put(f"{API}/opname/{did}/count", json={
        "status": status,
        "lines": [{"line_id": line_id, "counted": qty, "reason": "Selisih fisik QA"} for line_id, qty in pairs],
    }, timeout=15)


def main():
    wait_api()
    s = login()
    # fixture: Direct MI default nonaktif (mi_mode mro_only) -> aktifkan untuk tenant test
    check(s.put(f"{API}/settings/mi", json={"mi_mode": "mro_plus_direct"}, timeout=15).status_code == 200, "Mode MI + Direct diaktifkan untuk test")
    run = uuid.uuid4().hex[:8]
    div = master(s, "divisions", {"code": f"OPN{run}", "name": f"Opname {run}"})
    wh = master(s, "warehouses", {"code": f"OPW{run}", "name": f"Gudang Opname {run}", "division_id": div["id"]})
    item_a = master(s, "items", {"code": f"OPA{run}", "name": f"Bearing A {run}", "unit": "pcs", "division_id": div["id"]})
    item_b = master(s, "items", {"code": f"OPB{run}", "name": f"Bearing B {run}", "unit": "pcs", "division_id": div["id"]})

    check(adjustment(s, wh["id"], div["id"], item_a["id"], 20, "OPEN A").status_code == 200, "Saldo awal item A = 20")
    check(adjustment(s, wh["id"], div["id"], item_b["id"], 10, "OPEN B").status_code == 200, "Saldo awal item B = 10")

    op1 = create_opname(s, wh["id"], div["id"], "OPNAME UTAMA")
    op1_id = op1["id"]
    lines1 = line_map(op1)
    check(len(lines1) == 2, "Snapshot opname utama memuat dua barang")
    check(approx(lines1[item_a["id"]]["snapshot"], 20) and approx(lines1[item_b["id"]]["snapshot"], 10), "Snapshot tercatat 20 dan 10")

    incomplete = s.post(f"{API}/opname/{op1_id}/submit", timeout=15)
    check(incomplete.status_code == 400, "Submit sebelum seluruh barang dihitung ditolak")

    neg = count(s, op1_id, [(lines1[item_a["id"]]["id"], -1)])
    check(neg.status_code == 400, "Qty hitung negatif ditolak")
    after_neg = line_map(detail(s, op1_id))
    check(after_neg[item_a["id"]].get("counted") is None and after_neg[item_b["id"]].get("counted") is None,
          "Request negatif tidak merusak dokumen")

    # Aturan baru: satu gudang hanya satu Opname aktif -> Opname kedua di gudang sama ditolak (409).
    dup = s.post(f"{API}/opname", json={"date": TODAY, "warehouse_id": wh["id"], "division_id": div["id"], "mode": "live", "scope": "division"}, timeout=15)
    check(dup.status_code == 409, "Opname kedua pada gudang yang sama ditolak (1 gudang = 1 Opname aktif)")
    wh2 = master(s, "warehouses", {"code": f"OPX{run}", "name": f"Gudang Pembanding {run}", "division_id": div["id"]})
    check(adjustment(s, wh2["id"], div["id"], item_a["id"], 5, "OPEN A2").status_code == 200, "Saldo item A di gudang pembanding = 5")
    op2 = create_opname(s, wh2["id"], div["id"], "OPNAME PEMBANDING")
    foreign = line_map(op2)[item_a["id"]]["id"]
    bad_owner = count(s, op1_id, [(foreign, 19)])
    check(bad_owner.status_code == 400, "Baris dari Stock Opname lain ditolak")

    good = count(s, op1_id, [
        (lines1[item_a["id"]]["id"], 17),
        (lines1[item_b["id"]]["id"], 12),
    ])
    check(good.status_code == 200, "Hasil hitung 17 dan 12 tersimpan")
    check(s.post(f"{API}/opname/{op1_id}/submit", timeout=15).status_code == 200, "Stock Opname dapat disubmit setelah lengkap")
    posted = s.post(f"{API}/opname/{op1_id}/post", timeout=15)
    check(posted.status_code == 200 and posted.json().get("status") == "Posted", "Stock Opname berhasil diposting")
    check(approx(stock(s, item_a["id"], wh["id"]), 17), "Variance -3 menghasilkan stok A = 17")
    check(approx(stock(s, item_b["id"], wh["id"]), 12), "Variance +2 menghasilkan stok B = 12")
    check(s.post(f"{API}/opname/{op1_id}/post", timeout=15).status_code in (400, 409), "Double posting ditolak")
    check(count(s, op1_id, [(lines1[item_a["id"]]["id"], 18)]).status_code == 409, "Endpoint count tidak dapat mengubah opname Posted")

    current = detail(s, op1_id)
    current_lines = line_map(current)
    edit_payload = {
        "date": TODAY, "warehouse_id": wh["id"], "division_id": div["id"],
        "mode": "live", "scope": "division", "notes": "KOREKSI POSTED",
        "lines": [
            {"id": current_lines[item_a["id"]]["id"], "item_id": item_a["id"], "snapshot": 20, "counted": 18},
            {"id": current_lines[item_b["id"]]["id"], "item_id": item_b["id"], "snapshot": 10, "counted": 11},
        ],
    }
    edit = s.put(f"{API}/transactions/opname/{op1_id}", json=edit_payload, timeout=15)
    check(edit.status_code == 200, "Koreksi opname Posted berhasil dengan reversal")
    check(approx(stock(s, item_a["id"], wh["id"]), 18), "Edit Posted menghasilkan stok A = 18")
    check(approx(stock(s, item_b["id"], wh["id"]), 11), "Edit Posted menghasilkan stok B = 11")

    edited = detail(s, op1_id)
    edited_lines = line_map(edited)
    tamper = dict(edit_payload)
    tamper["lines"] = [
        {"id": edited_lines[item_a["id"]]["id"], "item_id": item_a["id"], "snapshot": 999, "counted": 18},
        {"id": edited_lines[item_b["id"]]["id"], "item_id": item_b["id"], "snapshot": 10, "counted": 11},
    ]
    bad_snapshot = s.put(f"{API}/transactions/opname/{op1_id}", json=tamper, timeout=15)
    check(bad_snapshot.status_code == 400, "Snapshot opname Posted tidak dapat dimanipulasi")
    check(approx(stock(s, item_a["id"], wh["id"]), 18) and approx(stock(s, item_b["id"], wh["id"]), 11), "Edit invalid tidak mengubah stok")

    dele = s.delete(f"{API}/transactions/opname/{op1_id}", timeout=15)
    check(dele.status_code == 200, "Delete opname Posted melakukan reversal")
    check(approx(stock(s, item_a["id"], wh["id"]), 20), "Reversal opname mengembalikan stok A = 20")
    check(approx(stock(s, item_b["id"], wh["id"]), 10), "Reversal opname mengembalikan stok B = 10")

    # Stale snapshot must never post a variance that would make physical stock negative.
    stale = create_opname(s, wh["id"], div["id"], "OPNAME STALE")
    stale_lines = line_map(stale)
    check(count(s, stale["id"], [
        (stale_lines[item_a["id"]]["id"], 0),
        (stale_lines[item_b["id"]]["id"], 10),
    ]).status_code == 200, "Opname stale selesai dihitung")
    movement = adjustment(s, wh["id"], div["id"], item_a["id"], -15, "MOVEMENT AFTER SNAPSHOT")
    check(movement.status_code == 200 and approx(stock(s, item_a["id"], wh["id"]), 5), "Pergerakan stok setelah snapshot menghasilkan stok A = 5")
    # Mode Live (kronologis): mutasi bertanggal <= waktu hitung yang diinput SETELAH hitung -> baris wajib dihitung ulang.
    blocked_submit = s.post(f"{API}/opname/{stale['id']}/submit", timeout=15)
    check(blocked_submit.status_code == 400 and "dihitung ulang" in blocked_submit.text, "Opname stale diblokir: barang perlu dihitung ulang")
    blocked_post = s.post(f"{API}/opname/{stale['id']}/post", timeout=15)
    check(blocked_post.status_code == 409, "Posting stale (belum Waiting Approval) ditolak")
    check(approx(stock(s, item_a["id"], wh["id"]), 5), "Posting stale gagal tidak mengubah stok")
    check(cancel(s, stale["id"], "Snapshot basi").status_code == 200, "Opname stale dibatalkan (lock gudang dilepas)")
    move_id = movement.json()["id"]
    check(s.delete(f"{API}/transactions/adjustment/{move_id}", timeout=15).status_code == 200, "Movement test dapat direversal")
    check(approx(stock(s, item_a["id"], wh["id"]), 20), "Reversal movement mengembalikan stok A = 20")

    # Positive opname variance that has already been consumed may not be reversed into negative stock.
    plus = create_opname(s, wh["id"], div["id"], "OPNAME PLUS")
    plus_lines = line_map(plus)
    check(count(s, plus["id"], [
        (plus_lines[item_a["id"]]["id"], 25),
        (plus_lines[item_b["id"]]["id"], 10),
    ]).status_code == 200, "Opname plus selesai dihitung")
    check(s.post(f"{API}/opname/{plus['id']}/submit", timeout=15).status_code == 200, "Opname plus diajukan approval")
    check(s.post(f"{API}/opname/{plus['id']}/post", timeout=15).status_code == 200, "Opname variance +5 berhasil diposting")
    check(approx(stock(s, item_a["id"], wh["id"]), 25), "Variance +5 menghasilkan stok A = 25")

    mi = s.post(f"{API}/mi", json={
        "date": TODAY, "division_id": div["id"], "default_warehouse_id": wh["id"],
        "receiver": "Opname Tester", "department": "Workshop", "source_type": "Direct",
        "notes": "CONSUME OPNAME PLUS",
        "lines": [{"item_id": item_a["id"], "qty": 23, "unit": "pcs", "warehouse_id": wh["id"]}],
    }, timeout=15)
    check(mi.status_code == 200 and approx(stock(s, item_a["id"], wh["id"]), 2), "MI mengonsumsi stok hasil opname hingga tersisa 2")
    cap = s.get(f"{API}/transactions/opname/{plus['id']}/capability", timeout=15)
    check(cap.status_code == 200 and cap.json().get("can_delete") is False, "Opname plus yang stoknya sudah terpakai diblokir untuk delete")
    check(s.delete(f"{API}/transactions/opname/{plus['id']}", timeout=15).status_code == 409, "Delete opname plus yang akan membuat stok minus ditolak")
    check(s.delete(f"{API}/transactions/mi/{mi.json()['id']}", timeout=15).status_code == 200, "MI test dapat direversal")
    check(s.delete(f"{API}/transactions/opname/{plus['id']}", timeout=15).status_code == 200, "Opname plus dapat direversal setelah stok tersedia")
    check(approx(stock(s, item_a["id"], wh["id"]), 20), "Semua reversal mengembalikan stok A = 20")

    # Guard stok negatif saat posting (pra-validasi sebelum movement pertama) tetap berlaku: mutasi bertanggal
    # SETELAH tanggal hitung tidak memicu hitung ulang (kronologis valid), tetapi stok fisik turun di bawah selisih.
    neg_op = create_opname(s, wh["id"], div["id"], "OPNAME GUARD NEGATIF")
    neg_lines = line_map(neg_op)
    check(count(s, neg_op["id"], [
        (neg_lines[item_a["id"]]["id"], 0),
        (neg_lines[item_b["id"]]["id"], 10),
    ]).status_code == 200, "Opname guard negatif selesai dihitung (A = 0, selisih -20)")
    check(s.post(f"{API}/opname/{neg_op['id']}/submit", timeout=15).status_code == 200, "Opname guard negatif diajukan approval")
    later = s.post(f"{API}/adjustments", json={
        "date": DUE, "warehouse_id": wh["id"], "division_id": div["id"], "adj_type": "Test",
        "reason": "MOVEMENT SETELAH TANGGAL HITUNG", "notes": "MOVEMENT SETELAH TANGGAL HITUNG",
        "lines": [{"item_id": item_a["id"], "adjustment": -15, "reason": "MOVEMENT SETELAH TANGGAL HITUNG"}],
    }, timeout=15)
    check(later.status_code == 200 and approx(stock(s, item_a["id"], wh["id"]), 5), "Mutasi bertanggal setelah hitung menurunkan stok A = 5")
    ledger_before = s.get(f"{API}/inventory/ledger", params={"item_id": item_a["id"], "warehouse_id": wh["id"]}, timeout=15)
    neg_post = s.post(f"{API}/opname/{neg_op['id']}/post", timeout=15)
    check(neg_post.status_code == 409 and "negatif" in neg_post.text, "Posting yang akan membuat stok negatif ditolak (409)")
    check(approx(stock(s, item_a["id"], wh["id"]), 5) and approx(stock(s, item_b["id"], wh["id"]), 10), "Posting ditolak tanpa partial write stok")
    ledger_after = s.get(f"{API}/inventory/ledger", params={"item_id": item_a["id"], "warehouse_id": wh["id"]}, timeout=15)
    check(ledger_before.status_code == 200 and ledger_after.status_code == 200
          and len(ledger_before.json()) == len(ledger_after.json())
          and not [r for r in ledger_after.json() if r.get("doc_id") == neg_op["id"]], "Posting ditolak tanpa partial write ledger")
    check(detail(s, neg_op["id"]).get("status") == "Waiting Approval", "Dokumen tetap Waiting Approval setelah posting ditolak")
    check(cancel(s, neg_op["id"], "QA guard negatif").status_code == 200, "Opname guard negatif dibatalkan")

    print("\nRESULT: PASS - Stock Opname, posting, koreksi, dan reversal stok konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
