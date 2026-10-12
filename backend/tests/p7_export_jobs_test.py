"""P7 — Export besar di background (job) — DB test terisolasi *itest*.

Membuktikan:
- J1 job selesai -> file identik (nilai sel) dengan export langsung untuk filter yang sama; jumlah baris = total daftar;
- J2 keamanan: user lain (tenant sama) & tenant lain tidak dapat melihat status / mengunduh (404); tanpa izin export -> 403;
- J3 batas PDF 5.000 baris tetap berlaku di background: job gagal dengan pesan 422 existing (tanpa file parsial);
- J4 ulangi (retry) job gagal; job selesai tidak dapat di-retry (409); job "terhenti" (proses mati) terdeteksi lalu dapat diulang;
- J5 kedaluwarsa -> 410 + status expired; hapus job menghapus file;
- J6 dua job paralel selesai dengan isi identik; daftar transaksi tetap responsif selama job berjalan;
- J7 idempoten: permintaan identik selagi job berjalan -> job yang sama (tanpa job/file ganda);
- J8 izin diperiksa ulang saat unduh (file berisi harga + akun tanpa izin harga -> 403);
- J9 retry dibatasi: kegagalan permanen (422) & batas percobaan -> 409; file sementara tidak tertinggal.
"""
import io
import os
import re
import sys
import time
import uuid

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
import vendor_invoice_test as V  # noqa: E402
from opening_correction_test import conn, ins  # noqa: E402

call, check, API = T.call, T.check, T.API
u = uuid.uuid4().hex[:5]
STAMP = re.compile(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}")


def cells(content):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    return [[ws.title] + [[STAMP.sub("<t>", str(c)) if isinstance(c, str) else c for c in row] for row in ws.iter_rows(values_only=True)]
            for ws in wb.worksheets]


def wait(fn, jid, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        sc, j = fn("GET", f"report-center/export-jobs/{jid}")
        if sc != 200 or j.get("status") in ("done", "failed", "expired"):
            return sc, j
        time.sleep(0.5)
    return 0, {}


def main():
    if "itest" not in os.environ.get("DATABASE_URL", ""):
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    M = T.setup()
    T.M = V.M = M
    tenant = call("GET", "auth/me")[1].get("tenant_id")
    N = 5010  # > batas PDF 5.000
    cn = conn()
    try:
        for i in range(N):
            day = f"2026-0{1 + i % 9}-{10 + i % 18}"
            mid = f"p7x-{u}-{i}"
            ins(cn, "mro", {"id": mid, "tenant_id": tenant, "no": f"P7X-{u}-{i:05d}", "date": day, "requester": f"Peminta {i % 7}",
                            "division_id": M["div"]["id"], "submitted": True, "status": "Approved", "created_at": f"{day}T01:{i % 60:02d}:00+00:00"})
    finally:
        cn.close()
    qs = "date_from=2026-03-01&date_to=2026-03-31"
    sc, lst = call("GET", f"mro?page=1&page_size=25&{qs}")
    n_mar = lst.get("total")

    # J1 identik dengan export langsung
    r_sync = T.S.get(f"{API}/report-center/txn-mro/export.xlsx?{qs}")
    sc, j = call("POST", f"report-center/txn-mro/export-jobs?fmt=xlsx&{qs}")
    check("J1a buat job export -> 200 queued/running", sc == 200 and j.get("status") in ("queued", "running") and "token" not in j, (sc, j))
    sc, j = wait(call, j.get("id"))
    check("J1b job selesai (done) dengan jumlah baris = total daftar", sc == 200 and j.get("status") == "done" and j.get("rows") == n_mar,
          (sc, j, n_mar))
    r_job = T.S.get(f"{API}/report-center/export-jobs/{j['id']}/download")
    check("J1c download 200 + header X-Report-Rows", r_job.status_code == 200 and r_job.headers.get("x-report-rows") == str(n_mar),
          (r_job.status_code, r_job.headers.get("x-report-rows")))
    check("J1d isi Excel background == export langsung (nilai sel)", r_sync.status_code == 200 and cells(r_sync.content) == cells(r_job.content))
    done_id = j["id"]

    # J2 keamanan
    other = V.mk_user("manager")
    sc1, _ = other("GET", f"report-center/export-jobs/{done_id}")
    r2 = other.S.get(f"{API}/report-center/export-jobs/{done_id}/download")
    check("J2a user lain (tenant sama) tidak bisa melihat status/unduh (404)", sc1 == 404 and r2.status_code == 404, (sc1, r2.status_code))
    t2 = uuid.uuid4().hex[:8]
    s2 = requests.Session()
    res = s2.post(f"{API}/saas/register", json={"company_name": f"X {t2}", "pic_name": "QA", "email": f"x_{t2}@example.com",
                                                 "whatsapp": "+628123456789", "workspace_slug": f"x-{t2}", "plan_code": "starter",
                                                 "password": "TestPass123!", "address": "x", "terms_accepted": True}).json()
    tok = res.get("token") or s2.post(f"{API}/auth/login", json={"email": f"x_{t2}@example.com", "password": "TestPass123!"}).json().get("token")
    s2.headers["Authorization"] = f"Bearer {tok}"
    r3, r4 = s2.get(f"{API}/report-center/export-jobs/{done_id}"), s2.get(f"{API}/report-center/export-jobs/{done_id}/download")
    check("J2b tenant lain tidak bisa melihat status/unduh (404)", r3.status_code == 404 and r4.status_code == 404, (r3.status_code, r4.status_code))
    noexp = V.mk_user("manager", overrides={"export": "deny"})
    sc, body = noexp("POST", f"report-center/txn-mro/export-jobs?fmt=xlsx&{qs}")
    check("J2c tanpa izin export -> 403", sc == 403, (sc, body))

    # J3 batas PDF
    sc, j = call("POST", "report-center/txn-mro/export-jobs?fmt=pdf")
    sc, j = wait(call, j.get("id"))
    check("J3 job PDF > 5.000 baris gagal dengan pesan batas existing (tanpa file)",
          j.get("status") == "failed" and "melebihi batas" in (j.get("error") or "") and "dipotong" in (j.get("error") or ""), j)
    r = T.S.get(f"{API}/report-center/export-jobs/{j['id']}/download")
    check("J3b job gagal tidak dapat diunduh (409)", r.status_code == 409, r.status_code)
    failed_id = j["id"]

    # J4 retry
    sc, body = call("POST", f"report-center/export-jobs/{failed_id}/retry")
    sc2, j = call("GET", f"report-center/export-jobs/{failed_id}")
    check("J4a kegagalan permanen (batas 422) tidak di-retry (409, attempts tetap 1, status failed)",
          sc == 409 and "melebihi batas" in str(body) and j.get("attempts") == 1 and j.get("status") == "failed", (sc, body, j))
    sc, _ = call("POST", f"report-center/export-jobs/{done_id}/retry")
    check("J4b job selesai tidak dapat di-retry (409)", sc == 409, sc)
    cn = conn()
    try:
        ins(cn, "report_export_jobs", {"id": f"stale-{u}", "tenant_id": tenant, "user_id": call("GET", "auth/me")[1].get("id"), "key": "txn-mro",
                                       "fmt": "xlsx", "params": {"date_from": "2026-03-01", "date_to": "2026-03-31"}, "status": "running",
                                       "token": "x" * 32, "attempts": 1, "created_at": "2026-01-01T00:00:00+00:00"})
    finally:
        cn.close()
    sc, j = call("GET", f"report-center/export-jobs/stale-{u}")
    check("J4c job terhenti (proses mati) terdeteksi -> failed + pesan Ulangi", sc == 200 and j.get("status") == "failed" and "Ulangi" in (j.get("error") or ""), j)
    call("POST", f"report-center/export-jobs/stale-{u}/retry")
    sc, j = wait(call, f"stale-{u}")
    check("J4d job terhenti dapat diulang hingga selesai", j.get("status") == "done" and j.get("rows") == n_mar, j)

    # J5 kedaluwarsa & hapus
    cn = conn()
    try:
        with cn.cursor() as cur:
            cur.execute("UPDATE report_export_jobs SET doc = JSON_SET(doc, '$.expires_at', '2000-01-01T00:00:00+00:00') WHERE pk = %s OR id = %s",
                        (f"stale-{u}", f"stale-{u}"))
        cn.commit()
    finally:
        cn.close()
    r = T.S.get(f"{API}/report-center/export-jobs/stale-{u}/download")
    sc, j = call("GET", f"report-center/export-jobs/stale-{u}")
    check("J5a file kedaluwarsa -> 410 + status expired", r.status_code == 410 and j.get("status") == "expired", (r.status_code, j.get("status")))
    sc, _ = call("DELETE", f"report-center/export-jobs/{done_id}")
    sc2, _ = call("GET", f"report-center/export-jobs/{done_id}")
    check("J5b hapus job -> 200 lalu 404", sc == 200 and sc2 == 404, (sc, sc2))

    # J6 paralel + responsif (dua filter berbeda) ; J7 idempoten (permintaan identik -> job sama)
    qs2 = "date_from=2026-04-01&date_to=2026-04-30"
    r_sync2 = T.S.get(f"{API}/report-center/txn-mro/export.xlsx?{qs2}")
    j_a = call("POST", f"report-center/txn-mro/export-jobs?fmt=xlsx&{qs}")[1]
    j_a2 = call("POST", f"report-center/txn-mro/export-jobs?fmt=xlsx&{qs}")[1]
    j_b = call("POST", f"report-center/txn-mro/export-jobs?fmt=xlsx&{qs2}")[1]
    t0 = time.perf_counter()
    sc, _ = call("GET", "mro?page=1&page_size=25")
    ms = (time.perf_counter() - t0) * 1000
    outs = [wait(call, i)[1] for i in (j_a["id"], j_b["id"])]
    bodies = [T.S.get(f"{API}/report-center/export-jobs/{i}/download").content for i in (j_a["id"], j_b["id"])]
    check("J6a dua job paralel selesai, isi identik dengan export langsung masing-masing", all(o.get("status") == "done" for o in outs)
          and cells(bodies[0]) == cells(r_sync.content) and cells(bodies[1]) == cells(r_sync2.content), [o.get("status") for o in outs])
    check("J6b daftar MRO tetap melayani request selama job berjalan", sc == 200, (sc, round(ms)))
    check("J7 permintaan identik selagi berjalan -> job yang sama (idempoten)", j_a.get("id") == j_a2.get("id") != j_b.get("id"),
          (j_a.get("id"), j_a2.get("id")))
    check("J7b status memuat data_as_of (cut-off data saat job mulai)", bool(outs[0].get("data_as_of")), outs[0])

    # J8 izin diperiksa ulang saat unduh
    nop = V.mk_user("manager", overrides={"view_purchase_price": "deny"})
    sc, jn = nop("POST", f"report-center/txn-mro/export-jobs?fmt=xlsx&{qs}")
    sc, jn = wait(nop, jn.get("id"))
    r_ok = nop.S.get(f"{API}/report-center/export-jobs/{jn['id']}/download")
    cn = conn()
    try:
        with cn.cursor() as cur:
            cur.execute("UPDATE report_export_jobs SET doc = JSON_SET(doc, '$.price_visible', true) WHERE id = %s", (jn["id"],))
        cn.commit()
    finally:
        cn.close()
    r_no = nop.S.get(f"{API}/report-center/export-jobs/{jn['id']}/download")
    check("J8 file berharga + akun tanpa izin harga -> 403 saat unduh (file tanpa harga tetap 200)",
          jn.get("status") == "done" and r_ok.status_code == 200 and r_no.status_code == 403, (jn.get("status"), r_ok.status_code, r_no.status_code, r_ok.text[:200], jn))

    # J9 batas percobaan untuk kegagalan sementara
    cn = conn()
    try:
        ins(cn, "report_export_jobs", {"id": f"stale3-{u}", "tenant_id": tenant, "user_id": call("GET", "auth/me")[1].get("id"), "key": "txn-mro",
                                       "fmt": "xlsx", "params": {"date_from": "2026-05-01"}, "status": "running",
                                       "token": "y" * 32, "attempts": 3, "created_at": "2026-01-01T00:00:00+00:00"})
    finally:
        cn.close()
    call("GET", f"report-center/export-jobs/stale3-{u}")
    sc, body = call("POST", f"report-center/export-jobs/stale3-{u}/retry")
    import glob
    parts = glob.glob("/tmp/procureflow-export-jobs/*/*.part") + glob.glob(os.path.join(os.environ.get("EXPORT_JOB_DIR", "/nonexistent"), "*/*.part"))
    check("J9 batas 3 percobaan -> 409; tidak ada file sementara (.part) tertinggal", sc == 409 and "Batas" in str(body) and not parts, (sc, body, parts))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
