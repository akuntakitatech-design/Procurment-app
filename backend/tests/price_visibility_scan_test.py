"""Pemindai kebocoran harga berbasis NILAI (throwaway tenant, DB uji terisolasi).

Membuat PO berharga khas (diskon baris, PPN, Diskon Final, DP) + DO, mengambil seluruh nilai uang yang terlihat
oleh admin, lalu memanggil SELURUH route GET (OpenAPI) sebagai user TANPA izin `view_purchase_price`
(purchasing deny + warehouse default) dan mencari nilai tersebut di JSON / XLSX / HTML.

Pakai: TEST_API_URL=http://127.0.0.1:8013/api python price_visibility_scan_test.py [--report out.json] [--report-only]
Default STRICT: exit 1 bila ada kebocoran / bentuk respon berubah. --report-only: hanya melaporkan (investigasi).
"""
import io
import json
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
    """GET -> (status, parsed-object|None, kind)."""
    try:
        if hasattr(caller, "S"):
            r = caller.S.get(f"{API}/{path}", timeout=120)
        else:
            r = T.S.get(f"{API}/{path}", timeout=120)
    except Exception as exc:
        return 599, None, f"conn-error:{type(exc).__name__}"
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
    if "text" in ct or "html" in ct:
        return r.status_code, r.text, "text"
    return r.status_code, None, ct.split(";")[0] or "?"


def targets(ids, report_keys):
    spec = json.load(open("/tmp/price_scan_openapi.json"))
    out = []
    for p, v in spec["paths"].items():
        if "get" not in v or p.startswith(SKIP_PREFIX) or "download" in p or p.endswith(".pdf"):
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
    users = {
        "purchasing_deny_price": mk_user("purchasing", overrides={"view_purchase_price": "deny"}),
        "warehouse_default": mk_user("warehouse", divs=[M["div"]["id"]]),
    }
    report = {"secrets": sorted(secrets), "report_keys": keys, "paths": len(paths), "leaks": {}, "admin_sees": 0, "errors": {},
              "shape": {}}
    sc, adm = call("GET", f"po/{po2['id']}")
    for uname, u in users.items():
        sc, lim = u("GET", f"po/{po2['id']}")
        report["shape"][uname] = {
            "status": sc, "same_keys": sc == 200 and set(lim) == set(adm),
            "same_line_keys": sc == 200 and set(lim["lines"][0]) == set(adm["lines"][0]),
            "qty_item_visible": sc == 200 and lim["lines"][0].get("qty") == 2 and lim["lines"][0].get("item_id") == M["item2"]["id"],
            "terms_visible": sc == 200 and lim.get("dp_enabled") is True and lim.get("dp_type") == "nominal"
                             and lim.get("final_discount_type") == "nominal"}
        print(f"bentuk respon {uname}: {report['shape'][uname]}")
    for path in paths:
        sc, body, kind = fetch(None, path)
        if sc == 200 and body is not None and find_hits(body, secrets):
            report["admin_sees"] += 1
    for uname, u in users.items():
        leaks = {}
        for path in paths:
            sc, body, kind = fetch(u, path)
            if sc >= 500:
                report["errors"].setdefault(uname, []).append(f"{path} -> {sc}")
            if sc != 200 or body is None:
                continue
            hits = uniq(find_hits(body, secrets))
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
    if rep:
        json.dump(report, open(rep, "w"), indent=1)
    total = sum(len(v) for v in report["leaks"].values())
    shape_ok = all(all(v.values()) if isinstance(v, dict) else False for v in
                   ({k: x for k, x in s.items() if k != "status"} for s in report["shape"].values()))
    print(f"\nRINGKASAN: {total} kebocoran (user x endpoint); kontrol positif admin={report['admin_sees']}; bentuk respon OK={shape_ok}")
    n_checks = len(paths) * len(users) + len(report["shape"]) + 1
    n_fail = total + sum(0 if all(v for k, v in s.items() if k != "status") else 1 for s in report["shape"].values()) \
        + (0 if report["admin_sees"] > 0 else 1)
    print(f"{n_checks - n_fail}/{n_checks} passed")
    if strict:
        return 0 if (total == 0 and report["admin_sees"] > 0 and shape_ok) else 1
    return 0 if report["admin_sees"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
