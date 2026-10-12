"""P7 — Export besar di background (Pusat Laporan & export daftar transaksi P6).

Alur: POST /api/report-center/{key}/export-jobs?fmt=xlsx&<filter> -> job `queued` (pemilik = user + tenant) -> worker memakai
`run()` + `check_limit()` + exporter YANG SAMA dengan export langsung (isi file identik; batas Excel 100.000 / PDF 5.000 tetap
422, tidak ada pemotongan) -> `done` + file sementara -> GET .../export-jobs/{id}/download (hanya pemilik, belum kedaluwarsa).
Export kecil tetap memakai endpoint langsung yang sudah ada (tidak diubah).

Keamanan: job & file hanya dapat dibaca user pembuat pada tenant yang sama (koleksi ber-tenant + cek user_id); hasil
dibangun dengan izin/cakupan/redaksi harga user pembuat (fungsi `run` yang sama). File disimpan di direktori privat
(0700) dengan nama acak, dihapus saat kedaluwarsa (TTL) / saat job dihapus; pesan error generik (tanpa data/harga).
Konkurensi: maksimal MAX_RUNNING job berjalan bersamaan per proses dan MAX_ACTIVE job aktif per user; pembuatan file
(openpyxl/reportlab) berjalan di thread agar event loop tetap melayani request lain.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse

JOBS = "report_export_jobs"
TTL_S = int(os.environ.get("EXPORT_JOB_TTL_SECONDS") or 3600)
MAX_RUNNING = int(os.environ.get("EXPORT_JOB_MAX_RUNNING") or 2)
MAX_ACTIVE = 3
DIR = Path(os.environ.get("EXPORT_JOB_DIR") or "/tmp/procureflow-export-jobs")
MEDIA = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf"}
PUBLIC = ("id", "key", "fmt", "status", "rows", "filename", "error", "created_at", "started_at", "finished_at", "expires_at", "attempts",
          "data_as_of")
MAX_ATTEMPTS = 3
HEARTBEAT_S = 15
STALE_S = int(os.environ.get("EXPORT_JOB_STALE_SECONDS") or 120)  # job aktif tanpa heartbeat selama ini = proses berhenti
_LAST_CLEAN = [0.0]
_TASKS: dict[str, asyncio.Task] = {}
_SEM: asyncio.Semaphore | None = None


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _public(job):
    return {k: job.get(k) for k in PUBLIC}


def _path(job):
    return DIR / str(job.get("tenant_id") or "_") / f"{job['id']}-{job.get('token')}.{job['fmt']}"


def _cleanup_files(throttle=0):
    """Hapus file job yang lebih tua dari TTL (juga sisa proses sebelumnya / file sementara gagal)."""
    if not DIR.exists() or (throttle and time.time() - _LAST_CLEAN[0] < throttle):
        return
    _LAST_CLEAN[0] = time.time()
    cutoff = time.time() - TTL_S
    for p in DIR.glob("*/*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def install(server, run, check_limit, to_xlsx, to_pdf, wib):
    import mariadb_motor

    app = server.app
    db = lambda: server.db  # proxy tenant aktif
    DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DIR, 0o700)
    _cleanup_files()

    def sem():
        global _SEM
        if _SEM is None:
            _SEM = asyncio.Semaphore(MAX_RUNNING)
        return _SEM

    async def expire_old(user_id):
        now = _iso(_now())
        for j in await db()[JOBS].find({"user_id": user_id, "status": "done", "expires_at": {"$lt": now}}, {"_id": 0}).to_list(500):
            try:
                _path(j).unlink(missing_ok=True)
            except OSError:
                pass
            await db()[JOBS].update_one({"id": j["id"]}, {"$set": {"status": "expired"}})

    def stale(j):
        """Job aktif yang tidak lagi dikerjakan proses mana pun (restart/crash): heartbeat/pembuatan lebih tua dari STALE_S."""
        last = j.get("heartbeat_at") or j.get("started_at") or j.get("created_at") or ""
        return last < _iso(_now() - timedelta(seconds=STALE_S))

    async def own(job_id, user):
        _cleanup_files(throttle=300)
        j = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
        if not j or j.get("user_id") != user.get("id"):
            raise HTTPException(404, "Job export tidak ditemukan.")
        if j.get("status") in ("queued", "running") and job_id not in _TASKS and stale(j):  # proses berhenti (mis. restart server)
            await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "failed", "finished_at": _iso(_now()),
                                                                  "error": "Proses export terhenti. Silakan klik Ulangi."}})
            j = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
        return j

    async def beat(job_id):
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await db()[JOBS].update_one({"id": job_id}, {"$set": {"heartbeat_at": _iso(_now())}})

    async def work(job_id, user, key, fmt, params):
        from reporting import registry as R
        mariadb_motor.REQ_CACHE.set({})  # cache request baru (bukan milik request pembuat)
        mariadb_motor.REQ_READS.set(None)  # tanpa memo baca request pembuat
        mariadb_motor.DB_STATS.set(None)
        hb = asyncio.create_task(beat(job_id))
        tmp = None
        try:
            async with sem():
                started = _iso(_now())
                await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "running", "started_at": started, "heartbeat_at": started,
                                                                      "data_as_of": started}})
                try:
                    res = await run(server, user, key, dict(params))
                    check_limit(res, fmt)
                    buf = await asyncio.to_thread(to_xlsx if fmt == "xlsx" else to_pdf, res)
                except HTTPException as e:  # batas 422 / filter wajib 400 / izin 403 — pesan existing (tanpa data)
                    await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "failed", "finished_at": _iso(_now()),
                                                                          "error": str(e.detail), "error_status": e.status_code}})
                    return
                job = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
                p = _path(job)
                p.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(p.parent, 0o700)
                data = buf.getvalue()
                tmp = p.with_name(p.name + ".part")  # tulis atomik: file final hanya ada bila lengkap
                await asyncio.to_thread(tmp.write_bytes, data)
                os.replace(tmp, p)
                tmp = None
                await server.audit(user, "export", "report", key, doc_no=f"{key}.{fmt}",
                                   after={"format": fmt, "rows": res["total_rows"], "filters": res["filters_applied"],
                                          "price_visible": res["price_visible"], "background": True})
                stamp = datetime.now(wib).strftime("%Y%m%d-%H%M")
                await db()[JOBS].update_one({"id": job_id}, {"$set": {
                    "status": "done", "rows": res["total_rows"], "bytes": len(data), "filename": f"{key}_{stamp}.{fmt}",
                    # file memuat kolom harga (laporan tanpa kolom harga selalu price_visible=True di engine -> bukan harga)
                    "price_visible": bool(res.get("price_visible")) and any(c.price for c in R.REGISTRY[key].columns),
                    "finished_at": _iso(_now()), "expires_at": _iso(_now() + timedelta(seconds=TTL_S))}})
        except Exception:  # pesan generik; detail teknis hanya di log server
            import logging
            logging.getLogger("export_jobs").exception("export job %s gagal", job_id)
            await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "failed", "finished_at": _iso(_now()),
                                                                  "error": "Export gagal diproses. Silakan klik Ulangi."}})
        finally:
            hb.cancel()
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            _TASKS.pop(job_id, None)

    def start(job, user):
        t = asyncio.create_task(work(job["id"], user, job["key"], job["fmt"], job.get("params") or {}))
        _TASKS[job["id"]] = t

    async def create(key: str, request: Request, user=Depends(server.current_user)):
        qp = dict(request.query_params)
        fmt = qp.pop("fmt", "xlsx")
        if fmt not in MEDIA:
            raise HTTPException(404, "Format export tidak dikenal.")
        server.require(user, "export")
        from reporting import registry as R
        if key not in R.REGISTRY:
            raise HTTPException(404, "Laporan tidak ditemukan.")
        await expire_old(user.get("id"))
        _cleanup_files(throttle=300)
        same = await db()[JOBS].find_one({"user_id": user.get("id"), "key": key, "fmt": fmt, "params": qp,
                                          "status": {"$in": ["queued", "running"]}}, {"_id": 0})
        if same and (same["id"] in _TASKS or not stale(same)):  # idempoten: permintaan identik yang masih berjalan -> job yang sama
            return _public(same)
        active = await db()[JOBS].count_documents({"user_id": user.get("id"), "status": {"$in": ["queued", "running"]}})
        if active >= MAX_ACTIVE:
            raise HTTPException(429, f"Masih ada {active} export berjalan. Tunggu hingga selesai.")
        job = {"id": str(uuid.uuid4()), "token": secrets.token_hex(16), "user_id": user.get("id"), "key": key, "fmt": fmt,
               "params": qp, "status": "queued", "attempts": 1, "created_at": _iso(_now()), "rows": None, "error": None}
        await db()[JOBS].insert_one(dict(job))
        job = await db()[JOBS].find_one({"id": job["id"]}, {"_id": 0})
        start(job, user)
        return _public(job)

    async def status(job_id: str, user=Depends(server.current_user)):
        return _public(await own(job_id, user))

    async def retry(job_id: str, user=Depends(server.current_user)):
        server.require(user, "export")
        j = await own(job_id, user)
        if j.get("status") not in ("failed", "expired"):
            raise HTTPException(409, "Hanya export yang gagal/kedaluwarsa yang dapat diulang.")
        if j.get("status") == "failed" and int(j.get("attempts") or 1) >= MAX_ATTEMPTS:
            raise HTTPException(409, f"Batas {MAX_ATTEMPTS} percobaan tercapai. Buat export baru.")
        if j.get("error_status") in (400, 403, 422):  # kegagalan permanen (batas baris / filter / izin) tidak diulang
            raise HTTPException(409, j.get("error") or "Export ini tidak dapat diulang. Ubah filter lalu buat export baru.")
        await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "queued", "error": None, "error_status": None, "rows": None,
                                                              "finished_at": None, "expires_at": None,
                                                              "attempts": int(j.get("attempts") or 1) + 1}})
        j = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
        start(j, user)
        return _public(j)

    async def download(job_id: str, user=Depends(server.current_user)):
        server.require(user, "export")  # izin diperiksa ulang saat unduh
        j = await own(job_id, user)
        if j.get("price_visible") and not server.has_perm(user, "view_purchase_price"):
            raise HTTPException(403, "File export memuat harga, sedangkan akun Anda tidak lagi memiliki izin melihat harga. Buat export baru.")
        if j.get("status") != "done":
            raise HTTPException(409, "File export belum siap." if j.get("status") in ("queued", "running") else "File export tidak tersedia.")
        if (j.get("expires_at") or "") < _iso(_now()) or not _path(j).exists():
            await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "expired"}})
            raise HTTPException(410, "File export sudah kedaluwarsa. Silakan klik Ulangi.")
        return FileResponse(_path(j), media_type=MEDIA[j["fmt"]], filename=j.get("filename"),
                            headers={"X-Report-Rows": str(j.get("rows") or 0), "Cache-Control": "no-store"})

    async def remove(job_id: str, user=Depends(server.current_user)):
        j = await own(job_id, user)
        if j.get("status") in ("queued", "running"):
            raise HTTPException(409, "Export masih berjalan.")
        _path(j).unlink(missing_ok=True)
        await db()[JOBS].delete_one({"id": job_id})
        return {"ok": True}

    app.add_api_route("/api/report-center/export-jobs/{job_id}", status, methods=["GET"], tags=["report-center"])
    app.add_api_route("/api/report-center/export-jobs/{job_id}", remove, methods=["DELETE"], tags=["report-center"])
    app.add_api_route("/api/report-center/export-jobs/{job_id}/download", download, methods=["GET"], tags=["report-center"])
    app.add_api_route("/api/report-center/export-jobs/{job_id}/retry", retry, methods=["POST"], tags=["report-center"])
    app.add_api_route("/api/report-center/{key}/export-jobs", create, methods=["POST"], tags=["report-center"])

