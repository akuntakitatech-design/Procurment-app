// Uji cetak PO template REAL (acuan FORM PO PAKAI DP manual). Murni HTML (tanpa jaringan). Jalankan:
//   cd /app/frontend && npx esbuild tests/po_print_real_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=/tmp/po_print_real.cjs --log-level=error && node /tmp/po_print_real.cjs
import { realPoHtml, buildPoPrintHtml, poSpkCell, renderTermsMessage } from "../src/lib/print.js";
import { APPROVED_PO_STATUSES } from "../src/lib/poPrintReal.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };
const layout = { show_message: true, show_signatures: true, show_qr: false, font_size: 11, margin_mm: 10, paper_size: "A4", footer_text: "Gedung Uji, Lt. 20\nPhone: 021-000" };
const SIG = "data:image/png;base64,SIG";
const grp = "04|NORMAL|12|11|12";
// Nilai TERSIMPAN Tax Engine v2 (replika PO manual): sengaja dibaca apa adanya, cetak tidak menghitung ulang.
const v2 = { no: "PO/115/VII/OMSS/2026", date: "2026-07-23", status: "Approved", tax_engine_version: 2, supplier_name: "PT Supplier Uji", supplier_ref: "785/Q/VII/2026",
  buyer_contact_name: "Buyer Uji", buyer_contact_phone: "0812", payment_term: "N-30", delivery_term: "H+30 Setelah PO",
  gross_total: 267900000, item_discount_total: 0, final_discount_amount: 0, subtotal_after_discount: 267900000, dpp_total: 267900000, non_ppn_total: 0,
  dpp_other_total: 245575000, tax_total: 29469000, tax_facility_total: 0, ppnbm_total: 0, grand_total: 297369000,
  tax_groups: [{ group: grp, trx_code: "04", dpp: 267900000, dpp_other: 245575000, ppn: 29469000, ppn_facility: 0 }], tax_rules_snapshot: [{ group: grp, tax_rate: 12, tax_dpp_factor_num: 11, tax_dpp_factor_den: 12 }],
  dp_enabled: true, dp_type: "percentage", dp_value: 40, dp_amount: 118947600, dp_remaining: 178421400,
  approvals: [{ seq: 1, status: "Approved", acted_by: "Approver L1" }, { seq: 2, status: "Approved", acted_by: "Approver L2" }],
  document_message: "Term and Condition\n1 Barang wajib dikirim 7 hari\n\nCatatan\n1 Invoice dilampiri:\n* Faktur Pajak (Jika PKP)",
  lines: [
    { id: "a", item_name: 'Smith Clamp 14"', qty: 30, price: 980000, discount: 0, dpp: 29400000, display_unit: "Ea", tax_mode: "EXCLUDE", tax_code: "P04", tax_name: "PPN DPP Nilai Lain", tax_trx_code: "04", mro_refs: ["2248"], ro_refs: [{ ro_no: "RO/1" }] },
    { id: "b", item_name: 'Smith Clamp 20"', qty: 50, price: 1140000, discount: 0, dpp: 57000000, display_unit: "Ea", tax_mode: "EXCLUDE", tax_code: "P04", tax_trx_code: "04", mro_refs: ["2248"], ro_refs: [{ ro_no: "RO/1" }] },
    { id: "c", item_name: 'Smith Clamp 24"', qty: 150, price: 1210000, discount: 0, dpp: 181500000, display_unit: "Ea", tax_mode: "EXCLUDE", tax_code: "P04", tax_trx_code: "04", mro_refs: ["2248"], ro_refs: [{ ro_no: "RO/1" }] }] };
const H = (doc, o = {}) => realPoHtml({ doc, company: { name: "PT. Rajawali Emas Ancora Lestari", address: "Yard Balai Raja" }, layout: { ...layout, ...(o.layout || {}) },
  logoImg: "data:image/png;base64,LOGO", supplier: { name: "PT Supplier Uji", contacts: [{ name: "Marketing Uji", phone: "0822", is_primary: true }], banks: [{ bank_name: "Bank Mandiri", account_no: "172-000", account_name: "PT Supplier Uji", is_primary: true }] },
  project: { name: "WUR-MD" }, signatureImg: SIG, showPrice: o.showPrice ?? true, internal: !!o.internal, autoPrint: o.autoPrint ?? false });
const sum = (h) => [...h.matchAll(/data-sum="([^"]+)">[\s\S]*?<td class="sum-label" colspan="2">([\s\S]*?)<\/td><td class="sum-value">([^<]*)<\/td>/g)].map((m) => [m[1], m[2].replace(/<[^>]+>/g, "").trim(), m[3]]);

// ---------------------------------------------------------------- struktur & desain manual
const h = H(v2);
check("A4 portrait + margin aman printer (atas/bawah 12 mm, kiri/kanan 15 mm) walau layout 10 mm", h.includes("@page{size:A4 portrait;margin:12mm 15mm}") && h.includes("@media screen{body{padding:12mm 15mm}}"));
check("margin layout lebih besar dari batas aman tetap dipakai", realPoHtml({ doc: v2, company: {}, layout: { ...layout, margin_mm: 18 }, showPrice: true, autoPrint: false }).includes("@page{size:A4 portrait;margin:18mm 18mm}"));
check("teks & garis hitam formal (bukan warna tema)", /body\{color:#000;/.test(h) && h.includes(".25mm solid #000"));
check("header: logo, nama perusahaan, judul PURCHASE ORDER", h.includes('class="real-logo" src="data:image/png;base64,LOGO"') && h.includes('<div class="brand-name">PT. Rajawali Emas Ancora Lestari</div>') && h.includes('<div class="po-title">PURCHASE ORDER</div>'));
check("Delivery To + Project + Bill To", h.includes("Please Delivery to :") && h.includes("Project WUR-MD") && h.includes("Please Bill to :"));
check("kotak meta berbingkai + catatan nomor PO seperti manual", h.includes(".meta-box{border:.3mm solid #000") && h.includes("This PO Number must appear on all invoices.") && h.includes("Packing list delivery orders."));
check("meta: PO No, tanggal panjang ID, supplier ref, buyer, marketing, terms", ["PO/115/VII/OMSS/2026", "23 Juli 2026", "785/Q/VII/2026", "Buyer Uji", "Marketing Uji", "N-30", "H+30 Setelah PO"].every((x) => h.includes(x)));
check("kolom tabel = manual: No | Description | No. SPK | Qty(2) | Price | Discount | Amount", h.includes('<thead><tr><th>No</th><th>Description</th><th>No. SPK</th><th colspan="2">Qty</th><th>Price</th><th>Discount</th><th>Amount<div class="th-sub">sebelum PPN</div></th></tr></thead>'));
check("header tabel berulang per halaman, garis penutup berulang, ringkasan TIDAK berulang (tabel terpisah)", h.includes(".items thead{display:table-header-group}.items tfoot.page-close{display:table-footer-group}") && h.includes('<tfoot class="page-close">') && h.includes('<table class="items sums keep" data-section="summary">') && !/<tfoot>[\s\S]*data-sum=/.test(h));
check("penanda halaman lanjutan (hal. 2 dst.) memuat No. PO; halaman 1 bersih", h.includes('@top-right{content:"PO/115/VII/OMSS/2026  ·  Halaman " counter(page)') && h.includes("@page:first{@top-right{content:none}}"));
check("No. PO berisi tanda kutip tidak merusak CSS halaman", !realPoHtml({ doc: { ...v2, no: 'PO"X\\Y' }, company: {}, layout, showPrice: true, autoPrint: false }).includes('content:"PO"X'));
check("baris grup referensi hanya MRO (\"MRO 2248\"), nomor RO tidak dicetak", h.includes('<td class="grp-label" colspan="2">MRO 2248</td>') && !h.includes("RO/1"));
check("harga tanpa 'Rp', diskon kosong '-', amount = DPP baris tersimpan", h.includes('<td class="r price">980.000</td><td class="r discount">-</td><td class="r amount">29.400.000</td>'));
check("rekening, Approved by / Signed by, footer alamat multi-baris", h.includes("Pembayaran dilakukan ke Rekening :") && h.includes("172-000") && h.includes("Approved by,") && h.includes("Signed by,") && h.includes('<div class="page-footer">Gedung Uji, Lt. 20<br/>Phone: 021-000</div>'));
check("syarat: heading tebal, nomor gantung, butir *", h.includes('<div class="term-heading">Term and Condition</div>') && h.includes('<span class="term-no">1</span><span class="term-text">Barang wajib dikirim 7 hari</span>') && h.includes('<div class="term-item bullet"><span class="term-no">*</span><span class="term-text">Faktur Pajak (Jika PKP)</span>'));
check("SPK header disisipkan sebelum Catatan (perilaku existing)", renderTermsMessage("Term and Condition\n1 a\nCatatan\n1 b", "SPK-9").indexOf("SPK : SPK-9") < renderTermsMessage("Term and Condition\n1 a\nCatatan\n1 b", "SPK-9").indexOf("Catatan"));
check("autoPrint default true (cetak dari aplikasi), false untuk pratinjau", realPoHtml({ doc: v2, company: {}, layout, showPrice: true }).includes("window.print()") && !h.includes("window.print()"));

// ---------------------------------------------------------------- nilai = Tax Engine tersimpan (manual: Total, DPP, PPN 12%, Grand Total, DP 40%, Sisa)
const s = sum(h);
check("ringkasan v2 sesuai manual (tanpa diskon: baris Total Harga Sebelum Diskon dilebur)", JSON.stringify(s.map((r) => r[1])) === JSON.stringify(["Nilai Pembelian Sebelum PPN", "DPP Nilai Lain", "PPN 12%", "Grand Total", "DP 40%", "Sisa Pembayaran"]), s);
check("angka ringkasan identik nilai tersimpan", JSON.stringify(s.map((r) => r[2])) === JSON.stringify(["267.900.000", "245.575.000", "29.469.000", "297.369.000", "118.947.600", "178.421.400"]), s);
const odd = { ...v2, tax_total: 1, grand_total: 2, dp_amount: 3, dp_remaining: 4 };
check("cetak TIDAK menghitung ulang: nilai tersimpan apa pun ditampilkan apa adanya", JSON.stringify(sum(H(odd)).filter((r) => ["ppn", "grand", "dp", "remaining"].includes(r[0])).map((r) => r[2])) === '["1","2","3","4"]');
check("objek doc tidak dimutasi oleh cetak", (() => { const d = JSON.parse(JSON.stringify(v2)); H(d); buildPoPrintHtml({ doc: d, allocLines: [], company: {}, layout }); return JSON.stringify(d) === JSON.stringify(v2); })());

// ---------------------------------------------------------------- variasi pajak & DP
const inc = { ...v2, dp_enabled: false, gross_total: 1000000, subtotal_after_discount: 1000000, dpp_total: 892857.14, dpp_other_total: 0, tax_total: 107142.86, grand_total: 1000000,
  tax_groups: [{ group: "01|NORMAL|12|1|1", dpp: 892857.14, dpp_other: 892857.14, ppn: 107142.86 }], tax_rules_snapshot: [{ group: "01|NORMAL|12|1|1", tax_rate: 12 }],
  lines: [{ id: "x", item_name: "Oli", qty: 1, price: 1000000, dpp: 892857.14, tax_mode: "INCLUDE", tax_code: "P01", tax_name: "PPN 12%", tax_trx_code: "01" }] };
const hi = H(inc), si = sum(hi);
check("PPN Include: 'Total Setelah Diskon' (harga termasuk PPN) + Nilai Sebelum PPN + PPN 12%", si.some((r) => r[0] === "after_disc" && /harga Include sudah termasuk PPN/.test(r[1])) && si.some((r) => r[0] === "before_ppn" && r[2] === "892.857,14") && si.some((r) => r[1] === "PPN 12%"), si);
check("tanpa DP: tidak ada baris DP / Sisa Pembayaran", !hi.includes("Sisa Pembayaran") && !hi.includes('data-sum="dp"'));
check("tidak ada keterangan Include/Exclude/Tanpa PPN per barang", !hi.includes("tax-note") && !/Include ·|Exclude ·|· PPN/.test(hi) && !h.includes("tax-note"));
const none = { ...inc, dpp_total: 0, non_ppn_total: 500000, tax_total: 0, grand_total: 500000, gross_total: 500000, subtotal_after_discount: 500000, tax_groups: [], tax_rules_snapshot: [],
  lines: [{ id: "y", item_name: "Jasa", qty: 1, price: 500000, dpp: 500000, tax_mode: "NONE" }] };
const sn = sum(H(none));
check("Tanpa PPN: PPN 0, label 'PPN', tanpa rincian kelompok", sn.some((r) => r[0] === "ppn" && r[1] === "PPN" && r[2] === "0") && !H(none).includes("Rincian Pajak per Kelompok") && !H(none).includes("tax-note"), sn);
const combo = { ...v2, dp_type: "nominal", dp_value: 25000000, dp_amount: 25000000, dp_remaining: 2394920, item_discount_total: 200000, final_discount_amount: 545000, gross_total: 27450000, subtotal_after_discount: 26705000,
  dpp_total: 25056500, non_ppn_total: 735000, dpp_other_total: 23602833.33, tax_total: 1603420, tax_facility_total: 1228920, grand_total: 27394920, payment_notes: "DP 7 hari kerja",
  tax_groups: [{ group: grp, trx_code: "04", dpp: 6272000, dpp_other: 5749333.33, ppn: 689920 }, { group: "01|NORMAL|12|1|1", trx_code: "01", dpp: 7612500, dpp_other: 7612500, ppn: 913500 }, { group: "07|TIDAK_DIPUNGUT|12|11|12", trx_code: "07", facility: "TIDAK_DIPUNGUT", dpp: 11172000, dpp_other: 10241000, ppn: 0, ppn_facility: 1228920 }],
  tax_rules_snapshot: [{ group: grp, tax_rate: 12 }, { group: "01|NORMAL|12|1|1", tax_rate: 12 }, { group: "07|TIDAK_DIPUNGUT|12|11|12", tax_rate: 12 }] };
const hc = H(combo), sc = sum(hc);
check("kombinasi: diskon item/final, Tanpa PPN, fasilitas, PPN 12% (tarif tunggal)", ["gross", "item_disc", "final_disc", "after_disc", "before_ppn", "non_ppn", "dpp_other", "ppn", "ppn_facility", "grand", "dp", "remaining"].every((k) => sc.some((r) => r[0] === k)) && sc.find((r) => r[0] === "ppn")[1] === "PPN 12%", sc.map((r) => r[0]));
check("kombinasi: rincian pajak per kelompok tampil (04, 01, 07 tidak ditagih, Barang Tanpa PPN)", hc.includes("Rincian Pajak per Kelompok") && hc.includes("(Kode 07) — tidak ditagih") && hc.includes("Barang Tanpa PPN"));
check("kombinasi: rincian pajak di area kosong kiri ringkasan (sel spacer rowspan), bukan blok terpisah", /<td class="sum-spacer" colspan="5" rowspan="\d+"><div class="tax-groups keep" data-section="tax-groups">/.test(hc) && (hc.match(/data-section="tax-groups"/g) || []).length === 1);
check("DP nominal: label 'DP' + nilai tersimpan + Ketentuan Pembayaran (catatan)", sc.find((r) => r[0] === "dp")[1] === "DP" && sc.find((r) => r[0] === "remaining")[2] === "2.394.920" && hc.includes("Ketentuan Pembayaran") && hc.includes("DP 7 hari kerja"));
check("PPN tunggal 1 kelompok: rincian kelompok tidak diulang (sudah di ringkasan)", !h.includes("Rincian Pajak per Kelompok"));
const v1 = { no: "PO-LAMA", status: "Approved", grand_total: 6660, subtotal_after_discount: 6000, lines: [{ item_name: "A", qty: 2, price: 3000, tax: 11, tax_amount: 660 }] };
check("PO lama (v1): ringkasan & angka seperti sebelumnya (PPN 11%)", JSON.stringify(sum(H(v1)).map((r) => [r[1], r[2]])) === JSON.stringify([["Total Harga Sebelum Diskon", "6.000"], ["Total Setelah Diskon", "6.000"], ["PPN 11%", "660"], ["Grand Total", "6.660"]]), sum(H(v1)));

// ---------------------------------------------------------------- izin harga & internal
const hp = H(v2, { showPrice: false });
check("tanpa izin harga: tidak ada angka harga/pajak/DP sama sekali", !["980.000", "29.400.000", "297.369.000", "118.947.600", "Sisa Pembayaran", "Grand Total", "<th>Price</th>"].some((x) => hp.includes(x)) && hp.includes("<th>Keterangan</th>") && hp.includes("Uang Muka (DP) disyaratkan"));
const ov = { ...v2, lines: [{ ...v2.lines[0], price_status: "Price Override", price_change_reason: "harga naik", contract_price_snapshot: 900000 }] };
check("catatan perubahan harga hanya di cetak internal", H(ov, { internal: true }).includes("Catatan Perubahan Harga (Internal)") && !H(ov).includes("Catatan Perubahan Harga"));

// ---------------------------------------------------------------- No. SPK dari alokasi tahap PO
check("No. SPK: satu SPK penuh -> nomor SPK", poSpkCell({ allocations: [{ spk_number: "SPK/1", allocated_qty: 10 }], non_spk_qty: 0 }) === "SPK/1");
check("No. SPK: campuran -> qty per SPK + Non-SPK (baris terpisah)", poSpkCell({ allocations: [{ spk_number: "SPK/1", allocated_qty: 25 }], non_spk_qty: 15 }) === "SPK/1 (25)\nNon-SPK (15)");
check("No. SPK: tanpa alokasi -> kosong (seperti manual)", poSpkCell(null) === "" && poSpkCell({ allocations: [], non_spk_qty: 5 }) === "");
const hb = buildPoPrintHtml({ doc: v2, allocLines: [{ item_line_id: "a", allocations: [{ spk_number: "SPK/1", allocated_qty: 30 }], non_spk_qty: 0 }], company: {}, layout, showPrice: true, autoPrint: false });
check("buildPoPrintHtml: No. SPK tampil pada baris yang dialokasikan saja", hb.includes('<td class="c spk">SPK/1</td>') && (hb.match(/<td class="c spk"><\/td>/g) || []).length === 2);

// ---------------------------------------------------------------- status approval -> watermark DRAFT & TTD/stempel (logika existing)
for (const st of ["Draft", "Waiting Approval", "Rejected", "Cancelled", ""]) {
  const x = H({ ...v2, status: st });
  check(`status '${st || "(kosong)"}': watermark DRAFT, tanpa TTD/stempel`, x.includes('<div class="draft-watermark">DRAFT</div>') && !x.includes(SIG));
}
for (const st of ["Approved", "Partially Received", "Fully Received", " approved "]) {
  const x = H({ ...v2, status: st });
  check(`status '${st}': tanpa watermark, TTD/stempel tampil`, !x.includes('class="draft-watermark"') && x.includes(`<img class="approved-signature" src="${SIG}"`));
}
check("himpunan status final-approved tidak berubah", [...APPROVED_PO_STATUSES].join() === "approved,partially received,fully received");
check("nama Approved by = approver terakhir yang approve (logika existing), override layout tetap dihormati", h.includes('<div class="sign-name">Approver L2</div>') && H(v2, { layout: { po_approved_name: "Direksi" } }).includes('<div class="sign-name">Direksi</div>'));
check("Approved tanpa file TTD: tidak ada gambar", !realPoHtml({ doc: v2, company: {}, layout, showPrice: true, signatureImg: "", autoPrint: false }).includes("approved-signature\" src"));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
