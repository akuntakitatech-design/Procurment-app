"""Unit test normalisasi margin Layout Dokumen (tanpa DB/HTTP). Jalankan: cd /app/backend && python print_layout_margin_test.py"""
import print_layout_layer as P
from fastapi import HTTPException

passed = 0


def check(ok, msg):
    global passed
    if not ok:
        raise AssertionError(msg)
    passed += 1
    print(f"PASS: {msg}")


po = lambda raw: P._normalize_one(raw, "PO", "Purchase Order")  # noqa: E731
sides = lambda d: [d[k] for k in P.MARGIN_SIDES]  # noqa: E731

check(sides(po({})) == [12, 15, 12, 15], "default PO: atas/bawah 12, kiri/kanan 15 (konfigurasi, bukan template)")
check(sides(P._normalize_one({}, "MRO", "Material Request Order")) == [12, 12, 12, 12], "default modul lain: 12 semua sisi")
check(sides(po({"margin_mm": 20})) == [20, 20, 20, 20], "migrasi data lama: margin_mm 20 -> keempat sisi 20")
for v in (10, 15, 20, 25):
    check(sides(po({k: v for k in P.MARGIN_SIDES})) == [v] * 4, f"seragam {v} mm tersimpan")
check(sides(po({"margin_mm": 20, "margin_top_mm": 25, "margin_right_mm": 10, "margin_bottom_mm": 15, "margin_left_mm": 20})) == [25, 10, 15, 20],
      "sisi independen (25/10/15/20) menang atas margin_mm")
check(sides(po({"margin_top_mm": 25})) == [25, 15, 12, 15], "hanya satu sisi dikirim -> sisi lain default (bukan margin_mm)")
check(sides(po({"margin_top_mm": 1, "margin_right_mm": 99, "margin_bottom_mm": "7.5", "margin_left_mm": 30})) == [5, 30, 7.5, 30], "clamp 5..30 & string angka")
try:
    po({"margin_left_mm": "abc"})
    check(False, "nilai tidak valid harus 400")
except HTTPException as e:
    check(e.status_code == 400, "nilai margin tidak valid -> 400")
check(all(isinstance(x, float) for x in sides(po({"margin_top_mm": 1, "margin_right_mm": 99}))), "tipe float konsisten (termasuk hasil clamp)")
print(f"\n{passed} passed")
