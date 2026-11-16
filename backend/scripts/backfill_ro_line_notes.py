"""Backfill sekali jalan (2026-11-16): isi `ro_lines.notes` dari keterangan baris MRO sumber.

Latar: sebelum perbaikan PR #175, "Tarik MRO" membuang keterangan baris MRO sehingga semua baris RO
tersimpan dengan notes kosong. Skrip ini mengisi baris RO yang notes-nya masih kosong dengan
keterangan MRO sumbernya (unik, urut tanggal MRO, digabung " | ") — sama dengan aturan frontend.

Aman:
- Dry-run bawaan (tidak menulis). Tulis hanya dengan `--apply`.
- Backup seluruh baris terdampak (termasuk doc lengkap) ditulis SEBELUM update.
- Hanya menyentuh `doc.notes`; `updated_at` dipertahankan (tidak ikut berubah).
- Baris RO yang notes-nya sudah terisi tidak pernah ditimpa.

Jalankan dari folder `backend`:
    python scripts/backfill_ro_line_notes.py            # dry-run
    python scripts/backfill_ro_line_notes.py --apply    # menulis
"""
import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE.parent / ".tmp-verify" / "backup_ro_notes_2026-11-16"


def db_config():
    env = {}
    for line in (BASE / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    body = env["DATABASE_URL"][len("mysql://"):]
    creds, rest = body.split("@", 1)
    user, password = creds.split(":", 1)
    hostport, dbname = rest.split("/", 1)
    host, port = hostport.split(":")
    return dict(host=host, port=int(port), user=user, password=password, database=dbname,
                connect_timeout=20, read_timeout=900, charset="utf8mb4")


def load_json(cursor, table):
    cursor.execute(f"SELECT pk, doc FROM {table}")
    out = {}
    for pk, doc in cursor.fetchall():
        try:
            d = json.loads(doc)
        except Exception:
            continue
        out[d.get("id")] = d
    return out


def join_notes(values):
    """Keterangan unik (urutan tetap), digabung ' | ' — sama dengan notesOf() di frontend."""
    seen, out = set(), []
    for v in values:
        s = str(v or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return " | ".join(out)


async def main(apply):
    print("MODE:", "APPLY (menulis ke DB)" if apply else "DRY-RUN (hanya membaca)")
    conn = pymysql.connect(**db_config())
    try:
        with conn.cursor() as cur:
            ro_lines = load_json(cur, "ro_lines")
            mro_lines = load_json(cur, "mro_lines")
            mro_heads = load_json(cur, "mro")
            cur.execute("SELECT doc FROM allocations WHERE target_type='ro' AND source_type='mro'")
            allocs = []
            for (doc,) in cur.fetchall():
                a = json.loads(doc)
                allocs.append((a.get("target_line_id"), a.get("source_line_id")))

        by_ro_line = defaultdict(list)
        for target, source in allocs:
            if target and source:
                by_ro_line[target].append(source)

        def sort_key(line_id):
            ml = mro_lines.get(line_id) or {}
            head = mro_heads.get(ml.get("mro_id")) or {}
            return (str(head.get("date") or ""), str(head.get("no") or ""), str(line_id))

        candidates, skipped_filled, no_notes = [], 0, 0
        for lid, rl in ro_lines.items():
            if str(rl.get("notes") or "").strip():
                skipped_filled += 1
                continue
            srcs = sorted(by_ro_line.get(lid, []), key=sort_key)
            vals = [((mro_lines.get(s) or {}).get("notes")) for s in srcs]
            new = join_notes(vals)
            if not new:
                no_notes += 1
                continue
            candidates.append({
                "id": rl.get("id"), "ro_id": rl.get("ro_id"), "item_id": rl.get("item_id"),
                "tenant_id": rl.get("tenant_id"),
                "old_notes": rl.get("notes") or "", "new_notes": new,
                "sources": srcs, "doc": rl,
            })

        print(f"ro_lines total          : {len(ro_lines)}")
        print(f"  sudah ada keterangan  : {skipped_filled}")
        print(f"  sumber MRO tanpa note : {no_notes}")
        print(f"  AKAN DIISI            : {len(candidates)}")

        if candidates:
            print("\ncontoh 8 baris:")
            for c in candidates[:8]:
                print(f"  RO {c['ro_id'][:8]}... | item {str(c['item_id'])[:8]}... | {c['new_notes'][:70]!r}")

        if not apply or not candidates:
            if not apply:
                print("\nDRY-RUN selesai — tidak ada perubahan. Jalankan dengan --apply untuk menerapkan.")
            return

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / "ro_line_notes_before.json"
        backup.write_text(json.dumps({
            "created_at": "2026-11-16",
            "purpose": "backup sebelum backfill ro_lines.notes dari keterangan MRO",
            "count": len(candidates),
            "rows": candidates,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nbackup ditulis: {backup} ({len(candidates)} baris)")

        done = 0
        with conn.cursor() as cur:
            for c in candidates:
                # updated_at = updated_at -> kolom auto-update tidak ikut berubah.
                # `pk` bukan gabungan tenant:id, jadi pakai id + tenant_id (NULL-safe <=>).
                cur.execute(
                    "UPDATE ro_lines SET doc = JSON_SET(doc, '$.notes', %s), updated_at = updated_at "
                    "WHERE id = %s AND tenant_id <=> %s AND (notes IS NULL OR notes = '')",
                    (c["new_notes"], c["id"], c["tenant_id"]),
                )
                done += cur.rowcount
        conn.commit()
        print(f"UPDATE selesai: {done} baris terisi")

        with conn.cursor() as cur:
            cur.execute("""SELECT SUM(CASE WHEN notes IS NULL OR notes='' THEN 1 ELSE 0 END),
                                  SUM(CASE WHEN notes IS NOT NULL AND notes!='' THEN 1 ELSE 0 END)
                           FROM ro_lines""")
            kosong, terisi = cur.fetchone()
            print(f"verifikasi ro_lines.notes: kosong={kosong} terisi={terisi}")
            cur.execute("""SELECT pk, ro_id, notes FROM ro_lines WHERE notes IS NOT NULL AND notes!='' LIMIT 5""")
            for pk, ro_id, notes in cur.fetchall():
                print(f"  {str(ro_id)[:8]}... | {notes[:70]!r}")
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="tulis perubahan ke database")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
