"""Import Excel di background: progres persen, log per baris (berhasil/gagal), dan log Excel yang bisa diunduh.

Alur: POST /api/excel/import-jobs/{dataset} (file) -> job `queued` -> worker memakai **fungsi impor yang sama**
(`excel_import_layer.run_import`, endpoint langsung tidak diubah) dengan `tracker` yang mencatat tiap baris ->
`GET /api/excel/import-jobs/{id}` untuk progres/persentase -> `GET /api/excel/import-jobs/{id}/log.xlsx` untuk log.

Keamanan: job & file log hanya untuk pembuatnya (koleksi ber-tenant lewat proxy `server.db` + cek `user_id`).
File log disimpan di direktori privat (0700), nama acak, dihapus setelah TTL. Pesan error generik (tanpa data sensitif).
Konkurensi: maksimal MAX_ACTIVE job aktif per user agar impor besar tidak saling menumpuk.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

import excel_import_layer as EI

JOBS = "import_jobs"
TTL_S = int(os.environ.get("IMPORT_JOB_TTL_SECONDS") or 7200)
MAX_ACTIVE = int(os.environ.get("IMPORT_JOB_MAX_ACTIVE") or 3)
FLUSH_ROWS = 25
FLUSH_S = 0.8
DIR = Path(os.environ.get("IMPORT_JOB_DIR") or "/tmp/procureflow-import-logs")
PUBLIC = ("id", "dataset", "filename", "status", "total", "processed", "ok", "failed", "skipped", "percent",
          "summary", "error", "errors_preview", "created_at", "started_at", "finished_at", "expires_at", "has_log")
_TASKS: dict[str, asyncio.Task] = {}
_LAST_CLEAN = [0.0]


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _path(job):
    return DIR / f"{job['id']}-{job.get('token')}.xlsx"


def _cleanup_files(throttle=0):
    if not DIR.exists() or (throttle and time.time() - _LAST_CLEAN[0] < throttle):
        return
    _LAST_CLEAN[0] = time.time()
    cutoff = time.time() - TTL_S
    for p in DIR.glob("*.xlsx"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def _public(job):
    out = {k: job.get(k) for k in PUBLIC}
    out["has_log"] = bool(job.get("log_bytes")) and (job.get("status") == "done")
    return out


class Tracker:
    """Pencatat progres + log per baris. Menyimpan log di memori, menulis file Excel saat selesai."""

    def __init__(self, server, job_id, total):
        self.server = server
        self.job_id = job_id
        self.total = max(1, int(total or 0))
        self.processed = 0
        self.ok = 0
        self.failed = 0
        self.skipped = 0
        self.rows: list[dict] = []
        self.buf: list[dict] = []
        self.last = 0.0

    @property
    def percent(self):
        return min(100, int(round(self.processed * 100.0 / self.total)))

    async def row(self, row=None, status="OK", code="", message="", doc_no="", batch=""):
        self.processed += 1
        if status == "OK":
            self.ok += 1
        elif status == "GAGAL":
            self.failed += 1
        else:
            self.skipped += 1
        entry = {"row": row, "batch": batch or "", "status": status, "code": code or "",
                 "doc_no": doc_no or "", "message": message or ""}
        self.rows.append(entry)
        self.buf.append(entry)
        if len(self.buf) >= FLUSH_ROWS or (time.monotonic() - self.last) >= FLUSH_S:
            self.buf.clear()
            await self.flush()
        return entry

    async def flush(self):
        """Update progres ke DB (dipanggil berkala; aman dipanggil walau buffer kosong)."""
        self.last = time.monotonic()
        try:
            await self.server.db[JOBS].update_one({"id": self.job_id}, {"$set": {
                "processed": self.processed, "ok": self.ok, "failed": self.failed, "skipped": self.skipped,
                "percent": self.percent, "heartbeat_at": _iso(_now())}})
        except Exception:  # noqa: BLE001 - progres tidak boleh menggagalkan impor
            logging.getLogger("import_jobs").warning("gagal update progres job %s", self.job_id, exc_info=True)


def _log_bytes(job, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Log Import"
    spec = EI.ALL_DATASETS.get(job.get("dataset")) or {}
    ok = len([r for r in rows if r["status"] == "OK"])
    gagal = len([r for r in rows if r["status"] == "GAGAL"])
    batal = len([r for r in rows if r["status"] not in ("OK", "GAGAL")])
    meta = [
        ("Dataset", spec.get("label") or job.get("dataset")),
        ("File", job.get("filename") or "-"),
        ("Waktu", str(job.get("finished_at") or job.get("created_at") or "")[:19].replace("T", " ")),
        ("Total baris", len(rows)),
        ("Berhasil", ok),
        ("Gagal", gagal),
        ("Tidak diproses", batal),
    ]
    for i, (k, v) in enumerate(meta, start=1):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=v)
    head = 9
    headers = ["No", "Baris Excel", "Batch / Kode", "Status", "Kode", "Dokumen", "Pesan"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=head, column=c, value=h)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center")
    for i, r in enumerate(rows, start=1):
        ws.append([i, r.get("row"), r.get("batch"), r.get("status"), r.get("code"), r.get("doc_no"), r.get("message")])
    widths = [6, 11, 18, 14, 22, 22, 70]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    ws.auto_filter.ref = f"A{head}:G{max(head, head + len(rows))}"
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def install(server):
    app = server.app
    db = lambda: server.db  # proxy tenant aktif (contextvar ikut task background)
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DIR, 0o700)
    except OSError:
        pass
    _cleanup_files()

    async def own(job_id, user):
        _cleanup_files(throttle=300)
        job = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
        if not job or job.get("user_id") != user.get("id"):
            raise HTTPException(404, "Job import tidak ditemukan.")
        return job

    async def work(job_id, dataset, rows, user):
        import mariadb_motor
        mariadb_motor.REQ_CACHE.set({})
        mariadb_motor.REQ_READS.set(None)
        mariadb_motor.DB_STATS.set(None)
        tracker = Tracker(server, job_id, len(rows))
        try:
            started = _iso(_now())
            await db()[JOBS].update_one({"id": job_id}, {"$set": {"status": "running", "started_at": started,
                                                                  "total": len(rows), "heartbeat_at": started}})
            result = await EI.run_import(server, dataset, rows, user, tracker)
            summary = {k: result.get(k) for k in ("imported", "created", "updated") if result.get(k) is not None}
            job = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
            data = _log_bytes({**job, "finished_at": _iso(_now())}, tracker.rows)
            path = _path(job)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            await db()[JOBS].update_one({"id": job_id}, {"$set": {
                "status": "done", "processed": tracker.processed, "ok": tracker.ok, "failed": tracker.failed,
                "skipped": tracker.skipped, "percent": 100, "summary": summary, "success": bool(result.get("ok")),
                "errors_preview": (result.get("errors") or [])[:10], "log_bytes": len(data),
                "finished_at": _iso(_now()), "expires_at": _iso(_now() + timedelta(seconds=TTL_S))}})
        except Exception:  # noqa: BLE001
            logging.getLogger("import_jobs").exception("import job %s gagal", job_id)
            await db()[JOBS].update_one({"id": job_id}, {"$set": {
                "status": "failed", "finished_at": _iso(_now()),
                "error": "Import gagal diproses. Periksa file lalu unggah ulang."}})
        finally:
            _TASKS.pop(job_id, None)

    @app.post("/api/excel/import-jobs/{dataset}", tags=["excel-import"])
    async def create(dataset: str, file: UploadFile = File(...), user=Depends(server.current_user)):
        server.require(user, "create")
        spec = EI.ALL_DATASETS.get(dataset)
        if not spec:
            raise HTTPException(404, "Dataset import tidak dikenal")
        if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(400, "Gunakan file Excel .xlsx")
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(400, "File terlalu besar (maksimal 20 MB)")
        headers, rows = EI._read_rows(data)
        EI._check_headers(headers, spec)
        if not rows:
            raise HTTPException(400, "Tidak ada data pada sheet Data")
        active = await db()[JOBS].count_documents({"user_id": user.get("id"), "status": {"$in": ["queued", "running"]}})
        if active >= MAX_ACTIVE:
            raise HTTPException(429, f"Masih ada {active} impor berjalan. Tunggu hingga selesai.")
        _cleanup_files(throttle=300)
        job = {"id": str(uuid.uuid4()), "token": secrets.token_hex(16), "user_id": user.get("id"), "dataset": dataset,
               "filename": file.filename, "status": "queued", "total": len(rows), "processed": 0, "ok": 0,
               "failed": 0, "skipped": 0, "percent": 0, "created_at": _iso(_now())}
        await db()[JOBS].insert_one(dict(job))
        _TASKS[job["id"]] = asyncio.create_task(work(job["id"], dataset, rows, user))
        saved = await db()[JOBS].find_one({"id": job["id"]}, {"_id": 0})
        return _public(saved)

    @app.get("/api/excel/import-jobs", tags=["excel-import"])
    async def list_jobs(dataset: str = "", limit: int = 10, user=Depends(server.current_user)):
        server.require(user, "view")
        flt = {"user_id": user.get("id")}
        if dataset:
            flt["dataset"] = dataset
        jobs = await db()[JOBS].find(flt, {"_id": 0}).sort("created_at", -1).to_list(max(1, min(50, int(limit or 10))))
        return {"items": [_public(j) for j in jobs]}

    @app.get("/api/excel/import-jobs/{job_id}", tags=["excel-import"])
    async def status(job_id: str, user=Depends(server.current_user)):
        job = await own(job_id, user)
        if job.get("status") in ("queued", "running") and job_id not in _TASKS:
            last = job.get("heartbeat_at") or job.get("started_at") or job.get("created_at") or ""
            if last < _iso(_now() - timedelta(seconds=180)):
                await db()[JOBS].update_one({"id": job_id}, {"$set": {
                    "status": "failed", "finished_at": _iso(_now()),
                    "error": "Proses import terhenti (server restart). Silakan unggah ulang."}})
                job = await db()[JOBS].find_one({"id": job_id}, {"_id": 0})
        return _public(job)

    @app.get("/api/excel/import-jobs/{job_id}/log.xlsx", tags=["excel-import"])
    async def log_xlsx(job_id: str, user=Depends(server.current_user)):
        job = await own(job_id, user)
        if job.get("status") != "done":
            raise HTTPException(409, "Log belum tersedia: import belum selesai.")
        path = _path(job)
        if not path.exists():
            raise HTTPException(410, "Log sudah kedaluwarsa. Jalankan import ulang untuk membuat log baru.")
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(path, media_type=media,
                            filename=f"log_import_{job.get('dataset')}_{stamp}.xlsx")
