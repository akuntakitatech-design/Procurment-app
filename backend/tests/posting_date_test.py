"""Uji unit perbandingan tanggal posting (tanpa DB, tanpa server).

Fokus: tanggal bisnis dikirim frontend sebagai ISO UTC (tengah malam WIB = 17:00Z hari
sebelumnya), sedangkan transaksi sistem memakai timestamp UTC. Guard "posting mundur"
harus membandingkan tanggal kalender WIB agar transaksi di hari yang sama tidak ditolak.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from posting_date import is_backdated, wib_date  # noqa: E402


def main():
    cases = [
        ("2026-11-02", "2026-11-02"),
        ("2026-11-01T17:00:00.000Z", "2026-11-02"),
        ("2026-11-02T02:30:03.696Z", "2026-11-02"),
        ("2026-11-02T11:46:50.977836+00:00", "2026-11-02"),
        ("2026-11-02T16:59:59Z", "2026-11-02"),
        ("2026-11-02T17:00:00Z", "2026-11-03"),
        ("2026-10-31", "2026-10-31"),
        ("", ""),
        (None, ""),
    ]
    for raw, want in cases:
        got = wib_date(raw)
        assert got == want, f"wib_date({raw!r}) = {got!r}, harusnya {want!r}"

    # Kasus keluhan: DO 02/11 WIB (tersimpan 01/11T17:00Z) vs MI 02/11 WIB (timestamp nyata).
    assert not is_backdated("2026-11-01T17:00:00.000Z", "2026-11-02T02:30:03.696Z"), \
        "tanggal sama (WIB) tidak boleh dianggap mundur"
    # Benar-benar mundur: 01/11 WIB vs 02/11 WIB.
    assert is_backdated("2026-10-31T17:00:00.000Z", "2026-11-02T02:30:03.696Z")
    # Jam berbeda di tanggal yang sama bukan mundur.
    assert not is_backdated("2026-11-02T09:00:00Z", "2026-11-02T11:00:00Z")
    # Tanggal kosong tidak dianggap mundur (posting memakai now_iso()).
    assert not is_backdated(None, "2026-11-02")
    assert not is_backdated("2026-11-02", None)
    print(f"posting_date_test: {len(cases) + 5} assertion OK")


if __name__ == "__main__":
    main()
