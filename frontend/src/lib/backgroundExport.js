import { toast } from "sonner";
import api from "@/lib/api";
import { JOB_DONE, JOB_FAILED, jobLabel, pollDelay } from "@/lib/exportJob";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function downloadJob(job) {
  const r = await api.get(`/report-center/export-jobs/${job.id}/download`, { responseType: "blob" });
  const url = window.URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url; a.download = job.filename || `${job.key}.${job.fmt}`; document.body.appendChild(a); a.click(); a.remove();
  window.URL.revokeObjectURL(url);
}

const errText = async (e) => {
  const d = e?.response?.data;
  try { if (d instanceof Blob) return JSON.parse(await d.text()).detail || "Export gagal."; } catch { /* bukan JSON */ }
  return d?.detail || "Export gagal. Coba lagi.";
};

/** Pantau job sampai selesai; notifikasi status (toast id tetap) + tombol Download / Ulangi. */
export async function watchJob(job) {
  const id = `export-job-${job.id}`;
  toast.loading(jobLabel(job), { id, duration: Infinity, description: "Anda dapat tetap memakai menu lain." });
  let cur = job;
  for (let i = 0; i < 720 && !(cur.status === JOB_DONE || JOB_FAILED.has(cur.status)); i += 1) {
    await sleep(pollDelay(i));
    try { cur = (await api.get(`/report-center/export-jobs/${job.id}`)).data; } catch (e) { toast.error(await errText(e), { id, duration: 8000 }); return; }
    if (!(cur.status === JOB_DONE || JOB_FAILED.has(cur.status))) toast.loading(jobLabel(cur), { id, duration: Infinity });
  }
  if (cur.status === JOB_DONE) {
    toast.success(jobLabel(cur), {
      id, duration: Infinity, closeButton: true,
      action: { label: "Download", onClick: () => downloadJob(cur).catch(async (e) => toast.error(await errText(e))) },
    });
    return;
  }
  toast.error(jobLabel(cur), {
    id, duration: Infinity, closeButton: true,
    action: { label: "Ulangi", onClick: async () => {
      try { watchJob((await api.post(`/report-center/export-jobs/${job.id}/retry`)).data); } catch (e) { toast.error(await errText(e)); }
    } },
  });
}

/** Buat job export background lalu pantau. */
export async function startBackgroundExport(key, fmt, qs) {
  try {
    const r = await api.post(`/report-center/${encodeURIComponent(key)}/export-jobs?fmt=${fmt}${qs ? `&${qs}` : ""}`);
    watchJob(r.data);
  } catch (e) { toast.error(await errText(e)); }
}
