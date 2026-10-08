// Node test (no deps): node frontend/src/lib/adjustmentLines.test.mjs
// Penyesuaian Stok multi gudang: default header -> baris, override manual, Terapkan Default, validasi multi gudang,
// Before/After per (barang, gudang BARIS), konversi UOM, qty +/−/0/tidak valid, fallback legacy, payload per baris,
// guard print khusus "adjustment", serta regresi sumber Transfer & Loan (tidak memakai/diubah oleh Adjustment).
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "adjLines-"));
writeFileSync(join(dir, "adjustmentLines.mjs"), readFileSync(join(here, "adjustmentLines.js"), "utf8"));
const A = await import(join(dir, "adjustmentLines.mjs"));
const src = (p) => readFileSync(join(here, "..", p), "utf8");

let pass = 0, fail = 0;
function check(name, ok) { if (ok) { pass += 1; console.log(`PASS ${name}`); } else { fail += 1; console.log(`FAIL ${name}`); } }

const H1 = { warehouse_id: "WA", project_id: "PA" };
const H2 = { warehouse_id: "WB", project_id: "PB" };

// 1. Default header -> baris baru
const l0 = A.newAdjLine(H1);
check("1a baris baru mewarisi Gudang Default", l0.warehouse_id === "WA");
check("1b baris baru mewarisi Project Default", l0.project_id === "PA");
check("1c baris baru berstatus Default (bukan Manual)", !A.isManual(l0, "warehouse_id") && !A.isManual(l0, "project_id"));
check("1d unit/aset tidak punya default header", l0.unit_id === "");
check("1e key unik per baris", A.newAdjLine(H1)._key !== A.newAdjLine(H1)._key);

// 2. Override per baris
const l1 = A.setLineField(A.newAdjLine(H1), "warehouse_id", "WC");
check("2a ubah gudang baris -> Manual", A.isManual(l1, "warehouse_id") && l1.warehouse_id === "WC");
check("2b project tetap Default", !A.isManual(l1, "project_id"));
const l1u = A.setLineField(l1, "unit_id", "U1");
check("2c unit/aset bukan field default (tanpa flag)", l1u.unit_id === "U1" && l1u._unitOverride === undefined);

// 3. Propagasi default: hanya field Default yang ikut
const { next: p1, dirty } = A.propagateDefaults([A.newAdjLine(H1), l1], H1, H2);
check("3a baris Default ikut default baru", p1[0].warehouse_id === "WB" && p1[0].project_id === "PB");
check("3b baris Manual gudang TIDAK ditimpa", p1[1].warehouse_id === "WC");
check("3c field Default di baris Manual tetap ikut (project)", p1[1].project_id === "PB");
check("3d dirty=true", dirty === true);
const same = A.propagateDefaults(p1, H2, H2);
check("3e default sama -> tidak dirty", same.dirty === false && same.next[0] === p1[0]);

// 4. Terapkan Default ke Semua Baris (eksplisit)
check("4a hitung override yang berbeda", A.manualOverrideCount(p1, H2) === 1);
check("4b override sama dengan default tidak dihitung", A.manualOverrideCount([A.setLineField(A.newAdjLine(H2), "warehouse_id", "WB")], H2) === 0);
const ap = A.applyDefaultsToAll(p1, H2);
check("4c semua baris = default", ap.every((l) => l.warehouse_id === "WB" && l.project_id === "PB"));
check("4d flag Manual direset", ap.every((l) => !A.isManual(l, "warehouse_id") && !A.isManual(l, "project_id")));
check("4e unit/aset baris dipertahankan", A.applyDefaultsToAll([l1u], H2)[0].unit_id === "U1");
check("4f tidak mutasi input", p1[1].warehouse_id === "WC");

// 5. Konversi UOM -> satuan dasar
check("5a baseDelta faktor 12 (+2 dus = +24)", A.baseDelta({ adjustment: "2", conversion_factor: 12 }) === 24);
check("5b baseDelta negatif (-1.5 x 4 = -6)", A.baseDelta({ adjustment: "-1.5", conversion_factor: 4 }) === -6);
check("5c faktor kosong = 1", A.baseDelta({ adjustment: "3" }) === 3);

// 6. Before/After & validasi multi gudang
const stock = { I1: { WA: 10, WB: 2 }, I2: { WA: 0 } };
const stockOf = (i, w) => A.availableFor(stock, i, w);
const lines = [
  { item_id: "I1", warehouse_id: "WA", adjustment: "5", conversion_factor: 1 },
  { item_id: "I1", warehouse_id: "WB", adjustment: "-2", conversion_factor: 1 },
  { item_id: "I1", warehouse_id: "WA", adjustment: "-12", conversion_factor: 1 },
  { item_id: "I2", warehouse_id: "WA", adjustment: "-1", conversion_factor: 1 },
];
const iss = A.adjLineIssues(lines, stockOf);
check("6a +5 di WA: 10 -> 15", iss[0].ok && iss[0].before === 10 && iss[0].after === 15);
check("6b -2 di WB: 2 -> 0 (gudang berbeda independen)", iss[1].ok && iss[1].before === 2 && iss[1].after === 0);
check("6c barang+gudang sama diakumulasi berurutan (15 -12 = 3)", iss[2].ok && iss[2].before === 15 && iss[2].after === 3);
check("6d minus stok diblok per gudang baris", !!iss[3].stock && iss[3].after === -1);
check("6e pesan error pertama menyebut baris", A.firstAdjIssueMessage(iss) === `Baris 4: ${iss[3].stock}`);
const iss2 = A.adjLineIssues([{ item_id: "I1", warehouse_id: "WB", adjustment: "-3", conversion_factor: 1 }, { item_id: "I1", warehouse_id: "WA", adjustment: "-3", conversion_factor: 1 }], stockOf);
check("6f stok gudang lain tidak dipakai (WB -3 diblok walau WA cukup)", !!iss2[0].stock && iss2[1].ok);
check("6g gudang wajib", !!A.adjLineIssues([{ item_id: "I1", warehouse_id: "", adjustment: "1" }], stockOf)[0].warehouse);
check("6h barang wajib", !!A.adjLineIssues([{ item_id: "", warehouse_id: "WA", adjustment: "1" }], stockOf)[0].item);
check("6i stok belum dimuat -> tanpa before/after & tanpa blok", A.adjLineIssues([{ item_id: "I9", warehouse_id: "WA", adjustment: "-1" }], stockOf)[0] === null);
check("6j UOM dikonversi saat cek stok (-1 dus x12 > stok 10)", !!A.adjLineIssues([{ item_id: "I1", warehouse_id: "WA", adjustment: "-1", conversion_factor: 12 }], stockOf)[0].stock);

// 7. Qty positif / negatif / nol / tidak valid
const q = (v) => A.adjLineIssues([{ item_id: "I1", warehouse_id: "WA", adjustment: v, conversion_factor: 1 }], stockOf)[0];
check("7a qty positif valid", q("1").ok === true);
check("7b qty negatif valid (dalam stok)", q("-1").ok === true);
check("7c qty 0 diblok", !!q("0").qty);
check("7d qty kosong diblok", !!q("").qty);
check("7e qty tidak valid (teks) diblok", !!q("abc").qty);
check("7f issueMessages kosong untuk baris ok", A.adjIssueMessages(q("1")).length === 0);

// 8. Edit: kredit stok reversal dokumen lama per (barang, gudang)
const orig = [{ item_id: "I1", warehouse_id: "WA", adjustment: 4 }, { item_id: "I1", warehouse_id: "WB", adjustment: -2 }, { item_id: "I1", warehouse_id: "WA", adjustment: 1 }];
const cr = A.editStockCredit(orig);
check("8a kredit reversal WA = -(4+1)", cr["I1::WA"] === -5);
check("8b kredit reversal WB = +2", cr["I1::WB"] === 2);
check("8c availableFor memakai kredit", A.availableFor(stock, "I1", "WB", cr) === 4 && A.availableFor(stock, "I1", "WA", cr) === 5);

// 9. Legacy / mixed fallback + linesFromDoc
const legacyDoc = { warehouse_id: "WH", lines: [{ id: "x1", item_id: "I1", adjustment: -2, warehouse_id: "WH", project_id: "", unit_id: null, reason: "r" }, { id: "x2", item_id: "I2", adjustment: 3, warehouse_id: "WZ", project_id: "PZ", approved_unit_cost: 5 }] };
const fl = A.linesFromDoc(legacyDoc, (id) => (id === "I1" ? "PCS" : ""));
check("9a gudang tiap baris (hasil fallback backend) dipertahankan per baris", fl[0].warehouse_id === "WH" && fl[1].warehouse_id === "WZ");
check("9b baris dari dokumen = Manual (tidak berubah saat default header diganti)", fl.every((l) => A.isManual(l, "warehouse_id") && A.isManual(l, "project_id")));
check("9c uom = satuan dasar, faktor 1 (qty tersimpan dlm dasar)", fl[0].uom_id === "PCS" && fl[0].conversion_factor === 1);
check("9d biaya & alasan terbawa", fl[1].approved_unit_cost === 5 && fl[0].reason === "r");
check("9e propagasi default tidak menimpa baris dokumen", A.propagateDefaults(fl, { warehouse_id: "WH" }, { warehouse_id: "WQ" }).dirty === false);

// 10. Payload API
const pl = A.adjLinesPayload([{ item_id: "I1", adjustment: "2", conversion_factor: 12, reason: "", approved_unit_cost: "", warehouse_id: "WA", project_id: "", unit_id: "U1", _whOverride: true }, { item_id: "I2", adjustment: "-1", conversion_factor: 1, approved_unit_cost: "7.5", warehouse_id: "WB", project_id: "PB", unit_id: "" }]);
check("10a qty dikonversi ke satuan dasar", pl[0].adjustment === 24 && pl[1].adjustment === -1);
check("10b gudang/project/unit eksplisit per baris", pl[0].warehouse_id === "WA" && pl[1].warehouse_id === "WB" && pl[1].project_id === "PB" && pl[0].unit_id === "U1");
check("10c kosong -> null (bukan string kosong)", pl[0].project_id === null && pl[1].unit_id === null && pl[0].approved_unit_cost === null);
check("10d biaya numeric", pl[1].approved_unit_cost === 7.5);
check("10e flag UI tidak terkirim", !("_whOverride" in pl[0]) && !("_key" in pl[0]));

// 11. Guard sumber: komponen khusus Adjustment, print khusus key "adjustment", Transfer & Loan tidak tersentuh
const page = src("pages/Adjustment.jsx");
check("11a Adjustment.jsx memakai AdjustmentItemLines", page.includes("AdjustmentItemLines") && !/from "@\/components\/ItemLines"/.test(page));
check("11b Adjustment.jsx memakai draft lampiran adjustment", page.includes("AdjustmentDraftAttachments") && page.includes('module: "adjustment"'));
check("11c tombol Terapkan Default + konfirmasi", page.includes("adj-apply-defaults-confirm") && page.includes("Terapkan Default ke Semua Baris"));
check("11d tombol Cetak di detail", page.includes("adj-print-btn") && page.includes('printDoc("adjustment"'));
const draft = src("components/AdjustmentDraftAttachments.jsx");
check("11e draft memakai entity adjustment_draft (bukan transfer/loan)", draft.includes('"adjustment_draft"') && !draft.includes("transfer_draft") && !draft.includes("loan_draft"));
const pr = src("lib/print.js");
check("11f print: blok khusus key === \"adjustment\"", pr.includes('if (key === "adjustment") {'));
check("11g print: kolom adjustment per baris", ["adj_wh", "adj_before", "adj_qty", "adj_after", "adj_reason"].every((k) => pr.includes(`"${k}"`)));
check("11h print: biaya hanya bila showPrice", pr.includes('...(showPrice ? ["adj_cost"] : [])'));
check("11i print: blok Transfer & Loan tetap ada", pr.includes('if (key === "transfer") {') && pr.includes('if (key === "loan") {') && pr.includes('"loan_from_wh", "loan_to_wh", "project", "unit_asset"') && pr.includes('"from_wh", "to_wh", "project", "unit_asset"'));
const loanPage = src("pages/Loan.jsx"); const trfPage = src("pages/Transfer.jsx");
check("11j Loan.jsx tidak memakai komponen/lib Adjustment", !loanPage.includes("adjustment") && !loanPage.includes("Adjustment"));
check("11k Transfer.jsx tidak memakai komponen/lib Adjustment", !trfPage.includes("adjustmentLines") && !trfPage.includes("AdjustmentItemLines"));
check("11l loanLines/transferLines tidak mengimpor adjustmentLines", !src("lib/loanLines.js").includes("adjustmentLines") && !src("lib/transferLines.js").includes("adjustmentLines"));

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
