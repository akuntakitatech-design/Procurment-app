import { round2 } from "@/lib/invoice";

export const DP_STATUS = { pending: "Menunggu Verifikasi", paid: "Sudah Dibayar", cancelled: "Dibatalkan" };

export const dpTypeLabel = (row) => {
  if (!row?.dp_type) return "-";
  if (row.dp_type === "percentage") return `Persentase (${String(row.dp_value ?? "").replace(".", ",")}%)`;
  return "Nominal (Rp)";
};

/** Batas alokasi per PO = MIN(DP tersedia, nilai bagian invoice PO) — dihitung backend (max_allocation). */
export const dpLimit = (c) => round2(c?.max_allocation || 0);

export const sumDp = (map) => round2(Object.values(map || {}).reduce((s, v) => s + (Number(v) || 0), 0));
