import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { useMasters, STOCK_REFS } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { ItemLines } from "@/components/ItemLines";
import { AttachmentPanel } from "@/components/DocMeta";
import { DocumentMessageEditor, saveDocumentMessage } from "@/components/DocumentMessageEditor";
import { TransactionMutationActions } from "@/components/TransactionMutationActions";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox } from "@/components/MasterRefCombobox";
import { DivisionField } from "@/components/DivisionField";
import { divisionError, lineQtyError } from "@/lib/txnValidation";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeftRight, Plus, ArrowLeft, Paperclip, X } from "lucide-react";
import { fmtDate, todayISO } from "@/lib/format";
import { toast } from "sonner";
import { TxnList } from "@/components/TxnList";
import { traceCol, noCol, dateCol } from "@/lib/txnList";


const EMPTY = () => ({ date: todayISO(), division_id: "", from_warehouse_id: "", to_warehouse_id: "", project_id: "", notes: "", document_message: null });

export default function Transfer() {
  const [mode, setMode] = useState("list"); const masters = useMasters(mode === "list" ? [] : STOCK_REFS);
  const { can } = useAuth();
  const list = useServerList("/transfers");
  
  const [h, setH] = useState(EMPTY());
  const [lines, setLines] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editingId, setEditingId] = useState(null);

  const load = () => list.reload();
  const openDetail = (id) => api.get(`/transfers/${id}`).then((r) => setSelected(r.data));
  const startNew = () => { setEditingId(null); setH(EMPTY()); setLines([]); setSelected(null); setMode("form"); };
  const startEdit = (doc = selected) => {
    if (!doc) return;
    const selected = doc;
    setSelected(doc);
    setEditingId(selected.id);
    setH({ date:selected.date, division_id:selected.division_id||"", from_warehouse_id:selected.from_warehouse_id||"", to_warehouse_id:selected.to_warehouse_id||"", project_id:selected.project_id||"", notes:selected.notes||"", document_message:selected.document_message||"" });
    setLines((selected.lines||[]).map(l=>({...l,_readonly:false})));
    setMode("form");
  };

  const [divErr, setDivErr] = useState(null);
  const save = async () => {
    { const de=divisionError(h.division_id);if(de){setDivErr(de);toast.error(de);return;}setDivErr(null);const qe=lineQtyError(lines);if(qe){toast.error(qe);return;} }
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
      <TransactionPageHeader type="transfer" mode={editingId ? "edit" : "new"} number={selected?.no} showNumberField subtitle={editingId ? "Perubahan akan melakukan reversal stok lama lalu posting ulang" : undefined}>
        <Button variant="outline" onClick={() => { setMode("list"); setEditingId(null); }}><ArrowLeft className="h-4 w-4 mr-2" />Kembali</Button>
        <Button onClick={save} disabled={lines.length === 0}>{editingId ? "Simpan Perubahan" : "Posting Transfer"}</Button>
      </TransactionPageHeader>
      <div className="space-y-4"><Card><CardContent className="pt-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Field label="No. Transfer"><Input value={editingId ? selected?.no || "" : "Otomatis saat disimpan"} disabled className="font-mono" /></Field>
          <Field label="Tanggal"><DatePicker value={h.date} onChange={(v) => setH({ ...h, date: v })} testid="trf-date" /></Field>
          <DivisionField testid="trf-division-field" options={masters.opts("divisions")} value={h.division_id} onChange={(v) => { setH({ ...h, division_id: v }); setDivErr(null); }} error={divErr} />
          <Field label="Gudang Asal"><Combobox options={masters.opts("warehouses")} value={h.from_warehouse_id} onChange={(v) => setH({ ...h, from_warehouse_id: v })} testid="trf-from" /></Field>
          <Field label="Gudang Tujuan"><Combobox options={masters.opts("warehouses")} value={h.to_warehouse_id} onChange={(v) => setH({ ...h, to_warehouse_id: v })} testid="trf-to" /></Field>
          <Field label="Proyek"><MasterProjectCombobox masters={masters} options={masters.opts("projects")} value={h.project_id} onChange={(v) => setH((s) => ({ ...s, project_id: v }))} testid="trf-project" /></Field>
          <Field label="Keterangan"><Input value={h.notes} onChange={(e) => setH({ ...h, notes: e.target.value })} /></Field>
        </div>
        <ItemLines lines={lines} onChange={setLines} masters={masters} fields={{ project: true, unit: true, notes: true }} stockWarehouse={() => h.from_warehouse_id} testidPrefix="trf" />
        <div className="rounded-xl border bg-card p-4"><div className="mb-3 flex items-center gap-2 font-head text-sm font-semibold"><Paperclip className="h-4 w-4" />Lampiran</div><AttachmentPanel entity="transfer" entityId={editingId} /></div>
      </CardContent></Card><DocumentMessageEditor module="transfer" value={h.document_message} onChange={(v)=>setH({...h,document_message:v})} useDefault={!editingId} /></div>
    </div>
  );

  return (
    <div>
      <TransactionPageHeader type="transfer" mode={selected ? "view" : "list"} number={selected?.no}>{can("create") && <Button onClick={startNew} data-testid="transfer-create-btn"><Plus className="h-4 w-4 mr-2" />Buat Transfer</Button>}</TransactionPageHeader>
      <TxnList module="transfer" testidPrefix="transfer" server={list} onReload={() => { setSelected(null); load(); }} selectedId={selected?.id} emptyText="Belum ada transfer" minWidth={1100}
        onOpen={(r) => openDetail(r.id)} onEdit={async (r) => { const d = await api.get(`/transfers/${r.id}`); startEdit(d.data); }}
        columns={[noCol("No. Transfer"), dateCol(fmtDate), { key: "from_name", label: "Dari" }, { key: "to_name", label: "Ke", render: (r) => <span className="flex items-center gap-1"><ArrowLeftRight className="h-3 w-3 text-muted-foreground" />{r.to_name}</span> }, traceCol("project"), traceCol("unit"), { key: "line_count", label: "Item", num: true }, { key: "status", label: "Status", status: true }]} />
      {selected && <Card className="mt-4 border-primary/20"><CardContent className="pt-5 space-y-4"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-wider text-primary">Detail Transaksi</div><div className="mt-1 font-mono font-semibold">{selected.no}</div><div className="mt-2"><TransactionMutationActions module="transfer" id={selected.id} onEdit={()=>startEdit()} onDeleted={()=>{setSelected(null);load();}} compact /></div></div><Button variant="ghost" size="icon" onClick={() => setSelected(null)}><X className="h-4 w-4" /></Button></div><AttachmentPanel entity="transfer" entityId={selected.id} /><DocumentMessageEditor module="transfer" value={selected.document_message||""} readOnly /></CardContent></Card>}
    </div>
  );
}
