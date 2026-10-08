import { useEffect, useRef, useState } from "react";
import api, { API, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CheckCircle2, FileText, Loader2, RotateCcw, Trash2, Upload, XCircle } from "lucide-react";
import { toast } from "sonner";

// Lampiran Transfer SEBELUM posting (pola MRO: pilih file -> Posting sekali klik).
// File langsung diunggah sebagai draft server-side (milik tenant + user aktif) dan baru terikat ke
// Transfer final setelah posting sukses. Validasi tipe/ukuran memakai aturan lampiran existing di backend.
export function TransferDraftAttachments({ draftId, draftError, onRetryDraft, onStateChange, testid = "trf-draft-attachments" }) {
  const [files, setFiles] = useState([]); // {key, name, status: uploading|ready|failed, id?, error?, file?}
  const cb = useRef(onStateChange);
  cb.current = onStateChange;

  useEffect(() => {
    if (!draftId) { setFiles([]); return; }
    let live = true;
    // Gabungkan (bukan timpa): file yang dipilih user selama request ini berjalan tidak boleh hilang.
    api.get(`/attachments?entity=transfer_draft&entity_id=${draftId}`)
      .then((r) => live && setFiles((fs) => {
        const known = new Set(fs.map((f) => f.id).filter(Boolean));
        const loaded = (r.data || []).filter((f) => !known.has(f.id)).map((f) => ({ key: f.id, id: f.id, name: f.original_filename, status: "ready" }));
        return [...loaded, ...fs];
      }))
      .catch(() => {});
    return () => { live = false; };
  }, [draftId]);

  useEffect(() => {
    cb.current?.({ uploading: files.some((f) => f.status === "uploading"), failed: files.filter((f) => f.status === "failed").length, ready: files.filter((f) => f.status === "ready").length });
  }, [files]);

  const patch = (key, p) => setFiles((fs) => fs.map((f) => (f.key === key ? { ...f, ...p } : f)));
  const send = async (key, file) => {
    patch(key, { status: "uploading", error: null });
    const fd = new FormData();
    fd.append("file", file); fd.append("entity", "transfer_draft"); fd.append("entity_id", draftId); fd.append("category", "Lampiran Transfer");
    try {
      const r = await api.post("/attachments", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setFiles((fs) => fs.filter((f) => f.key === key || f.id !== r.data.id).map((f) => (f.key === key ? { ...f, status: "ready", id: r.data.id, file: null } : f)));
    } catch (e) {
      patch(key, { status: "failed", error: apiError(e.response?.data?.detail) || "Gagal mengunggah", file });
    }
  };
  const pick = (e) => {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    if (!picked.length || !draftId) return;
    const rows = picked.map((file) => ({ key: `${Date.now()}-${Math.random().toString(36).slice(2)}`, name: file.name, status: "uploading", file }));
    setFiles((fs) => [...fs, ...rows]);
    rows.forEach((r) => send(r.key, r.file));
  };
  const remove = async (f) => {
    if (f.id) {
      try { await api.delete(`/attachments/${f.id}`); } catch (err) { toast.error(apiError(err.response?.data?.detail) || "Gagal menghapus lampiran"); return; }
    }
    setFiles((fs) => fs.filter((x) => x.key !== f.key));
  };

  if (!draftId) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid={`${testid}-status`}>
        {draftError ? <><XCircle className="h-4 w-4 text-destructive" /><span className="text-destructive">{draftError}</span>{onRetryDraft && <Button variant="outline" size="sm" onClick={onRetryDraft} data-testid={`${testid}-retry-draft`}><RotateCcw className="mr-2 h-3.5 w-3.5" />Coba lagi</Button>}</>
          : <><Loader2 className="h-4 w-4 animate-spin" />Menyiapkan lampiran...</>}
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid={testid}>
      <label className="inline-flex">
        <input type="file" multiple className="hidden" onChange={pick} data-testid={`${testid}-input`} />
        <Button asChild variant="outline" size="sm"><span className="cursor-pointer"><Upload className="mr-2 h-4 w-4" />Pilih File</span></Button>
      </label>
      <div className="space-y-2">
        {files.length === 0 && <p className="text-sm text-muted-foreground" data-testid={`${testid}-empty`}>Belum ada lampiran (opsional).</p>}
        {files.map((f, i) => (
          <div key={f.key} className="flex items-center gap-2 rounded-md border p-2 text-sm" data-testid={`${testid}-file-${i}`}>
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            {f.id ? <a href={`${API}/attachments/${f.id}/download`} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:underline">{f.name}</a> : <span className="min-w-0 flex-1 truncate">{f.name}</span>}
            {f.status === "uploading" && <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" data-testid={`${testid}-file-status-${i}`}><Loader2 className="h-3 w-3 animate-spin" />Mengunggah...</span>}
            {f.status === "ready" && <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700" data-testid={`${testid}-file-status-${i}`}><CheckCircle2 className="h-3.5 w-3.5" />siap</span>}
            {f.status === "failed" && <span className="inline-flex items-center gap-1 text-xs text-destructive" title={f.error} data-testid={`${testid}-file-status-${i}`}><XCircle className="h-3.5 w-3.5" />{f.error}</span>}
            {f.status === "failed" && f.file && <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => send(f.key, f.file)} aria-label="Unggah ulang" data-testid={`${testid}-file-retry-${i}`}><RotateCcw className="h-3.5 w-3.5" /></Button>}
            <Button variant="ghost" size="icon" className="h-7 w-7" disabled={f.status === "uploading"} onClick={() => remove(f)} aria-label={`Hapus ${f.name}`} data-testid={`${testid}-file-remove-${i}`}><Trash2 className="h-3.5 w-3.5" /></Button>
          </div>
        ))}
      </div>
    </div>
  );
}
