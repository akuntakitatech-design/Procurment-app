// Uji konfigurasi margin Layout Dokumen -> renderer PO REAL (per sisi, tanpa margin tetap, migrasi data lama, tanpa margin ganda).
// Jalankan: npx esbuild tests/po_print_margin_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=/tmp/m.cjs && node /tmp/m.cjs
import { realPoHtml } from "../src/lib/poPrintReal.js";
import { layoutMargins, mergeLayout, cssMargin, contentBox, MARGIN_RANGE } from "../src/lib/printMargins.js";
import fs from "fs";

let pass = 0, fail = 0;
const check = (name, ok, extra) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, extra === undefined ? "" : JSON.stringify(extra)); } };
const doc = { no: "PO/UJI/1", status: "Approved", tax_engine_version: 2, lines: [{ id: "a", item_name: "Barang", qty: 1, price: 1000, unit: "pcs" }], grand_total: 1000 };
const H = (layout, extra = {}) => realPoHtml({ doc, company: {}, layout: { show_message: true, show_signatures: true, paper_size: "A4", ...layout }, showPrice: true, autoPrint: false, ...extra });
const pageRule = (h) => (h.match(/@page\{size:A4 portrait;margin:([^}]*)\}/) || [])[1];
const sheetH = (h) => Number((h.match(/\.sheet\{min-height:([\d.]+)mm/) || [])[1]);
// Cetak: @page margin 0 + padding .sheet agar browser tidak mencetak header/footer bawaan.
const sheetPad = (h) => (h.match(/@media print\{.*?\.sheet\{padding:([^;]+);/) || [])[1];
const printSheetH = (h) => Number((h.match(/@media print\{.*?\.sheet\{padding:[^}]*min-height:([\d.]+)mm/) || [])[1]);

// 1) seragam 10/15/20/25 -> padding cetak per sisi + @page margin 0
for (const v of [10, 15, 20, 25]) {
  const h = H({ margin_top_mm: v, margin_right_mm: v, margin_bottom_mm: v, margin_left_mm: v });
  check(`margin ${v} mm -> @page margin 0 (header/footer browser tidak tercetak)`, pageRule(h) === "0", pageRule(h));
  check(`margin ${v} mm -> padding sheet cetak sama dengan konfigurasi`, sheetPad(h) === `${v}mm ${v}mm ${v}mm ${v}mm`, sheetPad(h));
  check(`margin ${v} mm -> padding layar sama (pratinjau = cetak)`, h.includes(`@media screen{body{padding:${v}mm ${v}mm ${v}mm ${v}mm}`));
  check(`margin ${v} mm -> tinggi sheet cetak = 297 - 0.6`, Math.abs(printSheetH(h) - (297 - 0.6)) < 0.05, printSheetH(h));
  check(`margin ${v} mm -> tinggi area isi = 297 - 2x${v} - 0.6`, Math.abs(sheetH(h) - (297 - 2 * v - 0.6)) < 0.05, sheetH(h));
  check(`margin ${v} mm -> data-margins body`, h.includes(`data-margins="${v} ${v} ${v} ${v}"`));
}
// 2) tiap sisi independen
const base = { margin_top_mm: 12, margin_right_mm: 15, margin_bottom_mm: 12, margin_left_mm: 15 };
for (const [side, idx] of [["top", 0], ["right", 1], ["bottom", 2], ["left", 3]]) {
  for (const v of [10, 20, 25]) {
    const exp = [12, 15, 12, 15]; exp[idx] = v;
    const h = H({ ...base, [`margin_${side}_mm`]: v });
    check(`sisi ${side}=${v} saja yang berubah (padding cetak)`, sheetPad(h) === exp.map((x) => `${x}mm`).join(" "), sheetPad(h));
  }
}
// 3) tidak ada margin tetap 15/20 di template; tidak ada margin ganda saat print
const src = fs.readFileSync(require("path").resolve(process.cwd(), "src/lib/poPrintReal.js"), "utf8");
check("template tidak memuat margin tetap (PRINT_SAFE_MM / Math.max(15 / 12, margin))", !/PRINT_SAFE_MM|Math\.max\(\s*1[25]\s*,/.test(src));
const h20 = H({ margin_top_mm: 20, margin_right_mm: 20, margin_bottom_mm: 20, margin_left_mm: 20 });
check("print: html/body padding 0 (margin hanya dari @page -> tanpa margin ganda)", h20.includes("html,body{margin:0;padding:0;background:#fff}") && !/@media print\{[^}]*body\{[^}]*padding/.test(h20));
check("hanya satu aturan margin @page (margin 0) dan tidak saling menimpa", (h20.match(/@page\{size:/g) || []).length === 1 && pageRule(h20) === "0");
// 4) prioritas & migrasi data lama
check("layoutMargins: sisi > margin_mm", JSON.stringify(layoutMargins({ margin_mm: 20, margin_top_mm: 8 })) === JSON.stringify({ top: 8, right: 20, bottom: 20, left: 20 }));
check("layoutMargins: hanya margin_mm (data lama) -> 4 sisi", JSON.stringify(layoutMargins({ margin_mm: 20 })) === JSON.stringify({ top: 20, right: 20, bottom: 20, left: 20 }));
check("layoutMargins: sisi kosong '' -> margin_mm", layoutMargins({ margin_mm: 18, margin_left_mm: "" }).left === 18);
check("layoutMargins: clamp sama dengan backend (5..30)", JSON.stringify(layoutMargins({ margin_top_mm: 1, margin_right_mm: 99, margin_bottom_mm: 5, margin_left_mm: 30 })) === JSON.stringify({ top: MARGIN_RANGE.min, right: MARGIN_RANGE.max, bottom: 5, left: 30 }));
const defaults = { margin_mm: 10, margin_top_mm: 12, margin_right_mm: 15, margin_bottom_mm: 12, margin_left_mm: 15 };
check("mergeLayout: tersimpan lama {margin_mm:20} TIDAK kalah oleh default sisi", JSON.stringify(layoutMargins(mergeLayout(defaults, { margin_mm: 20 }))) === JSON.stringify({ top: 20, right: 20, bottom: 20, left: 20 }));
check("mergeLayout: tersimpan per sisi dipakai", JSON.stringify(layoutMargins(mergeLayout(defaults, { margin_mm: 20, margin_top_mm: 25, margin_right_mm: 10, margin_bottom_mm: 15, margin_left_mm: 20 }))) === JSON.stringify({ top: 25, right: 10, bottom: 15, left: 20 }));
check("mergeLayout: belum pernah disimpan -> default konfigurasi", JSON.stringify(layoutMargins(mergeLayout(defaults, {}))) === JSON.stringify({ top: 12, right: 15, bottom: 12, left: 15 }));
check("cssMargin urutan atas kanan bawah kiri", cssMargin({ top: 1, right: 2, bottom: 3, left: 4 }) === "1mm 2mm 3mm 4mm");
check("contentBox A4 margin 25/10/15/20", JSON.stringify(contentBox([210, 297], { top: 25, right: 10, bottom: 15, left: 20 })) === JSON.stringify({ width: 180, height: 257 }));
// 5) penanda halaman lanjutan & garis bantu pratinjau & petunjuk dialog
check("penanda halaman lanjutan ada bila margin atas >= 8 mm", H({ margin_top_mm: 10 }).includes("@top-right{content:"));
check("penanda halaman lanjutan dimatikan bila margin atas < 8 mm (tidak terpotong)", !H({ margin_top_mm: 6 }).includes("@top-right"));
check("garis bantu margin hanya di pratinjau (screen), bukan cetak", H({}, { marginGuides: true }).includes("@media screen{.sheet{outline:") && !H({}).includes("outline:.3mm dashed"));
const popup = realPoHtml({ doc, company: {}, layout: { margin_top_mm: 20, margin_right_mm: 20, margin_bottom_mm: 20, margin_left_mm: 20 }, showPrice: true, autoPrint: true });
check("popup cetak: petunjuk dialog (Margins Default, Scale 100%) tampil di layar & disembunyikan saat print", popup.includes('data-testid="print-dialog-hint"') && popup.includes("@media print{.print-hint{display:none!important}") && popup.includes("atas 20 mm, kanan 20 mm, bawah 20 mm, kiri 20 mm"));
check("pratinjau (autoPrint=false) tanpa petunjuk dialog", !H({}).includes('data-testid="print-dialog-hint"'));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
