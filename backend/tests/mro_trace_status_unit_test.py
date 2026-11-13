"""Unit test kolom laporan MRO Traceability (harga satuan + dua status terpisah).

Yang diuji (`backend/reporting/reports_procurement.py`):
- Harga Satuan = Nilai PO / Qty PO; None bila kolom harga disembunyikan atau belum ada PO.
- Status DO = status PENERIMAAN: Diterima / Diterima Sebagian / Belum Diterima / "-" (tanpa PO).
- Status MI tetap Open / Partial / Completed (mengikuti outstanding MI).
- Urutan & label kolom pada ReportSpec: Harga Satuan tepat setelah Qty PO, Status DO tepat setelah
  Total DO, Status MI di ujung setelah Outstanding (tidak diduplikasi).

Jalankan: backend/.venv/Scripts/python.exe tests/mro_trace_status_unit_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reporting.reports_procurement as RP  # noqa: E402
from reporting.registry import REGISTRY  # noqa: E402

fail = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info not in ("", None) else ""))
    if not ok:
        fail.append(name)


def row(**kw):
    base = {"mro_id": "m1", "mro_refs": [{"no": "MRO/1", "date": "2026-11-01"}], "request": 10.0,
            "qty_po": 0.0, "qty_received": 0.0, "qty_mi": 0.0, "outstanding": 10.0, "status": "Open"}
    base.update(kw)
    return base


# --- Harga satuan = Nilai PO / Qty PO
f = RP._flat(row(qty_po=1.0, po_gross=1289000.0))
check("harga satuan = Nilai PO / Qty PO", f["po_unit_price"] == 1289000.0, f["po_unit_price"])

f = RP._flat(row(qty_po=4.0, po_gross=1000000.0))
check("harga satuan dirata-rata sesuai qty (1.000.000 / 4)", f["po_unit_price"] == 250000.0, f["po_unit_price"])

f = RP._flat(row(qty_po=10.0, po_gross=None))
check("harga satuan None bila kolom harga disembunyikan", f["po_unit_price"] is None, f["po_unit_price"])

f = RP._flat(row(qty_po=0.0, po_gross=0.0))
check("harga satuan None bila belum ada PO", f["po_unit_price"] is None, f["po_unit_price"])

f = RP._flat(row(qty_po=None, po_gross=None))
check("qty_po None tidak error", f["po_unit_price"] is None and f["do_status"] == "-", f["do_status"])

# --- Status DO (penerimaan) terpisah dari Status MI
f = RP._flat(row(qty_po=10.0, qty_received=10.0, status="Completed"))
check("status DO: diterima penuh", f["do_status"] == "Diterima", f["do_status"])

f = RP._flat(row(qty_po=10.0, qty_received=4.0, status="Partial"))
check("status DO: diterima sebagian", f["do_status"] == "Diterima Sebagian", f["do_status"])

f = RP._flat(row(qty_po=10.0, qty_received=0.0, status="Open"))
check("status DO: belum diterima", f["do_status"] == "Belum Diterima", f["do_status"])

f = RP._flat(row(qty_po=10.0, qty_received=12.0))
check("status DO: kelebihan terima tetap Diterima", f["do_status"] == "Diterima", f["do_status"])

f = RP._flat(row(qty_po=0.0, qty_received=0.0, status="Open"))
check("status DO: tanpa PO = '-'", f["do_status"] == "-", f["do_status"])

# Status MI tidak boleh ikut berubah oleh status penerimaan
f = RP._flat(row(qty_po=10.0, qty_received=10.0, qty_mi=0.0, status="Open"))
check("status MI tetap Open walau DO sudah diterima semua", f["status"] == "Open", f["status"])

f = RP._flat(row(qty_po=10.0, qty_received=0.0, qty_mi=10.0, outstanding=0.0, status="Completed"))
check("status MI tetap Completed walau DO belum diterima", f["status"] == "Completed", f["status"])

# --- Urutan & label kolom
spec = REGISTRY["mro-traceability"]
keys = [c.key for c in spec.columns]
labels = {c.key: c.label for c in spec.columns}
check("jumlah kolom = 36", len(keys) == 36, len(keys))
check("harga satuan tepat setelah Qty PO", keys[keys.index("qty_po") + 1] == "po_unit_price",
      " -> ".join(keys[keys.index("qty_po") - 1:keys.index("qty_po") + 2]))
check("label harga satuan", labels["po_unit_price"] == "Harga Satuan", labels["po_unit_price"])
check("status DO tepat setelah Total DO", keys[keys.index("do_total") + 1] == "do_status",
      " -> ".join(keys[keys.index("do_total") - 1:keys.index("do_total") + 2]))
check("status MI setelah Outstanding", keys[keys.index("outstanding") + 1] == "status",
      " -> ".join(keys[keys.index("outstanding"):keys.index("outstanding") + 2]))
check("label dua status berbeda & jelas",
      labels["do_status"] == "Status DO" and labels["status"] == "Status MI",
      f'{labels["do_status"]} / {labels["status"]}')
check("status tidak diduplikasi", keys.count("status") == 1 and keys.count("do_status") == 1)
check("harga satuan & status tidak dijumlahkan di baris TOTAL",
      not next(c for c in spec.columns if c.key == "po_unit_price").total
      and not next(c for c in spec.columns if c.key == "do_status").total
      and not next(c for c in spec.columns if c.key == "status").total)
check("harga satuan mengikuti izin harga (price=True)",
      next(c for c in spec.columns if c.key == "po_unit_price").price)
check("filter status diberi label 'Status MI'",
      next(x for x in spec.filters if x.key == "status").label == "Status MI")

print(f"\n{'SEMUA PASS' if not fail else str(len(fail)) + ' GAGAL -> ' + str(fail)}  ({len(keys)} kolom)")
sys.exit(1 if fail else 0)
