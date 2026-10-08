// Node test (no deps): node frontend/src/lib/masterInline.test.mjs
// Inline "Tambah Project/Unit Baru" dari form transaksi: helper + integrasi reusable di seluruh transaksi.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, "..", p), "utf8");
const M = await import(join(here, "masterInline.js"));

let pass = 0, fail = 0;
const t = (name, cond) => { if (cond) { pass += 1; console.log(`PASS ${name}`); } else { fail += 1; console.log(`FAIL ${name}`); } };

// --- helper ---
const can = (perms) => (act, mod) => perms.includes(`${mod}.${act}`);
t("canInlineCreate: projects.create -> tombol Tambah Project tampil", M.canInlineCreate(can(["projects.create"]), "projects"));
t("canInlineCreate: hanya projects.view -> tidak tampil", !M.canInlineCreate(can(["projects.view"]), "projects"));
t("canInlineCreate: units.create -> tombol Tambah Unit tampil", M.canInlineCreate(can(["units.create"]), "units"));
t("canInlineCreate: hanya units.view -> tidak tampil", !M.canInlineCreate(can(["units.view"]), "units"));
t("canInlineCreate: master lain (uoms) tidak diaktifkan", !M.canInlineCreate(can(["uoms.create"]), "uoms"));
t("label: '+ Tambah Project Baru' / '+ Tambah Unit Baru'", M.inlineCreateLabel("projects") === "Tambah Project Baru" && M.inlineCreateLabel("units") === "Tambah Unit Baru");
t("prefill Unit: Divisi transaksi diisi otomatis", JSON.stringify(M.inlinePrefill("units", { division_id: "D1" })) === '{"division_id":"D1"}');
t("prefill Project: tanpa Divisi (master Project tidak punya Divisi)", JSON.stringify(M.inlinePrefill("projects", { division_id: "D1" })) === "{}");
const lines = [{ project_id: "a" }, { project_id: "b" }, { project_id: "c" }, { project_id: "d" }];
const out = M.applyToLine(lines, 3, "project_id", "NEW");
t("applyToLine: hanya baris pemanggil (ke-4) yang berubah", out[3].project_id === "NEW" && out.slice(0, 3).map((l) => l.project_id).join() === "a,b,c");
t("applyToLine: baris lain tetap objek yang sama (data tidak hilang)", out[0] === lines[0] && out[1] === lines[1]);
const po = M.projectOption({ id: "p1", code: "PRJ-00001", name: "Project OMSS", pic: "Budi" });
t("projectOption: value = id master, label cari kode+nama, terpilih = nama", po.value === "p1" && po.label.includes("PRJ-00001") && po.label.includes("Project OMSS") && po.selectedLabel === "Project OMSS");
const uo = M.unitOption({ id: "u1", code: "UNT-00001", name: "Excavator", plate_no: "BM 1" });
t("unitOption: value = id master, terpilih = plat/nama", uo.value === "u1" && uo.label.includes("UNT-00001") && uo.selectedLabel === "BM 1");

// --- komponen reusable ---
const C = src("components/MasterRefCombobox.jsx");
t("MasterRefCombobox: footerAction hanya bila canInlineCreate (izin create)", C.includes("const allowed = !disabled && canInlineCreate(can, name)") && C.includes("footerAction = allowed ?"));
t("MasterRefCombobox: memakai modal Master existing (MasterQuickCreate)", C.includes('import { MasterQuickCreate } from "@/pages/MasterData"'));
t("MasterRefCombobox: setelah Save -> upsert + onChange(id) pemanggil + reload master", C.includes("c.masters?.upsert?.(name, doc)") && C.includes("c.onChange?.(doc.id, doc)") && C.includes("c.masters?.reload?.(name)"));
t("MasterRefCombobox: onChange terbaru via ref (tidak stale, tidak menimpa baris lain)", C.includes("latest.current = { onChange, onCreated, masters }"));
t("MasterCreateProvider dipasang di App (modal tidak ikut ter-unmount)", src("App.js").includes("<MasterCreateProvider>"));
const MD = src("pages/MasterData.jsx");
t("MasterQuickCreate: prefill digabung ke form master existing (kode/validasi tetap)", MD.includes("export function MasterQuickCreate({ name, open, onClose, onCreated, prefill = null })") && MD.includes("setForm({ ...f, ...pre })"));
t("MasterFormDialog: gagal Save -> modal tetap terbuka (onSaved hanya saat sukses)", /onSaved\(res\.data\);\s*\} catch \(e\) \{ toast\.error\(apiError/.test(MD));

// --- integrasi global ---
const IL = src("components/ItemLines.jsx");
t("ItemLines: Project baris pakai MasterProjectCombobox + update(i) baris pemanggil", (IL.match(/<MasterProjectCombobox masters=\{masters\} options=\{projOpts\} value=\{l\.project_id \|\| ""\} onChange=\{\(v\) => update\(i, \{ project_id: v \}\)\}/g) || []).length === 2);
t("ItemLines: Unit baris pakai MasterUnitCombobox + update(i) baris pemanggil", (IL.match(/<MasterUnitCombobox masters=\{masters\} options=\{unitOpts\} value=\{l\.unit_id \|\| ""\} onChange=\{\(v\) => update\(i, \{ unit_id: v \}\)\}/g) || []).length === 2);
const DH = src("components/DocumentHeaderDefaults.jsx");
t("DocumentHeaderDefaults (DO/MI): header Project/Unit reusable + functional setH", DH.includes("<MasterProjectCombobox") && DH.includes("<MasterUnitCombobox") && DH.includes("setH((s) => ({ ...s, default_project_id: v }))"));
for (const [n, pre] of [["Mro.jsx", "mro"], ["Ro.jsx", "ro"], ["Po.jsx", "po"]]) {
  const s = src(`pages/${n}`);
  t(`${n}: header Project & Unit/Aset Default pakai komponen reusable`, s.includes(`testid="${pre}-hdr-project"`) && s.includes(`testid="${pre}-hdr-unit"`) && s.includes("<MasterProjectCombobox") && s.includes("<MasterUnitCombobox"));
  t(`${n}: ItemLines menerima Divisi (prefill Unit baru)`, s.includes("division={h.division_id}"));
}
t("Mi.jsx: Project/Unit baris Direct pakai komponen reusable", src("pages/Mi.jsx").includes("<MasterProjectCombobox masters={masters} options={projOpts}") && src("pages/Mi.jsx").includes("<MasterUnitCombobox masters={masters} options={unitOpts}"));
// Transfer: Project Default tetap komponen reusable; opsi nama-saja (cari kode+nama) dari transferLines.nameOnlyOptions.
t("Transfer.jsx: Project header pakai komponen reusable", src("pages/Transfer.jsx").includes('<MasterProjectCombobox masters={masters} options={projOpts} value={h.project_id}') && src("pages/Transfer.jsx").includes("const projOpts = nameOnlyOptions(masters.data.projects)"));
// Pinjam Barang multi gudang: baris khusus Loan (LoanItemLines) tetap memakai komponen Project/Unit reusable + divisi;
// Project Default header pakai komponen reusable dengan opsi nama-saja.
t("Loan.jsx: LoanItemLines project/unit (reusable) + divisi", src("pages/Loan.jsx").includes("<LoanItemLines lines={lines} onChange={setLines} masters={masters} defaults={defaults} issues={shownIssues} stockOf={stockOf} division={h.division_id}")
  && src("components/LoanItemLines.jsx").includes("<MasterProjectCombobox masters={masters} options={projOpts}") && src("components/LoanItemLines.jsx").includes("<MasterUnitCombobox masters={masters} options={unitOpts}"));
t("Loan.jsx: Project Default header pakai komponen reusable", src("pages/Loan.jsx").includes('<MasterProjectCombobox masters={masters} options={projOpts} value={h.project_id}') && src("pages/Loan.jsx").includes("const projOpts = nameOnlyOptions(masters.data.projects)"));
t("Spk.jsx: Project/Site pakai komponen reusable + daftar lokal ikut refresh", src("pages/Spk.jsx").includes("<MasterProjectCombobox") && src("pages/Spk.jsx").includes("onCreated={(doc) => setProjects("));
const raw = /<Combobox[^>]*options=\{(projOpts|projectOpts|unitOpts|projects|units|masters\.opts\("(projects|units)"[^)]*\))\}/;
for (const n of ["Mro.jsx", "Ro.jsx", "Po.jsx", "Do.jsx", "Mi.jsx", "Transfer.jsx", "Loan.jsx", "Spk.jsx"]) t(`${n}: tidak ada Combobox Project/Unit mentah tersisa`, !raw.test(src(`pages/${n}`)));
t("ItemLines/DocumentHeaderDefaults: tidak ada Combobox Project/Unit mentah", !raw.test(IL) && !raw.test(DH));

// --- tidak merusak tampilan UOM Penyesuaian Stok ---
// Multi gudang per item: UOM per baris ada di AdjustmentItemLines; Project/Unit per baris memakai MasterRefCombobox,
// sedangkan UOM tetap Combobox biasa (tidak disentuh inline master; label terpilih tetap nama saja).
const adj = src("components/AdjustmentItemLines.jsx");
const adjUom = adj.slice(adj.indexOf("testid={`${testidPrefix}-uom-"), adj.indexOf("/>", adj.indexOf("testid={`${testidPrefix}-uom-")));
t("Adjustment.jsx: tidak disentuh inline master (UOM terpilih tetap nama saja)", adj.includes("selectedLabel: adjustmentSelectedUnitLabel(u)") && /<Combobox dense testid=\{`\$\{testidPrefix\}-uom-/.test(adj) && !adjUom.includes("Master"));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
