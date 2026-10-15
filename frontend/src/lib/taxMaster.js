// F2 — konfigurasi Master Pajak (Jenis Transaksi PPN). Kelengkapan dicek ulang backend (po_tax.tax_master_issues).
export const TRX_CODE_OPTIONS = [
  { value: "", label: "— Belum diisi —" },
  { value: "01", label: "01 · Kepada pihak yang bukan pemungut PPN" },
  { value: "02", label: "02 · Kepada pemungut instansi pemerintah" },
  { value: "03", label: "03 · Kepada pemungut selain instansi pemerintah" },
  { value: "04", label: "04 · DPP Nilai Lain" },
  { value: "05", label: "05 · Besaran tertentu" },
  { value: "06", label: "06 · Kepada orang pribadi pemegang paspor luar negeri" },
  { value: "07", label: "07 · PPN tidak dipungut / DTP" },
  { value: "08", label: "08 · PPN dibebaskan" },
  { value: "09", label: "09 · Penyerahan aktiva (Pasal 16D)" },
  { value: "10", label: "10 · Penyerahan lainnya" },
];
export const FACILITY_OPTIONS = [
  { value: "NORMAL", label: "Tanpa fasilitas" },
  { value: "TIDAK_DIPUNGUT", label: "Tidak Dipungut (kode 07)" },
  { value: "DTP", label: "Ditanggung Pemerintah / DTP (kode 07)" },
  { value: "DIBEBASKAN", label: "Dibebaskan (kode 08)" },
];
export const FACILITY_LABEL = { NORMAL: "Tanpa fasilitas", TIDAK_DIPUNGUT: "Tidak Dipungut", DTP: "DTP", DIBEBASKAN: "Dibebaskan" };

/** Kelengkapan master untuk PO v2 (mirror ringkas backend; backend tetap penentu). */
export function taxMasterIssues(t) {
  const issues = [];
  if (!t?.trx_code) issues.push("kode transaksi faktur");
  if (!t?.dpp_factor_num || !t?.dpp_factor_den) issues.push("faktor DPP Nilai Lain");
  return issues;
}
