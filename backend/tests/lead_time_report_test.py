"""Regresi Laporan Lead Time (GET /api/reports/lead-time) — throwaway tenant, DB uji terisolasi.

Bug lama: tanggal dokumen campuran (tanggal murni / timestamp naive vs timestamp ber-zona) -> TypeError
"can't subtract offset-naive and offset-aware datetimes" -> HTTP 500 untuk semua user. Perbaikan menormalkan semua
tanggal ke WIB (Asia/Jakarta) tanpa mengubah rumus (selisih hari antar tanggal dokumen).

Variasi tanggal ditulis langsung ke dokumen di DB uji (mensimulasikan data lama / impor / klien berbeda).
Pakai: TEST_API_URL=http://127.0.0.1:8013/api TEST_DATABASE_URL=mysql://.../proc_itest python lead_time_report_test.py
"""
import os
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receipt_control_test as T  # noqa: E402

call, API = T.call, T.API
RES = {"pass": 0, "fail": 0}


def check(name, cond, info=""):
    RES["pass" if cond else "fail"] += 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {str(info)[:300]}"))


def dbw(table, doc_id, date_value):
    import pymysql
    from urllib.parse import urlparse, unquote
    url = os.environ["TEST_DATABASE_URL"]
    u = urlparse(url.replace("mariadb://", "mysql://"))
    name = u.path.lstrip("/")
    assert "itest" in name or name.endswith("_test"), f"menolak DB non-uji: {name}"
    c = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""), database=name,
                        client_flag=pymysql.constants.CLIENT.FOUND_ROWS)
    with c.cursor() as cur:
        cur.execute(f"UPDATE `{table}` SET doc = JSON_SET(doc, '$.date', %s) WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.id'))=%s",
                    [date_value, doc_id])
        n = cur.rowcount
    c.commit(); c.close()
    assert n == 1, (table, doc_id, n)


def row_for(mro_no, caller=None):
    sc, rows = (caller or call)("GET", "reports/lead-time")
    row = next((r for r in rows if r.get("mro_no") == mro_no), None) if isinstance(rows, list) else None
    return sc, row, rows


def main():
    M = T.setup()
    po, mro_no, _ro_no = T.make_po(M, "supX", 3)
    sc, do = call("POST", "do", T.do_body(M, po, 3, "supX"), 200)
    check("setup: DO dibuat", sc == 200 and do.get("id"), (sc, do))
    sc, mros = call("GET", "mro")
    mros = mros.get("items", mros) if isinstance(mros, dict) else mros
    mro = next(m for m in mros if m.get("no") == mro_no)
    sc, cur_do = call("GET", f"do/{do['id']}")
    print(f"format tanggal tersimpan via API: MRO={mro.get('date')!r} PO={po.get('date')!r} DO={cur_do.get('date')!r}")

    # 1) data persis seperti dibuat aplikasi (kasus yang dulu 500 bila ada DO ber-zona)
    sc, row, rows = row_for(mro_no)
    check("lead-time 200 dengan data DO dari API", sc == 200 and row is not None, (sc, str(rows)[:200]))

    def scenario(name, mro_d, po_d, do_d, exp):
        dbw("mro", mro["id"], mro_d)
        dbw("po", po["id"], po_d)
        dbw("do", do["id"], do_d)
        sc, row, rows = row_for(mro_no)
        got = {k: (row or {}).get(k) for k in exp}
        check(f"{name}: 200 & {exp}", sc == 200 and got == exp, (sc, got, str(rows)[:200]))

    # 1b) kasus nyata penyebab 500: MRO timestamp ber-zona (default aplikasi) + PO tanggal murni dari form
    dbw("po", po["id"], "2026-10-14")
    sc, row, rows = row_for(mro_no)
    check("MRO ber-zona + PO tanggal murni: 200 & selisih terhitung", sc == 200 and row is not None and row.get("mro_to_po") is not None,
          (sc, row, str(rows)[:200]))

    # 2) semua tanggal murni -> rumus lama (selisih hari) tidak berubah
    scenario("tanggal murni", "2026-06-01", "2026-06-03", "2026-06-05", {"mro_to_po": 2, "po_to_do": 2, "do_to_mi": None, "total": None})
    # 3) DO timestamp UTC 'Z' (20:00Z = 03:00 WIB tgl 6) vs PO tanggal murni (WIB)
    scenario("DO ber-zona UTC Z", "2026-06-01", "2026-06-03", "2026-06-05T20:00:00Z", {"mro_to_po": 2, "po_to_do": 3})
    # 4) DO timestamp +00:00 (2026-06-05T16:30Z = 23:30 WIB tgl 5) -> masih tanggal 5 WIB
    scenario("DO ber-zona +00:00 malam", "2026-06-01", "2026-06-03", "2026-06-05T16:30:00+00:00", {"po_to_do": 2})
    # 5) PO timestamp +07:00, DO tanggal murni
    scenario("PO ber-zona +07:00", "2026-06-01", "2026-06-03T23:30:00+07:00", "2026-06-05", {"mro_to_po": 2, "po_to_do": 1})
    # 6) timestamp naive (dianggap WIB) campur ber-zona
    scenario("naive campur aware", "2026-06-01T08:00:00", "2026-06-03T09:00:00+07:00", "2026-06-05T02:00:00+00:00",
             {"mro_to_po": 2, "po_to_do": 2})
    # 7) tanggal kosong / tidak valid -> tahap itu kosong (None), endpoint tetap 200
    scenario("DO tanggal kosong", "2026-06-01", "2026-06-03", "", {"mro_to_po": 2, "po_to_do": None})
    scenario("DO tanggal tidak valid", "2026-06-01", "2026-06-03", "bukan-tanggal", {"mro_to_po": 2, "po_to_do": None})
    scenario("MRO tanggal kosong", "", "2026-06-03", "2026-06-05", {"mro_to_po": None, "po_to_do": 2})

    # 8) tenant isolation: tenant lain tidak melihat MRO tenant ini
    import requests
    S, u = requests.Session(), uuid.uuid4().hex[:8]
    email = f"ltiso_{u}@example.com"
    r = S.post(f"{API}/saas/register", json={"company_name": f"LTISO {u}", "pic_name": "QA", "email": email, "whatsapp": "+628123456789",
                                            "workspace_slug": f"ltiso-{u}", "plan_code": "starter", "password": "TestPass123!",
                                            "address": "x", "terms_accepted": True})
    S.cookies.clear()
    S.post(f"{API}/auth/login", json={"email": email, "password": "TestPass123!"})
    r = S.get(f"{API}/reports/lead-time")
    check("tenant lain: 200 & tidak memuat MRO tenant ini", r.status_code == 200 and not any(x.get("mro_no") == mro_no for x in r.json()),
          r.status_code)

    n = RES["pass"] + RES["fail"]
    print(f"\n{RES['pass']}/{n} passed")
    return 0 if RES["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
