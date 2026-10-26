// Uji template cetak Transmittal Invoice (murni HTML, tanpa jaringan).
// Jalankan: cd frontend && npx esbuild tests/transmittal_print_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=./tmp-transmittal.cjs --log-level=error && node ./tmp-transmittal.cjs
import { buildTransmittalHtml } from "../src/lib/transmittalPrint.js";
import { checklistSummary, emptyChecklist } from "../src/lib/docChecklist.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };

const checklistFull = { invoice: "Lengkap", faktur_pajak: "Lengkap", po: "Lengkap", do: "Lengkap", bukti_penerimaan: "Lengkap", kwitansi: "Tidak Berlaku", bast: "Tidak Berlaku", kontrak: "Tidak Berlaku" };
const checklistPartial = { ...checklistFull, do: "Belum Lengkap", bukti_penerimaan: "Belum Lengkap" };

const doc = {
  no: "TRN/2026/10/00007", date: "2026-10-23", status: "Dikirim", destination: "Finance & Accounting",
  sender_name: "Agus Prasetyo", receiver_name: "Melda Sari", notes: "Mohon dicek kelengkapan faktur pajak.",
  sent_at: "2026-10-23T09:15:00+00:00", total_amount: 1500000,
  items: [
    { id: "i1", supplier_name: "PT. Riau Indo Pasifik", invoice_no: "INV/2026/001", tax_invoice_no: "010.000-26.00000001", tax_invoice_date: "2026-10-20", po_nos: "PO/2026/10/00009", do_nos: "DO/2026/10/00009", amount: 1000000, checklist: checklistFull },
    { id: "i2", supplier_name: "PT. ABC", invoice_no: "INV/2026/002", tax_invoice_no: "", tax_invoice_date: "", po_nos: "PO/2026/10/00010", do_nos: "", amount: 500000, checklist: checklistPartial },
  ],
};

const h = buildTransmittalHtml({ doc, company: { name: "PT. Rajawali Emas Ancora Lestari", address: "Yard Balai Raja" }, autoPrint: false });

check("judul & nomor transmittal", h.includes("TRANSMITTAL INVOICE") && h.includes("TRN/2026/10/00007"));
check("tanggal panjang Indonesia", h.includes("23 Oktober 2026"));
check("tujuan, pengirim, penerima, status", h.includes("Finance &amp; Accounting") && h.includes("Agus Prasetyo") && h.includes("Melda Sari") && h.includes("Dikirim"));
check("jumlah invoice & total nilai (incl. PPN)", h.includes(">2<") && h.includes("1.500.000"));
check("baris vendor + no invoice + faktur pajak + PO", h.includes("PT. Riau Indo Pasifik") && h.includes("INV/2026/001") && h.includes("010.000-26.00000001") && h.includes("PO/2026/10/00009"));
check("nilai per invoice + total footer", h.includes("1.000.000") && h.includes("500.000") && h.includes("TOTAL"));
check("checklist lengkap vs belum lengkap (jumlah dokumen kurang)", h.includes("Lengkap") && h.includes("Belum Lengkap (2)"));
check("keterangan tercetak", h.includes("Mohon dicek kelengkapan faktur pajak."));
check("area tanda tangan pengirim & penerima", h.includes("Dikirim oleh,") && h.includes("Diterima oleh,") && h.includes("Tanggal: 23/10/2026"));
check("A4 portrait & margin cetak", h.includes("@page{size:A4 portrait;margin:12mm}"));
check("autoPrint=false tidak memicu window.print", !h.includes("window.print()"));
check("autoPrint=true memicu window.print", buildTransmittalHtml({ doc, company: {}, autoPrint: true }).includes("window.print()"));
check("HTML di-escape (tidak ada tag mentah dari input)", !buildTransmittalHtml({ doc: { ...doc, destination: "<script>alert(1)</script>" }, company: {}, autoPrint: false }).includes("<script>alert(1)</script>"));

// checklistSummary: Tidak Berlaku tidak dihitung wajib; kosong -> semua Belum Lengkap
const sumFull = checklistSummary(checklistFull);
check("ringkasan checklist: Lengkap semua yang wajib", sumFull.complete && sumFull.done === sumFull.required && sumFull.required === 5, sumFull);
const sumPartial = checklistSummary(checklistPartial);
check("ringkasan checklist: mendeteksi 2 dokumen belum lengkap", !sumPartial.complete && sumPartial.pending.length === 2, sumPartial.pending);
const sumEmpty = checklistSummary(emptyChecklist());
check("invoice tanpa checklist -> belum lengkap semua (8 wajib)", !sumEmpty.complete && sumEmpty.required === 8, sumEmpty);

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
