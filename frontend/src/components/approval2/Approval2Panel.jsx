import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { StatusBadge } from "@/components/StatusBadge";
import { Field } from "@/components/DatePicker";
import { A2_READY, batchTotals, fmtA2Date, fmtPpn, fmtRp, isoToday, searchEligible, selectableRows, toggleId } from "@/lib/approval2";
import { FilePlus2, Search, Layers } from "lucide-react";
import { toast } from "sonner";

export function Approval2Panel({ scope = "mine", onChanged }) {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(isoToday());
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [e, b] = await Promise.all([api.get(`/approval2/po/eligible?scope=${scope}`), api.get("/approval2/po/batches")]);
      setRows(e.data || []); setBatches(b.data || []);
      setSel((s) => s.filter((id) => (e.data || []).some((r) => r.approval_task_id === id && r.submission_status === A2_READY)));
    } catch (err) {
      setError(apiError(err.response?.data?.detail));
    } finally { setLoading(false); }
  }, [scope]);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => searchEligible(rows, q), [rows, q]);
  const ready = useMemo(() => selectableRows(filtered), [filtered]);
  const chosen = rows.filter((r) => sel.includes(r.approval_task_id));
  const allChecked = ready.length > 0 && ready.every((r) => sel.includes(r.approval_task_id));
  const t = batchTotals(chosen);

  const create = async () => {
    if (!title.trim()) { toast.error("Judul Pengajuan wajib diisi"); return; }
    if (!date) { toast.error("Tanggal Pengajuan wajib diisi"); return; }
    setSaving(true);
    try {
      const r = await api.post("/approval2/po/batches", { title: title.trim(), submission_date: date, approval_task_ids: sel });
      toast.success(`Pengajuan ${r.data.no} dibuat`);
      setOpen(false); setSel([]); setTitle(""); onChanged?.();
      nav(`/approval/approval2/${r.data.id}`);
    } catch (err) {
      toast.error(apiError(err.response?.data?.detail));
    } finally { setSaving(false); }
  };

  return <div className="space-y-6" data-testid="approval2-panel">
    <Card><CardContent className="p-0">
      <div className="flex flex-col gap-3 border-b p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="font-semibold">PO Menunggu Approval Level 2</div>
          <div className="text-xs text-muted-foreground">Centang PO yang akan diajukan ke pimpinan, lalu buat pengajuan untuk di-export JPEG.</div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative w-full sm:w-80"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari No PO, supplier, project, PIC..." className="pl-9" data-testid="approval2-search" /></div>
          <Button disabled={sel.length === 0} onClick={() => { setDate(isoToday()); setOpen(true); }} data-testid="approval2-create-open"><FilePlus2 className="h-4 w-4 mr-2" />Buat Pengajuan Approval 2{sel.length ? ` (${sel.length})` : ""}</Button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1000px] text-sm zebra">
          <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="w-10 p-3"><Checkbox checked={allChecked} disabled={ready.length === 0} onCheckedChange={() => setSel(allChecked ? sel.filter((id) => !ready.some((r) => r.approval_task_id === id)) : Array.from(new Set([...sel, ...ready.map((r) => r.approval_task_id)])))} aria-label="Pilih semua" data-testid="approval2-select-all" /></th>
            <th className="p-3">No PO</th><th className="p-3">Tanggal PO</th><th className="p-3">Supplier</th><th className="p-3">Project</th><th className="p-3 text-right">Nilai</th><th className="p-3">PIC</th><th className="p-3">Status Pengajuan</th>
          </tr></thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="p-6"><div className="h-4 w-1/3 animate-pulse rounded bg-muted" /></td></tr>}
            {!loading && error && <tr><td colSpan={8} className="p-6 text-center text-destructive" data-testid="approval2-error">{error} <Button variant="link" onClick={load}>Coba lagi</Button></td></tr>}
            {!loading && !error && filtered.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-muted-foreground" data-testid="approval2-empty">Tidak ada PO yang menunggu Approval Level 2</td></tr>}
            {!loading && !error && filtered.map((r) => {
              const isReady = r.submission_status === A2_READY;
              return <tr key={r.approval_task_id} className="border-t" data-testid={`approval2-row-${r.po_no}`}>
                <td className="p-3"><Checkbox checked={sel.includes(r.approval_task_id)} disabled={!isReady} onCheckedChange={() => setSel((s) => toggleId(s, r.approval_task_id))} aria-label={`Pilih ${r.po_no}`} data-testid={`approval2-check-${r.po_no}`} /></td>
                <td className="p-3"><button onClick={() => nav(`/po/${r.po_id}`)} className="font-mono text-xs font-semibold text-primary hover:underline">{r.po_no}</button></td>
                <td className="p-3">{fmtA2Date(r.po_date)}</td><td className="p-3">{r.supplier_name}</td><td className="p-3">{r.project_text}</td>
                <td className="p-3 text-right tabular-nums">{fmtRp(r.grand_total)}</td><td className="p-3">{r.pic_name}</td>
                <td className="p-3"><div className="flex items-center gap-2"><StatusBadge status={r.submission_status} />{!isReady && r.batch_id && <button className="font-mono text-xs text-primary hover:underline" onClick={() => nav(`/approval/approval2/${r.batch_id}`)}>{r.batch_no}</button>}</div></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
    </CardContent></Card>

    <Card><CardContent className="p-0">
      <div className="flex items-center gap-2 border-b p-4"><Layers className="h-4 w-4 text-muted-foreground" /><div className="font-semibold">Riwayat Pengajuan Approval 2</div></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-sm zebra">
          <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">No Pengajuan</th><th className="p-3">Judul</th><th className="p-3">Tanggal Pengajuan</th><th className="p-3">Dibuat Oleh</th><th className="p-3 text-right">Jumlah PO</th><th className="p-3 text-right">Total Nilai</th><th className="p-3">Status</th></tr></thead>
          <tbody>
            {!loading && batches.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">Belum ada pengajuan</td></tr>}
            {batches.map((b) => <tr key={b.id} className="border-t cursor-pointer hover:bg-accent/40" onClick={() => nav(`/approval/approval2/${b.id}`)} data-testid={`approval2-batch-${b.no}`}>
              <td className="p-3 font-mono text-xs font-semibold text-primary">{b.no}</td><td className="p-3 font-medium">{b.title}</td><td className="p-3">{fmtA2Date(b.submission_date)}</td>
              <td className="p-3">{b.created_by_name}</td><td className="p-3 text-right tabular-nums">{b.po_count} <span className="text-xs text-muted-foreground">({b.approved_count} approved)</span></td>
              <td className="p-3 text-right tabular-nums">{fmtRp(b.total_value)}</td><td className="p-3"><StatusBadge status={b.status} /></td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </CardContent></Card>

    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-3xl" data-testid="approval2-create-dialog">
        <DialogHeader><DialogTitle>Buat Pengajuan Approval 2</DialogTitle><DialogDescription>Judul adalah judul pengajuan (bukan master Project). Export JPEG tidak meng-approve PO.</DialogDescription></DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Judul Pengajuan *"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="contoh: Project PHR Duri" maxLength={150} data-testid="approval2-title" /></Field>
          <Field label="Tanggal Pengajuan *"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="approval2-date" /></Field>
        </div>
        <div className="max-h-72 overflow-auto rounded-lg border">
          <table className="w-full text-sm"><thead className="bg-muted sticky top-0"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">No PO</th><th className="p-2">Supplier</th><th className="p-2">Keterangan</th><th className="p-2 text-right">DPP</th><th className="p-2 text-right">PPN</th><th className="p-2 text-right">Total</th></tr></thead>
            <tbody>{chosen.map((r) => <tr key={r.approval_task_id} className="border-t align-top"><td className="p-2 font-mono text-xs">{r.po_no}</td><td className="p-2 whitespace-nowrap">{r.supplier_name}</td><td className="p-2 text-xs">{r.transaction_description}</td><td className="p-2 text-right tabular-nums whitespace-nowrap">{fmtRp(r.dpp)}</td><td className="p-2 text-right tabular-nums whitespace-nowrap">{fmtPpn(r.ppn)}</td><td className="p-2 text-right tabular-nums whitespace-nowrap font-semibold">{fmtRp(r.grand_total)}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="text-right text-sm" data-testid="approval2-create-summary">{t.count} PO · Total Nilai <span className="font-bold">{fmtRp(t.total)}</span></div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Batal</Button>
          <Button onClick={create} disabled={saving || !title.trim() || !date} data-testid="approval2-create-submit">{saving ? "Menyimpan..." : "Buat Pengajuan"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}
