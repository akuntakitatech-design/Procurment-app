import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { DocList } from "@/components/DocList";
import { ItemLines } from "@/components/ItemLines";
import { DocMetaTabs } from "@/components/DocMetaTabs";
import { DocumentHeaderDefaults } from "@/components/DocumentHeaderDefaults";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { PageHeader } from "@/components/PageHeader";
import { TransactionProgress } from "@/components/TransactionProgress";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { PullDialog } from "@/components/PullDialog";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { num, fmtDate, todayISO } from "@/lib/format";
import { inheritSourceHeader } from "@/lib/sourceInheritance";
import { Save, Send, Printer, Ban, ArrowLeft, Download, X } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";

export function RoList() {
  const [rows,setRows]=useState([]); useEffect(()=>{api.get("/ro").then(r=>setRows(r.data));},[]);
  return <DocList title="RO — Request Order" subtitle="Permintaan pembelian barang" createPath="/ro/new" basePath="/ro" testidPrefix="ro" rows={rows} columns={[{key:"no",label:"No. RO",mono:true},{key:"date",label:"Tanggal",render:r=>fmtDate(r.date)},{key:"requester",label:"Pemohon"},{key:"division_name",label:"Divisi"},{key:"line_count",label:"Item",num:true},{key:"status",label:"Status",status:true}]}/>;
}

export function RoForm() {
  const {id}=useParams(); const nav=useNavigate(); const {can}=useAuth(); const masters=useMasters();
  const [h,setH]=useState({date:todayISO(),need_date:null,requester:"",department:"",division_id:"",default_warehouse_id:"",default_project_id:"",default_unit_id:"",spk:"",notes:"",document_message:null});
  const [lines,setLines]=useState([]); const [doc,setDoc]=useState(null); const [pull,setPull]=useState(false); const [editing,setEditing]=useState(false); const isNew=!id; const waitingApproval=doc?.approval_status==="Waiting Approval"; const readOnly=!isNew&&!editing;
  const load=useCallback(()=>api.get(`/ro/${id}`).then(r=>{setDoc(r.data);setH(r.data);setLines(r.data.lines.map(l=>({...l,_readonly:true})));setEditing(false);}),[id]); useEffect(()=>{if(id)load();},[id,load]);
  const beginEdit=()=>{setEditing(true);setLines(cur=>cur.map(l=>({...l,_readonly:false})));};
  const onPull=(picked)=>{
    const add=picked.map(p=>({item_id:p.item_id,qty:p._qty,unit:p.unit,uom_id:p.uom_id,conversion_factor:p.conversion_factor||1,warehouse_id:p.warehouse_id||h.default_warehouse_id,project_id:p.project_id||h.default_project_id,unit_id:p.unit_id||h.default_unit_id,_warehouseOverride:!!p.warehouse_id,_projectOverride:!!p.project_id,_unitOverride:!!p.unit_id,notes:"",_locked:true,_sourceHeader:p.source_header||null,_sourceLabel:`MRO: ${p.mro_no}`,sources:[{mro_id:p.mro_id,line_id:p.line_id,qty:p._qty,base_qty:p._qty*(p.conversion_factor||1)}]}));
    const combined=[...lines,...add]; setLines(combined); setH(cur=>inheritSourceHeader(cur,combined));
  };
  const save=async()=>{try{if(isNew){const res=await api.post("/ro",{...h,lines:lines.map(l=>({...l,sources:l.sources||[]}))});await saveDocumentMessage("ro",res.data.id,h.document_message);toast.success("RO tersimpan");nav(`/ro/${res.data.id}`);}else{await api.put(`/transactions/ro/${id}`,{...h,lines});await saveDocumentMessage("ro",id,h.document_message);toast.success("Perubahan RO tersimpan. Approval direset jika sebelumnya sudah disetujui.");load();}}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const doSubmit=async()=>{try{await api.post(`/ro/${id}/submit`);toast.success("RO disubmit");load();}catch(e){toast.error(apiError(e.response?.data?.detail));}}; const doCancel=async()=>{await api.post(`/ro/${id}/cancel`,{});load();};
  const dispQty=(l,v)=>num((Number(v)||0)/(Number(l.conversion_factor)||1)), ownQty=(l)=>num(l.display_qty??((Number(l.qty)||0)/(Number(l.conversion_factor)||1))), unitText=(l)=>l.display_unit||l.unit||"";
  const defaults={warehouse_id:h.default_warehouse_id,project_id:h.default_project_id,unit_id:h.default_unit_id};
  const refs=doc&&<table className="w-full text-sm"><thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2">MRO Asal</th><th className="p-2 text-right">Qty</th><th className="p-2 text-right">Ordered</th><th className="p-2 text-right">Outstanding</th></tr></thead><tbody>{doc.lines.map((l,i)=><tr key={i} className="border-t"><td className="p-2">{l.item_code}</td><td className="p-2 font-mono text-xs">{(l.mro_refs||[]).map(m=>m.no).join(", ")}</td><td className="p-2 text-right">{ownQty(l)} {unitText(l)}</td><td className="p-2 text-right">{dispQty(l,l.ordered)}</td><td className="p-2 text-right font-semibold">{dispQty(l,l.outstanding)}</td></tr>)}</tbody></table>;
  return <div><PageHeader title={isNew?"RO Baru":doc?.no} subtitle={doc&&<StatusBadge status={doc.status}/>}><Button variant="outline" onClick={()=>nav("/ro")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{isNew&&<Button variant={pull?"secondary":"outline"} onClick={()=>setPull(!pull)}><Download className="h-4 w-4 mr-2"/>{pull?"Tutup Sumber":"Tarik MRO"}</Button>}{!isNew&&!editing&&<TransactionMutationActions module="ro" id={id} onEdit={beginEdit} onDeleted={()=>nav("/ro")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{(isNew&&can("create")||editing&&can("edit"))&&<Button onClick={save}><Save className="h-4 w-4 mr-2"/>{editing?"Simpan Perubahan":"Simpan"}</Button>}{!isNew&&!doc?.submitted&&!waitingApproval&&!editing&&can("submit")&&<Button onClick={doSubmit}><Send className="h-4 w-4 mr-2"/>Submit</Button>}{!isNew&&doc&&!doc.cancelled&&!editing&&can("cancel")&&<Button variant="outline" onClick={doCancel}><Ban className="h-4 w-4 mr-2"/>Batalkan</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("RO",doc,{title:"REQUEST ORDER"})}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</PageHeader>
    <TransactionProgress className="mb-4" stages={["Draft","Waiting Approval","Open","Partial Ordered","Fully Ordered"]} status={isNew?"Draft":editing?"Edit":doc?.status}/><PullDialog open={pull} onClose={()=>setPull(false)} url="/pull/mro-for-ro" title="Tarik MRO — Pilih Item Kebutuhan" onConfirm={onPull} columns={[{key:"mro_no",label:"MRO",mono:true},{key:"item_code",label:"Kode",mono:true},{key:"item_name",label:"Barang"},{key:"unit",label:"Satuan"},{key:"requested",label:"Request",num:true},{key:"processed",label:"Diproses",num:true},{key:"outstanding",label:"Sisa",num:true},{key:"warehouse_name",label:"Gudang"}]}/>
    <DocMetaTabs entity="ro" entityId={id} references={refs}><div className="space-y-4"><Card><CardContent className="pt-6 space-y-6"><div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Tanggal"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})}/></Field><Field label="Tanggal Kebutuhan"><DatePicker value={h.need_date} onChange={v=>setH({...h,need_date:v})}/></Field><Field label="Divisi"><Combobox options={masters.opts("divisions",d=>d.name)} value={h.division_id} onChange={v=>setH({...h,division_id:v})}/></Field><Field label="Pemohon"><Input value={h.requester||""} onChange={e=>setH({...h,requester:e.target.value})} disabled={readOnly}/></Field><Field label="Departemen"><Input value={h.department||""} onChange={e=>setH({...h,department:e.target.value})} disabled={readOnly}/></Field><Field label="Gudang Default"><Combobox options={masters.opts("warehouses",d=>d.name)} value={h.default_warehouse_id} onChange={v=>setH({...h,default_warehouse_id:v})} disabled={readOnly}/></Field><DocumentHeaderDefaults h={h} setH={setH} masters={masters} readOnly={readOnly}/><Field label="Keterangan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})} disabled={readOnly}/></Field></div>
      {readOnly?<div className="border rounded-md overflow-x-auto"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2 text-right">Qty</th><th className="p-2 text-right">Ordered</th><th className="p-2 text-right">Outstanding</th></tr></thead><tbody>{lines.map((l,i)=><tr key={i} className="border-t"><td className="p-2">{l.item_code} — {l.item_name}</td><td className="p-2 text-right">{ownQty(l)} {unitText(l)}</td><td className="p-2 text-right">{dispQty(l,l.ordered)}</td><td className="p-2 text-right font-semibold">{dispQty(l,l.outstanding)}</td></tr>)}</tbody></table></div>:<ItemLines lines={lines} onChange={setLines} masters={masters} fields={{warehouse:true,project:true,unit:true,notes:true}} defaults={defaults}/>}</CardContent></Card><DocumentMessageEditor module="ro" value={h.document_message} onChange={v=>setH({...h,document_message:v})} useDefault={isNew} readOnly={readOnly}/></div></DocMetaTabs>
  </div>;
}
