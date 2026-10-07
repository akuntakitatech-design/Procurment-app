import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { DocList } from "@/components/DocList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";
import { ItemLines } from "@/components/ItemLines";
import { DocMetaTabs } from "@/components/DocMetaTabs";
import { uploadPendingAttachments } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { TransactionProgress } from "@/components/TransactionProgress";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox, MasterUnitCombobox } from "@/components/MasterRefCombobox";
import { inlinePrefill, projectOption, unitOption } from "@/lib/masterInline";
import { DivisionField } from "@/components/DivisionField";
import { divisionError, lineQtyError } from "@/lib/txnValidation";
import { StatusBadge } from "@/components/StatusBadge";
import { RoSourcePickerDialog, RoConsolidatedTable, mergePicked, fromSavedLine, toPayloadLine, lineIsValid } from "@/components/ro/RoConsolidation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { num, fmtDate, todayISO } from "@/lib/format";
import { inheritSourceHeader } from "@/lib/sourceInheritance";
import { Save, Send, Printer, Ban, ArrowLeft, Download, X } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";
import { SpkAllocationModal, useDocAllocations, formatAllocText } from "@/components/SpkAllocationModal";
import { useCompletenessWarning } from "@/components/CompletenessWarningDialog";
import { buildTxnWarnings, HEADER_FIELDS, ITEM_FIELDS } from "@/lib/validation";

export function RoList() {
  const list=useServerList("/ro"); const load=()=>list.reload();
  return <DocList txType="ro" createPath="/ro/new" basePath="/ro" module="ro" printType="RO" printOpts={{title:"REQUEST ORDER"}} onReload={load} testidPrefix="ro" server={list} minWidth={1200} columns={[noCol("No. RO"),dateCol(fmtDate),{key:"requester",label:"Pemohon"},traceCol("mro"),traceCol("project"),{key:"division_name",label:"Divisi"},traceCol("spk"),{key:"line_count",label:"Item",num:true},{key:"status",label:"Status",status:true}]}/>;
}

export function RoForm() {
  const {id}=useParams(); const nav=useNavigate(); const {can}=useAuth(); const masters=useMasters();
  const [h,setH]=useState({date:todayISO(),need_date:todayISO(),requester:"",department:"",division_id:"",default_warehouse_id:"",default_project_id:"",default_unit_id:"",spk:"",notes:"",document_message:null});
  const [lines,setLines]=useState([]); const [doc,setDoc]=useState(null); const [pull,setPull]=useState(false); const [editing,setEditing]=useState(false); const isNew=!id; const waitingApproval=doc?.approval_status==="Waiting Approval"; const readOnly=!isNew&&!editing;
  const alloc=useDocAllocations("ro",id); const [allocLine,setAllocLine]=useState(null);
  const [pending,setPending]=useState([]); // in-memory attachments chosen before first save
  const { confirm, dialog } = useCompletenessWarning();
  const consAllocCell=(l,i,sk)=>{
    if(readOnly&&l.id){const st=alloc.map[l.id]; return <button type="button" onClick={()=>setAllocLine(l.id)} data-testid={`ro-alloc-cell-${i}`} className={`w-full text-left text-xs rounded-md border px-2 py-1.5 transition-colors hover:bg-accent/50 ${st?.is_over?"border-destructive text-destructive":"border-border"}`}>{formatAllocText(st)}</button>;}
    return <span data-testid={`ro-alloc-inherit-${i}`} title={`Diwarisi dari MRO sesuai rincian sumber saat simpan. ${sk.title}`} className="text-xs text-muted-foreground">{sk.text}</span>;
  };
  const hasPreview=(p)=>p&&((p.allocations&&p.allocations.length)||Number(p.non_spk_qty||0)>1e-9);
  const allocCell=(l,i)=>{
    if(!l.id){ // unsaved RO line: show inherited-from-MRO preview (read-only)
      if(hasPreview(l._inheritPreview)) return <div data-testid={`ro-alloc-inherit-${i}`} title="Diwarisi dari MRO — read-only sebelum simpan" className="w-full text-left text-xs rounded-md border border-dashed border-border bg-muted/30 px-2 py-1.5 text-muted-foreground">{formatAllocText(l._inheritPreview)}</div>;
      return <span className="text-xs italic text-muted-foreground">Diwarisi saat simpan</span>;
    }
    const s=alloc.map[l.id]; return <button type="button" onClick={()=>setAllocLine(l.id)} data-testid={`ro-alloc-cell-${i}`} className={`w-full text-left text-xs rounded-md border px-2 py-1.5 transition-colors hover:bg-accent/50 ${s?.is_over?"border-destructive text-destructive":"border-border"}`}>{formatAllocText(s)}</button>;
  };
  const [trackVer,setTrackVer]=useState(0); // dinaikkan setelah simpan/submit/batal sukses -> panel Tracking dimuat ulang
  const load=useCallback(()=>api.get(`/ro/${id}`).then(r=>{setDoc(r.data);setH(r.data);setLines(r.data.lines.map(fromSavedLine));setEditing(false);}),[id]);
  const reloadAfterMutation=()=>load().then(()=>setTrackVer(v=>v+1)); useEffect(()=>{if(id)load();},[id,load]);
  const beginEdit=()=>{setEditing(true);setLines(cur=>cur.map(l=>({...l,_readonly:false})));};
  // Konsolidasi: baris bersumber MRO (Divisi + Barang) vs baris manual (tanpa MRO)
  const consLines=lines.filter(l=>l._consolidated), manualLines=lines.filter(l=>!l._consolidated);
  const setConsLines=(next)=>setLines([...next,...manualLines]); const setManualLines=(next)=>setLines([...consLines,...next]);
  const divisionName=masters.map("divisions")[h.division_id]?.name;
  const onPull=(picked)=>{
    if(!picked.length) return;
    const div=h.division_id||picked[0].division_id;
    if(picked.some(g=>g.division_id!==div)){toast.error("Satu RO hanya untuk satu Divisi.");return;}
    const merged=mergePicked(consLines,picked,{warehouse_id:h.default_warehouse_id});
    setLines([...merged,...manualLines]);
    setH(cur=>({...inheritSourceHeader(cur,picked.flatMap(g=>g.sources.map(s=>({source_header:s.source_header})))),division_id:div}));
  };
  const doSave=async()=>{
    const bad=consLines.findIndex(l=>!lineIsValid(l));
    if(bad>=0){toast.error(`Baris ${consLines[bad].item_code||bad+1}: Qty RO harus > 0, sama dengan total Rincian alokasi sumber, dan tidak melebihi sisa MRO.`);return;}
    try{
    const payloadLines=lines.map(toPayloadLine);
    if(isNew){
      const res=await api.post("/ro",{...h,lines:payloadLines});
      const rid=res.data.id;
      await saveDocumentMessage("ro",rid,h.document_message);
      let failed=[];
      if(pending.length){ const up=await uploadPendingAttachments("ro",rid,pending); failed=up.failed; setPending(failed); }
      if(failed.length) toast.error(`RO berhasil disimpan sebagai Draft, tetapi lampiran "${failed.map(f=>f.name).join(", ")}" gagal diunggah. Silakan coba kembali.`);
      else toast.success("RO tersimpan");
      nav(`/ro/${rid}`);
    } else {
      await api.put(`/transactions/ro/${id}`,{...h,lines:payloadLines});await saveDocumentMessage("ro",id,h.document_message);toast.success("Perubahan RO tersimpan. Approval direset jika sebelumnya sudah disetujui.");reloadAfterMutation();
    }
  }catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const [divErr,setDivErr]=useState(null);
  const save=()=>{const de=divisionError(h.division_id);if(de){setDivErr(de);toast.error(de);return;}setDivErr(null);const qe=lineQtyError(lines);if(qe){toast.error(qe);return;}confirm(buildTxnWarnings({h,lines,headerFields:HEADER_FIELDS.ro,itemFields:ITEM_FIELDS.ro}),doSave);};
  const doSubmit=async()=>{try{await api.post(`/ro/${id}/submit`);toast.success("RO disubmit");reloadAfterMutation();}catch(e){toast.error(apiError(e.response?.data?.detail));}}; const doCancel=async()=>{await api.post(`/ro/${id}/cancel`,{});reloadAfterMutation();};
  const dispQty=(l,v)=>num((Number(v)||0)/(Number(l.conversion_factor)||1)), ownQty=(l)=>num(l.display_qty??((Number(l.qty)||0)/(Number(l.conversion_factor)||1))), unitText=(l)=>l.display_unit||l.unit||"";
  const defaults={warehouse_id:h.default_warehouse_id,project_id:h.default_project_id,unit_id:h.default_unit_id};
  const projectOpts=(masters.data.projects||[]).map(projectOption); const unitOpts=(masters.data.units||[]).map(unitOption);
  const refs=doc&&<table className="w-full text-sm"><thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2">MRO Asal</th><th className="p-2 text-right">Qty</th><th className="p-2 text-right">Ordered</th><th className="p-2 text-right">Outstanding</th></tr></thead><tbody>{doc.lines.map((l,i)=><tr key={i} className="border-t"><td className="p-2">{l.item_code}</td><td className="p-2 font-mono text-xs">{(l.mro_refs||[]).map(m=>m.no).join(", ")}</td><td className="p-2 text-right">{ownQty(l)} {unitText(l)}</td><td className="p-2 text-right">{dispQty(l,l.ordered)}</td><td className="p-2 text-right font-semibold">{dispQty(l,l.outstanding)}</td></tr>)}</tbody></table>;
  return <div><TransactionPageHeader type="ro" mode={isNew?"new":!doc?null:editing?"edit":"view"} number={doc?.no} showNumberField subtitle={doc&&<StatusBadge status={doc.status}/>}><Button variant="outline" onClick={()=>nav("/ro")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{(isNew||editing)&&<Button variant="outline" onClick={()=>setPull(true)} data-testid="ro-pull-mro-btn"><Download className="h-4 w-4 mr-2"/>Tarik MRO</Button>}{!isNew&&!editing&&<TransactionMutationActions module="ro" id={id} ready={!!doc} onEdit={beginEdit} onDeleted={()=>nav("/ro")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{(isNew&&can("create")||editing&&can("edit"))&&<Button onClick={save}><Save className="h-4 w-4 mr-2"/>{editing?"Simpan Perubahan":"Simpan"}</Button>}{!isNew&&!doc?.submitted&&!waitingApproval&&!editing&&can("submit")&&<Button onClick={doSubmit}><Send className="h-4 w-4 mr-2"/>Submit</Button>}{!isNew&&doc&&!doc.cancelled&&!editing&&can("cancel")&&<Button variant="outline" onClick={doCancel}><Ban className="h-4 w-4 mr-2"/>Batalkan</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("RO",doc,{title:"REQUEST ORDER"})}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</TransactionPageHeader>
    <TransactionProgress className="mb-4" stages={["Draft","Waiting Approval","Open","Partial Ordered","Fully Ordered"]} status={isNew?"Draft":editing?"Edit":doc?.status}/><RoSourcePickerDialog open={pull} onClose={()=>setPull(false)} divisionId={h.division_id} onConfirm={onPull} formLines={consLines} currentDocId={isNew?null:id}/>
    <DocMetaTabs entity="ro" entityId={id} lifecycleRefreshKey={trackVer} references={refs} attachmentPending={pending} onAttachmentPendingChange={setPending}><div className="space-y-4"><Card><CardContent className="pt-6 space-y-4"><div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Pemohon"><Input value={h.requester||""} onChange={e=>setH({...h,requester:e.target.value})} disabled={readOnly}/></Field><Field label="Tanggal"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})}/></Field><Field label="Tanggal Kebutuhan"><DatePicker value={h.need_date} onChange={v=>setH({...h,need_date:v})}/></Field><DivisionField testid="ro-division-field" options={masters.opts("divisions",d=>d.name)} value={h.division_id} onChange={v=>{setH({...h,division_id:v});setDivErr(null);}} disabled={readOnly} locked={consLines.length>0} lockedHint="Divisi mengikuti MRO sumber. Hapus baris MRO untuk mengganti Divisi." error={divErr}/></div><div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Proyek Default"><MasterProjectCombobox masters={masters} options={projectOpts} value={h.default_project_id||""} onChange={v=>setH(s=>({...s,default_project_id:v}))} disabled={readOnly} testid="ro-hdr-project"/></Field><Field label="Gudang Default"><Combobox options={masters.opts("warehouses",d=>d.name)} value={h.default_warehouse_id} onChange={v=>setH({...h,default_warehouse_id:v})} disabled={readOnly}/></Field><Field label="Unit/Aset Default"><MasterUnitCombobox masters={masters} options={unitOpts} value={h.default_unit_id||""} onChange={v=>setH(s=>({...s,default_unit_id:v}))} disabled={readOnly} prefill={()=>inlinePrefill("units",{division_id:h.division_id})} testid="ro-hdr-unit"/></Field><Field label="Keterangan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})} disabled={readOnly}/></Field></div>
      {(consLines.length>0||!readOnly)&&<div className="space-y-2" data-testid="ro-consolidated-section"><div className="flex items-center justify-between"><h3 className="font-head text-sm font-semibold">Kebutuhan dari MRO (terkonsolidasi per Divisi + Barang)</h3>{!readOnly&&<span className="text-xs text-muted-foreground">Qty dalam satuan dasar barang</span>}</div>
        <RoConsolidatedTable lines={consLines} onChange={setConsLines} readOnly={readOnly} divisionName={divisionName} allocCell={consAllocCell} extraCols={readOnly?{head:<><th className="p-2 text-right">Ordered</th><th className="p-2 text-right">Outstanding</th><th className="p-2">Status PO</th></>,cells:(l,i)=><><td className="p-2 text-right tabular-nums">{num(l.ordered)}</td><td className="p-2 text-right font-semibold tabular-nums">{num(l.outstanding)}</td><td className="p-2" data-testid={`ro-line-po-status-${i}`}>{l.po_status?<StatusBadge status={l.po_status}/>:"-"}</td></>}:null}/></div>}
      {readOnly?(manualLines.length>0&&<div className="space-y-2"><h3 className="font-head text-sm font-semibold">Barang tanpa sumber MRO</h3><div className="border rounded-md overflow-x-auto"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2">Keterangan</th><th className="p-2 text-right">Qty</th><th className="p-2 text-right">Ordered</th><th className="p-2 text-right">Outstanding</th><th className="p-2">Alokasi SPK</th></tr></thead><tbody>{manualLines.map((l,i)=><tr key={i} className="border-t"><td className="p-2">{l.item_code} — {l.item_name}</td><td className="p-2">{l.notes||"-"}</td><td className="p-2 text-right">{ownQty(l)} {unitText(l)}</td><td className="p-2 text-right">{dispQty(l,l.ordered)}</td><td className="p-2 text-right font-semibold">{dispQty(l,l.outstanding)}</td><td className="p-2 text-xs" data-testid={`ro-alloc-view-${i}`}>{formatAllocText(alloc.map[l.id])}</td></tr>)}</tbody></table></div></div>):<div className="space-y-2"><h3 className="font-head text-sm font-semibold">Barang Tambahan (tanpa sumber MRO)</h3><ItemLines lines={manualLines} onChange={setManualLines} masters={masters} fields={{warehouse:true,project:true,unit:true,notes:true}} defaults={defaults} division={h.division_id} allocationColumn={{header:"Alokasi SPK",render:allocCell}} testidPrefix="ro"/></div>}</CardContent></Card><DocumentMessageEditor module="ro" value={h.document_message} onChange={v=>setH({...h,document_message:v})} useDefault={isNew} readOnly={readOnly}/></div></DocMetaTabs>
    {allocLine&&<SpkAllocationModal open onClose={()=>setAllocLine(null)} sourceType="ro" lineId={allocLine} docStatus={doc?.status} canManage={alloc.canManage} onChanged={()=>{alloc.reload();}}/>}
    {dialog}
  </div>;
}
