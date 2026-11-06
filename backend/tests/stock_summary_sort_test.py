"""Unit test urutan daftar Posisi Stok (tanpa DB / tanpa server).

Menguji `stock_summary._filtered_sorted` + `wh_sort_id`:
    - key teks (code/name), angka (total_stock), status (rank)
    - kolom stok per gudang `sort=wh:<id>`: nilai kosong (barang tanpa catatan stok di gudang itu) selalu di akhir
    - sort tidak valid -> urutan default (terbaru dahulu)
    - gudang di luar cakupan -> `wh_sort_id` None (urutan default, bukan error)

Jalankan: cd backend && python -m pytest tests/stock_summary_sort_test.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stock_summary as SS  # noqa: E402

WH = "wh-gudang-1"


def sample():
    """4 barang: dua punya catatan stok di WH, dua tidak (salah satunya qty 0)."""
    def row(**kw):
        base = {"stock_records": 1, "stock_status": "Normal", "category_label": "Sparepart", "unit_label": "Pcs"}
        base.update(kw)
        return base

    return [
        row(id="i1", code="BRG-003", name="Beta", total_stock=0.0, stock_status="Out of Stock", created_at="2026-01-01"),
        row(id="i2", code="BRG-001", name="alpha", total_stock=12.5, stock_status="Overstock", created_at="2026-01-02"),
        row(id="i3", code="BRG-004", name="Gamma", total_stock=3.0, stock_status="Low Stock", created_at="2026-01-03",
            stock_records=0, category_label=None, unit_label=None),
        row(id="i4", code="BRG-002", name="Delta", total_stock=7.0, stock_status="Normal", created_at="2026-01-04"),
    ]


def run(qp, wh_values=None, rows=None):
    return asyncio.run(SS._filtered_sorted(rows if rows is not None else sample(), qp, wh_values))


def codes(result):
    return [r["code"] for r in result]


def test_text_sort_asc_and_desc():
    assert codes(run({"sort": "name", "dir": "asc"})) == ["BRG-001", "BRG-003", "BRG-002", "BRG-004"]
    assert codes(run({"sort": "name", "dir": "desc"})) == ["BRG-004", "BRG-002", "BRG-003", "BRG-001"]
    assert codes(run({"sort": "code", "dir": "asc"})) == ["BRG-001", "BRG-002", "BRG-003", "BRG-004"]


def test_category_and_unit_empty_values_last():
    # i3 tidak punya kategori/satuan -> selalu di akhir, arah asc maupun desc
    assert codes(run({"sort": "category_label", "dir": "asc"}))[-1] == "BRG-004"
    assert codes(run({"sort": "unit_label", "dir": "desc"}))[-1] == "BRG-004"


def test_numeric_total_stock():
    assert [r["total_stock"] for r in run({"sort": "total_stock", "dir": "asc"})] == [0.0, 3.0, 7.0, 12.5]
    assert [r["total_stock"] for r in run({"sort": "total_stock", "dir": "desc"})] == [12.5, 7.0, 3.0, 0.0]


def test_stock_status_uses_rank():
    assert codes(run({"sort": "stock_status", "dir": "asc"})) == ["BRG-003", "BRG-004", "BRG-002", "BRG-001"]
    assert codes(run({"sort": "stock_status", "dir": "desc"})) == ["BRG-001", "BRG-002", "BRG-004", "BRG-003"]


def test_warehouse_column_sort_keeps_rows_without_record_last():
    values = {"i1": 0.0, "i2": 9.0}  # i3 & i4 tidak punya catatan stok di gudang ini
    asc = codes(run({"sort": f"wh:{WH}", "dir": "asc"}, values))
    desc = codes(run({"sort": f"wh:{WH}", "dir": "desc"}, values))
    assert asc == ["BRG-003", "BRG-001", "BRG-004", "BRG-002"]
    assert desc == ["BRG-001", "BRG-003", "BRG-004", "BRG-002"]
    # barang tanpa catatan stok di gudang itu selalu di akhir, asc maupun desc
    assert asc[-2:] == ["BRG-004", "BRG-002"] and desc[-2:] == ["BRG-004", "BRG-002"]


def test_unknown_sort_falls_back_to_default_newest_first():
    ordered = codes(run({"sort": "zzz-bukan-key"}))
    assert ordered == ["BRG-002", "BRG-004", "BRG-001", "BRG-003"]  # created_at desc, lalu code desc
    assert codes(run({})) == ordered


def test_wh_key_validation():
    assert SS.wh_sort_id(f"wh:{WH}", [WH, "lain"]) == WH
    assert SS.wh_sort_id(f"wh:{WH}", ["lain"]) is None       # gudang di luar cakupan -> diabaikan
    assert SS.wh_sort_id("name", [WH]) is None
    assert SS.wh_sort_id("wh:", [WH]) is None
    assert SS.wh_sort_id(None, [WH]) is None


def test_status_filter_no_stock():
    assert codes(run({"stock_status": "No Stock"})) == ["BRG-004"]
    assert codes(run({"stock_status": "Out of Stock"})) == ["BRG-003"]
