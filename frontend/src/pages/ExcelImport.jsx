import { useEffect, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Download, Upload, FileSpreadsheet, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { toast } from "sonner";

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ImportCard({ item }) {
  const inputRef = useRef(null);
  const timerRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);
  const [logBusy, setLogBusy] = useState(false);

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  const template = async () => {
    try {
      setBusy(true);
      const r = await api.get(`/excel/template/${item.key}`, { responseType: "blob" });
      downloadBlob(r.data, `template_${item.key}.xlsx`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || "Template gagal diunduh"); }
    finally { setBusy(false); }
  };

  const stopPoll = () => { if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; } };

  const poll = (id) => {
    stopPoll();
    timerRef.current = setInterval(async () => {
      try {
        const r = await api.get(`/excel/import-jobs/${id}`);
        setJob(r.data);
        const st = r.data?.status;
        if (st === "done" || st === "failed") {
          stopPoll(); setBusy(false);
          if (st === "done" && r.data?.success) toast.success(`${item.label}: ${r.data.ok || 0} baris berhasil`);
          else if (st === "done") toast.warning(`${item.label}: ${r.data?.failed || 0} baris gagal — unduh log untuk detail`);
          else toast.error(r.data?.error || "Import gagal");
        }
      } catch (e) {
        stopPoll(); setBusy(false);
        toast.error(apiError(e.response?.data?.detail) || "Gagal memantau progres import");
      }
    }, 1200);
  };

  const choose = () => inputRef.current?.click();
  const upload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      setBusy(true); setJob(null);
      const fd = new FormData(); fd.append("file", file);
      const r = await api.post(`/excel/import-jobs/${item.key}`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setJob(r.data);
      poll(r.data.id);
    } catch (err) {
      setBusy(false);
      const msg = apiError(err.response?.data?.detail) || "Import gagal";
      setJob({ status: "failed", error: msg, percent: 0 });
      toast.error(msg);
    }
  };

  const downloadLog = async () => {
    if (!job?.id) return;
    try {
      setLogBusy(true);
      const r = await api.get(`/excel/import-jobs/${job.id}/log.xlsx`, { responseType: "blob" });
      downloadBlob(r.data, `log_import_${item.key}.xlsx`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || "Log gagal diunduh"); }
    finally { setLogBusy(false); }
  };

  const pct = job?.percent ?? 0;
  const running = job && (job.status === "queued" || job.status === "running");
  const done = job?.status === "done";
  const failed = job?.status === "failed";

  return <Card className="overflow-hidden" data-testid={`excel-import-card-${item.key}`}>
    <CardContent className="pt-5 space-y-4">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-xl bg-emerald-50 text-emerald-700 flex items-center justify-center shrink-0"><FileSpreadsheet className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1"><div className="font-head font-semibold">{item.label}</div><div className="text-xs text-muted-foreground mt-1">Kolom wajib: {(item.required || []).join(", ") || "-"}</div></div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={template} disabled={busy} data-testid={`excel-template-${item.key}`}><Download className="h-4 w-4 mr-2" />Download Template</Button>
        <Button size="sm" onClick={choose} disabled={busy} data-testid={`excel-upload-${item.key}`}>{busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Upload className="h-4 w-4 mr-2" />}{running ? "Memproses..." : "Upload Excel"}</Button>
        <input ref={inputRef} type="file" accept=".xlsx,.xlsm" className="hidden" onChange={upload} data-testid={`excel-file-${item.key}`} />
      </div>
      {item.key === "opening_inventory" && <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-2.5 text-xs text-amber-900">Harga beli diisi per satuan yang dipilih. Jika file yang sama diperbaiki dan diupload ulang, saldo awal item + gudang + proyek akan dikoreksi dengan selisih, bukan digandakan.</div>}
      {job && <div data-testid={`excel-result-${item.key}`} className={`rounded-lg border p-3 text-xs ${failed ? "border-destructive/40 bg-destructive/5" : done && job.success ? "border-emerald-200 bg-emerald-50/60" : done ? "border-amber-200 bg-amber-50/60" : "border-blue-200 bg-blue-50/60"}`}>
        <div className="flex items-center gap-2 font-semibold">
          {running ? <Loader2 className="h-4 w-4 animate-spin text-blue-600" /> : failed ? <AlertTriangle className="h-4 w-4 text-destructive" /> : done && job.success ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}
          {running ? `Memproses ${pct}%` : failed ? "Import gagal" : done && job.success ? "Import selesai" : "Ada data yang perlu diperbaiki"}
        </div>
        {running && <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted" data-testid={`excel-progress-${item.key}`}><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>}
        <div className="mt-1 text-muted-foreground" data-testid={`excel-counts-${item.key}`}>
          Baris: {job.total ?? "-"} · Diproses: {job.processed ?? 0} · Berhasil: {job.ok ?? 0} · Gagal: {job.failed ?? 0}{job.skipped ? ` · Tidak diproses: ${job.skipped}` : ""}
        </div>
        {job.summary && (job.summary.imported != null || job.summary.created != null) && <div className="mt-1 text-muted-foreground">Dokumen/record: {job.summary.imported ?? 0}{job.summary.created != null ? ` · Baru: ${job.summary.created} · Update: ${job.summary.updated}` : ""}</div>}
        {failed && job.error && <div className="mt-2 text-destructive">{job.error}</div>}
        {(job.errors_preview || []).length > 0 && <div className="mt-2 max-h-32 overflow-auto space-y-1 text-amber-900">{job.errors_preview.map((x, i) => <div key={i}>• {x}</div>)}</div>}
        {done && <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={downloadLog} disabled={logBusy || !job.has_log} data-testid={`excel-log-${item.key}`}>
            {logBusy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Download className="h-4 w-4 mr-2" />}Download Log Excel
          </Button>
          <span className="self-center text-muted-foreground">Log berisi status tiap baris beserta pesan error.</span>
        </div>}
      </div>}
    </CardContent>
  </Card>;
}

export default function ExcelImport() {
  const [data, setData] = useState({ masters: [], transactions: [] });
  const [loading, setLoading] = useState(true);
  useEffect(() => { api.get("/excel/datasets").then(r => setData(r.data || { masters: [], transactions: [] })).catch(e => toast.error(apiError(e.response?.data?.detail))).finally(() => setLoading(false)); }, []);

  return <div className="space-y-7">
    <PageHeader title="Import Excel" subtitle="Upload data massal menggunakan template resmi aplikasi. Template menjaga nama kolom dan kode referensi tetap konsisten." />
    <div className="rounded-xl border bg-blue-50/50 p-4 text-sm text-slate-700">
      <b>Alur aman:</b> download template → isi tanpa mengubah nama header → upload kembali. Untuk transaksi, gunakan <code className="font-mono">batch_ref</code> yang sama untuk beberapa baris item dalam satu dokumen. Nomor transaksi tetap dibuat otomatis oleh sistem.
    </div>
    {loading ? <div className="text-sm text-muted-foreground">Memuat daftar template...</div> : <>
      <section className="space-y-3"><div><h2 className="font-head text-lg font-semibold">Master Data & Saldo Awal</h2><p className="text-sm text-muted-foreground">Barang, supplier, unit/aset, stok minimal/maksimal, dan saldo awal persediaan beserta harga beli.</p></div><div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">{data.masters.map(x => <ImportCard key={x.key} item={x} />)}</div></section>
      <section className="space-y-3"><div><h2 className="font-head text-lg font-semibold">Seluruh Transaksi</h2><p className="text-sm text-muted-foreground">MRO, RO, PO, DO, MI, transfer, pinjaman, return, adjustment, dan stock opname. Validasi stok dan traceability tetap mengikuti aturan transaksi aplikasi.</p></div><div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">{data.transactions.map(x => <ImportCard key={x.key} item={x} />)}</div></section>
    </>}
  </div>;
}
