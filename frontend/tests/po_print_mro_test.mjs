// Uji cetak PO: nomor MRO di atas nama barang (kolom Description). Jalankan:
//   cd /app/frontend && npx esbuild tests/po_print_mro_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=/tmp/po_print_mro.cjs --log-level=error && node /tmp/po_print_mro.cjs
import { realPoHtml, poDescCell } from "../src/lib/print.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };
const layout = { show_message: true, show_signatures: true, show_qr: false, primary_color: "#123", font_size: 11 };
const L = (o) => ({ qty: 2, price: 1000, dpp: 2000, tax: 11, tax_amount: 220, notes: "Spek A", display_unit: "PCS", ...o });
const doc = { no: "PO/2026/10/00001", status: "Approved", grand_total: 6660, subtotal_after_discount: 6000, lines: [
  L({ item_name: "Bearing 6205", mro_refs: ["MRO/2026/10/00001"] }),
  L({ item_name: "Seal Kit", mro_refs: ["MRO/2026/10/00003", "MRO/2026/10/00002", "MRO/2026/10/00003", ""] }),
  L({ item_name: "Oli <SAE> 40" })] };
const html = (d, showPrice = true) => realPoHtml({ doc: d, company: { name: "PT Uji" }, layout, supplier: {}, project: {}, showPrice, internal: false });
const descCells = (h) => [...h.matchAll(/<td class="desc">([\s\S]*?)<\/td>/g)].map((m) => m[1]);

const h = html(doc);
const [one, multi, none] = descCells(h);
check("1 MRO: nomor MRO tampil di atas nama barang", one === '<div class="mro-ref">MRO/2026/10/00001</div><div class="item-name">Bearing 6205</div>', one);
check("multi-MRO: semua nomor tampil, tanpa duplikasi/kosong (urutan dari backend dipertahankan)", multi === '<div class="mro-ref">MRO/2026/10/00003, MRO/2026/10/00002</div><div class="item-name">Seal Kit</div>', multi);
check("tanpa MRO: nama barang seperti biasa (identik template lama, tetap di-escape)", none === "Oli &lt;SAE&gt; 40", none);
check("tanpa MRO: mro_refs kosong [] juga identik", poDescCell({ item_name: "X", mro_refs: [] }) === "X");
check("nomor MRO di-escape", poDescCell({ item_name: "X", mro_refs: ["<b>"] }).includes("&lt;b&gt;"));
check("font MRO lebih kecil dari nama barang (11px -> 8px), tetap terbaca (min 7px)",
  /\.items \.desc \.mro-ref\{font-size:8px;/.test(h) && /font-size:11px/.test(h), (h.match(/\.mro-ref\{[^}]*\}/) || [])[0]);
check("font MRO minimal 7px pada font kecil", /\.mro-ref\{font-size:7px;/.test(realPoHtml({ doc, company: {}, layout: { ...layout, font_size: 8 }, supplier: {}, project: {}, showPrice: true })));
check("tidak ada kolom baru: header & colgroup tetap (9 kolom harga)", (h.match(/<col style/g) || []).length === 9
  && h.includes("<th>No</th><th>Description</th><th>Keterangan</th><th colspan=\"2\">Qty</th><th>Alokasi SPK</th><th>Price</th><th>Discount</th><th>Amount</th>"));
const hn = html(doc, false);
check("tanpa harga: 6 kolom tetap + MRO tampil", (hn.match(/<col style/g) || []).length === 6 && descCells(hn)[0].includes("MRO/2026/10/00001") && !hn.includes("<th>Price</th>"));
check("ukuran tabel tidak berubah: lebar Description tetap 22% / 28%", h.includes('<col style="width:22%">') && hn.includes('<col style="width:28%">'));
check("isi lain tetap: Keterangan, Qty, Unit, Amount, Grand Total", h.includes('<td class="ket">Spek A</td>') && h.includes('<td class="c unit">PCS</td>') && h.includes("Grand Total"));
const plain = { ...doc, lines: doc.lines.map(({ mro_refs, ...l }) => l) };
const strip = (s) => s.replace(/<div class="mro-ref">[^<]*<\/div><div class="item-name">([^<]*)<\/div>/g, "$1");
check("selain sel Description & CSS MRO, HTML cetak identik dengan PO tanpa referensi MRO (harga, perhitungan, tanda tangan, format)", strip(h) === html(plain), "diff");

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
