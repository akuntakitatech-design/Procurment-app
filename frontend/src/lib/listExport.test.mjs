// Node test (no deps): node frontend/src/lib/listExport.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import * as mod from "./listExport.js";

test("query export: buang halaman/facets/counts & nilai kosong, pertahankan filter, pencarian, periode, sort", () => {
  const q = mod.listExportQuery({ page: 3, page_size: 25, facets: "a,b", counts: "x", q: "baut m8", sort: "grand_total", dir: "desc",
    f_receipt_status: "Partial", date_from: "2026-01-01", date_to: "", rf_kind: "overdue", empty: null });
  const sp = new URLSearchParams(q);
  assert.equal(sp.get("page"), null); assert.equal(sp.get("page_size"), null); assert.equal(sp.get("facets"), null); assert.equal(sp.get("counts"), null);
  assert.equal(sp.get("q"), "baut m8"); assert.equal(sp.get("sort"), "grand_total"); assert.equal(sp.get("dir"), "desc");
  assert.equal(sp.get("f_receipt_status"), "Partial"); assert.equal(sp.get("date_from"), "2026-01-01"); assert.equal(sp.get("rf_kind"), "overdue");
  assert.equal(sp.has("date_to"), false); assert.equal(sp.has("empty"), false);
});

test("batas export sama dengan Pusat Laporan: Excel 100.000, PDF 5.000; tombol nonaktif + alasan bila terlampaui", () => {
  assert.deepEqual(mod.LIST_EXPORT_LIMITS, { xlsx: 100000, pdf: 5000 });
  assert.equal(mod.listExportState(5000, "pdf", true).ok, true);
  const p = mod.listExportState(5001, "pdf", true);
  assert.equal(p.ok, false); assert.match(p.reason, /melebihi batas Export PDF/);
  assert.equal(mod.listExportState(5001, "xlsx", true).ok, true);
  assert.equal(mod.listExportState(100001, "xlsx", true).ok, false);
  assert.match(mod.listExportState(1, "xlsx", false).reason, /izin export/);
});

test("setiap daftar server-side punya kunci export", () => {
  for (const u of ["/mro", "/ro", "/po", "/do", "/mi", "/transfers", "/loans", "/adjustments", "/opname", "/vendor-invoices", "/vendor-invoices/do-billing"]) {
    assert.match(mod.LIST_EXPORT_KEYS[u], /^txn-/);
  }
});

// Regresi P6: Transfer, Pinjam, Penyesuaian — halaman (route /transfer, /loan, /adjustment) memakai useServerList ke
// endpoint daftar yang terpetakan ke export, dan TxnList merender ListExportButtons dari server.exportKey.
import { readFileSync } from "node:fs";
const src = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("Transfer/Pinjam/Penyesuaian: route halaman, endpoint daftar & kunci export terhubung", () => {
  const app = src("../App.js");
  const cases = [["Transfer", "/transfer", "/transfers", "txn-transfer"], ["Loan", "/loan", "/loans", "txn-loan"],
    ["Adjustment", "/adjustment", "/adjustments", "txn-adjustment"]];
  for (const [page, route, url, key] of cases) {
    assert.match(app, new RegExp(`path="${route}" element={<Protected><${page} />`), `route ${route}`);
    const p = src(`../pages/${page}.jsx`);
    assert.match(p, new RegExp(`useServerList\\("${url}"\\)`), `${page} memakai useServerList(${url})`);
    assert.match(p, /<TxnList [^>]*server={list}/, `${page} meneruskan server={list} ke TxnList`);
    assert.equal(mod.LIST_EXPORT_KEYS[url], key);
  }
  const txn = src("../components/TxnList.jsx");
  assert.match(txn, /server\?\.exportKey && <ListExportButtons reportKey={server\.exportKey} query={server\.query}/);
});

test("Transfer/Pinjam/Penyesuaian: query export = filter/pencarian/periode/sort aktif tanpa halaman", () => {
  const q = new URLSearchParams(mod.listExportQuery({ page: 2, page_size: 50, q: "TRF-001", sort: "no", dir: "asc",
    date_from: "2026-10-01", date_to: "2026-10-31", f_status: "Posted" }));
  assert.deepEqual(Object.fromEntries(q), { q: "TRF-001", sort: "no", dir: "asc", date_from: "2026-10-01", date_to: "2026-10-31", f_status: "Posted" });
});
