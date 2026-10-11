// P6 — Export Excel/PDF daftar transaksi lewat engine Pusat Laporan (/api/report-center/<key>/export.<fmt>).
// Query export = parameter daftar yang sedang aktif (filter/tab, pencarian, periode, sort) TANPA halaman,
// sehingga backend mengekspor SELURUH hasil filter. Batas mengikuti Pusat Laporan (ditegakkan server: 422).
import { exportState } from "./reportCenter.js";

export const LIST_EXPORT_LIMITS = { xlsx: 100000, pdf: 5000 };

// URL daftar (useServerList) -> kunci ReportSpec export daftar transaksi
export const LIST_EXPORT_KEYS = {
  "/mro": "txn-mro", "/ro": "txn-ro", "/po": "txn-po", "/do": "txn-do", "/mi": "txn-mi",
  "/transfers": "txn-transfer", "/loans": "txn-loan", "/adjustments": "txn-adjustment", "/opname": "txn-opname",
  "/vendor-invoices": "txn-invoice", "/vendor-invoices/do-billing": "txn-do-billing",
};

const DROP = new Set(["page", "page_size", "facets", "counts"]);

export function listExportQuery(params = {}) {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (DROP.has(k) || v === undefined || v === null || v === "") return;
    sp.append(k, String(v));
  });
  return sp.toString();
}

// Status tombol export berdasarkan jumlah hasil daftar saat ini (server tetap memvalidasi ulang).
export function listExportState(total, fmt, canExport) {
  return exportState({ export_limits: LIST_EXPORT_LIMITS, total_rows: Number(total) || 0 }, fmt, canExport);
}
