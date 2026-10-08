// Node test (no deps): node frontend/src/lib/txnValidation.test.mjs
// Validasi frontend transaksi: Divisi wajib, warisan/kunci Divisi dari sumber, Qty > 0,
// Penyesuaian +/- (tidak 0), Opname counted = 0 valid, label Satuan terpilih Penyesuaian.
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `txnValidation.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "txnValidation.js"), "utf8"));
const V = await import(tmp);
const page = (n) => readFileSync(join(here, "..", "pages", n), "utf8");
const comp = (n) => readFileSync(join(here, "..", "components", n), "utf8");

let pass = 0, fail = 0;
const t = (name, cond) => { if (cond) { pass += 1; console.log("PASS " + name); } else { fail += 1; console.log("FAIL " + name); } };

// Divisi
t("divisi kosong -> pesan Bahasa Indonesia", V.divisionError("") === "Divisi wajib diisi.");
t("divisi null -> error", V.divisionError(null) === V.DIVISION_REQUIRED_MSG);
t("divisi spasi -> error", V.divisionError("  ") === V.DIVISION_REQUIRED_MSG);
t("divisi terisi -> valid", V.divisionError("div-1") === null);

// Qty normal
for (const [label, q] of [["0", 0], ["negatif", -1], ["null", null], ["kosong", ""], ["NaN", NaN], ["Infinity", Infinity], ["teks", "abc"]]) {
  t(`qty ${label} -> ditolak`, V.isPositiveQty(q) === false);
}
t("qty 0.5 -> valid", V.isPositiveQty(0.5));
t("qty '3' -> valid", V.isPositiveQty("3"));
t("lineQtyError baris 2", V.lineQtyError([{ qty: 1 }, { qty: 0 }]) === "Baris 2: Qty harus lebih besar dari 0.");
t("lineQtyError semua valid -> null", V.lineQtyError([{ qty: 1 }, { qty: 2 }]) === null);

// Penyesuaian
t("penyesuaian +5 valid", V.lineQtyError([{ adjustment: 5 }], "adjustment") === null);
t("penyesuaian -3 valid", V.lineQtyError([{ adjustment: -3 }], "adjustment") === null);
t("penyesuaian 0 ditolak", V.lineQtyError([{ adjustment: 0 }], "adjustment") === "Baris 1: Qty Penyesuaian tidak boleh 0.");
t("penyesuaian kosong ditolak", V.lineQtyError([{ adjustment: "" }], "adjustment") !== null);

// Opname counted = 0 valid
t("opname counted 0 valid", V.lineQtyError([{ counted: 0 }], "opname") === null);
t("opname counted kosong (belum dihitung) valid", V.lineQtyError([{ counted: "" }], "opname") === null);
t("opname counted negatif ditolak", V.lineQtyError([{ counted: -1 }], "opname") !== null);

// Divisi turunan dari sumber
const one = V.sourceDivision([{ source_header: { division_id: "A" } }, { _sourceHeader: { division_id: "A" } }]);
t("sumber satu divisi -> diwarisi", one.sourced && one.division_id === "A" && !one.conflict);
const two = V.sourceDivision([{ source_header: { division_id: "A" } }, { _source_division_id: "B" }]);
t("sumber beda divisi -> konflik, tidak dipilih otomatis", two.conflict && two.division_id === null);
t("konflik -> pesan blokir", V.divisionError("A", two) === V.SOURCE_DIVISION_CONFLICT_MSG);
t("tanpa sumber -> tidak sourced", V.sourceDivision([]).sourced === false);

// Satuan terpilih Penyesuaian: nama saja
t("selected unit = nama", V.adjustmentSelectedUnitLabel({ code: "PCS", name: "Pieces" }) === "Pieces");
t("selected unit fallback kode", V.adjustmentSelectedUnitLabel({ code: "PCS" }) === "PCS");

// Integrasi halaman (UX guard terpasang di form yang diwajibkan)
for (const n of ["Mro.jsx", "Ro.jsx", "Po.jsx", "Do.jsx", "Mi.jsx", "Transfer.jsx", "Loan.jsx", "Adjustment.jsx", "Opname.jsx"]) {
  const s = page(n);
  t(`${n}: memakai DivisionField wajib`, s.includes("<DivisionField") && s.includes("divisionError("));
}
const tag = (n, tid) => { const s = page(n); const i = s.indexOf(`<DivisionField testid="${tid}"`); return i < 0 ? "" : s.slice(i, s.indexOf("/>", i)); };
t("Ro.jsx: Divisi terkunci saat ada sumber MRO", tag("Ro.jsx", "ro-division-field").includes("locked={consLines.length>0}"));
t("Po.jsx: Divisi terkunci saat ada sumber RO", tag("Po.jsx", "po-division-field").includes("locked={roLinked}"));
t("Do.jsx: Divisi terkunci (mengikuti PO)", / locked /.test(tag("Do.jsx", "do-division-field")));
t("Mi.jsx: Divisi terkunci saat sumber MRO", tag("Mi.jsx", "mi-division-field").includes("locked={!direct&&lines.some(l=>l.mro_id)}"));
t("Mi.jsx: helper text 'Divisi mengikuti MRO sumber' (bukan PO)", tag("Mi.jsx", "mi-division-field").includes('lockedHint="Divisi mengikuti MRO sumber') && !tag("Mi.jsx", "mi-division-field").includes("PO sumber"));
t("Mi.jsx: tidak ada sumber PO untuk MI (hanya MRO/Direct)", !/TabsTrigger value="PO"/.test(page("Mi.jsx")));

// Penyesuaian Stok multi gudang: UOM per baris dipindah ke komponen khusus AdjustmentItemLines (perilaku sama).
const adj = page("Adjustment.jsx") + comp("AdjustmentItemLines.jsx");
t("Adjustment.jsx: selectedLabel nama satuan", adj.includes("selectedLabel: adjustmentSelectedUnitLabel(u)"));
t("Adjustment.jsx: label dropdown memuat kode + nama + konversi (cari via kode/nama)", adj.includes("label: `${u.code && u.name && u.code !== u.name ? `${u.code} · ` : \"\"}${u.name || u.code || \"Satuan\"}") && adj.includes("— Dasar"));
// simulasi: label dropdown vs label terpilih untuk PCS/Pieces
{ const u = { code: "PCS", name: "Pieces" };
  const label = `${u.code && u.name && u.code !== u.name ? `${u.code} · ` : ""}${u.name || u.code || "Satuan"} — Dasar`;
  t("Dropdown PCS/Pieces: kode & nama tampil, dapat dicari 'pcs' dan 'pieces'", label === "PCS · Pieces — Dasar" && label.toLowerCase().includes("pcs") && label.toLowerCase().includes("pieces"));
  t("Terpilih PCS/Pieces: hanya 'Pieces'", V.adjustmentSelectedUnitLabel(u) === "Pieces"); }
t("Adjustment.jsx: qty mode adjustment", adj.includes('lineQtyError(lines,"adjustment")'));
const cb = comp("Combobox.jsx");
t("Combobox: pencarian tetap memakai label opsi", cb.includes("value={o.label}"));
t("Combobox: selectedLabel hanya untuk tampilan terpilih", cb.includes("selected.selectedLabel ?? selected.label"));
const df = comp("DivisionField.jsx");
t("DivisionField: label Divisi * dan pesan error", df.includes("Divisi <span") && df.includes("-error"));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
