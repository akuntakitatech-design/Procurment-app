// Golden test Tax Engine v2 (mirror frontend) — fixture BERSAMA backend/tests/fixtures/tax_engine_golden.json.
// Node, tanpa dependency: node frontend/src/lib/taxEngine.test.mjs
//   --cases <file.json> --out <file.json> : hitung kasus berformat fixture & tulis output (parity test backend).
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `taxEngine.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "taxEngine.js"), "utf8"));
const T = await import(tmp);
const FIXTURE = join(here, "..", "..", "..", "backend", "tests", "fixtures", "tax_engine_golden.json");

let fail = 0;
const check = (n, c, info = "") => { console.log(`${c ? "PASS" : "FAIL"} ${n}${!c && info ? " — " + (typeof info === "string" ? info : JSON.stringify(info)) : ""}`); if (!c) fail++; };

const tname = (v) => (v === null ? "null" : Array.isArray(v) ? "array" : typeof v);
function subsetDiff(exp, act, path = "") {
  if (exp !== null && typeof exp === "object" && !Array.isArray(exp)) {
    if (tname(act) !== "object") return [`${path}: bukan objek (${JSON.stringify(act)})`];
    return Object.entries(exp).flatMap(([k, v]) => (k in act ? subsetDiff(v, act[k], `${path}.${k}`) : [`${path}.${k}: tidak ada`]));
  }
  if (Array.isArray(exp)) {
    if (!Array.isArray(act) || act.length !== exp.length) return [`${path}: panjang list ${exp.length} != ${Array.isArray(act) ? act.length : JSON.stringify(act)}`];
    return exp.flatMap((e, i) => subsetDiff(e, act[i], `${path}[${i}]`));
  }
  return tname(exp) !== tname(act) || exp !== act ? [`${path}: expected ${JSON.stringify(exp)} got ${JSON.stringify(act)}`] : [];
}

const prepLines = (fx, lines) => lines.map((l) => { const { rule, ...x } = l; if (rule) x.tax_rule = fx.rules[rule]; return x; });
const runPo = (fx, c) => T.computePo(c.header || {}, prepLines(fx, c.lines));
const poOf = (fx, c) => (c.po_inline ? runPo(fx, c.po_inline) : runPo(fx, fx.po_cases.find((p) => p.id === c.po)));
const ruleOf = (fx, name) => (name ? T.makeRule(fx.rules[name]) : null);
const attempt = (fn) => { try { return JSON.parse(JSON.stringify(fn())); } catch (e) { return { __error__: true, message: String(e.message || e) }; } };

export function computeAll(fx) {
  const res = {};
  for (const c of fx.rule_cases || []) res[`rule:${c.id}`] = attempt(() => T.ruleFromMaster(c.master));
  for (const c of fx.po_cases || []) res[`po:${c.id}`] = attempt(() => runPo(fx, c));
  for (const c of fx.invoice_cases || []) {
    if (c.sequence) c.sequence.forEach((s, k) => { res[`inv:${c.id}#${k}`] = attempt(() => T.computeInvoice(poOf(fx, c), s.billed, s.faktur_actual || null)); });
    else res[`inv:${c.id}`] = attempt(() => T.computeInvoice(poOf(fx, c), c.billed, c.faktur_actual || null));
  }
  for (const c of fx.dp_cases || []) res[`dp:${c.id}`] = attempt(() => {
    const po = poOf(fx, c); const inv = T.computeInvoice(po, po.lines.map((l, i) => ({ line_index: i, qty: l.qty })));
    const dps = c.dps.map((d) => T.computeDp(d.amount, ruleOf(fx, d.rule), d.with_faktur));
    return { dps, settle: T.settleWithDp(inv, dps) };
  });
  for (const c of fx.match_cases || []) res[`match:${c.id}`] = attempt(() => T.matchFaktur(c.expected, c.faktur, c.tolerance ?? "1"));
  return res;
}

const argv = process.argv;
if (argv.includes("--cases")) {
  const fx = JSON.parse(readFileSync(argv[argv.indexOf("--cases") + 1], "utf8"));
  writeFileSync(argv[argv.indexOf("--out") + 1], JSON.stringify(computeAll(fx)));
  process.exit(0);
}

const fx = JSON.parse(readFileSync(FIXTURE, "utf8"));
const res = computeAll(fx);
const one = (key, c, exp) => {
  const r = res[key];
  if (c.error) return check(`${key} ${c.title || ""} -> ditolak`, r && r.__error__ === true, r);
  if (r && r.__error__) return check(`${key} ${c.title || ""}`, false, r.message);
  const d = subsetDiff(exp, r); check(`${key} ${c.title || ""}`, !d.length, d.slice(0, 6).join("; "));
};
fx.rule_cases.forEach((c) => one(`rule:${c.id}`, c, c.expect));
fx.po_cases.forEach((c) => one(`po:${c.id}`, c, c.expect));
fx.invoice_cases.forEach((c) => (c.sequence ? c.sequence.forEach((s, k) => one(`inv:${c.id}#${k}`, s, s.expect)) : one(`inv:${c.id}`, c, c.expect)));
fx.dp_cases.forEach((c) => one(`dp:${c.id}`, c, c.error ? null : { dps: c.expect_dps, settle: c.expect }));
fx.match_cases.forEach((c) => one(`match:${c.id}`, c, c.expect));

// unit: pembulatan & parsing (tanpa float)
const R = T.roundUnits, b = (n) => BigInt(n);
check("HALF_UP 0,005 -> 0,01 (bukan half-even)", R("0.005", 2) === b(1) && R("0.015", 2) === b(2) && R("0.025", 2) === b(3));
check("HALF_UP negatif simetris", R("-0.005", 2) === b(-1) && R("-2.5", 0) === b(-3) && R("-2.4", 0) === b(-2));
check("Rupiah HALF_UP 33.962,50 -> 33.963 ; 16,49 -> 16", R("33962.50", 0) === b(33963) && R("16.49", 0) === b(16));
check("Float tidak menyusup: 0.1 + 0.2 eksak", T.toQ(0.1).add(T.toQ(0.2)).cmp(T.toQ("0.3")) === 0);
for (const bad of ["1.000,50", "1,5", "abc", "1_000", "NaN", "Infinity", "1e999999", "-", ".", NaN, Infinity]) {
  let ok = false; try { T.toQ(bad); } catch { ok = true; } check(`Input angka tidak valid ditolak: ${String(bad)}`, ok);
}
check("engineVersionOf: tanpa versi = v1, v2 dikenali", T.engineVersionOf({}) === 1 && T.engineVersionOf({ tax_engine_version: 2 }) === 2);
check("ROUNDING_POLICY ada di output PO", JSON.stringify(res["po:S1"].rounding_policy) === JSON.stringify(T.ROUNDING_POLICY));
const src = readFileSync(join(here, "taxEngine.js"), "utf8");
check("Tanpa parseFloat/Number()/Math.round di engine", !/parseFloat|Number\(|Math\.round|toFixed/.test(src));

console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED");
process.exit(fail ? 1 : 0);
