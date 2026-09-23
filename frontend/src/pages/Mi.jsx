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
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { PullDialog } from "@/components/PullDialog";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { num, fmtDate, todayISO } from "@/lib/format";
import { inheritSourceHeader } from "@/lib/sourceInheritance";
import { Save, Printer, ArrowLeft, Download, X } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";

export function MiList(){const[rows,setRows]=useState([]);useEffect(()=>{api.get("/mi").then(r=>setRows(r.data));},[]);return <DocList title="MI — Material Issued" subtitle="Pengeluaran barang dari gudang" createPath="/mi/new" basePath="/mi" testidPrefix="mi" rows={rows} columns={[{key:"no",label:"No. MI",mono:true},{key:"date",label:"Tanggal",render:r=>fmtDate(r.date)},{key:"receiver",label:"Penerima"},{key:"source_type",label:"Sumber"},{key:"line_count",label:"Item",num:true},{key:"status",label:"Status",status:true}]}/>;}

export function MiForm(){
  const{id}=useParams();const nav=useNavigate();const{can}=useAuth();const masters=useMasters();
  const[h,setH]=useState({date:todayISO(),division_id:"",default_warehouse_id:"",default_project_id:"",default_unit_id:"",spk:"",receiver:"",department:"",source_type:"MRO",notes:"",document_message:null});
  const[lines,setLines]=useState([]);const[doc,setDoc]=useState(null);const[pull,setPull]=useState(false);const[editing,setEditing]=useState(false);const isNew=!id;const editable=isNew||editing;
  const load=useCallback(()=>api.get(`/mi/${id}`).then(r=>{setDoc(r.data);setH(r.data);setLines(r.data.lines.map(l=>({...l,_readonly:true})));setEditing(false);}),[id]);
  useEffect(()=>{if(id)load();},[id,load]);
  const beginEdit=()=>{setEditing(true);setLines(cur=>cur.map(l=>({...l,_readonly:false})));};
  const onPull=picked=>{const add=picked.map(p=>({item_id:p.item_id,qty:p._qty,unit:p.unit,uom_id:p.uom_id,conversion_factor:p.conversion_factor||1,warehouse_id:p.warehouse_id||h.default_warehouse_id,project_id:p.project_id||h.default_project_id,unit_id:p.unit_id||h.default_unit_id,_warehouseOverride:!!p.warehouse_id,_projectOverride:!!p.project_id,_unitOverride:!!p.unit_id,notes:"",_locked:true,_sourceHeader:p.source_header||null,_sourceLabel:`MRO: ${p.mro_no} (tersedia ${num(p.available)} ${p.unit||""})`,mro_id:p.mro_id,mro_line_id:p.line_id,sources:[{mro_id:p.mro_id,line_id:p.line_id,qty:p._qty,base_qty:p._qty*(p.conversion_factor||1)}]}));const combined=[...lines,...add];setLines(combined);setH(cur=>inheritSourceHeader(cur,combined));};
  const save=async()=>{try{if(isNew){const res=await api.post("/mi",{...h,lines});await saveDocumentMessage("mi",res.data.id,h.document_message);toast.success("MI diposting, stok berkurang dalam satuan dasar");nav(`/mi/${res.data.id}`);}else{await api.put(`/transactions/mi/${id}`,{...h,lines});await saveDocumentMessage("mi",id,h.document_message);toast.success("MI diperbarui. Sistem membalik stok lama lalu memposting ulang perubahan.");load();}}catch(e){toast.error(apiError(e.response?.data?.detail));}};const ownQty=l=>num(l.display_qty??((Number(l.qty)||0)/(Number(l.conversion_factor)||1))),unitText=l=>l.display_unit||l.unit||"";
  const defaults={warehouse_id:h.default_warehouse_id,project_id:h.default_project_id,unit_id:h.default_unit_id};
  return <div><PageHeader title={isNew?"MI Baru":doc?.no} subtitle={doc&&<StatusBadge status={doc.status}/>}><Button variant="outline" onClick={()=>nav("/mi")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{editable&&h.source_type==="MRO"&&<Button variant="outline" onClick={()=>setPull(true)}><Download className="h-4 w-4 mr-2"/>Tarik MRO</Button>}{!isNew&&!editing&&<TransactionMutationActions module="mi" id={id} onEdit={beginEdit} onDeleted={()=>nav("/mi")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{editable&&can(isNew?"create":"edit")&&<Button onClick={save} disabled={lines.length===0}><Save className="h-4 w-4 mr-2"/>{editing?"Simpan Perubahan":"Posting Pengeluaran"}</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("MI",doc,{title:"MATERIAL ISSUED"})}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</PageHeader>
    <PullDialog open={pull} onClose={()=>setPull(false)} url="/pull/mro-for-mi" title="Tarik MRO — Pilih Item Dikeluarkan" onConfirm={onPull} columns={[{key:"mro_no",label:"MRO",mono:true},{key:"item_code",label:"Kode",mono:true},{key:"item_name",label:"Barang"},{key:"unit",label:"Satuan"},{key:"requested",label:"Request",num:true},{key:"issued",label:"Sudah MI",num:true},{key:"outstanding",label:"Sisa",num:true},{key:"available",label:"Stok",num:true}]}/>
    <DocMetaTabs entity="mi" entityId={id}><div className="space-y-4"><Card><CardContent className="pt-6 space-y-6">{editable&&<Tabs value={h.source_type} onValueChange={v=>{setH({...h,source_type:v});setLines([]);}}><TabsList><TabsTrigger value="MRO">Dari MRO</TabsTrigger><TabsTrigger value="Direct">Direct (Tanpa MRO)</TabsTrigger></TabsList></Tabs>}<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Tanggal"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})} disabled={!editable}/></Field><Field label="Divisi"><Combobox options={masters.opts("divisions",d=>d.name)} value={h.division_id} onChange={v=>setH({...h,division_id:v})} disabled={!editable}/></Field><Field label="Gudang Default"><Combobox options={masters.opts("warehouses",d=>d.name)} value={h.default_warehouse_id} onChange={v=>setH({...h,default_warehouse_id:v})} disabled={!editable}/></Field><DocumentHeaderDefaults h={h} setH={setH} masters={masters} readOnly={!editable}/><Field label="Penerima"><Input value={h.receiver||""} onChange={e=>setH({...h,receiver:e.target.value})} disabled={!editable}/></Field><Field label="Departemen"><Input value={h.department||""} onChange={e=>setH({...h,department:e.target.value})} disabled={!editable}/></Field><Field label="Keterangan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})} disabled={!editable}/></Field></div>
      {editable?<ItemLines lines={lines} onChange={setLines} masters={masters} fields={{warehouse:true,project:true,unit:true,notes:true}} defaults={defaults}/>:<div className="border rounded-md overflow-x-auto"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2">MRO</th><th className="p-2 text-right">Qty</th><th className="p-2">Satuan</th><th className="p-2">Gudang</th><th className="p-2">Proyek</th><th className="p-2">Unit/Aset</th></tr></thead><tbody>{lines.map((l,i)=><tr key={i} className="border-t"><td className="p-2">{l.item_name||l.item_code}</td><td className="p-2 font-mono text-xs">{l.mro_no||"-"}</td><td className="p-2 text-right">{ownQty(l)}</td><td className="p-2">{unitText(l)}</td><td className="p-2">{l.warehouse_name}</td><td className="p-2">{l.project_name||"-"}</td><td className="p-2">{l.unit_name||"-"}</td></tr>)}</tbody></table></div>}</CardContent></Card><DocumentMessageEditor module="mi" value={h.document_message} onChange={v=>setH({...h,document_message:v})} useDefault={isNew} readOnly={!editable}/></div></DocMetaTabs>
  </div>;
}
