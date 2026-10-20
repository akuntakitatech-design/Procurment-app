// Uji cetak PO: referensi MRO/RO sebagai baris grup di kolom Description (format PO manual "MRO 2248"). Jalankan:
//   cd /app/frontend && npx esbuild tests/po_print_mro_test.mjs --bundle --platform=node --format=cjs --loader:.js=jsx --outfile=/tmp/po_print_mro.cjs --log-level=error && node /tmp/po_print_mro.cjs
import { realPoHtml, poDescCell, poRefGroups, poRefLabel } from "../src/lib/print.js";

let pass = 0, fail = 0;
const check = (name, ok, info) => { if (ok) { pass++; console.log("PASS", name); } else { fail++; console.log("FAIL", name, info ?? ""); } };
const layout = { show_message: true, show_signatures: true, show_qr: false, font_size: 11 };
const L = (o) => ({ qty: 2, price: 1000, dpp: 2000, tax: 11, tax_amount: 220, notes: "Spek A", display_unit: "PCS", ...o });
const doc = { no: "PO/2026/10/00001", status: "Approved", grand_total: 8880, subtotal_after_discount: 8000, lines: [
  L({ item_name: "Bearing 6205", mro_refs: ["MRO/2026/10/00001"], ro_refs: [{ ro_no: "RO/2026/10/00001" }] }),
  L({ item_name: "Seal Kit", mro_refs: ["MRO/2026/10/00001"], ro_refs: [{ ro_no: "RO/2026/10/00001" }] }),
  L({ item_name: "Gasket", mro_refs: ["MRO/2026/10/00003", "MRO/2026/10/00002", "MRO/2026/10/00003", ""], ro_refs: [{ ro_no: "RO/2026/10/00002" }, { ro_no: "RO/2026/10/00002" }] }),
  L({ item_name: "Oli <SAE> 40" })] };
const html = (d, showPrice = true) => realPoHtml({ doc: d, company: { name: "PT Uji" }, layout, supplier: {}, project: {}, showPrice, internal: false, autoPrint: false });
const grp = (h) => [...h.matchAll(/<td class="grp-label" colspan="2">([\s\S]*?)<\/td>/g)].map((m) => m[1]);
const names = (h) => [...h.matchAll(/<div class="item-name">([\s\S]*?)<\/div>/g)].map((m) => m[1]);

const h = html(doc);
const g = grp(h);
check("baris grup: 3 grup berurutan (MRO-1/RO-1, MRO-3+MRO-2/RO-2, tanpa referensi)", g.length === 3, g);
check("grup 1 memuat MRO + RO, baris berurutan dengan referensi sama digabung", g[0] === "MRO/2026/10/00001  ·  RO/2026/10/00001", g[0]);
check("multi-MRO: tanpa duplikasi/kosong, urutan backend dipertahankan; RO unik", g[1] === "MRO/2026/10/00003, MRO/2026/10/00002  ·  RO/2026/10/00002", g[1]);
check("baris tanpa referensi di antara grup diberi label jelas", g[2] === "Tanpa referensi MRO/RO", g[2]);
check("nama barang tetap tampil & di-escape; penomoran tetap 1..4", names(h).join("|") === "Bearing 6205|Seal Kit|Gasket|Oli &lt;SAE&gt; 40" && /<td class="c no">4<\/td>/.test(h), names(h));
check("PO tanpa referensi sama sekali: tidak ada baris grup", grp(html({ ...doc, lines: [L({ item_name: "X" })] })).length === 0);
check("nomor tanpa awalan diberi prefix MRO/RO (\"MRO 2248\" seperti manual)", poRefLabel({ mro_refs: ["2248"], ro_refs: [{ ro_no: "77" }] }) === "MRO 2248  ·  RO 77");
check("nomor referensi di-escape", html({ ...doc, lines: [L({ item_name: "X", mro_refs: ["<b>"] })] }).includes("MRO &lt;b&gt;"));
check("poRefGroups: indeks baris asli dipertahankan", poRefGroups(doc.lines).flatMap((x) => x.rows.map(([, i]) => i)).join() === "0,1,2,3");
check("tanpa harga: grup tetap tampil, kolom harga tidak ada", grp(html(doc, false)).length === 3 && !html(doc, false).includes("<th>Price</th>"));
check("poDescCell (kompatibilitas ekspor lama) tetap bekerja", poDescCell({ item_name: "X", mro_refs: [] }) === "X");
const plain = { ...doc, lines: doc.lines.map(({ mro_refs, ro_refs, ...l }) => l) };
const strip = (s) => s.replace(/<tr class="grp">[\s\S]*?<\/tr>/g, "");
check("selain baris grup, HTML cetak identik dengan PO tanpa referensi (harga, perhitungan, TTD, format)", strip(h) === html(plain), "diff");

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
