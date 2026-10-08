import { useEffect, useMemo, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { LoanItemLines } from "@/components/LoanItemLines";
import { LoanDraftAttachments } from "@/components/LoanDraftAttachments";
import { LoanDetailLines } from "@/components/LoanDetailLines";
import { AttachmentPanel } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { LoanReturnActions } from "@/components/LoanReturnActions";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox } from "@/components/MasterRefCombobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError } from "@/lib/txnValidation";
import { StatusBadge } from "@/components/StatusBadge";
import { LoanReturnPicker } from "@/components/LoanReturnPicker";
import { LookupStatusAlert } from "@/components/LookupStatusAlert";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Plus, ArrowLeft, ArrowLeftRight, Undo2, X, Save, Paperclip, CopyCheck, Printer } from "lucide-react";
import { loadStock } from "@/components/StockInfo";
import { printDoc } from "@/lib/print";
import { applyDefaultsToAll, availableFor, editStockCredit, firstLoanIssueMessage, linesFromDoc, linesPayload, loanLineIssues, manualOverrideCount, nameOnlyOptions, newLoanLine } from "@/lib/loanLines";
import { num, fmtDate, todayISO } from "@/lib/format";
import { toast } from "sonner";
import { TxnList } from "@/components/TxnList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";

const EMPTY = () => ({ date: todayISO(), division_id: "", from_warehouse_id: "", to_warehouse_id: "", due_date: null, project_id: "", requester: "", notes: "", document_message: null });
const nameOnly = (d) => d.name;

export default function Loan() {
  const [mode, setMode] = useState("list"); const masters = useMasters(mode === "list" ? [] : STOCK_REFS); const { can } = useAuth();
  const list = useServerList("/loans");
  const [h, setH] = useState(EMPTY());
  const [lines, setLines] = useState([]); const [detail, setDetail] = useState(null); const [ret, setRet] = useState(false); const [editingId, setEditingId] = useState(null);
  const [returns, setReturns] = useState([]); const [returnEdit, setReturnEdit] = useState(null); const [returnLines, setReturnLines] = useState([]);
  const [origLines, setOrigLines] = useState([]); // snapshot dokumen saat edit (kredit reversal stok)
  const [draftId, setDraftId] = useState(null); // draft lampiran server-side (upload sebelum posting)
  const [draftErr, setDraftErr] = useState(null);
  const [attState, setAttState] = useState({ uploading: false, failed: 0, ready: 0 });
  const [saving, setSaving] = useState(false);
  const [confirmApply, setConfirmApply] = useState(false);
  const [stockMap, setStockMap] = useState({}); // itemId -> {warehouseId: stock}
  const [divErr, setDivErr] = useState(null);
  const [tried, setTried] = useState(false);
  const draftRef = useRef(null);
  draftRef.current = draftId;
  const load = () => list.reload();

  const newDraft = () => { setDraftId(null); setDraftErr(null); api.post("/attachment-drafts", { module: "loan" }).then((r) => setDraftId(r.data.id)).catch((e) => setDraftErr(apiError(e.response?.data?.detail) || "Lampiran belum dapat disiapkan")); };
  const discardDraft = () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); setDraftId(null); };
  useEffect(() => () => { const id = draftRef.current; if (id) api.delete(`/attachment-drafts/${id}`).catch(() => {}); }, []);

  const startNew = () => { setTried(false); setEditingId(null); setOrigLines([]); setH(EMPTY()); setLines([newLoanLine(EMPTY())]); setDetail(null); setReturns([]); setMode("form"); newDraft(); };
  const startEdit = (doc = detail) => {
    if (!doc) return;
    setDetail(doc); setEditingId(doc.id); setTried(false);
    setH({ date: doc.date, division_id: doc.division_id || "", from_warehouse_id: doc.from_warehouse_id || "", to_warehouse_id: doc.to_warehouse_id || "", due_date: doc.due_date || null, project_id: doc.project_id || "", requester: doc.requester || "", notes: doc.notes || "", document_message: doc.document_message || "" });
    const ls = linesFromDoc(doc); setLines(ls); setOrigLines(ls); setMode("form");
  };
  const back = () => { if (!editingId) discardDraft(); setMode("list"); setEditingId(null); setLines([]); };

  // Stok tersedia per (barang, Gudang Pemberi BARIS) — refresh saat barang / gudang pemberi baris berubah.
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
  const issues = loanLineIssues(lines, stockOf);
  const shownIssues = issues.map((x, i) => (tried || lines[i]?.item_id ? x : null));
  const defaults = useMemo(() => ({ from_warehouse_id: h.from_warehouse_id, to_warehouse_id: h.to_warehouse_id, project_id: h.project_id }), [h.from_warehouse_id, h.to_warehouse_id, h.project_id]);
  const overrides = manualOverrideCount(lines, defaults);
  const doApplyAll = () => { setLines((ls) => applyDefaultsToAll(ls, defaults)); setConfirmApply(false); toast.success("Default header diterapkan ke semua baris"); };
  const askApplyAll = () => (overrides > 0 ? setConfirmApply(true) : doApplyAll());

  const openDetail = async (id) => { try { const [a, b] = await Promise.all([api.get(`/loans/${id}`), api.get(`/loans/${id}/returns`)]); setDetail(a.data); setReturns(b.data || []); setRet(false); setReturnEdit(null); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };
  const save = async () => {
    setTried(true);
    const de = divisionError(h.division_id); if (de) { setDivErr(de); toast.error(de); return; } setDivErr(null);
    if (!lines.length) { toast.error("Minimal satu baris barang"); return; }
    const ie = firstLoanIssueMessage(issues); if (ie) { toast.error(ie); return; }
    if (attState.uploading) { toast.error("Tunggu hingga semua lampiran selesai diunggah"); return; }
    setSaving(true);
    try {
      const body = { ...h, lines: linesPayload(lines) };
      const res = editingId ? await api.put(`/transactions/loan/${editingId}`, body) : await api.post("/loans", { ...body, attachment_draft_id: draftId || undefined });
      const keep = editingId || res.data.id;
      await saveDocumentMessage("loan", keep, h.document_message);
      toast.success(editingId ? "Pinjaman diperbarui; stok direversal lalu diposting ulang" : `Pinjaman ${res.data.no} diposting${attState.ready ? ` dengan ${attState.ready} lampiran` : ""}`);
      setDraftId(null); setMode("list"); setLines([]); setH(EMPTY()); setEditingId(null); load(); if (keep) openDetail(keep);
    } catch (e) {
      // Posting gagal: Pinjaman tidak terbentuk, lampiran tetap draft -> user bisa perbaiki lalu Posting ulang.
      toast.error(apiError(e.response?.data?.detail));
    } finally { setSaving(false); }
  };
  const beginReturnEdit = (row) => { setReturnEdit({ ...row, date: row.date || todayISO(), notes: row.notes || "" }); setReturnLines((row.lines || []).map((l) => ({ ...l, qty: Number(l.qty) || 0 }))); };
  const saveReturnEdit = async () => { try { await api.put(`/loan-returns/${returnEdit.id}`, { date: returnEdit.date, notes: returnEdit.notes, lines: returnLines.map((l) => ({ loan_line_id: l.loan_line_id, qty: Number(l.qty) || 0 })) }); toast.success("Return diperbarui; stok direversal lalu diposting ulang"); setReturnEdit(null); openDetail(detail.id); load(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };
  const retDir = (l) => (l.return_from_name || l.return_to_name ? ` (${l.return_from_name || "-"} → ${l.return_to_name || "-"})` : "");

  const whOpts = nameOnlyOptions(masters.data.warehouses);
  const projOpts = nameOnlyOptions(masters.data.projects);

  if (mode === "form") return (
    <div>
      <TransactionPageHeader type="loan" mode={editingId ? "edit" : "new"} number={detail?.no} showNumberField subtitle={editingId ? "Perubahan akan melakukan reversal stok lama lalu posting ulang" : undefined}>
        <Button variant="outline" onClick={back} data-testid="loan-back-btn"><ArrowLeft className="h-4 w-4 mr-2" />{editingId ? "Kembali" : "Batal"}</Button>
        <Button onClick={save} disabled={lines.length === 0 || saving || attState.uploading} data-testid="loan-save-btn">{saving ? "Memproses..." : editingId ? "Simpan Perubahan" : "Posting Pinjaman"}</Button>
      </TransactionPageHeader>
      <div className="space-y-4"><LookupStatusAlert masters={masters} names={["divisions", "warehouses", "projects", "units", "items", "uoms"]} testid="loan-lookup-status" /><Card><CardContent className="pt-6 space-y-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4" data-testid="loan-header-meta">
          <Field label="No. Pinjaman"><Input value={editingId ? detail?.no || "" : "Otomatis saat diposting"} disabled className="font-mono" data-testid="loan-no" /></Field>
          <Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH((s) => ({ ...s, date: v }))} testid="loan-date" /></Field>
          <DivisionField testid="loan-division-field" options={masters.opts("divisions", nameOnly)} value={h.division_id} onChange={(v) => { setH((s) => ({ ...s, division_id: v })); setDivErr(null); }} error={divErr} />
          <Field label="Target Pengembalian"><DatePicker value={h.due_date} onChange={(v) => setH((s) => ({ ...s, due_date: v }))} testid="loan-due-date" /></Field>
          <Field label="Pemohon"><Input value={h.requester} onChange={(e) => setH((s) => ({ ...s, requester: e.target.value }))} placeholder="Nama pemohon" data-testid="loan-requester" /></Field>
          <div className="md:col-span-1 lg:col-span-3"><Field label="Keterangan"><Input value={h.notes} onChange={(e) => setH((s) => ({ ...s, notes: e.target.value }))} placeholder="Catatan dokumen" data-testid="loan-notes" /></Field></div>
        </div>
        <div className="rounded-lg border border-dashed bg-muted/30 p-4" data-testid="loan-header-defaults">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div><div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Default Baris</div><div className="text-xs text-muted-foreground">Mengisi baris baru otomatis. Baris yang diubah manual (tanda <b>Manual</b>) tidak ikut berubah. Posting & Return selalu membaca gudang & project per baris.</div></div>
            <Button type="button" variant="outline" size="sm" disabled={!lines.length} onClick={askApplyAll} data-testid="loan-apply-defaults"><CopyCheck className="h-4 w-4 mr-2" />Terapkan Default ke Semua Baris</Button>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Field label="Project Default"><MasterProjectCombobox masters={masters} options={projOpts} value={h.project_id} onChange={(v) => setH((s) => ({ ...s, project_id: v }))} placeholder="Pilih project" testid="loan-project" /></Field>
            <Field label="Gudang Pemberi Default"><Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={h.from_warehouse_id} onChange={(v) => setH((s) => ({ ...s, from_warehouse_id: v }))} placeholder="Pilih gudang pemberi" testid="loan-from" /></Field>
            <Field label="Gudang Peminjam Default"><Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={h.to_warehouse_id} onChange={(v) => setH((s) => ({ ...s, to_warehouse_id: v }))} placeholder="Pilih gudang peminjam" testid="loan-to" invalid={!!h.from_warehouse_id && h.from_warehouse_id === h.to_warehouse_id} /></Field>
          </div>
          {!!h.from_warehouse_id && h.from_warehouse_id === h.to_warehouse_id && <div className="mt-2 text-xs text-destructive" data-testid="loan-header-same-warning">Gudang Pemberi Default dan Gudang Peminjam Default sama — baris dengan nilai ini tidak dapat diposting.</div>}
        </div>
        <LoanItemLines lines={lines} onChange={setLines} masters={masters} defaults={defaults} issues={shownIssues} stockOf={stockOf} division={h.division_id} />
        {shownIssues.some(Boolean) && <div className="text-xs text-destructive" data-testid="loan-post-blocked">Posting diblokir sampai semua masalah baris diperbaiki.</div>}
        <div className="rounded-xl border bg-card p-4" data-testid="loan-attachments"><div className="mb-3 flex flex-wrap items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran{!editingId && <span className="text-xs font-normal text-muted-foreground">— unggah sekarang; otomatis terikat ke Pinjaman saat Posting</span>}</div>
          {editingId ? <AttachmentPanel entity="loan" entityId={editingId} /> : <LoanDraftAttachments draftId={draftId} draftError={draftErr} onRetryDraft={newDraft} onStateChange={setAttState} />}
        </div>
      </CardContent></Card><DocumentMessageEditor module="loan" value={h.document_message} onChange={(v) => setH((s) => ({ ...s, document_message: v }))} useDefault={!editingId} /></div>
      <AlertDialog open={confirmApply} onOpenChange={setConfirmApply}>
        <AlertDialogContent data-testid="loan-apply-defaults-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Terapkan default ke semua baris?</AlertDialogTitle>
            <AlertDialogDescription>Project, Gudang Pemberi, dan Gudang Peminjam di semua baris akan diganti dengan default header. Ada <b>{overrides}</b> nilai yang diubah manual dan akan ditimpa.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="loan-apply-defaults-cancel">Batal</AlertDialogCancel>
            <AlertDialogAction onClick={doApplyAll} data-testid="loan-apply-defaults-confirm">Ya, terapkan</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );

  return <div>
    <TransactionPageHeader type="loan" mode={detail ? "view" : "list"} number={detail?.no}>{can("create") && <Button onClick={startNew} data-testid="loan-create-btn"><Plus className="h-4 w-4 mr-2" />Buat Pinjaman</Button>}</TransactionPageHeader>
    <TxnList module="loan" testidPrefix="loan" server={list} onReload={() => { setDetail(null); load(); }} selectedId={detail?.id} emptyText="Belum ada pinjaman" minWidth={1200}
      onOpen={(r) => openDetail(r.id)} onEdit={async (r) => { const d = await api.get(`/loans/${r.id}`); startEdit(d.data); }}
      columns={[noCol("No. Pinjaman"), dateCol(fmtDate), { key: "from_name", label: "Pemberi", render: (r) => <span data-testid={`loan-from-${r.id}`}>{r.from_name}{r.multi_warehouse && <span className="ml-1 rounded bg-muted px-1 text-[10px] text-muted-foreground">multi</span>}</span> }, { key: "to_name", label: "Peminjam", render: (r) => <span className="flex items-center gap-1" data-testid={`loan-to-${r.id}`}><ArrowLeftRight className="h-3 w-3 text-muted-foreground" />{r.to_name}</span> }, { key: "requester", label: "Pemohon" }, traceCol("project"), traceCol("unit"), { key: "outstanding_total", label: "Outstanding Dasar", num: true, render: (r) => num(r.outstanding_total) }, { key: "status", label: "Status", status: true }]} />
    {detail && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Detail Pinjaman</div><div className="mt-1 flex flex-wrap items-center gap-2"><span className="text-xs font-semibold text-muted-foreground">No. Pinjaman</span><h2 className="font-head font-mono text-lg font-semibold" data-testid="loan-detail-no">{detail.no}</h2><StatusBadge status={detail.status} /></div><div className="mt-2 flex flex-wrap items-center gap-2"><TransactionMutationActions module="loan" id={detail.id} onEdit={() => startEdit()} onDeleted={() => { setDetail(null); setReturns([]); load(); }} compact />{can("print") && <Button variant="outline" size="sm" onClick={() => printDoc("loan", detail, { title: "Pinjam Antar Gudang" })} data-testid="loan-print-btn"><Printer className="h-4 w-4 mr-2" />Cetak</Button>}</div></div><Button variant="ghost" size="icon" onClick={() => { setDetail(null); setRet(false); }} aria-label="Tutup detail" data-testid="loan-detail-close"><X className="h-4 w-4" /></Button></div>
      <LoanDetailLines doc={detail} />
      <AttachmentPanel entity="loan" entityId={detail.id} />
      <DocumentMessageEditor module="loan" value={detail.document_message || ""} readOnly />
      {detail.outstanding_total > 0 && can("create") && <Button onClick={() => setRet(!ret)} data-testid="loan-return-btn"><Undo2 className="h-4 w-4 mr-2" />{ret ? "Tutup Form Return" : "Return Pinjaman"}</Button>}
      <LoanReturnPicker open={ret} loanId={detail.id} onClose={() => setRet(false)} onPosted={() => { setRet(false); openDetail(detail.id); load(); }} />
      <div className="border-t pt-4"><div className="font-head font-semibold mb-2">Riwayat Return</div>{returns.length === 0 ? <div className="text-sm text-muted-foreground">Belum ada return.</div> : <div className="space-y-2" data-testid="loan-return-history">{returns.map((r, ri) => <div key={r.id} className="rounded-lg border p-3" data-testid={`loan-return-${ri}`}><div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between"><div><div className="font-mono text-xs font-semibold">{r.no}</div><div className="text-xs text-muted-foreground">{fmtDate(r.date)} · {(r.lines || []).map((l) => `${l.item_code || l.item_name}: ${num(l.qty)}${retDir(l)}`).join(", ") || "Detail legacy"}</div></div><LoanReturnActions row={r} onEdit={beginReturnEdit} onDeleted={() => { openDetail(detail.id); load(); }} /></div>{r.legacy_ambiguous && <div className="mt-2 text-xs text-destructive">Return lama ini tidak memiliki jejak baris unik, sehingga edit/hapus otomatis dikunci untuk menjaga stok.</div>}</div>)}</div>}</div>
      {returnEdit && <div className="rounded-xl border border-primary/20 p-4 space-y-3"><div className="flex items-center justify-between"><div><div className="text-xs uppercase font-semibold text-primary">Edit Return</div><div className="font-mono text-sm font-semibold">{returnEdit.no}</div></div><Button variant="ghost" size="icon" onClick={() => setReturnEdit(null)} aria-label="Tutup edit return"><X className="h-4 w-4" /></Button></div><div className="grid grid-cols-1 md:grid-cols-2 gap-3"><Field label="Tanggal"><DatePicker value={returnEdit.date} onChange={(v) => setReturnEdit({ ...returnEdit, date: v })} /></Field><Field label="Catatan"><Input value={returnEdit.notes || ""} onChange={(e) => setReturnEdit({ ...returnEdit, notes: e.target.value })} /></Field></div><div className="space-y-2">{returnLines.map((l, i) => <div key={l.id || i} className="grid grid-cols-[1fr_140px] gap-3 items-center"><div className="text-sm">{l.item_code} — {l.item_name}<span className="ml-1 text-xs text-muted-foreground">{retDir(l)}</span></div><Input type="number" step="any" value={l.qty} onChange={(e) => setReturnLines((cur) => cur.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} className="text-right" data-testid={`loan-return-edit-qty-${i}`} /></div>)}</div><Button onClick={saveReturnEdit} data-testid="loan-return-edit-save"><Save className="h-4 w-4 mr-2" />Simpan Perubahan Return</Button></div>}
    </CardContent></Card>}
  </div>;
}
