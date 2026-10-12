// P7 — export besar diproses di background (job server) lalu diunduh; export kecil tetap langsung (perilaku lama).
export const BG_EXPORT_ROWS = 5000;

/** "background" bila Excel dengan hasil > BG_EXPORT_ROWS baris; selain itu "direct" (PDF maks 5.000 baris selalu langsung). */
export function exportMode(total, fmt) {
  const n = Number(total);
  return fmt === "xlsx" && Number.isFinite(n) && n > BG_EXPORT_ROWS ? "background" : "direct";
}

export const JOB_DONE = "done";
export const JOB_FAILED = new Set(["failed", "expired"]);

/** Teks status job untuk notifikasi. */
export function jobLabel(job) {
  const s = job?.status;
  if (s === "queued") return "Menunggu antrian export...";
  if (s === "running") return "Export sedang diproses di background...";
  if (s === JOB_DONE) return `Export siap diunduh (${Number(job.rows || 0).toLocaleString("id-ID")} baris).`;
  if (s === "expired") return "File export sudah kedaluwarsa.";
  return job?.error || "Export gagal diproses.";
}

/** Interval polling (ms): cepat di awal, melambat untuk job panjang; berhenti setelah batas waktu. */
export function pollDelay(attempt) {
  return attempt < 5 ? 1500 : attempt < 20 ? 3000 : 5000;
}
