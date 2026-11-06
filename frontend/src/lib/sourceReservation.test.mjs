// Node test (no deps): node frontend/src/lib/sourceReservation.test.mjs
// Aturan picker: Sisa Efektif = sisa untuk dokumen ini - qty di form aktif; <=0 -> hilang; tarik ulang -> merge.
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `sourceReservation.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "sourceReservation.js"), "utf8"));
const R = await import(pathToFileURL(tmp).href);

let fail = 0;
const check = (name, cond, info = "") => { console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };
const eq = (a, b) => Math.abs(Number(a) - Number(b)) < 1e-6;

// ---------------------------------------------------------------- RO <- MRO
{
  const pull = [{ line_id: "M1", item_id: "I", mro_id: "D1", mro_no: "MRO-1", division_id: "V", outstanding_base: 10, outstanding: 10 }];
  const grp = (rows) => rows.map((r) => ({ key: `V|I`, item_id: "I", division_id: "V", sources: [{ line_id: r.line_id, mro_id: r.mro_id, sisa: r.outstanding_base, db_sisa: r._db_outstanding_base ?? r.outstanding_base, qty: 0 }] }));
  const take = (rows, q) => grp(rows).map((g) => ({ ...g, sources: g.sources.map((s) => ({ ...s, qty: q ?? s.sisa })) }));
  const vis = (lines) => R.applyRoReservation(pull, R.roFormReservation(lines));
  let lines = R.mergeRoPicked([], take(vis([]), 10));
  check("RO tarik 10 dari sisa 10 -> sumber hilang", vis(lines).length === 0);
  lines = R.mergeRoPicked([], take(vis([]), 6));
  check("RO tarik 6 -> sisa picker 4", eq(vis(lines)[0].outstanding_base, 4), vis(lines));
  lines = lines.map((l) => ({ ...l, qty: 7, sources: l.sources.map((s) => ({ ...s, qty: 7 })) }));
  check("RO qty form 6 -> 7 -> sisa picker 3", eq(vis(lines)[0].outstanding_base, 3));
  lines = R.mergeRoPicked(lines, take(vis(lines)));
  check("RO tarik tambahan 3 -> tetap 1 baris, 1 sumber, qty 10", lines.length === 1 && lines[0].sources.length === 1 && eq(lines[0].qty, 10), lines);
  check("RO setelah merge sisa sumber tetap = sisa DB (10)", eq(lines[0].sources[0].sisa, 10));
  check("RO setelah merge -> sumber hilang", vis(lines).length === 0);
  check("RO hapus baris -> sumber kembali 10", eq(vis([])[0].outstanding_base, 10));
}

// ---------------------------------------------------------------- Picker "Tarik MRO" per dokumen MRO (Opsi 1)
{
  const pull = [
    { mro_id: "M2", mro_no: "MRO-2", mro_date: "2026-10-02", division_id: "V", division_name: "Divisi V", item_id: "I1", item_code: "A1", item_name: "Baut", outstanding: 5 },
    { mro_id: "M1", mro_no: "MRO-1", mro_date: "2026-10-01", division_id: "V", division_name: "Divisi V", item_id: "I1", item_code: "A1", item_name: "Baut", outstanding: 3 },
    { mro_id: "M1", mro_no: "MRO-1", mro_date: "2026-10-01", division_id: "V", division_name: "Divisi V", item_id: "I2", item_code: "B2", item_name: "Mur", outstanding: 2 },
    { mro_id: "M3", mro_no: "MRO-3", mro_date: "2026-10-03", division_id: "W", division_name: "Divisi W", item_id: "I1", item_code: "A1", item_name: "Baut", outstanding: 4 },
  ];
  const g = R.groupMroRows(pull);
  check("picker MRO: 1 baris per dokumen MRO (urut tanggal)", g.length === 3 && g.map((x) => x.mro_no).join() === "MRO-1,MRO-2,MRO-3", g.map((x) => x.mro_no));
  check("picker MRO: jumlah item dihitung per MRO", g[0].item_count === 2 && g[1].item_count === 1, g.map((x) => x.item_count));
  check("picker MRO: divisi ikut dokumen MRO", g[0].division_name === "Divisi V" && g[2].division_id === "W");

  const chosen = new Set(g.filter((x) => ["MRO-1", "MRO-2"].includes(x.mro_no)).map((x) => x.key));
  const rows = R.rowsOfMro(pull, chosen);
  check("picker MRO: centang 2 MRO -> semua item keduanya ditarik (3 baris)", rows.length === 3 && !rows.some((r) => r.mro_id === "M3"), rows.length);
  const cons = R.consolidatePulled(rows);
  const a1 = cons.find((x) => x.item_code === "A1");
  check("picker MRO: barang sama dari 2 MRO jadi 1 baris", cons.length === 2 && !!a1, cons.map((x) => x.item_code));
  check("picker MRO: baris A1 punya 2 sumber MRO", a1.sources.length === 2, a1.sources.map((s) => s.mro_no));
  const full = R.distribute(a1.sources, a1.sources.reduce((t, s) => t + Number(s.sisa), 0));
  check("picker MRO: qty terakumulasi 3 + 5 = 8", eq(full.reduce((t, s) => t + s.qty, 0), 8), full.map((s) => s.qty));
  check("picker MRO: seluruh sisa diambil (tidak ada sisa tersisa)", full.every((s) => eq(s.qty, s.sisa)));

  // Item yang sudah dipakai di form: MRO tetap tampil, item yang sisa efektifnya 0 disembunyikan.
  const reserved = R.reserveMap([["L-M1-A1", 3]]);
  const avail = R.applyRoReservation(pull.map((r) => ({ ...r, line_id: r.mro_no === "MRO-1" && r.item_id === "I1" ? "L-M1-A1" : `${r.mro_no}-${r.item_id}` })), reserved);
  const g2 = R.groupMroRows(avail);
  const m1 = g2.find((x) => x.mro_no === "MRO-1");
  check("picker MRO: MRO yang sebagian dipakai tetap tampil", !!m1 && m1.item_count === 1, m1);
  check("picker MRO: item yang sisa efektifnya habis hilang dari pilihan", !!m1 && !m1.lines.some((r) => r.item_id === "I1"));
}

// ---------------------------------------------------------------- PO <- RO
{
  const pull = [{ line_id: "R1", ro_id: "RO", ro_no: "RO-1", item_id: "I", division_id: "V", outstanding_base: 10,
    sources: [{ ro_alloc_id: "A1", mro_no: "MRO-1", sisa: 10 }] }];
  const mk = (r) => ({ item_id: r.item_id, qty: r._qty, conversion_factor: 1, _roSources: (r.sources || []).map((s) => ({ ...s, ro_id: r.ro_id, line_id: r.line_id, qty: r._qty })) });
  const vis = (lines) => R.applyPoReservation(pull, lines);
  let { lines } = R.mergePulledIntoPo([], [{ ...vis([])[0], _qty: 10 }], mk);
  check("PO tarik 10 dari sisa 10 -> sumber hilang", vis(lines).length === 0);
  ({ lines } = R.mergePulledIntoPo([], [{ ...vis([])[0], _qty: 6 }], mk));
  check("PO tarik 6 -> sisa picker 4", eq(vis(lines)[0].outstanding_base, 4));
  check("PO tarik 6 -> sisa rincian sumber 4", eq(vis(lines)[0].sources[0].sisa, 4));
  ({ lines } = R.mergePulledIntoPo(lines, [{ ...vis(lines)[0], _qty: 4 }], mk));
  check("PO tarik tambahan 4 -> tetap 1 baris PO, qty 10", lines.length === 1 && eq(lines[0].qty, 10), lines);
  check("PO merge: rincian sumber tetap 1 (lineage RO/MRO utuh), qty 10, sisa 10", lines[0]._roSources.length === 1 && eq(lines[0]._roSources[0].qty, 10) && eq(lines[0]._roSources[0].sisa, 10) && lines[0]._roSources[0].mro_no === "MRO-1");
  check("PO setelah merge -> sumber hilang", vis(lines).length === 0);
  check("PO hapus baris -> sumber kembali 10", eq(vis([])[0].outstanding_base, 10));
}

// ---------------------------------------------------------------- DO <- PO, MI <- MRO
for (const [mod, key, docKey] of [["DO", "po_line_id", "po_id"], ["MI", "mro_line_id", "mro_id"]]) {
  const pull = [{ line_id: "L1", [docKey]: "D", outstanding_base: 10, outstanding: 10, conversion_factor: 1 }];
  const vis = (lines) => R.applyLineReservation(pull, R.lineFormReservation(lines, key));
  const add = (lines, q) => { const { merged, fresh } = R.mergeLinePull(lines, [{ ...pull[0], _qty: q }], key, docKey); return [...merged, ...fresh.map((p) => ({ [key]: p.line_id, [docKey]: p[docKey], qty: p._qty, conversion_factor: 1 }))]; };
  let lines = add([], 10);
  check(`${mod} tarik 10 dari sisa 10 -> sumber hilang`, vis(lines).length === 0);
  lines = add([], 6);
  check(`${mod} tarik 6 -> sisa picker 4`, eq(vis(lines)[0].outstanding, 4) && eq(vis(lines)[0].reserved, 6));
  lines = lines.map((l) => ({ ...l, qty: 7 }));
  check(`${mod} qty form 6 -> 7 -> sisa picker 3`, eq(vis(lines)[0].outstanding, 3));
  lines = add(lines, 3);
  check(`${mod} tarik tambahan -> merge ke baris existing (1 baris, qty 10)`, lines.length === 1 && eq(lines[0].qty, 10) && eq(lines[0].sources[0].base_qty, 10), lines);
  check(`${mod} hapus baris -> sumber kembali 10`, eq(vis([])[0].outstanding, 10));
  // konversi satuan: sumber dalam BOX (1 BOX = 12 PCS dasar), baris form dalam BOX juga
  const boxPull = [{ line_id: "L2", [docKey]: "D", outstanding_base: 24, outstanding: 2, conversion_factor: 12 }];
  const v2 = R.applyLineReservation(boxPull, R.lineFormReservation([{ [key]: "L2", qty: 1, conversion_factor: 12 }], key));
  check(`${mod} konversi satuan: 2 BOX - 1 BOX di form -> sisa 1 BOX (12 dasar)`, eq(v2[0].outstanding, 1) && eq(v2[0].outstanding_base, 12));
}
// MI Direct line tidak dihitung sebagai reservasi MRO (skip)
{
  const { merged, fresh } = R.mergeLinePull([{ mro_line_id: "L1", qty: 1, _direct: true, conversion_factor: 1 }], [{ line_id: "L1", _qty: 2, conversion_factor: 1 }], "mro_line_id", "mro_id", (l) => l._direct);
  check("MI baris Direct tidak di-merge dengan sumber MRO", merged.length === 1 && fresh.length === 1);
}
check("pullParams Edit -> current_doc_id; Baru -> kosong", R.pullParams("X").current_doc_id === "X" && Object.keys(R.pullParams(null)).length === 0);

console.log(`\n${fail ? "FAILED " + fail : "ALL PASSED"}`);
process.exit(fail ? 1 : 0);
