import { useEffect, useState } from "react";
import api, { API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Paperclip, Upload, Trash2, FileText, History } from "lucide-react";
import { fmtDateTime } from "@/lib/format";
import { toast } from "sonner";

export function AttachmentPanel({ entity, entityId }) {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const load = () => {
    if (!entityId) { setFiles([]); return; }
    api.get(`/attachments?entity=${entity}&entity_id=${entityId}`).then((r) => setFiles(r.data));
  };
  useEffect(() => { load(); }, [entity, entityId]);

  const upload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!entityId) {
      toast.info("Simpan transaksi terlebih dahulu. Setelah nomor transaksi terbentuk, lampiran dapat langsung diunggah di halaman yang sama.");
      e.target.value = "";
      return;
    }
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file); fd.append("entity", entity); fd.append("entity_id", entityId); fd.append("category", "Lainnya");
    try {
      await api.post("/attachments", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("File terunggah"); load();
    } catch { toast.error("Gagal upload"); }
    setUploading(false); e.target.value = "";
  };
  const del = async (id) => { await api.delete(`/attachments/${id}`); load(); };

  return (
    <div className="space-y-3">
      {!entityId && (
        <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          Lampiran tersedia di form ini. Simpan transaksi terlebih dahulu agar nomor transaksi terbentuk, lalu upload file tanpa berpindah menu.
        </div>
      )}
      <label className={`inline-flex ${!entityId ? "opacity-60" : ""}`}>
        <input type="file" className="hidden" onChange={upload} data-testid="attachment-input" />
        <Button asChild variant="outline" size="sm" disabled={uploading || !entityId}>
          <span className={entityId ? "cursor-pointer" : "cursor-not-allowed"}><Upload className="h-4 w-4 mr-2" />{uploading ? "Mengunggah..." : "Upload File"}</span>
        </Button>
      </label>
      <div className="space-y-2">
        {entityId && files.length === 0 && <p className="text-sm text-muted-foreground">Belum ada lampiran</p>}
        {files.map((f) => (
          <div key={f.id} className="flex items-center gap-2 rounded-md border p-2 text-sm">
            <FileText className="h-4 w-4 text-muted-foreground" />
            <a href={`${API}/attachments/${f.id}/download`} target="_blank" rel="noreferrer" className="flex-1 truncate hover:underline">{f.original_filename}</a>
            <span className="text-xs text-muted-foreground">{f.category}</span>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => del(f.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AuditPanel({ entity, entityId }) {
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
            <span className="font-medium capitalize">{l.action}</span> oleh <span className="font-medium">{l.user_name || l.user}</span>
            {l.reason && <span className="text-muted-foreground"> — {l.reason}</span>}
            <div className="text-xs text-muted-foreground">{fmtDateTime(l.at)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
