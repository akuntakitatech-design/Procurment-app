// Node test (no deps): node frontend/src/lib/format.test.mjs
// Formatter angka: nilai kosong -> "0", locale id-ID, dan sisa float kecil tidak boleh tampil "-0".
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `format.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "format.js"), "utf8"));
const F = await import(pathToFileURL(tmp).href);

let fail = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail += 1; console.log(`FAIL ${label}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`); }
  else console.log(`PASS ${label}`);
};

check("num(null)", F.num(null), "0");
check("num(undefined)", F.num(undefined), "0");
check("num(0)", F.num(0), "0");
check("num(17643)", F.num(17643), "17.643");
check("num(1234.5)", F.num(1234.5), "1.234,5");
check("num(-6e-15) tidak '-0'", F.num(-6e-15), "0");
check("num(-0) tidak '-0'", F.num(-0), "0");
check("num(-0.004) tidak '-0'", F.num(-0.004), "0");
check("num(-2.5) tetap negatif", F.num(-2.5), "-2,5");

console.log(fail === 0 ? "\nSEMUA PASS" : `\n${fail} GAGAL`);
process.exit(fail === 0 ? 0 : 1);
