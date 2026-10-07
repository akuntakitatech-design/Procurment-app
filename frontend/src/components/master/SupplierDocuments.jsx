import { useCallback, useEffect, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Download, FileText, Trash2, Upload } from "lucide-react";
import { fmtDateTime } from "@/lib/format";
import { toast } from "sonner";

export const SUPPLIER_DOC_CATEGORIES = ["NPWP", "KTP", "NIB", "SIUP", "Akta Perusahaan", "Rekening Bank", "Surat Penawaran", "Kontrak", "Dokumen Pendukung", "Lainnya"];

/** Dokumen Supplier — memakai attachment engine existing (entity "supplier", entity_id = supplier.id). */
export function SupplierDocuments({ supplierId }) {
  const { can } = useAuth();
  const canView = can("view", "suppliers");
  const canManage = can("edit", "suppliers") && can("upload_attachment");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [category, setCategory] = useState("NPWP");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    if (!supplierId || !canView) { setRows([]); return; }
    setError(null);
    try { const r = await api.get("/attachments", { params: { entity: "supplier", entity_id: supplierId } }); setRows(r.data || []); }
    catch (e) { setError(apiError(e.response?.data?.detail)); setRows([]); }
  }, [supplierId, canView]);
  useEffect(() => { load(); }, [load]);

  const upload = async (e) => {
    const file = (e.target.files || [])[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file); fd.append("entity", "supplier"); fd.append("entity_id", supplierId);
    fd.append("category", category); fd.append("note", note.trim());
    try {
      await api.post("/attachments", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Dokumen ${category} terunggah`); setNote(""); load();
    } catch (err) { toast.error(apiError(err.response?.data?.detail) || "Gagal mengunggah dokumen"); }
    finally { setBusy(false); }
  };
  const open = async (f) => {
    try {
      const r = await api.get(`/attachments/${f.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a"); a.href = url; a.target = "_blank"; a.rel = "noreferrer";
      if (!/^(image|application\/pdf)/.test(f.content_type || "")) a.download = f.original_filename;
      a.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { toast.error("Dokumen tidak dapat dibuka"); }
  };
  const del = async (f) => {
    if (!window.confirm(`Hapus dokumen "${f.original_filename}"?`)) return;
    try { await api.delete(`/attachments/${f.id}`); toast.success("Dokumen dihapus"); load(); }
    catch (err) { toast.error(apiError(err.response?.data?.detail) || "Gagal menghapus dokumen"); }
  };

  if (!supplierId) return <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-sm text-muted-foreground" data-testid="supplier-docs-unsaved">Simpan supplier terlebih dahulu, lalu unggah dokumen (NPWP, KTP, NIB, dan lainnya).</div>;
  if (!canView) return <div className="text-sm text-muted-foreground" data-testid="supplier-docs-no-access">Anda tidak memiliki akses melihat dokumen supplier.</div>;

  return (
    <div className="space-y-3" data-testid="supplier-docs">
      {canManage && <div className="grid grid-cols-1 gap-2 rounded-lg border bg-background p-3 md:grid-cols-[220px_1fr_auto] md:items-end">
        <div className="space-y-1.5"><label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Kategori Dokumen</label>
          <Select value={category} onValueChange={setCategory}><SelectTrigger data-testid="supplier-docs-category"><SelectValue /></SelectTrigger>
            <SelectContent>{SUPPLIER_DOC_CATEGORIES.map((c) => <SelectItem key={c} value={c} data-testid={`supplier-docs-category-${c}`}>{c}</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1.5"><label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Catatan</label>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Contoh: berlaku s/d 2027" data-testid="supplier-docs-note" /></div>
        <div>
          <input ref={fileRef} type="file" className="hidden" onChange={upload} data-testid="supplier-docs-input" accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.csv,.txt" />
          <Button type="button" variant="outline" disabled={busy} onClick={() => fileRef.current?.click()} data-testid="supplier-docs-upload"><Upload className="mr-2 h-4 w-4" />{busy ? "Mengunggah..." : "Upload Dokumen"}</Button>
        </div>
      </div>}
      {error && <div className="flex items-center gap-2 text-sm text-destructive" data-testid="supplier-docs-error">{error}<Button type="button" variant="link" size="sm" onClick={load}>Coba lagi</Button></div>}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="p-2">Nama File</th><th className="p-2">Kategori</th><th className="p-2">Catatan</th><th className="p-2">Tanggal Upload</th><th className="p-2">Diupload Oleh</th><th className="p-2 text-right">Aksi</th></tr></thead>
          <tbody>
            {rows === null && [0, 1].map((i) => <tr key={i} className="border-t"><td colSpan={6} className="p-2"><Skeleton className="h-6 w-full" /></td></tr>)}
            {rows && rows.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-muted-foreground" data-testid="supplier-docs-empty">Belum ada dokumen supplier</td></tr>}
            {(rows || []).map((f) => <tr key={f.id} className="border-t" data-testid={`supplier-doc-row-${f.original_filename}`}>
              <td className="p-2"><span className="inline-flex items-center gap-2"><FileText className="h-4 w-4 text-muted-foreground" />{f.original_filename}</span></td>
              <td className="p-2" data-testid={`supplier-doc-category-${f.original_filename}`}>{f.category || "-"}</td>
              <td className="p-2" data-testid={`supplier-doc-note-${f.original_filename}`}>{f.note || "-"}</td>
              <td className="p-2 whitespace-nowrap">{fmtDateTime(f.created_at)}</td>
              <td className="p-2">{f.uploaded_by || "-"}</td>
              <td className="p-2"><div className="flex justify-end gap-1">
                <Button type="button" variant="ghost" size="sm" onClick={() => open(f)} data-testid={`supplier-doc-open-${f.original_filename}`}><Download className="mr-1 h-3.5 w-3.5" />Lihat/Download</Button>
                {canManage && <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={() => del(f)} aria-label="Hapus dokumen" data-testid={`supplier-doc-delete-${f.original_filename}`}><Trash2 className="h-3.5 w-3.5" /></Button>}
              </div></td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  );
}
