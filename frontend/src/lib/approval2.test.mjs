// Node test (no deps): node frontend/src/lib/approval2.test.mjs
// Aturan UI Pengajuan Approval 2 PO: hanya Siap Diajukan yang dapat dipilih, Level 2 PO tanpa Approve/Reject
// individual, nama file JPEG, format tanggal pengajuan, PPN tanpa pajak = "-", total footer.
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `approval2.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "approval2.js"), "utf8"));
const A = await import(tmp);

let fail = 0;
const check = (name, cond, info = "") => { console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };

check("Level 2 PO Pending -> diproses via Pengajuan Approval 2", A.isLevel2PoTask({ module: "po", seq: 2, status: "Pending" }));
check("Level 1 PO tetap Approve/Reject individual", !A.isLevel2PoTask({ module: "po", seq: 1, status: "Pending" }));
check("MRO/RO Level 2 tidak terpengaruh", !A.isLevel2PoTask({ module: "mro", seq: 2, status: "Pending" }) && !A.isLevel2PoTask({ module: "ro", seq: 2, status: "Pending" }));
check("PO Level 2 sudah Approved bukan aksi batch", !A.isLevel2PoTask({ module: "po", seq: 2, status: "Approved" }));

check("Nama file JPEG sesuai format", A.approval2FileName("Project PHR Duri", "2026-10-06") === "Approval2_Project-PHR-Duri_2026-10-06.jpg", A.approval2FileName("Project PHR Duri", "2026-10-06"));
check("Nama file aman dari karakter khusus", A.approval2FileName("  PHR / Duri: Tahap #2 ", "2026-10-06T00:00:00Z") === "Approval2_PHR-Duri-Tahap-2_2026-10-06.jpg", A.approval2FileName("  PHR / Duri: Tahap #2 ", "2026-10-06T00:00:00Z"));

check("Tanggal pengajuan murni tidak bergeser zona waktu", A.fmtA2Date("2026-10-06") === "06/10/2026");
check("Tanggal kosong -> '-'", A.fmtA2Date(null) === "-");
check("PPN 0 tampil '-'", A.fmtPpn(0) === "-" && A.fmtPpnRp(0) === "-");
check("PPN ada nilainya tampil angka", A.fmtPpn(1100) === (1100).toLocaleString("id-ID"));

const rows = [
  { approval_task_id: "t1", po_no: "PO/1", supplier_name: "Supplier X", project_text: "WUR-MD", pic_name: "Budi", submission_status: A.A2_READY, dpp: 100, ppn: 11, grand_total: 111 },
  { approval_task_id: "t2", po_no: "PO/2", supplier_name: "Supplier Y", project_text: "WUR-MD, OMSS", pic_name: "Sari", submission_status: A.A2_SUBMITTED, dpp: 200, ppn: 0, grand_total: 200 },
  { approval_task_id: "t3", po_no: "PO/3", supplier_name: "Supplier X", project_text: "OMSS", pic_name: "Budi", submission_status: A.A2_READY, dpp: 50, ppn: 5.5, grand_total: 55.5 },
];
const sel = A.selectableRows(rows).map((r) => r.approval_task_id);
check("Hanya Siap Diajukan yang dapat dipilih (Sudah Diajukan tidak)", sel.join() === "t1,t3", sel);
check("Cari berdasarkan supplier", A.searchEligible(rows, "supplier y").map((r) => r.po_no).join() === "PO/2");
check("Cari berdasarkan project", A.searchEligible(rows, "omss").length === 2);
check("Cari berdasarkan PIC", A.searchEligible(rows, "budi").length === 2);
check("Cari berdasarkan No PO", A.searchEligible(rows, "po/3").length === 1);
check("Toggle pilih/batal", A.toggleId(A.toggleId([], "t1"), "t1").length === 0 && A.toggleId(["t1"], "t3").join() === "t1,t3");
const t = A.batchTotals(rows);
check("Footer: Jumlah PO", t.count === 3);
check("Footer: Total DPP/PPN/Nilai", t.dpp === 350 && Math.abs(t.ppn - 16.5) < 1e-9 && Math.abs(t.total - 366.5) < 1e-9, t);
check("Hari ini format YYYY-MM-DD", A.isoToday(new Date(2026, 9, 6)) === "2026-10-06");

// Izin granular Approval 2
const canOf = (...keys) => (k) => keys.includes(k);
const vOnly = A.a2Access(canOf("po_approval2.view"), "Diajukan");
check("view saja: tidak bisa submit/approve/export", vOnly.view && !vOnly.submit && !vOnly.approve && !vOnly.canExport && !vOnly.canUploadEvidence);
const vSub = A.a2Access(canOf("po_approval2.view", "po_approval2.submit"), "Draft");
check("view+submit: dapat mengajukan Draft (export), tidak approve", vSub.canExport && !vSub.approve);
const vApp = A.a2Access(canOf("po_approval2.view", "po_approval2.approve"), "Diajukan");
check("view+approve: approve & unggah bukti, tidak export", vApp.approve && vApp.canUploadEvidence && !vApp.canExport && !vApp.submit);
const vPrDraft = A.a2Access(canOf("po_approval2.view", "po_approval2.print"), "Draft");
const vPr = A.a2Access(canOf("po_approval2.view", "po_approval2.print"), "Diajukan");
check("view+print: export batch Diajukan, tidak bisa mengajukan Draft", vPr.canExport && vPr.canPreview && !vPrDraft.canExport);
check("tanpa view: semua tertutup", !A.a2Access(canOf("po_approval2.print", "po_approval2.submit"), "Draft").canExport);
check("Key izin po_approval2.*", A.A2_PERM.view === "po_approval2.view" && A.A2_PERM.print === "po_approval2.print");

console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED");
process.exit(fail ? 1 : 0);
