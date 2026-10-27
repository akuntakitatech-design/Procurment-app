// F2 — Penyajian PO v2 (Tax Engine v2) untuk FORM, DETAIL, dan CETAK. Murni presentasi atas nilai dari backend
// (preview server / nilai TERSIMPAN): tidak ada perhitungan pajak di sini — hanya memilih, memberi label, dan
// menjumlahkan dua nilai backend dalam sen (Nilai Pembelian Sebelum PPN = Total DPP + Nilai Tanpa PPN).
export const isPoV2 = (doc) => Number(doc?.tax_engine_version) === 2;

const MODE = { EXCLUDE: "Exclude", INCLUDE: "Include", NONE: "Tanpa PPN" };
const FAC = { TIDAK_DIPUNGUT: "Tidak Dipungut", DTP: "DTP", DIBEBASKAN: "Dibebaskan" };
const n = (v) => Number(v || 0);
const cents = (v) => Math.round(n(v) * 100);
const pct = (v) => String(v ?? "").replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1").replace(".", ",");

/** Format uang PO v2 — SAMA di form, detail, dan cetak (id-ID, sen hanya bila ada). */
export const fmtIdr = (v) => (v == null || v === "" ? "–" : new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(n(v)));

/** Rupiah tanpa desimal — dipakai untuk DPP Nilai Lain (dibulatkan pada dokumen). */
export const fmtIdr0 = (v) => (v == null || v === "" ? "–" : new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Math.round(n(v))));

/** Label kolom nilai baris PO v2 (form, detail, cetak). */
export const LINE_AMOUNT_LABEL = "Jumlah Sebelum PPN";
/** Nilai baris sebelum PPN = DPP baris dari backend (setelah diskon item & bagian diskon final; harga Include dikeluarkan PPN-nya). */
export const poLineAmount = (l) => (l?.dpp == null ? null : n(l.dpp));

/** Keterangan perlakuan PPN satu baris PO v2 dari SNAPSHOT baris — format sama dengan chip form:
 * "Exclude · PPN DPP Nilai Lain · 04" / "Tanpa PPN" / "Include · Tidak Dipungut · 07". */
export function poTaxLineNote(l) {
  const mode = String(l?.tax_mode || "NONE").toUpperCase();
  if (mode === "NONE" || !l?.tax_code) return MODE.NONE;
  const fac = FAC[l.tax_facility];
  return `${MODE[mode] || mode} · ${fac || l.tax_name || "PPN"}${l.tax_trx_code ? ` · ${l.tax_trx_code}` : ""}`;
}

/** Label kelompok pajak dari snapshot aturan (bukan dari Master Pajak terkini). */
export function poTaxGroupLabel(g, rules = []) {
  const r = (rules || []).find((x) => x.group === g.group) || {};
  const [trx, , rate, num, den] = String(g.group || "").split("|");
  const rt = r.tax_rate ?? rate;
  const fn = r.tax_dpp_factor_num ?? num;
  const fd = r.tax_dpp_factor_den ?? den;
  const basis = fn && fd && String(fn) !== String(fd) ? ` × ${fn}/${fd}` : "";
  const fac = FAC[g.facility];
  return `${fac ? `PPN ${fac}` : "PPN"} ${pct(rt)}%${basis} (Kode ${g.trx_code || trx || "-"})`;
}

/** Nilai Pembelian Sebelum PPN = Total DPP (objek PPN) + Nilai Tanpa PPN (penjumlahan sen dari nilai backend). */
export const purchaseBeforePpn = (t) => (t?.dpp_total == null && t?.non_ppn_total == null ? null : (cents(t.dpp_total) + cents(t.non_ppn_total)) / 100);

/**
 * Baris Ringkasan PO v2 — satu sumber untuk form, detail, dan cetak (urutan & istilah identik).
 * opts.form: baris diskon selalu tampil (form punya input Diskon Final).
 * Baris bertanda `sub` adalah keterangan (bukan penjumlah); `grand` hanya SATU baris di akhir.
 */
export function poV2SummaryRows(t, opts = {}) {
  t = t || {};
  const rows = [{ key: "gross", label: "Total Harga Sebelum Diskon", value: n(t.gross_total) }];
  if (opts.form || n(t.item_discount_total)) rows.push({ key: "item_disc", label: "Diskon Item", value: n(t.item_discount_total), neg: true });
  if (opts.form || n(t.final_discount_amount)) rows.push({ key: "final_disc", label: "Diskon Final", value: n(t.final_discount_amount), neg: true });
  const before = purchaseBeforePpn(t) ?? 0;
  // Harga Include sudah memuat PPN: Total Setelah Diskon berbeda dari Nilai Pembelian Sebelum PPN -> tampilkan keduanya.
  if (cents(t.subtotal_after_discount) !== Math.round(before * 100)) {
    rows.push({ key: "after_disc", label: "Total Setelah Diskon", hint: "harga Include sudah termasuk PPN", value: n(t.subtotal_after_discount) });
  }
  rows.push({ key: "before_ppn", label: "Nilai Pembelian Sebelum PPN", value: before, strong: true });
  if (n(t.non_ppn_total) && n(t.dpp_total)) rows.push({ key: "non_ppn", label: "termasuk barang Tanpa PPN", value: n(t.non_ppn_total), sub: true });
  if (n(t.dpp_other_total)) rows.push({ key: "dpp_other", label: "DPP Nilai Lain", hint: "dasar perhitungan PPN", value: n(t.dpp_other_total) });
  rows.push({ key: "ppn", label: "PPN", value: n(t.tax_total) });
  if (n(t.tax_facility_total)) rows.push({ key: "ppn_facility", label: "PPN fasilitas (tidak ditagih)", value: n(t.tax_facility_total), sub: true });
  if (n(t.ppnbm_total)) rows.push({ key: "ppnbm", label: "PPnBM", value: n(t.ppnbm_total) });
  rows.push({ key: "grand", label: "Grand Total", value: n(t.grand_total), grand: true });
  return rows;
}

/** Rincian pajak per kelompok kode faktur (dapat dibuka di layar; tabel ringkas di cetak). */
export function poTaxGroupRows(t) {
  return (t?.tax_groups || []).map((g) => {
    const fac = n(g.ppn_facility);
    return { key: g.group, label: poTaxGroupLabel(g, t.tax_rules_snapshot), dpp: n(g.dpp), dpp_other: n(g.dpp_other), ppn: fac ? 0 : n(g.ppn), facility: fac };
  });
}
