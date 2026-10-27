"""Unit test tanpa database: format nomor dokumen (kode project, bulan Romawi, lebar seq).

Jalankan: python numbering_unit_test.py
"""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "mysql://u:p@127.0.0.1:3306/unit_test")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-0123456789abcdef")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server as S  # noqa: E402

PASS = 0
FAIL = 0


def check(ok, msg, info=None):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS: {msg}")
    else:
        FAIL += 1
        print(f"FAIL: {msg} {info if info is not None else ''}")


YM = datetime(2026, 6, 15, tzinfo=timezone.utc)
PO_FMT = "PO/{project}/{seq:3}/{roman_month}/{year}"

# ---------------------------------------------------------------- kode project
check(S.project_number_code({"code": "WUR-MD"}) == "WUR-MD", "Kode project dipakai apa adanya (uppercase)")
check(S.project_number_code({"name": "wur md"}) == "WUR-MD", "Fallback nama project: spasi -> '-'")
check(S.project_number_code({"code": "WUR MD"}) == "WUR-MD", "Spasi pada kode dinormalisasi")
check(S.project_number_code({"name": "PT. ABC / X"}) == "PT-ABC-X", "Karakter selain A-Z/0-9 -> '-' tanpa '-' ganda")
check(S.project_number_code({}) == "", "Project tanpa kode/nama -> string kosong")
check(S.project_number_code(None) == "", "Project None -> string kosong")
check(len(S.project_number_code({"code": "A" * 40})) == 24, "Kode project dibatasi 24 karakter")

# ---------------------------------------------------------------- format nomor
out = S.fill_number_format(PO_FMT, doc_type="PO", ym=YM, seq=193, project_code="WUR-MD")
check(out == "PO/WUR-MD/193/VI/2026", "Format PO + project + bulan Romawi: PO/WUR-MD/193/VI/2026", out)

out = S.fill_number_format(PO_FMT, doc_type="PO", ym=YM, seq=7, project_code="OMSS")
check(out == "PO/OMSS/007/VI/2026", "Seq 3 digit dengan nol di depan: 007", out)

out = S.fill_number_format(PO_FMT, doc_type="PO", ym=YM, seq=193, project_code="")
check(out == "PO/193/VI/2026", "Tanpa project: segmen dihapus, tidak ada '//'", out)

out = S.fill_number_format("{project}/PO/{seq:3}", doc_type="PO", ym=YM, seq=5, project_code="")
check(out == "PO/005", "Project di awal format & kosong: garis miring tidak tertinggal", out)

check(S.fill_number_format("PO/{year}/{month}/{seq}", doc_type="PO", ym=YM, seq=6) == "PO/2026/06/00006",
      "Format lama tetap 5 digit (kompatibel)")
check(S.fill_number_format("PO/{seq}", doc_type="PO", ym=YM, seq=123456) == "PO/123456",
      "Seq melebihi lebar tidak dipotong")
check(S.fill_number_format("{type}/{roman_month}/{year}", doc_type="DO", ym=datetime(2026, 12, 1, tzinfo=timezone.utc), seq=1)
      == "DO/XII/2026", "Bulan Desember -> XII dan {type} terisi")
check(S.fill_number_format("{roman_month}", doc_type="X", ym=datetime(2026, 1, 1, tzinfo=timezone.utc), seq=1) == "I",
      "Bulan Januari -> I")
check(S.fill_number_format("{roman_month}", doc_type="X", ym=datetime(2026, 8, 1, tzinfo=timezone.utc), seq=1) == "VIII",
      "Bulan Agustus -> VIII")
check(len(S.ROMAN_MONTHS) == 12 and S.ROMAN_MONTHS[0] == "I" and S.ROMAN_MONTHS[-1] == "XII",
      "ROMAN_MONTHS berisi 12 bulan (I..XII)")

# ---------------------------------------------------------------- next_number (DB palsu, tanpa koneksi)
import asyncio  # noqa: E402
import re  # noqa: E402


class _Settings:
    def __init__(self, formats):
        self.formats = formats

    async def find_one(self, q, proj=None):
        return {"id": "numbering", "formats": dict(self.formats)}


class _Projects:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    async def find_one(self, q, proj=None):
        self.asked.append(q.get("id"))
        return self.rows.get(q.get("id"))


class _Counters:
    def __init__(self, seq):
        self.seq = seq

    async def find_one_and_update(self, q, upd, upsert=False, return_document=None):
        self.seq += 1
        return {"id": q.get("id"), "seq": self.seq}


class _DB:
    def __init__(self, formats, projects=None, seq=57):
        self.settings = _Settings(formats)
        self.projects = _Projects(projects or {"p1": {"id": "p1", "code": "WUR MD"}})
        self.counters = _Counters(seq)


async def _next(fmt, project_id=None, seq=57):
    fake = _DB({"PO": fmt}, seq=seq)
    old = S.db
    S.db = fake
    try:
        return await S.next_number("PO", project_id=project_id), fake
    finally:
        S.db = old


ym_now = datetime.now(timezone.utc)
roman_now = S.ROMAN_MONTHS[ym_now.month - 1]
out, fake = asyncio.run(_next(PO_FMT, "p1"))
check(out == f"PO/WUR-MD/058/{roman_now}/{ym_now.year}",
      "next_number memakai kode project + seq 3 digit + bulan Romawi", out)
check(fake.projects.asked == ["p1"], "Project diambil sekali dari DB saat format memuat {project}", fake.projects.asked)

out, fake = asyncio.run(_next("PO/{year}/{month}/{seq}"))
check(fake.projects.asked == [], "Format tanpa {project} tidak membaca koleksi projects", fake.projects.asked)
check(out == f"PO/{ym_now.year}/{ym_now.month:02d}/00058", "Format lama tetap 5 digit lewat next_number", out)

out, _ = asyncio.run(_next(PO_FMT, None))
check(out == f"PO/058/{roman_now}/{ym_now.year}", "PO tanpa project: segmen project dilewati (tanpa '//')", out)

# ---------------------------------------------------------------- migrasi format (numbering_upgrade)
up = S.numbering_upgrade({"formats": {"PO": "PO/{year}/{month}/{seq}", "RO": "RO/{year}/{month}/{seq}"}})
check(up and up["formats"]["PO"] == S.PO_FORMAT_V2, "Default lama PO -> dinaikkan ke format v2 (project + Romawi)", up)
check(up and up["formats"]["RO"] == "RO/{year}/{month}/{seq}", "Format dokumen lain tidak diubah")
check(up and up["numbering_version"] == 2, "numbering_version diset 2")

_up = S.numbering_upgrade({"formats": {"PO": "PO/{project}/{seq:3}/{roman_month}/{year}"}})
check(_up and _up["formats"]["PO"] == S.PO_FORMAT_V2 and _up["numbering_version"] == 2,
      "Format sudah v2 tanpa versi: hanya versi dinaikkan (format tetap)", _up)

_up = S.numbering_upgrade({"formats": {"PO": "PO-CUSTOM/{seq}"}})
check(_up and _up["formats"]["PO"] == "PO-CUSTOM/{seq}", "Format custom pengguna TIDAK ditimpa", _up)

check(S.numbering_upgrade({"numbering_version": 2}) is None, "Sudah versi 2 -> tidak ada perubahan (idempoten)")
check(S.numbering_upgrade({})["formats"]["PO"] == S.PO_FORMAT_V2, "Tanpa setting -> PO default v2")
check(S.numbering_upgrade({"numbering_version": "x", "formats": {"PO": "PO/{year}/{month}/{seq}"}})["numbering_version"] == 2,
      "Versi tidak valid dianggap v1")

print(f"\n{PASS}/{PASS + FAIL} passed")
sys.exit(1 if FAIL else 0)
