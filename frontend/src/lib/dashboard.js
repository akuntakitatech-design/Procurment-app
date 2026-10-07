// Helper murni Dashboard Procurement & Finance (tanpa React) — dipakai halaman Dashboard & diuji node.
// Semua angka berasal dari backend /api/dashboard/control-center; di sini hanya label, warna, format & link drill-down.

export const TONES = {
  navy: { icon: "bg-[#EEF3F9] text-[#2C4A6E]", bar: "#3D5A80", text: "text-[#2C4A6E]" },
  blue: { icon: "bg-[#EDF4FB] text-[#3F6E9C]", bar: "#7FA7CF", text: "text-[#3F6E9C]" },
  green: { icon: "bg-[#EEF6F2] text-[#3D7A62]", bar: "#5E9C82", text: "text-[#3D7A62]" },
  amber: { icon: "bg-[#FBF4E8] text-[#9A6A22]", bar: "#D4A04E", text: "text-[#9A6A22]" },
  red: { icon: "bg-[#FBF0F0] text-[#A34B4B]", bar: "#C46A6A", text: "text-[#A34B4B]" },
  indigo: { icon: "bg-[#EFF0FA] text-[#4D5A9E]", bar: "#5B6FB0", text: "text-[#4D5A9E]" },
  slate: { icon: "bg-[#F1F3F6] text-[#5B6676]", bar: "#A3ADBA", text: "text-[#5B6676]" },
};

// document_status (internal key backend) -> label Indonesia + warna donut (muted, tidak neon)
export const STATUS_META = {
  "Draft": { label: "Draft", color: "#B4BCC8" },
  "Waiting Approval 1": { label: "Menunggu Approval 1", color: "#D9B26A" },
  "Ready Approval 2": { label: "Siap Diajukan Approval 2", color: "#8FB3D9" },
  "Waiting Approval 2": { label: "Menunggu Approval 2", color: "#C98F3B" },
  "Waiting Approval": { label: "Menunggu Persetujuan", color: "#E2C68F" },
  "Approved": { label: "Disetujui", color: "#6FA58D" },
  "Closed": { label: "Ditutup", color: "#5B6FB0" },
  "Rejected": { label: "Ditolak", color: "#C98080" },
  "Cancelled": { label: "Dibatalkan", color: "#D5D9DF" },
};
export const statusLabel = (s) => STATUS_META[s]?.label || s || "-";
export const statusColor = (s) => STATUS_META[s]?.color || "#C7CDD6";

const pad = (n) => String(n).padStart(2, "0");
export const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const lastDay = (y, m) => new Date(y, m + 1, 0);

export const PERIODS = [
  { key: "this_month", label: "Bulan Ini" },
  { key: "last_month", label: "Bulan Lalu" },
  { key: "last_3", label: "3 Bulan Terakhir" },
  { key: "this_year", label: "Tahun Ini" },
  { key: "all", label: "Semua Periode" },
];

/** Rentang tanggal preset periode (default Bulan Ini). */
export function periodRange(key, today = new Date()) {
  const y = today.getFullYear(), m = today.getMonth();
  if (key === "all") return { period: "all", date_from: "", date_to: "" };
  if (key === "last_month") return { date_from: iso(new Date(y, m - 1, 1)), date_to: iso(lastDay(y, m - 1)) };
  if (key === "last_3") return { date_from: iso(new Date(y, m - 2, 1)), date_to: iso(lastDay(y, m)) };
  if (key === "this_year") return { date_from: `${y}-01-01`, date_to: `${y}-12-31` };
  return { date_from: iso(new Date(y, m, 1)), date_to: iso(lastDay(y, m)) };
}

export function periodText(key, today = new Date()) {
  if (key === "this_month") return today.toLocaleDateString("id-ID", { month: "long", year: "numeric" });
  return PERIODS.find((p) => p.key === key)?.label || "";
}

/** Query string untuk endpoint control-center. */
export function ccParams(f, today = new Date()) {
  const r = periodRange(f.period || "this_month", today);
  const p = { ...r, division_id: f.division_id || "", project_id: f.project_id || "", supplier_id: f.supplier_id || "" };
  Object.keys(p).forEach((k) => !p[k] && delete p[k]);
  return p;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
export const monthLabel = (ym) => { const [y, m] = String(ym || "").split("-"); return m ? `${MONTHS[Number(m) - 1]} ${y.slice(2)}` : ym; };

/** Rupiah ringkas: Rp 3,42 M / Rp 985 jt / Rp 12 rb. */
export function compactRupiah(v) {
  if (v == null) return "***";
  const n = Number(v) || 0, a = Math.abs(n), sign = n < 0 ? "-" : "";
  const fmt = (x, d) => x.toLocaleString("id-ID", { maximumFractionDigits: d, minimumFractionDigits: 0 });
  if (a >= 1e12) return `${sign}Rp ${fmt(a / 1e12, 2)} T`;
  if (a >= 1e9) return `${sign}Rp ${fmt(a / 1e9, 2)} M`;
  if (a >= 1e6) return `${sign}Rp ${fmt(a / 1e6, a >= 1e8 ? 0 : 1)} jt`;
  if (a >= 1e3) return `${sign}Rp ${fmt(a / 1e3, 0)} rb`;
  return `${sign}Rp ${fmt(a, 0)}`;
}

// Kartu KPI -> tujuan drill-down (filter list existing via rf_* yang backward-compatible).
const PO_KIND = new Set(["waiting_a1", "ready_a2", "waiting_a2", "waiting_approval", "approved", "not_received", "partial", "late", "valid"]);
const INV_KIND = new Set(["unpaid", "payable", "due_soon", "overdue"]);

export function drillLink(kind, f = {}, _perms = {}, today = new Date()) {
  const r = periodRange(f.period || "this_month", today);
  const q = new URLSearchParams();
  const put = (k, v) => v && q.set(k, v);
  const dims = () => { put("date_from", r.date_from); put("date_to", r.date_to); put("rf_division_id", f.division_id); put("rf_project_id", f.project_id); put("rf_supplier_id", f.supplier_id); };
  // Semua kartu PO (termasuk Approval 2) -> list PO dgn predikat sama, agar jumlah list = angka kartu.
  if (PO_KIND.has(kind)) { q.set("rf_kind", kind); dims(); return `/po?${q}`; }
  if (kind === "po_all") { dims(); return `/po${q.toString() ? `?${q}` : ""}`; }
  if (kind === "mro_open" || kind === "ro_open") { q.set("rf_kind", "open"); dims(); q.delete("rf_supplier_id"); return `/${kind.split("_")[0]}?${q}`; }
  if (INV_KIND.has(kind)) { q.set("rf_kind", kind === "payable" ? "unpaid" : kind); dims(); return `/invoice?${q}`; }
  if (kind === "invoice_unbilled") { q.set("tab", "do"); q.set("rf_kind", "unbilled"); dims(); return `/invoice?${q}`; }
  if (kind === "dp_paid" || kind === "dp_unallocated") return "/dp-supplier";
  return "/";
}

export const RF_LABEL = {
  waiting_a1: "Menunggu Approval 1", waiting_approval: "Menunggu Approval", ready_a2: "Siap Diajukan Approval 2", waiting_a2: "Menunggu Approval 2",
  approved: "PO Disetujui", not_received: "PO Belum Diterima", partial: "PO Diterima Sebagian", late: "PO Terlambat",
  valid: "PO Valid", open: "Belum Diproses", unpaid: "Invoice Belum Dibayar", due_soon: "Jatuh Tempo ≤ 7 Hari",
  overdue: "Lewat Jatuh Tempo", unbilled: "Invoice Belum Diterima",
};

export const ATTENTION_TABS = [
  { key: "all", label: "Semua" },
  { key: "approval", label: "Menunggu Approval" },
  { key: "not_received", label: "Belum Diterima" },
  { key: "unbilled", label: "Invoice Belum Diterima", finance: true },
  { key: "unpaid", label: "Invoice Belum Dibayar", finance: true },
  { key: "due", label: "Jatuh Tempo", finance: true },
];

export const attentionRows = (att, tab) => (att?.rows || []).filter((r) => tab === "all" || (r.tabs || []).includes(tab));
