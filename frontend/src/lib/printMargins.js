// Margin cetak per sisi dari konfigurasi Layout Dokumen (satu sumber untuk renderer PO REAL, template generik, dan pratinjau).
// Urutan prioritas: margin_{sisi}_mm -> margin_mm (data lama, satu nilai) -> fallback. Rentang validasi = backend (5..30 mm).
// Tidak ada margin tetap di template: nilai cetak = nilai tersimpan.
export const MARGIN_SIDES = ["top", "right", "bottom", "left"];
export const MARGIN_LABELS = { top: "Atas", right: "Kanan", bottom: "Bawah", left: "Kiri" };
export const MARGIN_RANGE = { min: 5, max: 30 };
export const marginKey = (side) => `margin_${side}_mm`;

const clamp = (v) => Math.round(Math.max(MARGIN_RANGE.min, Math.min(MARGIN_RANGE.max, v)) * 10) / 10;
const num = (v) => {
  if (v === "" || v === null || v === undefined) return NaN;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : NaN;
};

/** @returns {{top:number,right:number,bottom:number,left:number}} margin mm per sisi */
export function layoutMargins(layout = {}, fallback = 12) {
  const legacy = num(layout?.margin_mm);
  const base = Number.isFinite(legacy) ? legacy : fallback;
  const out = {};
  for (const s of MARGIN_SIDES) {
    const v = num(layout?.[marginKey(s)]);
    out[s] = clamp(Number.isFinite(v) ? v : base);
  }
  return out;
}

/** Nilai CSS urutan atas kanan bawah kiri, mis. "20mm 15mm 20mm 15mm". */
export const cssMargin = (m) => `${m.top}mm ${m.right}mm ${m.bottom}mm ${m.left}mm`;

/** Tinggi/lebar area isi per halaman (mm) setelah margin. */
export function contentBox(paperMm, m) {
  return { width: paperMm[0] - m.left - m.right, height: paperMm[1] - m.top - m.bottom };
}

/**
 * Gabung default + layout tersimpan dengan aturan migrasi yang sama seperti backend:
 * tersimpan punya sisi -> pakai sisi; hanya margin_mm (data lama) -> keempat sisi = margin_mm; selain itu default.
 */
export function mergeLayout(defaults = {}, saved = {}) {
  const out = { ...defaults, ...(saved || {}) };
  const hasSide = MARGIN_SIDES.some((s) => saved && saved[marginKey(s)] !== undefined && saved[marginKey(s)] !== null && saved[marginKey(s)] !== "");
  if (!hasSide && saved && Number.isFinite(num(saved.margin_mm))) {
    for (const s of MARGIN_SIDES) out[marginKey(s)] = num(saved.margin_mm);
  }
  return out;
}

/** Catatan untuk dialog cetak browser (layar saja, tidak ikut tercetak). */
export const PRINT_DIALOG_HINT = "Agar margin sesuai Layout Dokumen: pada dialog cetak pilih Margins/Margin = Default, Scale/Skala = 100% (Default), dan matikan Headers and footers.";
