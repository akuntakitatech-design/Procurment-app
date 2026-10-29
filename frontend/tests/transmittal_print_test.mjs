// Uji template cetak Transmittal Invoice (murni HTML, tanpa jaringan).
// Jalankan: cd frontend && npx esbuild tests/transmittal_print_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=./tmp-transmittal.cjs --log-level=error && node ./tmp-transmittal.cjs
import { buildTransmittalHtml, buildTransmittalMultiHtml, checklistMark, PRINT_CHECKLIST, MIN_ROWS } from "../src/lib/transmittalPrint.js";
import { checklistSummary, emptyChecklist } from "../src/lib/docChecklist.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };

const full = { invoice: "Lengkap", faktur_pajak: "Lengkap", po: "Lengkap", do: "Lengkap", bukti_penerimaan: "Lengkap", kwitansi: "Lengkap", bast: "Tidak Berlaku", kontrak: "Tidak Berlaku" };
const partial = { ...full, do: "Belum Lengkap", bukti_penerimaan: "Belum Lengkap", bast: "Belum Lengkap" };

const doc = {
  no: "TRN/2026/10/00007", date: "2026-10-23", status: "Dikirim", destination: "Finance & Accounting",
  sender_name: "Agus Prasetyo", receiver_name: "Melda Sari", notes: "Mohon dicek kelengkapan faktur pajak.",
  sent_at: "2026-10-23T09:15:00+00:00", total_amount: 1500000,
  items: [
    { id: "i1", supplier_name: "PT. PROFITA ABADI", invoice_no: "PA/DO/897654", tax_invoice_no: "44423675618930", po_nos: "PO/REAL/26/10/000551", do_nos: "DO/2026/10/00003", do_supplier_nos: "121336", amount: 1000000, checklist: full },
    { id: "i2", supplier_name: "PT. ABC", invoice_no: "INV/2026/002", tax_invoice_no: "", po_nos: "PO/2026/10/00010", do_nos: "DO/2026/10/00004", do_supplier_nos: "", amount: 500000, checklist: partial },
  ],
};

const LOGO = "data:image/png;base64,LOGO";
const h = buildTransmittalHtml({ doc, company: { name: "PT. Rajawali Emas Ancora Lestari", address: "Yard Balai Raja" }, logoImg: LOGO, autoPrint: false });

// --- Kop sesuai form manual "Pengiriman Transmittal Invoice"
check("kop: Pengiriman Transmittal Invoice + Vendor Proyek PHR", h.includes("Pengiriman Transmittal Invoice") && h.includes("Vendor Proyek PHR"));
check("kop: nomor transmittal tercetak", h.includes("TRN/2026/10/00007"));
check("tanggal panjang Indonesia", h.includes("Tanggal : 23 Oktober 2026"));
check("nama & alamat perusahaan", h.includes("PT. Rajawali Emas Ancora Lestari") && h.includes("Yard Balai Raja"));
check("logo tampil di atas nama perusahaan", h.includes(`<img class="logo" src="${LOGO}"`) && h.indexOf('class="logo"') < h.indexOf('class="company-name"'));
check("tanpa logo: tidak ada <img> logo", !buildTransmittalHtml({ doc, company: {}, logoImg: "", autoPrint: false }).includes('class="logo"'));

// --- Info: Pengirim & Penerima DIBIARKAN KOSONG (diisi manual setelah cetak)
check("info: Tujuan / Departemen tercetak", h.includes("Tujuan / Departemen") && h.includes("Finance &amp; Accounting"));
check("info: Pengirim & Penerima kosong (diisi manual)", /Pengirim<\/span><span class="val"><\/span>/.test(h)
  && /Penerima<\/span><span class="val"><\/span>/.test(h) && !h.includes("Agus Prasetyo") && !h.includes("Melda Sari"));
check("Total Invoice = JUMLAH invoice (bukan nominal)", /Total Invoice<\/span><span class="val">2<\/span>/.test(h));
check("status internal tidak dicetak", !h.includes(">Dikirim<"));

// --- Kolom sesuai form
check("kolom: Nama Vendor, No. Invoice, No. Faktur Pajak, No. PO",
  ["Nama Vendor", "No. Invoice", "No. Faktur Pajak", "No. PO"].every((x) => h.includes(x)));
check("header kelompok Item Pemeriksaan Kelengkapan (3 kolom)", h.includes("Item Pemeriksaan Kelengkapan") && h.includes('colspan="3"'));
check("sub-kolom: No DO Sistem, No. DO Supplier, Nilai (Inc PPN)",
  ["No DO Sistem", "No. DO Supplier", "Nilai (Inc PPN)"].every((x) => h.includes(x)));
check("kolom lama 'Bukti Penerimaan Barang' & 'No DO SUPLIER' sudah tidak ada",
  !h.includes("Bukti Penerimaan Barang (PT. REAL)") && !h.includes("No DO SUPLIER"));
check("kolom ✓: Kwitansi, BAST / Timesheet, Kontrak Kerja (Subcon)",
  ["Kwitansi", "BAST / Timesheet", "Kontrak Kerja (Subcon)"].every((x) => h.includes(x)));
check("PRINT_CHECKLIST = 3 tanda ✓", PRINT_CHECKLIST.map((x) => x.key).join() === "kwitansi,bast,kontrak", PRINT_CHECKLIST.map((x) => x.key));

// --- Simbol checklist
check("simbol: Lengkap = ✓, Belum Lengkap = ✗, Tidak Berlaku = −",
  checklistMark("Lengkap") === "✓" && checklistMark("Belum Lengkap") === "✗" && checklistMark("Tidak Berlaku") === "−");
const marks = (h.match(/class="mark">([^<]+)</g) || []).map((m) => m.replace(/.*>/, "").replace("<", ""));
check("jumlah simbol sesuai data: 2 ✓, 1 ✗, 3 −", marks.filter((m) => m === "✓").length === 2
  && marks.filter((m) => m === "✗").length === 1 && marks.filter((m) => m === "−").length === 3, marks);

// --- Data & format
check("baris vendor + no invoice + faktur pajak + PO",
  h.includes("PT. PROFITA ABADI") && h.includes("PA/DO/897654") && h.includes("44423675618930") && h.includes("PO/REAL/26/10/000551"));
check("No DO Sistem = nomor DO sistem (DO/2026/10/00003)", h.includes("DO/2026/10/00003"));
check("No. DO Supplier = nomor surat jalan supplier (121336)", h.includes("121336"));
check("nilai diformat ribuan koma (1,000,000 & 500,000)", h.includes("1,000,000") && h.includes("500,000"));
check("tidak ada baris TOTAL nominal (form manual tanpa total)", !h.includes("1,500,000"));
check("keterangan tercetak bila diisi", h.includes("Mohon dicek kelengkapan faktur pajak."));
check("tanpa catatan -> blok Keterangan tidak muncul", !buildTransmittalHtml({ doc: { ...doc, notes: "" }, company: {}, autoPrint: false }).includes('class="notes"'));

// --- Baris kosong bernomor sampai minimal 7 baris
const rowCount = (html) => (html.match(/<tr class="row">/g) || []).length;
check(`minimal ${MIN_ROWS} baris bernomor (2 data + 5 kosong)`, MIN_ROWS === 7 && rowCount(h) === 7, rowCount(h));
check("nomor baris terakhir = 7", h.includes('<td class="c">7</td>'));
check("dokumen tanpa invoice tetap 7 baris kosong",
  rowCount(buildTransmittalHtml({ doc: { ...doc, items: [] }, company: {}, autoPrint: false })) === 7);

// --- Tanda tangan: Nama & Tanggal DIBIARKAN KOSONG
check("tanda tangan Dikirim/Diterima tercetak", h.includes("Dikirim Oleh,") && h.includes("Diterima Oleh,"));
check("Nama & Tanggal pada tanda tangan kosong (diisi manual)",
  (h.match(/Nama :<\/div>/g) || []).length === 2 && (h.match(/Tanggal :<\/div>/g) || []).length === 2);

// --- Cetak
check("A4 landscape & margin cetak", h.includes("@page{size:A4 landscape;margin:10mm}"));
check("autoPrint=false tidak memicu window.print", !h.includes("window.print()"));
check("autoPrint=true memicu window.print", buildTransmittalHtml({ doc, company: {}, autoPrint: true }).includes("window.print()"));
check("HTML di-escape (tidak ada tag mentah dari input)",
  !buildTransmittalHtml({ doc: { ...doc, destination: "<script>alert(1)</script>" }, company: {}, autoPrint: false }).includes("<script>alert(1)</script>"));

// --- Ringkasan checklist
const sumFull = checklistSummary(full);
check("ringkasan checklist: Lengkap semua yang wajib", sumFull.complete && sumFull.done === sumFull.required && sumFull.required === 6, sumFull);
const sumPartial = checklistSummary(partial);
check("ringkasan checklist: mendeteksi 3 dokumen belum lengkap", !sumPartial.complete && sumPartial.pending.length === 3, sumPartial.pending);
const sumEmpty = checklistSummary(emptyChecklist());
check("invoice tanpa checklist -> belum lengkap semua (8 wajib)", !sumEmpty.complete && sumEmpty.required === 8, sumEmpty);

// --- Export PDF massal: satu halaman per transmittal
const doc2 = { ...doc, no: "TRN/2026/10/00008", destination: "Gudang", items: [] };
const multi = buildTransmittalMultiHtml({ docs: [doc, doc2], autoPrint: false, logoImg: LOGO });
check("multi: dua bagian dokumen + semua nomor tercetak",
  (multi.match(/<section class="doc">/g) || []).length === 2 && multi.includes("TRN/2026/10/00007") && multi.includes("TRN/2026/10/00008"));
check("multi: satu transmittal per halaman (page break)", multi.includes(".doc + .doc{break-before:page;page-break-before:always}"));
check("multi: judul ringkas jumlah dokumen", multi.includes("<title>Transmittal Invoice (2)</title>"));
check("multi: 2 halaman x 7 baris bernomor", rowCount(multi) === 14, rowCount(multi));
check("multi: satu window.print untuk seluruh halaman",
  (buildTransmittalMultiHtml({ docs: [doc, doc2], autoPrint: true }).match(/window\.print\(\)/g) || []).length === 1);
check("multi: escaping tetap berlaku",
  !buildTransmittalMultiHtml({ docs: [{ ...doc, destination: "<b>x</b>" }], autoPrint: false }).includes("<b>x</b>"));
check("multi: landscape sama dengan cetak tunggal", buildTransmittalMultiHtml({ docs: [doc], autoPrint: false }).includes("@page{size:A4 landscape;margin:10mm}"));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
