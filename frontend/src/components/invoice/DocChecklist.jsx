import { useCallback, useEffect, useMemo, useState } from "react";
import api, { API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/Combobox";
import { uploadPendingAttachments } from "@/components/DocMeta";
import { CHECKLIST_OPTIONS, CHECK_VALUES, normalizeChecklist } from "@/lib/docChecklist";
import { FileText, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

const STATUS_OPTIONS = CHECK_VALUES.map((v) => ({ value: v, label: v }));

/**
 * Checklist 8 jenis dokumen + lampiran per jenis (multi-file).
 * `invoiceId` kosong -> hanya status (lampiran diunggah setelah invoice tersimpan).
 */
export function DocChecklist({ value, onStatus, invoiceId, canEdit = true, onFilesChanged }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState("");
  const checklist = normalizeChecklist(value);

  const load = useCallback(() => {
    if (!invoiceId) { setFiles([]); onFilesChanged?.([]); return; }
    api.get(`/attachments?entity=invoice&entity_id=${invoiceId}`)
      .then((r) => { const rows = r.data || []; setFiles(rows); onFilesChanged?.(rows); })
      .catch(() => setFiles([]));
  }, [invoiceId, onFilesChanged]);
  useEffect(() => { load(); }, [load]);

  const byCat = useMemo(() => {
    const m = {};
    for (const f of files) { const c = f.category || "Lainnya"; (m[c] = m[c] || []).push(f); }
    return m;
  }, [files]);

  const upload = async (category, e) => {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    if (!picked.length || !invoiceId) return;
    setBusy(category);
    const { failed } = await uploadPendingAttachments("invoice", invoiceId, picked, category);
    setBusy("");
    if (failed.length) toast.error(`${failed.length} file gagal diunggah`);
    else toast.success(`${picked.length} file terunggah · ${category}`);
    load();
  };

  const del = async (id) => {
    try { await api.delete(`/attachments/${id}`); load(); }
    catch (err) { toast.error(err.response?.data?.detail || "Gagal menghapus lampiran"); }
  };

  return (
    <div className="divide-y rounded-lg border" data-testid="invoice-doc-checklist">
      {CHECKLIST_OPTIONS.map((opt) => {
        const status = checklist[opt.key];
        const list = byCat[opt.category] || [];
        return (
          <div key={opt.key} className="grid grid-cols-1 items-center gap-2 p-3 md:grid-cols-[1fr_170px_150px_auto]" data-testid={`checklist-row-${opt.key}`}>
            <div className="min-w-0">
              <div className="text-sm font-medium">{opt.label}</div>
              {list.length > 0 && (
                <div className="mt-1 space-y-0.5">
                  {list.map((f) => (
                    <div key={f.id} className="flex items-center gap-1.5 text-xs" data-testid={`checklist-file-${opt.key}-${f.id}`}>
                      <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <a href={`${API}/attachments/${f.id}/download`} target="_blank" rel="noreferrer" className="truncate hover:underline">{f.original_filename}</a>
                      {canEdit && <Button type="button" variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={() => del(f.id)} aria-label={`Hapus ${f.original_filename}`}><Trash2 className="h-3 w-3" /></Button>}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="w-full md:w-40">
              <Combobox options={STATUS_OPTIONS} value={status} onChange={(v) => onStatus?.(opt.key, v)} disabled={!canEdit} testid={`checklist-status-${opt.key}`} dense />
            </div>
            <div className="text-xs text-muted-foreground" data-testid={`checklist-files-${opt.key}`}>
              {list.length ? `${list.length} file digital` : "Belum ada file"}
            </div>
            <div className="flex items-center gap-2">
              {canEdit && invoiceId && (
                <label className="inline-flex">
                  <input type="file" multiple className="hidden" onChange={(e) => upload(opt.category, e)} data-testid={`checklist-upload-${opt.key}`} />
                  <Button asChild type="button" variant="outline" size="sm" disabled={busy === opt.category}>
                    <span className="cursor-pointer"><Upload className="mr-1.5 h-3.5 w-3.5" />{busy === opt.category ? "Mengunggah..." : "Upload"}</span>
                  </Button>
                </label>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
