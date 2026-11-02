/**
 * Opsi pemilih supplier: judul = **Nama Legal Perusahaan**, subjudul = **PIC + Alamat**.
 *
 * Pada master supplier, `name` berisi nama PIC (mis. "Aliang") sedangkan nama perusahaan ada di
 * `legal_name` (mis. "PT Riau Indo Pasifik"). Tanpa ini, dropdown hanya menampilkan nama orang
 * sehingga sulit membedakan vendor.
 */
export function supplierOption(d) {
  const legal = String(d?.legal_name || "").trim();
  const pic = String(d?.name || "").trim();
  const address = String(d?.address || "").trim();
  const label = legal || pic || "-";
  const sub = [legal && pic && pic !== legal ? `PIC: ${pic}` : "", address].filter(Boolean).join(" · ");
  return { label, selectedLabel: label, sublabel: sub || undefined };
}

/** Nilai kolom Supplier pada DAFTAR transaksi: nama legal perusahaan (fallback ke nama tersimpan). */
export const supplierLegalName = (r) => r?.supplier_legal_name || r?.supplier_name || "-";
