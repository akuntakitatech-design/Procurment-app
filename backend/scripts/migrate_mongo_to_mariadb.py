#!/usr/bin/env python3
"""
Migrasi data ProcureFlow: MongoDB (dump produksi) -> MariaDB.

Sumber bisa berupa:
  - MongoDB yang sedang berjalan (--mongo mongodb://... --db procurement), atau
  - file dump `mongodb.archive.gz` (--archive path) yang akan di-restore dulu ke
    mongod lokal (butuh `mongorestore`).

Target: MariaDB (DATABASE_URL). Skema diterapkan lewat mariadb_motor (idempoten).
Setiap dokumen disimpan apa adanya (tanpa `_id`) ke tabel bernama sama dengan koleksi.
Idempoten: dijalankan ulang akan meng-upsert berdasarkan pk (doc.id; untuk koleksi
tanpa `id` seperti item_warehouse dipakai pk deterministik dari item_id+warehouse_id).

Opsi:
  --truncate   : kosongkan tabel target sebelum isi (cut-over bersih)
  --only a,b   : hanya koleksi tertentu
  --report out : simpan laporan JSON (count Mongo vs MariaDB per koleksi)

Contoh:
  DATABASE_URL=mysql://... python scripts/migrate_mongo_to_mariadb.py --mongo mongodb://localhost:27017 --db proc_inspect --truncate --report /tmp/migrasi.json
"""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import mariadb_motor as M  # noqa: E402


def deterministic_pk(coll: str, doc: dict, seen: set | None = None) -> str:
    """pk sama dengan aturan runtime shim (M._pick_pk): id, atau tenant_id:id untuk data multi-tenant.
    Bila masih bentrok dalam satu koleksi (Mongo mengizinkan id ganda), pakai UUID."""
    if isinstance(doc.get("id"), str) and doc["id"]:
        pk = M._pick_pk(doc)
    elif coll == "item_warehouse" and doc.get("item_id") and doc.get("warehouse_id"):
        pk = "iw-" + hashlib.sha1(f"{doc['item_id']}|{doc['warehouse_id']}".encode()).hexdigest()[:40]
    else:
        pk = str(uuid.uuid4())
    if seen is not None:
        if pk in seen:
            pk = str(uuid.uuid4())
        seen.add(pk)
    return pk


def parse_dt(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    return M._parse_dt(value)


def to_jsonable(value):
    """Konversi tipe BSON yang mungkin muncul ke tipe JSON."""
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if type(value).__name__ in ("ObjectId", "Decimal128", "Int64"):
        return str(value) if type(value).__name__ != "Int64" else int(value)
    return value


async def migrate(args):
    from pymongo import MongoClient

    if args.archive:
        print(f"[restore] {args.archive} -> {args.mongo}/{args.db}")
        cmd = ["mongorestore", "--quiet", f"--uri={args.mongo}", "--archive=" + args.archive, "--gzip", "--drop",
               f"--nsFrom={args.archive_db}.*", f"--nsTo={args.db}.*"]
        subprocess.run(cmd, check=True)

    mongo = MongoClient(args.mongo)[args.db]
    db = M.database_from_env()
    await db._get_pool()   # terapkan skema

    only = set(args.only.split(",")) if args.only else None
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "collections": {}}
    collections = sorted(mongo.list_collection_names())
    for coll in collections:
        if only and coll not in only:
            continue
        if not M._IDENT.match(coll):
            print(f"[skip] nama koleksi tidak valid: {coll}"); continue
        await db._ensure_table(coll)
        if args.truncate:
            await db._execute(f"DELETE FROM {M._q(coll)}", [])
        docs = list(mongo[coll].find({}))
        rows_to_insert = []
        seen_pk: set = set()
        for raw in docs:
            doc = to_jsonable(raw)
            pk = deterministic_pk(coll, doc, seen_pk)
            created = parse_dt(doc.get("created_at")) or parse_dt(doc.get("at")) or parse_dt(doc.get("date")) or datetime.utcnow()
            rows_to_insert.append((pk, json.dumps(doc, ensure_ascii=False, default=str), created, datetime.utcnow()))
        # batch insert (multi-row) agar cepat walau latensi jaringan tinggi
        BATCH = int(os.environ.get("MIGRATE_BATCH", "300"))
        pool = await db._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for i in range(0, len(rows_to_insert), BATCH):
                    chunk = rows_to_insert[i:i + BATCH]
                    await cur.executemany(
                        f"INSERT INTO {M._q(coll)} (pk, doc, created_at, updated_at) VALUES (%s, %s, %s, %s) "
                        f"ON DUPLICATE KEY UPDATE doc = VALUES(doc), updated_at = VALUES(updated_at)", chunk)
        rows = await db._fetchall(f"SELECT COUNT(*) FROM {M._q(coll)}", [])
        target_count = int(rows[0][0])
        ok = target_count == len(docs)
        report["collections"][coll] = {"mongo": len(docs), "mariadb": target_count, "ok": ok}
        print(f"  {coll:28s} mongo={len(docs):5d}  mariadb={target_count:5d}  {'OK' if ok else 'MISMATCH'}")

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["all_ok"] = all(c["ok"] for c in report["collections"].values())
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"[report] {args.report}")
    print("SEMUA COCOK" if report["all_ok"] else "ADA MISMATCH")
    await db.close()
    return 0 if report["all_ok"] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo", default=os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    ap.add_argument("--db", default=os.environ.get("MONGO_SOURCE_DB", "procurement"))
    ap.add_argument("--archive", help="path mongodb.archive.gz (opsional, akan di-restore ke --db)")
    ap.add_argument("--archive-db", default="procurement", help="nama db di dalam archive")
    ap.add_argument("--truncate", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--report")
    args = ap.parse_args()
    sys.exit(asyncio.run(migrate(args)))


if __name__ == "__main__":
    main()
