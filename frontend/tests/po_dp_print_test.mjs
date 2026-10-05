// Uji print PO DP (realPoHtml + template generik via dpRows). Jalankan:
//   cd /app/frontend && npx esbuild tests/po_dp_print_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=/tmp/po_dp_print.cjs --log-level=error && node /tmp/po_dp_print.cjs
import { realPoHtml } from "../src/lib/print.js";
import { computeDp, dpRows } from "../src/lib/poDp.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };
const layout = { show_message: true, show_signatures: false, show_qr: false, primary_color: "#123" };
const base = { no: "PO-2026-0001", status: "Approved", grand_total: 297369000, subtotal_after_discount: 267900000, lines: [
  { item_name: "Barang A", qty: 1, price: 267900000, dpp: 267900000, tax: 11, tax_amount: 29469000 }] };
const html = (doc) => realPoHtml({ doc, company: { name: "PT Uji" }, layout, supplier: {}, project: {}, showPrice: true, internal: false });
const grandIdx = (h) => h.indexOf("Grand Total");

const pct = { ...base, dp_enabled: true, dp_type: "percentage", dp_value: 40, dp_amount: 118947600, dp_remaining: 178421400, payment_notes: "DP dibayar 7 hari setelah PO." };
const hp = html(pct);
check("print %: baris DP 40% setelah Grand Total", hp.includes("DP 40%") && hp.indexOf("DP 40%") > grandIdx(hp) && /118[.,]947[.,]600/.test(hp));
check("print %: Sisa Pembayaran 178.421.400", hp.includes("Sisa Pembayaran") && /178[.,]421[.,]400/.test(hp) && hp.indexOf("Sisa Pembayaran") > hp.indexOf("DP 40%"));
check("print: Keterangan Pembayaran tampil", hp.includes("Ketentuan Pembayaran") && hp.includes("DP dibayar 7 hari setelah PO."));

const nom = { ...base, dp_enabled: true, dp_type: "nominal", dp_value: 100000000, dp_amount: 100000000, dp_remaining: 197369000 };
const hn = html(nom);
check("print nominal: label 'DP' tanpa persen + 100.000.000", />DP<\/td>/.test(hn) && !/DP \d/.test(hn) && /100[.,]000[.,]000/.test(hn));
check("print nominal: Sisa Pembayaran 197.369.000", /197[.,]369[.,]000/.test(hn));
check("print nominal tanpa keterangan: blok Ketentuan Pembayaran tidak muncul", !hn.includes("Ketentuan Pembayaran"));

const none = { ...base, dp_enabled: false };
const h0 = html(none);
check("print tanpa DP: tidak ada baris DP / Sisa Pembayaran", !h0.includes("Sisa Pembayaran") && !h0.includes('class="dp-row"') && h0.includes("Grand Total"));
const old = { ...base };  // PO lama tanpa field DP
check("print PO lama tanpa field DP: tanpa baris DP", !html(old).includes("Sisa Pembayaran"));
check("print tanpa izin harga: tidak ada nilai DP", !realPoHtml({ doc: pct, company: {}, layout, supplier: {}, project: {}, showPrice: false }).includes("Sisa Pembayaran"));

const dec = { ...base, dp_enabled: true, dp_type: "percentage", dp_value: 12.5, dp_amount: 37171125, dp_remaining: 260197875 };
check("print %: persen desimal 12,5%", html(dec).includes("DP 12,5%"));
check("dpRows generik: 2 baris DP + Sisa", dpRows(pct).length === 2 && dpRows(none).length === 0 && dpRows(old).length === 0);

// pratinjau form = engine backend
const p = computeDp({ dp_enabled: true, dp_type: "percentage", dp_value: 40 }, 297369000);
check("pratinjau %: 118.947.600 / 178.421.400", p.amount === 118947600 && p.remaining === 178421400, p);
const n = computeDp({ dp_enabled: true, dp_type: "nominal", dp_value: 100000000 }, 297369000);
check("pratinjau nominal: 100.000.000 / 197.369.000", n.amount === 100000000 && n.remaining === 197369000, n);
check("pratinjau nominal > Grand Total: pesan blokir", computeDp({ dp_enabled: true, dp_type: "nominal", dp_value: 300000000 }, 297369000).error === "Nilai DP tidak boleh melebihi Grand Total PO.");
check("pratinjau % > 100 / 0 / negatif invalid", [101, 0, -5].every((v) => !!computeDp({ dp_enabled: true, dp_type: "percentage", dp_value: v }, 1000).error));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
