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
check("jumlah kolom = 37", len(keys) == 37, len(keys))
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

# --- Filter Status DO
fdo = next((x for x in spec.filters if x.key == "do_status"), None)
check("filter Status DO ada & berlabel 'Status DO'", fdo is not None and fdo.label == "Status DO",
      fdo.label if fdo else "tidak ada")

# --- Status dokumen PO (Draft / Approval 1 / Approval 2 / Disetujui / Ditutup)
f = RP._flat(row(_po_statuses=["Disetujui"]))
check("status PO tunggal", f["po_status"] == "Disetujui", f["po_status"])

f = RP._flat(row(_po_statuses=["Ditutup", "Menunggu Approval 1"]))
check("beberapa PO digabung berurutan", f["po_status"] == "Menunggu Approval 1, Ditutup", f["po_status"])

f = RP._flat(row())
check("status PO '-' bila tidak ada PO", f["po_status"] == "-" and f["po_status_list"] == [],
      f"{f['po_status']} / {f['po_status_list']}")

check("kolom Status PO tepat setelah No. PO", keys[keys.index("po_no") + 1] == "po_status",
      " -> ".join(keys[keys.index("po_no"):keys.index("po_no") + 2]))
check("label kolom Status PO", labels["po_status"] == "Status PO", labels["po_status"])
check("Status PO tidak dijumlahkan di baris TOTAL",
      not next(c for c in spec.columns if c.key == "po_status").total)

fps = next((x for x in spec.filters if x.key == "po_status"), None)
check("filter Status PO ada & berlabel 'Status PO'", fps is not None and fps.label == "Status PO",
      fps.label if fps else "tidak ada")
_po_vals = [v for v, _ in fps.options] if fps else []
check("opsi filter Status PO memuat Draft / Approval 1 / Approval 2 / Disetujui / Ditutup",
      {"Draft", "Menunggu Approval 1", "Menunggu Approval 2", "Disetujui", "Ditutup"} <= set(_po_vals), _po_vals)
check("opsi filter Status DO lengkap (4 nilai)",
      fdo is not None and [v for v, _ in fdo.options] == ["Diterima", "Diterima Sebagian", "Belum Diterima", "-"],
      [v for v, _ in fdo.options] if fdo else None)
check("label '-' pada filter Status DO = Tanpa PO",
      fdo is not None and dict(fdo.options).get("-") == "Tanpa PO", dict(fdo.options) if fdo else None)

# --- Builder menyaring berdasarkan kedua status (RTD._build_rows di-monkeypatch, tanpa DB)
import asyncio  # noqa: E402

RAW = [
    row(qty_po=10.0, qty_received=10.0, status="Completed", qty_mi=10.0, outstanding=0.0, po_gross=1000.0),
    row(qty_po=10.0, qty_received=4.0, status="Partial", qty_mi=4.0, outstanding=6.0, po_gross=1000.0),
    row(qty_po=10.0, qty_received=0.0, status="Open", qty_mi=0.0, outstanding=10.0, po_gross=1000.0),
    row(qty_po=0.0, qty_received=0.0, status="Open", qty_mi=0.0, outstanding=10.0),
]
_orig = RP.RTD._build_rows


async def _fake_build_rows(server, date_from, date_to, user):
    return [dict(x) for x in RAW]


RP.RTD._build_rows = _fake_build_rows

try:
    async def run_filters():
        out = {}
        for params in ({}, {"do_status": "Diterima"}, {"do_status": "Diterima Sebagian"},
                       {"do_status": "Belum Diterima"}, {"do_status": "-"},
                       {"status": "Open"}, {"status": "Completed"}, {"status": "Open", "do_status": "-"}):
            out[json_key(params)] = await RP.mro_traceability(None, None, dict(params))
        return out

    def json_key(params):
        return ",".join(f"{k}={v}" for k, v in sorted(params.items())) or "semua"

    got = asyncio.run(run_filters())
finally:
    RP.RTD._build_rows = _orig

check("tanpa filter: 4 baris", len(got["semua"]) == 4, len(got["semua"]))
check("filter Status DO=Diterima -> 1 baris",
      len(got["do_status=Diterima"]) == 1 and got["do_status=Diterima"][0]["do_status"] == "Diterima")
check("filter Status DO=Diterima Sebagian -> 1 baris",
      len(got["do_status=Diterima Sebagian"]) == 1, len(got["do_status=Diterima Sebagian"]))
check("filter Status DO=Belum Diterima -> 1 baris",
      len(got["do_status=Belum Diterima"]) == 1, len(got["do_status=Belum Diterima"]))
check("filter Status DO='-' (Tanpa PO) -> 1 baris",
      len(got["do_status=-"]) == 1 and got["do_status=-"][0]["qty_po"] == 0.0, len(got["do_status=-"]))
check("filter Status MI=Open -> 2 baris", len(got["status=Open"]) == 2, len(got["status=Open"]))
check("filter Status MI=Completed -> 1 baris", len(got["status=Completed"]) == 1)
check("kombinasi Status MI=Open + Status DO='-' -> 1 baris",
      len(got["do_status=-,status=Open"]) == 1, len(got["do_status=-,status=Open"]))

# --- Filter Status PO (peta status di-monkeypatch: builder tetap tanpa DB)
RAW_PO = [
    row(po_refs=[{"id": "p1", "no": "PO/1", "date": "2026-11-01"}], qty_po=1.0),
    row(po_refs=[{"id": "p2", "no": "PO/2", "date": "2026-11-01"}], qty_po=1.0),
    row(po_refs=[{"id": "p1", "no": "PO/1", "date": "2026-11-01"},
                 {"id": "p3", "no": "PO/3", "date": "2026-11-01"}], qty_po=3.0),
]
PO_MAP = {"p1": "Draft", "p2": "Menunggu Approval 1", "p3": "Disetujui"}


async def _fake_po_rows(server, date_from, date_to, user):
    return [dict(x) for x in RAW_PO]


async def _fake_status_map(server, rows):
    return dict(PO_MAP)


_orig_map = RP._po_status_map
RP.RTD._build_rows = _fake_po_rows
RP._po_status_map = _fake_status_map
try:
    async def run_po_filters():
        return {json_key(pp): await RP.mro_traceability(None, None, dict(pp))
                for pp in ({}, {"po_status": "Draft"}, {"po_status": "Disetujui"},
                           {"po_status": "Menunggu Approval 1"}, {"po_status": "Ditutup"})}

    po_got = asyncio.run(run_po_filters())
finally:
    RP.RTD._build_rows = _orig
    RP._po_status_map = _orig_map

check("tanpa filter Status PO: 3 baris", len(po_got["semua"]) == 3, len(po_got["semua"]))
check("filter Status PO=Draft -> 2 baris (termasuk baris multi-PO)",
      len(po_got["po_status=Draft"]) == 2, len(po_got["po_status=Draft"]))
check("filter Status PO=Disetujui -> 1 baris",
      len(po_got["po_status=Disetujui"]) == 1, len(po_got["po_status=Disetujui"]))
check("filter Status PO=Menunggu Approval 1 -> 1 baris",
      len(po_got["po_status=Menunggu Approval 1"]) == 1)
check("filter Status PO=Ditutup -> 0 baris", len(po_got["po_status=Ditutup"]) == 0)
_multi = next(r for r in po_got["semua"] if r["qty_po"] == 3.0)
check("baris dengan 2 PO menampilkan keduanya", _multi["po_status"] == "Draft, Disetujui", _multi["po_status"])

# --- Dasar tanggal = TANGGAL PO (opsi A): baris masuk bila minimal satu PO-nya di periode
check("judul laporan 'PO Traceability'", spec.title == "PO Traceability", spec.title)
check("date_basis menyebut Tanggal PO", "Tanggal PO" in spec.date_basis, spec.date_basis)

RAW_PERIOD = [
    row(po_refs=[{"no": "PO/1", "date": "2026-11-05"}], qty_po=5.0, qty_received=5.0),
    row(po_refs=[{"no": "PO/2", "date": "2026-10-20"}], qty_po=5.0),
    row(po_refs=[{"no": "PO/3", "date": "2026-10-28"}, {"no": "PO/4", "date": "2026-11-10"}], qty_po=5.0),
    row(po_refs=[], qty_po=0.0),
]
_calls = []


async def _fake_period(server, date_from, date_to, user):
    _calls.append((date_from, date_to))
    return [dict(x) for x in RAW_PERIOD]


RP.RTD._build_rows = _fake_period
try:
    async def run_period():
        out = {}
        for params in ({}, {"date_from": "2026-11-01", "date_to": "2026-11-30"},
                       {"date_from": "2026-10-01", "date_to": "2026-10-31"},
                       {"date_from": "2026-12-01", "date_to": "2026-12-31"},
                       {"date_from": "2026-11-01", "date_to": "2026-11-30", "do_status": "Diterima"}):
            out[json_key(params)] = await RP.mro_traceability(None, None, dict(params))
        return out

    period = asyncio.run(run_period())
finally:
    RP.RTD._build_rows = _orig

check("rantai dibangun tanpa batas tanggal MRO (None, None)",
      _calls[0] == (None, None), str(_calls[0]))
check("periode kosong = 'Semua data' (barang tanpa PO tetap tampil)", len(period["semua"]) == 4,
      len(period["semua"]))
check("periode Nov: hanya baris yang punya PO di Nov (2 baris)",
      len(period["date_from=2026-11-01,date_to=2026-11-30"]) == 2,
      [x["po_no"] for x in period["date_from=2026-11-01,date_to=2026-11-30"]])
check("PO di luar periode tidak ikut (Des -> 0 baris)",
      len(period["date_from=2026-12-01,date_to=2026-12-31"]) == 0,
      len(period["date_from=2026-12-01,date_to=2026-12-31"]))
check("satu baris dengan 2 PO: masuk bila salah satu PO di periode (Okt: 2 baris)",
      len(period["date_from=2026-10-01,date_to=2026-10-31"]) == 2,
      [x["po_no"] for x in period["date_from=2026-10-01,date_to=2026-10-31"]])
check("barang tanpa PO tidak muncul saat periode diisi",
      all(x["po_no"] for x in period["date_from=2026-11-01,date_to=2026-11-30"]),
      [x["po_no"] for x in period["date_from=2026-11-01,date_to=2026-11-30"]])
check("periode PO + Status DO bisa dikombinasikan (1 baris)",
      len(period["date_from=2026-11-01,date_to=2026-11-30,do_status=Diterima"]) == 1,
      len(period["date_from=2026-11-01,date_to=2026-11-30,do_status=Diterima"]))

print(f"\n{'SEMUA PASS' if not fail else str(len(fail)) + ' GAGAL -> ' + str(fail)}  ({len(keys)} kolom)")
sys.exit(1 if fail else 0)
