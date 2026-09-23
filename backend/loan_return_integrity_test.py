"""Disposable integration test for loan/return stock integrity."""
import os
import sys
import time
import uuid
import requests

API = os.environ.get("TEST_API_URL", "http://loan-return-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


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
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    check(r.status_code == 200, f"Master {name} berhasil dibuat")
    return r.json()


def stock(s, item_id, wh_id):
    r = s.get(f"{API}/item-warehouse", params={"warehouse_id": wh_id, "item_id": item_id}, timeout=15)
    check(r.status_code == 200, "Posisi stok dapat dibaca")
    rows = r.json()
    return float(rows[0].get("current_stock", 0)) if rows else 0.0


def approx(a, b):
    return abs(float(a) - float(b)) < 1e-6


def detail(s, loan_id):
    r = s.get(f"{API}/loans/{loan_id}", timeout=15)
    check(r.status_code == 200, "Detail loan dapat dibaca")
    return r.json()


def return_docs(s, loan_id):
    r = s.get(f"{API}/loans/{loan_id}/returns", timeout=15)
    check(r.status_code == 200, "Daftar return dapat dibaca")
    return r.json()


def make_loan(s, from_wh, to_wh, item_id, qty, label):
    r = s.post(f"{API}/loans", json={
        "date": "2026-09-20", "due_date": "2026-09-27",
        "from_warehouse_id": from_wh, "to_warehouse_id": to_wh,
        "requester": "Integrity Tester", "notes": label,
        "lines": [{"item_id": item_id, "qty": qty, "unit": "pcs", "notes": label}],
    }, timeout=15)
    check(r.status_code == 200, f"{label} berhasil dibuat")
    return r.json()


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]
    div = master(s, "divisions", {"code": f"DLR{run}", "name": f"Loan Return {run}"})
    wh_a = master(s, "warehouses", {"code": f"LRA{run}", "name": f"Gudang A {run}", "division_id": div["id"]})
    wh_b = master(s, "warehouses", {"code": f"LRB{run}", "name": f"Gudang B {run}", "division_id": div["id"]})
    item = master(s, "items", {"code": f"LRI{run}", "name": f"Bearing {run}", "unit": "pcs", "division_id": div["id"]})

    opening = s.post(f"{API}/adjustments", json={
        "date": "2026-09-20", "warehouse_id": wh_a["id"], "division_id": div["id"],
        "adj_type": "Saldo Awal Test", "reason": "Integrity test", "notes": "LOAN RETURN TEST",
        "lines": [{"item_id": item["id"], "adjustment": 20, "reason": "opening"}],
    }, timeout=15)
    check(opening.status_code == 200, "Saldo awal 20 berhasil dibuat")

    loan = make_loan(s, wh_a["id"], wh_b["id"], item["id"], 6, "LOAN UTAMA")
    loan_id = loan["id"]
    d = detail(s, loan_id)
    line_id = d["lines"][0]["id"]
    check(d.get("status") == "Open" and approx(d.get("outstanding_total"), 6), "Loan awal Open dengan outstanding 6")
    check(approx(stock(s, item["id"], wh_a["id"]), 14), "Loan mengurangi stok pemberi menjadi 14")
    check(approx(stock(s, item["id"], wh_b["id"]), 6), "Loan menambah stok peminjam menjadi 6")

    # Loan kedua untuk menguji foreign loan_line dan menjaga perhitungan stok tetap eksplisit.
    loan2 = make_loan(s, wh_a["id"], wh_b["id"], item["id"], 2, "LOAN PEMBANDING")
    foreign_line = detail(s, loan2["id"])["lines"][0]["id"]
    before = len(return_docs(s, loan_id))
    bad = s.post(f"{API}/loans/{loan_id}/return", json={
        "date": "2026-09-20", "lines": [{"loan_line_id": foreign_line, "qty": 1}]
    }, timeout=15)
    check(bad.status_code in (400, 409), "Baris dari loan lain ditolak")
    check(len(return_docs(s, loan_id)) == before, "Foreign-line gagal tidak meninggalkan return orphan")

    partial = s.post(f"{API}/loans/{loan_id}/return", json={
        "date": "2026-09-20", "notes": "RETURN 2", "lines": [{"loan_line_id": line_id, "qty": 2}]
    }, timeout=15)
    check(partial.status_code == 200, "Partial return 2 berhasil")
    d = detail(s, loan_id)
    check(d.get("status") == "Partial Returned" and approx(d.get("outstanding_total"), 4), "Partial return menghasilkan outstanding 4")
    check(approx(stock(s, item["id"], wh_a["id"]), 14), "Stok pemberi benar setelah dua loan dan return 2")
    check(approx(stock(s, item["id"], wh_b["id"]), 6), "Stok peminjam benar setelah dua loan dan return 2")

    docs = return_docs(s, loan_id)
    check(len(docs) == 1 and approx(docs[0]["lines"][0]["qty"], 2), "Return line qty 2 tercatat")
    rid = docs[0]["id"]

    # Invalid over-return may not create an orphan header or alter stock.
    count_before = len(docs)
    a_before = stock(s, item["id"], wh_a["id"])
    b_before = stock(s, item["id"], wh_b["id"])
    over = s.post(f"{API}/loans/{loan_id}/return", json={
        "date": "2026-09-20", "lines": [{"loan_line_id": line_id, "qty": 5}]
    }, timeout=15)
    check(over.status_code in (400, 409), "Over-return ditolak")
    check(len(return_docs(s, loan_id)) == count_before, "Over-return gagal tidak meninggalkan header orphan")
    check(approx(stock(s, item["id"], wh_a["id"]), a_before), "Over-return tidak mengubah stok pemberi")
    check(approx(stock(s, item["id"], wh_b["id"]), b_before), "Over-return tidak mengubah stok peminjam")

    cap = s.get(f"{API}/loan-returns/{rid}/capability", timeout=15)
    check(cap.status_code == 200 and cap.json().get("can_edit") is True, "Return partial dapat diedit")
    edit = s.put(f"{API}/loan-returns/{rid}", json={
        "date": "2026-09-20", "notes": "RETURN EDIT 1",
        "lines": [{"loan_line_id": line_id, "qty": 1}],
    }, timeout=15)
    check(edit.status_code == 200, "Edit return 2 menjadi 1 berhasil")
    d = detail(s, loan_id)
    check(approx(d.get("outstanding_total"), 5), "Edit return menghasilkan outstanding 5")
    check(approx(stock(s, item["id"], wh_a["id"]), 13), "Edit return menghasilkan stok pemberi benar")
    check(approx(stock(s, item["id"], wh_b["id"]), 7), "Edit return menghasilkan stok peminjam benar")

    delete_ret = s.delete(f"{API}/loan-returns/{rid}", timeout=15)
    check(delete_ret.status_code == 200, "Delete return melakukan reversal")
    d = detail(s, loan_id)
    check(d.get("status") == "Open" and approx(d.get("outstanding_total"), 6), "Delete return mengembalikan loan ke Open")
    check(approx(stock(s, item["id"], wh_a["id"]), 12), "Delete return mengembalikan stok pemberi ke loan-only")
    check(approx(stock(s, item["id"], wh_b["id"]), 8), "Delete return mengembalikan stok peminjam ke loan-only")

    full = s.post(f"{API}/loans/{loan_id}/return", json={
        "date": "2026-09-20", "notes": "RETURN FULL", "lines": [{"loan_line_id": line_id, "qty": 6}]
    }, timeout=15)
    check(full.status_code == 200, "Full return berhasil")
    d = detail(s, loan_id)
    check(d.get("status") == "Completed" and approx(d.get("outstanding_total"), 0), "Full return membuat loan Completed")
    check(approx(stock(s, item["id"], wh_a["id"]), 18), "Full return mengembalikan stok ke pemberi")
    check(approx(stock(s, item["id"], wh_b["id"]), 2), "Peminjam tinggal memiliki loan pembanding 2")

    active = return_docs(s, loan_id)
    full_rid = active[0]["id"]
    lcap = s.get(f"{API}/transactions/loan/{loan_id}/capability", timeout=15)
    check(lcap.status_code == 200 and lcap.json().get("can_delete") is False, "Return aktif memblokir delete loan")
    blocked = s.delete(f"{API}/transactions/loan/{loan_id}", timeout=15)
    check(blocked.status_code == 409, "Delete loan dengan return aktif ditolak")

    check(s.delete(f"{API}/loan-returns/{full_rid}", timeout=15).status_code == 200, "Full return dapat direversal")
    check(s.delete(f"{API}/transactions/loan/{loan_id}", timeout=15).status_code == 200, "Loan utama dapat direversal setelah return dihapus")
    check(s.delete(f"{API}/transactions/loan/{loan2['id']}", timeout=15).status_code == 200, "Loan pembanding dapat direversal")
    check(approx(stock(s, item["id"], wh_a["id"]), 20), "Semua reversal mengembalikan gudang pemberi ke 20")
    check(approx(stock(s, item["id"], wh_b["id"]), 0), "Semua reversal mengembalikan gudang peminjam ke 0")

    print("\nRESULT: PASS - loan/return dan reversal stok konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
