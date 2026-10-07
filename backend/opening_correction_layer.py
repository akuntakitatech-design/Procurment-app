"""Koreksi Nilai Awal Persediaan: status pool, Tetapkan Massal, Revaluasi Saldo Awal / Valuation Replay.

Endpoint (tenant-scoped via proxy; gudang dibatasi cakupan divisi user seperti Nilai Awal Persediaan existing):
  GET  /api/valuation/opening-status        READ-ONLY. Status per pool (Sudah Dinilai / Siap Ditetapkan / Perlu
                                             Revaluasi / Tidak Ada Nilai Sumber). Izin: view_purchase_price.
  POST /api/valuation/opening-mass/apply    TULIS. Tetapkan Massal pool 'Siap Ditetapkan' (atau subset `keys`) lewat
                                             POST /valuation/opening existing (guard identik). Idempotent.
  POST /api/valuation/replay/dry-run        READ-ONLY. Simulasi replay kronologis (tanpa tulis apa pun, termasuk audit log).
  POST /api/valuation/replay/apply          TULIS. Terapkan hasil dry-run (fingerprint + frasa konfirmasi). Idempotent.
  GET  /api/valuation/replay/runs           READ-ONLY. Riwayat run (audit).
Izin aksi (Tetapkan Massal, Dry Run, Apply): view_purchase_price AND stock_adjustment (HTTP 403 sebelum proses apa pun).
Harga dasar HANYA dari Import Saldo Awal Persediaan (opening_inventory: Σ opening_value / Σ base_qty) — tanpa fallback.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException

import valuation_replay as VR

CONFIRM_PHRASE = "REVALUASI SALDO AWAL"


def install(server):
    app = server.app
    CURRENT_USER = Depends(server.current_user)  # dependency singleton (hindari B008)
    import doc_procurement as DP
    from reporting.scope import local_day

    # ------------------------------------------------------------------ baca (tanpa tulis)
    async def _scope(user, warehouse_id=None, division_id=None):
        m = await DP.maps()
        alw = DP._opening_wh_scope(user)
        whs = m["warehouses"]

        def in_scope(wid):
            return DP._wh_in_scope(whs.get(wid), alw) and (not division_id or (whs.get(wid) or {}).get("division_id") == division_id)

        flt = {"warehouse_id": warehouse_id} if warehouse_id else {}
        rows = await server.db.item_warehouse.find(flt, {"_id": 0}).to_list(200000)
        return [r for r in rows if in_scope(r.get("warehouse_id"))], m, in_scope

    async def _analyze(user, warehouse_id=None, division_id=None, want=None, do_replay=False):
        pools, m, in_scope = await _scope(user, warehouse_id, division_id)
        ids = sorted({p.get("item_id") for p in pools if p.get("item_id")})
        pkeys = {VR.key(p) for p in pools}
        slices = [s for s in (await server.db.opening_inventory.find({"item_id": {"$in": ids}}, {"_id": 0}).to_list(200000) if ids else [])
                  if VR.key(s) in pkeys]
        opened = {VR.key(r) for r in (await server.db.valuation_ledger.find(
            {"item_id": {"$in": ids}, "doc_type": "Opening Valuation"}, {"_id": 0, "item_id": 1, "warehouse_id": 1}).to_list(200000) if ids else [])}
        stock = await server.db.stock_ledger.find({"item_id": {"$in": ids}}, {
            "_id": 0, "item_id": 1, "warehouse_id": 1, "doc_type": 1, "doc_no": 1, "at": 1, "txn_at": 1}).to_list(500000) if ids else []
        stock = [e for e in stock if VR.key(e) in pkeys]
        ledger_by_item, item_pools = {}, {}
        if do_replay:
            _, moves = VR.movement_index(stock)
            src = VR.opening_sources(slices)
            by_k = {VR.key(p): p for p in pools}
            seed_items = sorted({k[0] for k, s in src.items() if k in by_k and k not in opened and (not want or k in want)
                                 and (k in moves or abs(s["qty"] - VR.f(by_k[k].get("current_stock"))) > 1e-9)}, key=str)
            for item_id in seed_items:
                ledger_by_item[item_id] = await server.db.valuation_ledger.find({"item_id": item_id}, {"_id": 0}).to_list(200000)
                item_pools[item_id] = {VR.key(p): p for p in await server.db.item_warehouse.find({"item_id": item_id}, {"_id": 0}).to_list(10000)}
        rows, results, summary = VR.analyze(pools, slices, opened, stock, ledger_by_item, item_pools, in_scope, want, do_replay)
        for r in rows:
            it = m["items"].get(r["item_id"], {})
            r.update(item_code=it.get("code"), item_name=it.get("name"),
                     warehouse_name=(m["warehouses"].get(r["warehouse_id"]) or {}).get("name"),
                     opening_date=local_day(r.get("opening_date")) or None)
        for res in results:
            it = m["items"].get(res["item_id"], {})
            res.update(item_code=it.get("code"), item_name=it.get("name"))
            for p in res.get("pools", []):
                p["warehouse_name"] = (m["warehouses"].get(p["warehouse_id"]) or {}).get("name")
        rows.sort(key=lambda r: (VR.DISPLAY_ORDER[r["status"]], r["item_name"] or "", r["warehouse_name"] or ""))
        return rows, results, summary

    def _want(body):
        return {(k.get("item_id"), k.get("warehouse_id")) for k in (body.get("keys") or []) if isinstance(k, dict)}

    def _public(results):
        keep = ("id", "doc_type", "doc_no", "warehouse_id", "txn_at", "qty_in", "qty_out", "before", "after")
        return [{k: v for k, v in r.items() if k != "changed"} | {"changed": [{x: c[x] for x in keep} for c in r.get("changed", [])]}
                for r in results]

    def _dry_summary(results):
        ok = [r for r in results if not r["blocked"]]
        return ok, {"items": len(results), "replayable": len(ok), "blocked": len(results) - len(ok),
                    "before_value": round(sum(r["before_value"] for r in ok), 4),
                    "opening_value": round(sum(r["opening_value"] for r in ok), 4),
                    "after_value": round(sum(r["after_value"] for r in ok), 4),
                    "delta": round(sum(r["after_value"] - r["before_value"] for r in ok), 4),
                    "affected_txns": sum(r["affected_txns"] for r in ok), "affected_in": sum(r["affected_in"] for r in ok),
                    "affected_out": sum(r["affected_out"] for r in ok), "affected_hpp": sum(r["affected_hpp"] for r in ok)}

    @app.get("/api/valuation/opening-status", tags=["valuation"])
    async def opening_status(warehouse_id: str | None = None, division_id: str | None = None, q: str | None = None,
                             status: str | None = None, user=CURRENT_USER):
        DP._require_value(user)
        rows, _, summary = await _analyze(user, warehouse_id, division_id)
        ql = (q or "").strip().lower()
        if ql:
            rows = [r for r in rows if ql in (r["item_name"] or "").lower() or ql in (r["item_code"] or "").lower()]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return {"rows": rows, "summary": summary, "status_labels": VR.STATUS_LABEL, "source": VR.SOURCE_LABEL}

    @app.post("/api/valuation/opening-mass/apply", tags=["valuation"])
    async def opening_mass_apply(body: dict | None = None, user=CURRENT_USER):
        """Tetapkan pool 'Siap Ditetapkan' (semua, atau subset `keys`) lewat POST /valuation/opening existing.
        Pool selain 'Siap Ditetapkan' (Perlu Revaluasi / Sudah Dinilai / Tanpa Sumber) tidak pernah ikut batch."""
        DP._require_valuation_action(user)
        body = body or {}
        want = _want(body)
        rows, _, _ = await _analyze(user, body.get("warehouse_id"), body.get("division_id"), want)
        seen = {(r["item_id"], r["warehouse_id"]) for r in rows}
        done, skipped = [], [{"item_id": k[0], "warehouse_id": k[1], "reason": "Pool tidak ditemukan / tidak memerlukan penetapan"}
                             for k in sorted(want - seen, key=str)]
        for r in rows:
            k = (r["item_id"], r["warehouse_id"])
            if want and k not in want:
                continue
            if r["status"] != VR.ST_READY:
                if want:
                    skipped.append({"item_id": k[0], "warehouse_id": k[1], "status": r["status"],
                                    "reason": r["reason"] or r["status_label"]})
                continue
            cost = r["opening_value"] / r["opening_qty"]  # presisi penuh: qty x cost = Σ opening_value import
            try:
                res = await DP.post_opening_valuation({"item_id": k[0], "warehouse_id": k[1], "opening_avg_cost": cost,
                                                       "cutoff_date": r.get("opening_date") or None,
                                                       "notes": "Tetapkan Massal dari Import Saldo Awal"}, user)
                done.append({"item_id": k[0], "warehouse_id": k[1], "inventory_value": res.get("inventory_value")})
            except HTTPException as exc:
                skipped.append({"item_id": k[0], "warehouse_id": k[1], "reason": exc.detail})
        if done:  # tanpa perubahan -> tanpa event audit (idempotent)
            await server.audit(user, "create", "valuation", "opening-mass", "Tetapkan Massal",
                               after={"applied": len(done), "skipped": len(skipped), "source": VR.SOURCE_LABEL, "pools": done[:500]})
        return {"applied": len(done), "skipped": skipped, "rows": done}

    @app.post("/api/valuation/replay/dry-run", tags=["valuation"])
    async def replay_dry_run(body: dict | None = None, user=CURRENT_USER):
        """READ-ONLY: tidak ada insert/update/audit log. Hanya kalkulasi in-memory."""
        DP._require_valuation_action(user)
        body = body or {}
        rows, results, summary = await _analyze(user, body.get("warehouse_id"), body.get("division_id"), _want(body), do_replay=True)
        ok, ds = _dry_summary(results)
        return {"dry_run": True, "summary": ds, "overall": summary, "fingerprint": VR.fingerprint(ok), "items": _public(results),
                "rows": [r for r in rows if r["status"] == VR.ST_REPLAY], "confirm_phrase": CONFIRM_PHRASE, "source": VR.SOURCE_LABEL}

    @app.post("/api/valuation/replay/apply", tags=["valuation"])
    async def replay_apply(body: dict | None = None, user=CURRENT_USER):
        DP._require_valuation_action(user)
        body = body or {}
        if (body.get("confirm") or "").strip().upper() != CONFIRM_PHRASE:
            raise HTTPException(400, f"Ketik frasa konfirmasi '{CONFIRM_PHRASE}' untuk menerapkan revaluasi")
        fp_in = body.get("fingerprint")
        prev = await server.db.valuation_replays.find_one({"fingerprint": fp_in, "status": "applied"}, {"_id": 0}) if fp_in else None
        if prev:
            return {"applied": False, "already_applied": True, "run_id": prev.get("id")}
        _, results, _ = await _analyze(user, body.get("warehouse_id"), body.get("division_id"), _want(body), do_replay=True)
        ok, summary = _dry_summary(results)
        fp = VR.fingerprint(ok)
        if not fp_in or fp_in != fp:
            raise HTTPException(409, "Data berubah sejak Dry Run (atau fingerprint tidak sesuai). Jalankan Dry Run ulang lalu review.")
        if not ok:
            raise HTTPException(400, "Tidak ada barang yang dapat direplay")
        run_id = server.gid()
        now = server.now_iso()
        await server.db.valuation_replays.insert_one({
            "id": run_id, "fingerprint": fp, "status": "applying", "kind": "Revaluasi Saldo Awal / Valuation Replay",
            "executed_by": user.get("email"), "executed_by_name": user.get("name"), "executed_at": now,
            "source": VR.SOURCE_LABEL, "summary": summary,
            "items": [{k: v for k, v in r.items() if k != "pools"} | {"pools": [{x: y for x, y in p.items() if x != "timeline"}
                                                                                for p in r["pools"]]} for r in _public(ok)]})
        for r in ok:
            # 1) pool akhir (CAS _ver dari dry-run): bila ada posting baru sejak dry-run, hentikan.
            for p in r["pools"]:
                ver = int(p.get("_ver") or 0)
                cas = {"item_id": p["item_id"], "warehouse_id": p["warehouse_id"], "current_stock": p["qty"]}
                cas["$and"] = [{"$or": [{"_ver": 0}, {"_ver": {"$exists": False}}, {"_ver": None}]}] if ver == 0 else [{"_ver": ver}]
                patch = {"avg_cost": p["after_avg"], "total_value": p["after_value"], "_ver": ver + 1, "valuation_replay_id": run_id}
                marker = None
                if p["injections"] and p["opening_value"]:
                    marker = server.gid()
                    patch["opening_valuation_id"] = marker
                won = await server.db.item_warehouse.find_one_and_update(cas, {"$set": patch}, return_document=True)
                if won is None:
                    await server.db.valuation_replays.update_one({"id": run_id}, {"$set": {
                        "status": "aborted", "aborted_at": server.now_iso(), "abort_reason": "pool berubah"}})
                    raise HTTPException(409, "Stok gudang berubah saat revaluasi. Jalankan Dry Run ulang.")
                for i, inj in enumerate(p["injections"] if marker else []):
                    # Penanda pada waktu Import Saldo Awal (sebelum mutasi yang dinilai ulang) -> riwayat as-of terbukti.
                    day = p.get("opening_at") or now
                    await server.db.valuation_ledger.insert_one({
                        "id": marker if i == 0 else server.gid(), "doc_type": "Opening Valuation", "doc_no": "SALDO-AWAL",
                        "doc_id": run_id, "item_id": p["item_id"], "warehouse_id": p["warehouse_id"], "qty_in": 0, "qty_out": 0,
                        "unit_cost": inj["avg_after"], "value_in": inj.get("opening_value", 0), "value_out": 0,
                        "qty_before": inj["qty_after"], "value_before": inj["value_before"], "avg_before": inj["avg_before"],
                        "qty_after": inj["qty_after"], "value_after": inj["value_after"], "avg_after": inj["avg_after"],
                        "valuation_method": "moving_weighted_average", "valuation_estimated": False,
                        "valuation_replay_id": run_id, "notes": "Revaluasi Saldo Awal (Import Saldo Awal)",
                        "user": user.get("email"), "txn_at": str(day), "at": str(day)})
            # 2) entri ledger valuasi: hanya hasil valuasi (qty/tanggal/sumber/harga IN tercatat tidak diubah)
            for c in r["changed"]:
                await server.db.valuation_ledger.update_one({"id": c["id"]}, {"$set": {
                    **c["after"], "valuation_replay_id": run_id, "valuation_replay_before": c["before"]}})
                if c["doc_type"] == "Transfer Out":
                    await server.db.transfer_lines.update_one({"id": c["line_id"]}, {"$set": {
                        "cost_snapshot": c["after"]["unit_cost"], "transfer_value": c["after"]["value_out"]}})
                elif c["doc_type"] == "Loan Out":
                    await server.db.loan_lines.update_one({"id": c["line_id"]}, {"$set": {
                        "cost_snapshot": c["after"]["unit_cost"], "loan_value": c["after"]["value_out"]}})
        await server.db.valuation_replays.update_one({"id": run_id}, {"$set": {"status": "applied", "applied_at": server.now_iso()}})
        await server.audit(user, "create", "valuation_replay", run_id, "Revaluasi Saldo Awal", after={"fingerprint": fp, **summary})
        return {"applied": True, "run_id": run_id, "summary": summary}

    @app.get("/api/valuation/replay/runs", tags=["valuation"])
    async def replay_runs(user=CURRENT_USER):
        DP._require_value(user)
        rows = await server.db.valuation_replays.find({}, {"_id": 0, "items": 0}).sort("executed_at", -1).to_list(100)
        return {"rows": rows}
