"""Pemindai kebocoran harga berbasis NILAI (throwaway tenant, DB uji terisolasi).

Membuat PO berharga khas (diskon baris, PPN, Diskon Final, DP) + DO, mengambil seluruh nilai uang yang terlihat
oleh admin, lalu memanggil SELURUH route GET (OpenAPI) sebagai user TANPA izin `view_purchase_price`
(purchasing deny + warehouse default) dan mencari nilai tersebut di JSON / XLSX / HTML.

Pakai: TEST_API_URL=http://127.0.0.1:8013/api python price_visibility_scan_test.py [--report out.json] [--report-only]
Default STRICT: exit 1 bila ada kebocoran / bentuk respon berubah / kebijakan DP dilanggar. --report-only: hanya melaporkan.

Kebijakan DP Supplier (keputusan pemilik, PR #70): user TANPA view_purchase_price yang memiliki izin modul DP
(supplier_dp.* / invoice.view) BOLEH melihat nominal DP, sisa DP, riwayat & status pembayaran; TIDAK BOLEH melihat
nilai PO / Grand Total / sisa PO setelah DP, harga satuan, maupun persentase DP (nominal DP / persen = Grand Total).
Nominal DP karenanya dikecualikan dari "nilai rahasia" HANYA untuk user dengan akses modul DP; nilai lain tetap rahasia.

Endpoint yang gagal diperiksa (HTTP 5xx, koneksi gagal, respon tak terbaca) dicatat BELUM DIUJI (bukan PASS) dan tidak
menghentikan pemeriksaan endpoint lain.
"""
import io
import json
import os
import re
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402

call, API = T.call, T.API
PRICE = 123457
QTY = 3
MONEY_KEY = re.compile(r"(price|total|amount|dpp|discount|gross|subtotal|^dp_|remaining|value|cost|tax_amount|ppn|nominal|budget|spend|payable|paid|outstanding)", re.I)
SKIP_PREFIX = ("/api/platform", "/api/auth", "/api/_", "/api/invitations/public", "/api/verify", "/api/platform-branding")


def money_values(obj, out, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            money_values(v, out, k)
    elif isinstance(obj, list):
        for v in obj:
            money_values(v, out, key)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and MONEY_KEY.search(key or "") and abs(obj) >= 1000:
        out.add(round(float(obj), 2))


def find_hits(obj, secrets, path="$", hits=None):
    hits = [] if hits is None else hits
    if isinstance(obj, dict):
        for k, v in obj.items():
            find_hits(v, secrets, f"{path}.{k}", hits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:200]):
            find_hits(v, secrets, f"{path}[]", hits)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if round(float(obj), 2) in secrets:
            hits.append((path, obj))
    elif isinstance(obj, str) and obj:
        for s in secrets:
            for txt in fmt_variants(s):
                if txt in obj:
                    hits.append((path, txt))
                    break
    return hits


def fmt_variants(v):
    i = int(round(v))
    if abs(v - i) > 0.001:
        return [f"{v:.2f}"]
    return [f"{i:,}".replace(",", "."), f"{i:,}"] if abs(i) >= 1000 else []


def uniq(hits):
    seen, out = set(), []
    for p, v in hits:
        if p not in seen:
            seen.add(p); out.append((p, v))
    return out


def make_po_priced(M):
    mro_no = f"MRO-{uuid.uuid4().hex[:6]}"
    sc, mro = call("POST", "mro", {"no": mro_no, "division_id": M["div"]["id"], "requester": "Budi", "submitted": True,
                                   "lines": [{"item_id": M["item"]["id"], "qty": QTY, "warehouse_id": M["wh"]["id"],
                                              "project_id": M["pa"]["id"], "notes": "scan"}]}, 200)
    call("POST", f"mro/{mro['id']}/submit", {})
    sc, ro = call("POST", "ro", {"division_id": M["div"]["id"], "submitted": True,
                                 "lines": [{"item_id": M["item"]["id"], "qty": QTY, "warehouse_id": M["wh"]["id"],
                                            "project_id": M["pa"]["id"], "notes": "scan",
                                            "sources": [{"mro_id": mro["id"], "line_id": mro["lines"][0]["id"], "qty": QTY}]}]}, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    sc, po = call("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "date": "2026-06-01",
                                 "final_discount_type": "percent", "final_discount_value": 3,
                                 "dp_enabled": True, "dp_type": "percentage", "dp_value": 40, "payment_notes": "DP 40%",
                                 "lines": [{"item_id": M["item"]["id"], "qty": QTY, "uom_id": M["uom"]["id"], "price": PRICE,
                                            "discount": 4321, "tax": 11, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"],
                                            "notes": "scan", "price_change_reason": "scan",
                                            "sources": [{"ro_id": ro["id"], "line_id": ro["lines"][0]["id"], "qty": QTY}]}]}, 200)
    call("POST", f"po/{po['id']}/submit", {})
    sc, d = call("GET", f"po/{po['id']}")
    if d.get("status") != "Approved":
        call("POST", f"po/{po['id']}/approve", {})
        sc, d = call("GET", f"po/{po['id']}")
    return d, mro, ro


def fetch(caller, path):
    """GET -> (status, parsed-object|None, kind). Koneksi gagal -> 1x ulang dengan koneksi baru; 5xx -> pool koneksi
    dikosongkan agar koneksi keep-alive yang diputus server tidak menggagalkan endpoint berikutnya."""
    sess = caller.S if hasattr(caller, "S") else T.S
    r, err = None, None
    for _attempt in range(2):
        try:
            r = sess.get(f"{API}/{path}", timeout=120)
            break
        except Exception as exc:  # noqa: BLE001
            err = exc
            for ad in sess.adapters.values():
                ad.poolmanager.clear()
    if r is None:
        return 599, None, f"conn-error:{type(err).__name__}"
    if r.status_code >= 500:
        for ad in sess.adapters.values():
            ad.poolmanager.clear()
    ct = r.headers.get("content-type", "")
    if "json" in ct:
        try:
            return r.status_code, r.json(), "json"
        except Exception:
            return r.status_code, None, "json?"
    if "spreadsheet" in ct or path.endswith(".xlsx"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
            cells = [c for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if c is not None]
            return r.status_code, cells, "xlsx"
        except Exception:
            return r.status_code, None, "xlsx?"
    if "pdf" in ct or path.split("?")[0].endswith(".pdf"):
        try:
            import pypdf
            txt = "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(io.BytesIO(r.content)).pages)
            return r.status_code, txt, "pdf"
        except Exception:
            return r.status_code, None, "pdf?"
    if "text" in ct or "html" in ct:
        return r.status_code, r.text, "text"
    return r.status_code, None, ct.split(";")[0] or "?"


def targets(ids, report_keys):
    spec = json.load(open("/tmp/price_scan_openapi.json"))
    out = []
    for p, v in spec["paths"].items():
        if "get" not in v or p.startswith(SKIP_PREFIX) or "download" in p:
            continue
        if p == "/api/report-center/{key}/export.pdf":
            out += [f"report-center/{k}/export.pdf?date_from=2026-01-01&date_to=2026-12-31" for k in report_keys]
            continue
        if "{" not in p:
            out.append(p[5:])
            if p in ("/api/mro", "/api/ro", "/api/po", "/api/do", "/api/mi", "/api/vendor-invoices", "/api/supplier-dp"):
                out.append(p[5:] + "?page=1&page_size=50")
            continue
        if p == "/api/report-center/{key}":
            out += [f"report-center/{k}" for k in report_keys]
            continue
        if p == "/api/report-center/{key}/export.xlsx":
            out += [f"report-center/{k}/export.xlsx" for k in report_keys]
            continue
        sub = p
        m = re.match(r"^/api/(po|ro|mro|do)/\{did\}(.*)$", p)
        if m:
            out.append(f"{m.group(1)}/{ids[m.group(1)]}{m.group(2)}")
            continue
        repl = {"{po_id}": ids["po"], "{mro_id}": ids["mro"], "{do_id}": ids["do"], "{item_id}": ids["item"],
                "{warehouse_id}": ids["wh"], "{did}": ids["do"] if "do-receiving" in p else None}
        if p.startswith("/api/lifecycle/"):
            out += [f"lifecycle/{e}/{ids[e]}" for e in ("mro", "ro", "po", "do")]
            continue
        if p.startswith("/api/document-message/"):
            out += [f"document-message/po/{ids['po']}"]
            continue
        if p.startswith("/api/transactions/{module}/{did}/capability"):
            out += [f"transactions/po/{ids['po']}/capability"]
            continue
        if p.startswith("/api/spk-allocations/po/{po_id}/budget-summary"):
            out.append(f"spk-allocations/po/{ids['po']}/budget-summary")
            continue
        if p.startswith("/api/spk-allocations/{source_type}/doc/{doc_id}"):
            out.append(f"spk-allocations/po/doc/{ids['po']}")
            continue
        for k, val in repl.items():
            if k in sub and val:
                sub = sub.replace(k, val)
        if "{" not in sub:
            out.append(sub[5:])
    return sorted(set(out))


def untested(sc, body, kind):
    """Respon yang isinya tidak dapat diperiksa -> BELUM DIUJI (bukan PASS)."""
    return sc >= 500 or (sc == 200 and (body is None or kind.endswith("?")))


def pay_dp_admin(po):
    """Admin membayar DP PO (draft -> bukti -> approve) agar riwayat & status pembayaran ikut terpindai."""
    sc, d = call("POST", f"supplier-dp/{po['id']}/draft", {}, 200)
    pid = d["active_payment"]["id"]
    r = T.S.post(f"{API}/attachments", files={"file": ("bukti.pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n", "application/pdf")},
                 data={"entity": "supplier_dp_payment", "entity_id": pid, "category": "Bukti Pembayaran"})
    assert r.status_code == 200, (r.status_code, r.text[:200])
    call("POST", f"supplier-dp/payments/{pid}/approve", {"payment_date": "2026-06-05", "fund_source": "Bank Operasional"}, 200)
    return pid


def dp_policy(u, po, dp_nominal):
    """User dgn akses DP: nominal/sisa/riwayat/status DP tampil; Nilai PO, Grand Total, sisa PO & persen DP tidak."""
    sc, rows = u("GET", "supplier-dp?tab=all")
    row = next((r for r in rows if r.get("po_id") == po["id"]), None) if isinstance(rows, list) else None
    sc_d, det = u("GET", f"supplier-dp/{po['id']}")
    sc_p, pod = u("GET", f"po/{po['id']}")
    det = det if sc_d == 200 and isinstance(det, dict) else {}
    pays = det.get("payments") or []
    r = row or {}
    return {
        "list_200": sc == 200 and row is not None,
        "dp_nominal_visible": r.get("dp_amount") == dp_nominal and det.get("dp_amount") == dp_nominal,
        "dp_paid_and_available_visible": r.get("paid_amount") == dp_nominal and r.get("dp_available") == dp_nominal,
        "payment_history_visible": len(pays) >= 1 and pays[0].get("amount") == dp_nominal and pays[0].get("status") == "Approved"
                                   and bool(pays[0].get("status_label")),
        "status_visible": r.get("status") == "Approved" and bool(r.get("status_label")),
        "po_value_hidden": "po_value" in r and r.get("po_value") is None and det.get("po_value") is None,
        "po_grand_total_hidden": isinstance(det.get("po"), dict) and det["po"].get("grand_total") is None
                                 and det["po"].get("dp_remaining") is None,
        "dp_percent_hidden": r.get("dp_value") is None and det.get("dp_value") is None
                             and all(p.get("dp_value") is None for p in pays)
                             and "%" not in str(r.get("dp_terms")) and "%" not in str(det.get("dp_terms")),
        "po_detail_dp_percent_hidden": sc_p in (403, 404) or (sc_p == 200 and pod.get("dp_value") is None),
    }


def main():
    strict = "--report-only" not in sys.argv
    rep = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else None
    M = T.setup()
    po, mro, ro = make_po_priced(M)
    sc, do = call("POST", "do", T.do_body(M, po, 2, "supX"), 200)
    sc, po2 = call("POST", "po", {"supplier_id": M["supY"]["id"], "division_id": M["div"]["id"], "date": "2026-06-02",
                                  "final_discount_type": "nominal", "final_discount_value": 7777,
                                  "dp_enabled": True, "dp_type": "nominal", "dp_value": 55555,
                                  "lines": [{"item_id": M["item2"]["id"], "qty": 2, "uom_id": M["uom"]["id"], "price": 98765,
                                             "discount": 0, "tax": 11, "warehouse_id": M["wh"]["id"], "price_change_reason": "scan"}]}, 200)
    pay_dp_admin(po)
    sc, po = call("GET", f"po/{po['id']}")
    dp_nominal = round(float(po["dp_amount"]), 2)
    spec = T.S.get(API.rsplit("/api", 1)[0] + "/openapi.json").json()
    json.dump(spec, open("/tmp/price_scan_openapi.json", "w"))
    secrets = set()
    for path in (f"po/{po['id']}", "po", f"do/{do['id']}", f"supplier-dp/{po['id']}", f"po/{po2['id']}"):
        sc, body, _ = fetch(None, path)
        if sc == 200:
            money_values(body, secrets)
    secrets |= {float(PRICE), float(PRICE * QTY), 98765.0, 7777.0, 55555.0}
    secrets = {s for s in secrets if abs(s) >= 1000}
    print(f"PO {po['no']} grand_total={po.get('grand_total')} nilai rahasia: {sorted(secrets)}")
    sc, cat = call("GET", "report-center/catalog")
    keys = [r.get("key") for g in (cat if isinstance(cat, list) else cat.get("groups", cat.get("items", []))) for r in (g.get("reports", [g]) if isinstance(g, dict) else []) if isinstance(r, dict) and r.get("key")]
    ids = {"po": po["id"], "ro": ro["id"], "mro": mro["id"], "do": do["id"], "item": M["item"]["id"], "wh": M["wh"]["id"]}
    paths = targets(ids, keys) + [f"po/{po2['id']}"]
    makers = {
        "purchasing_deny_price": lambda: mk_user("purchasing", overrides={"view_purchase_price": "deny"}),
        "warehouse_default": lambda: mk_user("warehouse", divs=[M["div"]["id"]]),
        "warehouse_global": lambda: mk_user("warehouse", overrides={"view_all_division": "allow", "view_all_warehouse": "allow"}),
        "manager_deny_price": lambda: mk_user("manager", overrides={"view_purchase_price": "deny"}),
        "finance_deny_price": lambda: mk_user("finance", overrides={"view_purchase_price": "deny"}),
    }
    # SCAN_USERS=a,b (subset; batas user per tenant paket starter). Default: purchasing deny + warehouse (divisi & global).
    # manager_deny_price / finance_deny_price: dijalankan price_visibility_scan_roles_test.py (tenant terpisah).
    # Nominal DP (bukan Nilai PO) boleh tampil HANYA untuk user dengan akses modul DP (lihat docstring).
    dp_allowed = {dp_nominal, 55555.0}  # nominal DP PO persen (sudah dibayar) & PO nominal
    pick = [x for x in os.environ.get("SCAN_USERS", "purchasing_deny_price,warehouse_default,warehouse_global").split(",") if x in makers]
    users = {name: makers[name]() for name in pick}
    report = {"secrets": sorted(secrets), "report_keys": keys, "paths": len(paths), "leaks": {}, "admin_sees": 0, "errors": {},
              "shape": {}, "untested": {}, "dp_access": {}, "dp_policy": {}}
    sc, adm = call("GET", f"po/{po2['id']}")
    for uname, u in users.items():
        sc, lim = u("GET", f"po/{po2['id']}")
        if sc in (403, 404):  # tidak berhak membuka dokumen sama sekali = tidak ada nilai yang bocor (bukan kegagalan bentuk)
            report["shape"][uname] = {"status": sc, "no_access": True}
            print(f"bentuk respon {uname}: HTTP {sc} (tanpa akses, dilewati)")
            continue
        report["shape"][uname] = {
            "status": sc, "same_keys": sc == 200 and set(lim) == set(adm),
            "same_line_keys": sc == 200 and set(lim["lines"][0]) == set(adm["lines"][0]),
            "qty_item_visible": sc == 200 and lim["lines"][0].get("qty") == 2 and lim["lines"][0].get("item_id") == M["item2"]["id"],
            "terms_visible": sc == 200 and lim.get("dp_enabled") is True and lim.get("dp_type") == "nominal"
                             and lim.get("final_discount_type") == "nominal"}
        print(f"bentuk respon {uname}: {report['shape'][uname]}")
    for path in paths:
        sc, body, kind = fetch(None, path)
        if untested(sc, body, kind):
            report["untested"].setdefault("admin", []).append(f"{path} -> {sc} {kind}")
        elif sc == 200 and find_hits(body, secrets):
            report["admin_sees"] += 1
    for uname, u in users.items():
        sc, _rows = u("GET", "supplier-dp")
        has_dp = sc == 200
        report["dp_access"][uname] = sc
        user_secrets = (secrets - dp_allowed) if has_dp else secrets
        if has_dp:
            report["dp_policy"][uname] = dp_policy(u, po, dp_nominal)
            print(f"kebijakan DP {uname}: {report['dp_policy'][uname]}")
        else:
            print(f"kebijakan DP {uname}: tanpa akses modul DP (GET supplier-dp -> {sc}); nominal DP tetap rahasia")
        leaks = {}
        for path in paths:
            sc, body, kind = fetch(u, path)
            if sc >= 500:
                report["errors"].setdefault(uname, []).append(f"{path} -> {sc}")
            if untested(sc, body, kind):
                report["untested"].setdefault(uname, []).append(f"{path} -> {sc} {kind}")
                continue
            if sc != 200:
                continue  # 401/403/404/409/422: tidak ada isi yang dikembalikan = tidak ada nilai yang bocor
            hits = uniq(find_hits(body, user_secrets))
            if hits:
                leaks[path] = {"kind": kind, "hits": [f"{p} = {v}" for p, v in hits[:25]]}
        report["leaks"][uname] = leaks
        print(f"\n=== {uname}: {len(leaks)} endpoint bocor dari {len(paths)} GET ===")
        for p, info in leaks.items():
            print(f"  LEAK {p} [{info['kind']}]")
            for h in info["hits"][:12]:
                print(f"       {h}")
    print(f"\nadmin melihat nilai harga di {report['admin_sees']} endpoint (kontrol positif)")
    if report["errors"]:
        print("HTTP 5xx:", json.dumps(report["errors"], indent=1))
    n_untested = sum(len(v) for k, v in report["untested"].items() if k != "admin")
    if report["untested"]:
        print("BELUM DIUJI (isi respon tidak dapat diperiksa; BUKAN PASS):", json.dumps(report["untested"], indent=1))
    if rep:
        json.dump(report, open(rep, "w"), indent=1)
    total = sum(len(v) for v in report["leaks"].values())
    shape_ok = all(all(v.values()) if isinstance(v, dict) else False for v in
                   ({k: x for k, x in s.items() if k != "status"} for s in report["shape"].values()))
    dp_fail = sum(0 if all(v.values()) else 1 for v in report["dp_policy"].values())
    print(f"\nRINGKASAN: {total} kebocoran (user x endpoint); kontrol positif admin={report['admin_sees']}; bentuk respon OK={shape_ok}; "
          f"kebijakan DP gagal={dp_fail}/{len(report['dp_policy'])}; BELUM DIUJI={n_untested}")
    n_checks = len(paths) * len(users) + len(report["shape"]) + len(report["dp_policy"]) + 1
    n_fail = total + sum(0 if all(v for k, v in s.items() if k != "status") else 1 for s in report["shape"].values()) \
        + dp_fail + (0 if report["admin_sees"] > 0 else 1)
    # endpoint BELUM DIUJI tidak dihitung lulus (n_checks - n_fail - n_untested), dilaporkan terpisah
    print(f"{n_checks - n_fail - n_untested}/{n_checks} passed ({n_untested} belum diuji, {n_fail} gagal)")
    if strict:
        return 0 if (total == 0 and report["admin_sees"] > 0 and shape_ok and dp_fail == 0) else 1
    return 0 if report["admin_sees"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
