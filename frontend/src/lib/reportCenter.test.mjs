// Node test (no deps): node frontend/src/lib/reportCenter.test.mjs
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { buildQuery, exportState, formatCell, isIsoDay, reportPath, validateFilters } from "./reportCenter.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, p), "utf8");
let fail = 0, n = 0;
const check = (name, cond, info = "") => { n++; console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };

check("1 buildQuery buang nilai kosong & gabung paging", buildQuery({ date_from: "2026-10-01", date_to: "", division_id: null, q: " baut " }, { page: 2, page_size: 50 })
  === "date_from=2026-10-01&q=baut&page=2&page_size=50", buildQuery({ date_from: "2026-10-01", q: " baut " }, { page: 2, page_size: 50 }));
check("2 export memakai filter yang sama TANPA paging", !buildQuery({ status: "Open" }).includes("page"));
check("3 isIsoDay hanya YYYY-MM-DD (tanpa ISO UTC)", isIsoDay("2026-10-01") && !isIsoDay("2026-09-30T17:00:00.000Z") && !isIsoDay(""));
check("4 validasi tanggal awal > akhir", validateFilters({ date_from: "2026-10-02", date_to: "2026-10-01" }) !== null && validateFilters({ date_from: "2026-10-01", date_to: "2026-10-01" }) === null);
check("5 format uang 2 desimal id-ID", formatCell(1234567.5, "money") === "1.234.567,50", formatCell(1234567.5, "money"));
check("6 format qty maks 4 desimal", formatCell(1.23456, "qty") === "1,2346" && formatCell(5, "qty") === "5", formatCell(1.23456, "qty"));
check("7 nilai kosong -> '-'", formatCell(null, "money") === "-" && formatCell("", "text") === "-");
const res = { total_rows: 5001, export_limits: { xlsx: 100000, pdf: 5000 } };
check("8 batas PDF 5.000 ditolak tegas, Excel tetap boleh", !exportState(res, "pdf", true).ok && exportState(res, "xlsx", true).ok, exportState(res, "pdf", true));
check("9 tanpa izin export -> tidak boleh", !exportState({ total_rows: 1, export_limits: {} }, "xlsx", false).ok);
check("10 reportPath encode key", reportPath("mro-traceability") === "/report-center/mro-traceability");
const page = src("../pages/ReportCenter.jsx");
check("11 halaman memakai endpoint server /report-center (catalog, data, export.xlsx, export.pdf)",
  page.includes("/report-center/catalog") && page.includes("export.${fmt}") && page.includes("reportPath("));
check("12 kolom & total dari server (tidak dihitung ulang di UI)", page.includes("res.columns") && page.includes("res.totals") && !/reduce\(/.test(page));
check("13 filter tanggal pakai input type=date (bukan DatePicker ISO UTC)", page.includes('type="date"') && !page.includes("DatePicker"));
check("14 data-testid utama tersedia", ["report-center-page", "report-center-export-xlsx", "report-center-export-pdf", "report-center-table", "report-center-total-row"].every((t) => page.includes(t)));
const hub = src("../pages/ModuleHub.jsx");
const app = src("../App.js");
check("15 menu Laporan memuat Pusat Laporan & route terdaftar; laporan lama tetap", hub.includes("/report-center") && app.includes('path="/report-center"') && app.includes('path="/reports"'));
// P1 Persediaan
const defs = [{ key: "as_of", label: "Per Tanggal (cut-off)", type: "date" }];
check("16 validasi tanggal generik dari metadata filter (as_of)", validateFilters({ as_of: "2026/10/01" }, defs) === "Per Tanggal (cut-off) tidak valid."
  && validateFilters({ as_of: "2026-10-01" }, defs) === null && validateFilters({ as_of: "x" }) === null);
check("17 filter master P1 dirender dari metadata server (gudang, kategori, barang, proyek, unit)",
  ["warehouse: [\"warehouses\"", "category: [\"item_categories\"", "item: [\"items\"", "project: [\"projects\"", "unit: [\"units\""].every((t) => page.includes(t)));
check("18 filter wajib (*) + notice server ditampilkan; baris saldo awal/akhir ditandai", page.includes("f.required") && page.includes("res.meta.notice")
  && page.includes("report-center-notice") && page.includes("report-row-${r._kind}"));
check("19 select dengan default server tidak menampilkan opsi 'Semua'", page.includes("f.default ? f.options"));

console.log(`\n${n - fail}/${n} passed`);
process.exit(fail ? 1 : 0);
