// Logika baris Transfer Antar Gudang multi gudang (murni, tanpa React — diuji di Node).
// Prinsip: HEADER = nilai default saat baris dibuat; DETAIL = snapshot per baris (sumber posting).
//   - Baris baru mewarisi default header TERBARU saat baris dibuat.
//   - Tiap field baris punya status eksplisit: "default" (mengikuti header) vs "manual" (override user).
//   - Default header berubah -> HANYA field berstatus "default" yang ikut; field "manual" tidak pernah ditimpa diam-diam.
//   - "Terapkan Default ke Semua Baris" = aksi eksplisit user (setelah konfirmasi) -> semua field kembali "default".
export const TRANSFER_DEFAULT_KEYS = ["project_id", "from_warehouse_id", "to_warehouse_id"];
export const OVERRIDE_FLAG = { project_id: "_projectOverride", from_warehouse_id: "_fromOverride", to_warehouse_id: "_toOverride", unit_id: "_unitOverride" };
export const FIELD_LABEL = { project_id: "Project", from_warehouse_id: "Gudang Asal", to_warehouse_id: "Gudang Tujuan" };

const val = (o, k) => (o || {})[k] || "";
const newKey = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `tmp-${Date.now()}-${Math.random().toString(36).slice(2)}`);

/** Baris baru: field default diisi dari header saat ini dan bertanda "default" (bukan manual). */
export function newTransferLine(defaults, extra = {}) {
  const line = { _key: newKey(), item_id: "", qty: 1, uom_id: "", conversion_factor: 1, unit: "", notes: "", unit_id: "", _unitOverride: false };
  TRANSFER_DEFAULT_KEYS.forEach((k) => { line[k] = val(defaults, k); line[OVERRIDE_FLAG[k]] = false; });
  return { ...line, ...extra };
}

/** True bila field baris sudah diubah manual oleh user (state eksplisit, bukan perbandingan label/teks). */
export const isManual = (line, key) => !!(line || {})[OVERRIDE_FLAG[key]];

/** User mengubah satu field baris -> nilai baru + tandai manual untuk field default/unit. */
export function setLineField(line, key, value) {
  const x = { ...line, [key]: value };
  if (OVERRIDE_FLAG[key]) x[OVERRIDE_FLAG[key]] = true;
  return x;
}

/**
 * Header default berubah: field berstatus "default" mengikuti default baru; field "manual" dipertahankan.
 * Return { next, dirty } (dirty=false bila tidak ada baris yang berubah).
 */
export function propagateDefaults(lines, oldDefaults, newDefaults) {
  const changed = TRANSFER_DEFAULT_KEYS.filter((k) => val(oldDefaults, k) !== val(newDefaults, k));
  if (!changed.length || !(lines || []).length) return { next: lines, dirty: false };
  let dirty = false;
  const next = lines.map((l) => {
    let x = l;
    changed.forEach((k) => {
      if (isManual(l, k)) return;
      const nv = val(newDefaults, k);
      if (val(x, k) !== nv) { x = { ...x, [k]: nv }; dirty = true; }
    });
    return x;
  });
  return { next: dirty ? next : lines, dirty };
}

/** Jumlah field manual yang AKAN ditimpa oleh "Terapkan Default ke Semua Baris" (untuk teks konfirmasi). */
export function manualOverrideCount(lines, defaults) {
  let n = 0;
  (lines || []).forEach((l) => TRANSFER_DEFAULT_KEYS.forEach((k) => { if (isManual(l, k) && val(l, k) !== val(defaults, k)) n += 1; }));
  return n;
}

/** Aksi eksplisit: semua baris diisi ulang dari default header terbaru; status kembali "default". */
export function applyDefaultsToAll(lines, defaults) {
  return (lines || []).map((l) => {
    const x = { ...l };
    TRANSFER_DEFAULT_KEYS.forEach((k) => { x[k] = val(defaults, k); x[OVERRIDE_FLAG[k]] = false; });
    return x;
  });
}

/** Baris dari dokumen tersimpan (mode edit): nilai baris = snapshot independen -> status manual. */
export function linesFromDoc(doc) {
  return ((doc || {}).lines || []).map((l) => ({
    ...l, _key: l.id || newKey(), from_warehouse_id: l.from_warehouse_id || "", to_warehouse_id: l.to_warehouse_id || "",
    project_id: l.project_id || "", unit_id: l.unit_id || "",
    _projectOverride: true, _fromOverride: true, _toOverride: true, _unitOverride: true,
  }));
}

export const baseQty = (l) => (Number(l.qty) || 0) * (Number(l.conversion_factor) || 1);

/**
 * Kredit stok saat EDIT: movement dokumen ini direversal dulu oleh backend, jadi stok yang tersedia
 * = stok saat ini + qty yang dulu keluar dari (barang, gudang asal) − qty yang dulu masuk ke (barang, gudang tujuan).
 */
export function editStockCredit(originalLines) {
  const c = {};
  (originalLines || []).forEach((l) => {
    if (!l.item_id) return;
    const q = baseQty(l);
    if (l.from_warehouse_id) c[`${l.item_id}::${l.from_warehouse_id}`] = (c[`${l.item_id}::${l.from_warehouse_id}`] || 0) + q;
    if (l.to_warehouse_id) c[`${l.item_id}::${l.to_warehouse_id}`] = (c[`${l.item_id}::${l.to_warehouse_id}`] || 0) - q;
  });
  return c;
}

/** Stok tersedia untuk (barang, gudang asal BARIS). stockMap: {itemId: {warehouseId: stock}}; null = belum termuat. */
export function availableFor(stockMap, itemId, warehouseId, credit = {}) {
  if (!itemId || !warehouseId) return null;
  const m = (stockMap || {})[itemId];
  if (!m) return null;
  return (Number(m[warehouseId]) || 0) + (Number(credit[`${itemId}::${warehouseId}`]) || 0);
}

/**
 * Masalah per baris Transfer (validasi frontend; backend tetap hard-block):
 * gudang asal/tujuan wajib, asal != tujuan, qty > 0, stok cukup per (barang, gudang asal LINE) secara agregat.
 * stockOf(itemId, warehouseId) -> number | null (null = belum termuat / di luar cakupan -> diserahkan ke backend).
 */
export function transferLineIssues(lines, stockOf = () => null) {
  const need = new Map();
  (lines || []).forEach((l) => {
    if (!l.item_id || !l.from_warehouse_id) return;
    const k = `${l.item_id}::${l.from_warehouse_id}`;
    need.set(k, (need.get(k) || 0) + baseQty(l));
  });
  return (lines || []).map((l) => {
    const r = {};
    if (!l.item_id) r.item = "Barang wajib dipilih";
    if (!l.from_warehouse_id) r.from = "Gudang Asal wajib dipilih";
    if (!l.to_warehouse_id) r.to = "Gudang Tujuan wajib dipilih";
    if (l.from_warehouse_id && l.from_warehouse_id === l.to_warehouse_id) r.same = "Gudang Asal dan Gudang Tujuan tidak boleh sama";
    if (!(Number(l.qty) > 0)) r.qty = "Qty harus lebih dari 0";
    if (l.item_id && l.from_warehouse_id) {
      const avail = stockOf(l.item_id, l.from_warehouse_id);
      const required = need.get(`${l.item_id}::${l.from_warehouse_id}`) || 0;
      if (avail != null && required > Number(avail) + 1e-9) {
        r.available = Number(avail); r.required = required;
        r.stock = `Stok di gudang asal tidak cukup (tersedia ${Number(avail)}, diminta ${required})`;
      }
    }
    return Object.keys(r).length ? r : null;
  });
}

export const issueMessages = (r) => (r ? [r.item, r.from, r.to, r.same, r.qty, r.stock].filter(Boolean) : []);

export const firstIssueMessage = (issues) => {
  const i = (issues || []).findIndex(Boolean);
  if (i < 0) return null;
  return `Baris ${i + 1}: ${issueMessages(issues[i])[0]}`;
};

/** Payload API: kirim field baris eksplisit (gudang/project/unit per baris), tanpa state UI. */
export function linesPayload(lines) {
  return (lines || []).map((l) => ({
    item_id: l.item_id, qty: l.qty, uom_id: l.uom_id || undefined, conversion_factor: l.conversion_factor, unit: l.unit, notes: l.notes || "",
    from_warehouse_id: l.from_warehouse_id || null, to_warehouse_id: l.to_warehouse_id || null,
    project_id: l.project_id || null, unit_id: l.unit_id || null,
  }));
}

/** Opsi master: pencarian kode + nama, nilai terpilih tampil NAMA saja. */
export function nameOnlyOptions(rows, extra = () => "") {
  return (rows || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${extra(d)}`, selectedLabel: d.name }));
}
