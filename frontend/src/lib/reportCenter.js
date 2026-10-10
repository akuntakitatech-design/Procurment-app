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

// Format sel = format Excel/PDF (qty maks 4 desimal, uang 2 desimal, pemisah ribuan titik); tanggal DD-MM-YYYY = PDF (sel Excel = nilai ISO JSON).
export function formatCell(value, type) {
  if (value === null || value === undefined || value === "") return "-";
  if (NUMERIC_TYPES.has(type)) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "-";
    return type === "money" ? MONEY.format(n) : type === "int" ? INT.format(n) : QTY.format(n);
  }
  if (type === "date") return fmtDay(value);
  return String(value);
}

// Tanggal bisnis ISO (YYYY-MM-DD...) -> DD-MM-YYYY tanpa konversi zona waktu; nilai lain apa adanya.
export function fmtDay(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v ?? ""));
  return m ? `${m[3]}-${m[2]}-${m[1]}` : String(v ?? "");
}

// Filter dari query URL (tautan yang dapat dibagikan): paging & parameter navigasi tidak ikut; validasi tetap server-side.
const NON_FILTER_PARAMS = new Set(["page", "page_size", "open", "tab"]);
export function filtersFromSearch(search = "") {
  const out = {};
  new URLSearchParams(search).forEach((v, k) => { if (!NON_FILTER_PARAMS.has(k) && String(v).trim()) out[k] = String(v).trim(); });
  return out;
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

// Halaman lama /reports (tab MRO Traceability, Lead Time, Pemakaian Unit) -> laporan padanan di Pusat Laporan (P2b).
export const LEGACY_REPORT_TABS = { trace: "mro-traceability", lead: "lead-time", usage: "pemakaian-barang" };
export function legacyReportPath(search = "") {
  const p = new URLSearchParams(search);
  const key = LEGACY_REPORT_TABS[p.get("tab")] || "mro-traceability";
  p.delete("tab");
  const qs = p.toString();
  return `${reportPath(key)}${qs ? `?${qs}` : ""}`;
}

// Kolom tautan drill-down: nomor dokumen sumber (MRO Traceability: mro_no; register/detail: no).
export const DRILL_KEYS = ["mro_no", "no"];
export function drillColumnIndex(cols) {
  for (const k of DRILL_KEYS) {
    const i = (cols || []).findIndex((c) => c.key === k);
    if (i >= 0) return i;
  }
  return -1;
}

// Halaman transaksi gudang (tanpa route detail): `?open=<id>` membuka detail dokumen (drill dari Pusat Laporan).
export function openParam(search) {
  const v = new URLSearchParams(search || "").get("open");
  return v && /^[A-Za-z0-9_-]{1,80}$/.test(v) ? v : null;
}
