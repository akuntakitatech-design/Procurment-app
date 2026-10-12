"""P7 — MRO Traceability batch (pengganti N+1) — DB test terisolasi *itest*.

Rantai nyata via API (MRO -> RO -> PO -> DO parsial / penuh) + MRO tanpa turunan; laporan lama /api/reports/mro-traceability
dan Pusat Laporan memberi qty, referensi & nilai finansial yang sama dengan perhitungan referensi dari dokumen sumber:
- T1 qty request/RO/PO/diterima/MI + status/outstanding per baris;
- T2 referensi RO/PO/DO (no) sesuai rantai; MRO tanpa turunan tetap muncul (qty 0, Open);
- T3 nilai PO (DPP/pajak/total proporsional) & Total DO (DPP per unit x qty diterima) = baris PO tersimpan;
- T4 user tanpa view_purchase_price: nilai finansial None (redaksi), qty sama;
- T5 jumlah query laporan tidak bertambah per baris (batch): 3 MRO vs 6 MRO -> selisih query kecil (bukan linear x6).
"""
import os
import re
import sys

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
import vendor_invoice_test as V  # noqa: E402

call, check, API = T.call, T.check, T.API


def rows_for(fn, nos):
    sc, rows = fn("GET", "reports/mro-traceability")
    return sc, {r["mro_no"]: r for r in rows or [] if r.get("mro_no") in nos}


def queries(path):
    r = T.S.get(f"{API}/{path}")
    m = re.search(r'desc="(\d+) q', r.headers.get("server-timing", ""))
    return int(m.group(1)) if m else None


def main():
    if "itest" not in os.environ.get("DATABASE_URL", ""):
        print("Menolak berjalan: hanya untuk DB test terisolasi (*itest*).")
        sys.exit(2)
    M = T.setup()
    T.M = V.M = M
    call("PUT", "settings/approval_modules", {"modules": {k: {"enabled": False, "levels": []} for k in ("mro", "ro", "po")}}, 200)
    po1, mro1, ro1 = T.make_po(M, "supX", 10)
    sc, do1 = call("POST", "do", T.do_body(M, po1, 4, "supX"), 200)
    po2, mro2, ro2 = T.make_po(M, "supX", 6)
    sc, do2 = call("POST", "do", T.do_body(M, po2, 6, "supX"), 200)
    sc, mro3 = call("POST", "mro", {"no": "MRO-SOLO", "division_id": M["div"]["id"], "requester": "Ani", "submitted": True,
                                    "lines": [{"item_id": M["item"]["id"], "qty": 3, "warehouse_id": M["wh"]["id"]}]}, 200)
    nos = {mro1, mro2, "MRO-SOLO"}
    sc, R = rows_for(call, nos)
    check("T0 laporan 200 + 3 baris MRO uji", sc == 200 and set(R) == nos, (sc, sorted(R)))
    a, b, c = R.get(mro1, {}), R.get(mro2, {}), R.get("MRO-SOLO", {})
    check("T1a rantai parsial: request/RO/PO/diterima/MI = 10/10/10/4/0, Open", (a.get("request"), a.get("qty_ro"), a.get("qty_po"),
          a.get("qty_received"), a.get("qty_mi"), a.get("status")) == (10, 10, 10, 4, 0, "Open"), a)
    check("T1b rantai penuh: 6/6/6/6/0 outstanding 6", (b.get("request"), b.get("qty_ro"), b.get("qty_po"), b.get("qty_received"),
          b.get("outstanding")) == (6, 6, 6, 6, 6), b)
    check("T2a referensi RO/PO/DO sesuai rantai", [x["no"] for x in a.get("ro_refs") or []] == [ro1]
          and [x["no"] for x in a.get("po_refs") or []] == [po1["no"]] and [x["no"] for x in a.get("do_refs") or []] == [do1["no"]], a)
    check("T2b MRO tanpa turunan tetap muncul: qty 0, Open, tanpa referensi", (c.get("request"), c.get("qty_ro"), c.get("status"),
          c.get("po_refs")) == (3, 0, "Open", []), c)
    pl = po1["lines"][0]
    dpp = float(pl.get("dpp") if pl.get("dpp") is not None else pl["qty"] * pl["price"])
    total = float(pl.get("total") if pl.get("total") is not None else dpp)
    check("T3a nilai PO = baris PO tersimpan (alokasi penuh)", abs(a.get("po_dpp", -1) - dpp) < 0.01 and abs(a.get("po_total", -1) - total) < 0.01,
          (a.get("po_dpp"), dpp, a.get("po_total"), total))
    check("T3b Total DO = DPP per unit x qty diterima", abs(a.get("do_total", -1) - dpp / float(pl["qty"]) * 4) < 0.01, (a.get("do_total"), dpp))
    lim = V.mk_user("manager", overrides={"view_purchase_price": "deny"}, divs=[M["div"]["id"]])
    sc, RL = rows_for(lim, nos)
    al = RL.get(mro1, {})
    check("T4 tanpa view_purchase_price: finansial None, qty sama", sc == 200 and al.get("po_total") is None and al.get("do_total") is None
          and al.get("qty_received") == 4 and al.get("qty_po") == 10, (sc, al, sorted(RL)))
    q1 = queries("reports/mro-traceability")
    for _ in range(3):
        T.make_po(M, "supX", 2)
    q2 = queries("reports/mro-traceability")
    check("T5 jumlah query batch (tidak linear per baris): 3 MRO -> 6 MRO", q1 is not None and q2 is not None and q2 - q1 <= 2, (q1, q2))
    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
