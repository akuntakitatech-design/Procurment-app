#!/usr/bin/env python3
"""AUDIT READ-ONLY — Nilai Awal Persediaan (Import Saldo Awal) & dry-run Tetapkan Massal / Valuation Replay.

Benar-benar read-only:
  - sesi MariaDB `SET SESSION TRANSACTION READ ONLY` + `START TRANSACTION READ ONLY` (server menolak tulis apa pun);
  - hanya perintah SELECT (diverifikasi sebelum eksekusi); diakhiri ROLLBACK; tidak memanggil API aplikasi;
  - kalkulasi memakai modul murni valuation_replay.analyze() yang sama dengan endpoint status / dry-run.
  - Output hanya ke stdout + file CSV/JSON lokal (opsional).

Sumber nilai opening HANYA opening_inventory (Import Saldo Awal Persediaan): Σ base_qty, Σ opening_value per
barang x gudang. Tanpa fallback harga PO / kontrak / master / avg_cost / total_value.

Pemakaian (dari folder backend):
  DATABASE_URL=mysql://user:pass@host:3306/db python scripts/opening_valuation_audit.py [--tenant ID] [--csv out.csv] [--json out.json]
"""
import argparse
import csv
import json
import os
import re
import sys
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import valuation_replay as VR

TABLES = ("item_warehouse", "valuation_ledger", "stock_ledger", "opening_inventory", "items", "warehouses")


def connect(url):
    import pymysql
    u = urlparse(re.sub(r"^[a-z]+(\+[a-z]+)?://", "mysql://", url))
    cn = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                         database=u.path.lstrip("/").split("?")[0], autocommit=False, charset="utf8mb4")
    cur = cn.cursor()
    cur.execute("SET SESSION TRANSACTION READ ONLY")
    cur.execute("START TRANSACTION READ ONLY")
    return cn, cur


def load(cur, table, tenant):
    sql = f"SELECT doc FROM `{table}`"
    args = ()
    if tenant:
        sql += " WHERE JSON_UNQUOTE(JSON_EXTRACT(doc, '$.tenant_id')) = %s"
        args = (tenant,)
    if not sql.lstrip().upper().startswith("SELECT"):
        raise RuntimeError("audit hanya boleh SELECT")
    cur.execute(sql, args)
    out = []
    for (doc,) in cur.fetchall():
        try:
            out.append(json.loads(doc))
        except (TypeError, ValueError):
            pass
    return out


def audit_tenant(data):
    items = {i.get("id"): i for i in data["items"]}
    whs = {w.get("id"): w for w in data["warehouses"]}
    opened = {VR.key(e) for e in data["valuation_ledger"] if e.get("doc_type") == "Opening Valuation"}
    ledger_by_item, item_pools = {}, {}
    for e in data["valuation_ledger"]:
        ledger_by_item.setdefault(e.get("item_id"), []).append(e)
    for p in data["item_warehouse"]:
        item_pools.setdefault(p.get("item_id"), {})[VR.key(p)] = p
    rows, results, s = VR.analyze(data["item_warehouse"], data["opening_inventory"], opened, data["stock_ledger"],
                                  ledger_by_item, item_pools, None, None, True)
    for r in rows:
        it, wh = items.get(r["item_id"], {}), whs.get(r["warehouse_id"], {})
        r.update(item_code=it.get("code"), item_name=it.get("name"), warehouse_name=wh.get("name"),
                 opening_date=(r.get("opening_date") or "")[:10] or None)
    for x in results:
        it = items.get(x["item_id"], {})
        x.update(item_code=it.get("code"), item_name=it.get("name"))
        for p in x.get("pools", []):
            p["warehouse_name"] = (whs.get(p["warehouse_id"]) or {}).get("name")
        bd = x.get("blocked_detail")
        if bd:
            bd["warehouse_name"] = (whs.get(bd.get("warehouse_id")) or {}).get("name")
    return rows, s, results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--tenant")
    ap.add_argument("--csv")
    ap.add_argument("--json")
    a = ap.parse_args()
    if not a.database_url:
        sys.exit("DATABASE_URL wajib")
    cn, cur = connect(a.database_url)
    try:
        data_all = {t: load(cur, t, a.tenant) for t in TABLES}
    finally:
        cn.rollback()
        cn.close()
    tenants = sorted({p.get("tenant_id") for p in data_all["item_warehouse"] if p.get("tenant_id")})
    report, csv_rows = {}, []
    for t in tenants:
        data = {k: [x for x in v if x.get("tenant_id") == t] for k, v in data_all.items()}
        rows, s, replay = audit_tenant(data)
        if not rows:
            continue
        report[t] = {"summary": s, "rows": rows, "replay": [{k: v for k, v in x.items() if k != "changed"} for x in replay]}
        print(f"\n=== Tenant {t}")
        print(f"  Pool diperiksa {s['total']} | Sudah Dinilai {s['valued']} | Siap Ditetapkan {s['ready']} | "
              f"Perlu Revaluasi {s['needs_replay']} | Tidak Ada Nilai Sumber {s['no_source']}")
        print(f"  Nilai sekarang {s['inventory_value_now']:,.2f} | sesudah Direct Apply {s['inventory_value_after_mass']:,.2f} | "
              f"sesudah Replay valid {s['inventory_value_after_all']:,.2f} | selisih {s['total_delta']:,.2f}")
        print(f"  Replay: ok {s['replay_ok']} / diblokir {s['replay_blocked']}; trx terdampak {s['replay_affected_txns']} "
              f"(masuk {s['replay_affected_in']}, keluar {s['replay_affected_out']}, HPP {s['replay_affected_hpp']})")
        for x in replay:
            if x["blocked"]:
                print(f"    diblokir: {x.get('item_code')} {x.get('item_name')}: {x['blocked']}")
        for r in rows:
            fm = r.get("first_move_after_opening") or {}
            csv_rows.append({
                "tenant": t, "kode": r.get("item_code"), "barang": r.get("item_name"), "gudang": r.get("warehouse_name"),
                "qty_saldo_awal_import": r.get("opening_qty"), "qty_saat_ini": r["qty"], "harga_opening_import": r.get("opening_cost"),
                "nilai_opening_import": r.get("opening_value"), "tanggal_saldo_awal": r.get("opening_date"),
                "nilai_sebelum": r["total_value"], "nilai_dry_run": r.get("after_value"), "selisih": r.get("delta"),
                "avg_sebelum": r["avg_cost"], "avg_dry_run": r.get("after_avg"),
                "trx_setelah_opening": r.get("moves_after_opening"), "mutasi_pertama": f"{fm.get('at', '')[:10]} {fm.get('doc_type', '')} {fm.get('doc_no', '')}".strip(),
                "trx_masuk_terdampak": r.get("affected_in"), "trx_keluar_terdampak": r.get("affected_out"), "hpp_terdampak": r.get("affected_hpp"),
                "status": r["status_label"], "action": r.get("action"),
                "alasan": "; ".join(x for x in (r.get("reason"), r.get("replay_blocked")) if x)})
    if not report:
        print("Tidak ada pool yang perlu koreksi nilai awal.")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["tenant"])
            w.writeheader()
            w.writerows(csv_rows)
        print(f"\nCSV: {a.csv} ({len(csv_rows)} baris)")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
        print(f"JSON: {a.json}")


if __name__ == "__main__":
    main()
