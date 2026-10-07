// Helper murni Pengajuan Approval 2 PO (dipakai UI + test node).

export const A2_READY = "Siap Diajukan";
export const A2_SUBMITTED = "Sudah Diajukan";

/** Task approval PO Level 2 yang Pending diproses lewat Pengajuan Approval 2 (bukan Approve/Reject individual). */
export const isLevel2PoTask = (row) => !!row && row.module === "po" && Number(row.seq) === 2 && row.status === "Pending";

/** Tanggal lokal hari ini (YYYY-MM-DD), tanpa geser zona waktu. */
export const isoToday = (d = new Date()) => {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

/** "2026-10-06" atau ISO datetime -> "06/10/2026" (tanpa konversi zona waktu untuk tanggal murni). */
export const fmtA2Date = (v) => {
  if (!v) return "-";
  const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m && String(v).length <= 10) return `${m[3]}/${m[2]}/${m[1]}`;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
};

export const fmtDateTimeSafe = (v) => {
  const d = new Date(v);
  if (!v || Number.isNaN(d.getTime())) return "-";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export const fmtMoney = (n) => Number(n || 0).toLocaleString("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
export const fmtRp = (n) => `Rp ${fmtMoney(n)}`;
/** PPN tanpa pajak ditampilkan "-" (bukan 0). */
export const fmtPpn = (n) => (Math.abs(Number(n || 0)) < 0.005 ? "-" : fmtMoney(n));
export const fmtPpnRp = (n) => (Math.abs(Number(n || 0)) < 0.005 ? "-" : fmtRp(n));

export const batchTotals = (items = []) => ({
  count: items.length,
  dpp: items.reduce((s, i) => s + Number(i.dpp || 0), 0),
  ppn: items.reduce((s, i) => s + Number(i.ppn || 0), 0),
  total: items.reduce((s, i) => s + Number(i.grand_total || 0), 0),
});

/** Approval2_Project-PHR-Duri_2026-10-06.jpg */
export const approval2FileName = (title, date) => {
  const slug = String(title || "Pengajuan").trim().replace(/\s+/g, "-").replace(/[^A-Za-z0-9_-]/g, "").replace(/-+/g, "-").replace(/^-|-$/g, "") || "Pengajuan";
  return `Approval2_${slug}_${String(date || "").slice(0, 10)}.jpg`;
};

/** Hanya PO Siap Diajukan yang boleh dicentang untuk batch baru. */
export const selectableRows = (rows = []) => rows.filter((r) => r.submission_status === A2_READY);

export const toggleId = (sel, id) => (sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);

export const searchEligible = (rows = [], q = "") => {
  const s = String(q || "").trim().toLowerCase();
  if (!s) return rows;
  return rows.filter((r) => `${r.po_no || ""} ${r.supplier_name || ""} ${r.project_text || ""} ${r.pic_name || ""}`.toLowerCase().includes(s));
};

// Izin granular Approval 2 (Hak Akses existing). `can` = useAuth().can (cek key penuh `po_approval2.<aksi>`).
export const A2_PERM = { view: "po_approval2.view", submit: "po_approval2.submit", approve: "po_approval2.approve", print: "po_approval2.print" };
export function a2Access(can, status) {
  const has = (k) => !!(typeof can === "function" && can(A2_PERM[k]));
  const view = has("view"), submit = has("submit"), approve = has("approve"), print = has("print");
  const draft = status === "Draft";
  return {
    view, submit, approve, print,
    // Draft -> Diajukan butuh submit; export ulang batch yang sudah diajukan cukup print (atau submit).
    canExport: view && (draft ? submit : (print || submit)),
    canPreview: view && (print || submit),
    canUploadEvidence: view && (approve || submit),
  };
}
