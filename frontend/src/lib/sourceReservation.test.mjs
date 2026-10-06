// Node test (no deps): node frontend/src/lib/sourceReservation.test.mjs
// Aturan picker: Sisa Efektif = sisa untuk dokumen ini - qty di form aktif; <=0 -> hilang; tarik ulang -> merge.
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `sourceReservation.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "sourceReservation.js"), "utf8"));
const R = await import(tmp);

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
