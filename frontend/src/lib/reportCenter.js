// Helper murni Pusat Laporan (tanpa React) — dipakai ReportCenter.jsx & diuji node.
// Backend = source of truth: kolom, total, scope, dan redaksi harga dihitung server; UI hanya menampilkan.

export const NUMERIC_TYPES = new Set(["qty", "money", "int"]);

// Query string filter laporan. Nilai kosong dibuang; tanggal dikirim apa adanya (YYYY-MM-DD lokal/WIB).
export function buildQuery(filters = {}, extra = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...filters, ...extra })) {
    if (v === undefined || v === null) continue;
    const s = String(v).trim();
    if (s) p.set(k, s);
  }
  return p.toString();
}

// Tanggal untuk <input type="date">: hanya terima YYYY-MM-DD (tanpa konversi zona waktu).
export function isIsoDay(v) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(v || ""));
}

export function validateFilters(f = {}, defs = []) {
  for (const d of defs || []) {
    if (d.type === "date" && f[d.key] && !isIsoDay(f[d.key])) return `${d.label} tidak valid.`;
  }
  if (f.date_from && !isIsoDay(f.date_from)) return "Tanggal Awal tidak valid.";
  if (f.date_to && !isIsoDay(f.date_to)) return "Tanggal Akhir tidak valid.";
  if (f.date_from && f.date_to && f.date_from > f.date_to) return "Tanggal Awal tidak boleh melebihi Tanggal Akhir.";
  return null;
}

const nf = (opts) => new Intl.NumberFormat("id-ID", opts);
const QTY = nf({ maximumFractionDigits: 4 });
const MONEY = nf({ minimumFractionDigits: 2, maximumFractionDigits: 2 });
const INT = nf({ maximumFractionDigits: 0 });

// Format sel = format Excel/PDF (qty maks 4 desimal, uang 2 desimal, pemisah ribuan titik).
export function formatCell(value, type) {
  if (value === null || value === undefined || value === "") return "-";
  if (NUMERIC_TYPES.has(type)) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "-";
    return type === "money" ? MONEY.format(n) : type === "int" ? INT.format(n) : QTY.format(n);
  }
  return String(value);
}

// Export diizinkan? (izin export + batas baris tegas dari server; tidak memotong data).
export function exportState(res, fmt, canExport) {
  if (!canExport) return { ok: false, reason: "Anda tidak memiliki izin export." };
  const lim = res?.export_limits?.[fmt];
  const n = res?.total_rows ?? 0;
  if (lim && n > lim) {
    const label = fmt === "pdf" ? "PDF" : "Excel";
    return { ok: false, reason: `Data ${INT.format(n)} baris melebihi batas Export ${label} (${INT.format(lim)} baris). Persempit filter.` };
  }
  return { ok: true, reason: "" };
}

export function reportPath(key) {
  return `/report-center/${encodeURIComponent(key)}`;
}
