import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { AttachmentPanel } from "@/components/DocMeta";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field } from "@/components/DatePicker";
import {
  Plus, Pencil, Search, Package, Warehouse, FolderKanban, Truck,
  Building2, Layers3, Boxes, ChevronRight, ArrowLeft, Ruler, Tags,
  Trash2, Percent, UsersRound, ContactRound,
} from "lucide-react";
import { num } from "@/lib/format";
import { toast } from "sonner";

const CONFIGS = {
  items: { label: "Barang", fields: [
    { k: "code", l: "Kode Barang", auto: true },
    { k: "name", l: "Nama Barang", req: true },
    { k: "alias", l: "Nama Alias" },
    { k: "category_id", l: "Kategori Barang", ref: "item_categories" },
    { k: "division_id", l: "Divisi", ref: "divisions" },
    { k: "base_uom_id", l: "Satuan Dasar", ref: "uoms", req: true },
    { k: "brand", l: "Merk" },
    { k: "part_number", l: "Part Number" },
    { k: "spec", l: "Spesifikasi" },
  ] },
  item_categories: { label: "Kategori Barang", fields: [
    { k: "code", l: "Kode Kategori", auto: true }, { k: "name", l: "Nama Kategori", req: true }, { k: "notes", l: "Keterangan" },
  ] },
  uoms: { label: "Satuan", fields: [
    { k: "code", l: "Kode Satuan", auto: true }, { k: "name", l: "Nama Satuan", req: true }, { k: "symbol", l: "Simbol", req: true }, { k: "notes", l: "Keterangan" },
  ] },
  taxes: { label: "Pajak", fields: [
    { k: "code", l: "Kode Pajak", auto: true }, { k: "name", l: "Nama Pajak", req: true },
    { k: "rate", l: "Tarif (%)", req: true, type: "number", step: "any", suffix: "%" }, { k: "notes", l: "Keterangan" },
  ] },
  supplier_categories: { label: "Kategori Supplier", fields: [
    { k: "code", l: "Kode Kategori", auto: true }, { k: "name", l: "Nama Kategori", req: true }, { k: "notes", l: "Keterangan" },
  ] },
  warehouses: { label: "Gudang", fields: [
    { k: "code", l: "Kode Gudang", auto: true }, { k: "name", l: "Nama Gudang", req: true }, { k: "location", l: "Lokasi" },
    { k: "division_id", l: "Divisi", ref: "divisions" }, { k: "pic", l: "PIC Gudang" }, { k: "notes", l: "Keterangan" },
  ] },
  projects: { label: "Proyek", fields: [
    { k: "code", l: "Kode Proyek", auto: true }, { k: "name", l: "Nama Proyek", req: true }, { k: "pic", l: "Penanggung Jawab" },
    { k: "status", l: "Status" }, { k: "notes", l: "Keterangan" },
  ] },
  units: { label: "Unit / Aset", fields: [
    { k: "code", l: "Kode Unit", auto: true }, { k: "name", l: "Nama Unit", req: true }, { k: "type", l: "Jenis" },
    { k: "plate_no", l: "Nomor Polisi" }, { k: "asset_no", l: "Nomor Asset" }, { k: "brand", l: "Merk" }, { k: "model", l: "Model" },
    { k: "year", l: "Tahun" }, { k: "division_id", l: "Divisi", ref: "divisions" },
  ] },
  suppliers: { label: "Supplier", fields: [
    { k: "code", l: "Kode Supplier", auto: true }, { k: "name", l: "Nama Supplier", req: true },
    { k: "supplier_category_id", l: "Kategori Supplier", ref: "supplier_categories" },
    { k: "phone", l: "Telepon" }, { k: "email", l: "Email" },
  ] },
  divisions: { label: "Divisi", fields: [
    { k: "code", l: "Kode Divisi", auto: true }, { k: "name", l: "Nama", req: true },
  ] },
  contacts: { label: "Kontak Internal", fields: [
    { k: "code", l: "Kode Kontak", auto: true },
    { k: "name", l: "Nama Lengkap", req: true },
    { k: "position", l: "Jabatan / Posisi" },
    { k: "division_id", l: "Divisi", ref: "divisions" },
    { k: "phone", l: "HP / WhatsApp" },
    { k: "email", l: "Email" },
    { k: "notes", l: "Keterangan" },
  ] },
};

const MASTER_GROUPS = [
  {
    title: "Barang & Persediaan",
    subtitle: "Identitas barang, kategori, satuan, dan kontrol stok.",
    cards: [
      { key: "items", label: "Barang", icon: Package, desc: "Nama barang, kategori, satuan dasar, multi satuan, merk dan spesifikasi." },
      { key: "item_categories", label: "Kategori Barang", icon: Tags, desc: "Kelompok barang yang menjadi pilihan dropdown pada master barang." },
      { key: "uoms", label: "Satuan", icon: Ruler, desc: "PCS, Box, Karton, Kg, Liter dan satuan lain untuk transaksi." },
      { key: "iw", label: "Stok Min/Max", icon: Boxes, desc: "Stok minimum, maksimum, dan suggested order per barang-gudang." },
    ],
  },
  {
    title: "Supplier & Pembelian",
    subtitle: "Vendor, klasifikasi supplier, pajak, rekening, dan default pembelian.",
    cards: [
      { key: "suppliers", label: "Supplier", icon: Building2, desc: "Profil supplier lengkap, PIC, alamat, legal, rekening bank, dan default PO." },
      { key: "supplier_categories", label: "Kategori Supplier", icon: UsersRound, desc: "Klasifikasi supplier seperti Sparepart, Jasa, Transportasi, Asset, dan lainnya." },
      { key: "taxes", label: "Pajak", icon: Percent, desc: "Daftar pajak dan tarif yang dapat dipilih langsung pada transaksi pembelian." },
    ],
  },
  {
    title: "Organisasi & Operasional",
    subtitle: "Referensi personel, divisi, lokasi, proyek, dan unit pemakaian barang.",
    cards: [
      { key: "divisions", label: "Divisi", icon: Layers3, desc: "Pengelompokan divisi untuk akses dan kebutuhan operasional." },
      { key: "contacts", label: "Kontak Internal", icon: ContactRound, desc: "Data karyawan/PIC internal yang dapat dipakai sebagai Buyer Contact dan referensi transaksi." },
      { key: "warehouses", label: "Gudang", icon: Warehouse, desc: "Lokasi penyimpanan, divisi, PIC, dan keterangan gudang." },
      { key: "projects", label: "Proyek", icon: FolderKanban, desc: "Master proyek dan penanggung jawab untuk alokasi transaksi." },
      { key: "units", label: "Unit / Aset", icon: Truck, desc: "Kendaraan, alat, atau aset sebagai tujuan pemakaian barang." },
    ],
  },
];

function Section({ title, subtitle, children }) {
  return <div className="rounded-xl border bg-muted/15 p-4 space-y-4">
    <div><h3 className="font-head font-semibold">{title}</h3>{subtitle && <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>}</div>
    {children}
  </div>;
}

function SupplierEditor({ form, setForm, refs }) {
  const supplierCategories = (refs.supplier_categories || []).map((x) => ({ value: x.id, label: x.name }));
  const taxOptions = [{ value: "", label: "Tanpa Pajak Default" }, ...(refs.taxes || []).map((x) => ({ value: x.id, label: `${x.name} (${num(x.rate)}%)` }))];
  const itemCategories = refs.item_categories || [];
  const contacts = form.contacts || [];
  const banks = form.banks || [];

  const setContact = (i, patch) => setForm((s) => ({ ...s, contacts: (s.contacts || []).map((x, idx) => idx === i ? { ...x, ...patch } : x) }));
  const setBank = (i, patch) => setForm((s) => ({ ...s, banks: (s.banks || []).map((x, idx) => idx === i ? { ...x, ...patch } : x) }));
  const primaryContact = (i) => setForm((s) => ({ ...s, contacts: (s.contacts || []).map((x, idx) => ({ ...x, is_primary: idx === i })) }));
  const primaryBank = (i) => setForm((s) => ({ ...s, banks: (s.banks || []).map((x, idx) => ({ ...x, is_primary: idx === i })) }));
  const toggleItemCategory = (id) => setForm((s) => {
    const cur = s.supplied_category_ids || [];
    return { ...s, supplied_category_ids: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] };
  });

  return <div className="space-y-4 py-2">
    <Section title="Informasi Umum" subtitle="Identitas dan klasifikasi utama supplier.">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Kode Supplier (Otomatis, bisa diedit)"><Input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} className="font-mono font-semibold" /></Field>
        <Field label="Nama Supplier *"><Input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Nama Legal / Perusahaan"><Input value={form.legal_name || ""} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} /></Field>
        <Field label="Kategori Supplier"><Combobox options={supplierCategories} value={form.supplier_category_id || ""} onChange={(v) => setForm({ ...form, supplier_category_id: v })} placeholder="Pilih kategori" /></Field>
        <Field label="Jenis Supplier"><Combobox options={[{ value: "Lokal", label: "Lokal" }, { value: "Import", label: "Import" }, { value: "Jasa", label: "Jasa" }]} value={form.supplier_type || "Lokal"} onChange={(v) => setForm({ ...form, supplier_type: v })} /></Field>
      </div>
    </Section>

    <Section title="Kontak / PIC" subtitle="Bisa lebih dari satu PIC. Tandai satu sebagai PIC utama.">
      <div className="space-y-3">
        {contacts.map((c, i) => <div key={c.id || i} className="grid grid-cols-1 md:grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2 items-end rounded-lg border bg-background p-3">
          <Field label="Nama PIC"><Input value={c.name || ""} onChange={(e) => setContact(i, { name: e.target.value })} /></Field>
          <Field label="Jabatan / Bagian"><Input value={c.role || ""} onChange={(e) => setContact(i, { role: e.target.value })} /></Field>
          <Field label="HP / WhatsApp"><Input value={c.phone || ""} onChange={(e) => setContact(i, { phone: e.target.value })} /></Field>
          <Field label="Email"><Input value={c.email || ""} onChange={(e) => setContact(i, { email: e.target.value })} /></Field>
          <div className="flex gap-1 pb-0.5"><Button type="button" variant={c.is_primary ? "default" : "outline"} size="sm" onClick={() => primaryContact(i)}>Utama</Button><Button type="button" variant="ghost" size="icon" onClick={() => setForm((s) => ({ ...s, contacts: (s.contacts || []).filter((_, idx) => idx !== i) }))}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>
        </div>)}
        <Button type="button" variant="outline" size="sm" onClick={() => setForm((s) => ({ ...s, contacts: [...(s.contacts || []), { name: "", role: "", phone: "", email: "", is_primary: !(s.contacts || []).length }] }))}><Plus className="h-4 w-4 mr-2" />Tambah PIC</Button>
      </div>
    </Section>

    <Section title="Alamat" subtitle="Alamat korespondensi dan wilayah supplier.">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="md:col-span-2"><Field label="Alamat Lengkap"><Input value={form.address || ""} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field></div>
        <Field label="Kecamatan / Area"><Input value={form.district || ""} onChange={(e) => setForm({ ...form, district: e.target.value })} /></Field>
        <Field label="Kota / Kabupaten"><Input value={form.city || ""} onChange={(e) => setForm({ ...form, city: e.target.value })} /></Field>
        <Field label="Provinsi"><Input value={form.province || ""} onChange={(e) => setForm({ ...form, province: e.target.value })} /></Field>
        <Field label="Kode Pos"><Input value={form.postal_code || ""} onChange={(e) => setForm({ ...form, postal_code: e.target.value })} /></Field>
        <Field label="Negara"><Input value={form.country || "Indonesia"} onChange={(e) => setForm({ ...form, country: e.target.value })} /></Field>
      </div>
    </Section>

    <Section title="Pajak & Legal" subtitle="Informasi legal dan perpajakan supplier.">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="NPWP"><Input value={form.npwp || ""} onChange={(e) => setForm({ ...form, npwp: e.target.value })} /></Field>
        <Field label="NIB / Nomor Legal"><Input value={form.nib || ""} onChange={(e) => setForm({ ...form, nib: e.target.value })} /></Field>
        <Field label="Nama Sesuai NPWP"><Input value={form.tax_name || ""} onChange={(e) => setForm({ ...form, tax_name: e.target.value })} /></Field>
        <label className="flex items-center gap-2 rounded-md border px-3 h-9 mt-6 text-sm"><input type="checkbox" checked={!!form.pkp} onChange={(e) => setForm({ ...form, pkp: e.target.checked })} />PKP</label>
        <div className="md:col-span-2"><Field label="Alamat Pajak"><Input value={form.tax_address || ""} onChange={(e) => setForm({ ...form, tax_address: e.target.value })} /></Field></div>
      </div>
    </Section>

    <Section title="Rekening Bank" subtitle="Bisa multi rekening. Satu rekening ditandai sebagai rekening utama.">
      <div className="space-y-3">
        {banks.map((b, i) => <div key={b.id || i} className="grid grid-cols-1 md:grid-cols-[1fr_1.15fr_1.2fr_1fr_100px_auto] gap-2 items-end rounded-lg border bg-background p-3">
          <Field label="Bank"><Input value={b.bank_name || ""} onChange={(e) => setBank(i, { bank_name: e.target.value })} /></Field>
          <Field label="No. Rekening"><Input value={b.account_no || ""} onChange={(e) => setBank(i, { account_no: e.target.value })} /></Field>
          <Field label="Nama Rekening"><Input value={b.account_name || ""} onChange={(e) => setBank(i, { account_name: e.target.value })} /></Field>
          <Field label="Cabang"><Input value={b.branch || ""} onChange={(e) => setBank(i, { branch: e.target.value })} /></Field>
          <Field label="Mata Uang"><Input value={b.currency || "IDR"} onChange={(e) => setBank(i, { currency: e.target.value })} /></Field>
          <div className="flex gap-1 pb-0.5"><Button type="button" variant={b.is_primary ? "default" : "outline"} size="sm" onClick={() => primaryBank(i)}>Utama</Button><Button type="button" variant="ghost" size="icon" onClick={() => setForm((s) => ({ ...s, banks: (s.banks || []).filter((_, idx) => idx !== i) }))}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>
        </div>)}
        <Button type="button" variant="outline" size="sm" onClick={() => setForm((s) => ({ ...s, banks: [...(s.banks || []), { bank_name: "", account_no: "", account_name: "", branch: "", currency: "IDR", is_primary: !(s.banks || []).length }] }))}><Plus className="h-4 w-4 mr-2" />Tambah Rekening</Button>
      </div>
    </Section>

    <Section title="Ketentuan Pembelian" subtitle="Nilai default ini otomatis dibawa saat supplier dipilih pada PO dan tetap bisa disesuaikan di transaksi.">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <Field label="Termin Pembayaran Default"><Input value={form.payment_term || ""} onChange={(e) => setForm({ ...form, payment_term: e.target.value })} placeholder="Contoh: 30 Hari" /></Field>
        <Field label="Mata Uang Default"><Input value={form.currency || "IDR"} onChange={(e) => setForm({ ...form, currency: e.target.value })} /></Field>
        <Field label="Pajak Default"><Combobox options={taxOptions} value={form.default_tax_id || ""} onChange={(v) => setForm({ ...form, default_tax_id: v })} /></Field>
        <Field label="Lead Time Normal (Hari)"><Input type="number" min="0" value={form.lead_time_days ?? 0} onChange={(e) => setForm({ ...form, lead_time_days: e.target.value })} /></Field>
        <Field label="Minimum Order"><Input type="number" min="0" value={form.min_order ?? 0} onChange={(e) => setForm({ ...form, min_order: e.target.value })} /></Field>
        <Field label="Hari / Jadwal Pengiriman"><Input value={form.delivery_days || ""} onChange={(e) => setForm({ ...form, delivery_days: e.target.value })} placeholder="Contoh: Senin, Kamis" /></Field>
        <div className="lg:col-span-3"><Field label="Area Layanan"><Input value={form.service_area || ""} onChange={(e) => setForm({ ...form, service_area: e.target.value })} /></Field></div>
      </div>
    </Section>

    <Section title="Kategori Barang yang Disuplai" subtitle="Pilih satu atau beberapa kategori barang untuk membantu pencarian dan evaluasi supplier.">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {itemCategories.length === 0 && <p className="text-sm text-muted-foreground">Belum ada Master Kategori Barang.</p>}
        {itemCategories.map((x) => <label key={x.id} className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm"><input type="checkbox" checked={(form.supplied_category_ids || []).includes(x.id)} onChange={() => toggleItemCategory(x.id)} />{x.name}</label>)}
      </div>
    </Section>

    <Section title="Catatan & Dokumen" subtitle="Catatan internal dan dokumen legal/kontrak supplier.">
      <Field label="Catatan Internal"><Input value={form.notes || ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
      {form.id ? <AttachmentPanel entity="supplier" entityId={form.id} /> : <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">Simpan supplier terlebih dahulu. Setelah itu buka Edit Supplier untuk upload NPWP, NIB, rekening, kontrak, price list, dan dokumen lainnya.</div>}
    </Section>
  </div>;
}

function MasterTab({ name }) {
  const cfg = CONFIGS[name];
  const { can } = useAuth();
  const [rows, setRows] = useState([]);
  const [refs, setRefs] = useState({});
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({});
  const [q, setQ] = useState("");

  const load = () => api.get(`/master/${name}`).then((r) => setRows(r.data));
  const loadRef = (rn) => api.get(`/master/${rn}?active_only=true`).then((r) => setRefs((s) => ({ ...s, [rn]: r.data })));

  useEffect(() => {
    load();
    const needed = [...new Set(cfg.fields.filter((f) => f.ref).map((f) => f.ref))];
    if (name === "items" && !needed.includes("uoms")) needed.push("uoms");
    if (name === "suppliers") ["supplier_categories", "taxes", "item_categories"].forEach((x) => { if (!needed.includes(x)) needed.push(x); });
    needed.forEach(loadRef);
  }, [name]);

  const openAdd = async () => {
    let code = "";
    try { const res = await api.get(`/master-code/${name}/preview`); code = res.data.code || ""; } catch {}
    const defaults = name === "items" ? { uoms: [] } : name === "taxes" ? { rate: 0 } : name === "suppliers" ? {
      contacts: [], banks: [], supplied_category_ids: [], country: "Indonesia", currency: "IDR", supplier_type: "Lokal", lead_time_days: 0, min_order: 0,
    } : {};
    setForm({ code, ...defaults }); setOpen(true);
  };

  const openEdit = (row) => {
    const copy = { ...row };
    if (name === "items") copy.uoms = (row.uoms || []).filter((x) => !x.is_base && x.uom_id !== row.base_uom_id);
    if (name === "suppliers") {
      copy.contacts = row.contacts || (row.contact || row.phone || row.email ? [{ name: row.contact || "", role: "", phone: row.phone || "", email: row.email || "", is_primary: true }] : []);
      copy.banks = row.banks || [];
      copy.supplied_category_ids = row.supplied_category_ids || [];
      copy.country = row.country || "Indonesia";
      copy.currency = row.currency || "IDR";
      copy.supplier_type = row.supplier_type || "Lokal";
    }
    setForm(copy); setOpen(true);
  };

  const save = async () => {
    try {
      const editing = !!form.id;
      const res = editing ? await api.put(`/master/${name}/${form.id}`, form) : await api.post(`/master/${name}`, form);
      toast.success(editing ? `Perubahan tersimpan — ${res.data.code}` : `${cfg.label} tersimpan — ${res.data.code}`);
      setOpen(false); setForm({}); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  const filtered = rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));
  const refName = (rn, id) => (refs[rn] || []).find((x) => x.id === id)?.name || "-";
  const refOptions = (rn) => (refs[rn] || []).map((x) => ({ value: x.id, label: x.name }));
  const uomOptions = refOptions("uoms");
  const displayField = (f, r) => {
    if (f.ref) return refName(f.ref, r[f.k]);
    const value = r[f.k];
    if (value === undefined || value === null || value === "") return "-";
    return f.suffix ? `${value}${f.suffix}` : value;
  };

  const addUom = () => setForm((s) => ({ ...s, uoms: [...(s.uoms || []), { uom_id: "", factor: 1 }] }));
  const updUom = (i, patch) => setForm((s) => ({ ...s, uoms: (s.uoms || []).map((u, x) => x === i ? { ...u, ...patch } : u) }));
  const delUom = (i) => setForm((s) => ({ ...s, uoms: (s.uoms || []).filter((_, x) => x !== i) }));

  return <div>
    <div className="flex items-center justify-between mb-4 gap-3">
      <div className="relative max-w-sm flex-1"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Cari ${cfg.label}...`} className="pl-9" /></div>
      {can("create") && <Button onClick={openAdd}><Plus className="h-4 w-4 mr-2" />Tambah {cfg.label}</Button>}
    </div>

    <div className="border rounded-xl overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
      {cfg.fields.slice(0, 5).map((f) => <th key={f.k} className="p-3">{f.l}</th>)}<th className="p-3">Status</th><th className="p-3 w-16"></th></tr></thead>
      <tbody>{filtered.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">Belum ada data</td></tr>}
        {filtered.map((r) => <tr key={r.id} className="border-t hover:bg-accent/40 transition-colors">
          {cfg.fields.slice(0, 5).map((f) => <td key={f.k} className={`p-3 ${f.k === "code" ? "font-mono text-xs font-semibold" : ""}`}>{displayField(f, r)}</td>)}
          <td className="p-3"><StatusBadge status={r.is_active ? "Normal" : "cancelled"} /></td>
          <td className="p-3"><Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(r)}><Pencil className="h-4 w-4" /></Button></td>
        </tr>)}</tbody></table></div>

    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className={`${name === "suppliers" ? "max-w-6xl" : "max-w-3xl"} max-h-[92vh] overflow-y-auto`}>
        <DialogHeader><DialogTitle className="font-head">{form.id ? "Edit" : "Tambah"} {cfg.label}</DialogTitle></DialogHeader>

        {name === "suppliers" ? <SupplierEditor form={form} setForm={setForm} refs={refs} /> : <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-2">
            {cfg.fields.map((f) => <Field key={f.k} label={f.l + (f.auto ? " (Otomatis, bisa diedit)" : f.req ? " *" : "")}>
              {f.ref ? <Combobox options={refOptions(f.ref)} value={form[f.k] || ""} onChange={(v) => setForm({ ...form, [f.k]: v })} /> :
                <Input type={f.type || "text"} step={f.step} min={f.type === "number" ? "0" : undefined} value={form[f.k] ?? ""} onChange={(e) => setForm({ ...form, [f.k]: e.target.value })} placeholder={f.auto ? "Kode otomatis" : undefined} className={f.auto ? "font-mono font-semibold" : ""} />}
            </Field>)}
          </div>

          {name === "items" && <div className="mt-2 rounded-xl border bg-muted/20 p-4 space-y-3">
            <div className="flex items-start justify-between gap-3"><div><h3 className="font-head font-semibold">Multi Satuan Barang</h3><p className="text-xs text-muted-foreground mt-1">Satuan dasar selalu bernilai 1. Tambahkan satuan transaksi dan isi berapa satuan dasar di dalam 1 satuan tersebut.</p></div><Button type="button" variant="outline" size="sm" onClick={addUom}><Plus className="h-4 w-4 mr-2" />Tambah Satuan</Button></div>
            <div className="rounded-lg border bg-background p-3 text-sm"><span className="text-muted-foreground">Satuan dasar:</span> <span className="font-semibold">{refName("uoms", form.base_uom_id)}</span><span className="ml-2 text-xs text-muted-foreground">= 1</span></div>
            {(form.uoms || []).length === 0 && <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">Belum ada satuan tambahan. Barang tetap bisa ditransaksikan dengan satuan dasar.</div>}
            {(form.uoms || []).map((row, i) => <div key={i} className="grid grid-cols-1 md:grid-cols-[1fr_180px_44px] gap-2 items-end rounded-lg border bg-background p-3">
              <Field label="Satuan Tambahan"><Combobox options={uomOptions.filter((x) => x.value !== form.base_uom_id)} value={row.uom_id || ""} onChange={(v) => updUom(i, { uom_id: v })} placeholder="Pilih satuan" /></Field>
              <Field label={`1 satuan = ... ${refName("uoms", form.base_uom_id)}`}><Input type="number" min="0.000001" step="any" value={row.factor ?? 1} onChange={(e) => updUom(i, { factor: e.target.value })} /></Field>
              <Button type="button" variant="ghost" size="icon" onClick={() => delUom(i)}><Trash2 className="h-4 w-4 text-destructive" /></Button>
            </div>)}
            <div className="text-xs text-muted-foreground">Contoh: satuan dasar PCS, BOX = 12. Saat transaksi 2 BOX, sistem mencatat stok 24 PCS tetapi dokumen tetap mengingat bahwa user memilih 2 BOX.</div>
          </div>}
        </>}

        <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Batal</Button><Button onClick={save}>Simpan</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}

function ItemWarehouseTab() {
  const [rows, setRows] = useState([]);
  const [items, setItems] = useState([]);
  const [whs, setWhs] = useState([]);
  const [form, setForm] = useState({ item_id: "", warehouse_id: "", min_stock: 0, max_stock: 0 });
  const load = () => api.get("/item-warehouse").then((r) => setRows(r.data));
  useEffect(() => { load(); api.get("/master/items?active_only=true").then((r) => setItems(r.data)); api.get("/master/warehouses?active_only=true").then((r) => setWhs(r.data)); }, []);
  const save = async () => { try { await api.post("/item-warehouse", form); toast.success("Tersimpan"); load(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };
  return <div className="space-y-4">
    <Card><CardContent className="pt-6"><div className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
      <Field label="Barang"><Combobox options={items.map((i) => ({ value: i.id, label: i.name }))} value={form.item_id} onChange={(v) => setForm({ ...form, item_id: v })} /></Field>
      <Field label="Gudang"><Combobox options={whs.map((w) => ({ value: w.id, label: w.name }))} value={form.warehouse_id} onChange={(v) => setForm({ ...form, warehouse_id: v })} /></Field>
      <Field label="Min Stock"><Input type="number" value={form.min_stock} onChange={(e) => setForm({ ...form, min_stock: Number(e.target.value) })} /></Field>
      <Field label="Max Stock"><Input type="number" value={form.max_stock} onChange={(e) => setForm({ ...form, max_stock: Number(e.target.value) })} /></Field>
      <Button onClick={save} disabled={!form.item_id || !form.warehouse_id}>Set Min/Max</Button>
    </div></CardContent></Card>
    <div className="border rounded-xl overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">Barang</th><th className="p-3">Gudang</th><th className="p-3 text-right">Current</th><th className="p-3 text-right">Min</th><th className="p-3 text-right">Max</th><th className="p-3 text-right">Suggested</th><th className="p-3">Status</th></tr></thead>
      <tbody>{rows.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">Belum ada konfigurasi</td></tr>}{rows.map((r, i) => <tr key={i} className="border-t"><td className="p-3">{r.item_code} — {r.item_name}</td><td className="p-3">{r.warehouse_name}</td><td className="p-3 text-right font-semibold">{num(r.current_stock)}</td><td className="p-3 text-right">{num(r.min_stock)}</td><td className="p-3 text-right">{num(r.max_stock)}</td><td className="p-3 text-right">{num(r.suggested_order)}</td><td className="p-3"><StatusBadge status={r.status} /></td></tr>)}</tbody></table></div>
  </div>;
}

function MasterCard({ card, count, onClick }) {
  const Icon = card.icon;
  return <button type="button" onClick={onClick} className="group w-full rounded-2xl border bg-card p-4 sm:p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
    <div className="flex items-center gap-4"><div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Icon className="h-6 w-6" /></div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h3 className="font-head text-base font-semibold">{card.label}</h3>{count !== undefined && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{count} data</span>}</div><p className="mt-1 text-xs sm:text-sm text-muted-foreground line-clamp-2">{card.desc}</p></div><ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
  </button>;
}

export default function MasterData() {
  const [active, setActive] = useState(null);
  const [counts, setCounts] = useState({});
  const loadCounts = async () => {
    const keys = Object.keys(CONFIGS); const out = {};
    await Promise.all(keys.map(async (k) => { try { const r = await api.get(`/master/${k}`); out[k] = r.data.length; } catch { out[k] = 0; } }));
    try { const r = await api.get("/item-warehouse"); out.iw = r.data.length; } catch { out.iw = 0; }
    setCounts(out);
  };
  useEffect(() => { loadCounts(); }, [active]);

  if (active) {
    const title = active === "iw" ? "Stok Min/Max" : CONFIGS[active]?.label;
    return <div><PageHeader title={title} subtitle="Kelola master data dan referensi transaksi"><Button variant="outline" onClick={() => setActive(null)}><ArrowLeft className="h-4 w-4 mr-2" />Kembali ke Master Data</Button></PageHeader>{active === "iw" ? <ItemWarehouseTab /> : <MasterTab name={active} />}</div>;
  }

  return <div><PageHeader title="Master Data" subtitle="Pilih master yang ingin dikelola. Form dibuka setelah kartu dipilih." /><div className="space-y-7">{MASTER_GROUPS.map((group) => <section key={group.title}><div className="mb-3"><h2 className="font-head text-sm font-semibold">{group.title}</h2><p className="mt-1 text-xs text-muted-foreground">{group.subtitle}</p></div><div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">{group.cards.map((card) => <MasterCard key={card.key} card={card} count={counts[card.key]} onClick={() => setActive(card.key)} />)}</div></section>)}</div></div>;
}
