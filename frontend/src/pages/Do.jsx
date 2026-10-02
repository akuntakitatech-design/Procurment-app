import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { DocList } from "@/components/DocList";
import { DocMetaTabs } from "@/components/DocMetaTabs";
import { AttachmentPanel, uploadPendingAttachments } from "@/components/DocMeta";
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NumericInput } from "@/components/NumericInput";
import { num, fmtDate, todayISO } from "@/lib/format";
import { inheritSourceHeader } from "@/lib/sourceInheritance";
import { Save, Printer, ArrowLeft, Download, Trash2, X, Info, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";
import { SpkAllocationModal, useDocAllocations, formatAllocText } from "@/components/SpkAllocationModal";
import { useCompletenessWarning } from "@/components/CompletenessWarningDialog";
import { buildTxnWarnings, HEADER_FIELDS, ITEM_FIELDS } from "@/lib/validation";

export function DoList(){const[rows,setRows]=useState([]);useEffect(()=>{api.get("/do").then(r=>setRows(r.data));},[]);return <DocList title="DO — Penerimaan Barang" subtitle="Penerimaan fisik barang dari supplier" createPath="/do/new" basePath="/do" testidPrefix="do" rows={rows} columns={[{key:"no",label:"No. DO",mono:true},{key:"date",label:"Tanggal",render:r=>fmtDate(r.date)},{key:"supplier_name",label:"Supplier"},{key:"supplier_invoice",label:"No. Faktur"},{key:"line_count",label:"Item",num:true},{key:"status",label:"Status",status:true}]}/>;}

const LBL = "mb-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground";

export function DoForm(){
  const{id}=useParams();const nav=useNavigate();const{can}=useAuth();const masters=useMasters();
  const[h,setH]=useState({date:todayISO(),supplier_id:"",supplier_dn:"",supplier_invoice:"",invoice_date:null,default_warehouse_id:"",default_project_id:"",default_unit_id:"",spk:"",receiver:"",notes:"",document_message:null});
  const[lines,setLines]=useState([]);const[doc,setDoc]=useState(null);const[pull,setPull]=useState(false);const[editing,setEditing]=useState(false);const isNew=!id;const editable=isNew||editing;
  const[pending,setPending]=useState([]); // attachments chosen before first save
  const alloc=useDocAllocations("do",id);const[allocLine,setAllocLine]=useState(null);
  const { confirm, dialog } = useCompletenessWarning();
  const items=masters.map("items"),uoms=masters.map("uoms"); const uomLabel=uid=>{const u=uoms[uid];return u?(u.symbol||u.name||u.code):"";};
  const uomOptions=itemId=>{const it=items[itemId];if(!it?.base_uom_id)return[];return[{uom_id:it.base_uom_id,factor:1,is_base:true},...(it.uoms||[]).filter(x=>x.uom_id!==it.base_uom_id)].map(r=>{const u=uoms[r.uom_id]||{},short=u.symbol||u.name||u.code||"Satuan";return{value:r.uom_id,factor:Number(r.factor)||1,label:`${u.name||u.code||"Satuan"}${u.symbol?` (${u.symbol})`:""}${r.is_base?" — Dasar":` — 1 = ${num(r.factor)} ${uomLabel(it.base_uom_id)}`}`,selectedLabel:short,unit:short};});};
  const whOpts=(masters.data.warehouses||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}${d.location?` · ${d.location}`:""}`,selectedLabel:d.name}));
  const projOpts=(masters.data.projects||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}${d.pic?` · PIC ${d.pic}`:""}`,selectedLabel:d.name}));
  const unitOpts=(masters.data.units||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}${d.plate_no?` (${d.plate_no})`:""}${d.asset_no?` · Asset ${d.asset_no}`:""}`,selectedLabel:d.plate_no||d.name}));
  const conditionOpts=[{value:"Baik",label:"Baik"},{value:"Rusak",label:"Rusak"},{value:"Kurang",label:"Kurang"},{value:"Lebih",label:"Lebih"}];
  const load=useCallback(()=>api.get(`/do/${id}`).then(r=>{setDoc(r.data);setH(r.data);setLines(r.data.lines.map(l=>({...l,exception_qty:Number(l.exception_qty)||0,_readonly:true})));setEditing(false);}),[id]);
  useEffect(()=>{if(id)load();},[id,load]);
  const beginEdit=()=>{setEditing(true);setLines(cur=>cur.map(l=>({...l,_readonly:false,exception_qty:Number(l.exception_qty)||0,sources:l.po_line_id?[{po_id:l.po_id,line_id:l.po_line_id,qty:l.qty,base_qty:l.qty}]:[]})));};
  const setHeader=(next)=>{const n=typeof next==="function"?next(h):next;const changed=["default_project_id","default_unit_id"].filter(k=>(n[k]||"")!==(h[k]||""));if(changed.length)setLines(cur=>cur.map(l=>{const x={...l};changed.forEach(k=>{const field=k==="default_project_id"?"project_id":"unit_id",flag=k==="default_project_id"?"_projectOverride":"_unitOverride";if(!x[flag]&&(!x[field]||x[field]===h[k]))x[field]=n[k]||"";});return x;}));setH(n);};
  const changeWarehouse=v=>{const old=h.default_warehouse_id;setH({...h,default_warehouse_id:v});setLines(cur=>cur.map(l=>(!l._warehouseOverride&&(!l.warehouse_id||l.warehouse_id===old)?{...l,warehouse_id:v}:l)));};
  const onPull=picked=>{const add=picked.map(p=>({po_id:p.po_id,po_line_id:p.line_id,po_no:p.po_no,item_id:p.item_id,item_code:p.item_code,item_name:p.item_name,unit:p.unit,uom_id:p.uom_id,conversion_factor:p.conversion_factor||1,qty_po:p.qty_po,received_before:p.received,outstanding:p.outstanding,qty:p._qty,warehouse_id:p.warehouse_id||h.default_warehouse_id,project_id:p.project_id||h.default_project_id,unit_id:p.unit_id||h.default_unit_id,_warehouseOverride:!!p.warehouse_id,_projectOverride:!!p.project_id,_unitOverride:!!p.unit_id,_sourceHeader:p.source_header||null,condition:"Baik",exception_qty:0,notes:"",sources:[{po_id:p.po_id,line_id:p.line_id,qty:p._qty,base_qty:p._qty*(p.conversion_factor||1)}]}));const combined=[...lines,...add];setLines(combined);setH(cur=>inheritSourceHeader(cur,combined));};
  const upd=(i,patch)=>setLines(cur=>cur.map((l,x)=>{if(x!==i)return l;if(patch.uom_id!==undefined){const s=uomOptions(l.item_id).find(o=>o.value===patch.uom_id),oldF=Number(l.conversion_factor)||1,newF=Number(s?.factor)||1,base=(Number(l.qty)||0)*oldF,excBase=(Number(l.exception_qty)||0)*oldF;return{...l,uom_id:patch.uom_id,conversion_factor:newF,unit:s?.unit||l.unit,qty:base/newF,exception_qty:excBase/newF};}const n={...l,...patch};if(patch.condition==="Baik")n.exception_qty=0;if(patch.warehouse_id!==undefined)n._warehouseOverride=true;if(patch.project_id!==undefined)n._projectOverride=true;if(patch.unit_id!==undefined)n._unitOverride=true;if(patch.qty!==undefined&&n.sources?.length===1)n.sources=[{...n.sources[0],qty:Number(patch.qty)||0,base_qty:(Number(patch.qty)||0)*(Number(n.conversion_factor)||1)}];return n;}));
  const doSave=async()=>{try{if(isNew){const res=await api.post("/do",{...h,lines});const did=res.data.id;await saveDocumentMessage("do",did,h.document_message);let failed=[];if(pending.length){const up=await uploadPendingAttachments("do",did,pending);failed=up.failed;setPending(failed);}if(failed.length)toast.error(`DO diposting, tetapi lampiran "${failed.map(f=>f.name).join(", ")}" gagal diunggah. Silakan coba kembali.`);else toast.success("DO diposting dan kondisi penerimaan tercatat");nav(`/do/${did}`);}else{await api.put(`/transactions/do/${id}`,{...h,lines});await saveDocumentMessage("do",id,h.document_message);toast.success("DO diperbarui. Stok dan kondisi penerimaan dihitung ulang.");load();}}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const save=()=>confirm(buildTxnWarnings({h,lines,headerFields:HEADER_FIELDS.do,itemFields:ITEM_FIELDS.do}),doSave);
  const ownQty=l=>num(l.display_qty??((Number(l.qty)||0)/(Number(l.conversion_factor)||1))),unitText=l=>l.display_unit||l.unit||"";
  const exceptionLabel=l=>l.condition==="Rusak"?"Qty Rusak":l.condition==="Kurang"?"Qty Kurang":l.condition==="Lebih"?"Qty Lebih":"-";
  const numOrDash=v=>(v===undefined||v===null||v==="")?"—":num(v);

  const UomCell=({l,i})=>(
    <div className="flex items-center gap-1">
      <div className="min-w-0 flex-1"><Combobox dense options={uomOptions(l.item_id)} value={l.uom_id||items[l.item_id]?.base_uom_id||""} onChange={v=>upd(i,{uom_id:v})} disabled={!l.item_id||uomOptions(l.item_id).length<=1}/></div>
      {l.item_id&&<Popover><PopoverTrigger asChild><button type="button" className="shrink-0 text-muted-foreground transition-colors hover:text-primary" title="Konversi Stok" data-testid={`do-uom-info-${i}`}><Info className="h-4 w-4"/></button></PopoverTrigger><PopoverContent align="end" className="w-60 text-xs"><div className="space-y-1"><div className="font-semibold">Konversi Stok</div><div className="flex justify-between gap-3"><span className="text-muted-foreground">Satuan transaksi</span><span className="font-medium">{num(l.qty)} {l.unit||""}</span></div>{(Number(l.conversion_factor)||1)!==1&&<div className="flex justify-between gap-3"><span className="text-muted-foreground">Faktor konversi</span><span>1 {l.unit||""} = {num(l.conversion_factor)} {uomLabel(items[l.item_id]?.base_uom_id)}</span></div>}<div className="flex justify-between gap-3 border-t pt-1"><span className="text-muted-foreground">Terhitung stok</span><span className="font-semibold">{num((Number(l.qty)||0)*(Number(l.conversion_factor)||1))} {uomLabel(items[l.item_id]?.base_uom_id)}</span></div></div></PopoverContent></Popover>}
    </div>
  );

  const allocCell=(l,i)=>(!l.id
    ? <span className="text-xs italic text-muted-foreground" data-testid={`do-alloc-inherit-${i}`}>Diwarisi saat simpan</span>
    : <button type="button" onClick={()=>setAllocLine(l.id)} data-testid={`do-alloc-cell-${i}`} className={`w-full text-left text-xs rounded-md border px-2 py-1.5 transition-colors hover:bg-accent/50 ${alloc.map[l.id]?.is_over?"border-destructive text-destructive":"border-border"}`}>{formatAllocText(alloc.map[l.id])}</button>);

  const head=[["w-[190px]","Barang"],["w-[150px]","Keterangan"],["w-[80px]","Qty PO"],["w-[90px]","Sebelumnya"],["w-[80px]","Sisa"],["w-[100px]","Qty Terima"],["w-[120px]","Satuan"],["w-[120px]","Kondisi"],["w-[110px]","Qty Selisih"],["w-[40px]",""]];

  const ConditionHelp=()=>(
    <Popover><PopoverTrigger asChild><button type="button" className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-primary" data-testid="do-condition-help"><Info className="h-3.5 w-3.5"/>Panduan Kondisi Penerimaan</button></PopoverTrigger><PopoverContent align="start" className="w-80 text-xs"><div className="space-y-1.5"><div className="font-semibold">Kondisi Penerimaan</div><p><b>Baik</b> — masuk stok normal.</p><p><b>Rusak</b> — mengurangi stok usable sesuai Qty Rusak.</p><p><b>Kurang</b> — mencatat selisih; PO tetap outstanding.</p><p><b>Lebih</b> — mencatat barang fisik berlebih tanpa menambah stok/PO melebihi pesanan.</p></div></PopoverContent></Popover>
  );

  return <div><PageHeader title={isNew?"DO Baru":doc?.no} subtitle={doc&&<StatusBadge status={doc.status}/>}><Button variant="outline" onClick={()=>nav("/do")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{editable&&<Button variant="outline" onClick={()=>setPull(true)}><Download className="h-4 w-4 mr-2"/>Tarik PO</Button>}{!isNew&&!editing&&<TransactionMutationActions module="do" id={id} onEdit={beginEdit} onDeleted={()=>nav("/do")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{editable&&can(isNew?"create":"edit")&&<Button onClick={save} disabled={lines.length===0}><Save className="h-4 w-4 mr-2"/>{editing?"Simpan Perubahan":"Posting Penerimaan"}</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("DO",doc,{title:"PENERIMAAN BARANG"})}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</PageHeader>
    <PullDialog open={pull} onClose={()=>setPull(false)} url={`/pull/po-for-do${h.supplier_id?"?supplier_id="+h.supplier_id:""}`} title="Tarik PO — Pilih Item Diterima" onConfirm={onPull} columns={[{key:"po_no",label:"PO",mono:true},{key:"supplier_name",label:"Supplier"},{key:"item_code",label:"Kode",mono:true},{key:"item_name",label:"Barang"},{key:"unit",label:"Satuan"},{key:"qty_po",label:"Qty PO",num:true},{key:"received",label:"Diterima",num:true},{key:"outstanding",label:"Sisa",num:true}]}/>
    <DocMetaTabs entity="do" entityId={id} hideAttachments><div className="space-y-4"><Card><CardContent className="pt-6 space-y-6">
      {/* HEADER — Row 1 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Tanggal Penerimaan"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})} disabled={!editable}/></Field><Field label="Supplier"><Combobox options={masters.opts("suppliers",d=>d.name)} value={h.supplier_id} onChange={v=>setH({...h,supplier_id:v})} disabled={!editable}/></Field><Field label="No. Surat Jalan"><Input value={h.supplier_dn||""} onChange={e=>setH({...h,supplier_dn:e.target.value})} disabled={!editable} data-testid="do-surat-jalan"/></Field><Field label="No. Faktur (opsional)"><Input value={h.supplier_invoice||""} onChange={e=>setH({...h,supplier_invoice:e.target.value})} disabled={!editable}/></Field></div>
      {/* HEADER — Row 2 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Gudang Default"><Combobox options={whOpts} value={h.default_warehouse_id} onChange={changeWarehouse} disabled={!editable}/></Field><DocumentHeaderDefaults h={h} setH={setHeader} masters={masters} readOnly={!editable} hideSpk/><Field label="Petugas Penerima"><Input value={h.receiver||""} onChange={e=>setH({...h,receiver:e.target.value})} disabled={!editable}/></Field></div>
      {/* HEADER — Row 3 */}
      <div className="grid grid-cols-1 gap-4"><Field label="Catatan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})} disabled={!editable}/></Field></div>

      {/* ATTACHMENTS — before item table */}
      <div className="rounded-lg border bg-muted/10 p-4"><div className="mb-3 flex items-center gap-2"><Paperclip className="h-4 w-4 text-muted-foreground"/><h3 className="font-head text-sm font-semibold">Lampiran Penerimaan</h3></div><AttachmentPanel entity="do" entityId={id} pending={pending} onPendingChange={setPending}/></div>

      {/* ITEM TABLE — compact 2-row (receiving) */}
      <div className="flex items-center justify-between"><h3 className="font-head text-sm font-semibold">Item Diterima</h3><ConditionHelp/></div>
      <div className="overflow-x-auto rounded-md border bg-card shadow-sm"><div className="min-w-[1180px]">
        <div className="flex items-stretch gap-1.5 border-b bg-muted px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{head.map(([w,t],k)=><div key={k} className={w+" shrink-0"+((t==="Qty PO"||t==="Sebelumnya"||t==="Sisa")?" text-right":"")}>{t}</div>)}{editable&&<div className="w-[40px] shrink-0"/>}</div>
        {lines.length===0&&<div className="p-6 text-center text-sm text-muted-foreground">Tarik PO untuk menambah item</div>}
        {lines.map((l,i)=><div key={i} className="border-b px-3 py-2.5 last:border-b-0" data-testid={`do-item-block-${i}`}>
          {/* ROW 1 — Receiving */}
          <div className="flex items-center gap-1.5">
            <div className="w-[190px] shrink-0 text-sm font-medium">{l.item_name||l.item_code||"-"}</div>
            <div className="w-[150px] shrink-0">{editable?<Input value={l.notes||""} onChange={e=>upd(i,{notes:e.target.value})} className="h-9 text-sm" placeholder="Keterangan" data-testid={`do-notes-${i}`}/>:<span className="text-sm text-muted-foreground">{l.notes||"-"}</span>}</div>
            <div className="w-[80px] shrink-0 text-right text-sm tabular-nums">{numOrDash(l.qty_po)}</div>
            <div className="w-[90px] shrink-0 text-right text-sm tabular-nums">{numOrDash(l.received_before)}</div>
            <div className="w-[80px] shrink-0 text-right text-sm font-medium tabular-nums">{numOrDash(l.outstanding)}</div>
            <div className="w-[100px] shrink-0">{editable?<NumericInput mode="quantity" value={l.qty} onChange={v=>upd(i,{qty:v})} className="h-9 text-right" data-testid={`do-qty-${i}`}/>:<div className="text-right text-sm tabular-nums">{ownQty(l)}</div>}</div>
            <div className="w-[120px] shrink-0">{editable?<UomCell l={l} i={i}/>:<span className="text-sm">{unitText(l)}</span>}</div>
            <div className="w-[120px] shrink-0">{editable?<Combobox dense options={conditionOpts} value={l.condition||"Baik"} onChange={v=>upd(i,{condition:v})} testid={`do-condition-${i}`}/>:<span className="text-sm">{l.condition||"Baik"}</span>}</div>
            <div className="w-[110px] shrink-0">{editable?(l.condition&&l.condition!=="Baik"?<div><NumericInput mode="quantity" value={l.exception_qty} onChange={v=>upd(i,{exception_qty:v})} className="h-9 text-right" data-testid={`do-exception-${i}`}/><div className="mt-0.5 text-[10px] text-muted-foreground">{exceptionLabel(l)}</div></div>:<div className="flex h-9 items-center justify-end text-muted-foreground">-</div>):(Number(l.exception_qty)>0?<div className="text-right text-sm"><div className="tabular-nums">{num(l.exception_qty)}</div><div className="text-[10px] text-muted-foreground">{exceptionLabel(l)}</div></div>:<div className="text-right text-muted-foreground">-</div>)}</div>
            {editable&&<div className="w-[40px] shrink-0"><Button variant="ghost" size="icon" className="h-9 w-9" onClick={()=>setLines(lines.filter((_,x)=>x!==i))} data-testid={`do-remove-${i}`}><Trash2 className="h-4 w-4 text-destructive"/></Button></div>}
          </div>
          {/* ROW 2 — Reference & Operational */}
          <div className="mt-2 flex items-end gap-2">
            <div className="w-[150px]"><div className={LBL}>PO</div><div className="flex h-9 items-center truncate font-mono text-[11px] text-muted-foreground" data-testid={`do-po-ref-${i}`}>{l.po_no||<span className="italic">—</span>}</div></div>
            <div className="w-[230px]"><div className={LBL}>Alokasi SPK</div><div data-testid={`do-alloc-${i}`}>{allocCell(l,i)}</div></div>
            <div className="w-[150px]"><div className={LBL}>Gudang</div>{editable?<Combobox options={whOpts} value={l.warehouse_id||""} onChange={v=>upd(i,{warehouse_id:v})} placeholder="Gudang"/>:<div className="flex h-9 items-center text-sm text-muted-foreground">{l.warehouse_name||"-"}</div>}</div>
            <div className="w-[150px]"><div className={LBL}>Proyek</div>{editable?<Combobox options={projOpts} value={l.project_id||""} onChange={v=>upd(i,{project_id:v})} placeholder="Proyek"/>:<div className="flex h-9 items-center text-sm text-muted-foreground">{l.project_name||"-"}</div>}</div>
            <div className="w-[150px]"><div className={LBL}>Unit / Aset</div>{editable?<Combobox options={unitOpts} value={l.unit_id||""} onChange={v=>upd(i,{unit_id:v})} placeholder="Unit/Aset"/>:<div className="flex h-9 items-center text-sm text-muted-foreground">{l.unit_name||"-"}</div>}</div>
          </div>
        </div>)}
      </div></div>
    </CardContent></Card><DocumentMessageEditor module="do" value={h.document_message} onChange={v=>setH({...h,document_message:v})} useDefault={isNew} readOnly={!editable}/></div></DocMetaTabs>
    {allocLine&&<SpkAllocationModal open onClose={()=>setAllocLine(null)} sourceType="do" lineId={allocLine} docStatus={doc?.status} canManage={alloc.canManage} onChanged={()=>{alloc.reload();}}/>}
    {dialog}
  </div>;
}
