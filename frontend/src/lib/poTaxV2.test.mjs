// Node test (no deps): node frontend/src/lib/poTaxV2.test.mjs
// F2 — Master Pajak (konfigurasi), payload preview PPN, pemetaan hasil backend, cetak PO v2 (presentasi nilai tersimpan).
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const load = async (f) => { const tmp = join(tmpdir(), `${f}.${process.pid}.mjs`); writeFileSync(tmp, readFileSync(join(here, `${f}.js`), "utf8")); return import(tmp); };
const M = await load("taxMaster");
const P = await load("poTaxPayload");
const R = await load("poTaxPrint");
let fail = 0;
const check = (n, c, info = "") => { console.log(`${c ? "PASS" : "FAIL"} ${n}${!c && info ? " — " + JSON.stringify(info) : ""}`); if (!c) fail++; };

// ---- Master Pajak
check("master: kode faktur 01..10 + kosong", M.TRX_CODE_OPTIONS.map((o) => o.value).join(",") === ",01,02,03,04,05,06,07,08,09,10");
check("master: fasilitas dipisah (Tidak Dipungut / DTP / Dibebaskan)", ["NORMAL", "TIDAK_DIPUNGUT", "DTP", "DIBEBASKAN"].every((v) => M.FACILITY_OPTIONS.some((o) => o.value === v)));
check("master: belum lengkap (tanpa kode faktur & faktor)", M.taxMasterIssues({ rate: 11 }).length === 2);
check("master: lengkap", M.taxMasterIssues({ rate: 12, trx_code: "04", dpp_factor_num: 11, dpp_factor_den: 12 }).length === 0);
check("master: faktor setengah diisi = belum lengkap", M.taxMasterIssues({ trx_code: "04", dpp_factor_num: 11 }).includes("faktor DPP Nilai Lain"));

// ---- payload preview: hanya INPUT; tanpa nominal pajak dari frontend
const h = { supplier_id: "S1", date: "2026-01-10", division_id: "D1", final_discount_type: "percent", final_discount_value: 5, grand_total: 999, tax_total: 9 };
const lines = [
  { id: "a", item_id: "I1", qty: 10, price: 250000, discount: 0, tax_mode: "EXCLUDE", tax_id: "T1", total: 123, tax_amount: 7, dpp: 1 },
  { item_id: "", qty: 1, price: 1 },
  { id: "c", item_id: "I3", qty: 1, price: 500000, tax_mode: "NONE", tax_id: "T1" },
  { id: "d", item_id: "I4", qty: 2, price: 1110000, discount: 10000, tax_mode: "include", tax_id: "T1" },
];
const pl = P.buildTaxPreviewPayload({ h, lines, poId: null });
check("payload: baris tanpa barang dilewati", pl.lines.length === 3);
check("payload: tidak mengirim nominal (total/tax_amount/dpp/grand)", pl.lines.every((l) => !("total" in l) && !("tax_amount" in l) && !("dpp" in l)) && !("grand_total" in pl) && !("tax_total" in pl));
check("payload: Tanpa PPN tidak membawa Jenis PPN", pl.lines[1].tax_mode === "NONE" && pl.lines[1].tax_id === null);
check("payload: mode dinormalisasi (include -> INCLUDE)", pl.lines[2].tax_mode === "INCLUDE");
check("payload: po_id hanya saat edit", pl.po_id === undefined && P.buildTaxPreviewPayload({ h, lines, poId: "PO1" }).po_id === "PO1");
check("payload: mode tidak dikenal -> NONE", P.buildTaxPreviewPayload({ h, lines: [{ item_id: "x", tax_mode: "PPNBM", tax_id: "T" }] }).lines[0].tax_mode === "NONE");

const data = { lines: [{ total: "2500000.00" }, { total: "500000.00" }, { total: "2099500.00" }] };
const by = P.mapPreviewByIndex(lines, data);
check("map: hasil backend ke indeks form (lewati baris kosong)", by[0].total === "2500000.00" && by[1] === undefined && by[2].total === "500000.00" && by[3].total === "2099500.00");
check("map: tanpa data -> null", P.mapPreviewByIndex(lines, null)[0] === null);

check("patch: Non-PKP selalu Tanpa PPN", JSON.stringify(P.taxPatchV2("T1", "EXCLUDE", false)) === JSON.stringify({ tax_id: "", tax_mode: "NONE", _taxInitialized: true }));
check("patch: PKP Exclude bawa Jenis PPN", P.taxPatchV2("T1", "EXCLUDE", true).tax_id === "T1");
check("patch: Tanpa PPN kosongkan Jenis PPN", P.taxPatchV2("T1", "NONE", true).tax_id === "");

const bl = P.budgetLinesV2(lines, { 0: { tax: 11, tax_inclusive: false }, 2: { tax: 0, tax_inclusive: false }, 3: { tax: 11, tax_inclusive: true } });
check("budget SPK: tarif dari backend (Exclude=efektif, Include=0, belum dihitung=0)", bl.map((l) => l.tax).join(",") === "11,0,0,0");
// ---- cetak PO v2 (nilai tersimpan; tidak menghitung)
check("print: v1 dikenali (tanpa versi)", !R.isPoV2({}) && !R.isPoV2({ tax_engine_version: 1 }) && R.isPoV2({ tax_engine_version: 2 }));
check("print: catatan baris", R.poTaxLineNote({ tax_mode: "EXCLUDE", tax_code: "PPN12", tax_trx_code: "04", tax_facility: "NORMAL" }) === "Exclude · PPN 04"
  && R.poTaxLineNote({ tax_mode: "NONE" }) === "Tanpa PPN"
  && R.poTaxLineNote({ tax_mode: "EXCLUDE", tax_code: "TD", tax_trx_code: "07", tax_facility: "TIDAK_DIPUNGUT" }) === "Exclude · Tidak Dipungut 07");
const doc = { tax_engine_version: 2, gross_total: 5220000, item_discount_total: 10000, final_discount_amount: 260500, subtotal_after_discount: 4949500,
  dpp_total: 4266441.44, non_ppn_total: 475000, tax_total: 469308.56, grand_total: 5210750,
  tax_groups: [{ group: "04|PPN12|12|11|12|NORMAL", trx_code: "04", tax_code: "PPN12", facility: "NORMAL", ppn: "469308.56", ppn_facility: "0.00" },
    { group: "07|TD|12|11|12|TIDAK_DIPUNGUT", trx_code: "07", tax_code: "TD", facility: "TIDAK_DIPUNGUT", ppn: "0.00", ppn_facility: "11.00" }],
  tax_rules_snapshot: [{ group: "04|PPN12|12|11|12|NORMAL", tax_rate: "12", tax_dpp_factor_num: 11, tax_dpp_factor_den: 12 }] };
const rows = R.poV2SummaryRows(doc);
const get = (k) => rows.find((r) => r.key === k);
check("print: urutan ringkasan = form", rows.map((r) => r.key).slice(0, 6).join(",") === "gross,item_disc,final_disc,after_disc,dpp,non_ppn" && rows[rows.length - 1].key === "grand");
check("print: grand = nilai tersimpan", get("grand").value === 5210750);
check("print: label kelompok dari snapshot", get("ppn:04|PPN12|12|11|12|NORMAL").label === "PPN 12% × 11/12 (Kode 04)");
check("print: fasilitas tidak ditagih = 0", get("ppn:07|TD|12|11|12|TIDAK_DIPUNGUT").value === 0 && /Tidak Dipungut.*tidak ditagih/.test(get("ppn:07|TD|12|11|12|TIDAK_DIPUNGUT").label));
const sumParts = get("dpp").value + get("non_ppn").value + rows.filter((r) => r.key.startsWith("ppn:")).reduce((a, r) => a + r.value, 0);
check("print: DPP + Tanpa PPN + PPN = Grand Total (rekonsiliasi nilai tersimpan)", Math.round(sumParts * 100) === Math.round(5210750 * 100), sumParts);
check("print: tanpa diskon -> baris diskon tidak tampil", !R.poV2SummaryRows({ ...doc, item_discount_total: 0, final_discount_amount: 0 }).some((r) => r.key.endsWith("disc") && r.key !== "after_disc"));
check("print: tanpa tax_groups -> satu baris PPN", R.poV2SummaryRows({ ...doc, tax_groups: [] }).filter((r) => r.key === "ppn").length === 1);

console.log(fail ? `FAILED ${fail}` : "ALL PASSED");
process.exit(fail ? 1 : 0);
