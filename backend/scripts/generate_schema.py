#!/usr/bin/env python3
"""
Generate backend/database/schema.sql untuk ProcureFlow di MariaDB.

Sumber:
  1. Koleksi yang dipakai kode (grep `db.<nama>.` di backend/*.py).
  2. Dokumen contoh dari MongoDB (dump produksi yang sudah di-restore) untuk
     menentukan field skalar top-level → kolom generated STORED (readable di
     phpMyAdmin + bisa diindeks & dipakai pushdown filter).

Aturan kolom generated:
  - Hanya field yang SELALU skalar (str/number/bool/null) di semua dokumen. Field
    yang pernah berupa object/array tidak dibuat kolomnya (tetap di JSON `doc`).
  - Field kunci (id, code, no, status, email, *_id, *_no, *_type, entity, action,
    role, is_*, date, at, created_at, updated_at, dsb) → VARCHAR(191) + INDEX.
  - Field skalar lain → TEXT (tanpa indeks), agar nilai panjang tidak error.
Idempoten: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN IF NOT EXISTS.

Pakai:
  python scripts/generate_schema.py --mongo mongodb://localhost:27017 --db proc_inspect \
      --code-dir . --out database/schema.sql
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

KEY_FIELD_RE = re.compile(
    r"^(id|code|no|number|status|email|username|entity|action|role|scope|type|category|module|"
    r"doc_type|doc_no|doc_id|identifier|key|name|date|at|created_at|updated_at|submitted_at|approved_at|"
    r"is_[a-z_]+|[a-z_]+_id|[a-z_]+_no|[a-z_]+_type|[a-z_]+_by|[a-z_]+_at|[a-z_]+_date|[a-z_]+_status)$"
)
MAX_INDEXED = 20          # batas indeks per tabel (InnoDB maks 64)
MAX_GENERATED = 40        # batas kolom generated per tabel

# Kolom default untuk koleksi yang ada di kode tetapi tidak ada contoh dokumennya
DEFAULT_FIELDS = ["id", "code", "no", "status"]
# Nama yang bentrok dengan kolom fisik tabel → tidak dibuat kolom generated (tetap ada di JSON doc)
RESERVED = {"pk", "doc", "created_at", "updated_at"}


def ident_ok(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name)) and len(name) <= 60


def collections_from_code(code_dir: Path) -> set:
    names = set()
    for p in code_dir.glob("*.py"):
        if p.name in ("mariadb_motor.py",):
            continue
        for m in re.finditer(r"\bdb\.([a-z_][a-z0-9_]*)\.(find|find_one|insert|update|delete|count|aggregate|distinct|create_index|find_one_and)", p.read_text(encoding="utf-8")):
            names.add(m.group(1))
    return names


def analyze(mongo_url: str, dbname: str):
    from pymongo import MongoClient
    db = MongoClient(mongo_url)[dbname]
    result = {}
    for coll in db.list_collection_names():
        kinds = defaultdict(set)   # field -> {scalar, complex}
        count = 0
        for doc in db[coll].find({}, {"_id": 0}):
            count += 1
            for k, v in doc.items():
                kinds[k].add("complex" if isinstance(v, (dict, list)) else "scalar")
        result[coll] = (count, kinds)
    return result


def build_table_sql(name: str, fields: list) -> list:
    """fields: list of (field, indexed:bool)."""
    stmts = []
    stmts.append(
        f"CREATE TABLE IF NOT EXISTS `{name}` (\n"
        f"  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',\n"
        f"  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),\n"
        f"  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),\n"
        f"  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),\n"
        f"  KEY idx_{name}_created (created_at, pk)\n"
        f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi {name} (ProcureFlow)'"
    )
    for field, indexed in fields:
        if indexed:
            stmts.append(f"ALTER TABLE `{name}` ADD COLUMN IF NOT EXISTS `{field}` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.{field}'), 191)) STORED")
            stmts.append(f"ALTER TABLE `{name}` ADD INDEX IF NOT EXISTS `idx_{name}_{field}` (`{field}`)")
        else:
            stmts.append(f"ALTER TABLE `{name}` ADD COLUMN IF NOT EXISTS `{field}` TEXT AS (JSON_VALUE(doc, '$.{field}')) STORED")
    return stmts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo", default="mongodb://localhost:27017")
    ap.add_argument("--db", default="proc_inspect")
    ap.add_argument("--code-dir", default=".")
    ap.add_argument("--out", default="database/schema.sql")
    args = ap.parse_args()

    code_dir = Path(args.code_dir)
    code_colls = collections_from_code(code_dir)
    try:
        analyzed = analyze(args.mongo, args.db)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Tidak bisa membaca Mongo ({exc}); memakai kolom default.", file=sys.stderr)
        analyzed = {}

    all_colls = sorted(code_colls | set(analyzed))
    out = [
        "-- =====================================================================",
        "-- ProcureFlow / Procurement — Skema MariaDB (dibuat oleh scripts/generate_schema.py)",
        "-- ---------------------------------------------------------------------",
        "-- Satu tabel per koleksi. Kolom `doc` = dokumen JSON lengkap; kolom lain",
        "-- adalah kolom GENERATED (turunan dari doc) agar mudah dibaca di phpMyAdmin",
        "-- dan bisa diindeks. Jangan mengubah kolom generated secara manual.",
        "-- File ini idempoten (aman dijalankan berulang).",
        "-- =====================================================================",
        "",
    ]
    summary_rows = []
    for coll in all_colls:
        if not ident_ok(coll):
            print(f"[skip] nama koleksi tidak valid: {coll}", file=sys.stderr); continue
        count, kinds = analyzed.get(coll, (0, {}))
        fields = []
        if kinds:
            scalar_fields = [f for f, ks in kinds.items() if ks == {"scalar"} and ident_ok(f) and f != "_id" and f not in RESERVED]
            keyed = [f for f in scalar_fields if KEY_FIELD_RE.match(f)]
            others = [f for f in scalar_fields if f not in keyed]
            # id selalu pertama
            keyed.sort(key=lambda f: (f != "id", f))
            indexed = keyed[:MAX_INDEXED]
            rest = keyed[MAX_INDEXED:] + others
            fields = [(f, True) for f in indexed] + [(f, False) for f in rest][: max(0, MAX_GENERATED - len(indexed))]
            if "id" not in [f for f, _ in fields]:
                fields.insert(0, ("id", True))
        else:
            fields = [(f, True) for f in DEFAULT_FIELDS]
        out.append(f"-- ---- {coll} ({count} dokumen contoh) ----")
        out.extend(s + ";" for s in build_table_sql(coll, fields))
        out.append("")
        summary_rows.append(coll)

    # View ringkasan jumlah baris per tabel
    union = "\nUNION ALL\n".join(f"SELECT '{c}' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `{c}`" for c in summary_rows)
    out.append("-- ---- Ringkasan jumlah data per tabel (untuk phpMyAdmin) ----")
    out.append(f"CREATE OR REPLACE VIEW v_ringkasan_data AS\n{union};")
    out.append("")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"Skema ditulis: {args.out} ({len(summary_rows)} tabel)")


if __name__ == "__main__":
    main()
