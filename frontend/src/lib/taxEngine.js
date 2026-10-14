// Tax Calculation Engine (PPN) — mirror frontend dari backend/tax_engine.py (F1, belum dipakai UI).
// Backend = sumber kebenaran; modul ini wajib menghasilkan angka identik (golden test bersama
// backend/tests/fixtures/tax_engine_golden.json). Tanpa float: rasional BigInt, ROUND_HALF_UP.
// PO: per sen berantai (DPP -> DPP Nilai Lain -> PPN), tanpa pembulatan rupiah.
// Invoice: faktur per kode transaksi = jumlah baris -> rupiah penuh HALF_UP (PER-11/PJ/2025 Ps.129(3)).
// Nilai uang dikembalikan sebagai string desimal ("110000.00").

export const TAX_ENGINE_VERSION = 2;
export const LEGACY_ENGINE_VERSION = 1;
const MODES = ["INCLUDE", "EXCLUDE", "NONE"];
const FACILITIES = ["NORMAL", "TIDAK_DIPUNGUT", "DTP", "DIBEBASKAN"];
const COST_TREATMENTS = ["CAPITALIZE_TAX", "EXCLUDE_TAX"];
export const ACQ_TYPES = ["INVENTORY", "ASSET", "SERVICE"];
export const ROUNDING_POLICY = Object.freeze({ po: "Decimal per sen (2 desimal) HALF_UP berantai; tanpa pembulatan rupiah",
  invoice_faktur: "jumlah baris per kode transaksi -> rupiah penuh HALF_UP (PER-11/PJ/2025 Ps.129(3))",
  final_discount: "prorata, sisa terbesar per sen" });
const GROUP_FIELDS = ["tax_trx_code", "tax_code", "tax_rate", "tax_dpp_factor_num", "tax_dpp_factor_den", "tax_facility"];
const groupKey = (l) => GROUP_FIELDS.map((k) => (l[k] === null || l[k] === undefined ? "" : String(l[k]))).join("|");
const B0 = BigInt(0), B1 = BigInt(1), B2 = BigInt(2), B10 = BigInt(10), B100 = BigInt(100);
// pangkat 10 tanpa operator ** (Babel dapat mentranspilasi ** menjadi Math.pow yang tidak mendukung BigInt)
const pow10 = (k) => { let r = B1; for (let i = 0; i < k; i++) r *= B10; return r; };
const babs = (a) => (a < B0 ? -a : a);
const gcd = (a, b) => { a = babs(a); b = babs(b); while (b) { const t = a % b; a = b; b = t; } return a || B1; };
const fdiv = (a, b) => { const q = a / b; return (a % b !== B0 && ((a < B0) !== (b < B0))) ? q - B1 : q; };

export class Q {
  constructor(n, d = B1) { if (d === B0) throw new Error("pembagian dengan nol"); if (d < B0) { n = -n; d = -d; } const g = gcd(n, d); this.n = n / g; this.d = d / g; }
  add(o) { o = toQ(o); return new Q(this.n * o.d + o.n * this.d, this.d * o.d); }
  sub(o) { o = toQ(o); return new Q(this.n * o.d - o.n * this.d, this.d * o.d); }
  mul(o) { o = toQ(o); return new Q(this.n * o.n, this.d * o.d); }
  div(o) { o = toQ(o); return new Q(this.n * o.d, this.d * o.n); }
  neg() { return new Q(-this.n, this.d); }
  cmp(o) { o = toQ(o); const l = this.n * o.d, r = o.n * this.d; return l < r ? -1 : l > r ? 1 : 0; }
  isZero() { return this.n === B0; }
  floor() { return fdiv(this.n, this.d); }
}
const ZERO = new Q(B0);
const qi = (i) => new Q(BigInt(i));
const qc = (cents) => new Q(BigInt(cents), B100);

export function toQ(v) {
  if (v instanceof Q) return v;
  if (v === null || v === undefined || v === "") return ZERO;
  if (typeof v === "boolean") throw new Error("angka tidak valid");
  if (typeof v === "bigint") return new Q(v);
  // pemisah ribuan/koma desimal (mis. "1.000,50") DITOLAK, tidak ditebak — sama dengan backend
  const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(String(v).trim());
  if (!m || (m[2] === "" && !m[3])) throw new Error(`angka tidak valid: ${v}`);
  const frac = m[3] || "", exp = parseInt(m[4] || "0", 10) - frac.length;
  if (Math.abs(exp) > 40 || (m[2] || "").length + frac.length > 40) throw new Error(`angka tidak valid: ${v}`); // batas wajar, sama dengan backend
  let n = BigInt((m[2] || "0") + frac); if (m[1] === "-") n = -n;
  return exp >= 0 ? new Q(n * pow10(exp)) : new Q(n, pow10(-exp));
}
export function roundUnits(x, scale) {
  const y = toQ(x).mul(new Q(pow10(scale))), h = new Q(B1, B2);
  return y.cmp(ZERO) >= 0 ? y.add(h).floor() : -(y.neg().add(h).floor());
}
export function dec(units, scale) {
  units = BigInt(units); const neg = units < B0; let s = babs(units).toString();
  if (scale > 0) { s = s.padStart(scale + 1, "0"); s = s.slice(0, -scale) + "." + s.slice(-scale); }
  return (neg ? "-" : "") + s;
}
const c2 = (x) => roundUnits(x, 2);
const d2 = (c) => dec(c, 2);
const cents = (s) => roundUnits(toQ(s), 2); // string "123.45" -> 12345n
function plain(x) { // Fraction -> desimal terminasi tanpa nol belakang (setara str(Decimal(n)/Decimal(d)))
  x = toQ(x); let s = 0; while (x.mul(new Q(pow10(s))).d !== B1 && s < 30) s++;
  let r = dec(x.mul(new Q(pow10(s))).floor(), s); if (r.includes(".")) r = r.replace(/0+$/, "").replace(/\.$/, ""); return r;
}

export function allocateUnits(raws, target, scale = 2) {
  const n = raws.length; if (!n) return []; const m = new Q(pow10(scale)); target = BigInt(target);
  const base = raws.map((r) => toQ(r).mul(m).floor()); const rem = raws.map((r, i) => toQ(r).mul(m).sub(new Q(base[i])));
  let diff = target - base.reduce((a, b) => a + b, B0);
  const order = [...Array(n).keys()].sort((a, b) => rem[b].cmp(rem[a]) || a - b);
  for (let k = 0; diff > B0; k++, diff -= B1) base[order[k % n]] += B1;
  return base;
}

// ----------------------------------------------------------------------------- aturan (master Accounting)
export function makeRule({ code = "PPN", name = null, rate = 0, dpp_factor_num = 1, dpp_factor_den = 1, trx_code = null, facility = "NORMAL" } = {}) {
  const r = toQ(rate), num = parseInt(dpp_factor_num, 10), den = parseInt(dpp_factor_den, 10);
  if (r.cmp(ZERO) < 0 || r.cmp(qi(100)) > 0) throw new Error("tarif pajak harus 0..100");
  if (!(den > 0) || !(num >= 0)) throw new Error("faktor DPP Nilai Lain tidak valid");
  const fac = String(facility || "NORMAL").toUpperCase(); if (!FACILITIES.includes(fac)) throw new Error(`fasilitas pajak tidak dikenal: ${fac}`);
  return { code: String(code || "PPN"), name: name || String(code || "PPN"), rate: plain(r), dpp_factor_num: num, dpp_factor_den: den,
    trx_code: trx_code === null || trx_code === undefined || trx_code === "" ? null : String(trx_code), facility: fac };
}
export function ruleFromMaster(t) {
  if (!t) return null;
  return makeRule({ code: t.code || t.id || "PPN", name: t.name, rate: t.rate || 0, dpp_factor_num: t.dpp_factor_num || 1, dpp_factor_den: t.dpp_factor_den || 1,
    trx_code: t.coretax_trx_code || t.trx_code || null, facility: t.facility || "NORMAL" });
}
export function snapshotRule(r) {
  r = r || {};
  return { tax_code: r.code ?? null, tax_name: r.name ?? null, tax_rate: r.rate ?? "0", tax_dpp_factor_num: r.dpp_factor_num ?? 1, tax_dpp_factor_den: r.dpp_factor_den ?? 1,
    tax_trx_code: r.trx_code ?? null, tax_facility: r.facility ?? "NORMAL" };
}
export function ruleFromLine(l) {
  if (l.tax_rule) return makeRule(l.tax_rule);
  if (!l.tax_code) return null;
  return makeRule({ code: l.tax_code, name: l.tax_name, rate: l.tax_rate || 0, dpp_factor_num: l.tax_dpp_factor_num || 1, dpp_factor_den: l.tax_dpp_factor_den || 1,
    trx_code: l.tax_trx_code ?? null, facility: l.tax_facility || "NORMAL" });
}
function acct(l) {
  const cred = l.input_vat_creditable === undefined || l.input_vat_creditable === null ? true : !!l.input_vat_creditable;
  const ct = String(l.cost_treatment || "CAPITALIZE_TAX").toUpperCase(); if (!COST_TREATMENTS.includes(ct)) throw new Error(`perlakuan biaya tidak dikenal: ${ct}`);
  const acq = String(l.acquisition_type || "INVENTORY").toUpperCase(); if (!ACQ_TYPES.includes(acq)) throw new Error(`jenis perolehan tidak dikenal: ${acq}`);
  return { cred, ct, acq };
}

function lineValues(i, mode, netC, rule, ppnbmRate) {
  if (mode === "NONE" || !rule) return { taxable: false, billed: false, dpp: netC, nl: B0, ppn: B0, bm: B0 };
  const rate = toQ(rule.rate).div(qi(100)), f = new Q(BigInt(rule.dpp_factor_num), BigInt(rule.dpp_factor_den)), bm = toQ(ppnbmRate).div(qi(100));
  const billed = rule.facility === "NORMAL";
  if (!rule.trx_code) throw new Error(`baris ${i + 1}: kode transaksi faktur wajib diisi di master jenis transaksi PPN`);
  if (!billed && mode === "INCLUDE") throw new Error(`baris ${i + 1}: fasilitas PPN tidak dapat dikombinasikan dengan harga Include`);
  if (!billed && !bm.isZero()) throw new Error(`baris ${i + 1}: PPnBM tidak berlaku untuk baris dengan fasilitas PPN`);
  if (bm.cmp(ZERO) < 0 || bm.cmp(qi(2)) > 0) throw new Error(`baris ${i + 1}: tarif PPnBM tidak valid`);
  const dpp = mode === "INCLUDE" ? c2(qc(netC).div(qi(1).add(rate.mul(f)).add(bm))) : netC;
  const nl = c2(qc(dpp).mul(f)), ppn = c2(qc(nl).mul(rate)), bmC = c2(qc(dpp).mul(bm));
  return { taxable: true, billed, dpp, nl, ppn, bm: bmC };
}
function finishLine(src, mode, rule, qty, grossC, discC, fdC, netC, v) {
  const { cred, ct, acq } = acct(src);
  const tax = v.billed ? v.ppn : B0, fac = v.billed ? B0 : v.ppn, total = v.dpp + tax + v.bm;
  const cost = v.dpp + v.bm + (v.billed && !cred && ct === "CAPITALIZE_TAX" ? tax : B0);
  const x = { ...src }; delete x.tax_rule;
  return Object.assign(x, snapshotRule(v.taxable ? rule : null), { tax_mode: mode, input_vat_creditable: cred, cost_treatment: ct, acquisition_type: acq,
    gross: d2(grossC), discount_amount: d2(discC), final_discount_share: d2(fdC), net_amount: d2(netC), dpp: d2(v.dpp), dpp_other: d2(v.nl),
    tax_amount: d2(tax), tax_facility_amount: d2(fac), ppnbm_amount: d2(v.bm), total: d2(total), include_rounding_diff: d2(mode === "INCLUDE" ? total - netC : B0),
    cost_base: d2(cost), unit_cost: qty.isZero() ? "0.000000" : dec(roundUnits(qc(cost).div(qty), 6), 6), taxable: v.taxable, tax_engine_version: TAX_ENGINE_VERSION });
}
function summarize(lines) {
  const s = (k, pred) => d2(lines.filter((l) => !pred || pred(l)).reduce((a, l) => a + cents(l[k]), B0));
  const groups = new Map();
  lines.forEach((l, idx) => {
    if (!l.taxable) return;
    const key = groupKey(l);
    if (!groups.has(key)) groups.set(key, { group: key, trx_code: l.tax_trx_code, tax_code: l.tax_code, tax_name: l.tax_name, facility: l.tax_facility, line_indexes: [], c: { dpp: B0, dpp_other: B0, ppn: B0, ppn_facility: B0, ppnbm: B0 } });
    const g = groups.get(key); g.line_indexes.push(idx);
    g.c.dpp += cents(l.dpp); g.c.dpp_other += cents(l.dpp_other); g.c.ppn += cents(l.tax_amount); g.c.ppn_facility += cents(l.tax_facility_amount); g.c.ppnbm += cents(l.ppnbm_amount);
  });
  const G = [...groups.values()].map((g) => { const { c, ...rest } = g; return { ...rest, _c: c, dpp: d2(c.dpp), dpp_other: d2(c.dpp_other), ppn: d2(c.ppn), ppn_facility: d2(c.ppn_facility), ppnbm: d2(c.ppnbm) }; });
  const tx = (l) => l.taxable;
  const t = { gross_total: s("gross"), item_discount_total: s("discount_amount"), final_discount_amount: s("final_discount_share"), subtotal_after_discount: s("net_amount"),
    dpp_total: s("dpp", tx), non_ppn_total: s("total", (l) => !l.taxable), dpp_other_total: s("dpp_other"), tax_total: s("tax_amount"), ppnbm_total: s("ppnbm_amount"),
    tax_facility_total: s("tax_facility_amount"), grand_total: s("total"), cost_base_total: s("cost_base"),
    cost_by_type: Object.fromEntries(ACQ_TYPES.map((k) => [k, s("cost_base", (l) => l.acquisition_type === k)])),
    input_vat_creditable_total: s("tax_amount", (l) => l.input_vat_creditable), input_vat_non_creditable_total: s("tax_amount", (l) => !l.input_vat_creditable) };
  t.subtotal_after_item_discount = d2(cents(t.gross_total) - cents(t.item_discount_total));
  return { totals: t, groups: G };
}
function rulesSnapshot(groups, lines) {
  return groups.map((g) => { const l = lines[g.line_indexes[0]];
    return { group: g.group, tax_code: l.tax_code, tax_name: l.tax_name, tax_rate: l.tax_rate, tax_dpp_factor_num: l.tax_dpp_factor_num,
      tax_dpp_factor_den: l.tax_dpp_factor_den, tax_trx_code: l.tax_trx_code, tax_facility: l.tax_facility }; });
}
const checkPkp = (h, mode, i) => { if (h.supplier_pkp === false && mode !== "NONE") throw new Error(`baris ${i + 1}: supplier Non-PKP tidak boleh dikenakan PPN (koreksi status di Master Supplier)`); };
const isPct = (t) => ["percent", "%", "persen", "pct"].includes(String(t || "").toLowerCase());

export function computePo(header = {}, lines = []) {
  const work = lines.map((l, i) => {
    const mode = String(l.tax_mode || "EXCLUDE").toUpperCase(); if (!MODES.includes(mode)) throw new Error(`baris ${i + 1}: mode pajak tidak dikenal ${mode}`);
    checkPkp(header, mode, i);
    const qty = toQ(l.qty), price = toQ(l.price); if (qty.cmp(ZERO) < 0 || price.cmp(ZERO) < 0) throw new Error(`baris ${i + 1}: qty/harga tidak boleh negatif`);
    const grossC = c2(qty.mul(price));
    let discC = l.discount_percent !== undefined && l.discount_percent !== null && l.discount_percent !== "" ? c2(qc(grossC).mul(toQ(l.discount_percent)).div(qi(100))) : c2(toQ(l.discount));
    if (discC < B0) discC = B0; if (discC > grossC) discC = grossC;
    return { l, i, mode, qty, grossC, discC, net0: grossC - discC };
  });
  const sub = work.reduce((a, w) => a + w.net0, B0), fv = toQ(header.final_discount_value);
  let fd = B0;
  if (fv.cmp(ZERO) > 0 && sub > B0) { fd = isPct(header.final_discount_type) ? c2(qc(sub).mul(fv).div(qi(100))) : c2(fv); if (fd > sub) fd = sub; }
  const shares = fd ? allocateUnits(work.map((w) => qc(w.net0).mul(new Q(fd, sub))), fd) : work.map(() => B0);
  const out = work.map((w, k) => {
    const rule = w.mode === "NONE" ? null : ruleFromLine(w.l);
    if (w.mode !== "NONE" && !rule) throw new Error(`baris ${w.i + 1}: jenis transaksi PPN wajib dipilih`);
    const net = w.net0 - shares[k];
    return finishLine(w.l, w.mode, rule, w.qty, w.grossC, w.discC, shares[k], net, lineValues(w.i, w.mode, net, rule, w.l.ppnbm_rate));
  });
  const { totals, groups } = summarize(out); totals.final_discount_type = header.final_discount_type || null;
  const G = groups.map(({ _c, ...g }) => g);
  return { tax_engine_version: TAX_ENGINE_VERSION, rounding_policy: { ...ROUNDING_POLICY }, lines: out, totals, tax_groups: G, tax_rules_snapshot: rulesSnapshot(G, out) };
}

export function computeInvoice(po, billed, fakturActual = null, tolerance = "1") {
  // prev_qty/prev_net = kumulatif invoice SEBELUMNYA; entri berulang untuk baris PO yang sama (multi-DO) diakumulasi otomatis.
  const seen = new Map(); const has = (v) => v !== null && v !== undefined && v !== "";
  const out = billed.map((b, i) => {
    const li = parseInt(b.line_index, 10);
    if (!(li >= 0 && li < po.lines.length)) throw new Error(`baris tagihan ${i + 1}: baris PO tidak ditemukan`);
    const pl = po.lines[li]; const qtyPo = toQ(pl.qty), qty = toQ(b.qty); let pq = toQ(b.prev_qty), pn = toQ(b.prev_net);
    let st = seen.get(li);
    if (st) {
      if ((has(b.prev_qty) && pq.cmp(st.pq) !== 0) || (has(b.prev_net) && pn.cmp(st.pn) !== 0)) throw new Error(`baris tagihan ${i + 1}: prev_qty/prev_net tidak konsisten untuk baris PO yang sama`);
      pq = st.pq.add(st.q); pn = st.pn.add(st.n);
    } else { st = { pq, pn, q: ZERO, n: ZERO }; seen.set(li, st); }
    if (qty.cmp(ZERO) <= 0 || pq.add(qty).cmp(qtyPo) > 0) throw new Error("qty ditagih tidak valid / melebihi qty PO");
    const netPo = toQ(pl.net_amount); const net = pq.add(qty).cmp(qtyPo) === 0 ? c2(netPo.sub(pn)) : c2(netPo.mul(qty).div(qtyPo));
    st.q = st.q.add(qty); st.n = st.n.add(qc(net));
    const rule = pl.taxable ? ruleFromLine(pl) : null;
    const src = { po_line_index: li, qty: String(b.qty), input_vat_creditable: pl.input_vat_creditable, cost_treatment: pl.cost_treatment, acquisition_type: pl.acquisition_type };
    if (pl.ppnbm_rate !== null && pl.ppnbm_rate !== undefined) src.ppnbm_rate = pl.ppnbm_rate;
    return finishLine(src, pl.tax_mode, rule, qty, net, B0, B0, net, lineValues(i, pl.tax_mode, net, rule, rule ? pl.ppnbm_rate : 0));
  });
  const { totals, groups } = summarize(out); const R = (c) => roundUnits(qc(c), 0);
  const faktur = groups.map((g) => ({ trx_code: g.trx_code, tax_code: g.tax_code, facility: g.facility, line_indexes: g.line_indexes,
    dpp: dec(R(g._c.dpp), 0), dpp_other: dec(R(g._c.dpp_other), 0), ppn: dec(R(g._c.ppn), 0), ppn_facility: dec(R(g._c.ppn_facility), 0), ppnbm: dec(R(g._c.ppnbm), 0) }));
  const fs = (k) => faktur.reduce((a, f) => a + BigInt(f[k]), B0);
  const payable = cents(totals.dpp_total) + cents(totals.non_ppn_total) + (fs("ppn") + fs("ppnbm")) * B100;
  const G = groups.map(({ _c, ...g }) => g);
  const res = { tax_engine_version: TAX_ENGINE_VERSION, rounding_policy: { ...ROUNDING_POLICY }, lines: out, totals, tax_groups: G, tax_rules_snapshot: rulesSnapshot(G, out), faktur,
    faktur_totals: { dpp: dec(fs("dpp"), 0), dpp_other: dec(fs("dpp_other"), 0), ppn: dec(fs("ppn"), 0), ppnbm: dec(fs("ppnbm"), 0), ppn_facility: dec(fs("ppn_facility"), 0) },
    expected_payable: d2(payable), rounding_adjustment: d2(payable - cents(totals.grand_total)) };
  if (fakturActual) res.faktur_match = matchFaktur(res.faktur_totals, fakturActual, tolerance);
  return res;
}

export function computeDp(amount, rule, withFaktur) {
  const a = c2(toQ(amount));
  if (!withFaktur || !rule) return { with_faktur: false, amount: d2(a), dpp: null, dpp_other: null, ppn: "0" };
  const v = lineValues(0, "INCLUDE", a, rule, 0), R = (c) => dec(roundUnits(qc(c), 0), 0);
  return { with_faktur: true, amount: d2(a), dpp: R(v.dpp), dpp_other: R(v.nl), ppn: R(v.ppn) };
}
export function settleWithDp(inv, dps) {
  const ft = inv.faktur_totals, total = toQ(inv.expected_payable), wf = dps.filter((d) => d.with_faktur);
  const sum = (arr, k) => arr.reduce((a, d) => a.add(toQ(d[k])), ZERO);
  const dpAmt = sum(dps, "amount"), dpDpp = sum(wf, "dpp"), dpNl = sum(wf, "dpp_other"), dpPpn = sum(wf, "ppn");
  if (dpAmt.cmp(total) > 0) throw new Error("DP melebihi nilai invoice");
  if (dpPpn.cmp(toQ(ft.ppn)) > 0) throw new Error("PPN DP melebihi PPN invoice");
  const fin = toQ(ft.ppn).sub(dpPpn), q = (x) => d2(c2(x));
  return { invoice_total: q(total), dp_amount: q(dpAmt), payable: q(total.sub(dpAmt)),
    final_faktur: { dpp: q(toQ(ft.dpp).sub(dpDpp)), dpp_other: q(toQ(ft.dpp_other).sub(dpNl)), ppn: q(fin) },
    dp_ppn: q(dpPpn), ppn_recognized_total: q(dpPpn.add(fin)), invoice_ppn: q(toQ(ft.ppn)), double_counted: dpPpn.add(fin).cmp(toQ(ft.ppn)) !== 0 };
}
export function matchFaktur(expected, faktur, tolerance = "1") {
  const tol = toQ(tolerance), diffs = {}; let worst = ZERO;
  for (const k of ["dpp", "dpp_other", "ppn", "ppnbm", "total"]) {
    if (expected[k] == null || faktur[k] == null) continue;
    const d = toQ(faktur[k]).sub(toQ(expected[k])); diffs[k] = d2(c2(d)); const a = d.cmp(ZERO) < 0 ? d.neg() : d; if (a.cmp(worst) > 0) worst = a;
  }
  const status = worst.isZero() ? "MATCH" : worst.cmp(tol) <= 0 ? "WARNING" : "NEEDS_APPROVAL";
  return { status, max_abs_diff: d2(c2(worst)), diffs, tolerance: d2(c2(tol)), requires_reason: status === "NEEDS_APPROVAL" };
}
export function engineVersionOf(doc) {
  const v = parseInt((doc || {}).tax_engine_version || LEGACY_ENGINE_VERSION, 10);
  return v === TAX_ENGINE_VERSION ? TAX_ENGINE_VERSION : LEGACY_ENGINE_VERSION;
}
