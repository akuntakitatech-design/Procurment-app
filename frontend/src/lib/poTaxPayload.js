// F2 — payload preview PPN & pemetaan hasil backend ke baris form (murni, tanpa perhitungan pajak).
// Frontend hanya mengirim INPUT (qty, harga, diskon, perlakuan, Jenis PPN); nominal resmi dari backend.
export const TAX_MODES = ["EXCLUDE", "INCLUDE", "NONE"];

export function normalizeMode(m) {
  const x = String(m || "").toUpperCase();
  return TAX_MODES.includes(x) ? x : "NONE";
}

/** Body POST /api/po/tax-preview. Baris tanpa barang dilewati (sama dengan jalur simpan). */
export function buildTaxPreviewPayload({ h = {}, lines = [], poId = null }) {
  return {
    po_id: poId || undefined, supplier_id: h.supplier_id || undefined, date: h.date, division_id: h.division_id,
    final_discount_type: h.final_discount_type, final_discount_value: h.final_discount_value,
    lines: (lines || []).filter((l) => l.item_id).map((l) => {
      const mode = normalizeMode(l.tax_mode);
      return { id: l.id, item_id: l.item_id, uom_id: l.uom_id, qty: l.qty, price: l.price, discount: l.discount,
        display_qty: l.display_qty, display_price: l.display_price, conversion_factor: l.conversion_factor,
        tax_id: mode === "NONE" ? null : (l.tax_id || null), tax_mode: mode };
    }),
  };
}

/** {indeks baris form: baris hasil backend} — baris tanpa barang tidak ikut dikirim sehingga dilewati. */
export function mapPreviewByIndex(lines = [], data = null) {
  const m = {}; let k = 0;
  (lines || []).forEach((l, i) => { if (l.item_id) { m[i] = data?.lines?.[k] || null; k += 1; } });
  return m;
}

/** Patch perlakuan PPN baris: Non-PKP selalu Tanpa PPN; Tanpa PPN tidak membawa Jenis PPN. */
export function taxPatchV2(taxId, mode, supplierPkp) {
  const m = !supplierPkp ? "NONE" : normalizeMode(mode);
  return { tax_id: m === "NONE" ? "" : (taxId || ""), tax_mode: m, _taxInitialized: true };
}

/** Estimasi budget SPK pra-simpan (endpoint existing memakai base x (1 + tax%)): untuk PO v2 tarif diambil dari
 *  hasil backend — Include/fasilitas/Tanpa PPN = 0 (total = nilai bersih), Exclude = tarif efektif backend. */
export function budgetLinesV2(lines = [], byIndex = {}) {
  return (lines || []).map((l, i) => {
    const v = byIndex?.[i];
    return { ...l, tax: !v || v.tax_inclusive ? 0 : Number(v.tax) || 0 };
  });
}
