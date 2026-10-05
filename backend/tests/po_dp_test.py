"""PO — DP fleksibel (%) atau nominal sebagai ketentuan pembayaran (throwaway tenant, dev DB)."""
import sys

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402
from opening_inventory_valuation_test import dbq  # noqa: E402

call, check = T.call, T.check
GT = 297369000  # 1 x 267.900.000 + PPN 11% (29.469.000)


def line(M, qty=1, price=267900000, discount=0, tax=11):
    return {"item_id": M["item"]["id"], "qty": qty, "uom_id": M["uom"]["id"], "price": price, "discount": discount, "tax": tax,
            "warehouse_id": M["wh"]["id"], "price_change_reason": "uji DP"}


def po(M, lines=None, expect=200, **hdr):
    body = {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "date": "2026-06-01", "lines": lines or [line(M)], **hdr}
    return call("POST", "po", body, expect)


def put(M, d, lines, **hdr):
    body = {k: d.get(k) for k in ("date", "supplier_id", "division_id", "payment_term", "currency", "tax_inclusive", "final_discount_type", "final_discount_value")}
    body.update(hdr)
    body["lines"] = lines
    return call("PUT", f"transactions/po/{d['id']}", body)


def get(d):
    return call("GET", f"po/{d['id']}")[1]


def n(table, doc_id):
    return dbq(f"SELECT COUNT(*) FROM {table} WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.doc_id'))=%s", [doc_id])


def main():
    M = T.setup()
    import vendor_invoice_test as V
    V.M = M

    sc, p0 = po(M)
    check("PO tanpa DP: dp_enabled False, tanpa nilai DP", p0["grand_total"] == GT and p0["dp_enabled"] is False and p0.get("dp_amount") is None, p0.get("dp_enabled"))
    sc, p1 = po(M, dp_enabled=True, dp_type="percentage", dp_value=40, payment_notes="DP 40% setelah PO ditandatangani")
    check("DP 40%: 118.947.600, sisa 178.421.400", (p1["dp_type"], p1["dp_value"], p1["dp_amount"], p1["dp_remaining"]) == ("percentage", 40, 118947600, 178421400), p1)
    check("Keterangan Pembayaran tersimpan", p1["payment_notes"] == "DP 40% setelah PO ditandatangani")
    sc, p2 = po(M, dp_enabled=True, dp_type="nominal", dp_value=100000000)
    check("DP nominal: 100.000.000, sisa 197.369.000", (p2["dp_type"], p2["dp_amount"], p2["dp_remaining"]) == ("nominal", 100000000, 197369000), p2)
    sc, p3 = po(M, dp_enabled=True, dp_type="percentage", dp_value=12.5)
    check("DP persen desimal 12,5% (Decimal HALF_UP): 37.171.125", p3["dp_amount"] == 37171125 and p3["dp_remaining"] == GT - 37171125, p3.get("dp_amount"))

    # --- validasi
    for name, hdr, msg in [
        ("nominal > Grand Total ditolak", {"dp_type": "nominal", "dp_value": GT + 1}, "Nilai DP tidak boleh melebihi Grand Total PO."),
        ("DP % > 100 ditolak", {"dp_type": "percentage", "dp_value": 100.01}, "maksimal 100%"),
        ("DP % = 0 ditolak", {"dp_type": "percentage", "dp_value": 0}, "lebih dari 0%"),
        ("DP nominal negatif ditolak", {"dp_type": "nominal", "dp_value": -5}, "lebih dari 0"),
        ("DP nominal 0 ditolak", {"dp_type": "nominal", "dp_value": 0}, "lebih dari 0"),
        ("DP aktif tanpa nilai ditolak", {"dp_type": "nominal", "dp_value": ""}, "wajib diisi"),
        ("DP aktif tanpa tipe ditolak", {"dp_type": "", "dp_value": 10}, "Tipe DP"),
    ]:
        sc, r = po(M, expect=None, dp_enabled=True, **hdr)
        check(name, sc == 400 and msg in str(r.get("detail")), (sc, r))
    sc, pmax = po(M, dp_enabled=True, dp_type="percentage", dp_value=100)
    sc, pnm = po(M, dp_enabled=True, dp_type="nominal", dp_value=GT)
    check("batas valid: 100% dan nominal = Grand Total", pmax["dp_amount"] == GT and pmax["dp_remaining"] == 0 and pnm["dp_remaining"] == 0)

    # --- diskon item + Diskon Final + PPN; harga termasuk pajak
    sc, pd = po(M, [line(M, 4, 100000, 40000, 11)], final_discount_type="percent", final_discount_value=10, dp_enabled=True, dp_type="percentage", dp_value=40)
    check("diskon item + Diskon Final 10% + PPN 11%: GT 359.640, DP 40% 143.856", abs(pd["grand_total"] - 359640) < 0.01 and pd["dp_amount"] == 143856
          and pd["dp_remaining"] == 215784, (pd["grand_total"], pd["dp_amount"]))
    sc, pi = po(M, [line(M, 1, 111000, 0, 11)], tax_inclusive=True, dp_enabled=True, dp_type="percentage", dp_value=12.5)
    check("PO include tax: GT 111.000, DP 12,5% 13.875", abs(pi["grand_total"] - 111000) < 0.01 and pi["dp_amount"] == 13875 and pi["dp_remaining"] == 97125, (pi["grand_total"], pi["dp_amount"]))

    # --- edit: % dihitung ulang, nominal tetap, nominal > GT diblok tanpa perubahan
    sc, r = put(M, p1, [line(M, 2)])
    e1 = get(p1)
    check("edit qty: DP % dihitung ulang (GT 594.738.000 -> DP 237.895.200)", sc == 200 and e1["grand_total"] == 2 * GT and e1["dp_amount"] == 237895200
          and e1["dp_type"] == "percentage" and e1["dp_value"] == 40 and e1["payment_notes"] == "DP 40% setelah PO ditandatangani", (sc, r, e1.get("dp_amount")))
    sc, r = put(M, p2, [line(M, 2)])
    e2 = get(p2)
    check("edit qty: DP nominal tetap 100.000.000, sisa 494.738.000", sc == 200 and e2["dp_amount"] == 100000000 and e2["dp_value"] == 100000000
          and e2["dp_remaining"] == 2 * GT - 100000000, (sc, e2.get("dp_amount"), e2.get("dp_remaining")))
    before = get(p2)
    sc, r = put(M, p2, [line(M, 1, 50000000, 0, 11)])
    after = get(p2)
    check("edit: Grand Total < DP nominal -> Save diblok, pesan jelas", sc == 400 and r.get("detail") == "Nilai DP tidak boleh melebihi Grand Total PO.", (sc, r))
    check("edit diblok: PO, baris, DP tidak berubah sama sekali", (after["grand_total"], after["dp_amount"], len(after["lines"]), after["lines"][0]["qty"], after["status"])
          == (before["grand_total"], before["dp_amount"], len(before["lines"]), before["lines"][0]["qty"], before["status"]), (before["grand_total"], after["grand_total"]))
    sc, r = put(M, p1, [line(M, 1)], dp_enabled=True, dp_type="nominal", dp_value=50000000, payment_notes="Ubah ke nominal")
    e3 = get(p1)
    check("edit: ganti tipe ke nominal + keterangan baru tersimpan", (e3["dp_type"], e3["dp_amount"], e3["dp_remaining"], e3["payment_notes"]) == ("nominal", 50000000, GT - 50000000, "Ubah ke nominal"), e3)
    sc, r = put(M, p1, [line(M, 1)], dp_enabled=False)
    check("edit: DP dimatikan -> tanpa DP", get(p1)["dp_enabled"] is False and get(p1).get("dp_amount") is None)

    # --- PO lama tanpa field DP
    _exec_legacy(p0["id"])
    old = get(p0)
    check("PO lama tanpa field DP: terbuka, dianggap tanpa DP", old["dp_enabled"] is False and old.get("dp_amount") is None and old["grand_total"] == GT, old.get("dp_enabled"))
    sc, r = put(M, old, [line(M, 1)])
    check("PO lama: edit tanpa field DP tetap berhasil & tetap tanpa DP", sc == 200 and get(p0)["dp_enabled"] is False, (sc, r))

    # --- approve PO ber-DP: tidak ada efek pembayaran/stok/valuasi; edit setelah approve mereset approval
    sc, sb0 = call("GET", f"stock/by-warehouse/{M['item']['id']}")
    sc, vi0 = call("GET", "vendor-invoices?page_size=200")
    call("POST", f"po/{pd['id']}/submit", {})
    if get(pd)["status"] == "Waiting Approval":
        call("POST", f"po/{pd['id']}/approve", {})
    ap = get(pd)
    sc, sb1 = call("GET", f"stock/by-warehouse/{M['item']['id']}")
    sc, vi1 = call("GET", "vendor-invoices?page_size=200")
    check("Approve PO ber-DP: status Approved, DP tetap", ap["status"] == "Approved" and ap["dp_amount"] == 143856, ap["status"])
    check("Approve PO ber-DP: tanpa stock/valuation ledger, stok & Vendor Invoice tidak berubah",
          n("stock_ledger", pd["id"]) == 0 and n("valuation_ledger", pd["id"]) == 0 and sb0 == sb1 and vi0 == vi1)
    sc, r = put(M, ap, [line(M, 4, 100000, 40000, 11)], dp_enabled=True, dp_type="percentage", dp_value=50)
    check("edit PO Approved (ubah DP) mengikuti rule existing: approval direset ke Draft", sc == 200 and get(pd)["status"] == "Draft" and get(pd)["dp_value"] == 50, (sc, get(pd)["status"]))

    # --- tanpa izin harga: nilai DP disembunyikan
    nop = mk_user("purchasing", overrides={"view_purchase_price": "deny"})
    sc, hp = nop("GET", f"po/{p3['id']}")
    check("tanpa izin Lihat Harga Beli: nominal DP/Sisa disembunyikan", sc == 200 and hp.get("dp_amount") is None and hp.get("dp_remaining") is None and hp.get("dp_enabled") is True, hp.get("dp_amount"))

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


def _exec_legacy(po_id):
    import pymysql
    from urllib.parse import urlparse, unquote
    url = next(x.split("=", 1)[1].strip().strip('"') for x in open("/app/backend/.env") if x.startswith("DATABASE_URL="))
    assert "prod" not in url.lower()
    u = urlparse(url.replace("mariadb://", "mysql://"))
    c = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""), database=u.path.lstrip("/"))
    with c.cursor() as cur:
        cur.execute("UPDATE po SET doc = JSON_REMOVE(doc, '$.dp_enabled', '$.dp_type', '$.dp_value', '$.dp_amount', '$.dp_remaining', '$.payment_notes') "
                    "WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.id'))=%s", [po_id])
    c.commit(); c.close()


if __name__ == "__main__":
    sys.exit(main())
