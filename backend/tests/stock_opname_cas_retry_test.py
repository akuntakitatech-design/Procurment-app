"""Retry konflik lock (1213 deadlock / 1205 lock wait timeout) pada klaim CAS status dokumen Stock Opname.

Membuktikan pada MariaDB NYATA (DB test terisolasi *itest* / *_test, tabel sementara khusus test):
  A. Kebijakan retry: hanya 1213/1205 (pymysql OperationalError); error lain langsung dilempar; maks. 3 percobaan
     termasuk percobaan pertama; percobaan habis -> HTTP 409 (bukan 500).
  B. Deadlock ASLI InnoDB (siklus lock 2 transaksi) -> transaksi korban di-ROLLBACK sebelum retry, retry menang,
     perubahan diterapkan tepat satu kali.
  C. Kegagalan 1213 setelah UPDATE sudah dieksekusi di dalam transaksi -> rollback utuh (data & lock bersih) sebelum retry.
  D. Lock wait timeout ASLI (1205): pulih bila lock dilepas; bila tidak dilepas -> tepat 3 percobaan lalu 409, data utuh.
  E. Klaim CAS bersamaan -> tepat 1 pemenang, sisanya kalah bersih (None), tanpa exception, tanpa penerapan ganda.

Jalankan: lewat scripts/run_regression_itest.sh (TEST_DATABASE_URL = DB test terisolasi). Tidak butuh backend HTTP.
"""
import asyncio
import os
import sys
import threading
import time
import uuid
from urllib.parse import unquote, urlparse

import pymysql
from fastapi import HTTPException
from pymysql.err import IntegrityError, OperationalError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from receipt_control_test import RESULTS, check, test_env

import mariadb_motor as MM
import stock_opname_workflow_layer as W

DSN = test_env().get("DATABASE_URL") or ""
DBN = urlparse(DSN.replace("mariadb://", "mysql://")).path.lstrip("/").split("?")[0]
if not DSN or not ("itest" in DBN or DBN.endswith("_test")):
    print(f"Menolak berjalan: database '{DBN}' bukan database test terisolasi (*itest* / *_test)")
    sys.exit(2)
SUF = uuid.uuid4().hex[:8]
T_MAIN, T_PAD = f"zz_cas_retry_{SUF}", f"zz_cas_pad_{SUF}"


def raw_conn(autocommit=True):
    u = urlparse(DSN.replace("mariadb://", "mysql://"))
    return pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""),
                           password=unquote(u.password or ""), database=DBN, autocommit=autocommit, charset="utf8mb4")


def fetch_doc(pk):
    import json
    with raw_conn() as cx, cx.cursor() as cur:
        cur.execute(f"SELECT doc FROM `{T_MAIN}` WHERE pk=%s", (pk,))
        r = cur.fetchone()
    return json.loads(r[0]) if r else None


def row_lock_free(pk):
    """True bila baris dapat dikunci SEGERA (tidak ada transaksi lain yang masih memegang lock)."""
    cx = raw_conn(autocommit=False)
    try:
        with cx.cursor() as cur:
            cur.execute(f"SELECT pk FROM `{T_MAIN}` WHERE pk=%s FOR UPDATE NOWAIT", (pk,))
            cur.fetchall()
        return True
    except OperationalError:
        return False
    finally:
        cx.rollback(); cx.close()


class Tracker:
    """Merekam urutan rollback/commit transaksi adapter & jeda retry (bukti rollback terjadi SEBELUM retry)."""
    def __init__(self): self.events = []; self.on_sleep = None

    async def sleep(self, d):
        self.events.append("sleep")
        if self.on_sleep:
            self.on_sleep(len([e for e in self.events if e == "sleep"]))
        await asyncio.sleep(d)


TRK = Tracker()
_orig_aexit, _orig_aenter = MM._Tx.__aexit__, MM._Tx.__aenter__
SHORT_WAIT = {"on": False}


async def _aexit(self, exc_type, exc, tb):
    TRK.events.append(("rollback" if exc_type else "commit") + (f":{exc.args[0]}" if exc_type and getattr(exc, "args", None) else ""))
    return await _orig_aexit(self, exc_type, exc, tb)


async def _aenter(self):
    conn = await _orig_aenter(self)
    if SHORT_WAIT["on"]:
        async with conn.cursor() as cur:
            await cur.execute("SET SESSION innodb_lock_wait_timeout = 1")
    return conn


MM._Tx.__aexit__, MM._Tx.__aenter__ = _aexit, _aenter


LOCKING = threading.Event()
_orig_fetchall = MM.MariaDatabase._fetchall


async def _fetchall(self, sql, params, conn=None):
    if conn is not None and T_MAIN in sql and "FOR UPDATE" in sql:
        LOCKING.set()   # adapter mulai SELECT ... FOR UPDATE (akan menunggu lock baris k2 milik transaksi X)
    return await _orig_fetchall(self, sql, params, conn=conn)


MM.MariaDatabase._fetchall = _fetchall


def wait_lock_wait(timeout=10):
    """Tunggu sampai adapter mengeksekusi SELECT ... FOR UPDATE, beri jeda agar ia benar-benar menunggu lock k2
    (tanpa hak PROCESS untuk membaca information_schema.INNODB_TRX)."""
    ok = LOCKING.wait(timeout)
    time.sleep(0.4)
    return ok


async def unit_policy():
    def mk(errs, result="OK"):
        calls = {"n": 0}

        async def op():
            calls["n"] += 1
            if errs:
                raise errs.pop(0)
            return result
        return op, calls

    sleeps = []

    async def sl(d): sleeps.append(round(d, 3))

    op, c = mk([OperationalError(1213, "Deadlock found")])
    r = await W.retry_lock_conflict(op, sleep=sl)
    check("A1. 1213 sekali -> retry -> berhasil (2 percobaan, jeda 1x)", r == "OK" and c["n"] == 2 and sleeps == [0.05], (r, c, sleeps))
    sleeps.clear()
    op, c = mk([OperationalError(1205, "Lock wait timeout"), OperationalError(1205, "Lock wait timeout")])
    r = await W.retry_lock_conflict(op, sleep=sl)
    check("A2. 1205 dua kali -> berhasil pada percobaan ke-3 (jeda bertingkat)", r == "OK" and c["n"] == 3 and sleeps == [0.05, 0.1], (c, sleeps))
    sleeps.clear()
    op, c = mk([OperationalError(1213, "x")] * 10)
    try:
        await W.retry_lock_conflict(op, sleep=sl); got = None
    except HTTPException as e:
        got = e.status_code
    check("A3. 1213 terus-menerus -> maks. 3 percobaan lalu HTTP 409 (bukan 500)", got == 409 and c["n"] == 3 and len(sleeps) == 2, (got, c))
    sleeps.clear()
    op, c = mk([OperationalError(1213, "x")] * 10)
    try:
        await W.retry_lock_conflict(op, attempts=10, sleep=sl)
    except HTTPException:
        pass
    check("A4. Permintaan attempts=10 tetap dibatasi 3 percobaan", c["n"] == 3, c)
    for label, err in (("A5. IntegrityError 1062", IntegrityError(1062, "Duplicate entry")),
                       ("A6. OperationalError 2006 (koneksi)", OperationalError(2006, "server has gone away")),
                       ("A7. ValueError berteks 'Deadlock' (bukan error DB)", ValueError("Deadlock found when trying to get lock")),
                       ("A8. HTTPException 400 (validasi bisnis)", HTTPException(400, "x")),
                       ("A9. OperationalError 1146 (tabel tidak ada)", OperationalError(1146, "doesn't exist"))):
        sleeps.clear()
        op, c = mk([err])
        try:
            await W.retry_lock_conflict(op, sleep=sl); raised = None
        except Exception as e:  # noqa: BLE001
            raised = e
        check(f"{label} -> TIDAK di-retry (1 percobaan, dilempar apa adanya)", raised is err and c["n"] == 1 and not sleeps, (type(raised), c))
    op, c = mk([], result=None)
    r = await W.retry_lock_conflict(op, sleep=sl)
    check("A10. Kalah CAS (None) -> dikembalikan apa adanya tanpa retry", r is None and c["n"] == 1)


async def real_db():
    db = MM.MariaDatabase(DSN, auto_schema=False, pool_size=10, name=DBN)
    main, pad = db[T_MAIN], db[T_PAD]
    try:
        await main.insert_one({"id": "k1", "tag": "other"})
        await asyncio.sleep(0.01)
        await main.insert_one({"id": "k2", "tag": "dl", "status": "Waiting Approval", "n": 0})
        await pad.insert_one({"id": "seed"})
        flt = {"tag": "dl", "status": "Waiting Approval"}   # tidak di-pushdown -> scan penuh FOR UPDATE (k1 lalu k2)
        upd = {"$set": {"status": "Posting"}, "$inc": {"n": 1}}

        def reset():
            with raw_conn() as cx, cx.cursor() as cur:
                cur.execute(f"UPDATE `{T_MAIN}` SET doc=JSON_SET(doc,'$.status','Waiting Approval','$.n',0) WHERE pk='k2'")

        # ---------- B. Deadlock ASLI InnoDB
        reset(); TRK.events.clear(); LOCKING.clear()
        x_err = {}

        def tx_x():
            cx = raw_conn(autocommit=False)
            try:
                with cx.cursor() as cur:
                    for i in range(30):   # transaksi X "lebih berat" -> InnoDB memilih transaksi adapter sebagai korban
                        cur.execute(f"INSERT INTO `{T_PAD}` (pk, doc) VALUES (%s, %s)", (f"p{SUF}{i}", '{"pad":1}'))
                    cur.execute(f"UPDATE `{T_MAIN}` SET doc=JSON_SET(doc,'$.x_touch',1) WHERE pk='k2'")
                    x_err["ready"] = True
                    if not wait_lock_wait():
                        x_err["e"] = "adapter tidak pernah menunggu lock"; return
                    cur.execute(f"SELECT pk FROM `{T_MAIN}` WHERE pk='k1' FOR UPDATE")   # siklus -> deadlock
                    cur.fetchall()
                cx.commit()
            except Exception as e:  # noqa: BLE001
                x_err["e"] = repr(e); cx.rollback()
            finally:
                cx.close()

        th = threading.Thread(target=tx_x); th.start()
        while not x_err.get("ready") and th.is_alive():
            await asyncio.sleep(0.01)
        won = await W.retry_lock_conflict(lambda: main.find_one_and_update(flt, upd), sleep=TRK.sleep)
        await asyncio.to_thread(th.join)
        d = fetch_doc("k2")
        ev = list(TRK.events)
        check("B1. Deadlock ASLI 1213 terjadi pada transaksi adapter lalu di-ROLLBACK sebelum jeda retry",
              ev[:2] == ["rollback:1213", "sleep"], ev)
        check("B2. Retry berikutnya COMMIT & memenangkan klaim CAS", won is not None and ev[-1] == "commit" and ev.count("commit") == 1, ev)
        check("B3. Transaksi lawan tetap utuh (tidak menjadi korban) & perubahannya tersimpan", "e" not in x_err and d.get("x_touch") == 1, x_err)
        check("B4. Perubahan diterapkan TEPAT SATU kali (n=1, status Posting)", d.get("n") == 1 and d.get("status") == "Posting", d)

        # ---------- C. 1213 setelah UPDATE dieksekusi di dalam transaksi -> rollback utuh
        reset(); TRK.events.clear()
        orig_exec = MM.MariaDatabase._execute
        state = {"fired": False, "between": None}

        async def exec_fail_once(self, sql, params, conn=None):
            rc = await orig_exec(self, sql, params, conn=conn)
            if not state["fired"] and conn is not None and sql.lstrip().upper().startswith("UPDATE") and T_MAIN in sql:
                state["fired"] = True
                raise OperationalError(1213, "Deadlock found when trying to get lock; try restarting transaction")
            return rc

        TRK.on_sleep = lambda k: state.__setitem__("between", (fetch_doc("k2"), row_lock_free("k2")))
        MM.MariaDatabase._execute = exec_fail_once
        try:
            won = await W.retry_lock_conflict(lambda: main.find_one_and_update(flt, upd), sleep=TRK.sleep)
        finally:
            MM.MariaDatabase._execute = orig_exec; TRK.on_sleep = None
        bdoc, bfree = state["between"] or ({}, False)
        check("C1. UPDATE sudah dieksekusi lalu 1213 -> ROLLBACK sebelum retry", state["fired"] and TRK.events[:2] == ["rollback:1213", "sleep"], TRK.events)
        check("C2. Di antara percobaan: data kembali utuh (n=0, Waiting Approval) & lock sudah dilepas",
              bdoc.get("n") == 0 and bdoc.get("status") == "Waiting Approval" and bfree, (bdoc, bfree))
        d = fetch_doc("k2")
        check("C3. Retry COMMIT; perubahan tepat satu kali (n=1)", won is not None and d.get("n") == 1 and d.get("status") == "Posting", d)

        # ---------- D. Lock wait timeout ASLI (1205)
        SHORT_WAIT["on"] = True
        try:
            for label, release_after in (("D1", 2), ("D2", None)):
                reset(); TRK.events.clear()
                holder = raw_conn(autocommit=False)
                hc = holder.cursor(); hc.execute(f"SELECT pk FROM `{T_MAIN}` WHERE pk='k2' FOR UPDATE"); hc.fetchall()

                def rel(k, h=holder, ra=release_after):
                    if ra is not None and k == ra:
                        h.rollback()
                TRK.on_sleep = rel
                t0 = time.time()
                try:
                    won = await W.retry_lock_conflict(lambda: main.find_one_and_update(flt, upd), sleep=TRK.sleep); code = 200
                except HTTPException as e:
                    won, code = None, e.status_code
                finally:
                    TRK.on_sleep = None
                    holder.rollback(); holder.close()
                ev = list(TRK.events); d = fetch_doc("k2")
                n_attempts = len([e for e in ev if e.startswith(("rollback", "commit"))])
                if release_after:
                    check("D1. 1205 ASLI x2 (lock dipegang) -> rollback tiap percobaan, lock dilepas -> percobaan ke-3 COMMIT",
                          ev == ["rollback:1205", "sleep", "rollback:1205", "sleep", "commit"] and won is not None and d.get("n") == 1, ev)
                else:
                    check("D2. 1205 ASLI terus-menerus -> tepat 3 percobaan (semua rollback) lalu HTTP 409",
                          code == 409 and n_attempts == 3 and all(e == "rollback:1205" for e in ev if e != "sleep"), (code, ev))
                    check("D3. Retry habis -> data tidak berubah (n=0, Waiting Approval) & tidak ada lock tertinggal",
                          d.get("n") == 0 and d.get("status") == "Waiting Approval" and row_lock_free("k2"), d)
                    check("D4. Durasi retry habis terbatas (< 10 detik)", time.time() - t0 < 10, round(time.time() - t0, 2))
        finally:
            SHORT_WAIT["on"] = False

        # ---------- E. Klaim CAS bersamaan (6 paralel x 5 ronde) -> tepat 1 pemenang
        ok_rounds, detail = 0, []
        for _ in range(5):
            reset(); TRK.events.clear()
            res = await asyncio.gather(*[W.retry_lock_conflict(lambda: main.find_one_and_update(flt, upd)) for _ in range(6)],
                                       return_exceptions=True)
            winners = [r for r in res if r is not None and not isinstance(r, BaseException)]
            errs = [r for r in res if isinstance(r, BaseException)]
            d = fetch_doc("k2")
            if len(winners) == 1 and not errs and d.get("n") == 1:
                ok_rounds += 1
            else:
                detail.append((len(winners), [repr(e)[:80] for e in errs], d.get("n")))
        check("E1. 6 klaim CAS bersamaan x5 ronde -> tepat 1 pemenang, 5 kalah bersih, 0 exception, n=1", ok_rounds == 5, detail)
    finally:
        with raw_conn() as cx, cx.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS `{T_MAIN}`"); cur.execute(f"DROP TABLE IF EXISTS `{T_PAD}`")
        await db.close()


def main():
    asyncio.run(unit_policy())
    asyncio.run(real_db())
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
