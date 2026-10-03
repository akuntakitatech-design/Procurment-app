import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { API, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Combobox } from "@/components/Combobox";
import { Field } from "@/components/DatePicker";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ListPager, SortTh } from "@/components/ListPager";
import { MasterDeleteDialog } from "@/components/MasterDeleteDialog";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Plus, Search, Pencil, ArrowLeft, FileText, Upload, Trash2, Download, ShieldCheck,
  Handshake, Tag, History, ListChecks, Calculator, CheckCircle2,
  Ban, Package,
} from "lucide-react";
import { toast } from "sonner";

const rupiah = (v) => "Rp " + (Number(v || 0)).toLocaleString("id-ID");
const parseMoney = (s) => {
  const n = String(s ?? "").replace(/[^\d]/g, "");
  return n === "" ? "" : Number(n);
};
const fmtDate = (d) => (d ? new Date(d).toLocaleString("id-ID") : "-");

const STATUS_OPTS = [
  { value: "", label: "Semua Status" },
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
];
const CURRENCY_OPTS = [
  { value: "IDR", label: "IDR" }, { value: "USD", label: "USD" },
  { value: "EUR", label: "EUR" }, { value: "SGD", label: "SGD" }, { value: "CNY", label: "CNY" },
];
const DISCOUNT_OPTS = [
  { value: "NONE", label: "Tanpa Diskon" },
  { value: "PERCENT", label: "Persentase (%)" },
  { value: "AMOUNT", label: "Nominal (Rp)" },
];
const TOLERANCE_OPTS = [
  { value: "USE_CONTRACT_DEFAULT", label: "Ikuti Default Kontrak" },
  { value: "CUSTOM", label: "Custom" },
];

const VC_BADGE = {
  draft: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
  active: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800",
  expired: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800",
  cancelled: "bg-slate-200 text-slate-500 line-through border-slate-300 dark:bg-slate-800 dark:text-slate-500",
};
const VC_LABEL = { draft: "Draft", active: "Active", expired: "Expired", cancelled: "Cancelled" };
function VcBadge({ status }) {
  const k = String(status || "").toLowerCase();
  return <span data-testid={`vc-status-${k}`} className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${VC_BADGE[k] || VC_BADGE.draft}`}>{VC_LABEL[k] || status}</span>;
}

function MoneyInput({ value, onChange, ...props }) {
  return <Input inputMode="numeric" value={value === "" || value == null ? "" : Number(value).toLocaleString("id-ID")}
    onChange={(e) => onChange(parseMoney(e.target.value))} {...props} />;
}

// Stable module-scope section (prevents input focus loss on re-render).
function FormSection({ title, icon: Icon, children, desc }) {
  return (
    <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
      <div className="flex items-center gap-2"><Icon className="h-4 w-4 text-primary" /><h3 className="font-head font-semibold">{title}</h3></div>
      {desc && <p className="text-xs text-muted-foreground -mt-2">{desc}</p>}
      {children}
    </div>
  );
}

function netPreview(base, dtype, dval) {
  const b = Number(base || 0);
  if (dtype === "PERCENT") return Math.max(0, b - Math.round((b * Number(dval || 0)) / 100));
  if (dtype === "AMOUNT") return Math.max(0, b - Number(dval || 0));
  return b;
}

function showErr(e) {
  const d = e?.response?.data?.detail;
  if (d && typeof d === "object" && d.message) {
    const cf = (d.conflicts || []).map((c) => c.contract_number).filter(Boolean).join(", ");
    toast.error(d.message + (cf ? ` — Konflik: ${cf}` : ""));
  } else {
    toast.error(apiError(d));
  }
}

/* ============================== LIST ============================== */
export function VendorContractList() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [sel, setSel] = useState(new Set()); const [delRows, setDelRows] = useState(null);
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 20 });
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [currency, setCurrency] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState("-created_at");
  const [suppliers, setSuppliers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [checkOpen, setCheckOpen] = useState(false);

  useEffect(() => { api.get("/lookup/suppliers").then((r) => setSuppliers(r.data || [])).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ q, status, supplier_id: supplierId, currency, sort, page: String(page), page_size: String(pageSize) });
      const r = await api.get(`/vendor-contracts?${params.toString()}`);
      setData(r.data || { items: [], total: 0 });
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [q, status, supplierId, currency, sort, page, pageSize]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);
  useEffect(() => { setSel(new Set()); }, [q, status, supplierId, currency, sort, page, pageSize]);

  const sortObj = { key: sort.replace(/^-/, ""), dir: sort.startsWith("-") ? "desc" : "asc" };
  const toggleSort = (key) => { setPage(1); setSort((s) => (s === key ? `-${key}` : s === `-${key}` ? key : `-${key}`)); };
  const th = (label, k, cls = "") => <SortTh label={label} k={k} sort={sortObj} onSort={toggleSort} className={cls} testid="vendor_contracts" />;

  return (
    <div>
      <PageHeader title="Kontrak Harga Vendor" subtitle="Master kontrak harga vendor sebagai sumber harga referensi resmi Procurement">
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setCheckOpen(true)} data-testid="vc-check-price-btn"><Calculator className="h-4 w-4 mr-2" />Cek Harga</Button>
          {can("vendor_contract:manage") && <Button onClick={() => nav("/vendor-contracts/new")} data-testid="vc-add-btn"><Plus className="h-4 w-4 mr-2" />Tambah Kontrak</Button>}
        </div>
      </PageHeader>

      <div className="flex flex-col lg:flex-row gap-3 mb-4">
        <div className="relative flex-1 max-w-md"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => { setPage(1); setQ(e.target.value); }} placeholder="Cari No Kontrak, vendor, PIC..." className="pl-9" data-testid="vc-search" /></div>
        <div className="w-full sm:w-56"><Combobox options={[{ value: "", label: "Semua Vendor" }, ...suppliers.map((s) => ({ value: s.id, label: s.name }))]} value={supplierId} onChange={(v) => { setPage(1); setSupplierId(v); }} placeholder="Vendor" /></div>
        <div className="w-full sm:w-44"><Combobox options={STATUS_OPTS} value={status} onChange={(v) => { setPage(1); setStatus(v); }} placeholder="Status" /></div>
        <div className="w-full sm:w-36"><Combobox options={[{ value: "", label: "Semua Mata Uang" }, ...CURRENCY_OPTS]} value={currency} onChange={(v) => { setPage(1); setCurrency(v); }} placeholder="Mata Uang" /></div>
      </div>

      {sel.size>0&&<div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm" data-testid="vendor_contracts-selection-bar"><span className="font-semibold" data-testid="vendor_contracts-selected-count">{sel.size} dipilih</span>{sel.size===1&&can("vendor_contract:manage")&&<Button size="sm" variant="outline" data-testid="vendor_contracts-bar-edit" onClick={()=>{const r=data.items.find((x)=>sel.has(x.id));if(r)nav(`/vendor-contracts/${r.id}/edit`);}}><Pencil className="mr-1.5 h-3.5 w-3.5" />Edit</Button>}{can("delete")&&<Button size="sm" variant="outline" data-testid="vendor_contracts-bar-delete" onClick={()=>setDelRows(data.items.filter((x)=>sel.has(x.id)).map((r)=>({id:r.id,label:[r.contract_number, r.supplier_name].filter(Boolean).join(" — ")})))}><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />{sel.size===1?"Hapus":"Hapus Massal"}</Button>}<Button size="sm" variant="ghost" className="ml-auto" onClick={()=>setSel(new Set())} data-testid="vendor_contracts-clear-selection">Batal pilih</Button></div>}<MasterDeleteDialog open={!!delRows} rows={delRows||[]} checkName="vendor_contracts" entityLabel="Kontrak Harga Vendor" onDeselect={(ids)=>setSel((c)=>new Set([...c].filter((x)=>!ids.includes(x))))} onClose={()=>setDelRows(null)} onDone={()=>{setDelRows(null);setSel(new Set());load();}} />
      <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-sm zebra">
          <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="w-10 p-3"><Checkbox checked={data.items.length>0&&data.items.every((x)=>sel.has(x.id))} onCheckedChange={()=>setSel(data.items.every((x)=>sel.has(x.id))?new Set():new Set(data.items.map((x)=>x.id)))} aria-label="Pilih semua" data-testid="vendor_contracts-select-all" /></th>
            {th("No Kontrak", "contract_number")}{th("Vendor", "supplier_name")}{th("Periode", "start_date")}
            {th("Mata Uang", "currency")}{th("Jml Item", "item_count", "text-right")}{th("PIC", "vendor_pic")}
            {th("Terakhir Diperbarui", "updated_at")}{th("Status", "derived_status")}<th className="p-3 w-44 text-right">Aksi</th>
          </tr></thead>
          <tbody>
            {loading && <tr><td colSpan={9} className="p-8 text-center text-muted-foreground">Memuat...</td></tr>}
            {!loading && data.items.length === 0 && <tr><td colSpan={9} className="p-8 text-center text-muted-foreground">Belum ada kontrak harga vendor</td></tr>}
            {!loading && data.items.map((r) => (
              <tr key={r.id} className="border-t hover:bg-accent/40 cursor-pointer transition-colors" onClick={() => nav(`/vendor-contracts/${r.id}`)} data-testid={`vc-row-${r.contract_number}`}>
                <td className="p-3" onClick={(e)=>e.stopPropagation()}><Checkbox checked={sel.has(r.id)} onCheckedChange={()=>setSel((c)=>{const n=new Set(c);n.has(r.id)?n.delete(r.id):n.add(r.id);return n;})} data-testid={`vendor_contracts-select-${r.contract_number}`} /></td>
                <td className="p-3 font-mono text-xs font-semibold">{r.contract_number}</td>
                <td className="p-3">{r.supplier_name || "-"}</td>
                <td className="p-3 text-xs text-muted-foreground">{r.start_date} s/d {r.end_date}</td>
                <td className="p-3">{r.currency}</td>
                <td className="p-3 text-right">{r.item_count ?? 0}</td>
                <td className="p-3 text-muted-foreground">{r.vendor_pic || "-"}</td>
                <td className="p-3 text-xs text-muted-foreground">{fmtDate(r.updated_at)}</td>
                <td className="p-3"><VcBadge status={r.derived_status} /></td>
                <td className="p-3" onClick={(e)=>e.stopPropagation()}><div className="flex justify-end gap-1">{can("vendor_contract:manage")&&<Button variant="ghost" size="sm" className="h-8" onClick={()=>nav(`/vendor-contracts/${r.id}/edit`)} data-testid={`vendor_contracts-edit-${r.contract_number}`}><Pencil className="mr-1 h-3.5 w-3.5" />Edit</Button>}{can("delete")&&<Button variant="ghost" size="sm" className="h-8 text-destructive hover:text-destructive" onClick={()=>setDelRows([{id:r.id,label:[ r.contract_number, r.supplier_name].filter(Boolean).join(" — ")}])} data-testid={`vendor_contracts-delete-${r.contract_number}`}><Trash2 className="mr-1 h-3.5 w-3.5" />Hapus</Button>}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ListPager total={data.total} page={data.page || page} pageSize={pageSize} setPage={setPage} setPageSize={(n) => { setPage(1); setPageSize(n); }} testid="vendor_contracts" unit="kontrak" />

      <PriceCheckDialog open={checkOpen} onOpenChange={setCheckOpen} suppliers={suppliers} />
    </div>
  );
}

/* ============================== PRICE CHECK (Resolver) ============================== */
function PriceCheckDialog({ open, onOpenChange, suppliers }) {
  const [items, setItems] = useState([]);
  const [uoms, setUoms] = useState([]);
  const [f, setF] = useState({ vendor_id: "", item_id: "", uom_id: "", date: "", qty: "" });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  useEffect(() => {
    if (!open) return;
    api.get("/lookup/items").then((r) => setItems(r.data || [])).catch(() => {});
    api.get("/lookup/uoms").then((r) => setUoms(r.data || [])).catch(() => {});
    setResult(null);
  }, [open]);

  const check = async () => {
    if (!f.vendor_id || !f.item_id || !f.uom_id) { toast.error("Vendor, Item, dan UOM wajib dipilih"); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams({ vendor_id: f.vendor_id, item_id: f.item_id, uom_id: f.uom_id });
      if (f.date) params.set("date", f.date);
      if (f.qty) params.set("qty", String(f.qty));
      const r = await api.get(`/vendor-contracts/resolve-price?${params.toString()}`);
      setResult(r.data);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader><DialogTitle>Cek Harga Kontrak (Effective Price Resolver)</DialogTitle>
          <DialogDescription>Menampilkan harga kontrak aktif yang berlaku untuk kombinasi Vendor + Item + UOM pada tanggal transaksi.</DialogDescription></DialogHeader>
        <div className="grid md:grid-cols-2 gap-3">
          <Field label="Vendor *"><Combobox testid="vc-check-vendor" options={suppliers.map((s) => ({ value: s.id, label: s.name }))} value={f.vendor_id} onChange={(v) => set("vendor_id", v)} placeholder="Pilih vendor" /></Field>
          <Field label="Barang/Jasa *"><Combobox testid="vc-check-item" options={items.map((i) => ({ value: i.id, label: i.name }))} value={f.item_id} onChange={(v) => set("item_id", v)} placeholder="Pilih barang" /></Field>
          <Field label="UOM *"><Combobox testid="vc-check-uom" options={uoms.map((u) => ({ value: u.id, label: u.name || u.symbol }))} value={f.uom_id} onChange={(v) => set("uom_id", v)} placeholder="Pilih UOM" /></Field>
          <Field label="Tanggal Transaksi"><Input type="date" value={f.date} onChange={(e) => set("date", e.target.value)} /></Field>
          <Field label="Qty (opsional, untuk tier Min Qty)"><Input type="number" min="0" value={f.qty} onChange={(e) => set("qty", e.target.value)} /></Field>
        </div>
        <Button onClick={check} disabled={loading} data-testid="vc-check-run" className="w-fit"><Calculator className="h-4 w-4 mr-2" />{loading ? "Mencari..." : "Cek Harga"}</Button>
        {result && (result.found ? (
          <div className="rounded-xl border bg-emerald-50/50 dark:bg-emerald-950/20 p-4 text-sm space-y-1" data-testid="vc-check-result">
            <div className="font-semibold text-emerald-700 dark:text-emerald-300">Harga ditemukan — Kontrak {result.contract_number}</div>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <div><span className="text-muted-foreground">Base Price:</span> {rupiah(result.base_price)}</div>
              <div><span className="text-muted-foreground">Net Contract Price:</span> <b>{rupiah(result.net_contract_price)}</b></div>
              <div><span className="text-muted-foreground">Tolerance:</span> {result.tolerance_pct}%</div>
              <div><span className="text-muted-foreground">Periode Efektif:</span> {result.effective_start} s/d {result.effective_end}</div>
              <div><span className="text-muted-foreground">Min Qty:</span> {result.min_qty}</div>
              <div><span className="text-muted-foreground">Lead Time:</span> {result.lead_time_days} hari</div>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border bg-muted/30 p-4 text-sm text-muted-foreground" data-testid="vc-check-empty">{result.detail || "Tidak ada harga kontrak aktif yang berlaku."}</div>
        ))}
      </DialogContent>
    </Dialog>
  );
}

/* ============================== FORM (header) ============================== */
export function VendorContractForm() {
  const nav = useNavigate();
  const { id } = useParams();
  const editing = !!id;
  const [form, setForm] = useState({
    contract_number: "", supplier_id: "", contract_date: "", start_date: "", end_date: "",
    currency: "IDR", contract_type: "", vendor_pic: "", payment_term: "", default_tolerance_pct: "", notes: "",
  });
  const [suppliers, setSuppliers] = useState([]);
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  useEffect(() => {
    api.get("/lookup/suppliers").then((r) => setSuppliers(r.data || [])).catch(() => {});
    if (editing) api.get(`/vendor-contracts/${id}`).then((r) => {
      const d = r.data;
      if (d.status !== "draft") { toast.error("Hanya kontrak Draft yang dapat diedit"); nav(`/vendor-contracts/${id}`); return; }
      setForm({
        contract_number: d.contract_number || "", supplier_id: d.supplier_id || "",
        contract_date: d.contract_date || "", start_date: d.start_date || "", end_date: d.end_date || "",
        currency: d.currency || "IDR", contract_type: d.contract_type || "", vendor_pic: d.vendor_pic || "",
        payment_term: d.payment_term || "", default_tolerance_pct: d.default_tolerance_pct ?? "", notes: d.notes || "",
      });
    }).catch((e) => toast.error(apiError(e.response?.data?.detail)));
  }, [id, editing, nav]);

  const submit = async () => {
    if (!form.contract_number || !form.supplier_id || !form.start_date || !form.end_date) {
      toast.error("Nomor Kontrak, Vendor, Tanggal Mulai & Berakhir wajib diisi"); return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        supplier_name: suppliers.find((s) => s.id === form.supplier_id)?.name || null,
        default_tolerance_pct: form.default_tolerance_pct === "" ? 0 : Number(form.default_tolerance_pct),
      };
      const r = editing ? await api.put(`/vendor-contracts/${id}`, payload) : await api.post("/vendor-contracts", payload);
      toast.success(editing ? "Kontrak diperbarui" : `Kontrak dibuat — ${r.data.contract_number}`);
      nav(`/vendor-contracts/${r.data.id || id}`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <div>
      <PageHeader title={editing ? "Edit Kontrak Vendor" : "Tambah Kontrak Vendor"} subtitle="Header kontrak harga vendor. Item harga ditambahkan pada Detail kontrak setelah disimpan.">
        <Button variant="outline" onClick={() => nav(editing ? `/vendor-contracts/${id}` : "/vendor-contracts")}><ArrowLeft className="h-4 w-4 mr-2" />Kembali</Button>
      </PageHeader>

      <div className="grid gap-4 max-w-4xl">
        <FormSection title="Informasi Kontrak" icon={Handshake}>
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Nomor Kontrak *"><Input value={form.contract_number} onChange={(e) => set("contract_number", e.target.value)} className="font-mono font-semibold" data-testid="vc-number" /></Field>
            <Field label="Vendor *"><Combobox testid="vc-supplier" options={suppliers.map((s) => ({ value: s.id, label: s.name }))} value={form.supplier_id} onChange={(v) => set("supplier_id", v)} placeholder="Pilih vendor" /></Field>
            <Field label="Tanggal Kontrak"><Input type="date" value={form.contract_date || ""} onChange={(e) => set("contract_date", e.target.value)} /></Field>
            <Field label="Jenis Kontrak"><Input value={form.contract_type} onChange={(e) => set("contract_type", e.target.value)} placeholder="Contoh: Harga Satuan, Framework" /></Field>
            <Field label="PIC Vendor"><Input value={form.vendor_pic} onChange={(e) => set("vendor_pic", e.target.value)} /></Field>
            <Field label="Termin Pembayaran"><Input value={form.payment_term} onChange={(e) => set("payment_term", e.target.value)} placeholder="Contoh: 30 Hari" /></Field>
          </div>
        </FormSection>

        <FormSection title="Periode & Komersial" icon={Tag} desc="Periode berlaku kontrak dan ketentuan komersial dasar.">
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Tanggal Mulai Berlaku *"><Input type="date" value={form.start_date || ""} onChange={(e) => set("start_date", e.target.value)} data-testid="vc-start" /></Field>
            <Field label="Tanggal Berakhir *"><Input type="date" value={form.end_date || ""} onChange={(e) => set("end_date", e.target.value)} data-testid="vc-end" /></Field>
            <Field label="Mata Uang *"><Combobox options={CURRENCY_OPTS} value={form.currency} onChange={(v) => set("currency", v)} /></Field>
            <Field label="Toleransi Harga Default (%)"><Input type="number" min="0" max="100" step="any" value={form.default_tolerance_pct} onChange={(e) => set("default_tolerance_pct", e.target.value)} data-testid="vc-tolerance" /></Field>
          </div>
          {form.start_date && form.end_date && form.end_date < form.start_date && <p className="text-xs text-destructive">Tanggal Berakhir tidak boleh sebelum Tanggal Mulai.</p>}
        </FormSection>

        <FormSection title="Catatan" icon={FileText}>
          <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} className="w-full min-h-24 rounded-md border bg-background px-3 py-2 text-sm" placeholder="Catatan internal kontrak" />
          <p className="text-xs text-muted-foreground">Item harga dan dokumen kontrak ditambahkan dari halaman Detail kontrak setelah disimpan.</p>
        </FormSection>

        <div className="flex gap-2">
          <Button onClick={submit} disabled={saving} data-testid="vc-save">{saving ? "Menyimpan..." : "Simpan Kontrak"}</Button>
          <Button variant="outline" onClick={() => nav(editing ? `/vendor-contracts/${id}` : "/vendor-contracts")}>Batal</Button>
        </div>
      </div>
    </div>
  );
}

/* ============================== ITEM DIALOG ============================== */
const blankItem = {
  item_id: "", uom_id: "", min_qty: "", base_price: "", discount_type: "NONE", discount_value: "",
  lead_time_days: "", tolerance_mode: "USE_CONTRACT_DEFAULT", tolerance_pct: "", effective_start: "", effective_end: "",
};
function ItemDialog({ open, onOpenChange, contract, editRow, onSaved }) {
  const [items, setItems] = useState([]);
  const [uoms, setUoms] = useState([]);
  const [f, setF] = useState(blankItem);
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  useEffect(() => {
    if (!open) return;
    api.get("/lookup/items").then((r) => setItems(r.data || [])).catch(() => {});
    api.get("/lookup/uoms").then((r) => setUoms(r.data || [])).catch(() => {});
    setF(editRow ? {
      item_id: editRow.item_id || "", uom_id: editRow.uom_id || "", min_qty: editRow.min_qty ?? "",
      base_price: editRow.base_price ?? "", discount_type: editRow.discount_type || "NONE",
      discount_value: editRow.discount_value ?? "", lead_time_days: editRow.lead_time_days ?? "",
      tolerance_mode: editRow.tolerance_mode || "USE_CONTRACT_DEFAULT", tolerance_pct: editRow.tolerance_pct ?? "",
      effective_start: editRow.effective_start || "", effective_end: editRow.effective_end || "",
    } : blankItem);
  }, [open, editRow]);

  const net = netPreview(f.base_price, f.discount_type, f.discount_value);
  const submit = async () => {
    if (!f.item_id || !f.uom_id) { toast.error("Barang dan UOM wajib dipilih"); return; }
    setSaving(true);
    try {
      const payload = {
        item_id: f.item_id, uom_id: f.uom_id,
        item_name: items.find((i) => i.id === f.item_id)?.name || null,
        item_code: items.find((i) => i.id === f.item_id)?.code || null,
        uom_name: uoms.find((u) => u.id === f.uom_id)?.name || uoms.find((u) => u.id === f.uom_id)?.symbol || null,
        min_qty: f.min_qty === "" ? 0 : Number(f.min_qty),
        base_price: f.base_price === "" ? 0 : Number(f.base_price),
        discount_type: f.discount_type,
        discount_value: f.discount_value === "" ? 0 : Number(f.discount_value),
        lead_time_days: f.lead_time_days === "" ? 0 : Number(f.lead_time_days),
        tolerance_mode: f.tolerance_mode,
        tolerance_pct: f.tolerance_pct === "" ? 0 : Number(f.tolerance_pct),
        effective_start: f.effective_start || null, effective_end: f.effective_end || null,
      };
      if (editRow) await api.put(`/vendor-contracts/${contract.id}/items/${editRow.id}`, payload);
      else await api.post(`/vendor-contracts/${contract.id}/items`, payload);
      toast.success(editRow ? "Item diperbarui" : "Item ditambahkan");
      onOpenChange(false); onSaved?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[92vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{editRow ? "Edit Item Harga" : "Tambah Item Harga"}</DialogTitle>
          <DialogDescription>Kontrak {contract.contract_number} — Net Price dihitung otomatis dari Base Price dan diskon.</DialogDescription></DialogHeader>
        <div className="space-y-4">
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Barang/Jasa *"><Combobox testid="vc-item-item" options={items.map((i) => ({ value: i.id, label: i.name }))} value={f.item_id} onChange={(v) => set("item_id", v)} placeholder="Pilih barang" /></Field>
            <Field label="UOM *"><Combobox testid="vc-item-uom" options={uoms.map((u) => ({ value: u.id, label: u.name || u.symbol }))} value={f.uom_id} onChange={(v) => set("uom_id", v)} placeholder="Pilih satuan" /></Field>
            <Field label="Minimum Qty"><Input type="number" min="0" step="any" value={f.min_qty} onChange={(e) => set("min_qty", e.target.value)} /></Field>
            <Field label="Lead Time (hari)"><Input type="number" min="0" value={f.lead_time_days} onChange={(e) => set("lead_time_days", e.target.value)} /></Field>
          </div>
          <div className="rounded-xl border p-3 space-y-3">
            <div className="text-xs font-semibold">Harga & Diskon</div>
            <div className="grid md:grid-cols-3 gap-3 items-end">
              <Field label="Base Price (Rp) *"><MoneyInput value={f.base_price} onChange={(v) => set("base_price", v)} data-testid="vc-item-base" /></Field>
              <Field label="Tipe Diskon"><Combobox options={DISCOUNT_OPTS} value={f.discount_type} onChange={(v) => set("discount_type", v)} /></Field>
              {f.discount_type === "PERCENT" && <Field label="Diskon (%)"><Input type="number" min="0" max="100" step="any" value={f.discount_value} onChange={(e) => set("discount_value", e.target.value)} data-testid="vc-item-disc" /></Field>}
              {f.discount_type === "AMOUNT" && <Field label="Diskon (Rp)"><MoneyInput value={f.discount_value} onChange={(v) => set("discount_value", v)} data-testid="vc-item-disc" /></Field>}
              {f.discount_type === "NONE" && <div />}
            </div>
            <div className="rounded-lg bg-muted/40 px-3 py-2 text-sm">Net Contract Price: <b data-testid="vc-item-net">{rupiah(net)}</b></div>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Mode Tolerance"><Combobox options={TOLERANCE_OPTS} value={f.tolerance_mode} onChange={(v) => set("tolerance_mode", v)} /></Field>
            {f.tolerance_mode === "CUSTOM"
              ? <Field label="Price Tolerance (%)"><Input type="number" min="0" max="100" step="any" value={f.tolerance_pct} onChange={(e) => set("tolerance_pct", e.target.value)} /></Field>
              : <div className="self-end rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">Mengikuti Default Kontrak: <b>{contract.default_tolerance_pct || 0}%</b></div>}
            <Field label="Effective Start (opsional)"><Input type="date" value={f.effective_start} onChange={(e) => set("effective_start", e.target.value)} /></Field>
            <Field label="Effective End (opsional)"><Input type="date" value={f.effective_end} onChange={(e) => set("effective_end", e.target.value)} /></Field>
          </div>
          <p className="text-xs text-muted-foreground">Jika periode efektif dikosongkan, item mengikuti periode kontrak ({contract.start_date} s/d {contract.end_date}).</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button onClick={submit} disabled={saving} data-testid="vc-item-save">{saving ? "Menyimpan..." : "Simpan Item"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ============================== PRICE CHANGE DIALOG ============================== */
function PriceChangeDialog({ open, onOpenChange, contract, row, onSaved }) {
  const [f, setF] = useState({ base_price: "", discount_type: "NONE", discount_value: "", effective_date: "", reason: "" });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  useEffect(() => {
    if (open && row) setF({ base_price: row.base_price ?? "", discount_type: row.discount_type || "NONE", discount_value: row.discount_value ?? "", effective_date: "", reason: "" });
  }, [open, row]);
  const net = netPreview(f.base_price, f.discount_type, f.discount_value);
  const submit = async () => {
    if (!f.effective_date || !f.reason.trim()) { toast.error("Tanggal efektif dan alasan wajib diisi"); return; }
    setSaving(true);
    try {
      await api.post(`/vendor-contracts/${contract.id}/items/${row.id}/price-change`, {
        base_price: f.base_price === "" ? 0 : Number(f.base_price), discount_type: f.discount_type,
        discount_value: f.discount_value === "" ? 0 : Number(f.discount_value),
        effective_date: f.effective_date, reason: f.reason,
      });
      toast.success("Perubahan harga resmi tercatat"); onOpenChange(false); onSaved?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  if (!row) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle>Perubahan Harga Resmi</DialogTitle>
          <DialogDescription>{row.item_name} ({row.uom_name}) — harga lama Net {rupiah(row.net_price)}. Perubahan ini tersimpan di histori harga (bukan Price Override).</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div className="grid md:grid-cols-3 gap-3 items-end">
            <Field label="Base Price Baru (Rp)"><MoneyInput value={f.base_price} onChange={(v) => set("base_price", v)} data-testid="vc-pc-base" /></Field>
            <Field label="Tipe Diskon"><Combobox options={DISCOUNT_OPTS} value={f.discount_type} onChange={(v) => set("discount_type", v)} /></Field>
            {f.discount_type === "PERCENT" && <Field label="Diskon (%)"><Input type="number" min="0" max="100" step="any" value={f.discount_value} onChange={(e) => set("discount_value", e.target.value)} /></Field>}
            {f.discount_type === "AMOUNT" && <Field label="Diskon (Rp)"><MoneyInput value={f.discount_value} onChange={(v) => set("discount_value", v)} /></Field>}
            {f.discount_type === "NONE" && <div />}
          </div>
          <div className="rounded-lg bg-muted/40 px-3 py-2 text-sm">Net Price Baru: <b>{rupiah(net)}</b></div>
          <Field label="Tanggal Efektif *"><Input type="date" value={f.effective_date} onChange={(e) => set("effective_date", e.target.value)} data-testid="vc-pc-date" /></Field>
          <Field label="Alasan Perubahan *"><textarea value={f.reason} onChange={(e) => set("reason", e.target.value)} className="w-full min-h-20 rounded-md border bg-background px-3 py-2 text-sm" data-testid="vc-pc-reason" /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button onClick={submit} disabled={saving} data-testid="vc-pc-save">{saving ? "Menyimpan..." : "Simpan Perubahan"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ============================== DOCUMENTS ============================== */
function ContractDocuments({ cid, canManage }) {
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const load = useCallback(() => api.get(`/vendor-contracts/${cid}/documents`).then((r) => setDocs(r.data || [])).catch(() => {}), [cid]);
  useEffect(() => { load(); }, [load]);
  const upload = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    if (file.size > 10 * 1024 * 1024) { toast.error("Ukuran file maksimal 10 MB"); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      await api.post(`/vendor-contracts/${cid}/documents`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Dokumen terunggah"); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setUploading(false); e.target.value = ""; }
  };
  const del = async (docId) => {
    if (!window.confirm("Hapus dokumen ini?")) return;
    try { await api.delete(`/vendor-contracts/${cid}/documents/${docId}`); toast.success("Dokumen dihapus"); load(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  const download = (d) => window.open(`${API}/vendor-contracts/${cid}/documents/${d.id}/download`, "_blank");
  return (
    <div className="space-y-3">
      {canManage && (
        <label className="inline-flex items-center gap-2 rounded-lg border border-dashed px-4 py-2 text-sm cursor-pointer hover:bg-accent/40" data-testid="vc-doc-upload-label">
          <Upload className="h-4 w-4" />{uploading ? "Mengunggah..." : "Upload Dokumen (PDF/JPG/PNG/WEBP, maks 10MB)"}
          <input type="file" className="hidden" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={upload} disabled={uploading} data-testid="vc-doc-input" />
        </label>
      )}
      {docs.length === 0 ? <div className="text-sm text-muted-foreground py-6 text-center">Belum ada dokumen kontrak.</div> : (
        <div className="space-y-2">
          {docs.map((d) => (
            <div key={d.id} className="flex items-center justify-between rounded-xl border p-3">
              <div className="flex items-center gap-3 min-w-0"><FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="min-w-0"><div className="text-sm font-medium truncate">{d.file_name}</div>
                  <div className="text-[11px] text-muted-foreground">{(d.file_size / 1024).toFixed(0)} KB · {d.mime_type} · {fmtDate(d.uploaded_at)} · {d.uploaded_by}</div></div></div>
              <div className="flex gap-1 shrink-0">
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => download(d)}><Download className="h-4 w-4" /></Button>
                {canManage && <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => del(d.id)}><Trash2 className="h-4 w-4 text-destructive" /></Button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================== DETAIL ============================== */
export function VendorContractDetail() {
  const nav = useNavigate();
  const { id } = useParams();
  const [c, setC] = useState(null);
  const [tab, setTab] = useState("items");
  const [itemOpen, setItemOpen] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [pcOpen, setPcOpen] = useState(false);
  const [pcRow, setPcRow] = useState(null);

  const load = useCallback(() => api.get(`/vendor-contracts/${id}`).then((r) => setC(r.data)).catch((e) => toast.error(apiError(e.response?.data?.detail))), [id]);
  useEffect(() => { load(); }, [load]);

  if (!c) return <div className="p-10 text-center text-muted-foreground">Memuat kontrak...</div>;
  const ds = c.derived_status;
  const isDraft = c.status === "draft";
  const isActive = c.status === "active";
  const canManage = c.can_manage;
  const canActivate = c.can_activate;
  const canPrice = c.can_manage_price;

  const activate = async () => {
    try { await api.post(`/vendor-contracts/${id}/activate`); toast.success("Kontrak diaktifkan"); load(); }
    catch (e) { showErr(e); }
  };
  const cancel = async () => {
    if (!window.confirm("Batalkan kontrak ini? Kontrak tidak dapat dipakai sebagai referensi baru.")) return;
    try { await api.post(`/vendor-contracts/${id}/cancel`); toast.success("Kontrak dibatalkan"); load(); }
    catch (e) { showErr(e); }
  };
  const delItem = async (rid) => {
    if (!window.confirm("Hapus item ini?")) return;
    try { await api.delete(`/vendor-contracts/${id}/items/${rid}`); toast.success("Item dihapus"); load(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  const openAddItem = () => { setEditRow(null); setItemOpen(true); };
  const openEditItem = (row) => { setEditRow(row); setItemOpen(true); };
  const openPriceChange = (row) => { setPcRow(row); setPcOpen(true); };

  const discLabel = (it) => it.discount_type === "PERCENT" ? `${it.discount_value}%` : it.discount_type === "AMOUNT" ? rupiah(it.discount_value) : "-";

  const summary = [
    ["Vendor", c.supplier_name || "-"],
    ["Periode", `${c.start_date} s/d ${c.end_date}`],
    ["Mata Uang", c.currency],
    ["Jumlah Item", String(c.item_count ?? 0)],
    ["Default Tolerance", `${c.default_tolerance_pct || 0}%`],
    ["Termin Pembayaran", c.payment_term || "-"],
  ];

  return (
    <div>
      <PageHeader title={`Kontrak ${c.contract_number}`} subtitle={c.supplier_name}>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" onClick={() => nav("/vendor-contracts")}><ArrowLeft className="h-4 w-4 mr-2" />Daftar</Button>
          {isDraft && canManage && <Button variant="outline" onClick={() => nav(`/vendor-contracts/${id}/edit`)} data-testid="vc-edit-btn"><Pencil className="h-4 w-4 mr-2" />Edit</Button>}
          {isDraft && canActivate && <Button onClick={activate} data-testid="vc-activate-btn"><CheckCircle2 className="h-4 w-4 mr-2" />Aktifkan</Button>}
          {c.status !== "cancelled" && canManage && <Button variant="outline" className="text-destructive" onClick={cancel} data-testid="vc-cancel-btn"><Ban className="h-4 w-4 mr-2" />Batalkan</Button>}
        </div>
      </PageHeader>

      <div className="rounded-xl border bg-card p-5 shadow-sm mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 font-mono font-semibold">{c.contract_number} <VcBadge status={ds} /></div>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
          {summary.map(([l, v]) => <div key={l}><div className="text-xs text-muted-foreground">{l}</div><div className="font-medium mt-0.5">{v}</div></div>)}
        </div>
      </div>

      <div className="border-b flex gap-1 mb-4 overflow-x-auto">
        {[["items", "Item Harga", ListChecks], ["documents", "Dokumen", FileText], ["history", "Histori Harga", History], ["audit", "Audit", ShieldCheck]].map(([k, l, Icon]) => (
          <button key={k} onClick={() => setTab(k)} className={`h-10 px-4 text-sm font-medium border-b-2 -mb-px inline-flex items-center gap-2 whitespace-nowrap ${tab === k ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`} data-testid={`vc-tab-${k}`}><Icon className="h-4 w-4" />{l}</button>
        ))}
      </div>

      {tab === "items" && (
        <div className="space-y-3">
          {isDraft && canManage && <Button onClick={openAddItem} data-testid="vc-item-add-btn"><Plus className="h-4 w-4 mr-2" />Tambah Item Harga</Button>}
          {!isDraft && <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">Item hanya dapat diubah saat Draft. Untuk kontrak Active gunakan tombol <b>Ubah Harga</b> (tercatat di Histori Harga).</div>}
          {(c.items || []).length === 0 ? <div className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">Belum ada item harga pada kontrak ini.</div> : (
            <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
              <table className="w-full text-sm"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground">
                <th className="p-3">Barang</th><th className="p-3">UOM</th><th className="p-3 text-right">Min Qty</th>
                <th className="p-3 text-right">Base Price</th><th className="p-3 text-right">Diskon</th><th className="p-3 text-right">Net Price</th>
                <th className="p-3 text-right">Tolerance</th><th className="p-3">Periode Efektif</th><th className="p-3 w-28">Aksi</th></tr></thead>
                <tbody>
                  {(c.items || []).map((it) => (
                    <tr key={it.id} className="border-t" data-testid={`vc-item-row-${it.item_id}`}>
                      <td className="p-3">{it.item_name || it.item_id}</td>
                      <td className="p-3 text-muted-foreground">{it.uom_name || "-"}</td>
                      <td className="p-3 text-right">{it.min_qty}</td>
                      <td className="p-3 text-right">{rupiah(it.base_price)}</td>
                      <td className="p-3 text-right text-xs">{discLabel(it)}</td>
                      <td className="p-3 text-right font-semibold" data-testid={`vc-item-net-${it.item_id}`}>{rupiah(it.net_price)}</td>
                      <td className="p-3 text-right text-xs">{it.effective_tolerance_pct}%</td>
                      <td className="p-3 text-xs text-muted-foreground">{(it.effective_start || c.start_date)} s/d {(it.effective_end || c.end_date)}</td>
                      <td className="p-3">
                        {isDraft && canManage && <><Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEditItem(it)}><Pencil className="h-3.5 w-3.5" /></Button>
                          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => delItem(it.id)}><Trash2 className="h-3.5 w-3.5 text-destructive" /></Button></>}
                        {isActive && canPrice && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => openPriceChange(it)} data-testid={`vc-pc-btn-${it.item_id}`}>Ubah Harga</Button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "documents" && <ContractDocuments cid={id} canManage={canManage} />}

      {tab === "history" && (
        (c.price_history || []).length === 0 ? <div className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">Belum ada perubahan harga resmi.</div> : (
          <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
            <table className="w-full text-sm"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground">
              <th className="p-3">Barang</th><th className="p-3 text-right">Net Lama</th><th className="p-3 text-right">Net Baru</th>
              <th className="p-3 text-right">Perubahan</th><th className="p-3">Tgl Efektif</th><th className="p-3">Alasan</th><th className="p-3">Oleh</th></tr></thead>
              <tbody>
                {(c.price_history || []).map((h) => (
                  <tr key={h.id} className="border-t" data-testid={`vc-hist-${h.id}`}>
                    <td className="p-3">{h.item_name} <span className="text-muted-foreground">({h.uom_name})</span></td>
                    <td className="p-3 text-right">{rupiah(h.previous_net_price)}</td>
                    <td className="p-3 text-right font-semibold">{rupiah(h.new_net_price)}</td>
                    <td className={`p-3 text-right text-xs ${(h.change_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{h.change_pct == null ? "-" : `${h.change_pct}%`}</td>
                    <td className="p-3 text-xs">{h.effective_date}</td>
                    <td className="p-3 text-xs text-muted-foreground max-w-xs truncate" title={h.reason}>{h.reason}</td>
                    <td className="p-3 text-xs text-muted-foreground">{h.actor_name || h.actor}<br />{fmtDate(h.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {tab === "audit" && (
        <div className="grid sm:grid-cols-2 gap-4 text-sm">
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Dibuat oleh</div><div className="font-medium mt-1">{c.created_by} · {fmtDate(c.created_at)}</div></div>
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Terakhir diubah</div><div className="font-medium mt-1">{c.updated_by} · {fmtDate(c.updated_at)}</div></div>
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Diaktifkan oleh</div><div className="font-medium mt-1">{c.activated_by ? `${c.activated_by} · ${fmtDate(c.activated_at)}` : "-"}</div></div>
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Dibatalkan oleh</div><div className="font-medium mt-1">{c.cancelled_by ? `${c.cancelled_by} · ${fmtDate(c.cancelled_at)}` : "-"}</div></div>
          <div className="sm:col-span-2 rounded-xl border bg-muted/20 p-4 text-xs text-muted-foreground flex items-center gap-2"><Package className="h-4 w-4" />Riwayat perubahan harga resmi tersedia pada tab Histori Harga. Jejak audit lengkap seluruh aksi tersedia pada menu Activity Log.</div>
        </div>
      )}

      {itemOpen && <ItemDialog open={itemOpen} onOpenChange={setItemOpen} contract={c} editRow={editRow} onSaved={load} />}
      {pcOpen && <PriceChangeDialog open={pcOpen} onOpenChange={setPcOpen} contract={c} row={pcRow} onSaved={load} />}
    </div>
  );
}
