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

// Kartu saldo/outstanding (posisi s/d tanggal akhir filter) vs aktivitas periode.
export const BACKLOG = new Set(["mro_open", "ro_open", "waiting_a1", "ready_a2", "waiting_a2", "waiting_approval", "not_received", "partial", "late",
  "invoice_unbilled", "unpaid", "payable", "due_soon", "overdue", "dp_unallocated"]);
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const isBacklog = (kind) => BACKLOG.has(kind);

export function drillLink(kind, f = {}, _perms = {}, today = new Date()) {
  const r = periodRange(f.period || "this_month", today);
  const q = new URLSearchParams();
  const put = (k, v) => v && q.set(k, v);
  // Saldo/outstanding = posisi s/d tanggal akhir filter (tanpa date_from: dokumen periode sebelumnya ikut);
  // aktivitas (PO Disetujui / semua PO) = transaksi di dalam periode. rf_asof = tanggal posisi bila lampau.
  const backlog = BACKLOG.has(kind);
  const asof = r.date_to && r.date_to < isoDay(today) ? r.date_to : "";
  const dims = () => {
    if (!backlog) put("date_from", r.date_from);
    put("date_to", r.date_to);
    if (backlog) put("rf_asof", asof);
    put("rf_division_id", f.division_id); put("rf_project_id", f.project_id); put("rf_supplier_id", f.supplier_id);
  };
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

// Drill-down KPI Persediaan -> Inventory (summary canonical yang sama; ikut filter Divisi dashboard).
const INV_STATUS = { total: "", out_of_stock: "Out of Stock", low_stock: "Low Stock", overstock: "Overstock" };
export function inventoryLink(kind, f = {}) {
  const p = new URLSearchParams();
  if (INV_STATUS[kind]) p.set("stock_status", INV_STATUS[kind]);
  if (f.division_id) p.set("division_id", f.division_id);
  const qs = p.toString();
  return qs ? `/inventory?${qs}` : "/inventory";
}

// "2026-09-30" -> "30/09/2026" (tanggal Nilai Persediaan per akhir filter)
export function asOfLabel(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "hari ini";
}

// ---------------------------------------------------------------- SPK & Budget Control / Kontrak Harga Vendor
/** Level pemakaian budget SPK (dihitung backend): < 80 Normal · 80–90 Perhatian · > 90 Kritis · > 100 Over Budget. */
export const SPK_LEVEL = {
  normal: { label: "Normal", bar: "#7FA7CF", text: "text-slate-600", chip: "bg-[#EDF4FB] text-[#3F6E9C]" },
  warning: { label: "Perhatian", bar: "#D4A04E", text: "text-[#9A6A22]", chip: "bg-[#FBF4E8] text-[#9A6A22]" },
  critical: { label: "Kritis", bar: "#C98282", text: "text-[#A34B4B]", chip: "bg-[#FBF0F0] text-[#A34B4B]" },
  over: { label: "Over Budget", bar: "#B86B6B", text: "text-[#A34B4B]", chip: "bg-[#FBF0F0] text-[#A34B4B]" },
};

/** Badge status Price Control (Effective Price Resolver existing). */
export const PRICE_STATUS = {
  ok: { label: "Sesuai", cls: "border-[#D5E8DF] bg-[#EEF6F2] text-[#3D7A62]" },
  over: { label: "Melebihi Tolerance", cls: "border-[#EEDADA] bg-[#FBF0F0] text-[#A34B4B]" },
  no_contract: { label: "Tanpa Kontrak", cls: "border-[#F1E3C8] bg-[#FBF4E8] text-[#9A6A22]" },
  history_incomplete: { label: "Riwayat Harga Tidak Lengkap", cls: "border-slate-200 bg-slate-50 text-slate-600" },
};

/** Lebar bar progress 0–100 (nilai > 100 dipotong; null -> 0). */
export function barPct(p) {
  const n = Number(p);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
}

/** Persentase singkat: 90 -> "90%", 92.35 -> "92,4%", null -> "–". */
export function pctText(p) {
  if (p == null || !Number.isFinite(Number(p))) return "–";
  const n = Number(p);
  return `${n >= 999 ? ">999" : n.toLocaleString("id-ID", { maximumFractionDigits: 1 })}%`;
}

export const spkDetailLink = (id) => `/spk/${id}`;
export const poDetailLink = (id) => `/po/${id}`;
export const contractDetailLink = (id) => `/vendor-contracts/${id}`;

const clean = (p) => { Object.keys(p).forEach((k) => (p[k] == null || p[k] === "") && delete p[k]); return p; };

/** Drill SPK (POSISI): hanya date_to = tanggal posisi (cut-off) + Divisi/Project. date_from TIDAK dikirim. */
export function spkDrillParams(asOf, f = {}, kind = "active") {
  return clean({ date_to: asOf, kind, division_id: f.division_id, project_id: f.project_id });
}

/** Drill status kontrak (POSISI): hanya date_to + Supplier. date_from TIDAK dikirim. */
export function contractDrillParams(asOf, f = {}, kind = "active") {
  return clean({ date_to: asOf, kind, supplier_id: f.supplier_id });
}

/** Drill Price Control (TRANSAKSI periode): date_from + date_to + Divisi/Project/Supplier. */
export function priceDrillParams(f = {}, status = "all", today = new Date()) {
  const r = periodRange(f.period || "this_month", today);
  return clean({ ...r, status, division_id: f.division_id, project_id: f.project_id, supplier_id: f.supplier_id });
}

export const DRILL_ENDPOINT = { spk: "/dashboard/drill/spk", contract: "/dashboard/drill/vendor-contracts", price: "/dashboard/drill/price-control" };
export const drillUrl = (type, params) => `${DRILL_ENDPOINT[type]}?${new URLSearchParams(params).toString()}`;

/** Kartu KPI SPK. Nominal hanya bila backend mengirim (spk:view) — tanpa nominal: hanya count, tanpa placeholder Rp. */
export function spkKpiCards(spk) {
  const k = spk?.kpi || {};
  const ratio = (a, b) => (b > 0 ? (a * 100) / b : null);
  if (!spk?.with_value) {
    return [
      { key: "active", label: "SPK Aktif", value: k.active ?? 0, tone: "navy", drill: "active", sub: "per tanggal posisi" },
      { key: "over_budget", label: "Over Budget", value: k.over_budget ?? 0, tone: k.over_budget ? "red" : "slate", drill: "over", sub: "pemakaian > 100%" },
      { key: "critical", label: "Kritis", value: k.critical ?? 0, tone: k.critical ? "amber" : "slate", drill: "critical", sub: "pemakaian > 90%" },
      { key: "attention", label: "Perlu Perhatian", value: k.attention ?? 0, tone: k.attention ? "amber" : "slate", drill: "attention", sub: `${k.expiring ?? 0} akan berakhir ≤ 30 hari` },
    ];
  }
  return [
    { key: "active", label: "SPK Aktif", value: k.active ?? 0, tone: "navy", drill: "active", sub: `${k.over_budget ?? 0} over budget` },
    { key: "budget", label: "Budget Procurement", value: k.budget, money: true, tone: "slate", drill: "active", sub: "incl. addendum" },
    { key: "commitment", label: "Commitment", value: k.commitment, money: true, tone: "blue", drill: "active", pct: k.usage_pct, sub: k.usage_pct == null ? "belum ada budget" : `${pctText(k.usage_pct)} dari budget` },
    { key: "realization", label: "Realisasi", value: k.realization, money: true, tone: "green", drill: "active", pct: k.realization_pct, sub: k.realization_pct == null ? "belum ada commitment" : `${pctText(k.realization_pct)} dari commitment` },
    { key: "open_commitment", label: "Open Commitment", value: k.open_commitment, money: true, tone: "amber", drill: "active", pct: ratio(k.open_commitment, k.commitment), sub: "commitment − realisasi" },
    { key: "remaining", label: "Sisa Budget", value: k.remaining, money: true, tone: k.remaining < 0 ? "red" : "indigo", drill: "active", pct: ratio(Math.max(k.remaining || 0, 0), k.budget), sub: "budget − commitment" },
  ];
}

/** Ringkasan SPK untuk Layer 2 (kartu ringkas): turunan spkKpiCards — nilai & formula identik, tanpa hitung ulang.
 *  Dengan spk:view: SPK Aktif · Budget · Commitment (sub Realisasi) · Sisa Budget. Tanpa: 4 kartu count. */
export function spkSummaryCards(spk) {
  const all = spkKpiCards(spk);
  if (!spk?.with_value) return all;
  const by = Object.fromEntries(all.map((c) => [c.key, c]));
  const k = spk.kpi || {};
  return [by.active, by.budget,
    { ...by.commitment, sub: k.realization_pct == null ? "belum ada realisasi" : `realisasi ${pctText(k.realization_pct)}` },
    by.remaining];
}

/** Kartu Persediaan (snapshot existing; angka apa adanya dari backend). */
export function inventoryCards(inv = {}) {
  const st = inv.stock || {};
  const ratio = (a) => (st.total > 0 ? (a * 100) / st.total : null);
  return [
    { key: "total", label: "Jumlah Item", value: st.total ?? 0, tone: "navy", sub: "barang aktif" },
    { key: "out_of_stock", label: "Stok Habis", value: st.out_of_stock ?? 0, tone: "red", pct: ratio(st.out_of_stock), sub: "dari jumlah item" },
    { key: "low_stock", label: "Stok Menipis", value: st.low_stock ?? 0, tone: "amber", pct: ratio(st.low_stock), sub: "di bawah minimum" },
    { key: "overstock", label: "Overstock", value: st.overstock ?? 0, tone: "indigo", pct: ratio(st.overstock), sub: "di atas maksimum" },
  ];
}

/** Urutan layer Dashboard: Kondisi -> Kontrol -> Analisis -> Tindakan -> detail lain. */
export const DASHBOARD_LAYERS = ["dash-layer-1", "dash-layer-2", "dash-layer-3", "dash-layer-4", "dash-layer-detail"];

/** Kartu status kontrak (posisi cut-off) — selalu count. */
export function contractKpiCards(c = {}) {
  const ratio = (a, b) => (b > 0 ? (a * 100) / b : null);
  const tot = (c.active || 0) + (c.expired || 0);
  return [
    { key: "active", label: "Kontrak Aktif", value: c.active ?? 0, tone: "green", drill: "active", pct: ratio(c.active, tot), sub: "berlaku pada tanggal posisi" },
    { key: "expiring", label: "Akan Berakhir ≤ 30 Hari", value: c.expiring ?? 0, tone: "amber", drill: "expiring", pct: ratio(c.expiring, c.active), sub: "dari tanggal posisi" },
    { key: "expired", label: "Kedaluwarsa", value: c.expired ?? 0, tone: "red", drill: "expired", pct: ratio(c.expired, tot), sub: "per tanggal posisi" },
    { key: "items", label: "Item Dalam Kontrak Aktif", value: c.items_active ?? 0, tone: "navy", sub: "harga efektif berlaku" },
  ];
}

/** Kartu Price Control (transaksi periode). Nilai Selisih hanya bila backend mengirim nominal. */
export function priceKpiCards(pc, withValue) {
  const k = pc?.kpi || {};
  const ratio = (a, b) => (b > 0 ? (a * 100) / b : null);
  const out = [
    { key: "ok", label: "PO Sesuai Harga Kontrak", value: k.po_ok ?? 0, tone: "green", drill: "ok", pct: ratio(k.po_ok, k.po_evaluated), sub: `dari ${k.po_evaluated ?? 0} PO Approved` },
    { key: "over", label: "PO Melebihi Tolerance", value: k.po_over ?? 0, tone: "red", drill: "over", pct: ratio(k.po_over, k.po_evaluated), sub: `${k.lines_over ?? 0} baris barang` },
    { key: "no_contract", label: "PO Tanpa Kontrak Aktif", value: k.po_no_contract ?? 0, tone: "amber", drill: "no_contract", pct: ratio(k.po_no_contract, k.po_evaluated), sub: `${k.lines_no_contract ?? 0} baris barang` },
  ];
  if (k.po_history_incomplete) out.push({ key: "history_incomplete", label: "PO Riwayat Harga Tidak Lengkap", value: k.po_history_incomplete, tone: "slate", drill: "history_incomplete", pct: ratio(k.po_history_incomplete, k.po_evaluated), sub: `${k.lines_history_incomplete ?? 0} baris perlu diperiksa` });
  if (withValue && k.diff_value != null) out.push({ key: "diff", label: "Nilai Selisih Harga", value: k.diff_value, money: true, tone: "slate", drill: "over", sub: "baris melebihi tolerance" });
  return out;
}

/** Kolom tabel Price Exception — kolom harga hanya bila nominal dikirim backend. */
export function exceptionColumns(withValue) {
  return ["PO", "Vendor", "Barang", ...(withValue ? ["Harga Kontrak", "Harga PO", "Tolerance", "Selisih"] : []), "Status"];
}
