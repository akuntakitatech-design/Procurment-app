import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { ItemLines } from "@/components/ItemLines";
import { AttachmentPanel } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeftRight, Plus, ArrowLeft, Paperclip, X } from "lucide-react";
import { fmtDate, todayISO } from "@/lib/format";
import { toast } from "sonner";

const EMPTY = () => ({ date: todayISO(), from_warehouse_id: "", to_warehouse_id: "", project_id: "", notes: "", document_message: null });

export default function Transfer() {
  const masters = useMasters();
  const { can } = useAuth();
  const [rows, setRows] = useState([]);
  const [mode, setMode] = useState("list");
  const [h, setH] = useState(EMPTY());
  const [lines, setLines] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editingId, setEditingId] = useState(null);

  const load = () => api.get("/transfers").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  const openDetail = (id) => api.get(`/transfers/${id}`).then((r) => setSelected(r.data));
  const startNew = () => { setEditingId(null); setH(EMPTY()); setLines([]); setSelected(null); setMode("form"); };
  const startEdit = () => {
    if (!selected) return;
    setEditingId(selected.id);
    setH({ date:selected.date, from_warehouse_id:selected.from_warehouse_id||"", to_warehouse_id:selected.to_warehouse_id||"", project_id:selected.project_id||"", notes:selected.notes||"", document_message:selected.document_message||"" });
    setLines((selected.lines||[]).map(l=>({...l,_readonly:false})));
    setMode("form");
  };

  const save = async () => {
    try {
      const res = editingId
        ? await api.put(`/transactions/transfer/${editingId}`, { ...h, lines })
        : await api.post("/transfers", { ...h, lines });
      const keepId = editingId || res.data.id;
      await saveDocumentMessage("transfer", keepId, h.document_message);
      toast.success(editingId ? "Transfer diperbarui; stok lama direversal lalu diposting ulang" : `Transfer ${res.data.no} diposting`);
      setMode("list"); setLines([]); setH(EMPTY()); setEditingId(null); load();
      if (keepId) openDetail(keepId);
    }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  if (mode === "form") return (
    <div>
      <PageHeader title={editingId ? "Edit Transfer" : "Transfer Baru"} subtitle={editingId ? "Perubahan akan melakukan reversal stok lama lalu posting ulang" : "Perpindahan barang permanen antar gudang"}>
        <Button variant="outline" onClick={() => { setMode("list"); setEditingId(null); }}><ArrowLeft className="h-4 w-4 mr-2" />Kembali</Button>
        <Button onClick={save} disabled={lines.length === 0}>{editingId ? "Simpan Perubahan" : "Posting Transfer"}</Button>
      </PageHeader>
      <div className="space-y-4"><Card><CardContent className="pt-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Field label="No. Transfer"><Input value={editingId ? selected?.no || "" : "Otomatis saat disimpan"} disabled className="font-mono" /></Field>
          <Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH({ ...h, date: v })} testid="trf-date" /></Field>
          <Field label="Gudang Asal"><Combobox options={masters.opts("warehouses")} value={h.from_warehouse_id} onChange={(v) => setH({ ...h, from_warehouse_id: v })} testid="trf-from" /></Field>
          <Field label="Gudang Tujuan"><Combobox options={masters.opts("warehouses")} value={h.to_warehouse_id} onChange={(v) => setH({ ...h, to_warehouse_id: v })} testid="trf-to" /></Field>
          <Field label="Proyek"><Combobox options={masters.opts("projects")} value={h.project_id} onChange={(v) => setH({ ...h, project_id: v })} /></Field>
          <Field label="Keterangan"><Input value={h.notes} onChange={(e) => setH({ ...h, notes: e.target.value })} /></Field>
        </div>
        <ItemLines lines={lines} onChange={setLines} masters={masters} fields={{ project: true, unit: true, notes: true }} />
        <div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran</div><AttachmentPanel entity="transfer" entityId={editingId} /></div>
      </CardContent></Card><DocumentMessageEditor module="transfer" value={h.document_message} onChange={(v)=>setH({...h,document_message:v})} useDefault={!editingId} /></div>
    </div>
  );

  return (
    <div>
      <PageHeader title="Transfer Antar Gudang" subtitle="Perpindahan barang permanen">{can("create") && <Button onClick={startNew} data-testid="transfer-create-btn"><Plus className="h-4 w-4 mr-2" />Buat Transfer</Button>}</PageHeader>
      <div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">No. Transfer</th><th className="p-3">Tanggal</th><th className="p-3">Dari</th><th className="p-3">Ke</th><th className="p-3 text-right">Item</th><th className="p-3">Status</th></tr></thead><tbody>{rows.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-muted-foreground">Belum ada transfer</td></tr>}{rows.map((r) => (<tr key={r.id} onClick={() => openDetail(r.id)} className={`border-t cursor-pointer hover:bg-accent/40 ${selected?.id === r.id ? "bg-primary/5" : ""}`}><td className="p-3 font-mono text-xs font-semibold">{r.no}</td><td className="p-3">{fmtDate(r.date)}</td><td className="p-3">{r.from_name}</td><td className="p-3 flex items-center gap-1"><ArrowLeftRight className="h-3 w-3 text-muted-foreground" />{r.to_name}</td><td className="p-3 text-right">{r.line_count}</td><td className="p-3"><StatusBadge status={r.status} /></td></tr>))}</tbody></table></div>
      {selected && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Detail Transaksi</div><div className="mt-1 font-mono font-semibold">{selected.no}</div><div className="mt-2"><TransactionMutationActions module="transfer" id={selected.id} onEdit={startEdit} onDeleted={()=>{setSelected(null);load();}} compact /></div></div><Button variant="ghost" size="icon" onClick={() => setSelected(null)}><X className="h-4 w-4" /></Button></div><AttachmentPanel entity="transfer" entityId={selected.id} /><DocumentMessageEditor module="transfer" value={selected.document_message||""} readOnly /></CardContent></Card>}
    </div>
  );
}
