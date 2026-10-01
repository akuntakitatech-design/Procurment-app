import { toNum } from "@/lib/format";

// ---------------------------------------------------------------------------
// Shared NON-BLOCKING completeness validation for transaction forms.
// This is warning-only — it never blocks. Real/hard business validations stay
// where they are (SPK over qty, permissions, tenant isolation, stock, budget
// HARD_BLOCK, approval, lifecycle, etc).
// ---------------------------------------------------------------------------

export const isEmptyVal = (v) =>
  v == null || (typeof v === "string" && v.trim() === "") || v === false;

// A completely empty/unused item row must NOT trigger warnings. A row becomes
// "active" (worth validating) once any meaningful field is filled: the item is
// picked, a note is typed, or a location (warehouse/project/unit) is chosen.
export function isItemRowActive(l) {
  if (!l) return false;
  if (l.item_id) return true;
  if (String(l.notes || "").trim()) return true;
  if (l.warehouse_id || l.project_id || l.unit_id) return true;
  return false;
}

/**
 * Build a grouped, specific completeness warning.
 * @param {object} p
 * @param {object} p.h header state
 * @param {array}  p.lines item rows
 * @param {array}  p.headerFields [{ key, label, get? }]
 * @param {array}  p.itemFields   [{ key, label, get?, check? }] label = full phrase e.g. "Qty belum diisi"
 * @returns {{ header: string[], items: string[], hasAny: boolean }}
 */
export function buildTxnWarnings({ h = {}, lines = [], headerFields = [], itemFields = [] }) {
  const header = [];
  for (const f of headerFields) {
    const v = f.get ? f.get(h) : h[f.key];
    if (isEmptyVal(v)) header.push(`${f.label} belum diisi`);
  }

  const items = [];
  (lines || []).forEach((l, idx) => {
    if (!isItemRowActive(l)) return;
    const rowNo = idx + 1;
    for (const f of itemFields) {
      const missing = f.check ? f.check(l) : isEmptyVal(f.get ? f.get(l) : l[f.key]);
      if (missing) items.push(`Baris ${rowNo} — ${f.label}`);
    }
  });

  return { header, items, hasAny: header.length > 0 || items.length > 0 };
}

// --- reusable item field configs -------------------------------------------
const F_ITEM = { key: "item_id", label: "Barang belum dipilih" };
const F_QTY = { key: "qty", label: "Qty belum diisi", check: (l) => !(toNum(l.qty) > 0) };
const F_SATUAN = { key: "unit", label: "Satuan belum diisi", check: (l) => !(l.uom_id || l.unit) };
const F_GUDANG = { key: "warehouse_id", label: "Gudang belum diisi" };
const F_PROYEK = { key: "project_id", label: "Proyek belum diisi" };
const F_UNIT = { key: "unit_id", label: "Unit/Aset belum diisi" };

export const ITEM_FIELDS_FULL = [F_ITEM, F_QTY, F_SATUAN, F_GUDANG, F_PROYEK, F_UNIT];
export const ITEM_FIELDS_BASIC = [F_ITEM, F_QTY, F_SATUAN];
// DO rows always carry item_id from the PO pull; validate qty + locations.
export const ITEM_FIELDS_DO = [F_QTY, F_SATUAN, F_GUDANG, F_PROYEK, F_UNIT];

// --- module header configs --------------------------------------------------
export const HEADER_FIELDS = {
  mro: [
    { key: "requester", label: "Pemohon" },
    { key: "division_id", label: "Divisi" },
    { key: "date", label: "Tanggal MRO" },
    { key: "default_project_id", label: "Proyek Default" },
    { key: "default_warehouse_id", label: "Gudang Default" },
    { key: "default_unit_id", label: "Unit/Aset Default" },
  ],
  ro: [
    { key: "requester", label: "Pemohon" },
    { key: "division_id", label: "Divisi" },
    { key: "date", label: "Tanggal" },
    { key: "default_warehouse_id", label: "Gudang Default" },
  ],
  po: [
    { key: "supplier_id", label: "Supplier" },
    { key: "date", label: "Tanggal" },
    { key: "division_id", label: "Divisi" },
    { key: "default_warehouse_id", label: "Gudang Default" },
  ],
  do: [
    { key: "supplier_id", label: "Supplier" },
    { key: "date", label: "Tanggal Penerimaan" },
    { key: "default_warehouse_id", label: "Gudang Default" },
  ],
  mi: [
    { key: "division_id", label: "Divisi" },
    { key: "default_warehouse_id", label: "Gudang Default" },
    { key: "receiver", label: "Penerima" },
  ],
};

export const ITEM_FIELDS = {
  mro: ITEM_FIELDS_FULL,
  ro: ITEM_FIELDS_FULL,
  po: ITEM_FIELDS_FULL,
  do: ITEM_FIELDS_DO,
  mi: ITEM_FIELDS_FULL,
};
