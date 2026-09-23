const HEADER_FIELDS = [
  "division_id",
  "spk",
  "default_warehouse_id",
  "default_project_id",
  "default_unit_id",
  "requester",
  "department",
  "need_date",
  "supplier_id",
  "payment_term",
  "currency",
  "eta",
  "supplier_bank_id",
  "default_tax_id",
  "tax_inclusive",
];

const empty = (v) => v === undefined || v === null || v === "";

/**
 * Derive a transaction header from all pulled source rows.
 * If every source agrees, the header inherits that value. If sources conflict,
 * ID/text defaults are cleared so the line-level dimensions remain authoritative.
 */
export function inheritSourceHeader(current, rows) {
  const next = { ...current };
  const headers = (rows || []).map((r) => r?.source_header || r?._sourceHeader).filter(Boolean);
  if (!headers.length) return next;

  for (const key of HEADER_FIELDS) {
    const values = headers.map((h) => h?.[key]).filter((v) => !empty(v));
    const uniq = [...new Set(values.map((v) => typeof v === "boolean" ? String(v) : String(v)))];
    if (uniq.length === 1) {
      const sample = values[0];
      next[key] = typeof sample === "boolean" ? sample : sample;
    } else if (uniq.length > 1) {
      // Mixed source headers: never pretend one header applies to every line.
      next[key] = key === "tax_inclusive" ? false : "";
    }
  }
  return next;
}
