import { useEffect, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError } from "@/lib/txnValidation";
import { LookupStatusAlert } from "@/components/LookupStatusAlert";
import { AdjustmentDraftAttachments } from "@/components/AdjustmentDraftAttachments";
import { OpnameWorkspace } from "@/components/OpnameWorkspace";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, X, Paperclip, Snowflake } from "lucide-react";
import { fmtDate, todayISO } from "@/lib/format";
import { MODE_INFO } from "@/lib/opnameLines";
import { toast } from "sonner";
import { TxnList } from "@/components/TxnList";
import { noCol, dateCol } from "@/lib/txnList";

const EMPTY = () => ({ date: todayISO().slice(0, 10), warehouse_id: "", division_id: "", mode: "live", scope: "all", notes: "", counter_name: "", document_message: null });

export default function Opname() {
  const [createOpen, setCreateOpen] = useState(false); const [detailId, setDetailId] = useState(null);
  const masters = useMasters(createOpen || detailId ? STOCK_REFS : []); const { can } = useAuth();
  const list = useServerList("/opname");
  const [h, setH] = useState(EMPTY()); const [divErr, setDivErr] = useState(null); const [saving, setSaving] = useState(false);
  const [draftId, setDraftId] = useState(null); const [draftErr, setDraftErr] = useState(null); const [attState, setAttState] = useState({});
  const draftRef = useRef(null); draftRef.current = draftId;
  const newDraft = () => { setDraftId(null); setDraftErr(null); api.post("/attachment-drafts", { module: "opname" }).then((r) => setDraftId(r.data.id)).catch((e) => setDraftErr(apiError(e.response?.data?.detail) || "Lampiran belum dapat disiapkan")); };
  const discardDraft = () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); setDraftId(null); };
  useEffect(() => () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); }, []);

  const openCreate = () => { const next = !createOpen; if (!next) discardDraft(); setCreateOpen(next); setDetailId(null); if (next) { setH(EMPTY()); newDraft(); } };
  const create = async () => {
    const de = divisionError(h.division_id); if (de) { setDivErr(de); toast.error(de); return; } setDivErr(null);
    if (attState.uploading) { toast.error("Tunggu lampiran selesai diunggah"); return; }
    try {
      setSaving(true);
      const res = await api.post("/opname", { ...h, attachment_draft_id: draftId || undefined });
      await saveDocumentMessage("opname", res.data.id, h.document_message);
      toast.success(`Stock Opname ${res.data.no} dibuat — snapshot ${res.data.summary?.total ?? 0} barang diambil`);
      setDraftId(null); setCreateOpen(false); setH(EMPTY()); list.reload(); setDetailId(res.data.id);
    } catch (e) { toast.error(apiError(e.response?.data?.detail), { duration: 8000 }); } finally { setSaving(false); }
  };

  return <div>
    <TransactionPageHeader type="opname" mode={createOpen ? "new" : detailId ? "view" : "list"}>{can("create") && <Button onClick={openCreate} data-testid="opn-create-btn"><Plus className="mr-2 h-4 w-4" />{createOpen ? "Tutup Form" : "Buat Opname"}</Button>}</TransactionPageHeader>
    {createOpen && <div className="mb-4 space-y-4"><LookupStatusAlert masters={masters} names={["divisions", "warehouses", "items", "uoms"]} testid="opn-lookup-status" />
      <Card className="border-primary/20"><CardContent className="space-y-5 pt-5">
        <div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Form Transaksi</div><h2 className="font-head text-lg font-semibold">Buat Stock Opname</h2><p className="text-xs text-muted-foreground">Satu dokumen untuk satu gudang. Gudang terkunci setelah snapshot diambil; satu gudang hanya boleh punya satu Opname aktif.</p></div><Button variant="ghost" size="icon" onClick={openCreate} aria-label="Tutup form" data-testid="opn-create-close"><X className="h-4 w-4" /></Button></div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="No. Opname"><Input value="Otomatis saat disimpan" disabled className="font-mono" /></Field>
          <Field label="Tanggal Opname"><DatePicker value={h.date} onChange={(v) => setH({ ...h, date: v })} /></Field>
          <Field label="Gudang (wajib)"><Combobox testid="opn-warehouse" options={masters.opts("warehouses")} value={h.warehouse_id} onChange={(v) => setH({ ...h, warehouse_id: v })} /></Field>
          <DivisionField testid="opn-division-field" options={masters.opts("divisions")} value={h.division_id} onChange={(v) => { setH({ ...h, division_id: v }); setDivErr(null); }} error={divErr} />
          <Field label="Mode Penghitungan"><Select value={h.mode} onValueChange={(v) => setH({ ...h, mode: v })}><SelectTrigger data-testid="opn-mode-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="live">Live</SelectItem><SelectItem value="freeze">Freeze</SelectItem></SelectContent></Select></Field>
          <Field label="Scope Barang"><Select value={h.scope} onValueChange={(v) => setH({ ...h, scope: v })}><SelectTrigger data-testid="opn-scope-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Semua Barang di Gudang</SelectItem><SelectItem value="division">Per Divisi</SelectItem></SelectContent></Select></Field>
          <Field label="Petugas Penghitung"><Input value={h.counter_name} onChange={(e) => setH({ ...h, counter_name: e.target.value })} placeholder="Nama petugas" data-testid="opn-counter" /></Field>
          <Field label="Catatan"><Input value={h.notes || ""} onChange={(e) => setH({ ...h, notes: e.target.value })} data-testid="opn-notes" /></Field>
        </div>
        <div className={`flex items-start gap-2 rounded-md border p-3 text-xs ${h.mode === "freeze" ? "border-sky-300 bg-sky-50 text-sky-900" : "bg-muted/40 text-muted-foreground"}`} data-testid="opn-mode-info">{h.mode === "freeze" && <Snowflake className="mt-0.5 h-3.5 w-3.5" />}{MODE_INFO[h.mode]}</div>
        <div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran (opsional, multi-file)</div><AdjustmentDraftAttachments draftId={draftId} draftError={draftErr} onRetryDraft={newDraft} onStateChange={setAttState} entity="opname_draft" category="Lampiran Stock Opname" bindLabel="saat dokumen disimpan" testid="opn-draft-attachments" /></div>
        <div className="flex justify-end gap-2"><Button variant="outline" onClick={openCreate} data-testid="opn-create-cancel">Batal</Button><Button onClick={create} disabled={!h.warehouse_id || saving} data-testid="opn-create-submit">{saving ? "Mengambil snapshot..." : "Ambil Snapshot & Mulai"}</Button></div>
      </CardContent></Card>
      <DocumentMessageEditor module="opname" value={h.document_message} onChange={(v) => setH({ ...h, document_message: v })} useDefault /></div>}

    <TxnList module="opname" testidPrefix="opname" server={list} onReload={() => { setDetailId(null); list.reload(); }} selectedId={detailId} emptyText="Belum ada stock opname" minWidth={1000} onOpen={(r) => { setCreateOpen(false); setDetailId(r.id); }} onEdit={(r) => { setCreateOpen(false); setDetailId(r.id); }}
      columns={[noCol("No. Opname"), dateCol(fmtDate), { key: "warehouse_name", label: "Gudang" }, { key: "mode", label: "Mode", render: (r) => <span className="capitalize">{r.mode}</span> }, { key: "line_count", label: "Item", num: true }, { key: "status", label: "Status", status: true }]} />

    {detailId && <OpnameWorkspace key={detailId} id={detailId} masters={masters} onClose={() => { setDetailId(null); list.reload(); }} onChanged={() => list.reload()} />}
  </div>;
}
