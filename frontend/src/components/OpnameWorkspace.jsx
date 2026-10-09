import { useCallback, useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/StatusBadge";
import { ItemPicker } from "@/components/ItemPicker";
import { AttachmentPanel } from "@/components/DocMeta";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { num, rupiah, fmtDate, fmtDateTime } from "@/lib/format";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle, ChevronLeft, ChevronRight, Download, FileSpreadsheet, Lock, Paperclip, Plus, Printer, RotateCcw, Save, Search, Send, Snowflake, Upload, X, XCircle } from "lucide-react";
import { FILTERS, MODE_INFO, STATUS_META, buildCountPayload, isBlank, mergeDraft, parseQty, progressPct, uomOptions } from "@/lib/opnameLines";
import { printOpname } from "@/lib/opnamePrint";

const Stat = ({ label, value, tone = "", testid }) => (
  <div className={`rounded-lg border bg-card px-3 py-2 ${tone}`} data-testid={testid}><div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div><div className="font-head text-lg font-semibold tabular-nums">{value}</div></div>
);

export function OpnameSummary({ summary: s = {}, canPrice }) {
  const pct = progressPct(s);
  return <div className="space-y-2" data-testid="opn-summary">
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="Total Barang" value={num(s.total)} testid="opn-sum-total" />
      <Stat label="Sudah Dihitung" value={num(s.counted)} testid="opn-sum-counted" />
      <Stat label="Belum Dihitung" value={num(s.uncounted)} tone={s.uncounted ? "border-amber-300" : ""} testid="opn-sum-uncounted" />
      <Stat label="Barang Sesuai" value={num(s.match)} testid="opn-sum-match" />
      <Stat label="Selisih Plus" value={num(s.plus)} testid="opn-sum-plus" />
      <Stat label="Selisih Minus" value={num(s.minus)} testid="opn-sum-minus" />
    </div>
    {canPrice && "net_value" in s && <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <Stat label="Total Nilai Surplus" value={rupiah(s.surplus_value)} testid="opn-sum-surplus" />
      <Stat label="Total Nilai Shortage" value={rupiah(s.shortage_value)} testid="opn-sum-shortage" />
      <Stat label="Nilai Selisih Bersih" value={rupiah(s.net_value)} tone={s.net_value < 0 ? "border-rose-300" : ""} testid="opn-sum-net" />
    </div>}
    <div className="flex items-center gap-3"><div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div><span className="text-xs tabular-nums text-muted-foreground" data-testid="opn-progress">{pct}% dihitung</span></div>
  </div>;
}

const ACTION_TEXT = {
  return: { title: "Kembalikan ke Penghitungan", btn: "Kembalikan", need: true },
  reject: { title: "Tolak (Reject) Stock Opname", btn: "Tolak", need: true },
  cancel: { title: "Batalkan Stock Opname", btn: "Batalkan Dokumen", need: true, note: "Freeze/lock gudang dilepas. Gunakan bila salah gudang, lalu buat dokumen baru." },
  approve: { title: "Approve & Posting Stock Opname", btn: "Approve & Posting", need: false, note: "Seluruh selisih akan diposting sekaligus ke stok & nilai persediaan (Moving Average). Bila satu baris gagal, seluruh posting dibatalkan dan dapat diulang." },
};

export function OpnameWorkspace({ id, masters, onClose, onChanged }) {
  const [doc, setDoc] = useState(null); const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1); const [q, setQ] = useState(""); const [qInput, setQInput] = useState(""); const [filter, setFilter] = useState("all");
  const [draft, setDraft] = useState({}); const [busy, setBusy] = useState(false); const [correcting, setCorrecting] = useState(false);
  const [reasonDlg, setReasonDlg] = useState(null); const [reasonText, setReasonText] = useState("");
  const [addOpen, setAddOpen] = useState(false); const [addItem, setAddItem] = useState(""); const [addReason, setAddReason] = useState("");
  const [imp, setImp] = useState(null);
  const itemsMap = masters.map("items"); const uomsMap = masters.map("uoms");
  const canPrice = !!doc?.permissions?.price;
  const editable = !!doc?.permissions?.count || correcting;
  const dirty = Object.keys(draft).length;

  const load = useCallback(async (pg = page) => {
    setLoading(true);
    try {
      const r = await api.get(`/opname/${id}/lines?page=${pg}&page_size=50&status=${filter}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
      setDoc(r.data); if (r.data.page && r.data.page !== pg) setPage(r.data.page);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setLoading(false); }
  }, [id, page, filter, q]);
  useEffect(() => { load(page); }, [load, page]);
  useEffect(() => { setDraft({}); setCorrecting(false); setPage(1); }, [id]);
  useEffect(() => { const t = setTimeout(() => { setPage(1); setQ(qInput.trim()); }, 300); return () => clearTimeout(t); }, [qInput]);

  const linesById = useMemo(() => Object.fromEntries((doc?.lines || []).map((l) => [l.id, l])), [doc]);
  const val = (l, k, fallback) => (draft[l.id] && k in draft[l.id] ? draft[l.id][k] : fallback);
  const setField = (l, patch) => setDraft((d) => mergeDraft(d, l.id, patch));
  const factorOf = (l, uid) => Number(uomOptions(itemsMap[l.item_id], uomsMap).find((o) => o.value === uid)?.factor) || 1;

  const save = async (silent = false) => {
    if (!dirty) return true;
    const { lines, errors } = buildCountPayload(draft, linesById);
    if (errors.length) { toast.error(errors[0]); return false; }
    try { setBusy(true); await api.put(`/opname/${id}/count`, { lines }); setDraft({}); if (!silent) toast.success(`${lines.length} baris tersimpan`); await load(page); onChanged?.(); return true; }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); return false; } finally { setBusy(false); }
  };
  const act = async (action, reason) => {
    if (EDIT_FIRST.has(action) && !(await save(true))) return;
    try {
      setBusy(true);
      if (action === "approve") await api.post(`/opname/${id}/post`);
      else await api.post(`/opname/${id}/workflow`, { action, reason });
      toast.success({ review: "Penghitungan selesai — masuk Review", submit: "Diajukan untuk approval", approve: "Disetujui & diposting. Stok disesuaikan.", return: "Dikembalikan ke penghitungan", reject: "Ditolak, dikembalikan ke penghitungan", cancel: "Stock Opname dibatalkan" }[action]);
      setReasonDlg(null); setReasonText(""); await load(1); setPage(1); onChanged?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail), { duration: 9000 }); await load(page); } finally { setBusy(false); }
  };
  const saveCorrection = async () => {
    try {
      setBusy(true);
      const full = (await api.get(`/opname/${id}`)).data.lines;
      const lines = full.map((l) => { const d = draft[l.id] || {}; const qv = "qty" in d ? parseQty(d.qty) : null; const counted = qv == null ? l.counted : qv * factorOf(l, d.uom_id || l.base_uom_id); return { id: l.id, counted, reason: "reason" in d ? d.reason : l.reason }; });
      await api.put(`/transactions/opname/${id}`, { lines });
      toast.success("Koreksi diposting: efek lama direversal lalu diposting ulang"); setDraft({}); setCorrecting(false); await load(page); onChanged?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };
  const doAdd = async () => {
    try { await api.post(`/opname/${id}/add-item`, { item_id: addItem, reason: addReason }); toast.success("Barang ditambahkan ke Stock Opname"); setAddOpen(false); setAddItem(""); setAddReason(""); setFilter("uncounted"); setPage(1); await load(1); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  const downloadTemplate = async () => {
    try { const r = await api.get(`/opname/${id}/template.xlsx`, { responseType: "blob" }); const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = `${String(doc.no).replace(/[^A-Za-z0-9_-]+/g, "_")}_lembar_hitung.xlsx`; a.click(); URL.revokeObjectURL(a.href); }
    catch (e) { toast.error("Template gagal diunduh"); }
  };
  const runImport = async (mode) => {
    const fd = new FormData(); fd.append("file", imp.file);
    try {
      setImp((s) => ({ ...s, busy: true }));
      const r = await api.post(`/opname/${id}/import?mode=${mode}`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      if (mode === "commit") { toast.success(`${r.data.applied} baris hasil hitung diperbarui (tidak diposting)`); setImp(null); setDraft({}); await load(page); onChanged?.(); }
      else setImp((s) => ({ ...s, preview: r.data, busy: false }));
    } catch (e) { const det = e.response?.data?.detail; setImp((s) => ({ ...s, busy: false, preview: det?.errors ? { ...(s.preview || {}), errors: det.errors } : s.preview })); toast.error(apiError(det)); }
  };

  if (!doc) return <Card className="mt-4"><CardContent className="py-10 text-center text-sm text-muted-foreground">{loading ? "Memuat Stock Opname..." : "Tidak ada data"}</CardContent></Card>;
  const p = doc.permissions || {}; const s = doc.summary || {};
  const pages = doc.page_count || 1;
  return <Card className="mt-4 border-primary/20" data-testid="opn-workspace"><CardContent className="space-y-4 pt-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <div className="text-xs font-semibold uppercase tracking-wider text-primary">Workspace Stock Opname</div>
        <div className="flex flex-wrap items-center gap-2"><h2 className="font-head font-mono text-lg font-semibold" data-testid="opn-no">{doc.no}</h2><StatusBadge status={doc.status} />
          {doc.mode === "freeze" ? <span className="inline-flex items-center gap-1 rounded-full border border-sky-300 bg-sky-50 px-2 py-0.5 text-xs text-sky-800" data-testid="opn-mode"><Snowflake className="h-3 w-3" />Freeze{doc.freeze_active ? " aktif" : ""}</span> : <span className="rounded-full border px-2 py-0.5 text-xs" data-testid="opn-mode">Live</span>}
          {doc.legacy && <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs text-amber-900" data-testid="opn-legacy">Dokumen lama</span>}</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs text-muted-foreground md:grid-cols-4">
          <span><Lock className="mr-1 inline h-3 w-3" />Gudang: <b className="text-foreground" data-testid="opn-warehouse">{doc.warehouse_name}</b></span><span>Tanggal: <b className="text-foreground">{fmtDate(doc.date)}</b></span>
          <span>Divisi: <b className="text-foreground">{doc.division_name || "-"}</b></span><span>Scope: <b className="text-foreground">{doc.scope === "division" ? "Per Divisi" : "Semua Barang"}</b></span>
          <span>Petugas: <b className="text-foreground">{doc.counter_name || "-"}</b></span><span>Snapshot: <b className="text-foreground">{fmtDateTime(doc.snapshot_at || doc.created_at)}</b></span>
        </div>
        <p className="text-xs text-muted-foreground">{MODE_INFO[doc.mode] || ""}</p>
      </div>
      <div className="flex items-center gap-1"><TransactionMutationActions module="opname" id={doc.status === "Posted" ? doc.id : null} onEdit={() => setCorrecting(true)} onDeleted={onClose} compact /><Button variant="ghost" size="icon" onClick={onClose} aria-label="Tutup" data-testid="opn-close"><X className="h-4 w-4" /></Button></div>
    </div>
    {doc.last_return && doc.status === "Counting" && <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="opn-last-return"><RotateCcw className="mt-0.5 h-4 w-4" /><div><b>{doc.last_return.action === "reject" ? "Ditolak" : "Dikembalikan"}</b> oleh {doc.last_return.by} — {doc.last_return.reason}</div></div>}
    {doc.last_post_error && doc.status !== "Posted" && <div className="flex items-start gap-2 rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900" data-testid="opn-post-error"><XCircle className="mt-0.5 h-4 w-4" /><div>Posting terakhir gagal dan dibatalkan seluruhnya (stok tidak berubah): {doc.last_post_error}</div></div>}
    <OpnameSummary summary={s} canPrice={canPrice} />
    {doc.readiness?.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="opn-readiness"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />Sebelum diajukan: {doc.readiness.join(" · ")}</div>}

    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[220px] flex-1"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="Cari kode / nama barang" className="pl-8" data-testid="opn-search" /></div>
      <Select value={filter} onValueChange={(v) => { setFilter(v); setPage(1); }}><SelectTrigger className="w-[190px]" data-testid="opn-filter"><SelectValue /></SelectTrigger><SelectContent>{FILTERS.map((f) => <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>)}</SelectContent></Select>
      <Button variant="outline" size="sm" onClick={downloadTemplate} data-testid="opn-template-btn"><Download className="mr-2 h-4 w-4" />Download Template Excel</Button>
      {p.import && <Button variant="outline" size="sm" onClick={() => setImp({ file: null, preview: null })} data-testid="opn-import-btn"><Upload className="mr-2 h-4 w-4" />Import Hasil Hitung</Button>}
      {p.add_item && <Button variant="outline" size="sm" onClick={() => setAddOpen(true)} data-testid="opn-add-item-btn"><Plus className="mr-2 h-4 w-4" />Tambah Barang</Button>}
      <Button variant="outline" size="sm" onClick={() => printOpname("sheet", id).catch((e) => toast.error(apiError(e.response?.data?.detail) || "Cetak gagal"))} data-testid="opn-print-sheet"><Printer className="mr-2 h-4 w-4" />Lembar Hitung</Button>
      <Button variant="outline" size="sm" onClick={() => printOpname("ba", id).catch((e) => toast.error(apiError(e.response?.data?.detail) || "Cetak gagal"))} data-testid="opn-print-ba"><FileSpreadsheet className="mr-2 h-4 w-4" />Berita Acara</Button>
    </div>

    <div className="overflow-auto rounded-md border"><table className="w-full min-w-[1100px] text-sm"><thead className="sticky top-0 z-10 bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground">
      <th className="p-2">Barang</th><th className="p-2 w-[150px]">Satuan Hitung</th><th className="p-2 text-right">Stok Sistem</th><th className="p-2 w-[150px]">Stok Fisik</th><th className="p-2 text-right">Selisih</th>
      {canPrice && <><th className="p-2 text-right">Harga Satuan (Moving Average)</th><th className="p-2 text-right">Nilai Selisih</th></>}<th className="p-2 w-[220px]">Alasan Selisih</th><th className="p-2">Status</th></tr></thead>
      <tbody>{(doc.lines || []).map((l) => {
        const it = itemsMap[l.item_id]; const opts = uomOptions(it, uomsMap); const uid = val(l, "uom_id", l.counted_uom_id || l.base_uom_id || opts[0]?.value || ""); const fx = factorOf(l, uid);
        const savedDisp = l.counted == null ? "" : (l.counted_uom_id && l.counted_uom_id === uid && l.counted_qty != null ? l.counted_qty : l.counted / fx);
        const qv = val(l, "qty", savedDisp); const qn = parseQty(qv); const pending = draft[l.id] && "qty" in draft[l.id];
        const variance = pending ? (qn == null || Number.isNaN(qn) ? null : qn * fx - l.system_qty) : l.variance;
        const st = pending ? (variance == null ? "uncounted" : Math.abs(variance) < 1e-9 ? "match" : variance > 0 ? "plus" : "minus") : l.status;
        const reasonVal = val(l, "reason", l.reason || ""); const needReason = variance != null && Math.abs(variance) > 1e-9 && !String(reasonVal).trim();
        const showCost = canPrice && editable && (l.needs_cost || l.approved_unit_cost != null || (variance > 0 && l.avg_cost == null));
        return <tr key={l.id} className={`border-t align-top ${l.needs_recount ? "bg-amber-50/70" : ""}`} data-testid={`opn-row-${l.item_code}`}>
          <td className="p-2"><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div><div className="font-medium">{l.item_name}</div>{l.added_manually && <div className="text-[11px] text-sky-700">+ ditambahkan: {l.added_reason}</div>}{l.needs_recount && <div className="text-[11px] font-medium text-amber-800" data-testid={`opn-recount-${l.item_code}`}><AlertTriangle className="mr-1 inline h-3 w-3" />Perlu hitung ulang: {l.recount_reason}</div>}</td>
          <td className="p-1.5">{editable && opts.length > 1 ? <Select value={uid} onValueChange={(v) => setField(l, { uom_id: v })}><SelectTrigger className="h-8" data-testid={`opn-uom-${l.item_code}`}><SelectValue /></SelectTrigger><SelectContent>{opts.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent></Select> : <span className="text-xs">{l.unit || "-"}</span>}</td>
          <td className="p-2 text-right tabular-nums">{num(l.system_qty)} <span className="text-[10px] text-muted-foreground">{l.unit}</span></td>
          <td className="p-1.5">{editable ? <Input type="number" min="0" step="any" inputMode="decimal" value={qv} placeholder="Belum dihitung" aria-label={`Stok fisik ${l.item_code}`} onChange={(e) => setField(l, { qty: e.target.value, uom_id: uid })} className={`h-8 min-w-[130px] text-right tabular-nums placeholder:text-xs ${pending ? "border-primary" : ""}`} data-testid={`opn-count-${l.item_code}`} /> : <div className="pt-1.5 text-right tabular-nums">{l.counted == null ? <span className="text-muted-foreground">—</span> : num(l.counted)}</div>}</td>
          <td className={`p-2 text-right font-semibold tabular-nums ${variance < 0 ? "text-rose-600" : variance > 0 ? "text-sky-700" : ""}`} data-testid={`opn-var-${l.item_code}`}>{variance == null ? "—" : `${variance > 0 ? "+" : ""}${num(variance)}`}</td>
          {canPrice && <><td className="p-1.5 text-right tabular-nums" data-testid={`opn-price-${l.item_code}`}>{showCost ? <div className="space-y-1"><Input type="number" min="0" step="any" value={val(l, "approved_unit_cost", l.approved_unit_cost ?? "")} onChange={(e) => setField(l, { approved_unit_cost: e.target.value })} placeholder={l.avg_cost ? `avg ${num(l.avg_cost)}` : "Harga wajib"} className="h-8 text-right" data-testid={`opn-cost-${l.item_code}`} /><Input value={val(l, "cost_reason", l.cost_reason || "")} onChange={(e) => setField(l, { cost_reason: e.target.value, approved_unit_cost: val(l, "approved_unit_cost", l.approved_unit_cost ?? "") })} placeholder="Alasan harga (wajib)" className="h-7 text-xs" data-testid={`opn-cost-reason-${l.item_code}`} /></div> : (l.unit_price == null ? <span className="text-xs text-muted-foreground">—</span> : rupiah(l.unit_price))}</td>
            <td className={`p-2 text-right tabular-nums ${l.value < 0 ? "text-rose-600" : ""}`} data-testid={`opn-value-${l.item_code}`}>{pending ? <span className="text-[11px] text-muted-foreground">simpan dulu</span> : l.value == null ? "—" : rupiah(l.value)}</td></>}
          <td className="p-1.5">{editable ? <Input value={reasonVal} onChange={(e) => setField(l, { reason: e.target.value })} placeholder={needReason ? "Wajib bila selisih" : "Alasan (opsional)"} className={`h-8 text-xs ${needReason ? "border-amber-400" : ""}`} data-testid={`opn-reason-${l.item_code}`} /> : <span className="text-xs">{l.reason || "-"}</span>}</td>
          <td className="p-2"><span className={`whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] ${STATUS_META[st]?.tone}`} data-testid={`opn-status-${l.item_code}`}>{STATUS_META[st]?.label}</span>{pending && <div className="mt-1 text-[10px] text-primary">belum disimpan</div>}</td>
        </tr>;
      })}{!doc.lines?.length && <tr><td colSpan={canPrice ? 9 : 7} className="p-6 text-center text-sm text-muted-foreground">Tidak ada barang untuk filter ini</td></tr>}</tbody></table></div>
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><span data-testid="opn-page-info">{doc.line_total} barang · halaman {doc.page || 1}/{pages}{dirty ? ` · ${dirty} perubahan belum disimpan (tetap tersimpan saat pindah halaman)` : ""}</span>
      <div className="flex gap-1"><Button variant="outline" size="sm" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)} data-testid="opn-prev"><ChevronLeft className="h-4 w-4" /></Button><Button variant="outline" size="sm" disabled={page >= pages || loading} onClick={() => setPage(page + 1)} data-testid="opn-next"><ChevronRight className="h-4 w-4" /></Button></div></div>

    <div className="flex flex-wrap gap-2 border-t pt-3">
      {correcting ? <><Button onClick={saveCorrection} disabled={busy} data-testid="opn-correction-save"><Save className="mr-2 h-4 w-4" />Simpan Koreksi (Reversal)</Button><Button variant="outline" onClick={() => { setCorrecting(false); setDraft({}); }} data-testid="opn-correction-cancel">Batal Koreksi</Button></> : <>
        {p.count && <Button variant="outline" onClick={() => save()} disabled={busy || !dirty} data-testid="opn-save"><Save className="mr-2 h-4 w-4" />Simpan Hitung{dirty ? ` (${dirty})` : ""}</Button>}
        {p.review && <Button onClick={() => act("review")} disabled={busy} data-testid="opn-review"><CheckCircle className="mr-2 h-4 w-4" />Selesai Hitung → Review</Button>}
        {p.submit && doc.status === "Review" && <Button onClick={() => act("submit")} disabled={busy} data-testid="opn-submit"><Send className="mr-2 h-4 w-4" />Ajukan Approval</Button>}
        {p.approve && <Button onClick={() => setReasonDlg("approve")} disabled={busy} data-testid="opn-approve"><CheckCircle className="mr-2 h-4 w-4" />Approve &amp; Posting</Button>}
        {p.reject && <Button variant="outline" className="text-rose-700" onClick={() => setReasonDlg("reject")} disabled={busy} data-testid="opn-reject"><XCircle className="mr-2 h-4 w-4" />Reject</Button>}
        {p.return && <Button variant="outline" onClick={() => setReasonDlg("return")} disabled={busy} data-testid="opn-return"><RotateCcw className="mr-2 h-4 w-4" />Kembalikan</Button>}
        {p.cancel && <Button variant="ghost" className="text-rose-700" onClick={() => setReasonDlg("cancel")} disabled={busy} data-testid="opn-cancel">Batalkan Dokumen</Button>}
      </>}
    </div>

    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran (foto fisik, berita acara, pendukung)</div><AttachmentPanel entity="opname" entityId={doc.id} /></div>
      <div className="rounded-xl border bg-card p-4" data-testid="opn-history"><div className="mb-2 font-head text-sm font-semibold">Riwayat &amp; Audit</div><ol className="space-y-1.5 text-xs">{(doc.history || []).map((h, i) => <li key={i} className="flex gap-2"><span className="w-32 shrink-0 text-muted-foreground">{fmtDateTime(h.at)}</span><span><b>{HIST[h.action] || h.action}</b> {h.to && h.from !== h.to ? `→ ${h.to}` : ""} oleh {h.by_name || h.by}{h.reason ? ` — “${h.reason}”` : ""}</span></li>)}</ol></div>
    </div>

    <Dialog open={!!reasonDlg} onOpenChange={(o) => !o && setReasonDlg(null)}><DialogContent data-testid="opn-reason-dialog"><DialogHeader><DialogTitle>{ACTION_TEXT[reasonDlg]?.title}</DialogTitle></DialogHeader>{ACTION_TEXT[reasonDlg]?.note && <p className="text-sm text-muted-foreground">{ACTION_TEXT[reasonDlg].note}</p>}{ACTION_TEXT[reasonDlg]?.need !== false && <Textarea value={reasonText} onChange={(e) => setReasonText(e.target.value)} placeholder="Alasan (wajib)" data-testid="opn-reason-input" />}<DialogFooter><Button variant="outline" onClick={() => setReasonDlg(null)} data-testid="opn-reason-cancel">Batal</Button><Button onClick={() => act(reasonDlg, reasonText)} disabled={(ACTION_TEXT[reasonDlg]?.need !== false && !reasonText.trim()) || busy} data-testid="opn-reason-confirm">{ACTION_TEXT[reasonDlg]?.btn}</Button></DialogFooter></DialogContent></Dialog>

    <Dialog open={addOpen} onOpenChange={setAddOpen}><DialogContent data-testid="opn-add-dialog"><DialogHeader><DialogTitle>Tambah Barang yang Ditemukan Fisik</DialogTitle></DialogHeader><p className="text-sm text-muted-foreground">Hanya barang dari Master Barang yang belum ada di dokumen ini. Penambahan dicatat di audit trail.</p><ItemPicker items={masters.data.items || []} lookup={masters.status?.("items")} uoms={uomsMap} value={addItem} onChange={setAddItem} warehouseId={doc.warehouse_id} testid="opn-add-item" /><Input value={addReason} onChange={(e) => setAddReason(e.target.value)} placeholder="Alasan penambahan (wajib)" data-testid="opn-add-reason" /><DialogFooter><Button variant="outline" onClick={() => setAddOpen(false)} data-testid="opn-add-cancel">Batal</Button><Button onClick={doAdd} disabled={!addItem || !addReason.trim()} data-testid="opn-add-confirm">Tambahkan</Button></DialogFooter></DialogContent></Dialog>

    <Dialog open={!!imp} onOpenChange={(o) => !o && setImp(null)}><DialogContent className="max-w-3xl" data-testid="opn-import-dialog"><DialogHeader><DialogTitle>Import Hasil Hitung — {doc.no}</DialogTitle></DialogHeader>
      <p className="text-sm text-muted-foreground">Gunakan file dari “Download Template Excel” dokumen ini. Baris Stok Fisik kosong tetap <b>Belum Dihitung</b>. Import hanya memperbarui hasil hitung — tidak mengajukan atau memposting.</p>
      <Input type="file" accept=".xlsx" onChange={(e) => setImp({ file: e.target.files?.[0] || null, preview: null })} data-testid="opn-import-file" />
      {imp?.preview && <div className="max-h-72 space-y-2 overflow-auto text-sm" data-testid="opn-import-preview">
        <div className="flex gap-4 text-xs"><span>Baris valid: <b>{imp.preview.valid_rows ?? imp.preview.rows?.length ?? 0}</b></span><span>Kosong (dilewati): <b>{imp.preview.skipped_blank ?? 0}</b></span><span className={imp.preview.errors?.length ? "text-rose-700" : ""}>Error: <b>{imp.preview.errors?.length || 0}</b></span></div>
        {imp.preview.errors?.length > 0 && <ul className="list-disc rounded-md border border-rose-200 bg-rose-50 p-2 pl-6 text-xs text-rose-900" data-testid="opn-import-errors">{imp.preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        {imp.preview.rows?.length > 0 && <table className="w-full text-xs [&_td]:px-2 [&_td]:py-1 [&_th]:px-2 [&_th]:py-1"><thead><tr className="text-left text-muted-foreground"><th>Baris</th><th>Kode</th><th>Nama</th><th className="text-right">Fisik</th><th>Satuan</th><th>Alasan</th></tr></thead><tbody>{imp.preview.rows.map((r) => <tr key={r.row} className="border-t"><td>{r.row}</td><td className="font-mono">{r.item_code}</td><td>{r.item_name}</td><td className="text-right">{num(r.qty)}</td><td>{r.unit}</td><td>{r.reason}</td></tr>)}</tbody></table>}
      </div>}
      <DialogFooter><Button variant="outline" onClick={() => setImp(null)} data-testid="opn-import-close">Tutup</Button><Button variant="outline" disabled={!imp?.file || imp?.busy} onClick={() => runImport("preview")} data-testid="opn-import-preview-btn">Preview</Button><Button disabled={!imp?.preview || imp.preview.errors?.length > 0 || !imp.preview.rows?.length || imp?.busy} onClick={() => runImport("commit")} data-testid="opn-import-commit-btn">Simpan Hasil Import</Button></DialogFooter>
    </DialogContent></Dialog>
  </CardContent></Card>;
}

const EDIT_FIRST = new Set(["review", "submit"]);
const HIST = { create: "Dibuat & snapshot", review: "Selesai hitung", submit: "Diajukan approval", return: "Dikembalikan", reject: "Ditolak", cancel: "Dibatalkan", approve_post: "Disetujui & diposting", correction: "Koreksi (reversal)" };
export { isBlank };
