// Validasi input transaksi di frontend (UX guard). Backend tetap menjadi sumber kebenaran.
export const DIVISION_REQUIRED_MSG = "Divisi wajib diisi.";
export const QTY_REQUIRED_MSG = "Qty harus lebih besar dari 0.";
export const ADJ_QTY_MSG = "Qty Penyesuaian tidak boleh 0.";
export const COUNT_NEGATIVE_MSG = "Qty hasil hitung fisik tidak boleh minus.";
export const SOURCE_DIVISION_CONFLICT_MSG = "Dokumen sumber berasal dari Divisi yang berbeda. Pisahkan transaksi per Divisi.";
export const SOURCE_DIVISION_MISSING_MSG = "Dokumen sumber tidak memiliki Divisi yang valid. Transaksi tidak dapat diproses.";

const blank = (v) => v === undefined || v === null || (typeof v === "string" && v.trim() === "");

/** Angka finite (bukan null/kosong/NaN/Infinity). */
export function toFiniteNumber(v) {
  if (blank(v) || typeof v === "boolean") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function isPositiveQty(v) {
  const n = toFiniteNumber(v);
  return n !== null && n > 0;
}

export function isNonZeroQty(v) {
  const n = toFiniteNumber(v);
  return n !== null && Math.abs(n) > 1e-12;
}

export function hasDivision(v) {
  return !blank(v);
}

/**
 * Cek baris transaksi. mode: "normal" (qty > 0), "adjustment" (+/- tetapi tidak 0), "opname" (counted >= 0, boleh 0/kosong).
 * Return {index, message} untuk baris pertama yang tidak valid, atau null.
 */
export function firstInvalidLine(lines, mode = "normal", key) {
  const list = Array.isArray(lines) ? lines : [];
  for (let i = 0; i < list.length; i += 1) {
    const l = list[i] || {};
    if (mode === "adjustment") {
      if (!isNonZeroQty(l[key || "adjustment"])) return { index: i, message: ADJ_QTY_MSG };
    } else if (mode === "opname") {
      const v = l[key || "counted"];
      if (!blank(v)) {
        const n = toFiniteNumber(v);
        if (n === null || n < 0) return { index: i, message: COUNT_NEGATIVE_MSG };
      }
    } else if (!isPositiveQty(l[key || "qty"])) {
      return { index: i, message: QTY_REQUIRED_MSG };
    }
  }
  return null;
}

/** Pesan validasi Qty lengkap dengan nomor baris, atau null bila valid. */
export function lineQtyError(lines, mode = "normal", key) {
  const bad = firstInvalidLine(lines, mode, key);
  return bad ? `Baris ${bad.index + 1}: ${bad.message}` : null;
}

const rowDivision = (r) => {
  const sh = r?.source_header || r?._sourceHeader;
  if (sh && !blank(sh.division_id)) return String(sh.division_id);
  if (!blank(r?.division_id)) return String(r.division_id);
  if (!blank(r?._source_division_id)) return String(r._source_division_id);
  return null;
};

/**
 * Divisi turunan dari baris sumber (MRO->RO, RO->PO, PO->DO, MRO->MI).
 * Return {sourced, division_id, conflict, missing}.
 */
export function sourceDivision(rows) {
  const list = (Array.isArray(rows) ? rows : []).filter(Boolean);
  if (!list.length) return { sourced: false, division_id: null, conflict: false, missing: false };
  const divs = list.map(rowDivision);
  const known = [...new Set(divs.filter(Boolean))];
  return {
    sourced: true,
    division_id: known.length === 1 ? known[0] : null,
    conflict: known.length > 1,
    missing: known.length === 0,
  };
}

/** Validasi Divisi header. Return pesan error atau null. */
export function divisionError(divisionId, src) {
  if (src?.conflict) return SOURCE_DIVISION_CONFLICT_MSG;
  if (!hasDivision(divisionId)) return DIVISION_REQUIRED_MSG;
  return null;
}

/** Label tampilan Satuan terpilih khusus Penyesuaian Stok: nama saja (fallback kode). */
export function adjustmentSelectedUnitLabel(uom) {
  if (!uom) return "";
  return String(uom.name || uom.code || "").trim();
}
