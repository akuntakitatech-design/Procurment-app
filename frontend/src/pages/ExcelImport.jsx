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
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const template = async () => {
    try {
      setBusy(true);
      const r = await api.get(`/excel/template/${item.key}`, { responseType: "blob" });
      downloadBlob(r.data, `template_${item.key}.xlsx`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || "Template gagal diunduh"); }
    finally { setBusy(false); }
  };

  const choose = () => inputRef.current?.click();
  const upload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      setBusy(true); setResult(null);
      const fd = new FormData(); fd.append("file", file);
      const r = await api.post(`/excel/import/${item.key}`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(r.data);
      if (r.data?.ok) toast.success(`${item.label}: ${r.data.imported || 0} berhasil diimport`);
      else toast.error(`${item.label}: file perlu diperbaiki`);
    } catch (err) {
      const msg = apiError(err.response?.data?.detail) || "Import gagal";
      setResult({ ok: false, errors: [msg] }); toast.error(msg);
    } finally { setBusy(false); }
  };

  return <Card className="overflow-hidden">
    <CardContent className="pt-5 space-y-4">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-xl bg-emerald-50 text-emerald-700 flex items-center justify-center shrink-0"><FileSpreadsheet className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1"><div className="font-head font-semibold">{item.label}</div><div className="text-xs text-muted-foreground mt-1">Kolom wajib: {(item.required || []).join(", ") || "-"}</div></div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={template} disabled={busy}><Download className="h-4 w-4 mr-2" />Download Template</Button>
        <Button size="sm" onClick={choose} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Upload className="h-4 w-4 mr-2" />}Upload Excel</Button>
        <input ref={inputRef} type="file" accept=".xlsx,.xlsm" className="hidden" onChange={upload} />
      </div>
      {item.key === "opening_inventory" && <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-2.5 text-xs text-amber-900">Harga beli diisi per satuan yang dipilih. Jika file yang sama diperbaiki dan diupload ulang, saldo awal item + gudang + proyek akan dikoreksi dengan selisih, bukan digandakan.</div>}
      {result && <div className={`rounded-lg border p-3 text-xs ${result.ok ? "border-emerald-200 bg-emerald-50/60" : "border-amber-200 bg-amber-50/60"}`}>
        <div className="flex items-center gap-2 font-semibold">{result.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}{result.ok ? "Import selesai" : "Ada data yang perlu diperbaiki"}</div>
        <div className="mt-1 text-muted-foreground">Baris terbaca: {result.rows ?? "-"} · Berhasil: {result.imported ?? 0}{result.created != null ? ` · Baru: ${result.created} · Update: ${result.updated}` : ""}</div>
        {(result.created_docs || []).length > 0 && <div className="mt-2 space-y-1">{result.created_docs.slice(0, 12).map((x, i) => <div key={i} className="font-mono">{x.batch_ref} → {x.no || x.id || "tersimpan"}</div>)}</div>}
        {(result.errors || []).length > 0 && <div className="mt-2 max-h-36 overflow-auto space-y-1 text-amber-900">{result.errors.map((x, i) => <div key={i}>• {x}</div>)}</div>}
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
