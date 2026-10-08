// Logika baris Penyesuaian Stok multi gudang (murni, tanpa React — diuji di Node).
// HEADER = default saat baris dibuat (Gudang Default, Project Default); DETAIL = sumber gudang/project/unit,
// stok, ledger & valuasi per baris. Baris yang diubah manual tidak ikut berubah saat default header diganti.

export const ADJ_DEFAULT_KEYS = ["warehouse_id", "project_id"];
export const ADJ_OVERRIDE_FLAG = { warehouse_id: "_whOverride", project_id: "_projectOverride" };
export const ADJ_FIELD_LABEL = { warehouse_id: "Gudang", project_id: "Project" };

let seq = 0;
const newKey = () => `adj-${Date.now().toString(36)}-${(seq += 1)}`;
const val = (o, k) => (o || {})[k] || "";

/** Baris baru: Gudang & Project diisi dari default header saat ini (status "Default"). */
export function newAdjLine(defaults, extra = {}) {
  const line = { _key: newKey(), item_id: "", adjustment: "", uom_id: "", conversion_factor: 1, reason: "", approved_unit_cost: "", unit_id: "" };
  ADJ_DEFAULT_KEYS.forEach((k) => { line[k] = val(defaults, k); line[ADJ_OVERRIDE_FLAG[k]] = false; });
  return { ...line, ...extra };
}

export const isManual = (line, key) => !!(line || {})[ADJ_OVERRIDE_FLAG[key]];

/** Ubah field baris; Gudang/Project yang diubah user ditandai Manual. */
export function setLineField(line, key, value) {
  const next = { ...line, [key]: value };
  if (ADJ_OVERRIDE_FLAG[key]) next[ADJ_OVERRIDE_FLAG[key]] = true;
  return next;
}

/** Default header berubah -> hanya field berstatus Default yang ikut berubah. */
export function propagateDefaults(lines, oldDefaults, newDefaults) {
  let dirty = false;
  const next = (lines || []).map((l) => {
    let cur = l;
    ADJ_DEFAULT_KEYS.forEach((k) => {
      if (val(oldDefaults, k) === val(newDefaults, k) || isManual(l, k)) return;
      if (cur === l) cur = { ...l };
      cur[k] = val(newDefaults, k); dirty = true;
    });
    return cur;
  });
  return { next, dirty };
}

/** Jumlah nilai manual yang BERBEDA dari default (akan ditimpa oleh Terapkan Default). */
export const manualOverrideCount = (lines, defaults) =>
  (lines || []).reduce((n, l) => n + ADJ_DEFAULT_KEYS.filter((k) => isManual(l, k) && (l[k] || "") !== val(defaults, k)).length, 0);

/** Terapkan default header ke semua baris (aksi eksplisit, dengan konfirmasi bila ada override). */
export const applyDefaultsToAll = (lines, defaults) =>
  (lines || []).map((l) => {
    const n = { ...l };
    ADJ_DEFAULT_KEYS.forEach((k) => { n[k] = val(defaults, k); n[ADJ_OVERRIDE_FLAG[k]] = false; });
    return n;
  });

/** Dokumen tersimpan -> baris form (qty disimpan dalam satuan dasar; semua field per baris dianggap Manual). */
export function linesFromDoc(doc, baseUomOf = () => "") {
  return ((doc || {}).lines || []).map((l) => ({
    _key: l.id || newKey(), item_id: l.item_id, adjustment: l.adjustment, uom_id: baseUomOf(l.item_id) || "", conversion_factor: 1,
    reason: l.reason || "", approved_unit_cost: l.approved_unit_cost ?? "", warehouse_id: l.warehouse_id || "", project_id: l.project_id || "",
    unit_id: l.unit_id || "", _whOverride: true, _projectOverride: true,
  }));
}

export const baseDelta = (l) => (Number(l.adjustment) || 0) * (Number(l.conversion_factor) || 1);

/** Kredit stok saat EDIT: backend mereversal movement lama dulu -> stok tersedia = stok kini − delta lama per (barang, gudang). */
export function editStockCredit(originalLines) {
  const c = {};
  (originalLines || []).forEach((l) => {
    if (!l.item_id || !l.warehouse_id) return;
    const k = `${l.item_id}::${l.warehouse_id}`;
    c[k] = (c[k] || 0) - baseDelta(l);
  });
  return c;
}

export function availableFor(stockMap, itemId, warehouseId, credit = {}) {
  if (!itemId || !warehouseId) return null;
  const m = (stockMap || {})[itemId];
  if (!m) return null;
  return (Number(m[warehouseId]) || 0) + (Number(credit[`${itemId}::${warehouseId}`]) || 0);
}

/**
 * Masalah per baris (frontend memberi peringatan; backend tetap hard-block):
 * barang & gudang wajib, qty != 0, stok tidak boleh minus per (barang, gudang BARIS) — disimulasikan berurutan
 * sesuai urutan baris (baris barang+gudang sama diakumulasi).
 */
export function adjLineIssues(lines, stockOf = () => null) {
  const sim = new Map();
  return (lines || []).map((l) => {
    const r = {};
    if (!l.item_id) r.item = "Barang wajib dipilih";
    if (!l.warehouse_id) r.warehouse = "Gudang wajib dipilih";
    const d = baseDelta(l);
    if (!Number.isFinite(Number(l.adjustment)) || Math.abs(d) < 1e-9) r.qty = "Qty Penyesuaian tidak boleh 0";
    if (l.item_id && l.warehouse_id && !r.qty) {
      const k = `${l.item_id}::${l.warehouse_id}`;
      if (!sim.has(k)) { const a = stockOf(l.item_id, l.warehouse_id); sim.set(k, a == null ? null : Number(a)); }
      const before = sim.get(k);
      if (before != null) {
        const after = before + d;
        r.before = before; r.after = after;
        if (after < -1e-9) r.stock = `Melebihi stok gudang (tersedia ${+before.toFixed(6)}, hasil ${+after.toFixed(6)})`;
        sim.set(k, after);
      }
    }
    const issue = ["item", "warehouse", "qty", "stock"].some((x) => r[x]);
    return issue ? r : (r.before != null ? { before: r.before, after: r.after, ok: true } : null);
  });
}

export const adjIssueMessages = (r) => (r && !r.ok ? [r.item, r.warehouse, r.qty, r.stock].filter(Boolean) : []);

export const firstAdjIssueMessage = (issues) => {
  const i = (issues || []).findIndex((x) => adjIssueMessages(x).length);
  return i < 0 ? null : `Baris ${i + 1}: ${adjIssueMessages(issues[i])[0]}`;
};

/** Payload API: qty dikonversi ke satuan dasar (konvensi existing); gudang/project/unit eksplisit per baris. */
export function adjLinesPayload(lines) {
  return (lines || []).map((l) => ({
    item_id: l.item_id, adjustment: baseDelta(l), reason: l.reason || "",
    approved_unit_cost: l.approved_unit_cost === "" || l.approved_unit_cost == null ? null : Number(l.approved_unit_cost),
    warehouse_id: l.warehouse_id || null, project_id: l.project_id || null, unit_id: l.unit_id || null,
  }));
}
