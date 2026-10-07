// Helper murni Nilai Awal Persediaan / Koreksi Saldo Awal (tanpa React) — dipakai OpeningValuation, OpeningCorrection,
// dialog Dashboard, dan diuji node. Backend tetap source of truth (izin & status dihitung server).

export const OPENING_STATUS_LABEL = {
  valued: "Sudah Dinilai",
  ready: "Siap Ditetapkan",
  needs_replay: "Perlu Revaluasi",
  no_source: "Tidak Ada Nilai Sumber",
};

export const OPENING_STATUS_TONE = {
  valued: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300",
  ready: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300",
  needs_replay: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300",
  no_source: "bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-300",
};

// Hak akses: melihat nilai = view_purchase_price; aksi (Tetapkan, Tetapkan Massal, Dry Run & Apply Revaluasi) =
// view_purchase_price AND stock_adjustment. `can` = useAuth().can (engine izin existing, custom role ikut).
export function valuationAccess(can) {
  const canView = !!(can && can("view_purchase_price"));
  return { canView, canApply: canView && !!can("stock_adjustment") };
}

export const rowKey = (r) => `${r.item_id}::${r.warehouse_id}`;

// Baris /valuation/opening-candidates yang boleh dicentang untuk Tetapkan Massal: belum dinilai, tidak diblokir mutasi,
// punya kandidat dari Import Saldo Awal, qty pool = qty saldo awal. Server tetap memvalidasi ulang (hanya 'Siap Ditetapkan').
export function massEligible(r) {
  if (!r || r.status === "valued" || r.opening_blocked_reason) return false;
  if (!(Number(r.opening_cost_candidate) > 0) || r.opening_import_qty == null) return false;
  return Math.abs(Number(r.opening_import_qty) - Number(r.qty_existing)) < 1e-9;
}

export function toggleKey(sel, k) {
  const next = new Set(sel);
  if (next.has(k)) next.delete(k); else next.add(k);
  return next;
}

export function eligibleKeys(rows) {
  return new Set((rows || []).filter(massEligible).map(rowKey));
}

export function keysPayload(sel) {
  return [...sel].map((k) => { const [item_id, warehouse_id] = k.split("::"); return { item_id, warehouse_id }; });
}

// Preview Tetapkan Massal dari /valuation/opening-status (sumber opening_inventory): hanya 'ready' yang akan ditetapkan.
export function massPreview(statusRows, sel) {
  const picked = (statusRows || []).filter((r) => sel.has(rowKey(r)));
  const apply = picked.filter((r) => r.status === "ready");
  const found = new Set(picked.map(rowKey));
  return {
    apply,
    skip: picked.filter((r) => r.status !== "ready"),
    missing: [...sel].filter((k) => !found.has(k)),
    value: apply.reduce((a, r) => a + (Number(r.opening_value) || 0), 0),
  };
}

// Dialog Dashboard: tampilkan yang perlu tindakan (Sudah Dinilai disembunyikan, cukup dihitung).
export function needsAction(rows) {
  return (rows || []).filter((r) => r.status !== "valued");
}
