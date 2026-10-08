// Node test (no deps): node frontend/src/lib/transferLines.test.mjs
// Transfer Antar Gudang multi gudang: default header -> baris, override manual, Terapkan Default,
// stok tersedia per (barang + gudang asal BARIS), validasi qty/gudang, payload per baris.
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `transferLines.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "transferLines.js"), "utf8"));
const T = await import(tmp);

let pass = 0, fail = 0;
const check = (name, cond, info = "") => { if (cond) { pass += 1; console.log(`PASS ${name}`); } else { fail += 1; console.log(`FAIL ${name} ${info}`); } };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const H1 = { project_id: "PA", from_warehouse_id: "WA", to_warehouse_id: "WB" };
const H2 = { project_id: "PB", from_warehouse_id: "WA", to_warehouse_id: "WD" };

// 1-4. Default header -> baris pertama & baris baru (default TERBARU saat dibuat)
let first = T.newTransferLine({});
let { next: lines, dirty } = T.propagateDefaults([first], {}, H1);
check("1. Header default mengisi baris pertama (baris dibuat sebelum header diisi)", dirty && lines[0].from_warehouse_id === "WA" && lines[0].to_warehouse_id === "WB" && lines[0].project_id === "PA");
const l2 = T.newTransferLine(H1);
check("2/3/4. Tambah baris mengambil Project/Gudang Asal/Gudang Tujuan default header", l2.project_id === "PA" && l2.from_warehouse_id === "WA" && l2.to_warehouse_id === "WB");
check("2. Baris baru berstatus Default (bukan Manual)", !T.isManual(l2, "project_id") && !T.isManual(l2, "from_warehouse_id") && !T.isManual(l2, "to_warehouse_id"));
const l3 = T.newTransferLine(H2);
check("2. Baris yang dibuat setelah header berubah memakai default TERBARU", l3.to_warehouse_id === "WD" && l3.project_id === "PB");

// 5. Override manual per baris & tidak ditimpa header
lines = [T.newTransferLine(H1), T.setLineField(T.newTransferLine(H1), "to_warehouse_id", "WC")];
check("5. Ubah gudang tujuan baris 2 -> status Manual", T.isManual(lines[1], "to_warehouse_id") && lines[1].to_warehouse_id === "WC");
({ next: lines } = T.propagateDefaults(lines, H1, { ...H1, to_warehouse_id: "WD" }));
check("5. Header berubah B->D: baris Manual tetap C (tidak ditimpa diam-diam)", lines[1].to_warehouse_id === "WC", lines[1].to_warehouse_id);
check("6. Baris berstatus Default mengikuti default header baru (B->D)", lines[0].to_warehouse_id === "WD");
check("6. Field lain baris manual (asal/project) yang masih Default tetap ikut", (() => { const r = T.propagateDefaults(lines, { ...H1, to_warehouse_id: "WD" }, { ...H1, to_warehouse_id: "WD", project_id: "PX" }).next; return r[1].project_id === "PX" && r[1].to_warehouse_id === "WC"; })());
const same = T.propagateDefaults(lines, H1, H1);
check("Header tidak berubah -> tidak ada perubahan baris", same.dirty === false && same.next === lines);

// 7-8. Terapkan Default ke Semua Baris (aksi eksplisit, dengan hitung override untuk konfirmasi)
const H3 = { project_id: "PA", from_warehouse_id: "WA", to_warehouse_id: "WD" };
check("7. Hitung nilai manual yang akan ditimpa (untuk konfirmasi)", T.manualOverrideCount(lines, H3) === 1, T.manualOverrideCount(lines, H3));
let applied = T.applyDefaultsToAll(lines, H3);
check("7. Terapkan Default menimpa SEMUA baris dengan default header", applied.every((l) => l.to_warehouse_id === "WD" && l.from_warehouse_id === "WA" && l.project_id === "PA"));
check("7. Setelah Terapkan Default, baris kembali berstatus Default", applied.every((l) => !T.isManual(l, "to_warehouse_id")) && T.manualOverrideCount(applied, H3) === 0);
applied = [applied[0], T.setLineField(applied[1], "from_warehouse_id", "WX")];
check("8. Setelah Terapkan Default, edit manual tetap bisa", applied[1].from_warehouse_id === "WX" && T.isManual(applied[1], "from_warehouse_id"));

// 9-12. Stok tersedia per (barang + gudang asal BARIS)
const stockMap = { IA: { WA: 10, WB: 3 }, IB: { WA: 0 } };
const stockOf = (i, w) => T.availableFor(stockMap, i, w);
check("9. Stok membaca Barang + Gudang Asal baris (IA@WA=10)", stockOf("IA", "WA") === 10);
check("10. Ganti Gudang Asal baris -> stok baris berubah (IA@WB=3)", stockOf("IA", "WB") === 3);
check("11. Ganti Barang -> stok berubah (IB@WA=0)", stockOf("IB", "WA") === 0);
check("Stok belum termuat -> null (diserahkan ke backend)", T.availableFor(stockMap, "IZ", "WA") === null && T.availableFor(stockMap, "IA", "") === null);
let iss = T.transferLineIssues([{ item_id: "IB", qty: 1, from_warehouse_id: "WA", to_warehouse_id: "WB" }], stockOf);
check("12. Stok 0, qty 1 -> error baris", !!iss[0]?.stock && iss[0].available === 0 && iss[0].required === 1);
check("12. Pesan pertama memblokir Posting", (T.firstIssueMessage(iss) || "").startsWith("Baris 1: Stok di gudang asal tidak cukup"));
iss = T.transferLineIssues([
  { item_id: "IA", qty: 6, from_warehouse_id: "WA", to_warehouse_id: "WB" },
  { item_id: "IA", qty: 5, from_warehouse_id: "WA", to_warehouse_id: "WC" },
], stockOf);
check("12. Qty agregat > stok (6+5 > 10 di WA) -> error di kedua baris", !!iss[0]?.stock && !!iss[1]?.stock);
iss = T.transferLineIssues([
  { item_id: "IA", qty: 6, from_warehouse_id: "WA", to_warehouse_id: "WB" },
  { item_id: "IA", qty: 3, from_warehouse_id: "WB", to_warehouse_id: "WA" },
], stockOf);
check("Gudang asal berbeda dihitung terpisah (WA 6<=10, WB 3<=3) -> OK", iss.every((x) => x === null), JSON.stringify(iss));
iss = T.transferLineIssues([{ item_id: "IA", qty: 1, from_warehouse_id: "WA", to_warehouse_id: "WA" }, { item_id: "IA", qty: 0, from_warehouse_id: "", to_warehouse_id: "" }], stockOf);
check("Gudang Asal = Tujuan -> error", !!iss[0]?.same);
check("Gudang kosong & qty 0 -> error", !!iss[1]?.from && !!iss[1]?.to && !!iss[1]?.qty);
const conv = T.transferLineIssues([{ item_id: "IA", qty: 2, conversion_factor: 6, from_warehouse_id: "WA", to_warehouse_id: "WB" }], stockOf);
check("Konversi satuan dihitung ke satuan dasar (2 x 6 = 12 > 10)", conv[0]?.required === 12);

// Edit: kredit reversal dokumen sendiri
const credit = T.editStockCredit([{ item_id: "IA", qty: 4, from_warehouse_id: "WA", to_warehouse_id: "WB" }]);
check("Edit: stok tersedia = stok + qty lama keluar dari gudang asal", T.availableFor(stockMap, "IA", "WA", credit) === 14 && T.availableFor(stockMap, "IA", "WB", credit) === -1);

// 13. Multi gudang dalam satu Transfer -> payload per baris
const multi = [
  { ...T.newTransferLine(H1), item_id: "Bearing", qty: 5 },
  T.setLineField({ ...T.newTransferLine(H1), item_id: "Oli", qty: 10 }, "to_warehouse_id", "WC"),
  T.setLineField(T.setLineField({ ...T.newTransferLine(H1), item_id: "Helm", qty: 3 }, "from_warehouse_id", "WD"), "project_id", "PB"),
];
const payload = T.linesPayload(multi);
check("13. Payload membawa pasangan gudang per baris A->B, A->C, D->B", eq(payload.map((p) => [p.from_warehouse_id, p.to_warehouse_id]), [["WA", "WB"], ["WA", "WC"], ["WD", "WB"]]));
check("13. Payload membawa project per baris & tanpa state UI", payload[2].project_id === "PB" && !Object.keys(payload[0]).some((k) => k.startsWith("_")));
check("13. Multi gudang valid (stok cukup) -> tanpa error", T.transferLineIssues(multi, () => 100).every((x) => x === null));

// Header: nama saja (pencarian tetap kode + nama)
const opts = T.nameOnlyOptions([{ id: "w1", code: "WH-PKU", name: "Warehouse Pekanbaru" }]);
check("Header tampil nama saja; pencarian kode + nama", opts[0].selectedLabel === "Warehouse Pekanbaru" && opts[0].label.includes("WH-PKU") && opts[0].label.includes("Warehouse Pekanbaru"));

// Mode edit: baris dokumen = snapshot (Manual) -> tidak ditimpa header
const fromDoc = T.linesFromDoc({ lines: [{ id: "l1", item_id: "IA", qty: 1, from_warehouse_id: "WA", to_warehouse_id: "WC", project_id: "PA" }] });
check("Edit: baris dokumen tidak ditimpa saat header diubah", T.propagateDefaults(fromDoc, H1, H2).next[0].to_warehouse_id === "WC");

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
