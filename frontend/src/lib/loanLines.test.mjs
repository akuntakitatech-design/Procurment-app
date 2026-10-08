// Node test (no deps): node frontend/src/lib/loanLines.test.mjs
// Pinjam Barang multi gudang: default header -> baris, override manual, Terapkan Default,
// stok tersedia per (barang + Gudang Pemberi BARIS), validasi qty/gudang, arah & qty return, payload per baris,
// serta guard sumber: Loan.jsx memakai komponen khusus Loan & ItemLines bersama tidak dipakai/diubah.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "loanLines-"));
for (const f of ["transferLines.js", "loanLines.js"]) writeFileSync(join(dir, f.replace(".js", ".mjs")), readFileSync(join(here, f), "utf8").replace('"./transferLines.js"', '"./transferLines.mjs"'));
const L = await import(join(dir, "loanLines.mjs"));
const src = (p) => readFileSync(join(here, "..", p), "utf8");

let pass = 0, fail = 0;
function check(name, ok) { if (ok) { pass += 1; console.log(`PASS ${name}`); } else { fail += 1; console.log(`FAIL ${name}`); } }

const H1 = { project_id: "PA", from_warehouse_id: "WA", to_warehouse_id: "WB" };
const H2 = { project_id: "PB", from_warehouse_id: "WD", to_warehouse_id: "WC" };

// 1-4. Default header -> baris baru
const l0 = L.newLoanLine(H1);
check("1. Header default mengisi baris pertama (Gudang Pemberi/Peminjam)", l0.from_warehouse_id === "WA" && l0.to_warehouse_id === "WB");
check("3. Project Default diwariskan ke baris", l0.project_id === "PA");
check("4. Baris baru berstatus Default (bukan manual)", !L.isManual(l0, "from_warehouse_id") && !L.isManual(l0, "to_warehouse_id") && !L.isManual(l0, "project_id"));
const l1 = L.newLoanLine(H2);
check("2. Tambah baris mengambil default header SAAT ITU", l1.from_warehouse_id === "WD" && l1.to_warehouse_id === "WC" && l1.project_id === "PB");

// 5/13. Override manual dan header berubah
let lines = [L.newLoanLine(H1), L.setLineField(L.newLoanLine(H1), "to_warehouse_id", "WC"), L.setLineField(L.newLoanLine(H1), "from_warehouse_id", "WD")];
check("5. User dapat override gudang per baris (tandai Manual)", lines[1].to_warehouse_id === "WC" && L.isManual(lines[1], "to_warehouse_id"));
const pr = L.propagateDefaults(lines, H1, { ...H1, to_warehouse_id: "WE", project_id: "PB" });
check("13. Header berubah: baris Default ikut", pr.next[0].to_warehouse_id === "WE" && pr.next[0].project_id === "PB");
check("13. Header berubah: baris Manual TIDAK ditimpa", pr.next[1].to_warehouse_id === "WC" && pr.next[2].from_warehouse_id === "WD");
check("6. Satu Pinjaman A->B, A->C, D->B", lines.map((l) => `${l.from_warehouse_id}>${l.to_warehouse_id}`).join(",") === "WA>WB,WA>WC,WD>WB");

// 14. Terapkan Default ke Semua Baris
check("14. Jumlah override manual untuk konfirmasi", L.manualOverrideCount(lines, H1) === 2);
const applied = L.applyDefaultsToAll(lines, H2);
check("14. Terapkan Default: semua baris = default & status kembali Default", applied.every((l) => l.from_warehouse_id === "WD" && l.to_warehouse_id === "WC" && !L.isManual(l, "to_warehouse_id")));

// 9-12. Stok & validasi
const stock = { I1: { WA: 10, WD: 4 } };
const stockOf = (i, w) => L.availableFor(stock, i, w);
check("9. Available stock = barang + Gudang Pemberi BARIS", stockOf("I1", "WA") === 10 && stockOf("I1", "WD") === 4);
check("10. Ganti Gudang Pemberi -> stok baris ikut gudang baru", stockOf("I1", "WD") !== stockOf("I1", "WA"));
const iss = L.loanLineIssues([{ ...L.newLoanLine(H1), item_id: "I1", qty: 6 }, { ...L.newLoanLine(H1), item_id: "I1", qty: 5 }, { ...L.newLoanLine({ ...H1, to_warehouse_id: "WA" }), item_id: "I1", qty: 1 }, { ...L.newLoanLine({}), item_id: "I1", qty: 0 }], stockOf);
check("11. Qty agregat > stok Gudang Pemberi -> diblok", !!iss[0]?.stock && !!iss[1]?.stock && /gudang pemberi/.test(iss[0].stock));
check("12. Pemberi = Peminjam -> diblok", /tidak boleh sama/.test(iss[2]?.same || ""));
check("Gudang Pemberi/Peminjam wajib + qty > 0", iss[3]?.from === "Gudang Pemberi wajib dipilih" && iss[3]?.to === "Gudang Peminjam wajib dipilih" && !!iss[3]?.qty);
check("Pesan pertama memakai label Pinjam", /^Baris 1: Stok di gudang pemberi/.test(L.firstLoanIssueMessage(iss)));
check("Edit: kredit stok reversal per (barang, gudang pemberi) asli", L.editStockCredit([{ item_id: "I1", qty: 3, from_warehouse_id: "WA", to_warehouse_id: "WB" }])["I1::WA"] === 3);

// 15-20. Return
check("15. Arah return baris A->B ditampilkan B -> A", L.returnDirection({ from_name: "Gudang A", to_name: "Gudang B" }) === "Gudang B → Gudang A");
check("17. Arah return baris D->B ditampilkan B -> D", L.returnDirection({ from_name: "Gudang D", to_name: "Gudang B" }) === "Gudang B → Gudang D");
check("20. Qty return > outstanding -> diblok", !!L.returnQtyIssue(6, 5) && L.returnQtyIssue(5, 5) === null && !!L.returnQtyIssue(0, 5));

// Payload & opsi
const pl = L.linesPayload([{ ...lines[2], item_id: "I1", unit_id: "U1" }])[0];
check("Payload kirim gudang/project/unit PER BARIS", pl.from_warehouse_id === "WD" && pl.to_warehouse_id === "WB" && pl.project_id === "PA" && pl.unit_id === "U1" && !("_fromOverride" in pl));
const opt = L.nameOnlyOptions([{ id: "1", code: "GA", name: "Gudang A" }])[0];
check("Dropdown tampil nama saja, cari kode+nama", opt.selectedLabel === "Gudang A" && opt.label.includes("GA"));
const fromDoc = L.linesFromDoc({ lines: [{ id: "x", item_id: "I1", from_warehouse_id: "WA", to_warehouse_id: "WC" }] });
check("Edit: baris tersimpan = snapshot manual, tidak ditimpa header", L.propagateDefaults(fromDoc, H1, H2).next[0].to_warehouse_id === "WC");

// Guard sumber / lingkup
const loan = src("pages/Loan.jsx");
check("Loan.jsx memakai LoanItemLines (bukan ItemLines bersama)", loan.includes("<LoanItemLines") && !loan.includes('from "@/components/ItemLines"'));
check("Loan.jsx: draft lampiran modul loan sebelum posting", loan.includes('api.post("/attachment-drafts", { module: "loan" })') && loan.includes("attachment_draft_id: draftId"));
check("Loan.jsx: label header default Pinjam", ["Project Default", "Gudang Pemberi Default", "Gudang Peminjam Default", "Target Pengembalian", "Pemohon"].every((x) => loan.includes(x)));
check("Loan.jsx: stok tidak lagi dari h.from_warehouse_id", !loan.includes("stockWarehouse={() => h.from_warehouse_id}"));
check("LoanDraftAttachments: entity loan_draft", src("components/LoanDraftAttachments.jsx").includes('fd.append("entity", "loan_draft")'));
const RR = [{ loan_line_id: "L1", outstanding: 6 }, { loan_line_id: "L2", outstanding: 0 }, { loan_line_id: "L3", outstanding: 6 }];
const ri = L.returnIssues(RR, { L1: "7", L3: "6" });
check("R4. Form Return: 7 > outstanding 6 -> peringatan jelas", ri.L1 === "Qty return melebihi outstanding (6)" && ri.L3 === null && !("L2" in ri));
check("R4. Form Return: baris tidak dipilih tidak divalidasi", Object.keys(L.returnIssues(RR, {})).length === 0);
const rp = src("components/LoanReturnPicker.jsx");
check("LoanReturnPicker: per loan_line_id, tanpa pilihan gudang, submit diblok saat ada masalah", rp.includes("loan_line_id: id") && !rp.includes("warehouse_id:") && rp.includes("disabled={blocked || saving}"));
check("Loan.jsx: Return memakai LoanReturnPicker (bukan PullDialog bersama)", loan.includes("<LoanReturnPicker") && !loan.includes("<PullDialog"));
const pjs = src("lib/print.js");
check("print.js: blok khusus loan per baris", pjs.includes('if (key === "loan")') && pjs.includes('"loan_from_wh", "loan_to_wh", "project", "unit_asset"'));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
