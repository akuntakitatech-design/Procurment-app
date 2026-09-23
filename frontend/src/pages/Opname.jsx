import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { AttachmentPanel } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Save, Send, CheckCircle, X, Paperclip } from "lucide-react";
import { num, fmtDate, todayISO } from "@/lib/format";
import { toast } from "sonner";

const EMPTY = () => ({ date: todayISO(), warehouse_id: "", division_id: "", mode: "live", scope: "all", notes: "", document_message: null });

export default function Opname() {
  const masters = useMasters(); const { can } = useAuth();
  const [rows, setRows] = useState([]); const [createOpen, setCreateOpen] = useState(false);
  const [h, setH] = useState(EMPTY());
  const [detail, setDetail] = useState(null); const [counts, setCounts] = useState({}); const [countUoms, setCountUoms] = useState({}); const [forceEditing,setForceEditing]=useState(false);
  const itemsMap = masters.map("items"); const uomsMap = masters.map("uoms");
  const uomLabel = (id) => { const u = uomsMap[id]; return u ? (u.symbol || u.name || u.code) : ""; };
  const uomOptions = (itemId) => {
    const it = itemsMap[itemId]; if (!it) return [];
    if (!it.base_uom_id) return it.unit ? [{ value: `legacy:${it.unit}`, label: it.unit, factor: 1 }] : [];
    const seen = new Set();
    return [{ uom_id: it.base_uom_id, factor: 1, is_base: true }, ...(it.uoms || [])]
      .filter((r) => r.uom_id && !seen.has(r.uom_id) && seen.add(r.uom_id))
      .map((r) => { const u = uomsMap[r.uom_id] || {}; return { value: r.uom_id, factor: Number(r.factor) || 1, label: `${u.name || u.code || "Satuan"}${u.symbol ? ` (${u.symbol})` : ""}${r.is_base ? " — Dasar" : ` — 1 = ${num(r.factor)} ${uomLabel(it.base_uom_id)}`}` }; });
  };
  const factorFor = (line, uid) => Number(uomOptions(line.item_id).find((x) => x.value === uid)?.factor) || 1;

  const load = () => api.get("/opname").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  const create = async () => { try { const res = await api.post("/opname", h); await saveDocumentMessage("opname", res.data.id, h.document_message); toast.success(`Stock opname ${res.data.no} dibuat, snapshot diambil`); setCreateOpen(false); setH(EMPTY()); load(); openDetail(res.data.id); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };

  const openDetail = (id) => api.get(`/opname/${id}`).then((r) => {
    setCreateOpen(false); setDetail(r.data); setForceEditing(false); setH({date:r.data.date,warehouse_id:r.data.warehouse_id||"",division_id:r.data.division_id||"",mode:r.data.mode||"live",scope:r.data.scope||"all",notes:r.data.notes||"",document_message:r.data.document_message||""});
    const nextUoms = {}; const nextCounts = {};
    r.data.lines.forEach((l) => { const it = itemsMap[l.item_id]; const uid = it?.base_uom_id || (it?.unit ? `legacy:${it.unit}` : ""); nextUoms[l.id] = uid; nextCounts[l.id] = l.counted ?? ""; });
    setCountUoms(nextUoms); setCounts(nextCounts);
  });

  const changeUom = (line, uid) => {
    const oldUid = countUoms[line.id]; const oldFactor = factorFor(line, oldUid); const newFactor = factorFor(line, uid); const current = counts[line.id];
    setCountUoms((s) => ({ ...s, [line.id]: uid }));
    if (current !== "" && current != null) { const base = Number(current) * oldFactor; setCounts((s) => ({ ...s, [line.id]: base / newFactor })); }
  };

  const baseCountLines=()=>detail.lines.map(line=>{const uid=countUoms[line.id];const factor=factorFor(line,uid);const c=counts[line.id];return{id:line.id,item_id:line.item_id,snapshot:line.snapshot,counted:c===""||c==null?null:Number(c)*factor};});
  const saveCount = async (status) => {
    const lines = baseCountLines().filter(x=>x.counted!==null).map(x=>({line_id:x.id,counted:x.counted}));
    await api.put(`/opname/${detail.id}/count`, { lines, status }); toast.success("Hasil hitung tersimpan dalam satuan dasar"); openDetail(detail.id); load();
  };
  const saveEdit=async()=>{try{await api.put(`/transactions/opname/${detail.id}`,{...h,lines:baseCountLines()});await saveDocumentMessage("opname",detail.id,h.document_message);toast.success("Stock opname diperbarui. Jika sudah Posted, efek stok lama direversal lalu diposting ulang.");openDetail(detail.id);load();}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const submit = async () => { await api.post(`/opname/${detail.id}/submit`); toast.success("Diajukan untuk approval"); openDetail(detail.id); load(); };
  const post = async () => { try { await api.post(`/opname/${detail.id}/post`); toast.success("Diposting, stok disesuaikan"); openDetail(detail.id); load(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };

  return <div>
    <PageHeader title="Stock Opname" subtitle="Cek fisik stok per gudang">{can("create") && <Button onClick={() => { const next=!createOpen; setCreateOpen(next); setDetail(null); if(next) setH(EMPTY()); }}><Plus className="h-4 w-4 mr-2" />{createOpen ? "Tutup Form" : "Buat Opname"}</Button>}</PageHeader>
    {createOpen && <div className="mb-4 space-y-4"><Card className="border-primary/20"><CardContent className="pt-5 space-y-5"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Form Transaksi</div><h2 className="font-head text-lg font-semibold">Buat Stock Opname</h2><p className="text-xs text-muted-foreground">Snapshot dan posting tetap menggunakan satuan dasar barang.</p></div><Button variant="ghost" size="icon" onClick={() => setCreateOpen(false)}><X className="h-4 w-4" /></Button></div><div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="No. Opname"><Input value="Otomatis saat disimpan" disabled className="font-mono" /></Field><Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH({ ...h, date: v })} /></Field><Field label="Gudang"><Combobox options={masters.opts("warehouses")} value={h.warehouse_id} onChange={(v) => setH({ ...h, warehouse_id: v })} /></Field><Field label="Scope"><Select value={h.scope} onValueChange={(v) => setH({ ...h, scope: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Semua Barang</SelectItem><SelectItem value="division">Per Divisi</SelectItem></SelectContent></Select></Field><Field label="Mode"><Select value={h.mode} onValueChange={(v) => setH({ ...h, mode: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="live">Live</SelectItem><SelectItem value="freeze">Freeze</SelectItem></SelectContent></Select></Field>{h.scope === "division" && <Field label="Divisi"><Combobox options={masters.opts("divisions")} value={h.division_id} onChange={(v) => setH({ ...h, division_id: v })} /></Field>}<Field label="Catatan"><Input value={h.notes || ""} onChange={(e) => setH({ ...h, notes: e.target.value })} /></Field></div><div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran</div><AttachmentPanel entity="opname" entityId={null} /></div><div className="flex justify-end"><Button onClick={create} disabled={!h.warehouse_id}>Ambil Snapshot & Mulai</Button></div></CardContent></Card><DocumentMessageEditor module="opname" value={h.document_message} onChange={(v)=>setH({...h,document_message:v})} useDefault /></div>}

    <div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">No. Opname</th><th className="p-3">Tanggal</th><th className="p-3">Gudang</th><th className="p-3">Mode</th><th className="p-3 text-right">Item</th><th className="p-3">Status</th></tr></thead><tbody>{rows.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-muted-foreground">Belum ada stock opname</td></tr>}{rows.map((r) => <tr key={r.id} onClick={() => openDetail(r.id)} className={`border-t cursor-pointer hover:bg-accent/40 ${detail?.id === r.id ? "bg-primary/5" : ""}`}><td className="p-3 font-mono text-xs font-semibold">{r.no}</td><td className="p-3">{fmtDate(r.date)}</td><td className="p-3">{r.warehouse_name}</td><td className="p-3 capitalize">{r.mode}</td><td className="p-3 text-right">{r.line_count}</td><td className="p-3"><StatusBadge status={r.status} /></td></tr>)}</tbody></table></div>

    {detail && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Workspace Stock Opname</div><div className="mt-1 flex flex-wrap items-center gap-2"><span className="text-xs font-semibold text-muted-foreground">No. Opname</span><h2 className="font-head font-mono text-lg font-semibold">{detail.no}</h2><StatusBadge status={detail.status} /></div><p className="mt-1 text-xs text-muted-foreground">Fisik boleh dihitung dengan satuan kemasan; sistem mengonversi ke satuan dasar saat disimpan.</p><div className="mt-2"><TransactionMutationActions module="opname" id={detail.id} onEdit={()=>setForceEditing(true)} onDeleted={()=>{setDetail(null);load();}} compact /></div></div><Button variant="ghost" size="icon" onClick={() => setDetail(null)}><X className="h-4 w-4" /></Button></div>
      {forceEditing&&<div className="grid grid-cols-1 md:grid-cols-3 gap-3 rounded-lg border p-3"><Field label="Tanggal"><DatePicker value={h.date} onChange={v=>setH({...h,date:v})}/></Field><Field label="Gudang"><Combobox options={masters.opts("warehouses")} value={h.warehouse_id} onChange={v=>setH({...h,warehouse_id:v})}/></Field><Field label="Catatan"><Input value={h.notes||""} onChange={e=>setH({...h,notes:e.target.value})}/></Field></div>}
      <div className="max-h-[560px] overflow-auto border rounded-md"><table className="w-full text-sm zebra min-w-[820px]"><thead className="sticky top-0 bg-muted z-10"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2 min-w-[170px]">Satuan Hitung</th><th className="p-2 text-right">Sistem</th><th className="p-2 w-28">Fisik</th><th className="p-2 text-right">Variance</th></tr></thead><tbody>{detail.lines.map((l) => {
        const uid = countUoms[l.id]; const factor = factorFor(l, uid); const systemDisplay = (Number(l.snapshot) || 0) / factor; const c = counts[l.id]; const physical = c === "" || c == null ? systemDisplay : Number(c); const v = physical - systemDisplay; const editable = forceEditing||["Counting", "Review"].includes(detail.status); const opts = uomOptions(l.item_id);
        return <tr key={l.id} className="border-t"><td className="p-2">{l.item_code} — {l.item_name}</td><td className="p-1.5">{editable ? <Combobox options={opts} value={uid || itemsMap[l.item_id]?.base_uom_id || ""} onChange={(x) => changeUom(l, x)} disabled={opts.length <= 1} /> : (uomLabel(itemsMap[l.item_id]?.base_uom_id) || itemsMap[l.item_id]?.unit || "-")}</td><td className="p-2 text-right tabular-nums">{num(systemDisplay)}</td><td className="p-1.5">{editable ? <Input type="number" step="any" value={c} onChange={(e) => setCounts({ ...counts, [l.id]: e.target.value })} className="h-8 text-right" /> : num(l.counted)}</td><td className={`p-2 text-right tabular-nums font-semibold ${v < 0 ? "text-destructive" : v > 0 ? "text-emerald-600" : ""}`}>{v > 0 ? "+" : ""}{num(v)}</td></tr>;
      })}</tbody></table></div>
      <div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran</div><AttachmentPanel entity="opname" entityId={detail.id} /></div>
      <DocumentMessageEditor module="opname" value={forceEditing?h.document_message:(detail.document_message||"")} onChange={(v)=>setH({...h,document_message:v})} readOnly={!forceEditing} />
      <div className="flex gap-2 flex-wrap border-t pt-3">{forceEditing&&<><Button onClick={saveEdit}><Save className="h-4 w-4 mr-2"/>Simpan Perubahan</Button><Button variant="outline" onClick={()=>openDetail(detail.id)}>Batal Edit</Button></>}{!forceEditing&&["Counting", "Review"].includes(detail.status) && <Button variant="outline" onClick={() => saveCount("Review")}><Save className="h-4 w-4 mr-2" />Simpan Hitung</Button>}{!forceEditing&&detail.status === "Review" && can("submit") && <Button onClick={submit}><Send className="h-4 w-4 mr-2" />Ajukan Approval</Button>}{!forceEditing&&detail.status === "Waiting Approval" && can("post_stock_opname") && <Button onClick={post}><CheckCircle className="h-4 w-4 mr-2" />Approve & Posting</Button>}</div>
    </CardContent></Card>}
  </div>;
}
