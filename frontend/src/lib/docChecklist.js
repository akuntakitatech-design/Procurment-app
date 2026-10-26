// Checklist kelengkapan dokumen Vendor Invoice.
// Status (Lengkap / Belum Lengkap / Tidak Berlaku) dicatat TERPISAH dari keberadaan file digital,
// karena dokumen fisik bisa sudah diterima walau file belum diunggah.
export const CHECK_VALUES = ["Lengkap", "Belum Lengkap", "Tidak Berlaku"];
export const CHECK_DEFAULT = "Belum Lengkap";

export const CHECKLIST_OPTIONS = [
  { key: "invoice", label: "Invoice", category: "Invoice" },
  { key: "faktur_pajak", label: "Faktur Pajak", category: "Faktur Pajak" },
  { key: "po", label: "Purchase Order", category: "Purchase Order" },
  { key: "do", label: "Delivery Order (DO)", category: "Delivery Order" },
  { key: "bukti_penerimaan", label: "Bukti Penerimaan Barang PT REAL", category: "Bukti Penerimaan Barang" },
  { key: "kwitansi", label: "Kwitansi", category: "Kwitansi" },
  { key: "bast", label: "BAST / Timesheet", category: "BAST/Timesheet" },
  { key: "kontrak", label: "Kontrak Kerja (Subcon)", category: "Kontrak Kerja" },
];

export const CHECKLIST_KEYS = CHECKLIST_OPTIONS.map((o) => o.key);
export const emptyChecklist = () => Object.fromEntries(CHECKLIST_OPTIONS.map((o) => [o.key, CHECK_DEFAULT]));

export const normalizeChecklist = (raw) => {
  const src = raw && typeof raw === "object" ? raw : {};
  return Object.fromEntries(CHECKLIST_OPTIONS.map((o) => [o.key, CHECK_VALUES.includes(src[o.key]) ? src[o.key] : CHECK_DEFAULT]));
};

/** Ringkasan: jumlah Lengkap / wajib (Tidak Berlaku tidak dihitung) + daftar yang belum lengkap. */
export const checklistSummary = (raw) => {
  const c = normalizeChecklist(raw);
  const items = CHECKLIST_OPTIONS.map((o) => ({ ...o, status: c[o.key] }));
  const required = items.filter((i) => i.status !== "Tidak Berlaku");
  const done = required.filter((i) => i.status === "Lengkap");
  return {
    items,
    required: required.length,
    done: done.length,
    pending: required.filter((i) => i.status !== "Lengkap").map((i) => i.label),
    complete: required.length === 0 || done.length === required.length,
  };
};
