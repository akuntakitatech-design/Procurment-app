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
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, ArrowLeft, Trash2, Paperclip, X } from "lucide-react";
import { fmtDate, num, todayISO } from "@/lib/format";
import { toast } from "sonner";

const TYPES = ["Rusak", "Hilang", "Expired", "Koreksi", "Selisih", "Ditemukan", "Lainnya"];
const EMPTY = () => ({ date: todayISO(), warehouse_id: "", division_id: "", adj_type: "Koreksi", reason: "", notes: "", document_message: null });

export default function Adjustment() {
  const masters = useMasters(); const { can } = useAuth();
  const [rows, setRows] = useState([]); const [mode, setMode] = useState("list");
  const [h, setH] = useState(EMPTY());
  const [lines, setLines] = useState([]); const [selected, setSelected] = useState(null); const [editingId,setEditingId]=useState(null);
  const itemsMap = masters.map("items"); const uomsMap = masters.map("uoms");
  const itemOpts = masters.opts("items", (d) => `${d.code} — ${d.name}`);
  const uomLabel = (id) => { const u = uomsMap[id]; return u ? (u.symbol || u.name || u.code) : ""; };
  const uomOptions = (itemId) => {
    const it = itemsMap[itemId]; if (!it) return [];
    if (!it.base_uom_id) return it.unit ? [{ value: `legacy:${it.unit}`, label: it.unit, factor: 1 }] : [];
    const seen = new Set();
    return [{ uom_id: it.base_uom_id, factor: 1, is_base: true }, ...(it.uoms || [])]
      .filter((r) => r.uom_id && !seen.has(r.uom_id) && seen.add(r.uom_id))
      .map((r) => { const u = uomsMap[r.uom_id] || {}; return { value: r.uom_id, factor: Number(r.factor) || 1, label: `${u.name || u.code || "Satuan"}${u.symbol ? ` (${u.symbol})` : ""}${r.is_base ? " — Dasar" : ` — 1 = ${num(r.factor)} ${uomLabel(it.base_uom_id)}`}` }; });
  };

  const load = () => api.get("/adjustments").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  const openDetail = (id) => api.get(`/adjustments/${id}`).then((r) => setSelected(r.data));
  const startNew=()=>{setEditingId(null);setH(EMPTY());setLines([]);setSelected(null);setMode("form");};
  const startEdit=()=>{if(!selected)return;setEditingId(selected.id);setH({date:selected.date,warehouse_id:selected.warehouse_id||"",division_id:selected.division_id||"",adj_type:selected.adj_type||"Koreksi",reason:selected.reason||"",notes:selected.notes||"",document_message:selected.document_message||""});setLines((selected.lines||[]).map(l=>({item_id:l.item_id,adjustment:l.adjustment,uom_id:itemsMap[l.item_id]?.base_uom_id||"",conversion_factor:1,reason:l.reason||""})));setMode("form");};
  const addRow = () => setLines([...lines, { item_id: "", adjustment: 0, uom_id: "", conversion_factor: 1, reason: "" }]);
  const upd = (i, patch) => setLines((cur) => cur.map((l, x) => {
    if (x !== i) return l;
    if (patch.item_id) { const it = itemsMap[patch.item_id]; return { ...l, ...patch, uom_id: it?.base_uom_id || "", conversion_factor: 1 }; }
    if (patch.uom_id !== undefined) { const opt = uomOptions(l.item_id).find((o) => o.value === patch.uom_id); return { ...l, uom_id: patch.uom_id, conversion_factor: Number(opt?.factor) || 1 }; }
    return { ...l, ...patch };
  }));

  const save = async () => {
    try {
      const baseLines = lines.map((l) => ({ ...l, adjustment: (Number(l.adjustment) || 0) * (Number(l.conversion_factor) || 1) }));
      const res = editingId ? await api.put(`/transactions/adjustment/${editingId}`, { ...h, lines: baseLines }) : await api.post("/adjustments", { ...h, lines: baseLines });
      const keep=editingId||res.data.id;
      await saveDocumentMessage("adjustment",keep,h.document_message);
      toast.success(editingId ? "Adjustment diperbarui; efek stok lama direversal lalu diposting ulang" : `Adjustment ${res.data.no} diposting dalam satuan dasar`);
      setMode("list");setLines([]);setH(EMPTY());setEditingId(null);load();if(keep)openDetail(keep);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  if (mode === "form") return <div>
    <PageHeader title={editingId?"Edit Stock Adjustment":"Stock Adjustment Baru"} subtitle={editingId?"Perubahan akan direversal dan diposting ulang":"Penyesuaian stok (plus/minus)"}><Button variant="outline" onClick={() => {setMode("list");setEditingId(null);}}><ArrowLeft className="h-4 w-4 mr-2" />Kembali</Button><Button onClick={save} disabled={lines.length === 0}>{editingId?"Simpan Perubahan":"Posting"}</Button></PageHeader>
    <div className="space-y-4"><Card><CardContent className="pt-6 space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"><Field label="No. Adjustment"><Input value={editingId?selected?.no||"":"Otomatis saat disimpan"} disabled className="font-mono" /></Field><Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH({ ...h, date: v })} /></Field><Field label="Gudang"><Combobox options={masters.opts("warehouses")} value={h.warehouse_id} onChange={(v) => setH({ ...h, warehouse_id: v })} /></Field><Field label="Divisi"><Combobox options={masters.opts("divisions")} value={h.division_id} onChange={(v) => setH({ ...h, division_id: v })} /></Field><Field label="Jenis"><Select value={h.adj_type} onValueChange={(v) => setH({ ...h, adj_type: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select></Field><Field label="Alasan"><Input value={h.reason} onChange={(e) => setH({ ...h, reason: e.target.value })} /></Field></div>
      <div className="border rounded-md overflow-x-auto bg-card"><table className="w-full text-sm min-w-[760px]"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-2 min-w-[240px]">Barang</th><th className="p-2 w-32">Adjustment (+/-)</th><th className="p-2 min-w-[170px]">Satuan</th><th className="p-2">Alasan</th><th className="p-2 w-10"></th></tr></thead><tbody>{lines.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">Belum ada item</td></tr>}{lines.map((l, i) => <tr key={i} className="border-t"><td className="p-1.5"><Combobox options={itemOpts} value={l.item_id} onChange={(v) => upd(i, { item_id: v })} /></td><td className="p-1.5"><Input type="number" step="any" value={l.adjustment} onChange={(e) => upd(i, { adjustment: e.target.value })} className="h-9 text-right" /></td><td className="p-1.5"><Combobox options={uomOptions(l.item_id)} value={l.uom_id || itemsMap[l.item_id]?.base_uom_id || ""} onChange={(v) => upd(i, { uom_id: v })} disabled={!l.item_id} /><div className="mt-1 text-[10px] text-muted-foreground">Terhitung stok: {num((Number(l.adjustment) || 0) * (Number(l.conversion_factor) || 1))} {uomLabel(itemsMap[l.item_id]?.base_uom_id) || itemsMap[l.item_id]?.unit}</div></td><td className="p-1.5"><Input value={l.reason} onChange={(e) => upd(i, { reason: e.target.value })} className="h-9" /></td><td className="p-1.5"><Button variant="ghost" size="icon" onClick={() => setLines(lines.filter((_, x) => x !== i))}><Trash2 className="h-4 w-4 text-destructive" /></Button></td></tr>)}</tbody></table></div>
      <Button variant="outline" size="sm" onClick={addRow}><Plus className="h-4 w-4 mr-2" />Tambah Baris</Button>
      <div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran</div><AttachmentPanel entity="adjustment" entityId={editingId} /></div>
    </CardContent></Card><DocumentMessageEditor module="adjustment" value={h.document_message} onChange={(v)=>setH({...h,document_message:v})} useDefault={!editingId} /></div>
  </div>;

  return <div><PageHeader title="Stock Adjustment" subtitle="Koreksi, rusak, hilang, expired, selisih">{can("stock_adjustment") && <Button onClick={startNew}><Plus className="h-4 w-4 mr-2" />Buat Adjustment</Button>}</PageHeader><div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">No. Adjustment</th><th className="p-3">Tanggal</th><th className="p-3">Gudang</th><th className="p-3">Jenis</th><th className="p-3">Alasan</th><th className="p-3 text-right">Item</th></tr></thead><tbody>{rows.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-muted-foreground">Belum ada adjustment</td></tr>}{rows.map((r) => <tr key={r.id} onClick={() => openDetail(r.id)} className={`border-t cursor-pointer hover:bg-accent/40 ${selected?.id === r.id ? "bg-primary/5" : ""}`}><td className="p-3 font-mono text-xs font-semibold">{r.no}</td><td className="p-3">{fmtDate(r.date)}</td><td className="p-3">{r.warehouse_name}</td><td className="p-3">{r.adj_type}</td><td className="p-3">{r.reason}</td><td className="p-3 text-right">{r.line_count}</td></tr>)}</tbody></table></div>{selected && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Detail Transaksi</div><div className="mt-1 font-mono font-semibold">{selected.no}</div><div className="mt-2"><TransactionMutationActions module="adjustment" id={selected.id} onEdit={startEdit} onDeleted={()=>{setSelected(null);load();}} compact /></div></div><Button variant="ghost" size="icon" onClick={() => setSelected(null)}><X className="h-4 w-4" /></Button></div><AttachmentPanel entity="adjustment" entityId={selected.id} /><DocumentMessageEditor module="adjustment" value={selected.document_message||""} readOnly /></CardContent></Card>}</div>;
}
