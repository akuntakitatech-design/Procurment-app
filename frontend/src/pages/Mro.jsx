import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { MasterQuickCreate } from "@/pages/MasterData";
import { useAuth } from "@/context/AuthContext";
import { ItemLines } from "@/components/ItemLines";
import { DocMetaTabs } from "@/components/DocMetaTabs";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { PageHeader } from "@/components/PageHeader";
import { TransactionProgress } from "@/components/TransactionProgress";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { num, toNum, fmtDate, todayISO } from "@/lib/format";
import { Save, Send, Printer, Ban, ArrowLeft, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";
import { SpkAllocationModal, formatAllocText } from "@/components/SpkAllocationModal";
import { uploadPendingAttachments } from "@/components/DocMeta";
import { useCompletenessWarning } from "@/components/CompletenessWarningDialog";
import { buildTxnWarnings, HEADER_FIELDS, ITEM_FIELDS } from "@/lib/validation";
import { TxnList } from "@/components/TxnList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";

const FLOW = ["MRO", "RO", "PO", "DO", "MI"];
function lifecycleStage(t) {
  const req = Number(t?.request || 0), ro = Number(t?.qty_ro || 0), po = Number(t?.qty_po || 0), received = Number(t?.qty_received || 0), mi = Number(t?.qty_mi || 0);
  if (req > 0 && mi >= req) return "Completed"; if (mi > 0) return "MI"; if (received > 0) return "DO"; if (po > 0) return "PO"; if (ro > 0) return "RO"; return "MRO";
}
function FlowMini({ stage }) {
  const current = stage === "Completed" ? 4 : Math.max(0, FLOW.indexOf(stage));
  return <div className="flex min-w-[280px] items-center gap-1.5">{FLOW.map((x, i) => { const done = stage === "Completed" || i < current, active = stage !== "Completed" && i === current; return <div key={x} className="flex items-center gap-1.5"><div className={`flex h-7 min-w-9 items-center justify-center rounded-full px-2 text-[10px] font-semibold ${done ? "bg-emerald-100 text-emerald-700" : active ? "bg-blue-100 text-blue-700 ring-1 ring-blue-200" : "bg-muted text-muted-foreground"}`}>{x}</div>{i < FLOW.length - 1 && <div className={`h-px w-3 ${done ? "bg-emerald-300" : "bg-border"}`} />}</div>; })}</div>;
}

export function MroList() {
  const nav = useNavigate(); const [rows, setRows] = useState([]); const [trace, setTrace] = useState([]); const [stageFilter, setStageFilter] = useState("all");
  const [loading, setLoading] = useState(true); const [error, setError] = useState(false); const [traceFailed, setTraceFailed] = useState(false);
  // Decoupled loads: /mro is the PRIMARY source for transaction rows. Traceability is best-effort
  // enrichment only — if it fails/aborts/times out, rows still render (trace falls back to []).
  const loadMro = useCallback(async () => { setLoading(true); setError(false); try { const a = await api.get("/mro"); setRows(a.data || []); } catch (e) { setError(true); setLoading(false); return; } setLoading(false); }, []);
  const loadTrace = useCallback(async () => { setTraceFailed(false); try { const b = await api.get("/reports/mro-traceability"); setTrace(b.data || []); } catch (e) { setTrace([]); setTraceFailed(true); } }, []);
  const reload = useCallback(() => { loadMro(); loadTrace(); }, [loadMro, loadTrace]);
  useEffect(() => { loadMro(); loadTrace(); }, [loadMro, loadTrace]);
  const traceByMro = useMemo(() => { const map = {}; for (const t of trace) { const k = t.mro_id; if (!k) continue; if (!map[k]) map[k] = { request: 0, qty_ro: 0, qty_po: 0, qty_received: 0, qty_mi: 0, outstanding: 0 }; ["request","qty_ro","qty_po","qty_received","qty_mi","outstanding"].forEach((x) => map[k][x] += Number(t[x] || 0)); } return map; }, [trace]);
  const enriched = useMemo(() => rows.map((r) => { const t = traceByMro[r.id] || { request: 0, qty_ro: 0, qty_po: 0, qty_received: 0, qty_mi: 0, outstanding: r.outstanding_total || 0 }; return { ...r, lifecycle: t, lifecycle_stage: lifecycleStage(t) }; }), [rows, traceByMro]);
  const counts = useMemo(() => { const out = { all: enriched.length, MRO: 0, RO: 0, PO: 0, DO: 0, MI: 0, Completed: 0 }; enriched.forEach((r) => out[r.lifecycle_stage]++); return out; }, [enriched]);
  const cards = [{ key:"all",label:"Total MRO",desc:"Seluruh transaksi"},{key:"MRO",label:"Belum ke RO",desc:"Masih di tahap MRO"},{key:"RO",label:"Sampai RO",desc:"Belum menjadi PO"},{key:"PO",label:"Sampai PO",desc:"Belum ada penerimaan"},{key:"DO",label:"Sampai DO",desc:"Barang sudah diterima"},{key:"MI",label:"Sampai MI",desc:"Pengeluaran masih partial"},{key:"Completed",label:"Selesai",desc:"MI memenuhi request"}];
  const filtered = useMemo(() => enriched.filter((r) => stageFilter === "all" || r.lifecycle_stage === stageFilter), [enriched, stageFilter]);
  const columns = useMemo(() => [noCol("No. MRO"), dateCol(fmtDate), { key: "requester", label: "Pemohon" }, { key: "division_name", label: "Divisi" }, traceCol("project"), traceCol("spk"), traceCol("warehouse"), { key: "line_count", label: "Item", num: true }, { key: "lifecycle_stage", label: "Tracking", render: (r) => <FlowMini stage={r.lifecycle_stage} /> }, { key: "req", label: "Request", num: true, value: (r) => r.lifecycle.request, render: (r) => num(r.lifecycle.request) }, { key: "mi", label: "MI", num: true, value: (r) => r.lifecycle.qty_mi, render: (r) => num(r.lifecycle.qty_mi) }, { key: "outs", label: "Outstanding", num: true, value: (r) => r.lifecycle.outstanding, render: (r) => <span className="font-semibold">{num(r.lifecycle.outstanding)}</span> }, { key: "status", label: "Status", status: true }], []);
  return <div><PageHeader title="MRO — Material Request Order" subtitle="Pengajuan kebutuhan material dan monitoring lifecycle transaksi"><Button onClick={() => nav("/mro/new")}><Plus className="h-4 w-4 mr-2" />Buat Baru</Button></PageHeader>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7 mb-5">{cards.map((c) => <button key={c.key} onClick={() => setStageFilter(c.key)} className={`rounded-xl border bg-card p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md ${stageFilter === c.key ? "border-primary ring-1 ring-primary/20" : ""}`}><div className="text-2xl font-bold tabular-nums">{counts[c.key] || 0}</div><div className="mt-1 text-sm font-semibold">{c.label}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{c.desc}</div></button>)}</div>
    {traceFailed && !error && !loading && <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800" data-testid="mro-trace-warning">Informasi tracking belum dapat dimuat. Baris transaksi tetap ditampilkan.</div>}
    {loading && <div className="rounded-xl border bg-card p-10 text-center text-muted-foreground shadow-sm" data-testid="mro-loading">Memuat transaksi MRO...</div>}
    {error && !loading && <div className="rounded-xl border bg-card p-10 text-center shadow-sm" data-testid="mro-error"><p className="mb-3 text-muted-foreground">Daftar MRO belum dapat dimuat.</p><Button variant="outline" onClick={reload} data-testid="mro-retry">Coba Lagi</Button></div>}
    {!loading && !error && <TxnList module="mro" columns={columns} rows={filtered} testidPrefix="mro" onReload={reload} resetKey={stageFilter} minWidth={1600} emptyText="Belum ada transaksi pada filter ini"
      filters={stageFilter !== "all" && <Button variant="outline" onClick={()=>setStageFilter("all")}>Tampilkan Semua</Button>}
      onOpen={(r)=>nav(`/mro/${r.id}`)} onEdit={(r)=>nav(`/mro/${r.id}?edit=1`)} onPrint={async (r)=>{const d=await api.get(`/mro/${r.id}`);printDoc("MRO",d.data);}}/>}
  </div>;
}

export function MroForm() {
  const { id } = useParams(); const nav = useNavigate(); const { can, user } = useAuth(); const masters = useMasters(STOCK_REFS); const [quickItem, setQuickItem] = useState(null);
  const [h, setH] = useState({ no: "", date: todayISO(), requester: "", department: "", division_id: "", default_warehouse_id: "", default_project_id: "", default_unit_id: "", spk: "", need_date: todayISO(), notes: "", document_message: null });
  const [lines, setLines] = useState([]); const [doc, setDoc] = useState(null); const [editing,setEditing]=useState(false); const isNew = !id;
  const [allocs, setAllocs] = useState({}); const [allocLine, setAllocLine] = useState(null); const [spkMap, setSpkMap] = useState({});
  const [pending, setPending] = useState([]); // in-memory attachments chosen before first save
  const [noError, setNoError] = useState(false); const noRef = useRef(null);
  const { confirm, dialog } = useCompletenessWarning();
  const lineKey = (l) => l.id || l._key;
  useEffect(() => { api.get("/lookup/spk").then((r)=>{ const m={}; (r.data||[]).forEach((s)=>{m[s.id]=s.spk_number;}); setSpkMap(m); }).catch(()=>{}); }, []);
  // Default Pemohon to the logged-in user on a brand-new MRO (still editable).
  useEffect(() => { if (isNew && user?.name) setH((prev) => (prev.requester ? prev : { ...prev, requester: user.name })); }, [isNew, user]);
  const load = useCallback(() => api.get(`/mro/${id}`).then(async (r) => {
    setDoc(r.data); setH(r.data); setLines(r.data.lines.map((l) => ({ ...l }))); setEditing(false);
    try { const ar = await api.get(`/spk-allocations/mro/doc/${id}`); const m={}; (ar.data.lines||[]).forEach((ln)=>{ if((ln.allocations||[]).length) m[ln.item_line_id]=ln.allocations.map((a)=>({spk_id:a.spk_id,allocated_qty:a.allocated_qty})); }); setAllocs(m); } catch { /* ignore */ }
  }), [id]);
  useEffect(() => { if (id) load(); }, [id, load]); const submitted = doc?.submitted; const waitingApproval = doc?.approval_status === "Waiting Approval"; const readOnly = !isNew && !editing && (submitted || waitingApproval);
  const allocSummary = (l) => { const list=(allocs[lineKey(l)]||[]); const qty=toNum(l.qty); const total=list.reduce((s,a)=>s+toNum(a.allocated_qty),0); return { item_qty: qty, non_spk_qty: Math.max(0,qty-total), allocations: list.map((a)=>({spk_number:spkMap[a.spk_id]||a.spk_id, allocated_qty:toNum(a.allocated_qty)})), over: total-qty>1e-6 }; };
  const persistAllocations = async (mroId) => {
    if (!Object.keys(allocs).length) return;
    let serverLines=[]; try { const r=await api.get(`/mro/${mroId}`); serverLines=r.data.lines||[]; } catch { return; }
    const persistLines = isNew ? lines : lines.filter((l)=>toNum(l.qty)>0);
    const pairs = serverLines.length===persistLines.length
      ? persistLines.map((l,j)=>[lineKey(l), serverLines[j]?.id])
      : (()=>{ const pool=[...serverLines]; return persistLines.map((l)=>{ const idx=pool.findIndex((s)=>s.item_id===l.item_id); const s=idx>=0?pool.splice(idx,1)[0]:null; return [lineKey(l), s?.id]; }); })();
    for (const [key, sid] of pairs) { if (!sid || !(key in allocs)) continue; const list=(allocs[key]||[]).filter((a)=>a.spk_id&&toNum(a.allocated_qty)>0).map((a)=>({spk_id:a.spk_id,allocated_qty:toNum(a.allocated_qty)})); try { await api.put(`/spk-allocations/mro/line/${sid}`,{allocations:list}); } catch(e){ toast.error(apiError(e.response?.data?.detail)); } }
  };
  // HARD validation (blocking): SPK allocation may never exceed item Qty.
  const spkOverQty = () => {
    for (const l of lines) { const tot=(allocs[lineKey(l)]||[]).reduce((s,a)=>s+toNum(a.allocated_qty),0); if (tot-toNum(l.qty)>1e-6) { toast.error(`Alokasi SPK (${num(tot)}) melebihi Qty item ${l.item_code||""} (${num(l.qty)}). Sesuaikan sebelum menyimpan.`); return true; } }
    return false;
  };
  const doSave = async (submit) => {
    try {
      const no=(h.no||"").trim();
      const payload={...h,no,submitted:false,lines}; let mroId;
      if(isNew){ const res=await api.post("/mro",payload); mroId=res.data.id; } else { await api.put(`/transactions/mro/${id}`,payload); mroId=id; }
      await saveDocumentMessage("mro",mroId,h.document_message);
      await persistAllocations(mroId);
      // Upload pending attachments against the freshly-created MRO ID.
      let failed=[];
      if (pending.length) {
        const res = await uploadPendingAttachments("mro", mroId, pending);
        failed = res.failed;
        setPending(failed); // keep only the failed ones for retry
      }
      if (submit && failed.length) {
        toast.error(`MRO berhasil disimpan sebagai Draft, tetapi lampiran "${failed.map((f)=>f.name).join(", ")}" gagal diunggah. Silakan coba kembali sebelum Submit.`);
        nav(`/mro/${mroId}`); if(!isNew) load(); return;
      }
      if (failed.length) toast.error(`MRO tersimpan, tetapi lampiran "${failed.map((f)=>f.name).join(", ")}" gagal diunggah. Silakan unggah ulang.`);
      if(submit) await api.post(`/mro/${mroId}/submit`);
      toast.success(submit?"MRO disubmit":"MRO tersimpan"); nav(`/mro/${mroId}`); if(!isNew) load();
    } catch(e){ const msg=apiError(e.response?.data?.detail); if(/nomor mro/i.test(String(msg))){ setNoError(true); noRef.current?.focus?.(); noRef.current?.scrollIntoView?.({behavior:"smooth",block:"center"}); } toast.error(msg); }
  };
  const save = (submit=false) => {
    // 1) HARD: Nomor MRO wajib (bukan bagian warning non-blocking)
    const no=(h.no||"").trim();
    if (isNew && !no) { setNoError(true); toast.error("Nomor MRO wajib diisi sebelum transaksi disimpan."); noRef.current?.focus?.(); noRef.current?.scrollIntoView?.({behavior:"smooth",block:"center"}); return; }
    setNoError(false);
    // 2) HARD: SPK allocation tidak boleh melebihi Qty item
    if (spkOverQty()) return;
    // 3) Non-blocking completeness warning, lalu lanjut simpan
    const warnings = buildTxnWarnings({ h, lines, headerFields: HEADER_FIELDS.mro, itemFields: ITEM_FIELDS.mro });
    confirm(warnings, () => doSave(submit));
  };
  const doSubmit=async()=>{try{await api.post(`/mro/${id}/submit`);toast.success("MRO disubmit");load();}catch(e){toast.error(apiError(e.response?.data?.detail));}}; const doCancel=async()=>{await api.post(`/mro/${id}/cancel`,{reason:"Dibatalkan user"});toast.success("MRO dibatalkan");load();};
  const factor=(l)=>Number(l.conversion_factor)||1, q=(l,v)=>num((Number(v)||0)/factor(l)), unitText=(l)=>l.display_unit||l.unit||"";
  const defaults={warehouse_id:h.default_warehouse_id,project_id:h.default_project_id,unit_id:h.default_unit_id};
  const projectOpts = masters.opts("projects", (d)=>d.name); const unitOpts = masters.opts("units", (d)=>d.plate_no||d.name);
  return <div><PageHeader title={isNew?"MRO Baru":doc?.no} subtitle={doc&&<StatusBadge status={doc.status}/>} numberInput={isNew?<Input ref={noRef} value={h.no||""} onChange={(e)=>{setH({...h,no:e.target.value});if(noError)setNoError(false);}} placeholder="mis. MRO-OMSS-001" data-testid="mro-no-input" className={`h-8 w-56 font-mono ${noError?"border-destructive ring-1 ring-destructive":""}`}/>:undefined}><Button variant="outline" onClick={()=>nav("/mro")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{!isNew&&!editing&&<TransactionMutationActions module="mro" id={id} ready={!!doc} onEdit={()=>setEditing(true)} onDeleted={()=>nav("/mro")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{(!readOnly||editing)&&can("edit")&&!isNew&&<Button variant="outline" onClick={()=>save(false)}><Save className="h-4 w-4 mr-2"/>Simpan Perubahan</Button>}{isNew&&can("create")&&<Button variant="outline" onClick={()=>save(false)}><Save className="h-4 w-4 mr-2"/>Simpan Draft</Button>}{isNew&&can("submit")&&<Button onClick={()=>save(true)}><Send className="h-4 w-4 mr-2"/>Simpan & Submit</Button>}{!isNew&&!submitted&&!waitingApproval&&!editing&&can("submit")&&<Button onClick={doSubmit}><Send className="h-4 w-4 mr-2"/>Submit</Button>}{!isNew&&doc&&!doc.cancelled&&!editing&&can("cancel")&&<Button variant="outline" onClick={doCancel}><Ban className="h-4 w-4 mr-2"/>Batalkan</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("MRO",doc)}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</PageHeader>
    <TransactionProgress className="mb-4" stages={["Draft","Waiting Approval","Open","Partial","Completed"]} status={isNew?"Draft":editing?"Edit":doc?.status}/><DocMetaTabs entity="mro" entityId={id} attachmentPending={pending} onAttachmentPendingChange={setPending}><div className="space-y-4"><Card><CardContent className="pt-6 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Pemohon"><Input value={h.requester||""} onChange={(e)=>setH({...h,requester:e.target.value})} disabled={readOnly}/></Field><Field label="Divisi"><Combobox options={masters.opts("divisions",d=>d.name)} value={h.division_id} onChange={(v)=>setH({...h,division_id:v})} disabled={readOnly}/></Field><Field label="Tanggal MRO"><DatePicker value={h.date} onChange={(v)=>setH({...h,date:v})} disabled={readOnly}/></Field><Field label="Tanggal Kebutuhan"><DatePicker value={h.need_date} onChange={(v)=>setH({...h,need_date:v})} disabled={readOnly}/></Field></div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Proyek Default"><Combobox options={projectOpts} value={h.default_project_id||""} onChange={(v)=>setH({...h,default_project_id:v})} disabled={readOnly}/></Field><Field label="Gudang Default"><Combobox options={masters.opts("warehouses",d=>d.name)} value={h.default_warehouse_id} onChange={(v)=>setH({...h,default_warehouse_id:v})} disabled={readOnly}/></Field><Field label="Unit/Aset Default"><Combobox options={unitOpts} value={h.default_unit_id||""} onChange={(v)=>setH({...h,default_unit_id:v})} disabled={readOnly}/></Field><Field label="Keterangan"><Input value={h.notes||""} onChange={(e)=>setH({...h,notes:e.target.value})} disabled={readOnly}/></Field></div>
      {readOnly?<div className="border rounded-md overflow-x-auto"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2">Keterangan</th><th className="p-2">Satuan</th><th className="p-2 text-right">Request</th><th className="p-2 text-right">RO</th><th className="p-2 text-right">PO</th><th className="p-2 text-right">Diterima</th><th className="p-2 text-right">MI</th><th className="p-2 text-right">Outstanding</th><th className="p-2">Alokasi SPK</th></tr></thead><tbody>{lines.map((l,i)=><tr key={i} className="border-t"><td className="p-2">{l.item_code} — {l.item_name}</td><td className="p-2">{l.notes||"-"}</td><td className="p-2">{unitText(l)}</td><td className="p-2 text-right">{q(l,l.monitor?.qty_request)}</td><td className="p-2 text-right">{q(l,l.monitor?.qty_ro)}</td><td className="p-2 text-right">{q(l,l.monitor?.qty_po)}</td><td className="p-2 text-right">{q(l,l.monitor?.qty_received)}</td><td className="p-2 text-right">{q(l,l.monitor?.qty_mi)}</td><td className="p-2 text-right font-semibold">{q(l,l.monitor?.outstanding)}</td><td className="p-2 text-xs" data-testid={`mro-alloc-view-${i}`}>{formatAllocText(allocSummary(l))}</td></tr>)}</tbody></table></div>:<ItemLines lines={lines} onChange={setLines} masters={masters} fields={{warehouse:true,project:true,unit:true,notes:true}} defaults={defaults} testidPrefix="mro" itemCreate={can("create","items")?(cb)=>setQuickItem(()=>cb):null} allocationColumn={{header:"Alokasi SPK", render:(l,i)=>{ const s=allocSummary(l); return <button type="button" disabled={!l.item_id} onClick={()=>setAllocLine(lineKey(l))} data-testid={`mro-alloc-cell-${i}`} className={`w-full text-left text-xs rounded-md border px-2 py-1.5 transition-colors hover:bg-accent/50 disabled:opacity-40 disabled:cursor-not-allowed ${s.over?"border-destructive text-destructive":"border-border"}`}>{formatAllocText(s)}{s.over&&" ⚠"}</button>; }}}/>}</CardContent></Card><DocumentMessageEditor module="mro" value={h.document_message} onChange={(v)=>setH({...h,document_message:v})} useDefault={isNew} readOnly={!isNew&&!editing}/></div>{quickItem&&<MasterQuickCreate name="items" open onClose={()=>setQuickItem(null)} onCreated={async(doc)=>{const cb=quickItem;await masters.reload("items");cb(doc.id);}}/>}</DocMetaTabs>
    {allocLine&&(()=>{ const l=lines.find((x)=>lineKey(x)===allocLine); if(!l) return null; return <SpkAllocationModal open onClose={()=>setAllocLine(null)} sourceType="mro" localMode itemQty={toNum(l.qty)} unit={l.unit||l.display_unit} initialAllocations={allocs[allocLine]||[]} canManage={can("spk_allocation:manage")} docStatus="Draft" onLocalSave={(list)=>setAllocs((prev)=>({...prev,[allocLine]:list}))}/>; })()}
    {dialog}
  </div>;
}
