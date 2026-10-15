// F2 — Cetak PO v2 (Tax Engine v2). Murni presentasi atas nilai TERSIMPAN dari backend:
// tidak ada perhitungan pajak di sini (hanya memilih & memberi label baris ringkasan).
export const isPoV2 = (doc) => Number(doc?.tax_engine_version) === 2;

const MODE = { EXCLUDE: "Exclude", INCLUDE: "Include", NONE: "Tanpa PPN" };
const FAC = { TIDAK_DIPUNGUT: "Tidak Dipungut", DTP: "DTP", DIBEBASKAN: "Dibebaskan" };
const n = (v) => Number(v || 0);
const pct = (v) => String(v ?? "").replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1").replace(".", ",");

/** Keterangan perlakuan PPN satu baris PO v2, mis. "Exclude · PPN 04" / "Tanpa PPN" / "Include · Tidak Dipungut 07". */
export function poTaxLineNote(l) {
  const mode = String(l?.tax_mode || "NONE").toUpperCase();
  if (mode === "NONE" || !l?.tax_code) return MODE.NONE;
  const fac = FAC[l.tax_facility];
  return `${MODE[mode] || mode} · ${fac || "PPN"}${l.tax_trx_code ? ` ${l.tax_trx_code}` : ""}`;
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

/** Baris ringkasan cetak PO v2 — identik urutannya dengan Ringkasan PO di form. */
export function poV2SummaryRows(doc) {
  const rows = [{ key: "gross", label: "Total Harga Sebelum Diskon", value: n(doc.gross_total) }];
  if (n(doc.item_discount_total)) rows.push({ key: "item_disc", label: "Diskon Item", value: n(doc.item_discount_total), neg: true });
  if (n(doc.final_discount_amount)) rows.push({ key: "final_disc", label: "Diskon Final", value: n(doc.final_discount_amount), neg: true });
  rows.push({ key: "after_disc", label: "Total Setelah Diskon", value: n(doc.subtotal_after_discount) });
  rows.push({ key: "dpp", label: "Total DPP (objek PPN)", value: n(doc.dpp_total) });
  if (n(doc.non_ppn_total)) rows.push({ key: "non_ppn", label: "Nilai Tanpa PPN", value: n(doc.non_ppn_total) });
  const groups = doc.tax_groups || [];
  if (groups.length) {
    groups.forEach((g) => {
      const fac = n(g.ppn_facility);
      rows.push({ key: `ppn:${g.group}`, label: poTaxGroupLabel(g, doc.tax_rules_snapshot) + (fac ? " — tidak ditagih" : ""), value: fac ? 0 : n(g.ppn) });
    });
  } else rows.push({ key: "ppn", label: "PPN", value: n(doc.tax_total) });
  rows.push({ key: "grand", label: "Grand Total", value: n(doc.grand_total), grand: true });
  return rows;
}
