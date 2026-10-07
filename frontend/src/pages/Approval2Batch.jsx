import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toJpeg } from "html-to-image";
import api, { apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import { StatusBadge } from "@/components/StatusBadge";
import { AttachmentPanel, AuditPanel } from "@/components/DocMeta";
import { Approval2Document } from "@/components/approval2/Approval2Document";
import { a2Access, approval2FileName, fmtA2Date, fmtDateTimeSafe, fmtPpn, fmtRp, toggleId } from "@/lib/approval2";
import { useAuth } from "@/context/AuthContext";
import { ArrowLeft, CheckCheck, Download, Eye, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const A2_AUDIT_LABELS = {
  create: "Pengajuan dibuat", add_po: "Tambah PO ke pengajuan", submit: "Diajukan (export JPEG)", export: "Export JPEG ulang",
  upload_approval_evidence: "Upload bukti persetujuan", upload_file: "Upload lampiran", bulk_approve: "Approve terpilih", delete_file: "Hapus lampiran",
};

async function renderJpeg(node) {
  const opts = { quality: 0.95, pixelRatio: 2, backgroundColor: "#ffffff", cacheBust: true, width: node.offsetWidth, height: node.offsetHeight };
  try { return await toJpeg(node, opts); } catch { return await toJpeg(node, { ...opts, skipFonts: true }); }
}

export default function Approval2Batch() {
  const { id } = useParams();
  const nav = useNavigate();
  const docRef = useRef(null);
  const { can } = useAuth();
  const [b, setB] = useState(null);
  const [error, setError] = useState(null);
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState(null);
  const [evidenceCount, setEvidenceCount] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get(`/approval2/po/batches/${id}`);
      setB(r.data); setEvidenceCount((r.data.evidence || []).length);
      setSel((s) => s.filter((x) => (r.data.items || []).some((i) => i.id === x && i.can_approve)));
    } catch (e) { setError(apiError(e.response?.data?.detail)); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const items = useMemo(() => b?.items || [], [b]);
  const approvable = items.filter((i) => i.can_approve);
  const allChecked = approvable.length > 0 && approvable.every((i) => sel.includes(i.id));
  const onFilesChange = useCallback((files) => setEvidenceCount(files.length), []);

  const doPreview = async () => {
    setBusy("preview");
    try { setPreview(await renderJpeg(docRef.current)); } catch { toast.error("Gagal membuat preview JPEG"); } finally { setBusy(""); }
  };
  const doExport = async () => {
    setBusy("export");
    try {
      const url = await renderJpeg(docRef.current);
      const a = document.createElement("a");
      a.href = url; a.download = approval2FileName(b.title, b.submission_date); a.click();
      await api.post(`/approval2/po/batches/${id}/submit`, {});
      toast.success("JPEG diunduh. Kirim ke grup pimpinan, lalu kembali untuk upload bukti persetujuan.");
      load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || "Gagal export JPEG"); } finally { setBusy(""); }
  };
  const approve = async () => {
    if (!sel.length) return;
    if (!window.confirm(`Approve ${sel.length} PO terpilih berdasarkan bukti persetujuan pimpinan?`)) return;
    setBusy("approve");
    try {
      const r = await api.post(`/approval2/po/batches/${id}/approve`, { item_ids: sel });
      toast.success(`${sel.length} PO disetujui`); setSel([]); setB(r.data); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(""); }
  };

  if (error) return <div className="p-6"><Card><CardContent className="p-8 text-center" data-testid="approval2-batch-error"><div className="mb-3 text-destructive">{error}</div><Button variant="outline" onClick={load}>Coba lagi</Button></CardContent></Card></div>;
  if (!b) return <div className="space-y-4"><Skeleton className="h-10 w-1/3" /><Skeleton className="h-40 w-full" /><Skeleton className="h-64 w-full" /></div>;
  const isDraft = b.status === "Draft";
  const acc = a2Access(can, b.status);
  const canApprove = acc.approve && !isDraft && sel.length > 0 && evidenceCount > 0;

  return <div data-testid="approval2-batch-page">
    <Breadcrumb className="mb-3"><BreadcrumbList>
      <BreadcrumbItem><BreadcrumbLink className="cursor-pointer" onClick={() => nav("/approval")}>Approval</BreadcrumbLink></BreadcrumbItem><BreadcrumbSeparator />
      <BreadcrumbItem><BreadcrumbLink className="cursor-pointer" onClick={() => nav("/approval?view=approval2")}>Pengajuan Approval 2</BreadcrumbLink></BreadcrumbItem><BreadcrumbSeparator />
      <BreadcrumbItem><BreadcrumbPage>Detail Batch</BreadcrumbPage></BreadcrumbItem>
    </BreadcrumbList></Breadcrumb>
    <PageHeader title={b.title} subtitle={`Pengajuan Approval 2 PO · ${b.no}`}>
      <Button variant="outline" onClick={() => nav("/approval?view=approval2")}><ArrowLeft className="h-4 w-4 mr-2" />Kembali</Button>
      <Button variant="outline" onClick={load}><RefreshCw className="h-4 w-4 mr-2" />Refresh</Button>
      {acc.canPreview && <Button variant="outline" onClick={doPreview} disabled={!!busy} data-testid="approval2-preview-jpeg"><Eye className="h-4 w-4 mr-2" />{busy === "preview" ? "Menyiapkan..." : "Preview JPEG"}</Button>}
      {acc.canExport && <Button onClick={doExport} disabled={!!busy} data-testid="approval2-export-jpeg"><Download className="h-4 w-4 mr-2" />{busy === "export" ? "Mengekspor..." : "Export JPEG"}</Button>}
    </PageHeader>

    <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      {[["No Batch", <span className="font-mono">{b.no}</span>, "no"], ["Judul", b.title, "title"], ["Tanggal Pengajuan", fmtA2Date(b.submission_date), "date"], ["Dibuat Oleh", b.created_by_name, "creator"],
        ["Status", <StatusBadge status={b.status} />, "status"], ["Jumlah PO", `${b.po_count} (${b.approved_count} approved)`, "count"], ["Total Nilai", fmtRp(b.total_value), "total"]].map(([k, v, tid]) =>
        <div key={k} className="rounded-xl border bg-card p-3"><div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{k}</div><div className="mt-1 text-sm font-semibold break-words" data-testid={`approval2-batch-${tid}`}>{v}</div></div>)}
    </div>

    <Card className="mb-5"><CardContent className="p-0">
      <div className="flex items-center justify-between border-b p-4"><div><div className="font-semibold">Dokumen Pengajuan (area export JPEG)</div><div className="text-xs text-muted-foreground">Export JPEG tidak meng-approve PO. {b.export_count ? `Sudah diexport ${b.export_count}x${b.last_exported_at ? `, terakhir ${fmtDateTimeSafe(b.last_exported_at)}` : ""}.` : "Belum diexport."}</div></div></div>
      <div className="overflow-auto bg-muted/40 p-4"><div className="inline-block shadow-sm"><Approval2Document ref={docRef} batch={b} items={items} /></div></div>
    </CardContent></Card>

    <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
      <Card><CardContent className="p-0">
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div><div className="font-semibold">PO dalam Pengajuan</div><div className="text-xs text-muted-foreground">Centang hanya PO yang disetujui pimpinan. PO lain tetap Approval Level 2 Pending.</div></div>
          {acc.approve ? <Button onClick={approve} disabled={!canApprove || !!busy} data-testid="approval2-approve-selected"><CheckCheck className="h-4 w-4 mr-2" />{busy === "approve" ? "Memproses..." : `Approve Terpilih${sel.length ? ` (${sel.length})` : ""}`}</Button> : <span className="text-xs text-muted-foreground" data-testid="approval2-approve-no-access">Anda tidak memiliki izin Approve Approval 2.</span>}
        </div>
        {isDraft && <div className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200" data-testid="approval2-draft-hint">Export JPEG terlebih dahulu agar pengajuan berstatus Diajukan.</div>}
        {!isDraft && evidenceCount === 0 && <div className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200" data-testid="approval2-evidence-hint">Upload Bukti Persetujuan Pimpinan sebelum Approve Terpilih.</div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1000px] text-sm zebra">
            <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
              <th className="w-10 p-3"><Checkbox checked={allChecked} disabled={!approvable.length} onCheckedChange={() => setSel(allChecked ? [] : approvable.map((i) => i.id))} aria-label="Pilih semua" data-testid="approval2-items-select-all" /></th>
              <th className="p-3">No PO</th><th className="p-3">Supplier</th><th className="p-3">Keterangan Transaksi</th><th className="p-3">Project</th><th className="p-3 text-right">DPP</th><th className="p-3 text-right">PPN</th><th className="p-3 text-right">Total</th><th className="p-3">PIC</th><th className="p-3">Status</th>
            </tr></thead>
            <tbody>{items.map((i) => <tr key={i.id} className="border-t align-top" data-testid={`approval2-item-${i.po_no}`}>
              <td className="p-3"><Checkbox checked={sel.includes(i.id)} disabled={!i.can_approve} onCheckedChange={() => setSel((s) => toggleId(s, i.id))} aria-label={`Pilih ${i.po_no}`} data-testid={`approval2-item-check-${i.po_no}`} /></td>
              <td className="p-3"><button onClick={() => nav(`/po/${i.po_id}`)} className="font-mono text-xs font-semibold text-primary hover:underline">{i.po_no}</button></td>
              <td className="p-3 whitespace-nowrap">{i.supplier_name}</td><td className="p-3 max-w-[320px] break-words">{i.transaction_description}</td><td className="p-3">{i.project_text}</td>
              <td className="p-3 text-right tabular-nums whitespace-nowrap">{fmtRp(i.dpp)}</td><td className="p-3 text-right tabular-nums whitespace-nowrap">{fmtPpn(i.ppn)}</td><td className="p-3 text-right tabular-nums whitespace-nowrap font-semibold">{fmtRp(i.grand_total)}</td>
              <td className="p-3">{i.pic_name}</td>
              <td className="p-3"><StatusBadge status={i.display_status} />{i.approved_at && <div className="mt-1 text-xs text-muted-foreground">{i.approved_by} · {fmtDateTimeSafe(i.approved_at)}</div>}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </CardContent></Card>

      <div className="space-y-5">
        <Card data-testid="approval2-evidence-card"><CardContent className="space-y-3 pt-6">
          <div><div className="font-semibold">Bukti Persetujuan Pimpinan *</div><div className="text-xs text-muted-foreground">Screenshot keputusan WA (JPG, JPEG, PNG, WEBP, PDF). Cukup sekali per batch; otomatis tampil di lampiran setiap PO yang di-approve.</div></div>
          <AttachmentPanel entity="po_approval2_batch" entityId={b.id} canUpload={acc.canUploadEvidence} canDelete={acc.canUploadEvidence && b.status !== "Selesai"} onFilesChange={onFilesChange} />
        </CardContent></Card>
        <Card><CardContent className="pt-6"><div className="mb-3 font-semibold">Audit Trail</div><AuditPanel key={`${b.status}-${b.approved_count}-${b.export_count}-${evidenceCount}`} entity="po_approval2_batch" entityId={b.id} labels={A2_AUDIT_LABELS} /></CardContent></Card>
      </div>
    </div>

    <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)}>
      <DialogContent className="max-w-[95vw]" data-testid="approval2-preview-dialog">
        <DialogHeader><DialogTitle>Preview JPEG</DialogTitle><DialogDescription>{approval2FileName(b.title, b.submission_date)}</DialogDescription></DialogHeader>
        <div className="max-h-[75vh] overflow-auto rounded border bg-muted/30">{preview && <img src={preview} alt="Preview pengajuan Approval 2" className="w-full" data-testid="approval2-preview-image" />}</div>
      </DialogContent>
    </Dialog>
  </div>;
}
