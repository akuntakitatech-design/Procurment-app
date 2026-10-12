"""P7 — parity hasil sebelum/sesudah: GET endpoint yang sama ke backend BASE (main) dan backend P7, DB & user yang sama.

  python scripts/perf_p7_parity.py --base http://127.0.0.1:8032/api --new http://127.0.0.1:8031/api --cred /root/perf/cred_x20.json \
      [--cred2 file_user_terbatas.json] [--only label,...] [--out docs/perf/p7-parity.json]
JSON dibandingkan setelah normalisasi kunci waktu-generate; Excel dibandingkan per nilai sel (metadata file diabaikan); PDF
dibandingkan jumlah baris (header X-Report-Rows) + status. Read-only (hanya GET). Hanya untuk DB uji *_itest.
"""
import argparse
import hashlib
import io
import json
import os
import time

import requests

VOLATILE = {"generated_at", "server_time", "now", "elapsed_ms", "as_of_generated", "timing_ms"}

P = "page=1&page_size=25"
ENDPOINTS = [
    # (label, path, mode) mode: json | xlsx | pdf
    ("Dashboard", "dashboard", "json"),
    ("Dashboard Premium", "dashboard-premium", "json"),
    ("Control Center (bulan)", "dashboard/control-center?date_from=2026-09-01&date_to=2026-09-30", "json"),
    ("MRO array lama (tanpa page)", "mro", "json"), ("RO array lama", "ro", "json"), ("PO array lama", "po", "json"),
    ("DO array lama", "do", "json"), ("MI array lama", "mi", "json"), ("Transfer array lama", "transfers", "json"),
    ("Pinjam array lama", "loans", "json"), ("Penyesuaian array lama", "adjustments", "json"), ("Opname array lama", "opname", "json"),
    ("Invoice Vendor (array)", "vendor-invoices", "json"), ("Tagihan DO (array)", "vendor-invoices/do-billing", "json"),
    ("Invoice Vendor hal.1 +facets", f"vendor-invoices?{P}&facets=supplier_name,trace_division,trace_project,trace_spk,trace_po,do_nos,status", "json"),
    ("Invoice Vendor cari+sort", "vendor-invoices?page=3&page_size=50&q=INV&sort=amount&dir=desc", "json"),
    ("Invoice Vendor filter periode", f"vendor-invoices?{P}&date_from=2026-03-01&date_to=2026-05-31", "json"),
    ("Tagihan DO hal.1 +facets", f"vendor-invoices/do-billing?{P}&facets=supplier_name,division,project,spk,billing_status", "json"),
    ("Tagihan DO hal.terakhir", "vendor-invoices/do-billing?page=9999&page_size=100&sort=remaining&dir=asc", "json"),
    ("Ringkasan Invoice", "vendor-invoices/summary", "json"),
    ("SPK hal.1", f"spk?{P}", "json"), ("Kontrak Vendor hal.1", f"vendor-contracts?{P}", "json"),
    ("Inventory item-stock", f"inventory/item-stock?{P}", "json"), ("Inventory ledger", "inventory/ledger", "json"),
    ("Lap. Register PO", "report-center/register-po?page=1&page_size=50", "json"),
    ("Lap. posisi stok", "report-center/posisi-stok?page=1&page_size=50", "json"),
    ("Lap. MRO traceability", "report-center/mro-traceability?page=1&page_size=50&date_from=2026-09-01&date_to=2026-09-30", "json"),
    ("Lap. AP outstanding", "report-center/ap-outstanding?page=1&page_size=50", "json"),
    ("Export Register PO Excel", "report-center/register-po/export.xlsx", "xlsx"),
    ("Export daftar PO PDF (periode)", "report-center/txn-po/export.pdf?date_from=2026-09-01&date_to=2026-09-30", "pdf"),
    # --- tambahan parity lengkap (sesi 2026-10-12): MRO Traceability, detail, lifecycle, paging, Control Center tahunan
    ("MRO Traceability (laporan)", "reports/mro-traceability", "json"),
    ("MRO Traceability (laporan, periode)", "reports/mro-traceability?date_from=2026-01-01&date_to=2026-06-30", "json"),
    ("MRO Traceability export Excel", "reports/mro-traceability/export.xlsx", "xlsx"),
    ("Traceability MRO detail", "traceability/{mro_id}", "json"),
    ("Lifecycle MRO", "lifecycle/mro/{mro_id}", "json"), ("Lifecycle RO", "lifecycle/ro/{ro_id}", "json"),
    ("Lifecycle PO", "lifecycle/po/{po_id}", "json"), ("Lifecycle DO", "lifecycle/do/{do_id}", "json"),
    ("Detail MRO", "mro/{mro_id}", "json"), ("Detail RO", "ro/{ro_id}", "json"), ("Detail PO", "po/{po_id}", "json"),
    ("Detail DO", "do/{do_id}", "json"), ("Detail MI", "mi/{mi_id}", "json"), ("Detail Pinjam", "loans/{loan_id}", "json"),
    ("Control Center (tahun)", "dashboard/control-center?date_from=2026-01-01&date_to=2026-12-31", "json"),
    ("Control Center (default)", "dashboard/control-center", "json"),
    ("Drill price-control", "dashboard/drill/price-control", "json"), ("Drill SPK", "dashboard/drill/spk", "json"),
    ("Lap. lead time", "reports/lead-time", "json"), ("Lap. unit usage", "reports/unit-usage", "json"),
    ("Lap. MRO traceability periode tahun", "report-center/mro-traceability?page=1&page_size=50&date_from=2026-01-01&date_to=2026-12-31", "json"),
    ("Lap. outstanding RO", "report-center/outstanding-ro?page=1&page_size=50", "json"),
    ("Lap. outstanding PO", "report-center/outstanding-po?page=1&page_size=50", "json"),
    ("Approval inbox", "approvals/inbox", "json"), ("Cari global", "search?q=MRO", "json"),
    ("Pull RO untuk PO", "pull/ro-for-po", "json"), ("Pull PO untuk DO", "pull/po-for-do", "json"), ("Pull MRO untuk RO", "pull/mro-for-ro", "json"),
    ("MRO paging hal.1 (by design: total tanpa cap)", f"mro?{P}", "json"), ("PO paging hal.1 (by design)", f"po?{P}", "json"),
    ("DO paging hal.1 (by design)", f"do?{P}", "json"), ("MI paging hal.1", f"mi?{P}", "json"),
]
IDS = {"mro_id": "mro", "ro_id": "ro", "po_id": "po", "do_id": "do", "mi_id": "mi", "loan_id": "loans"}
RC_KEYS = ("adjustment-detail adjustment-register ap-aging ap-invoice-register ap-outstanding ap-outstanding-summary ap-payments "
           "ap-supplier-recap ap-supplier-recap-monthly hpp-mi hutang kartu-stok-nilai kartu-stok-qty lead-time loan-detail loan-register "
           "loan-return-register min-max-reorder mro-traceability mutasi-persediaan opname-detail opname-register outstanding-do "
           "outstanding-mro outstanding-po outstanding-ro pemakaian-barang persediaan posisi-stok price-compliance procurement register-do "
           "register-mi register-mro register-po register-ro rekap-nilai-do rekap-pembelian ringkasan-nilai riwayat-pergerakan-stok spk "
           "spk-budget spk-budget-do spk-budget-po transfer-detail transfer-register vendor-contract-list warehouse").split()
ENDPOINTS += [(f"Pusat Laporan {k} (tahun)", f"report-center/{k}?page=1&page_size=50&date_from=2026-01-01&date_to=2026-12-31", "json")
              for k in RC_KEYS]


def resolve_ids(api, cred):
    """ID dokumen contoh (terbaru) per modul dari server --new; dipakai sama untuk kedua server (DB sama)."""
    s = session(api, cred)
    out = {}
    for key, mod in IDS.items():
        r = s.get(f"{api}/{mod}?page=1&page_size=1", timeout=600)
        body = r.json() if r.status_code == 200 else {}
        items = body.get("items") if isinstance(body, dict) else body
        out[key] = (items or [{}])[0].get("id", "none")
    return out


def norm(x):
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x


def digest(r, mode):
    if mode == "json":
        body = norm(r.json())
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest(), body
    if mode == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True)
        cells = [[ws.title] + [list(row) for row in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
        return hashlib.sha256(json.dumps(cells, default=str).encode()).hexdigest(), None
    return f"rows={r.headers.get('x-report-rows')}", None


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: tipe {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: hanya di {'base' if k in a else 'new'}"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: panjang {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:80]!r} != {str(b)[:80]!r}"


def session(api, cred):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + s.post(f"{api}/auth/login", json=cred, timeout=120).json()["token"]
    return s


def seq(a, eps, users):
    """Satu server per tahap (base lalu P7) agar tidak ada dua server berat sekaligus di memori kontainer."""
    import pickle
    if a.seq_save:
        store = {}
        for uname, cred in users:
            sb = session(a.base, cred)
            for label, path, mode in eps:
                t0 = time.perf_counter(); r = sb.get(f"{a.base}/{path}", timeout=3600); ms = (time.perf_counter() - t0) * 1000
                h, body = digest(r, mode) if r.status_code == 200 else (None, None)
                store[(uname, label)] = {"status": r.status_code, "ms": round(ms), "digest": h, "body": body,
                                         "raw": None if r.status_code == 200 else r.content}
                print(f"saved {uname} {label} {r.status_code} {round(ms)} ms", flush=True)
                pickle.dump(store, open(a.seq_save, "wb"))
        return
    store = pickle.load(open(a.seq_compare, "rb"))
    res = json.load(open(a.out)) if os.path.exists(a.out) and os.environ.get("PARITY_APPEND") == "1" else []
    print("| User | Endpoint | base HTTP | P7 HTTP | identik | base ms | P7 ms | catatan |\n|---|---|---|---|---|---|---|---|", flush=True)
    for uname, cred in users:
        sn = session(a.new, cred)
        for label, path, mode in eps:
            b = store.get((uname, label))
            if b is None:
                continue
            t0 = time.perf_counter(); rn = sn.get(f"{a.new}/{path}", timeout=3600); tn = (time.perf_counter() - t0) * 1000
            note = ""
            if b["status"] == rn.status_code == 200:
                hn, bn = digest(rn, mode)
                same = b["digest"] == hn
                if not same:
                    note = (first_diff(b["body"], bn) if b["body"] is not None else f"{b['digest'][:12]} != {hn[:12]}") or "beda"
            else:
                same = b["status"] == rn.status_code and b["raw"] == rn.content
                note = f"status {b['status']}/{rn.status_code}"
            row = {"user": uname, "label": label, "path": path, "base_status": b["status"], "new_status": rn.status_code,
                   "identical": same, "base_ms": b["ms"], "new_ms": round(tn), "note": note, "mode": "berurutan"}
            res.append(row)
            print(f"| {uname} | {label} | {b['status']} | {rn.status_code} | {'YA' if same else 'TIDAK'} | {b['ms']} | {row['new_ms']} | {note} |", flush=True)
            json.dump(res, open(a.out, "w"), indent=1)
    bad = [r for r in res if not r["identical"]]
    print(f"\nidentik {len(res) - len(bad)}/{len(res)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--cred", required=True)
    ap.add_argument("--cred2", default="", help="user terbatas (cakupan divisi / tanpa view_purchase_price) — opsional")
    ap.add_argument("--cred-label", default="global")
    ap.add_argument("--only", default="")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--out", default="/app/docs/perf/p7-parity.json")
    ap.add_argument("--seq-save", default="", help="mode berurutan (hemat memori): ambil dari --base saja, simpan ke file")
    ap.add_argument("--seq-compare", default="", help="mode berurutan: ambil dari --new, bandingkan dengan file --seq-save")
    a = ap.parse_args()
    only = [x.strip().lower() for x in a.only.split(",") if x.strip()]
    excl = [x.strip().lower() for x in a.exclude.split(",") if x.strip()]
    eps = [e for e in ENDPOINTS if (not only or any(o in e[0].lower() for o in only)) and not any(o in e[0].lower() for o in excl)]
    users = [(a.cred_label, json.load(open(a.cred)))] + ([("terbatas", json.load(open(a.cred2)))] if a.cred2 else [])
    if any("{" in e[1] for e in eps):
        ids = resolve_ids(a.base if a.seq_save else a.new, users[0][1])
        print("ID contoh:", ids, flush=True)
        eps = [(lbl, p.format(**ids) if "{" in p else p, m) for lbl, p, m in eps]
    if a.seq_save or a.seq_compare:
        return seq(a, eps, users)
    res = []
    print("| User | Endpoint | base HTTP | P7 HTTP | identik | base ms | P7 ms | catatan |\n|---|---|---|---|---|---|---|---|", flush=True)
    for uname, cred in users:
        # satu login dipakai kedua server (DB & JWT_SECRET sama): kebijakan 1 sesi aktif per user mencabut sesi login kedua
        sn = session(a.new, cred)
        sb = requests.Session()
        sb.headers["Authorization"] = sn.headers["Authorization"]
        for label, path, mode in eps:
            t0 = time.perf_counter(); rb = sb.get(f"{a.base}/{path}", timeout=3600); tb = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter(); rn = sn.get(f"{a.new}/{path}", timeout=3600); tn = (time.perf_counter() - t0) * 1000
            note, same = "", False
            if rb.status_code == rn.status_code == 200:
                hb, bb = digest(rb, mode)
                hn, bn = digest(rn, mode)
                same = hb == hn
                if not same and bb is not None:
                    note = first_diff(bb, bn) or "beda"
                elif not same:
                    note = f"{hb[:12]} != {hn[:12]}"
            else:
                same = rb.status_code == rn.status_code and rb.content == rn.content
                note = f"status {rb.status_code}/{rn.status_code}"
            row = {"user": uname, "label": label, "path": path, "base_status": rb.status_code, "new_status": rn.status_code,
                   "identical": same, "base_ms": round(tb), "new_ms": round(tn), "note": note}
            res.append(row)
            print(f"| {uname} | {label} | {rb.status_code} | {rn.status_code} | {'YA' if same else 'TIDAK'} | {row['base_ms']} | {row['new_ms']} | {note} |",
                  flush=True)
            json.dump(res, open(a.out, "w"), indent=1)
    bad = [r for r in res if not r["identical"]]
    print(f"\nidentik {len(res) - len(bad)}/{len(res)}")


if __name__ == "__main__":
    main()
