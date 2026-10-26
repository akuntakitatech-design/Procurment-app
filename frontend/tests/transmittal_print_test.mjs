// Uji template cetak Transmittal Invoice (murni HTML, tanpa jaringan).
// Jalankan: cd frontend && npx esbuild tests/transmittal_print_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=./tmp-transmittal.cjs --log-level=error && node ./tmp-transmittal.cjs
import { buildTransmittalHtml, buildTransmittalMultiHtml, checklistMark, PRINT_CHECKLIST } from "../src/lib/transmittalPrint.js";
import { checklistSummary, emptyChecklist } from "../src/lib/docChecklist.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };

const full = { invoice: "Lengkap", faktur_pajak: "Lengkap", po: "Lengkap", do: "Lengkap", bukti_penerimaan: "Lengkap", kwitansi: "Tidak Berlaku", bast: "Tidak Berlaku", kontrak: "Tidak Berlaku" };
const partial = { ...full, do: "Belum Lengkap", bukti_penerimaan: "Belum Lengkap" };

const doc = {
  no: "TRN/2026/10/00007", date: "2026-10-23", status: "Dikirim", destination: "Finance & Accounting",
  sender_name: "Agus Prasetyo", receiver_name: "Melda Sari", notes: "Mohon dicek kelengkapan faktur pajak.",
  sent_at: "2026-10-23T09:15:00+00:00", total_amount: 1500000,
  items: [
    { id: "i1", supplier_name: "PT. PROFITA ABADI", invoice_no: "PA/DO/897654", tax_invoice_no: "44423675618930", po_nos: "PO/REAL/26/10/000551", do_nos: "DO/1", amount: 1000000, checklist: full },
    { id: "i2", supplier_name: "PT. ABC", invoice_no: "INV/2026/002", tax_invoice_no: "", po_nos: "PO/2026/10/00010", do_nos: "", amount: 500000, checklist: partial },
  ],
};

const LOGO = "data:image/png;base64,LOGO";
const h = buildTransmittalHtml({ doc, company: { name: "PT. Rajawali Emas Ancora Lestari", address: "Yard Balai Raja" }, logoImg: LOGO, autoPrint: false });

check("judul & nomor transmittal", h.includes("TRANSMITTAL INVOICE") && h.includes("TRN/2026/10/00007"));
check("tanggal panjang Indonesia", h.includes("23 Oktober 2026"));
check("informasi tujuan/pengirim/penerima/status", h.includes("Finance &amp; Accounting") && h.includes("Agus Prasetyo") && h.includes("Melda Sari") && h.includes("Dikirim"));

// Kolom sesuai form manual PT REAL
check("kolom: Nama Vendor, No. Invoice, No. Faktur Pajak, No. PO, Nilai (Inc PPN)",
  h.includes("Nama Vendor") && h.includes("No. Invoice") && h.includes("No. Faktur Pajak") && h.includes("No. PO") && h.includes("Nilai (Inc PPN)"));
check("header kelompok Checklist Kelengkapan", h.includes("Checklist Kelengkapan") && h.includes('colspan="5"'));
check("5 sub-kolom checklist: DO, Bukti Penerimaan (PT. REAL), Kwitansi, BAST/Timesheet, Kontrak Kerja",
  ["DO", "Bukti Penerimaan Barang (PT. REAL)", "Kwitansi", "BAST / Timesheet", "Kontrak Kerja (Subcon)"].every((x) => h.includes(x)));
check("PRINT_CHECKLIST berisi 5 jenis (Invoice/Faktur Pajak/PO tidak diulang)",
  PRINT_CHECKLIST.map((x) => x.key).join() === "do,bukti_penerimaan,kwitansi,bast,kontrak");

// Simbol checklist
check("simbol: Lengkap = ✓, Belum Lengkap = ✗, Tidak Berlaku = −",
  checklistMark("Lengkap") === "✓" && checklistMark("Belum Lengkap") === "✗" && checklistMark("Tidak Berlaku") === "−");
const marks = (h.match(/class="mark">([^<]+)</g) || []).map((m) => m.replace(/.*>/, "").replace("<", ""));
check("jumlah simbol sesuai data: 2 ✓, 2 ✗, 6 −", marks.filter((m) => m === "✓").length === 2 && marks.filter((m) => m === "✗").length === 2 && marks.filter((m) => m === "−").length === 6, marks);

// Data & format
check("baris vendor + no invoice + faktur pajak + PO", h.includes("PT. PROFITA ABADI") && h.includes("PA/DO/897654") && h.includes("44423675618930") && h.includes("PO/REAL/26/10/000551"));
check("nilai diformat ribuan koma (1,000,000) + total", h.includes("1,000,000") && h.includes("500,000") && h.includes("1,500,000"));
check("keterangan tercetak", h.includes("Mohon dicek kelengkapan faktur pajak."));
check("area tanda tangan pengirim & penerima", h.includes("Dikirim oleh,") && h.includes("Diterima oleh,") && h.includes("Tanggal: 23/10/2026"));

// Logo di atas nama perusahaan
check("logo tampil di atas nama perusahaan", h.includes(`<img class="logo" src="${LOGO}"`) && h.indexOf('class="logo"') < h.indexOf('class="company-name"'));
check("tanpa logo: tidak ada <img> logo", !buildTransmittalHtml({ doc, company: {}, logoImg: "", autoPrint: false }).includes('class="logo"'));

check("A4 landscape & margin cetak", h.includes("@page{size:A4 landscape;margin:10mm}"));
check("autoPrint=false tidak memicu window.print", !h.includes("window.print()"));
check("autoPrint=true memicu window.print", buildTransmittalHtml({ doc, company: {}, autoPrint: true }).includes("window.print()"));
check("HTML di-escape (tidak ada tag mentah dari input)", !buildTransmittalHtml({ doc: { ...doc, destination: "<script>alert(1)</script>" }, company: {}, autoPrint: false }).includes("<script>alert(1)</script>"));

// Ringkasan checklist
const sumFull = checklistSummary(full);
check("ringkasan checklist: Lengkap semua yang wajib", sumFull.complete && sumFull.done === sumFull.required && sumFull.required === 5, sumFull);
const sumPartial = checklistSummary(partial);
check("ringkasan checklist: mendeteksi 2 dokumen belum lengkap", !sumPartial.complete && sumPartial.pending.length === 2, sumPartial.pending);
const sumEmpty = checklistSummary(emptyChecklist());
check("invoice tanpa checklist -> belum lengkap semua (8 wajib)", !sumEmpty.complete && sumEmpty.required === 8, sumEmpty);

// Export PDF massal: satu halaman per transmittal
const doc2 = { ...doc, no: "TRN/2026/10/00008", destination: "Gudang", items: [] };
const multi = buildTransmittalMultiHtml({ docs: [doc, doc2], autoPrint: false, logoImg: LOGO });
check("multi: dua bagian dokumen + semua nomor tercetak",
  (multi.match(/<section class="doc">/g) || []).length === 2 && multi.includes("TRN/2026/10/00007") && multi.includes("TRN/2026/10/00008"));
check("multi: satu transmittal per halaman (page break)", multi.includes(".doc + .doc{break-before:page;page-break-before:always}"));
check("multi: judul ringkas jumlah dokumen", multi.includes("<title>Transmittal Invoice (2)</title>"));
check("multi: dokumen tanpa invoice tetap punya placeholder", multi.includes("Tidak ada invoice"));
check("multi: satu window.print untuk seluruh halaman",
  (buildTransmittalMultiHtml({ docs: [doc, doc2], autoPrint: true }).match(/window\.print\(\)/g) || []).length === 1);
check("multi: escaping tetap berlaku",
  !buildTransmittalMultiHtml({ docs: [{ ...doc, destination: "<b>x</b>" }], autoPrint: false }).includes("<b>x</b>"));
check("multi: landscape sama dengan cetak tunggal", buildTransmittalMultiHtml({ docs: [doc], autoPrint: false }).includes("@page{size:A4 landscape;margin:10mm}"));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
