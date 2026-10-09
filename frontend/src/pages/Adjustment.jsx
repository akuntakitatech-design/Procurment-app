import { useEffect, useMemo, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { AttachmentPanel } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { AdjustmentItemLines } from "@/components/AdjustmentItemLines";
import { AdjustmentDetailLines } from "@/components/AdjustmentDetailLines";
import { AdjustmentDraftAttachments } from "@/components/AdjustmentDraftAttachments";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox } from "@/components/MasterRefCombobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError, lineQtyError } from "@/lib/txnValidation";
import { LookupStatusAlert } from "@/components/LookupStatusAlert";
import { loadStock } from "@/components/StockInfo";
import { printDoc } from "@/lib/print";
import { adjLineIssues, adjLinesPayload, applyDefaultsToAll, availableFor, editStockCredit, firstAdjIssueMessage, linesFromDoc, manualOverrideCount, newAdjLine } from "@/lib/adjustmentLines";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Plus, ArrowLeft, Paperclip, X, CopyCheck, Printer } from "lucide-react";
import { fmtDate, todayISO } from "@/lib/format";
import { toast } from "sonner";
import { useOpenParam } from "@/hooks/useOpenParam";
import { TxnList } from "@/components/TxnList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";

const TYPES = ["Rusak", "Hilang", "Expired", "Koreksi", "Selisih", "Ditemukan", "Lainnya"];
const EMPTY = () => ({ date: todayISO(), warehouse_id: "", division_id: "", project_id: "", adj_type: "Koreksi", reason: "", notes: "", document_message: null });
const nameOnly = (d) => d.name;

export default function Adjustment() {
  const [mode, setMode] = useState("list"); const masters = useMasters(mode === "list" ? [] : STOCK_REFS); const { can } = useAuth();
  const canPrice = can("view_purchase_price");
  const list = useServerList("/adjustments");
  const [h, setH] = useState(EMPTY());
  const [lines, setLines] = useState([]); const [selected, setSelected] = useState(null); const [editingId, setEditingId] = useState(null);
  const [origLines, setOrigLines] = useState([]);
  const [draftId, setDraftId] = useState(null); const [draftErr, setDraftErr] = useState(null);
  const [attState, setAttState] = useState({ uploading: false, failed: 0, ready: 0 });
  const [saving, setSaving] = useState(false); const [tried, setTried] = useState(false);
  const [confirmApply, setConfirmApply] = useState(false);
  const [stockMap, setStockMap] = useState({});
  const [divErr, setDivErr] = useState(null); const [whErr, setWhErr] = useState(null);
  const draftRef = useRef(null); draftRef.current = draftId;
  const itemsMap = masters.map("items");
  const load = () => list.reload();

  const newDraft = () => { setDraftId(null); setDraftErr(null); api.post("/attachment-drafts", { module: "adjustment" }).then((r) => setDraftId(r.data.id)).catch((e) => setDraftErr(apiError(e.response?.data?.detail) || "Lampiran belum dapat disiapkan")); };
  const discardDraft = () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); setDraftId(null); };
  useEffect(() => () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); }, []);

  const openDetail = (id) => api.get(`/adjustments/${id}`).then((r) => setSelected(r.data)).catch((e) => toast.error(apiError(e.response?.data?.detail)));
  useOpenParam(openDetail);
  const startNew = () => { setTried(false); setEditingId(null); setOrigLines([]); setH(EMPTY()); setLines([newAdjLine(EMPTY())]); setSelected(null); setMode("form"); newDraft(); };
  const startEdit = (doc = selected) => {
    if (!doc) return;
    setSelected(doc); setEditingId(doc.id); setTried(false);
    setH({ date: doc.date, warehouse_id: doc.warehouse_id || "", division_id: doc.division_id || "", project_id: doc.project_id || "", adj_type: doc.adj_type || "Koreksi", reason: doc.reason || "", notes: doc.notes || "", document_message: doc.document_message || "" });
    const ls = linesFromDoc(doc, (id) => itemsMap[id]?.base_uom_id); setLines(ls); setOrigLines(ls); setMode("form");
  };
  const back = () => { if (!editingId) discardDraft(); setMode("list"); setEditingId(null); setLines([]); };

  // Stok per (barang, gudang BARIS) — refresh saat barang / gudang baris berubah.
  const itemKey = [...new Set(lines.map((l) => l.item_id).filter(Boolean))].sort().join(",");
  const whKey = lines.map((l) => `${l.item_id || ""}@${l.warehouse_id || ""}`).join(",");
  useEffect(() => {
    let live = true;
    itemKey.split(",").filter(Boolean).forEach((id) => loadStock(id, "fresh").then((r) => {
      if (!live || !r || r.error) return;
      setStockMap((m) => ({ ...m, [id]: Object.fromEntries((r.warehouses || []).map((w) => [w.warehouse_id, Number(w.stock) || 0])) }));
    }));
    return () => { live = false; };
  }, [itemKey, whKey]);
  const credit = useMemo(() => (editingId ? editStockCredit(origLines) : {}), [editingId, origLines]);
  const stockOf = (itemId, whId) => availableFor(stockMap, itemId, whId, credit);
  const issues = adjLineIssues(lines, stockOf);
  const shownIssues = issues.map((x, i) => (tried || lines[i]?.item_id ? x : null));
  const blocked = !!firstAdjIssueMessage(shownIssues);
  const defaults = useMemo(() => ({ warehouse_id: h.warehouse_id, project_id: h.project_id }), [h.warehouse_id, h.project_id]);
  const overrides = manualOverrideCount(lines, defaults);
  const doApplyAll = () => { setLines((ls) => applyDefaultsToAll(ls, defaults)); setConfirmApply(false); toast.success("Default header diterapkan ke semua baris"); };
  const askApplyAll = () => (overrides > 0 ? setConfirmApply(true) : doApplyAll());

  const save = async () => {
    setTried(true);
    const de = divisionError(h.division_id); if (de) { setDivErr(de); toast.error(de); return; } setDivErr(null);
    if (!h.warehouse_id) { setWhErr("Gudang Default wajib dipilih"); toast.error("Gudang Default wajib dipilih"); return; } setWhErr(null);
    if (!lines.length) { toast.error("Minimal satu baris barang"); return; }
    const qe = lineQtyError(lines,"adjustment"); if (qe) { toast.error(qe); return; }
    const ie = firstAdjIssueMessage(issues); if (ie) { toast.error(ie); return; }
    if (attState.uploading) { toast.error("Tunggu hingga semua lampiran selesai diunggah"); return; }
    setSaving(true);
    try {
      const body = { ...h, lines: adjLinesPayload(lines) };
      const res = editingId ? await api.put(`/transactions/adjustment/${editingId}`, body) : await api.post("/adjustments", { ...body, attachment_draft_id: draftId || undefined });
      const keep = editingId || res.data.id;
      await saveDocumentMessage("adjustment", keep, h.document_message);
      toast.success(editingId ? "Adjustment diperbarui; efek stok lama direversal lalu diposting ulang" : `Adjustment ${res.data.no} diposting${attState.ready ? ` dengan ${attState.ready} lampiran` : ""}`);
      setDraftId(null); setMode("list"); setLines([]); setH(EMPTY()); setEditingId(null); load(); if (keep) openDetail(keep);
    } catch (e) {
      // Posting gagal: dokumen tidak terbentuk, lampiran tetap draft -> perbaiki lalu Posting ulang.
      toast.error(apiError(e.response?.data?.detail));
    } finally { setSaving(false); }
  };

  const whOpts = masters.opts("warehouses", nameOnly);
  const projOpts = masters.opts("projects", nameOnly);

  if (mode === "form") return <div>
    <TransactionPageHeader type="adjustment" mode={editingId ? "edit" : "new"} number={selected?.no} showNumberField subtitle={editingId ? "Perubahan akan direversal dan diposting ulang" : undefined}>
      <Button variant="outline" onClick={back} data-testid="adj-back-btn"><ArrowLeft className="h-4 w-4 mr-2" />{editingId ? "Kembali" : "Batal"}</Button>
      <Button onClick={save} disabled={lines.length === 0 || saving || attState.uploading} data-testid="adj-save-btn">{saving ? "Memproses..." : attState.uploading ? "Menunggu lampiran..." : editingId ? "Simpan Perubahan" : "Posting"}</Button>
    </TransactionPageHeader>
    <div className="space-y-4"><LookupStatusAlert masters={masters} names={["divisions", "warehouses", "projects", "units", "items", "uoms"]} testid="adj-lookup-status" /><Card><CardContent className="pt-6 space-y-5">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4" data-testid="adj-header-meta">
        <Field label="No. Adjustment"><Input value={editingId ? selected?.no || "" : "Otomatis saat diposting"} disabled className="font-mono" data-testid="adj-no" /></Field>
        <Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH((s) => ({ ...s, date: v }))} testid="adj-date" /></Field>
        <DivisionField testid="adj-division-field" options={masters.opts("divisions", nameOnly)} value={h.division_id} onChange={(v) => { setH((s) => ({ ...s, division_id: v })); setDivErr(null); }} error={divErr} />
        <Field label="Jenis"><Select value={h.adj_type} onValueChange={(v) => setH((s) => ({ ...s, adj_type: v }))}><SelectTrigger data-testid="adj-type"><SelectValue /></SelectTrigger><SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select></Field>
        <Field label="Alasan"><Input value={h.reason} onChange={(e) => setH((s) => ({ ...s, reason: e.target.value }))} data-testid="adj-reason" /></Field>
        <div className="md:col-span-1 lg:col-span-3"><Field label="Catatan"><Input value={h.notes} onChange={(e) => setH((s) => ({ ...s, notes: e.target.value }))} placeholder="Catatan dokumen" data-testid="adj-notes" /></Field></div>
      </div>
      <div className="rounded-lg border border-dashed bg-muted/30 p-4" data-testid="adj-header-defaults">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div><div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Default Baris</div><div className="text-xs text-muted-foreground">Mengisi baris baru otomatis. Baris yang diubah manual (tanda <b>Manual</b>) tidak ikut berubah. Stok, ledger &amp; valuasi selalu membaca gudang per baris.</div></div>
          <Button type="button" variant="outline" size="sm" disabled={!lines.length} onClick={askApplyAll} data-testid="adj-apply-defaults"><CopyCheck className="h-4 w-4 mr-2" />Terapkan Default ke Semua Baris</Button>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Gudang Default"><Combobox testid="adj-warehouse" options={whOpts} lookup={masters.status?.("warehouses")} value={h.warehouse_id} onChange={(v) => { setH((s) => ({ ...s, warehouse_id: v })); setWhErr(null); }} placeholder="Pilih gudang default" invalid={!!whErr} />{whErr && <div className="mt-1 text-xs text-destructive" data-testid="adj-warehouse-error">{whErr}</div>}</Field>
          <Field label="Project Default"><MasterProjectCombobox masters={masters} options={projOpts} value={h.project_id} onChange={(v) => setH((s) => ({ ...s, project_id: v }))} placeholder="Opsional" testid="adj-project" /></Field>
        </div>
      </div>
      <AdjustmentItemLines lines={lines} onChange={setLines} masters={masters} defaults={defaults} issues={shownIssues} stockOf={stockOf} canPrice={canPrice} division={h.division_id} />
      {blocked && <div className="text-xs text-destructive" data-testid="adj-post-blocked">Posting diblokir sampai semua masalah baris diperbaiki.</div>}
      <div className="rounded-xl border bg-card p-4" data-testid="adj-attachments"><div className="mb-3 flex flex-wrap items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran{!editingId && <span className="text-xs font-normal text-muted-foreground">— unggah sekarang (bisa beberapa file); otomatis terikat ke dokumen saat Posting</span>}</div>
        {editingId ? <AttachmentPanel entity="adjustment" entityId={editingId} /> : <AdjustmentDraftAttachments draftId={draftId} draftError={draftErr} onRetryDraft={newDraft} onStateChange={setAttState} />}
      </div>
    </CardContent></Card><DocumentMessageEditor module="adjustment" value={h.document_message} onChange={(v) => setH((s) => ({ ...s, document_message: v }))} useDefault={!editingId} /></div>
    <AlertDialog open={confirmApply} onOpenChange={setConfirmApply}>
      <AlertDialogContent data-testid="adj-apply-defaults-dialog">
        <AlertDialogHeader><AlertDialogTitle>Terapkan default ke semua baris?</AlertDialogTitle>
          <AlertDialogDescription>Gudang dan Project di semua baris akan diganti dengan default header. Ada <b>{overrides}</b> nilai yang diubah manual dan akan ditimpa.</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel data-testid="adj-apply-defaults-cancel">Batal</AlertDialogCancel><AlertDialogAction onClick={doApplyAll} data-testid="adj-apply-defaults-confirm">Ya, terapkan</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>;

  return <div><TransactionPageHeader type="adjustment" mode={selected ? "view" : "list"} number={selected?.no}>{can("stock_adjustment") && <Button onClick={startNew} data-testid="adj-create-btn"><Plus className="h-4 w-4 mr-2" />Buat Adjustment</Button>}</TransactionPageHeader>
    <TxnList module="adjustment" testidPrefix="adjustment" server={list} onReload={() => { setSelected(null); load(); }} selectedId={selected?.id} emptyText="Belum ada adjustment" minWidth={1100} onOpen={(r) => openDetail(r.id)} onEdit={async (r) => { const d = await api.get(`/adjustments/${r.id}`); startEdit(d.data); }}
      columns={[noCol("No. Adjustment"), dateCol(fmtDate), { key: "warehouse_name", label: "Gudang", render: (r) => <span data-testid={`adj-warehouse-${r.id}`}>{r.warehouse_name}{r.multi_warehouse && <span className="ml-1 rounded bg-muted px-1 text-[10px] text-muted-foreground">multi</span>}</span> }, { key: "adj_type", label: "Jenis" }, { key: "reason", label: "Alasan" }, traceCol("project"), traceCol("unit"), { key: "line_count", label: "Item", num: true }]} />
    {selected && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Detail Transaksi</div><h2 className="mt-1 font-head font-mono font-semibold" data-testid="adj-detail-no">{selected.no}</h2><div className="mt-2 flex flex-wrap items-center gap-2"><TransactionMutationActions module="adjustment" id={selected.id} onEdit={() => startEdit()} onDeleted={() => { setSelected(null); load(); }} compact />{can("print") && <Button variant="outline" size="sm" onClick={() => printDoc("adjustment", selected, { title: "Penyesuaian Stok", showPrice: canPrice })} data-testid="adj-print-btn"><Printer className="h-4 w-4 mr-2" />Cetak</Button>}</div></div><Button variant="ghost" size="icon" onClick={() => setSelected(null)} aria-label="Tutup detail" data-testid="adj-detail-close"><X className="h-4 w-4" /></Button></div>
      <AdjustmentDetailLines doc={selected} canPrice={canPrice} />
      <AttachmentPanel entity="adjustment" entityId={selected.id} /><DocumentMessageEditor module="adjustment" value={selected.document_message || ""} readOnly /></CardContent></Card>}</div>;
}
