import { useCallback, useEffect, useState, useRef } from "react";
import api, { API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Upload, Trash2, FileText, History, Clock } from "lucide-react";
import { fmtDateTime } from "@/lib/format";
import { toast } from "sonner";

/**
 * Upload a batch of pending (in-memory) File objects to an entity once its ID
 * exists. Returns which files succeeded/failed so the caller can decide whether
 * to submit. Never throws for individual failures.
 */
export async function uploadPendingAttachments(entity, entityId, files, category = "Lainnya") {
  const uploaded = [];
  const failed = [];
  for (const file of files || []) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("entity", entity);
    fd.append("entity_id", entityId);
    fd.append("category", category);
    try {
      await api.post("/attachments", fd, { headers: { "Content-Type": "multipart/form-data" } });
      uploaded.push(file);
    } catch {
      failed.push(file);
    }
  }
  return { uploaded, failed };
}

export function AttachmentPanel({ entity, entityId, pending, onPendingChange, multiple = false, canUpload = true, canDelete = true, onFilesChange }) {
  const [files, setFiles] = useState([]);
  const filesCb = useRef(onFilesChange);
  filesCb.current = onFilesChange;
  const [uploading, setUploading] = useState(false);
  // Pending mode is active when the document has no ID yet AND the parent form
  // opted in by providing onPendingChange (e.g. a brand-new MRO being created).
  const pendingMode = !entityId && typeof onPendingChange === "function";
  const pendingList = pending || [];

  const load = useCallback(() => {
    if (!entityId) { setFiles([]); return; }
    api.get(`/attachments?entity=${entity}&entity_id=${entityId}`).then((r) => { setFiles(r.data); filesCb.current?.(r.data || []); });
  }, [entity, entityId]);
  useEffect(() => { load(); }, [load]);

  // Select files BEFORE first save — keep them in memory (never localStorage).
  const pickPending = (e) => {
    const picked = Array.from(e.target.files || []);
    if (picked.length) onPendingChange([...(pending || []), ...picked]);
    e.target.value = "";
  };
  const removePending = (idx) => onPendingChange((pending || []).filter((_, i) => i !== idx));

  const upload = async (e) => {
    const picked = Array.from(e.target.files || []);
    if (!picked.length) return;
    setUploading(true);
    const { failed } = await uploadPendingAttachments(entity, entityId, picked);
    if (failed.length) toast.error(`Gagal upload: ${failed.map((f) => f.name).join(", ")}`);
    if (failed.length < picked.length) toast.success("File terunggah");
    load(); setUploading(false); e.target.value = "";
  };
  const del = async (id) => {
    try { await api.delete(`/attachments/${id}`); } catch (err) { toast.error(err.response?.data?.detail || "Gagal menghapus lampiran"); }
    load();
  };

  // ---------- Pending mode (new, unsaved document) ----------
  if (pendingMode) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          Pilih lampiran sekarang. File ditahan sementara dan otomatis terunggah saat transaksi pertama kali disimpan.
        </div>
        <label className="inline-flex">
          <input type="file" multiple className="hidden" onChange={pickPending} data-testid="attachment-pending-input" />
          <Button asChild variant="outline" size="sm">
            <span className="cursor-pointer"><Upload className="h-4 w-4 mr-2" />Pilih File</span>
          </Button>
        </label>
        <div className="space-y-2">
          {pendingList.length === 0 && <p className="text-sm text-muted-foreground">Belum ada lampiran dipilih</p>}
          {pendingList.map((f, i) => (
            <div key={`${f.name}-${i}`} className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/60 p-2 text-sm" data-testid={`attachment-pending-${i}`}>
              <FileText className="h-4 w-4 text-amber-600" />
              <span className="flex-1 truncate">{f.name}</span>
              <span className="inline-flex items-center gap-1 text-xs text-amber-700"><Clock className="h-3 w-3" />Menunggu disimpan</span>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => removePending(i)} data-testid={`attachment-pending-remove-${i}`}><Trash2 className="h-3.5 w-3.5" /></Button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ---------- Normal mode (document already saved) ----------
  return (
    <div className="space-y-3">
      {!entityId && (
        <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          Lampiran tersedia di form ini. Simpan transaksi terlebih dahulu agar nomor transaksi terbentuk, lalu upload file tanpa berpindah menu.
        </div>
      )}
      {canUpload && <label className={`inline-flex ${!entityId ? "opacity-60" : ""}`}>
        <input type="file" multiple={multiple} className="hidden" onChange={upload} data-testid="attachment-input" />
        <Button asChild variant="outline" size="sm" disabled={uploading || !entityId}>
          <span className={entityId ? "cursor-pointer" : "cursor-not-allowed"}><Upload className="h-4 w-4 mr-2" />{uploading ? "Mengunggah..." : "Upload File"}</span>
        </Button>
      </label>}
      <div className="space-y-2">
        {entityId && files.length === 0 && <p className="text-sm text-muted-foreground">Belum ada lampiran</p>}
        {files.map((f) => (
          <div key={f.id} className="flex items-center gap-2 rounded-md border p-2 text-sm" data-testid={`attachment-item-${f.original_filename}`}>
            <FileText className="h-4 w-4 text-muted-foreground" />
            <a href={`${API}/attachments/${f.id}/download`} target="_blank" rel="noreferrer" className="flex-1 truncate hover:underline">{f.original_filename}</a>
            <span className="text-xs text-muted-foreground">{f.category}</span>
            {canDelete && <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => del(f.id)} data-testid={`attachment-delete-${f.original_filename}`} aria-label="Hapus lampiran"><Trash2 className="h-3.5 w-3.5" /></Button>}
          </div>
        ))}
      </div>
    </div>
  );
}

// Label aksi audit yang ditambahkan fitur Pengajuan Approval 2 (aksi lain tetap tampil apa adanya).
const AUDIT_LABELS = { approval2_batch_add: "Masuk Pengajuan Approval 2", approval2_batch_approve: "Approval 2 via batch" };

export function AuditPanel({ entity, entityId, labels }) {
  const [logs, setLogs] = useState([]);
  useEffect(() => { if (entityId) api.get(`/audit?entity=${entity}&entity_id=${entityId}`).then((r) => setLogs(r.data)); else setLogs([]); }, [entity, entityId]);
  return (
    <div className="space-y-2">
      {!entityId && <p className="text-sm text-muted-foreground">Riwayat aktivitas akan tersedia setelah transaksi disimpan.</p>}
      {entityId && logs.length === 0 && <p className="text-sm text-muted-foreground">Belum ada riwayat</p>}
      {logs.map((l) => (
        <div key={l.id} className="flex items-start gap-3 border-l-2 border-primary/40 pl-3 py-1">
          <History className="h-4 w-4 mt-0.5 text-muted-foreground" />
          <div className="text-sm">
            <span className="font-medium capitalize">{labels?.[l.action] || AUDIT_LABELS[l.action] || l.action}</span> oleh <span className="font-medium">{l.user_name || l.user}</span>
            {l.reason && <span className="text-muted-foreground"> — {l.reason}</span>}
            <div className="text-xs text-muted-foreground">{fmtDateTime(l.at)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
