// Node test (no deps): node frontend/src/lib/openingValuation.test.mjs
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { OPENING_STATUS_LABEL, eligibleKeys, keysPayload, massEligible, massPreview, needsAction, rowKey, toggleKey, valuationAccess } from "./openingValuation.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, p), "utf8");
let fail = 0, n = 0;
const check = (name, cond, info = "") => { n++; console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };
const canOf = (perms) => (p) => perms.includes(p);

// ---- matriks izin (view_purchase_price x stock_adjustment)
const m00 = valuationAccess(canOf([]));
const m10 = valuationAccess(canOf(["view_purchase_price"]));
const m01 = valuationAccess(canOf(["stock_adjustment"]));
const m11 = valuationAccess(canOf(["view_purchase_price", "stock_adjustment"]));
check("Tanpa harga & tanpa adjustment: tidak melihat nilai, tidak ada aksi", !m00.canView && !m00.canApply, m00);
check("Harga tanpa adjustment: boleh melihat nilai, TIDAK ada aksi Tetapkan/Massal/Replay", m10.canView && !m10.canApply, m10);
check("Adjustment tanpa harga: tidak melihat nilai, tidak ada aksi", !m01.canView && !m01.canApply, m01);
check("Kedua izin: melihat nilai + aksi", m11.canView && m11.canApply, m11);
check("can undefined aman", !valuationAccess(undefined).canView);

// ---- status final
check("Label status final", JSON.stringify(Object.values(OPENING_STATUS_LABEL)) === JSON.stringify(["Sudah Dinilai", "Siap Ditetapkan", "Perlu Revaluasi", "Tidak Ada Nilai Sumber"]));

// ---- seleksi Tetapkan Massal di Nilai Awal Persediaan
const rows = [
  { item_id: "a", warehouse_id: "w", status: "unvalued", qty_existing: 10, opening_import_qty: 10, opening_cost_candidate: 5000 },
  { item_id: "b", warehouse_id: "w", status: "unvalued", qty_existing: 10, opening_import_qty: 10, opening_cost_candidate: 5000, opening_blocked_reason: "mutasi" },
  { item_id: "c", warehouse_id: "w", status: "valued", qty_existing: 10, opening_import_qty: 10, opening_cost_candidate: 5000 },
  { item_id: "d", warehouse_id: "w", status: "unvalued", qty_existing: 4, opening_import_qty: null, opening_cost_candidate: null },
  { item_id: "e", warehouse_id: "w", status: "unvalued", qty_existing: 12, opening_import_qty: 10, opening_cost_candidate: 5000 },
];
check("Eligible hanya pool belum dinilai, tanpa mutasi, ada kandidat import, qty = saldo awal", JSON.stringify([...eligibleKeys(rows)]) === JSON.stringify(["a::w"]), [...eligibleKeys(rows)]);
check("Pool diblokir / sudah dinilai / tanpa sumber tidak bisa dicentang", !massEligible(rows[1]) && !massEligible(rows[2]) && !massEligible(rows[3]) && !massEligible(rows[4]));
let sel = toggleKey(new Set(), "a::w");
sel = toggleKey(sel, "x::w");
sel = toggleKey(sel, "x::w");
check("toggleKey menambah & menghapus", [...sel].join() === "a::w");
check("keysPayload", JSON.stringify(keysPayload(new Set(["a::w", "b::w2"]))) === JSON.stringify([{ item_id: "a", warehouse_id: "w" }, { item_id: "b", warehouse_id: "w2" }]));
const st = [
  { item_id: "a", warehouse_id: "w", status: "ready", opening_value: 50000 },
  { item_id: "b", warehouse_id: "w", status: "needs_replay", opening_value: 100000 },
  { item_id: "c", warehouse_id: "w", status: "valued" },
];
const pv = massPreview(st, new Set(["a::w", "b::w", "z::w"]));
check("Preview massal: hanya 'Siap Ditetapkan' diterapkan, Perlu Revaluasi dilewati, nilai = Σ nilai import",
  pv.apply.map(rowKey).join() === "a::w" && pv.skip.map(rowKey).join() === "b::w" && pv.missing.join() === "z::w" && pv.value === 50000, pv);
check("Dialog Dashboard menyembunyikan Sudah Dinilai", needsAction(st).map(rowKey).join() === "a::w,b::w");

// ---- komponen memakai helper izin (bukan nama role / hanya view_purchase_price)
const ov = src("../components/OpeningValuation.jsx");
const oc = src("../components/OpeningCorrection.jsx");
check("OpeningValuation memakai valuationAccess (canApply) untuk Tetapkan & Tetapkan Massal", ov.includes("valuationAccess(can)") && ov.includes("canApply &&") && ov.includes("opening-mass-apply-btn"));
check("OpeningCorrection tanpa cek nama role admin", !oc.includes('role === "admin"') && oc.includes("valuationAccess(can)"));
const iGate = oc.indexOf('{canApply ? <div className="flex flex-wrap gap-2">'), iMass = oc.indexOf('data-testid="oc-mass-preview-btn"'),
  iDry = oc.indexOf('data-testid="oc-dryrun-btn"'), iNote = oc.indexOf('data-testid="oc-no-action-note"');
check("Tombol Tetapkan Massal & Dry Run OpeningCorrection hanya dalam cabang canApply", iGate > 0 && iGate < iMass && iMass < iDry && iDry < iNote, { iGate, iMass, iDry, iNote });
check("Tombol Terapkan Revaluasi butuh canApply", oc.includes("{canApply && ds.replayable > 0 && <Button"));
const ud = src("../components/dashboard/UnvaluedStockDialog.jsx");
check("Dialog Dashboard memakai needsAction + status Sudah Dinilai", ud.includes("needsAction(data?.rows)") && ud.includes("s.valued"));

console.log(`\n${n - fail}/${n} passed`);
process.exit(fail ? 1 : 0);
