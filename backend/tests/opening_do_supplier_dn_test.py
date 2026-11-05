"""No. Surat Jalan DO Saldo Awal default = No. DO (murni, tanpa DB/HTTP).

Jalankan dari backend/:  python tests/opening_do_supplier_dn_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from opening_do_layer import resolve_supplier_dn  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


check("kosong -> ikut No. DO", resolve_supplier_dn("007936-26", "") == "007936-26")
check("None -> ikut No. DO", resolve_supplier_dn("PA/DO/26100396", None) == "PA/DO/26100396")
check("spasi saja -> ikut No. DO", resolve_supplier_dn("007936-26", "   ") == "007936-26")
check("diisi manual -> dipakai apa adanya", resolve_supplier_dn("007936-26", "SJ-77") == "SJ-77")
check("nilai manual di-trim", resolve_supplier_dn("007936-26", "  SJ-77 ") == "SJ-77")
check("No. DO bertrim", resolve_supplier_dn(" 007936-26 ", "") == "007936-26")

try:
    resolve_supplier_dn("x" * 65, "")
    check("> 64 karakter ditolak 400", False)
except HTTPException as e:
    check("> 64 karakter ditolak 400", e.status_code == 400 and "64" in str(e.detail), f"{e.status_code} {e.detail}")

passed = sum(1 for r in RESULTS if r)
print(f"\n{passed}/{len(RESULTS)} passed")
sys.exit(0 if passed == len(RESULTS) else 1)
