// DP / Uang Muka PO — ketentuan pembayaran (bukan transaksi pembayaran).
// Pratinjau di form memakai aritmetika sen (integer) agar konsisten dengan engine backend
// (compute_po_dp: Decimal, 2 desimal HALF_UP). Nilai tersimpan selalu dihitung ulang di backend.

export const DP_EXCEEDS_MSG = "Nilai DP tidak boleh melebihi Grand Total PO.";
export const DP_PCT_MSG = "Persentase DP harus lebih dari 0% dan maksimal 100%.";
export const DP_ZERO_MSG = "Nilai DP harus lebih dari 0.";

const cents = (n) => Math.round((Number(n) || 0) * 100);

export const fmtPct = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  return String(Math.round(n * 10000) / 10000).replace(".", ",");
};

/** Pratinjau DP terhadap Grand Total form. Return {enabled, type, value, amount, remaining, error}. */
export function computeDp(h, grand) {
  if (!h || !h.dp_enabled) return { enabled: false };
  const type = h.dp_type === "nominal" ? "nominal" : "percentage";
  const v = Number(h.dp_value);
  const g = cents(grand);
  if (!(v > 0)) return { enabled: true, type, error: type === "percentage" ? DP_PCT_MSG : DP_ZERO_MSG };
  if (type === "percentage") {
    if (v > 100) return { enabled: true, type, value: v, error: DP_PCT_MSG };
    const amt = Math.round((g * v) / 100);
    return { enabled: true, type, value: v, amount: amt / 100, remaining: (g - amt) / 100 };
  }
  const amt = cents(v);
  if (amt > g) return { enabled: true, type, value: v, amount: amt / 100, error: DP_EXCEEDS_MSG };
  return { enabled: true, type, value: v, amount: amt / 100, remaining: (g - amt) / 100 };
}

export const dpLabel = (doc) => (doc?.dp_type === "percentage" ? `Uang Muka (DP) ${fmtPct(doc.dp_value)}% dari Grand Total` : "Uang Muka (DP)");

/** Baris KETENTUAN PEMBAYARAN (syarat DP pada PO, BUKAN pembayaran aktual). Kosong bila PO tidak memakai DP. */
export function dpRows(doc) {
  if (!doc || !doc.dp_enabled || doc.dp_amount == null) return [];
  return [
    { key: "dp", label: dpLabel(doc), amount: Number(doc.dp_amount) },
    { key: "remaining", label: "Sisa setelah DP", amount: Number(doc.dp_remaining) },
  ];
}

/** Status pembayaran DP dari modul DP Supplier (null = tidak diketahui / tidak berizin -> jangan klaim dibayar). */
export function dpPaymentStatus(info) {
  if (!info) return null;
  if (Number(info.paid_amount) > 0 && info.status === "Approved") return { key: "paid", label: `Sudah dibayar${info.dp_no ? ` · ${info.dp_no}` : ""}`, amount: Number(info.paid_amount) };
  if (info.payment_id) return { key: "pending", label: "Pembayaran DP menunggu verifikasi" };
  return { key: "unpaid", label: "Belum dibayar" };
}
