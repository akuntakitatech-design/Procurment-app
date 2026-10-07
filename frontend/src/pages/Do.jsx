import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { DocList } from "@/components/DocList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";
import { DocMetaTabs } from "@/components/DocMetaTabs";
import { DoInvoicePanel } from "@/components/invoice/DoInvoicePanel";
import { AttachmentPanel, uploadPendingAttachments } from "@/components/DocMeta";
import { DocumentHeaderDefaults } from "@/components/DocumentHeaderDefaults";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError, lineQtyError, sourceDivision, SOURCE_DIVISION_CONFLICT_MSG } from "@/lib/txnValidation";
import { StatusBadge } from "@/components/StatusBadge";
import { PullDialog } from "@/components/PullDialog";
import { applyLineReservation, lineFormReservation, mergeLinePull, pullParams } from "@/lib/sourceReservation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DoItemRow, DO_COLS, overOf } from "@/components/DoItemRow";
import { fmtDate, todayISO } from "@/lib/format";
import { Printer, ArrowLeft, Download, X, Info, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";
import { SpkAllocationModal, useDocAllocations, formatAllocText } from "@/components/SpkAllocationModal";
import { useCompletenessWarning } from "@/components/CompletenessWarningDialog";
import { buildTxnWarnings, HEADER_FIELDS, ITEM_FIELDS } from "@/lib/validation";

export function DoList(){const list=useServerList("/do");const load=()=>list.reload();return <DocList txType="do" createPath="/do/new" basePath="/do" module="do" printType="DO" printOpts={{title:"PENERIMAAN BARANG"}} onReload={load} testidPrefix="do" server={list} minWidth={1500} columns={[noCol("No. DO"),dateCol(fmtDate),{key:"supplier_name",label:"Supplier"},{key:"supplier_dn",label:"No. Surat Jalan"},traceCol("mro"),traceCol("ro"),traceCol("po"),traceCol("project"),traceCol("division"),traceCol("spk"),{key:"supplier_invoice",label:"No. Faktur"},{key:"line_count",label:"Item",num:true},{key:"status",label:"Status",status:true}]}/>;}

const LBL = "mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground";
const commonOf=(lines,k)=>{const v=[...new Set(lines.map(l=>l[k]||""))];return v.length===1?v[0]:(v.length?"__mixed__":"");};

export function DoForm(){
  const{id}=useParams();const nav=useNavigate();const{can}=useAuth();const masters=useMasters();
  const[h,setH]=useState({date:todayISO(),supplier_id:"",supplier_dn:"",supplier_invoice:"",invoice_date:null,default_warehouse_id:"",default_project_id:"",default_unit_id:"",spk:"",receiver:"",notes:"",document_message:null});
  const[lines,setLines]=useState([]);const[doc,setDoc]=useState(null);const[pull,setPull]=useState(false);const[editing,setEditing]=useState(false);const isNew=!id;const editable=isNew||editing;
  const[pending,setPending]=useState([]);const[divErr,setDivErr]=useState(null);
  const alloc=useDocAllocations("do",id);const[allocLine,setAllocLine]=useState(null);
  const { confirm, dialog } = useCompletenessWarning();
  const whMap=masters.map("warehouses"),projMap=masters.map("projects"),unitMap=masters.map("units"),supMap=masters.map("suppliers");
  const names={wh:l=>l.warehouse_name||whMap[l.warehouse_id]?.name,project:l=>l.project_name||projMap[l.project_id]?.name,unit:l=>l.unit_name||(unitMap[l.unit_id]?(unitMap[l.unit_id].plate_no||unitMap[l.unit_id].name):"")};
  const whOpts=(masters.data.warehouses||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}`,selectedLabel:d.name}));
  const load=useCallback(()=>api.get(`/do/${id}`).then(r=>{setDoc(r.data);setH(r.data);setLines(r.data.lines.map(l=>{const f=Number(l.conversion_factor)||1;return{...l,qty:Number(l.display_qty??((Number(l.qty)||0)/f)),exception_qty:Number(l.exception_qty)||0,_readonly:true};}));setEditing(false);}),[id]);
  useEffect(()=>{if(id)load();},[id,load]);
  const beginEdit=()=>{setEditing(true);setLines(cur=>cur.map(l=>({...l,_readonly:false,sources:l.po_line_id?[{po_id:l.po_id,line_id:l.po_line_id,qty:l.qty,base_qty:l.qty*(Number(l.conversion_factor)||1)}]:[]})));};
  const onPull=picked=>{
    const sups=[...new Set([h.supplier_id,...lines.map(()=>h.supplier_id),...picked.map(p=>p.supplier_id)].filter(Boolean))];
    if(sups.length>1){toast.error("Satu DO hanya boleh berisi PO dari supplier yang sama. Pilih PO dari supplier yang sama.");return;}
    // Baris PO yang sudah ada di form -> Qty Terima digabung ke baris DO tersebut (1 baris PO = 1 baris DO).
    const {merged,fresh}=mergeLinePull(lines,picked,"po_line_id","po_id");
    const add=fresh.map(p=>({po_id:p.po_id,po_line_id:p.line_id,po_no:p.po_no,item_id:p.item_id,item_code:p.item_code,item_name:p.item_name,unit:p.unit,uom_id:p.uom_id,conversion_factor:p.conversion_factor||1,qty_po:p.qty_po,received_before:p.received,qty:p._qty,notes:p.notes||"",warehouse_id:p.warehouse_id||h.default_warehouse_id,project_id:p.project_id||"",unit_id:p.unit_id||"",_source_division_id:p.source_header?.division_id||p.division_id||"",warehouse_name:p.warehouse_name,project_name:p.project_name,unit_name:p.unit_name,lineage:{mro:p.mro_no,ro:p.ro_no,po:p.po_no,spk:p.spk_text},condition:"Baik",exception_qty:0,sources:[{po_id:p.po_id,line_id:p.line_id,qty:p._qty,base_qty:p._qty*(p.conversion_factor||1)}]}));
    const nextLines=[...merged,...add];const sd=sourceDivision(add);const curDiv=h.division_id||sourceDivision(lines.filter(l=>l._source_division_id)).division_id;
    if(sd.conflict||(curDiv&&sd.division_id&&sd.division_id!==curDiv)){toast.error("Satu DO hanya boleh berisi PO dari divisi yang sama.");return;}
    setLines(nextLines);setDivErr(null);setH(cur=>({...cur,supplier_id:cur.supplier_id||sups[0]||"",division_id:cur.division_id||sd.division_id||""}));};
  const upd=(i,patch)=>setLines(cur=>cur.map((l,x)=>{if(x!==i)return l;const n={...l,...patch};if(patch.condition==="Baik")n.exception_qty=0;if(patch.qty!==undefined&&n.sources?.length===1)n.sources=[{...n.sources[0],qty:Number(patch.qty)||0,base_qty:(Number(patch.qty)||0)*(Number(n.conversion_factor)||1)}];return n;}));
  const remove=i=>setLines(cur=>cur.filter((_,x)=>x!==i));
  const hdr=k=>{const v=commonOf(lines,k);return v;};
  const payload=()=>{const w=hdr("warehouse_id"),p=hdr("project_id"),u=hdr("unit_id");return{...h,default_warehouse_id:lines.length?(w==="__mixed__"?"":w):h.default_warehouse_id,default_project_id:p==="__mixed__"?"":p,default_unit_id:u==="__mixed__"?"":u,lines};};
  const doSave=async()=>{try{if(isNew){const res=await api.post("/do",payload());const did=res.data.id;await saveDocumentMessage("do",did,h.document_message);let failed=[];if(pending.length){const up=await uploadPendingAttachments("do",did,pending);failed=up.failed;setPending(failed);}if(failed.length)toast.error(`DO diposting, tetapi lampiran "${failed.map(f=>f.name).join(", ")}" gagal diunggah. Silakan coba kembali.`);else toast.success("DO diposting dan kondisi penerimaan tercatat");nav(`/do/${did}`);}else{await api.put(`/transactions/do/${id}`,payload());await saveDocumentMessage("do",id,h.document_message);toast.success("DO diperbarui. Stok dan kondisi penerimaan dihitung ulang.");load();}}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const save=()=>{if(!lines.some(l=>Number(l.qty)>0))return toast.error("Minimal satu item harus memiliki Qty Terima lebih dari 0");const sdv=sourceDivision(lines.filter(l=>l._source_division_id));if(sdv.conflict){setDivErr(SOURCE_DIVISION_CONFLICT_MSG);return toast.error(SOURCE_DIVISION_CONFLICT_MSG);}const de=divisionError(h.division_id||sdv.division_id);if(de){setDivErr(de);toast.error(de);return;}setDivErr(null);const qe=lineQtyError(lines);if(qe){toast.error(qe);return;}const miss=lines.findIndex(l=>overOf(l)>0&&!String(l.over_receipt_reason||"").trim());if(miss>=0)return toast.error(`Item ${miss+1}: Qty Terima melebihi sisa PO. Alasan Penerimaan Berlebih wajib diisi.`);confirm(buildTxnWarnings({h,lines,headerFields:HEADER_FIELDS.do,itemFields:ITEM_FIELDS.do}),doSave);};
  const allocCell=(l,i)=>(!l.id
    ? <span className="text-[11px]" data-testid={`do-alloc-preview-${i}`}>{l.lineage?.spk||"-"}</span>
    : <button type="button" onClick={()=>setAllocLine(l.id)} data-testid={`do-alloc-cell-${i}`} className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors hover:bg-accent/50 ${alloc.map[l.id]?.is_over?"border-destructive text-destructive":"border-border"}`}>{formatAllocText(alloc.map[l.id])}</button>);
  const ConditionHelp=()=>(
    <Popover><PopoverTrigger asChild><button type="button" className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-primary" data-testid="do-condition-help"><Info className="h-3.5 w-3.5"/>Panduan Kondisi Penerimaan</button></PopoverTrigger><PopoverContent align="start" className="w-80 text-xs"><div className="space-y-1.5"><div className="font-semibold">Kondisi Penerimaan</div><p><b>Baik</b> — masuk stok normal.</p><p><b>Rusak</b> — mengurangi stok usable sesuai Qty Rusak.</p><p><b>Kurang</b> — mencatat selisih; PO tetap outstanding.</p><p><b>Lebih</b> — mencatat barang fisik berlebih tanpa menambah stok/PO melebihi pesanan.</p><p><b>Over Receipt</b> — Qty Terima melebihi Sisa PO; wajib alasan, Qty PO tidak berubah.</p></div></PopoverContent></Popover>
  );
  const locked=lines.length>0;
  // Sisa efektif picker = sisa PO untuk DO ini - Qty Terima yang sudah ada di form (satuan dasar).
  const pullTransform=useMemo(()=>{const res=lineFormReservation(lines,"po_line_id");return rows=>applyLineReservation(rows,res);},[lines]);
  const HeaderDefault=({label,k,map,tid})=>{const v=hdr(k);const text=v==="__mixed__"?"Beragam":(map[v]?.plate_no||map[v]?.name||"");return <Field label={label}><Input value={text} disabled placeholder="-" data-testid={tid}/></Field>;};
  return <div><TransactionPageHeader type="do" mode={isNew?"new":!doc?null:editing?"edit":"view"} number={doc?.no} showNumberField subtitle={doc&&<StatusBadge status={doc.status}/>}><Button variant="outline" onClick={()=>nav("/do")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{editable&&<Button variant="outline" onClick={()=>setPull(true)} data-testid="do-pull-po"><Download className="h-4 w-4 mr-2"/>Tarik PO</Button>}{!isNew&&!editing&&<TransactionMutationActions module="do" id={id} ready={!!doc} onEdit={beginEdit} onDeleted={()=>nav("/do")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{editable&&can(isNew?"create":"edit")&&<Button onClick={save} disabled={lines.length===0} data-testid="do-save">{editing?"Simpan Perubahan":"Posting Penerimaan"}</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("DO",doc,{title:"PENERIMAAN BARANG"})}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</TransactionPageHeader>
    <PullDialog open={pull} onClose={()=>setPull(false)} url={`/pull/po-for-do${h.supplier_id?"?supplier_id="+h.supplier_id:""}`} params={pullParams(isNew?null:id)} transform={pullTransform} title="Tarik PO — Pilih Item Diterima" onConfirm={onPull} columns={[{key:"po_no",label:"PO",mono:true},{key:"supplier_name",label:"Supplier"},{key:"mro_no",label:"MRO",mono:true},{key:"ro_no",label:"RO",mono:true},{key:"item_code",label:"Kode",mono:true},{key:"item_name",label:"Barang"},{key:"unit",label:"Satuan"},{key:"qty_po",label:"Qty PO",num:true},{key:"received",label:"Diterima",num:true},{key:"reserved",label:"Di Form",num:true},{key:"outstanding",label:"Sisa",num:true}]}/>
    <DocMetaTabs entity="do" entityId={id} hideAttachments><div className="space-y-4">{!isNew&&can("invoice.view")&&<DoInvoicePanel doId={id}/>}<Card><CardContent className="pt-6 space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><DivisionField testid="do-division-field" options={masters.opts("divisions",d=>d.name)} value={h.division_id||sourceDivision(lines.filter(l=>l._source_division_id)).division_id||""} onChange={()=>{}} locked lockedHint="Divisi mengikuti PO sumber dan tidak dapat diubah." error={divErr}/><Field label="Tanggal Penerimaan"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})} disabled={!editable}/></Field><Field label={locked?"Supplier (mengikuti PO)":"Supplier"}><div data-testid="do-supplier">{locked?<Input value={supMap[h.supplier_id]?.name||h.supplier_name||""} disabled/>:<Combobox options={masters.opts("suppliers",d=>d.name)} value={h.supplier_id} onChange={v=>setH({...h,supplier_id:v})} disabled={!editable}/>}</div></Field><Field label="No. Surat Jalan"><Input value={h.supplier_dn||""} onChange={e=>setH({...h,supplier_dn:e.target.value})} disabled={!editable} data-testid="do-surat-jalan"/></Field><Field label="No. Faktur (opsional)"><Input value={h.supplier_invoice||""} onChange={e=>setH({...h,supplier_invoice:e.target.value})} disabled={!editable} data-testid="do-invoice"/></Field></div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">{locked?<><HeaderDefault label="Gudang Default" k="warehouse_id" map={whMap} tid="do-hdr-warehouse"/><HeaderDefault label="Proyek Default" k="project_id" map={projMap} tid="do-hdr-project"/><HeaderDefault label="Unit/Aset Default" k="unit_id" map={unitMap} tid="do-hdr-unit"/></>:<><Field label="Gudang Default"><Combobox options={whOpts} value={h.default_warehouse_id} onChange={v=>setH({...h,default_warehouse_id:v})} disabled={!editable}/></Field><DocumentHeaderDefaults testidPrefix="do" h={h} setH={setH} masters={masters} readOnly={!editable} hideSpk/></>}<Field label="Petugas Penerima"><Input value={h.receiver||""} onChange={e=>setH({...h,receiver:e.target.value})} disabled={!editable}/></Field></div>
      <div className="grid grid-cols-1 gap-4"><Field label="Catatan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})} disabled={!editable}/></Field></div>
      <div className="rounded-lg border bg-muted/10 p-4"><div className="mb-3 flex items-center gap-2"><Paperclip className="h-4 w-4 text-muted-foreground"/><h3 className="font-head text-sm font-semibold">Lampiran Penerimaan</h3></div><AttachmentPanel entity="do" entityId={id} pending={pending} onPendingChange={setPending}/></div>
      <div className="flex items-center justify-between"><h3 className="font-head text-sm font-semibold">Item Diterima</h3><ConditionHelp/></div>
      <div className={LBL}>Sumber item (MRO | RO | PO | Alokasi SPK), Barang, Keterangan, Gudang, Proyek, Unit/Aset dan Satuan terkunci mengikuti PO.</div>
      <div className="overflow-x-auto rounded-md border bg-card shadow-sm"><div className="min-w-[1560px]">
        <div className="flex items-stretch gap-1.5 border-b bg-muted px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{DO_COLS.map(([w,t,r],k)=><div key={k} className={`${w} shrink-0 ${r?"text-right":""}`}>{t}</div>)}</div>
        {lines.length===0&&<div className="p-6 text-center text-sm text-muted-foreground">Tarik PO untuk menambah item</div>}
        {lines.map((l,i)=><DoItemRow key={i} l={l} i={i} editable={editable} upd={upd} remove={remove} names={names} allocCell={allocCell(l,i)}/>)}
      </div></div>
    </CardContent></Card><DocumentMessageEditor module="do" value={h.document_message} onChange={v=>setH({...h,document_message:v})} useDefault={isNew} readOnly={!editable}/></div></DocMetaTabs>
    {allocLine&&<SpkAllocationModal open onClose={()=>setAllocLine(null)} sourceType="do" lineId={allocLine} docStatus={doc?.status} canManage={alloc.canManage} onChanged={()=>{alloc.reload();}}/>}
    {dialog}
  </div>;
}
