// Tanggal Approval 2 PO (daftar PO). Sumber: backend `approval2_at` = 'YYYY-MM-DD HH:MM:SS' WIB dari riwayat Approval 2
// final; null = bukan Disetujui / tanpa riwayat (tidak ada tanggal perkiraan).
export const APPROVAL2_SORT_FIELD = "approval2_at";

export function fmtApproval2(stamp) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(stamp || ""));
  return m ? `${m[3]}/${m[2]}/${m[1]} · Approval 2 (WIB)` : null;
}

// Teks kecil di bawah badge hanya untuk Status Dokumen = Approved (badge hijau "Disetujui").
export const approval2Note = (row) => (row && row.document_status === "Approved" ? fmtApproval2(row.approval2_at) : null);

export const APPROVAL2_SORT_OPTIONS = [
  { value: "", label: "Urutan bawaan" },
  { value: "asc", label: "Tgl Approval 2: terlama → terbaru" },
  { value: "desc", label: "Tgl Approval 2: terbaru → terlama" },
];

// sort daftar server ({key, dir, ui}) <-> nilai dropdown. ui = kolom Status Dokumen (penanda panah di judul kolom).
export const approval2SortValue = (sort) => (sort?.key === APPROVAL2_SORT_FIELD ? sort.dir : "");
export const approval2SortFrom = (value) =>
  value === "asc" || value === "desc" ? { key: APPROVAL2_SORT_FIELD, dir: value, ui: "document_status" } : null;
