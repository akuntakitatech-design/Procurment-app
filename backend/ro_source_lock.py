"""Kunci lintas-proses untuk sisa baris sumber saat RO (sumber MRO) / PO (sumber RO) disimpan.

Masalah: hitung-sisa -> tulis-allocation adalah read-modify-write. asyncio.Lock hanya berlaku di
satu proses; bila backend berjalan multi-worker / multi-pod, dua request dapat membaca sisa yang
sama lalu sama-sama menulis allocation (over-allocation).

Mekanisme (MariaDB/MySQL): named lock server-side `GET_LOCK()` per baris MRO sumber.
- Nama kunci per baris MRO (`pfro:<mro_line_id>`), sehingga hanya record relevan yang
  diserialisasi; RO dari MRO berbeda tetap paralel penuh.
- Kunci diambil dalam urutan terurut (sorted) -> semua proses memakai urutan global yang sama,
  sehingga tidak ada siklus tunggu (deadlock). MariaDB juga mendeteksi deadlock user-lock.
- Kunci ditahan pada koneksi KHUSUS dari pool terpisah (bukan pool data) agar request yang
  sedang menunggu tidak menghabiskan koneksi pool data milik pemegang kunci.
- Tanpa row lock pada tabel data -> tidak ada lock-wait/deadlock dengan query data lain.
- Timeout -> HTTP 409 (aman untuk diulang); kunci selalu dilepas (RELEASE_ALL_LOCKS) dan
  otomatis dilepas server bila koneksi/proses mati.
Sisa MRO dihitung ulang (validate) SETELAH semua kunci didapat dan allocation ditulis sebelum
kunci dilepas -> critical section lintas proses.
Fallback (DB bukan MariaDB, mis. Mongo dev): asyncio.Lock per proses.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

log = logging.getLogger("procureflow")

LOCK_TIMEOUT_S = 15
LOCK_PREFIX = "pfro:"
_FALLBACK = asyncio.Lock()
_pools = {}
_pool_guard = asyncio.Lock()


def lock_names(line_ids, prefix=LOCK_PREFIX):
    return sorted({f"{prefix}{x}" for x in line_ids if x})


def _dsn_of(server):
    """DSN MariaDB di balik (berlapis) TenantDatabaseProxy -> MariaDatabase._dsn."""
    obj = getattr(server, "raw_db", None) or getattr(server, "db", None)
    for _ in range(8):
        if obj is None:
            break
        try:
            dsn = object.__getattribute__(obj, "_dsn")
            return dsn if isinstance(dsn, str) and dsn.startswith(("mysql", "mariadb")) else None
        except AttributeError:
            pass
        try:
            obj = object.__getattribute__(obj, "_raw")
        except AttributeError:
            break
    return None


async def _lock_pool(dsn):
    pool = _pools.get(dsn)
    if pool is None:
        async with _pool_guard:
            pool = _pools.get(dsn)
            if pool is None:
                import aiomysql
                u = urlparse(dsn.replace("mariadb://", "mysql://"))
                pool = await aiomysql.create_pool(
                    host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""),
                    password=unquote(u.password or ""), db=unquote(u.path.lstrip("/")),
                    charset="utf8mb4", autocommit=True, minsize=0, maxsize=32, pool_recycle=3600)
                _pools[dsn] = pool
    return pool


@asynccontextmanager
async def db_named_locks(dsn, names, timeout=LOCK_TIMEOUT_S):
    """Ambil seluruh named lock (urut) pada satu koneksi khusus; lepas semua saat keluar."""
    if not names:
        yield
        return
    pool = await _lock_pool(dsn)
    conn = await pool.acquire()
    try:
        async with conn.cursor() as cur:
            for name in names:
                await cur.execute("SELECT GET_LOCK(%s, %s)", (name, timeout))
                got = (await cur.fetchone() or [None])[0]
                if got != 1:
                    raise HTTPException(409, "Sisa sumber (MRO/RO) sedang diproses transaksi lain. Silakan coba simpan lagi.")
        yield
    finally:
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT RELEASE_ALL_LOCKS()")
            pool.release(conn)
        except Exception as exc:  # koneksi rusak -> tutup; server melepas kunci otomatis
            log.warning(f"RO source lock release: {exc}")
            conn.close()
            pool.release(conn)


@asynccontextmanager
async def mro_line_locks(server, line_ids):
    async with source_line_locks(server, line_ids, LOCK_PREFIX):
        yield


@asynccontextmanager
async def source_line_locks(server, line_ids, prefix):
    """Kunci generik per baris sumber (RO: prefix 'pfro:' baris MRO; PO: 'pfpo:' baris RO)."""
    dsn = _dsn_of(server)
    names = lock_names(line_ids, prefix)
    if dsn:
        async with db_named_locks(dsn, names):
            yield
    else:
        if names:
            log.warning("RO source lock: DB bukan MariaDB -> fallback asyncio.Lock (hanya aman 1 proses)")
        async with _FALLBACK:
            yield
