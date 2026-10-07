import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { DocList } from "@/components/DocList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";
import { DocMetaTabs } from "@/components/DocMetaTabs";
import { AttachmentPanel, uploadPendingAttachments } from "@/components/DocMeta";
import { DocumentHeaderDefaults } from "@/components/DocumentHeaderDefaults";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError, lineQtyError, sourceDivision } from "@/lib/txnValidation";
import { ItemPicker } from "@/components/ItemPicker";
import { QtyStock } from "@/components/StockInfo";
import { StatusBadge } from "@/components/StatusBadge";
import { PullDialog } from "@/components/PullDialog";
import { applyLineReservation, lineFormReservation, mergeLinePull, pullParams } from "@/lib/sourceReservation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NumericInput } from "@/components/NumericInput";
import { num, fmtDate, todayISO } from "@/lib/format";
import { inheritSourceHeader } from "@/lib/sourceInheritance";
import { Save, Printer, ArrowLeft, Download, X, Info, Trash2, Plus, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { printDoc } from "@/lib/print";
import { useDocAllocations } from "@/components/SpkAllocationModal";
import { useCompletenessWarning } from "@/components/CompletenessWarningDialog";
import { buildTxnWarnings, HEADER_FIELDS, ITEM_FIELDS } from "@/lib/validation";

export function MiList(){const list=useServerList("/mi");const load=()=>list.reload();return <DocList txType="mi" createPath="/mi/new" basePath="/mi" module="mi" printType="MI" printOpts={{title:"MATERIAL ISSUED"}} onReload={load} testidPrefix="mi" server={list} minWidth={1300} columns={[noCol("No. MI"),dateCol(fmtDate),traceCol("mro"),traceCol("project"),traceCol("division"),traceCol("spk"),traceCol("requester"),{key:"receiver",label:"Penerima"},{key:"source_type",label:"Sumber",value:r=>(r.source_mode==="direct"||r.source_type==="Direct")?"Direct":"MRO",render:r=>(r.source_mode==="direct"||r.source_type==="Direct")?"Direct":"MRO"},{key:"line_count",label:"Item",num:true},{key:"status",label:"Status",status:true}]}/>;}

// Alokasi SPK MI (read-only, sumber MRO): "SPK-001" | "SPK-001 (6), SPK-002 (4)" | "Non-SPK".
const baseQty=l=>(Number(l.qty)||0)*(Number(l.conversion_factor)||1);
const spkKey=l=>l.mro_line_id&&baseQty(l)>0?`${l.mro_line_id}|${baseQty(l)}`:null;
const fmtMiAlloc=s=>{const a=(s?.allocations||[]).filter(x=>Number(x.allocated_qty)>1e-9);if(!a.length)return "Non-SPK";const non=Number(s.non_spk_qty)||0;if(a.length===1&&non<=1e-9)return a[0].spk_number||"SPK";const parts=a.map(x=>`${x.spk_number||"SPK"} (${num(x.allocated_qty)})`);if(non>1e-9)parts.push(`Non-SPK (${num(non)})`);return parts.join(", ");};
const miAllocCell=(l,saved,prev)=>{if(l.id)return fmtMiAlloc(saved[l.id]);const k=spkKey(l);if(!k)return l.mro_line_id?"—":"Non-SPK";const v=prev[k];if(v===undefined||v===null)return <span className="italic">memuat...</span>;if(v===false)return <span className="italic">Diwarisi saat simpan</span>;return fmtMiAlloc(v);};

export function MiForm(){
  const{id}=useParams();const nav=useNavigate();const{can}=useAuth();const masters=useMasters(STOCK_REFS);
  const[h,setH]=useState({date:todayISO(),division_id:"",default_warehouse_id:"",default_project_id:"",default_unit_id:"",spk:"",receiver:"",requester:"",department:"",source_type:"MRO",source_mode:"mro",notes:"",document_message:null});
  const[lines,setLines]=useState([]);const[doc,setDoc]=useState(null);const[pull,setPull]=useState(false);const[editing,setEditing]=useState(false);const isNew=!id;const editable=isNew||editing;
  const[pending,setPending]=useState([]);const[divErr,setDivErr]=useState(null);
  const[cfg,setCfg]=useState({mi_mode:"mro_only",can_direct:false});
  const[spkPrev,setSpkPrev]=useState({}); // preview alokasi SPK (sumber MRO) sebelum simpan
  const[stockMap,setStockMap]=useState({}); // item_id -> [{warehouse_id,warehouse_name,stock}]
  const alloc=useDocAllocations("mi",id);
  const { confirm, dialog } = useCompletenessWarning();
  const items=masters.map("items"),uoms=masters.map("uoms"); const uomLabel=uid=>{const u=uoms[uid];return u?(u.symbol||u.name||u.code):"";};
  const uomOptions=itemId=>{const it=items[itemId];if(!it?.base_uom_id)return[];return[{uom_id:it.base_uom_id,factor:1,is_base:true},...(it.uoms||[]).filter(x=>x.uom_id!==it.base_uom_id)].map(r=>{const u=uoms[r.uom_id]||{},short=u.symbol||u.name||u.code||"Satuan";return{value:r.uom_id,factor:Number(r.factor)||1,label:`${u.name||u.code||"Satuan"}${u.symbol?` (${u.symbol})`:""}${r.is_base?" — Dasar":` — 1 = ${num(r.factor)} ${uomLabel(it.base_uom_id)}`}`,selectedLabel:short,unit:short};});};
  const whOpts=(masters.data.warehouses||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}`,selectedLabel:d.name}));
  const projOpts=(masters.data.projects||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}`,selectedLabel:d.name}));
  const unitOpts=(masters.data.units||[]).map(d=>({value:d.id,label:`${d.code?d.code+" — ":""}${d.name}${d.plate_no?` (${d.plate_no})`:""}`,selectedLabel:d.plate_no||d.name}));
  useEffect(()=>{api.get("/settings/mi").then(r=>setCfg(r.data)).catch(()=>{});},[]);
  const loadStock=useCallback(itemId=>{if(!itemId||stockMap[itemId])return;api.get(`/stock/by-warehouse/${itemId}`).then(r=>setStockMap(s=>({...s,[itemId]:r.data.warehouses||[]}))).catch(()=>{});},[stockMap]);
  const load=useCallback(()=>api.get(`/mi/${id}`).then(r=>{setDoc(r.data);setH(r.data);setLines(r.data.lines.map(l=>({...l,_readonly:true})));setEditing(false);}),[id]);
  useEffect(()=>{if(id)load();},[id,load]);
  useEffect(()=>{lines.forEach(l=>l.item_id&&loadStock(l.item_id));},[lines,loadStock]);
  useEffect(()=>{const t=setTimeout(()=>lines.forEach(l=>{const k=!l.id&&spkKey(l);if(!k||spkPrev[k]!==undefined)return;setSpkPrev(m=>({...m,[k]:null}));api.post("/spk-allocations/preview-inherit",{target_type:"mi",sources:[{source_line_id:l.mro_line_id,qty:baseQty(l)}]}).then(r=>setSpkPrev(m=>({...m,[k]:r.data}))).catch(()=>setSpkPrev(m=>({...m,[k]:false})));}),300);return()=>clearTimeout(t);},[lines,spkPrev]);
  const beginEdit=()=>{setEditing(true);setLines(cur=>cur.map(l=>({...l,_readonly:false})));};
  const direct=h.source_type==="Direct";
  // Sisa efektif picker = sisa MRO untuk MI ini - Qty Issue yang sudah ada di form (satuan dasar).
  const pullTransform=useMemo(()=>{const res=lineFormReservation(lines.filter(l=>!l._direct),"mro_line_id");return rows=>applyLineReservation(rows,res);},[lines]);
  // Baris MRO yang sudah ada di form -> Qty Issue digabung ke baris MI tersebut (bukan baris duplikat).
  const onPull=picked=>{const {merged,fresh}=mergeLinePull(lines,picked,"mro_line_id","mro_id",l=>l._direct);const add=fresh.map(p=>({item_id:p.item_id,item_code:p.item_code,item_name:p.item_name,qty:p._qty,unit:p.unit,uom_id:p.uom_id,conversion_factor:p.conversion_factor||1,warehouse_id:p.warehouse_id,project_id:p.project_id||h.default_project_id,unit_id:p.unit_id||h.default_unit_id,_warehouseOverride:false,_projectOverride:!!p.project_id,_unitOverride:!!p.unit_id,notes:p.notes||"",_locked:true,_sourceHeader:p.source_header||null,mro_id:p.mro_id,mro_no:p.mro_no,mro_line_id:p.line_id,qty_mro:p.requested,issued_before:p.issued,outstanding:p.outstanding,_available:p.available,sources:[{mro_id:p.mro_id,line_id:p.line_id,qty:p._qty,base_qty:p._qty*(p.conversion_factor||1)}]}));const combined=[...merged,...add];const sd=sourceDivision(combined.filter(l=>!l._direct&&(l._sourceHeader||l.source_header)));if(sd.conflict||(h.division_id&&sd.division_id&&lines.some(l=>l.mro_id)&&sd.division_id!==h.division_id)){toast.error("Satu MI hanya untuk satu Divisi. Pilih MRO dari Divisi yang sama.");return;}setLines(combined);setDivErr(null);setH(cur=>{const nx=inheritSourceHeader(cur,combined);const sh=picked[0]?.source_header||{};return {...nx,division_id:sd.division_id||nx.division_id||cur.division_id||"",requester:nx.requester||sh.requester||sh.pemohon||cur.requester||""};});picked.forEach(p=>loadStock(p.item_id));};
  const syncSrc=l=>(l.sources?.length===1?{...l,sources:[{...l.sources[0],qty:Number(l.qty)||0,base_qty:(Number(l.qty)||0)*(Number(l.conversion_factor)||1)}]}:l);
  const addRow=()=>setLines(cur=>[...cur,{item_id:"",qty:0,unit:"",uom_id:"",conversion_factor:1,warehouse_id:h.default_warehouse_id||"",project_id:h.default_project_id||"",unit_id:h.default_unit_id||"",notes:"",_direct:true}]);
  const upd=(i,patch)=>setLines(cur=>cur.map((l,x)=>{if(x!==i)return l;if(patch.item_id!==undefined){const it=items[patch.item_id];const base=it?.base_uom_id||"";loadStock(patch.item_id);return{...l,item_id:patch.item_id,uom_id:base,conversion_factor:1,unit:base?uomLabel(base):""};}if(patch.uom_id!==undefined){const s=uomOptions(l.item_id).find(o=>o.value===patch.uom_id),newF=Number(s?.factor)||1;return syncSrc({...l,uom_id:patch.uom_id,conversion_factor:newF,unit:s?.unit||l.unit});}return patch.qty!==undefined?syncSrc({...l,...patch}):{...l,...patch};}));
  const doSave=async()=>{try{if(isNew){const res=await api.post("/mi",{...h,lines});const mid=res.data.id;await saveDocumentMessage("mi",mid,h.document_message);let failed=[];if(pending.length){const up=await uploadPendingAttachments("mi",mid,pending);failed=up.failed;setPending(failed);}if(failed.length)toast.error(`MI diposting, tetapi lampiran "${failed.map(f=>f.name).join(", ")}" gagal diunggah. Silakan coba kembali.`);else toast.success("MI diposting, stok berkurang dalam satuan dasar");nav(`/mi/${mid}`);}else{await api.put(`/transactions/mi/${id}`,{...h,lines});await saveDocumentMessage("mi",id,h.document_message);toast.success("MI diperbarui. Sistem membalik stok lama lalu memposting ulang perubahan.");load();}}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const save=()=>{const de=divisionError(h.division_id);if(de){setDivErr(de);toast.error(de);return;}setDivErr(null);const qe=lineQtyError(lines);if(qe){toast.error(qe);return;}confirm(buildTxnWarnings({h,lines,headerFields:HEADER_FIELDS.mi,itemFields:ITEM_FIELDS.mi}),doSave);};
  const numOrDash=v=>(v===undefined||v===null||v==="")?"—":num(v);
  const availOf=l=>{if(l._available!==undefined&&l._available!==null)return Number(l._available)||0;const rows=stockMap[l.item_id]||[];const r=rows.find(x=>x.warehouse_id===l.warehouse_id);return r?Number(r.stock)||0:undefined;};
  const afterIssue=l=>{const a=availOf(l);if(a===undefined)return undefined;return a-(Number(l.qty)||0)*(Number(l.conversion_factor)||1);};

  const UomCell=({l,i})=>(<div className="flex items-center gap-1"><div className="min-w-0 flex-1"><Combobox dense options={uomOptions(l.item_id)} value={l.uom_id||items[l.item_id]?.base_uom_id||""} onChange={v=>upd(i,{uom_id:v})} disabled={!l.item_id||uomOptions(l.item_id).length<=1}/></div>{l.item_id&&<Popover><PopoverTrigger asChild><button type="button" className="shrink-0 text-muted-foreground hover:text-primary" title="Konversi Stok" data-testid={`mi-uom-info-${i}`}><Info className="h-4 w-4"/></button></PopoverTrigger><PopoverContent align="end" className="w-60 text-xs"><div className="space-y-1"><div className="font-semibold">Konversi Stok</div><div className="flex justify-between gap-3"><span className="text-muted-foreground">Satuan transaksi</span><span className="font-medium">{num(l.qty)} {l.unit||""}</span></div>{(Number(l.conversion_factor)||1)!==1&&<div className="flex justify-between gap-3"><span className="text-muted-foreground">Faktor konversi</span><span>1 {l.unit||""} = {num(l.conversion_factor)} {uomLabel(items[l.item_id]?.base_uom_id)}</span></div>}<div className="flex justify-between gap-3 border-t pt-1"><span className="text-muted-foreground">Terhitung stok</span><span className="font-semibold">{num((Number(l.qty)||0)*(Number(l.conversion_factor)||1))} {uomLabel(items[l.item_id]?.base_uom_id)}</span></div></div></PopoverContent></Popover>}</div>);

  const head=[["w-[190px]","Barang"],["w-[140px]","Keterangan"],["w-[130px]","MRO"],["w-[170px]","Alokasi SPK"],["w-[140px]","Gudang"],["w-[140px]","Proyek"],["w-[130px]","Unit/Aset"],["w-[75px]","Qty MRO"],["w-[80px]","Sudah Issue"],["w-[85px]","Sisa Qty Issue"],["w-[100px]","Qty Issue"],["w-[110px]","Satuan"],["w-[120px]","Stok Setelah Issue"],["w-[44px]","Hapus"]];

  return <div><TransactionPageHeader type="mi" mode={isNew?"new":!doc?null:editing?"edit":"view"} number={doc?.no} showNumberField subtitle={doc&&<span className="flex items-center gap-2"><StatusBadge status={doc.status}/>{(doc.source_mode==="direct"||doc.source_type==="Direct")&&<span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700" data-testid="mi-direct-badge">Direct</span>}</span>}><Button variant="outline" onClick={()=>nav("/mi")}><ArrowLeft className="h-4 w-4 mr-2"/>Kembali</Button>{editable&&!direct&&<Button variant="outline" onClick={()=>setPull(true)} data-testid="mi-pull-btn"><Download className="h-4 w-4 mr-2"/>Tarik MRO</Button>}{editable&&direct&&<Button variant="outline" onClick={addRow} data-testid="mi-add-row"><Plus className="h-4 w-4 mr-2"/>Tambah Baris</Button>}{!isNew&&!editing&&<TransactionMutationActions module="mi" id={id} ready={!!doc} onEdit={beginEdit} onDeleted={()=>nav("/mi")}/>} {editing&&<Button variant="outline" onClick={load}><X className="h-4 w-4 mr-2"/>Batal Edit</Button>}{editable&&can(isNew?"create":"edit")&&<Button onClick={save} disabled={lines.length===0}><Save className="h-4 w-4 mr-2"/>{editing?"Simpan Perubahan":"Posting Pengeluaran"}</Button>}{!isNew&&!editing&&<Button variant="outline" onClick={()=>printDoc("MI",doc,{title:"MATERIAL ISSUED"})}><Printer className="h-4 w-4 mr-2"/>Print</Button>}</TransactionPageHeader>
    <PullDialog open={pull} onClose={()=>setPull(false)} url="/pull/mro-for-mi" params={pullParams(isNew?null:id)} transform={pullTransform} title="Tarik MRO — Pilih Item Dikeluarkan" onConfirm={onPull} columns={[{key:"mro_no",label:"MRO",mono:true},{key:"item_name",label:"Barang"},{key:"warehouse_name",label:"Gudang"},{key:"unit",label:"Satuan"},{key:"requested",label:"Qty Request",num:true},{key:"issued",label:"Sudah MI",num:true},{key:"reserved",label:"Di Form",num:true},{key:"outstanding",label:"Remaining",num:true},{key:"available",label:"Stok",num:true}]}/>
    <DocMetaTabs entity="mi" entityId={id} hideAttachments><div className="space-y-4"><Card><CardContent className="pt-6 space-y-6">
      {editable&&cfg.can_direct&&<Tabs value={h.source_type} onValueChange={v=>{setH({...h,source_type:v,source_mode:v==="Direct"?"direct":"mro"});setLines([]);}}><TabsList><TabsTrigger value="MRO">Dari MRO</TabsTrigger><TabsTrigger value="Direct">Direct (Tanpa MRO)</TabsTrigger></TabsList></Tabs>}
      {/* HEADER Row 1 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Penerima Barang"><Input value={h.receiver||""} onChange={e=>setH({...h,receiver:e.target.value})} disabled={!editable} data-testid="mi-receiver"/></Field>{!direct&&<Field label="Pemohon MRO"><Input value={h.requester||""} disabled readOnly placeholder="Diwarisi dari MRO" data-testid="mi-requester"/></Field>}<Field label="Tanggal"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})} disabled={!editable}/></Field><DivisionField testid="mi-division-field" options={masters.opts("divisions",d=>d.name)} value={h.division_id} onChange={v=>{setH({...h,division_id:v});setDivErr(null);}} disabled={!editable} locked={!direct&&lines.some(l=>l.mro_id)} lockedHint="Divisi mengikuti MRO sumber dan tidak dapat diubah." error={divErr}/></div>
      {/* HEADER Row 2 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="Gudang Default"><Combobox options={whOpts} value={h.default_warehouse_id} onChange={v=>setH({...h,default_warehouse_id:v})} disabled={!editable}/></Field><DocumentHeaderDefaults h={h} setH={setH} masters={masters} readOnly={!editable} hideSpk/><Field label="Keperluan / Keterangan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})} disabled={!editable}/></Field></div>

      {/* ATTACHMENTS */}
      <div className="rounded-lg border bg-muted/10 p-4"><div className="mb-3 flex items-center gap-2"><Paperclip className="h-4 w-4 text-muted-foreground"/><h3 className="font-head text-sm font-semibold">Lampiran Pengeluaran</h3></div><AttachmentPanel entity="mi" entityId={id} pending={pending} onPendingChange={setPending}/></div>

      {/* ITEM TABLE */}
      <h3 className="font-head text-sm font-semibold">Item Dikeluarkan {direct&&<span className="ml-2 inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">Direct</span>}</h3>
      <div className="overflow-x-auto rounded-md border bg-card shadow-sm"><div className="min-w-[1760px]">
        <div className="flex items-stretch gap-1.5 border-b bg-muted px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{head.map(([w,t],k)=><div key={k} className={w+" shrink-0"+((t==="Qty MRO"||t==="Sudah Issue"||t==="Sisa Qty Issue"||t==="Stok Setelah Issue")?" text-right":"")}>{t}</div>)}</div>
        {lines.length===0&&<div className="p-6 text-center text-sm text-muted-foreground">{direct?"Klik Tambah Baris untuk menambah item":"Tarik MRO untuk menambah item"}</div>}
        {lines.map((l,i)=><div key={i} className="border-b px-3 py-2.5 last:border-b-0" data-testid={`mi-item-block-${i}`}>
          <div className="flex items-center gap-1.5">
            <div className="w-[190px] shrink-0">{(editable&&direct)?<ItemPicker items={masters.data.items||[]} uoms={masters.map("uoms")} value={l.item_id} onChange={v=>upd(i,{item_id:v})} warehouseId={l.warehouse_id} testid={`mi-item-${i}`}/>:<span className="text-sm font-medium">{l.item_name||l.item_code||"-"}</span>}</div>
            <div className="w-[140px] shrink-0">{editable?<Input value={l.notes||""} onChange={e=>upd(i,{notes:e.target.value})} className="h-9 text-sm" placeholder="Keterangan"/>:<span className="text-sm text-muted-foreground">{l.notes||"-"}</span>}</div>
            <div className="w-[130px] shrink-0 truncate font-mono text-[11px] text-muted-foreground" data-testid={`mi-mro-ref-${i}`} title={l.mro_no||""}>{l.mro_no||<span className="italic">—</span>}</div>
            <div className="w-[170px] shrink-0 truncate text-xs text-muted-foreground" data-testid={`mi-alloc-${i}`} title={l.id?fmtMiAlloc(alloc.map[l.id]):(spkPrev[spkKey(l)]?fmtMiAlloc(spkPrev[spkKey(l)]):undefined)}>{miAllocCell(l,alloc.map,spkPrev)}</div>
            <div className="w-[140px] shrink-0">{(editable&&direct)?<Combobox options={whOpts} value={l.warehouse_id||""} onChange={v=>upd(i,{warehouse_id:v})} placeholder="Gudang"/>:<div className="truncate text-sm text-muted-foreground" data-testid={`mi-wh-${i}`} title={!direct?"Terkunci sesuai MRO":""}>{masters.map("warehouses")[l.warehouse_id]?.name||l.warehouse_name||"-"}{!direct&&<div className="text-[10px]">(terkunci MRO)</div>}</div>}</div>
            <div className="w-[140px] shrink-0">{(editable&&direct)?<Combobox options={projOpts} value={l.project_id||""} onChange={v=>upd(i,{project_id:v})} placeholder="Proyek"/>:<div className="truncate text-sm text-muted-foreground">{masters.map("projects")[l.project_id]?.name||l.project_name||"-"}</div>}</div>
            <div className="w-[130px] shrink-0">{(editable&&direct)?<Combobox options={unitOpts} value={l.unit_id||""} onChange={v=>upd(i,{unit_id:v})} placeholder="Unit/Aset"/>:<div className="truncate text-sm text-muted-foreground">{masters.map("units")[l.unit_id]?.name||l.unit_name||"-"}</div>}</div>
            <div className="w-[75px] shrink-0 text-right text-sm tabular-nums">{direct?"—":numOrDash(l.qty_mro)}</div>
            <div className="w-[80px] shrink-0 text-right text-sm tabular-nums">{direct?"—":numOrDash(l.issued_before)}</div>
            <div className="w-[85px] shrink-0 text-right text-sm font-medium tabular-nums">{direct?"—":numOrDash(l.outstanding)}</div>
            <div className="w-[100px] shrink-0"><QtyStock itemId={l.item_id} warehouseId={l.warehouse_id} itemName={items[l.item_id]?.name||l.item_name} value={availOf(l)} testid={`mi-stock-${i}`}>{editable?<NumericInput mode="quantity" value={l.qty} onChange={v=>upd(i,{qty:v})} className="h-9 text-right" data-testid={`mi-qty-${i}`}/>:<div className="h-9 pt-2 text-right text-sm tabular-nums">{num(l.qty)}</div>}</QtyStock></div>
            <div className="w-[110px] shrink-0">{editable?<UomCell l={l} i={i}/>:<span className="text-sm">{l.unit||""}</span>}</div>
            <div className="w-[120px] shrink-0 text-right text-sm tabular-nums" data-testid={`mi-after-${i}`}>{afterIssue(l)===undefined?"—":<span className={afterIssue(l)<0?"text-destructive font-semibold":""}>{num(afterIssue(l))} {uomLabel(items[l.item_id]?.base_uom_id)}</span>}</div>
            <div className="w-[44px] shrink-0">{editable&&<Button variant="ghost" size="icon" className="h-9 w-9" onClick={()=>setLines(lines.filter((_,x)=>x!==i))} data-testid={`mi-remove-${i}`} aria-label="Hapus"><Trash2 className="h-4 w-4 text-destructive"/></Button>}</div>
          </div>
        </div>)}
      </div></div>
    </CardContent></Card><DocumentMessageEditor module="mi" value={h.document_message} onChange={v=>setH({...h,document_message:v})} useDefault={isNew} readOnly={!editable}/></div></DocMetaTabs>
    {dialog}
  </div>;
}
