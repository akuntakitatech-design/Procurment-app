// Logika baris Pinjam Barang multi gudang (murni, tanpa React — diuji di Node).
// Prinsip sama dengan Transfer: HEADER = default saat baris dibuat; DETAIL = snapshot per baris (sumber posting & return).
// Helper generik (status Default/Manual, propagasi default, terapkan ke semua baris, kredit stok edit) dipakai ulang
// dari transferLines.js TANPA mengubah file Transfer; yang khusus Pinjam hanya label & validasi.
import {
  OVERRIDE_FLAG, isManual, setLineField, propagateDefaults, manualOverrideCount, applyDefaultsToAll,
  linesFromDoc, baseQty, editStockCredit, availableFor, linesPayload, nameOnlyOptions, newTransferLine,
} from "./transferLines.js";

export { OVERRIDE_FLAG, isManual, setLineField, propagateDefaults, manualOverrideCount, applyDefaultsToAll, linesFromDoc, baseQty, editStockCredit, availableFor, linesPayload, nameOnlyOptions };

export const LOAN_DEFAULT_KEYS = ["project_id", "from_warehouse_id", "to_warehouse_id"];
export const LOAN_FIELD_LABEL = { project_id: "Project", from_warehouse_id: "Gudang Pemberi", to_warehouse_id: "Gudang Peminjam" };

/** Baris Pinjaman baru: Project/Gudang Pemberi/Gudang Peminjam diisi dari default header saat ini (status "Default"). */
export const newLoanLine = (defaults, extra = {}) => newTransferLine(defaults, extra);

/**
 * Masalah per baris Pinjaman (frontend memberi peringatan; backend tetap hard-block):
 * Gudang Pemberi/Peminjam wajib, Pemberi != Peminjam, qty > 0, stok cukup per (barang, Gudang Pemberi LINE) secara agregat.
 */
export function loanLineIssues(lines, stockOf = () => null) {
  const need = new Map();
  (lines || []).forEach((l) => {
    if (!l.item_id || !l.from_warehouse_id) return;
    const k = `${l.item_id}::${l.from_warehouse_id}`;
    need.set(k, (need.get(k) || 0) + baseQty(l));
  });
  return (lines || []).map((l) => {
    const r = {};
    if (!l.item_id) r.item = "Barang wajib dipilih";
    if (!l.from_warehouse_id) r.from = "Gudang Pemberi wajib dipilih";
    if (!l.to_warehouse_id) r.to = "Gudang Peminjam wajib dipilih";
    if (l.from_warehouse_id && l.from_warehouse_id === l.to_warehouse_id) r.same = "Gudang Pemberi dan Gudang Peminjam tidak boleh sama";
    if (!(Number(l.qty) > 0)) r.qty = "Qty harus lebih dari 0";
    if (l.item_id && l.from_warehouse_id) {
      const avail = stockOf(l.item_id, l.from_warehouse_id);
      const required = need.get(`${l.item_id}::${l.from_warehouse_id}`) || 0;
      if (avail != null && required > Number(avail) + 1e-9) {
        r.available = Number(avail); r.required = required;
        r.stock = `Stok di gudang pemberi tidak cukup (tersedia ${Number(avail)}, diminta ${required})`;
      }
    }
    return Object.keys(r).length ? r : null;
  });
}

export const loanIssueMessages = (r) => (r ? [r.item, r.from, r.to, r.same, r.qty, r.stock].filter(Boolean) : []);

export const firstLoanIssueMessage = (issues) => {
  const i = (issues || []).findIndex(Boolean);
  if (i < 0) return null;
  return `Baris ${i + 1}: ${loanIssueMessages(issues[i])[0]}`;
};

/** Arah Return untuk ditampilkan: keluar dari Gudang Peminjam line, masuk ke Gudang Pemberi line (tidak dipilih ulang user). */
export const returnDirection = (l) => `${(l || {}).to_name || "-"} → ${(l || {}).from_name || "-"}`;

/** Validasi qty return per baris (frontend): 0 < qty <= outstanding baris. */
export function returnQtyIssue(qty, outstanding) {
  const q = Number(qty);
  if (!(q > 0)) return "Qty return harus lebih dari 0";
  if (q > Number(outstanding || 0) + 1e-9) return `Qty return melebihi outstanding (${Number(outstanding || 0)})`;
  return null;
}


/** Masalah qty untuk baris yang dipilih di form Return: { [loan_line_id]: pesan | null }. */
export function returnIssues(rows, sel) {
  const out = {};
  (rows || []).forEach((r) => {
    if (!sel || !(r.loan_line_id in sel)) return;
    out[r.loan_line_id] = returnQtyIssue(sel[r.loan_line_id], r.outstanding);
  });
  return out;
}
