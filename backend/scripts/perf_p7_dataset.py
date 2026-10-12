"""P7 — pembangun dataset benchmark volume besar (HANYA DB test terisolasi `*_itest`; menolak DB lain).

Langkah (idempoten per langkah, dijalankan berurutan):
  copy   : salin skema + data DB sumber perf (default proc_perf_itest, 20x alur nyata via API) -> DB target (default proc_p7_itest).
           Opsional P7_DATA_DIR = DATA DIRECTORY tabel target (JANGAN /var/tmp: hilang saat pod restart).
  clone K: gandakan dokumen transaksi tenant perf K kali dengan ID baru konsisten (relasi antar dokumen ikut dipetakan),
           nomor dokumen diberi akhiran -Dkk, tanggal digeser mundur. audit_logs/notifications TIDAK digandakan (hanya volume log).
  extra N: tanam SPK, Kontrak Vendor, Invoice Vendor (ditautkan ke DO nyata), dan Pinjaman (+baris) untuk tenant perf.
  counts : cetak jumlah dokumen per koleksi.

Contoh (in-place di proc_perf_itest): python scripts/perf_p7_dataset.py clone 3 && python scripts/perf_p7_dataset.py extra 20000
Koneksi: root lokal 127.0.0.1 (MariaDB sandbox pod). Tidak pernah menyentuh preview/sandbox/production.
"""
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta

import pymysql

sys.path.insert(0, "/app/backend")
from mariadb_motor import _pick_pk  # noqa: E402

SRC = os.environ.get("P7_SRC_DB", "proc_perf_itest")
DST = os.environ.get("P7_DB", "proc_perf_itest")  # default: tumbuh in-place di DB perf (volume durable /root); `copy` hanya bila DST != SRC
DDIR = os.environ.get("P7_DATA_DIR", "")            # kosong = datadir MariaDB (durable). /var/tmp hilang saat pod restart!
LEDGER_CLONES = int(os.environ.get("P7_LEDGER_CLONES", "1"))  # stock/valuation ledger hanya digandakan sekian kali (hemat disk)
LEDGERS = {"stock_ledger", "valuation_ledger"}
for _n in (SRC, DST):
    assert _n.endswith("_itest") and _n not in ("proc_itest",), f"menolak DB {_n}"

COLLS = ["mro", "mro_lines", "ro", "ro_lines", "po", "po_lines", "do", "do_lines", "mi", "mi_lines", "allocations",
         "stock_ledger", "valuation_ledger", "transfers", "transfer_lines", "adjustments", "adjustment_lines", "approval_tasks"]
NO_COLLS = ("mro", "ro", "po", "do", "mi", "transfers", "adjustments")
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})([T ].*)?$")


def cx(db):
    c = pymysql.connect(host="127.0.0.1", user="root", database=db, autocommit=False, charset="utf8mb4")
    cur = c.cursor()
    cur.execute("SELECT DATABASE()")
    assert cur.fetchone()[0] == db
    return c, cur


def step_copy():
    assert DST != SRC, "copy hanya bila P7_DB berbeda dari sumber"
    if DDIR:
        os.makedirs(DDIR, exist_ok=True)
        os.system(f"chown mysql:mysql {DDIR}")
    c, cur = cx(SRC)
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DST}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'", (DST,))
    if cur.fetchall():
        print(f"{DST} sudah berisi tabel — copy dilewati")
        return
    cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'", (SRC,))
    for (t,) in cur.fetchall():
        cur.execute(f"SHOW CREATE TABLE `{SRC}`.`{t}`")
        ddl = cur.fetchone()[1].replace(f"CREATE TABLE `{t}`", f"CREATE TABLE `{DST}`.`{t}`", 1)
        cur.execute(ddl + (f" DATA DIRECTORY='{DDIR}'" if DDIR else ""))
        cur.execute(f"SHOW COLUMNS FROM `{SRC}`.`{t}`")
        cols = [r[0] for r in cur.fetchall() if "GENERATED" not in (r[5] or "").upper()]
        cl = ",".join(f"`{x}`" for x in cols)
        cur.execute(f"INSERT INTO `{DST}`.`{t}` ({cl}) SELECT {cl} FROM `{SRC}`.`{t}`")
        c.commit()
        print("copy", t, flush=True)
    c.close()


def shift(s, days):
    m = DATE.match(s)
    if not m:
        return s
    try:
        d = datetime.strptime(m.group(1), "%Y-%m-%d") - timedelta(days=days)
    except ValueError:
        return s
    return d.strftime("%Y-%m-%d") + (m.group(2) or "")


def step_clone(k_total):
    c, cur = cx(DST)
    cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
    have = {r[0] for r in cur.fetchall()}
    src = {}
    for t in COLLS:
        if t in have:
            cur.execute(f"SELECT doc FROM `{t}` WHERE JSON_VALUE(doc,'$.p7_clone') IS NULL")
            src[t] = [json.loads(r[0]) for r in cur.fetchall()]
    ids = {d["id"] for docs in src.values() for d in docs if isinstance(d.get("id"), str)}
    nos = {d["no"] for t in NO_COLLS for d in src.get(t, []) if d.get("no")}
    print({t: len(v) for t, v in src.items()}, "ids", len(ids), flush=True)

    def walk(v, idm, k, days):
        if isinstance(v, dict):
            return {kk: walk(vv, idm, k, days) for kk, vv in v.items()}
        if isinstance(v, list):
            return [walk(x, idm, k, days) for x in v]
        if isinstance(v, str):
            if v in idm:
                return idm[v]
            if v in nos:
                return f"{v}-D{k:02d}"
            return shift(v, days)
        return v

    for k in range(1, k_total + 1):
        idm = {i: str(uuid.uuid4()) for i in ids}
        days = 200 + k * 31
        for t, docs in src.items():
            if t in LEDGERS and k > LEDGER_CLONES:
                continue
            rows = []
            for d in docs:
                nd = walk(d, idm, k, days)
                nd["p7_clone"] = k
                ca = str(nd.get("created_at") or nd.get("at") or nd.get("date") or "2026-01-01").replace("T", " ").replace("Z", "")[:19]
                if len(ca) == 10:
                    ca += " 00:00:00"
                rows.append((_pick_pk(nd), json.dumps(nd, ensure_ascii=False, default=str), ca, ca))
            for i in range(0, len(rows), 1000):
                cur.executemany(f"INSERT INTO `{t}` (pk, doc, created_at, updated_at) VALUES (%s,%s,%s,%s)", rows[i:i + 1000])
            c.commit()
        print("clone", k, "ok", flush=True)
    c.close()


def step_extra(n):
    c, cur = cx(DST)
    cur.execute("SELECT JSON_VALUE(doc,'$.tenant_id') FROM users WHERE JSON_VALUE(doc,'$.email') LIKE 'perf\\_%%' LIMIT 1")
    tenant = cur.fetchone()[0]

    def col(t, extra=""):
        cur.execute(f"SELECT doc FROM `{t}` WHERE JSON_VALUE(doc,'$.tenant_id')=%s {extra}", (tenant,))
        return [json.loads(r[0]) for r in cur.fetchall()]
    divs, sups, whs, projs = col("divisions"), col("suppliers"), col("warehouses"), col("projects")
    items = col("items", "LIMIT 500")
    users = col("users")
    dos = col("do", "ORDER BY created_at DESC")
    tag = uuid.uuid4().hex[:4]
    rows = {}

    def put(t, d):
        d["tenant_id"] = tenant
        d["p7_seed"] = tag
        ca = str(d.get("created_at"))[:19].replace("T", " ")
        rows.setdefault(t, []).append((_pick_pk(d), json.dumps(d, ensure_ascii=False), ca, ca))

    statuses = ("draft", "active", "active", "active", "closed", "cancelled")
    for i in range(n):
        day = (datetime(2026, 10, 1) - timedelta(days=i % 600)).strftime("%Y-%m-%d")
        ts = f"{day}T0{i % 10}:{i % 60:02d}:{(i // 60) % 60:02d}+00:00"
        dv, pj, us = divs[i % len(divs)], projs[i % len(projs)], users[i % len(users)]
        bud = 1_000_000 * (1 + i % 97)
        put("spk", {"id": f"p7-spk-{tag}-{i}", "spk_number": f"SPK-P7-{tag}-{i:05d}", "project_name": pj.get("name") or f"Proyek {i % 30}",
                    "customer": f"Customer {i % 41}", "spk_date": day, "start_date": day, "end_date": "2027-12-31", "division_id": dv["id"],
                    "pic_id": us.get("id"), "project_id": pj["id"], "division_name": dv.get("name"), "pic_name": us.get("name"),
                    "spk_value": bud * 2, "procurement_budget": bud, "status": statuses[i % len(statuses)], "notes": "",
                    "budget_policy_mode": "global", "original_spk_value": bud * 2, "original_procurement_budget": bud, "over_budget": False,
                    "created_by": us.get("id"), "created_at": ts, "updated_at": ts})
        if i % 10 == 0:
            sp = sups[i % len(sups)]
            put("vendor_contracts", {"id": f"p7-vc-{tag}-{i}", "contract_number": f"KT-P7-{tag}-{i:05d}", "supplier_id": sp["id"],
                                     "supplier_name": sp.get("name"), "contract_date": day, "start_date": day, "end_date": "2027-06-30",
                                     "currency": "IDR", "contract_type": "price_agreement", "default_tolerance_pct": 5, "notes": "",
                                     "status": ("draft", "active", "active", "cancelled")[i % 4], "created_by": us.get("id"),
                                     "created_at": ts, "updated_at": ts})
        if i < len(dos):
            d = dos[i]
            amt = float(1_000_000 + (i % 300) * 10_000)
            vid = f"p7-vi-{tag}-{i}"
            paid = (0.0, amt / 2, amt)[i % 3]
            put("vendor_invoices", {"id": vid, "no": f"VI-P7-{tag}-{i:05d}", "supplier_id": d.get("supplier_id") or sups[i % len(sups)]["id"],
                                    "invoice_no": f"INV/{tag}/{i:05d}", "invoice_no_norm": f"inv{tag}{i:05d}", "invoice_date": day,
                                    "received_date": day, "due_date": (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d"),
                                    "dpp": round(amt / 1.11, 2), "tax_amount": round(amt - amt / 1.11, 2), "amount": amt, "alloc_total": amt,
                                    "diff": 0.0, "diff_status": "Sesuai", "diff_reason": "", "do_ids": [d["id"]],
                                    "po_ids": [], "division_ids": [d.get("division_id")], "notes": "", "status": "Diterima",
                                    "paid_total": paid, "dp_allocated_total": 0.0,
                                    "payment_status": ("Belum Dibayar", "Dibayar Sebagian", "Lunas")[i % 3],
                                    "created_by": us.get("id"), "created_by_name": us.get("name"), "created_at": ts, "updated_at": ts})
            put("vendor_invoice_allocations", {"id": f"{vid}-a", "invoice_id": vid, "do_id": d["id"], "amount": amt,
                                               "created_by": us.get("id"), "created_at": ts})
        if i % 4 == 0:
            ln = f"p7-ln-{tag}-{i}"
            w1, w2 = whs[i % len(whs)], whs[(i + 1) % len(whs)]
            put("loans", {"id": ln, "no": f"LN-P7-{tag}-{i:05d}", "date": day, "from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                          "due_date": "2027-01-31", "division_id": dv["id"], "project_id": pj["id"], "requester": f"Peminjam {i % 13}",
                          "notes": "", "created_by": us.get("id"), "created_at": ts})
            for j in range(2):
                it = items[(i + j) % len(items)]
                put("loan_lines", {"id": f"{ln}-l{j}", "loan_id": ln, "item_id": it["id"], "qty": 2, "returned": (0, 1, 2)[(i // 4 + j) % 3],
                                   "from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"], "project_id": pj["id"], "notes": "",
                                   "created_at": ts})
    for t, vals in rows.items():
        for k in range(0, len(vals), 1000):
            cur.executemany(f"INSERT INTO `{t}` (pk, doc, created_at, updated_at) VALUES (%s,%s,%s,%s)", vals[k:k + 1000])
        c.commit()
        print("extra", t, len(vals), flush=True)
    c.close()


def step_counts():
    c, cur = cx(DST)
    for t in COLLS + ["spk", "vendor_contracts", "vendor_invoices", "loans", "loan_lines", "items", "audit_logs"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM `{t}`")
            print(f"{t:24s} {cur.fetchone()[0]:>9,}")
        except pymysql.err.ProgrammingError:
            print(f"{t:24s} (tidak ada)")
    c.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    {"copy": lambda: step_copy(), "clone": lambda: step_clone(int(a[1])), "extra": lambda: step_extra(int(a[1])),
     "counts": lambda: step_counts()}[a[0]]()
