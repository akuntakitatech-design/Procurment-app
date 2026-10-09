import { useEffect, useMemo, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { TransferItemLines } from "@/components/TransferItemLines";
import { TransferDraftAttachments } from "@/components/TransferDraftAttachments";
import { TransferDetailLines } from "@/components/TransferDetailLines";
import { AttachmentPanel } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox } from "@/components/MasterRefCombobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError } from "@/lib/txnValidation";
import { LookupStatusAlert } from "@/components/LookupStatusAlert";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { ArrowLeftRight, Plus, ArrowLeft, Paperclip, X, CopyCheck, Printer } from "lucide-react";
import { loadStock } from "@/components/StockInfo";
import { printDoc } from "@/lib/print";
import { applyDefaultsToAll, availableFor, editStockCredit, firstIssueMessage, linesFromDoc, linesPayload, manualOverrideCount, nameOnlyOptions, newTransferLine, transferLineIssues } from "@/lib/transferLines";
import { fmtDate, todayISO } from "@/lib/format";
import { toast } from "sonner";
import { useOpenParam } from "@/hooks/useOpenParam";
import { TxnList } from "@/components/TxnList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";

const EMPTY = () => ({ date: todayISO(), division_id: "", from_warehouse_id: "", to_warehouse_id: "", project_id: "", notes: "", document_message: null });
const nameOnly = (d) => d.name;

export default function Transfer() {
  const [mode, setMode] = useState("list"); const masters = useMasters(mode === "list" ? [] : STOCK_REFS);
  const { can } = useAuth();
  const list = useServerList("/transfers");

  const [h, setH] = useState(EMPTY());
  const [lines, setLines] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [origLines, setOrigLines] = useState([]); // snapshot dokumen saat edit (kredit reversal stok)
  const [draftId, setDraftId] = useState(null); // draft lampiran server-side (upload sebelum posting)
  const [draftErr, setDraftErr] = useState(null);
  const [attState, setAttState] = useState({ uploading: false, failed: 0, ready: 0 });
  const [saving, setSaving] = useState(false);
  const [confirmApply, setConfirmApply] = useState(false);
  const [stockMap, setStockMap] = useState({}); // itemId -> {warehouseId: stock}
  const [divErr, setDivErr] = useState(null);
  const draftRef = useRef(null);
  draftRef.current = draftId;

  const load = () => list.reload();
  const openDetail = (id) => api.get(`/transfers/${id}`).then((r) => setSelected(r.data));
  useOpenParam(openDetail);
  const newDraft = () => { setDraftId(null); setDraftErr(null); api.post("/attachment-drafts", { module: "transfer" }).then((r) => setDraftId(r.data.id)).catch((e) => setDraftErr(apiError(e.response?.data?.detail) || "Lampiran belum dapat disiapkan")); };
  const discardDraft = () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); setDraftId(null); };
  // Tinggalkan halaman saat form baru terbuka -> draft lampiran dibatalkan (cleanup 24 jam tetap jadi pengaman).
  useEffect(() => () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); }, []);

  const startNew = () => {
    setTried(false); setEditingId(null); setOrigLines([]); setH(EMPTY()); setLines([newTransferLine(EMPTY())]); setSelected(null); setMode("form"); newDraft();
  };
  const startEdit = (doc = selected) => {
    if (!doc) return;
    setSelected(doc); setEditingId(doc.id);
    setH({ date: doc.date, division_id: doc.division_id || "", from_warehouse_id: doc.from_warehouse_id || "", to_warehouse_id: doc.to_warehouse_id || "", project_id: doc.project_id || "", notes: doc.notes || "", document_message: doc.document_message || "" });
    const ls = linesFromDoc(doc);
    setLines(ls); setOrigLines(ls); setMode("form");
  };
  const back = () => { if (!editingId) discardDraft(); setMode("list"); setEditingId(null); setLines([]); };

  // Stok tersedia per (barang, gudang asal BARIS) — refresh saat barang / gudang asal baris berubah.
  const itemKey = [...new Set(lines.map((l) => l.item_id).filter(Boolean))].sort().join(",");
  const fromKey = lines.map((l) => `${l.item_id || ""}@${l.from_warehouse_id || ""}`).join(",");
  useEffect(() => {
    let live = true;
    itemKey.split(",").filter(Boolean).forEach((id) => loadStock(id, "fresh").then((r) => {
      if (!live || !r || r.error) return;
      setStockMap((m) => ({ ...m, [id]: Object.fromEntries((r.warehouses || []).map((w) => [w.warehouse_id, Number(w.stock) || 0])) }));
    }));
    return () => { live = false; };
  }, [itemKey, fromKey]);
  const credit = useMemo(() => (editingId ? editStockCredit(origLines) : {}), [editingId, origLines]);
  const stockOf = (itemId, whId) => availableFor(stockMap, itemId, whId, credit);
  const issues = transferLineIssues(lines, stockOf);
  const hasIssue = issues.some(Boolean);
  const [tried, setTried] = useState(false); // pesan "wajib dipilih" baris kosong baru tampil setelah user mencoba Posting
  const shownIssues = issues.map((x, i) => (tried || lines[i]?.item_id ? x : null));
  const defaults = useMemo(() => ({ from_warehouse_id: h.from_warehouse_id, to_warehouse_id: h.to_warehouse_id, project_id: h.project_id }), [h.from_warehouse_id, h.to_warehouse_id, h.project_id]);
  const overrides = manualOverrideCount(lines, defaults);

  const doApplyAll = () => { setLines((ls) => applyDefaultsToAll(ls, defaults)); setConfirmApply(false); toast.success("Default header diterapkan ke semua baris"); };
  const askApplyAll = () => (overrides > 0 ? setConfirmApply(true) : doApplyAll());

  const save = async () => {
    setTried(true);
    const de = divisionError(h.division_id); if (de) { setDivErr(de); toast.error(de); return; } setDivErr(null);
    if (!lines.length) { toast.error("Minimal satu baris barang"); return; }
    const ie = firstIssueMessage(issues); if (ie) { toast.error(ie); return; }
    if (attState.uploading) { toast.error("Tunggu hingga semua lampiran selesai diunggah"); return; }
    setSaving(true);
    try {
      const body = { ...h, lines: linesPayload(lines) };
      const res = editingId
        ? await api.put(`/transactions/transfer/${editingId}`, body)
        : await api.post("/transfers", { ...body, attachment_draft_id: draftId || undefined });
      const keepId = editingId || res.data.id;
      await saveDocumentMessage("transfer", keepId, h.document_message);
      toast.success(editingId ? "Transfer diperbarui; stok lama direversal lalu diposting ulang" : `Transfer ${res.data.no} diposting${attState.ready ? ` dengan ${attState.ready} lampiran` : ""}`);
      setDraftId(null); setMode("list"); setLines([]); setH(EMPTY()); setEditingId(null); load();
      if (keepId) openDetail(keepId);
    } catch (e) {
      // Posting gagal: transaksi tidak terbentuk, lampiran tetap draft -> user bisa perbaiki lalu Posting ulang.
      toast.error(apiError(e.response?.data?.detail));
    } finally { setSaving(false); }
  };

  const whOpts = nameOnlyOptions(masters.data.warehouses);
  const projOpts = nameOnlyOptions(masters.data.projects);

  if (mode === "form") return (
    <div>
      <TransactionPageHeader type="transfer" mode={editingId ? "edit" : "new"} number={selected?.no} showNumberField subtitle={editingId ? "Perubahan akan melakukan reversal stok lama lalu posting ulang" : undefined}>
        <Button variant="outline" onClick={back} data-testid="trf-back-btn"><ArrowLeft className="h-4 w-4 mr-2" />{editingId ? "Kembali" : "Batal"}</Button>
        <Button onClick={save} disabled={lines.length === 0 || saving || attState.uploading} data-testid="trf-save-btn">{saving ? "Memproses..." : editingId ? "Simpan Perubahan" : "Posting Transfer"}</Button>
      </TransactionPageHeader>
      <div className="space-y-4"><LookupStatusAlert masters={masters} names={["divisions", "warehouses", "projects", "units", "items", "uoms"]} testid="trf-lookup-status" /><Card><CardContent className="pt-6 space-y-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4" data-testid="trf-header-meta">
          <Field label="No. Transfer"><Input value={editingId ? selected?.no || "" : "Otomatis saat diposting"} disabled className="font-mono" data-testid="trf-no" /></Field>
          <Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH((s) => ({ ...s, date: v }))} testid="trf-date" /></Field>
          <DivisionField testid="trf-division-field" options={masters.opts("divisions", nameOnly)} value={h.division_id} onChange={(v) => { setH((s) => ({ ...s, division_id: v })); setDivErr(null); }} error={divErr} />
          <Field label="Keterangan"><Input value={h.notes} onChange={(e) => setH((s) => ({ ...s, notes: e.target.value }))} placeholder="Catatan dokumen" data-testid="trf-notes" /></Field>
        </div>
        <div className="rounded-lg border border-dashed bg-muted/30 p-4" data-testid="trf-header-defaults">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div><div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Default Baris</div><div className="text-xs text-muted-foreground">Mengisi baris baru otomatis. Baris yang diubah manual (tanda <b>Manual</b>) tidak ikut berubah. Posting stok selalu membaca gudang & project per baris.</div></div>
            <Button type="button" variant="outline" size="sm" disabled={!lines.length} onClick={askApplyAll} data-testid="trf-apply-defaults"><CopyCheck className="h-4 w-4 mr-2" />Terapkan Default ke Semua Baris</Button>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Field label="Project Default"><MasterProjectCombobox masters={masters} options={projOpts} value={h.project_id} onChange={(v) => setH((s) => ({ ...s, project_id: v }))} placeholder="Pilih project" testid="trf-project" /></Field>
            <Field label="Gudang Asal Default"><Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={h.from_warehouse_id} onChange={(v) => setH((s) => ({ ...s, from_warehouse_id: v }))} placeholder="Pilih gudang asal" testid="trf-from" /></Field>
            <Field label="Gudang Tujuan Default"><Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={h.to_warehouse_id} onChange={(v) => setH((s) => ({ ...s, to_warehouse_id: v }))} placeholder="Pilih gudang tujuan" testid="trf-to" invalid={!!h.from_warehouse_id && h.from_warehouse_id === h.to_warehouse_id} /></Field>
          </div>
          {!!h.from_warehouse_id && h.from_warehouse_id === h.to_warehouse_id && <div className="mt-2 text-xs text-destructive" data-testid="trf-header-same-warning">Gudang Asal Default dan Gudang Tujuan Default sama — baris dengan nilai ini tidak dapat diposting.</div>}
        </div>
        <TransferItemLines lines={lines} onChange={setLines} masters={masters} defaults={defaults} issues={shownIssues} stockOf={stockOf} division={h.division_id} />
        {hasIssue && shownIssues.some(Boolean) && <div className="text-xs text-destructive" data-testid="trf-post-blocked">Posting diblokir sampai semua masalah baris diperbaiki.</div>}
        <div className="rounded-xl border bg-card p-4" data-testid="trf-attachments"><div className="mb-3 flex flex-wrap items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran{!editingId && <span className="text-xs font-normal text-muted-foreground">— unggah sekarang; otomatis terikat ke Transfer saat Posting</span>}</div>
          {editingId ? <AttachmentPanel entity="transfer" entityId={editingId} /> : <TransferDraftAttachments draftId={draftId} draftError={draftErr} onRetryDraft={newDraft} onStateChange={setAttState} />}
        </div>
      </CardContent></Card><DocumentMessageEditor module="transfer" value={h.document_message} onChange={(v) => setH((s) => ({ ...s, document_message: v }))} useDefault={!editingId} /></div>
      <AlertDialog open={confirmApply} onOpenChange={setConfirmApply}>
        <AlertDialogContent data-testid="trf-apply-defaults-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Terapkan default ke semua baris?</AlertDialogTitle>
            <AlertDialogDescription>Project, Gudang Asal, dan Gudang Tujuan di semua baris akan diganti dengan default header. Ada <b>{overrides}</b> nilai yang diubah manual dan akan ditimpa.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="trf-apply-defaults-cancel">Batal</AlertDialogCancel>
            <AlertDialogAction onClick={doApplyAll} data-testid="trf-apply-defaults-confirm">Ya, terapkan</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );

  return (
    <div>
      <TransactionPageHeader type="transfer" mode={selected ? "view" : "list"} number={selected?.no}>{can("create") && <Button onClick={startNew} data-testid="transfer-create-btn"><Plus className="h-4 w-4 mr-2" />Buat Transfer</Button>}</TransactionPageHeader>
      <TxnList module="transfer" testidPrefix="transfer" server={list} onReload={() => { setSelected(null); load(); }} selectedId={selected?.id} emptyText="Belum ada transfer" minWidth={1100}
        onOpen={(r) => openDetail(r.id)} onEdit={async (r) => { const d = await api.get(`/transfers/${r.id}`); startEdit(d.data); }}
        columns={[noCol("No. Transfer"), dateCol(fmtDate), { key: "from_name", label: "Dari", render: (r) => <span data-testid={`transfer-from-${r.id}`}>{r.from_name}{r.multi_warehouse && <span className="ml-1 rounded bg-muted px-1 text-[10px] text-muted-foreground">multi</span>}</span> }, { key: "to_name", label: "Ke", render: (r) => <span className="flex items-center gap-1" data-testid={`transfer-to-${r.id}`}><ArrowLeftRight className="h-3 w-3 text-muted-foreground" />{r.to_name}</span> }, traceCol("project"), traceCol("unit"), { key: "line_count", label: "Item", num: true }, { key: "status", label: "Status", status: true }]} />
      {selected && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Detail Transaksi</div><div className="mt-1 font-mono font-semibold" data-testid="trf-detail-no">{selected.no}</div><div className="mt-2"><div className="flex flex-wrap items-center gap-2"><TransactionMutationActions module="transfer" id={selected.id} onEdit={() => startEdit()} onDeleted={() => { setSelected(null); load(); }} compact />{can("print") && <Button variant="outline" size="sm" onClick={() => printDoc("transfer", selected, { title: "Transfer Antar Gudang" })} data-testid="trf-print-btn"><Printer className="h-4 w-4 mr-2" />Cetak</Button>}</div></div></div><Button variant="ghost" size="icon" onClick={() => setSelected(null)} aria-label="Tutup detail" data-testid="trf-detail-close"><X className="h-4 w-4" /></Button></div><TransferDetailLines doc={selected} /><AttachmentPanel entity="transfer" entityId={selected.id} /><DocumentMessageEditor module="transfer" value={selected.document_message || ""} readOnly /></CardContent></Card>}
    </div>
  );
}
