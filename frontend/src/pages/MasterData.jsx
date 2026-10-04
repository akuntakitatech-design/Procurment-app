import { useCallback, useEffect, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { MasterDeleteDialog } from "@/components/MasterDeleteDialog";
import { useNavigate } from "react-router-dom";
import { MASTER_MODULE } from "@/lib/access";
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
  Trash2, Percent, UsersRound, ContactRound, ClipboardList, Handshake,
} from "lucide-react";
import { num } from "@/lib/format";
import { useServerList } from "@/lib/serverList";
import { nextSort } from "@/lib/txnList";
import { ListPager, SortTh } from "@/components/ListPager";
import { toast } from "sonner";
import { ItemStockTab } from "@/components/master/ItemStockTab";

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
        <Field label="Kode Supplier (Otomatis, bisa diedit)"><Input data-testid="master-suppliers-field-code" value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} className="font-mono font-semibold" /></Field>
        <Field label="Nama Supplier *"><Input data-testid="master-suppliers-field-name" value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Nama Legal / Perusahaan"><Input data-testid="master-suppliers-field-legal_name" value={form.legal_name || ""} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} /></Field>
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

export const masterRefNames = (name) => {
  const needed = [...new Set((CONFIGS[name]?.fields || []).filter((f) => f.ref).map((f) => f.ref))];
  if (name === "items" && !needed.includes("uoms")) needed.push("uoms");
  if (name === "suppliers") ["supplier_categories", "taxes", "item_categories"].forEach((x) => { if (!needed.includes(x)) needed.push(x); });
  return needed;
};

export async function newMasterForm(name) {
  let code = "";
  try { const res = await api.get(`/master-code/${name}/preview`); code = res.data.code || ""; } catch {}
  const defaults = name === "items" ? { uoms: [] } : name === "taxes" ? { rate: 0 } : name === "suppliers" ? {
    contacts: [], banks: [], supplied_category_ids: [], country: "Indonesia", currency: "IDR", supplier_type: "Lokal", lead_time_days: 0, min_order: 0,
  } : {};
  return { code, ...defaults };
}

// Form Master existing (field, validasi, endpoint sama) — dipakai Master Data dan shortcut "+ Tambah" di transaksi.
export function MasterFormDialog({ name, open, onOpenChange, form, setForm, refs, onSaved }) {
  const cfg = CONFIGS[name];
  const refName = (rn, id) => (refs[rn] || []).find((x) => x.id === id)?.name || "-";
  const refOptions = (rn) => (refs[rn] || []).map((x) => ({ value: x.id, label: x.name }));
  const uomOptions = refOptions("uoms");
  const addUom = () => setForm((s) => ({ ...s, uoms: [...(s.uoms || []), { uom_id: "", factor: 1 }] }));
  const updUom = (i, patch) => setForm((s) => ({ ...s, uoms: (s.uoms || []).map((u, x) => x === i ? { ...u, ...patch } : u) }));
  const delUom = (i) => setForm((s) => ({ ...s, uoms: (s.uoms || []).filter((_, x) => x !== i) }));
  const save = async () => {
    try {
      const editing = !!form.id;
      const res = editing ? await api.put(`/master/${name}/${form.id}`, form) : await api.post(`/master/${name}`, form);
      toast.success(editing ? `Perubahan tersimpan — ${res.data.code}` : `${cfg.label} tersimpan — ${res.data.code}`);
      onSaved(res.data);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${name === "suppliers" ? "max-w-6xl" : "max-w-3xl"} max-h-[92vh] overflow-y-auto`} data-testid={`master-${name}-form`}>
        <DialogHeader><DialogTitle className="font-head">{form.id ? "Edit" : "Tambah"} {cfg.label}</DialogTitle></DialogHeader>
        {name === "suppliers" ? <SupplierEditor form={form} setForm={setForm} refs={refs} /> : <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-2">
            {cfg.fields.map((f) => <Field key={f.k} label={f.l + (f.auto ? " (Otomatis, bisa diedit)" : f.req ? " *" : "")}>
              {f.ref ? <Combobox options={refOptions(f.ref)} value={form[f.k] || ""} onChange={(v) => setForm({ ...form, [f.k]: v })} /> :
                <Input data-testid={`master-${name}-field-${f.k}`} type={f.type || "text"} step={f.step} min={f.type === "number" ? "0" : undefined} value={form[f.k] ?? ""} onChange={(e) => setForm({ ...form, [f.k]: e.target.value })} placeholder={f.auto ? "Kode otomatis" : undefined} className={f.auto ? "font-mono font-semibold" : ""} />}
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

        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)} data-testid={`master-${name}-form-cancel`}>Batal</Button><Button onClick={save} data-testid={`master-${name}-form-save`}>Simpan</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MasterQuickCreate({ name, open, onClose, onCreated }) {
  const [form, setForm] = useState({});
  const [refs, setRefs] = useState({});
  useEffect(() => {
    if (!open) return;
    newMasterForm(name).then(setForm);
    masterRefNames(name).forEach((rn) => api.get(`/lookup/${rn}`).then((r) => setRefs((s) => ({ ...s, [rn]: r.data }))).catch(() => {}));
  }, [open, name]);
  return <MasterFormDialog name={name} open={open} onOpenChange={(o) => !o && onClose()} form={form} setForm={setForm} refs={refs} onSaved={(doc) => { onClose(); onCreated(doc); }} />;
}

const STATUS_FILTER = [{ value: "", label: "Semua Status" }, { value: "Aktif", label: "Aktif" }, { value: "Nonaktif", label: "Nonaktif" }];
const sortKey = (f) => (f.ref ? `${f.k.slice(0, -3)}_label` : f.k);

const ITEM_REF_NAMES = masterRefNames("items");

function MasterTab({ name }) {
  if (name === "items") return <ItemStockTab FormDialog={MasterFormDialog} newForm={newMasterForm} refNames={ITEM_REF_NAMES} />;
  return <GenericMasterTab name={name} />;
}

function GenericMasterTab({ name }) {
  const cfg = CONFIGS[name];
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const list = useServerList(`/master/${name}`, { f_status_label: status });
  const rows = list.rows;
  const [refs, setRefs] = useState({});
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({});
  const [sel, setSel] = useState(new Set());
  const [delRows, setDelRows] = useState(null);
  const selectable = can("edit", name) || can("delete", name);
  useEffect(() => { setSel(new Set()); }, [list.q, status, name, list.page, list.pageSize, list.sort]);

  const loadRef = useCallback((rn) => api.get(`/lookup/${rn}`).then((r) => setRefs((s) => ({ ...s, [rn]: r.data }))).catch(() => {}), []);
  useEffect(() => { masterRefNames(name).forEach(loadRef); }, [name, loadRef]);

  const openAdd = async () => { setForm(await newMasterForm(name)); setOpen(true); };

  const openEdit = (row) => {
    const copy = { ...row };
    ["status_label", "category_label", "division_label", "base_uom_label", "supplier_category_label"].forEach((k) => delete copy[k]);
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

  const labelOf = (r) => [r.code, r.name].filter(Boolean).join(" — ") || "-";
  const selRows = rows.filter((r) => sel.has(r.id));
  const allOn = rows.length > 0 && rows.every((r) => sel.has(r.id));
  const toggle = (id) => setSel((cur) => { const n = new Set(cur); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const askDelete = (list) => setDelRows(list.map((r) => ({ id: r.id, label: labelOf(r) })));
  const refName = (rn, id) => (refs[rn] || []).find((x) => x.id === id)?.name || "-";
  const displayField = (f, r) => {
    if (f.ref) return r[sortKey(f)] || (r[f.k] ? refName(f.ref, r[f.k]) : "-");
    const value = r[f.k];
    if (value === undefined || value === null || value === "") return "-";
    return f.suffix ? `${value}${f.suffix}` : value;
  };
  const onSort = (k) => list.setSort(nextSort(list.sort, k));

  return <div>
    <div className="flex flex-wrap items-center justify-between mb-4 gap-3">
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <div className="relative max-w-sm flex-1 min-w-[220px]"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" /><Input value={list.q} onChange={(e) => list.setQ(e.target.value)} placeholder={`Cari ${cfg.label}...`} className="pl-9" data-testid={`master-${name}-search`} /></div>
        <div className="w-44" data-testid={`master-${name}-status-filter`}><Combobox options={STATUS_FILTER} value={status} onChange={setStatus} placeholder="Status" /></div>
      </div>
      {can("create", name) && <Button onClick={openAdd} data-testid={`master-${name}-add`}><Plus className="h-4 w-4 mr-2" />Tambah {cfg.label}</Button>}
    </div>

    {selRows.length > 0 && <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm" data-testid={`master-${name}-selection-bar`}>
      <span className="font-semibold" data-testid={`master-${name}-selected-count`}>{selRows.length} dipilih</span>
      {selRows.length === 1 && can("edit", name) && <Button size="sm" variant="outline" onClick={() => openEdit(selRows[0])} data-testid={`master-${name}-bar-edit`}><Pencil className="mr-1.5 h-3.5 w-3.5" />Edit</Button>}
      {can("delete", name) && <Button size="sm" variant="outline" onClick={() => askDelete(selRows)} data-testid={`master-${name}-bar-delete`}><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />{selRows.length === 1 ? "Hapus" : "Hapus Massal"}</Button>}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSel(new Set())} data-testid={`master-${name}-clear-selection`}>Batal pilih</Button>
    </div>}
    <div className="border rounded-xl overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
      {selectable && <th className="w-10 p-3"><Checkbox checked={allOn} onCheckedChange={() => setSel(allOn ? new Set() : new Set(rows.map((r) => r.id)))} aria-label="Pilih semua di halaman ini" data-testid={`master-${name}-select-all`} /></th>}
      {cfg.fields.slice(0, 5).map((f) => <SortTh key={f.k} label={f.l} k={sortKey(f)} sort={list.sort} onSort={onSort} testid={`master-${name}`} />)}<SortTh label="Status" k="status_label" sort={list.sort} onSort={onSort} testid={`master-${name}`} /><th className="p-3 w-40 text-right">Aksi</th></tr></thead>
      <tbody>{rows.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-muted-foreground" data-testid={`master-${name}-empty`}>{list.loading ? "Memuat..." : list.error ? "Gagal memuat data" : list.q || status ? "Tidak ada data yang cocok" : "Belum ada data"}</td></tr>}
        {rows.map((r) => <tr key={r.id} className={`border-t hover:bg-accent/40 transition-colors ${sel.has(r.id) ? "bg-primary/5" : ""}`} data-testid={`master-${name}-row-${r.code || r.id}`}>
          {selectable && <td className="p-3"><Checkbox checked={sel.has(r.id)} onCheckedChange={() => toggle(r.id)} aria-label={`Pilih ${labelOf(r)}`} data-testid={`master-${name}-select-${r.code || r.id}`} /></td>}
          {cfg.fields.slice(0, 5).map((f) => <td key={f.k} className={`p-3 ${f.k === "code" ? "font-mono text-xs font-semibold" : ""}`}>{displayField(f, r)}</td>)}
          <td className="p-3"><StatusBadge status={r.is_active ? "Aktif" : "Nonaktif"} className={r.is_active ? "bg-emerald-50 text-emerald-700 border-emerald-200" : ""} /></td>
          <td className="p-3"><div className="flex justify-end gap-1">
            {can("edit", name) && <Button variant="ghost" size="sm" className="h-8" onClick={() => openEdit(r)} data-testid={`master-${name}-edit-${r.code || r.id}`}><Pencil className="mr-1 h-3.5 w-3.5" />Edit</Button>}
            {can("delete", name) && <Button variant="ghost" size="sm" className="h-8 text-destructive hover:text-destructive" onClick={() => askDelete([r])} data-testid={`master-${name}-delete-${r.code || r.id}`}><Trash2 className="mr-1 h-3.5 w-3.5" />Hapus</Button>}
          </div></td>
        </tr>)}</tbody></table></div>
    <ListPager total={list.total} page={list.page} pageSize={list.pageSize} setPage={list.setPage} setPageSize={list.setPageSize} testid={`master-${name}`} />
    <MasterDeleteDialog open={!!delRows} rows={delRows || []} checkName={name} entityLabel={cfg.label} onDeselect={(ids) => setSel((c) => new Set([...c].filter((x) => !ids.includes(x))))} onClose={() => setDelRows(null)} onDone={() => { setDelRows(null); setSel(new Set()); list.reload(); }} />

    <MasterFormDialog name={name} open={open} onOpenChange={setOpen} form={form} setForm={setForm} refs={refs} onSaved={() => { setOpen(false); setForm({}); list.reload(); }} />
  </div>;
}

const iwKey = (r) => `${r.item_id}|${r.warehouse_id}`;
const iwLabel = (r) => `${r.item_code || "-"} — ${r.item_name || "-"} @ ${r.warehouse_name || "-"}`;

const IW_STATUS = [{ value: "", label: "Semua Status" }, { value: "Normal", label: "Normal" }, { value: "Low Stock", label: "Stok Menipis" }, { value: "Out of Stock", label: "Stok Habis" }, { value: "Overstock", label: "Melebihi Maksimum" }];

function ItemWarehouseTab() {
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const list = useServerList("/item-warehouse", { f_status: status });
  const rows = list.rows;
  const [items, setItems] = useState([]);
  const [whs, setWhs] = useState([]);
  const [form, setForm] = useState({ item_id: "", warehouse_id: "", min_stock: 0, max_stock: 0 });
  const [sel, setSel] = useState(new Set());
  const [delRows, setDelRows] = useState(null);
  const selectable = can("edit", "stock_minmax") || can("delete", "stock_minmax");
  useEffect(() => { setSel(new Set()); }, [list.q, status, list.page, list.pageSize, list.sort]);
  useEffect(() => { api.get("/lookup/items").then((r) => setItems(r.data)).catch(() => {}); api.get("/lookup/warehouses").then((r) => setWhs(r.data)).catch(() => {}); }, []);
  const save = async () => { try { await api.post("/item-warehouse", form); toast.success("Stok Min/Max tersimpan"); list.reload(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };
  const edit = (r) => { setForm({ item_id: r.item_id, warehouse_id: r.warehouse_id, min_stock: r.min_stock || 0, max_stock: r.max_stock || 0 }); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const selRows = rows.filter((r) => sel.has(iwKey(r)));
  const allOn = rows.length > 0 && rows.every((r) => sel.has(iwKey(r)));
  const toggle = (k) => setSel((c) => { const n = new Set(c); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const askDelete = (list) => setDelRows(list.map((r) => ({ id: iwKey(r), label: iwLabel(r) })));
  const onSort = (k) => list.setSort(nextSort(list.sort, k));
  const th = (label, k, cls = "") => <SortTh label={label} k={k} sort={list.sort} onSort={onSort} className={cls} testid="minmax" />;
  return <div className="space-y-4">
    <Card><CardContent className="pt-6"><div className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end" data-testid="minmax-form">
      <Field label="Barang"><Combobox options={items.map((i) => ({ value: i.id, label: i.name }))} value={form.item_id} onChange={(v) => setForm({ ...form, item_id: v })} /></Field>
      <Field label="Gudang"><Combobox options={whs.map((w) => ({ value: w.id, label: w.name }))} value={form.warehouse_id} onChange={(v) => setForm({ ...form, warehouse_id: v })} /></Field>
      <Field label="Stok Minimum"><Input type="number" value={form.min_stock} onChange={(e) => setForm({ ...form, min_stock: Number(e.target.value) })} data-testid="minmax-min-input" /></Field>
      <Field label="Stok Maksimum"><Input type="number" value={form.max_stock} onChange={(e) => setForm({ ...form, max_stock: Number(e.target.value) })} data-testid="minmax-max-input" /></Field>
      <Button onClick={save} disabled={!form.item_id || !form.warehouse_id || !can("edit", "stock_minmax")} data-testid="minmax-save">Simpan Min/Max</Button>
    </div></CardContent></Card>
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative max-w-sm flex-1 min-w-[220px]"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" /><Input value={list.q} onChange={(e) => list.setQ(e.target.value)} placeholder="Cari barang atau gudang..." className="pl-9" data-testid="minmax-search" /></div>
      <div className="w-48" data-testid="minmax-status-filter"><Combobox options={IW_STATUS} value={status} onChange={setStatus} placeholder="Status" /></div>
    </div>
    {selRows.length > 0 && <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm" data-testid="minmax-selection-bar">
      <span className="font-semibold" data-testid="minmax-selected-count">{selRows.length} dipilih</span>
      {selRows.length === 1 && can("edit", "stock_minmax") && <Button size="sm" variant="outline" onClick={() => edit(selRows[0])} data-testid="minmax-bar-edit"><Pencil className="mr-1.5 h-3.5 w-3.5" />Edit</Button>}
      {can("delete", "stock_minmax") && <Button size="sm" variant="outline" onClick={() => askDelete(selRows)} data-testid="minmax-bar-delete"><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />{selRows.length === 1 ? "Hapus" : "Hapus Massal"}</Button>}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSel(new Set())} data-testid="minmax-clear-selection">Batal pilih</Button>
    </div>}
    <div><div className="border rounded-xl overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
      {selectable && <th className="w-10 p-3"><Checkbox checked={allOn} onCheckedChange={() => setSel(allOn ? new Set() : new Set(rows.map(iwKey)))} aria-label="Pilih semua di halaman ini" data-testid="minmax-select-all" /></th>}
      {th("Barang", "item_name")}{th("Gudang", "warehouse_name")}{th("Stok Saat Ini", "current_stock", "text-right")}{th("Min", "min_stock", "text-right")}{th("Maks", "max_stock", "text-right")}{th("Saran Order", "suggested_order", "text-right")}{th("Status", "status")}<th className="p-3 w-40 text-right">Aksi</th></tr></thead>
      <tbody>{rows.length === 0 && <tr><td colSpan={9} className="p-8 text-center text-muted-foreground" data-testid="minmax-empty">{list.loading ? "Memuat..." : list.error ? "Gagal memuat data" : list.q || status ? "Tidak ada data yang cocok" : "Belum ada konfigurasi"}</td></tr>}
        {rows.map((r, i) => <tr key={iwKey(r)} className={`border-t ${sel.has(iwKey(r)) ? "bg-primary/5" : ""}`} data-testid={`minmax-row-${i}`}>
          {selectable && <td className="p-3"><Checkbox checked={sel.has(iwKey(r))} onCheckedChange={() => toggle(iwKey(r))} aria-label={`Pilih ${iwLabel(r)}`} data-testid={`minmax-select-${i}`} /></td>}
          <td className="p-3">{r.item_code} — {r.item_name}</td><td className="p-3">{r.warehouse_name}</td><td className="p-3 text-right font-semibold">{num(r.current_stock)}</td><td className="p-3 text-right">{num(r.min_stock)}</td><td className="p-3 text-right">{num(r.max_stock)}</td><td className="p-3 text-right">{num(r.suggested_order)}</td><td className="p-3"><StatusBadge status={r.status} /></td>
          <td className="p-3"><div className="flex justify-end gap-1">{can("edit", "stock_minmax") && <Button variant="ghost" size="sm" className="h-8" onClick={() => edit(r)} data-testid={`minmax-edit-${i}`}><Pencil className="mr-1 h-3.5 w-3.5" />Edit</Button>}{can("delete", "stock_minmax") && <Button variant="ghost" size="sm" className="h-8 text-destructive hover:text-destructive" onClick={() => askDelete([r])} data-testid={`minmax-delete-${i}`}><Trash2 className="mr-1 h-3.5 w-3.5" />Hapus</Button>}</div></td>
        </tr>)}</tbody></table></div>
      <ListPager total={list.total} page={list.page} pageSize={list.pageSize} setPage={list.setPage} setPageSize={list.setPageSize} testid="minmax" /></div>
    <MasterDeleteDialog open={!!delRows} rows={delRows || []} checkName="item_warehouse" entityLabel="Stok Min/Max" onDeselect={(ids) => setSel((c) => new Set([...c].filter((x) => !ids.includes(x))))} onClose={() => setDelRows(null)} onDone={() => { setDelRows(null); setSel(new Set()); list.reload(); }} />
  </div>;
}

function MasterCard({ card, count, onClick }) {
  const Icon = card.icon;
  return <button type="button" onClick={onClick} data-testid={`master-card-${card.key}`} className="group w-full rounded-2xl border bg-card p-4 sm:p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
    <div className="flex items-center gap-4"><div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Icon className="h-6 w-6" /></div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h3 className="font-head text-base font-semibold">{card.label}</h3>{count !== undefined && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{count} data</span>}</div><p className="mt-1 text-xs sm:text-sm text-muted-foreground line-clamp-2">{card.desc}</p></div><ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
  </button>;
}

export default function MasterData() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [active, setActive] = useState(null);
  const [counts, setCounts] = useState({});
  const loadCounts = async () => {
    const keys = Object.keys(CONFIGS).filter((k) => can("view", k)); const out = {};
    const one = { params: { page: 1, page_size: 25 } };
    await Promise.all(keys.map(async (k) => { try { const r = await api.get(`/master/${k}`, one); out[k] = r.data.total; } catch { out[k] = 0; } }));
    if (can("view", "stock_minmax")) { try { const r = await api.get("/item-warehouse", one); out.iw = r.data.total; } catch { out.iw = 0; } }
    setCounts(out);
  };
  useEffect(() => { loadCounts(); }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  if (active) {
    const title = active === "iw" ? "Stok Min/Max" : CONFIGS[active]?.label;
    return <div><PageHeader title={title} subtitle="Kelola master data dan referensi transaksi"><Button variant="outline" onClick={() => setActive(null)}><ArrowLeft className="h-4 w-4 mr-2" />Kembali ke Master Data</Button></PageHeader>{active === "iw" ? <ItemWarehouseTab /> : <MasterTab name={active} />}</div>;
  }

  return <div><PageHeader title="Master Data" subtitle="Pilih master yang ingin dikelola. Form dibuka setelah kartu dipilih." /><div className="space-y-7">
    {(can("spk:view") || can("vendor_contract:view")) && <section><div className="mb-3"><h2 className="font-head text-sm font-semibold">Procurement</h2><p className="mt-1 text-xs text-muted-foreground">Kontrak kerja, harga vendor & kontrol budget procurement.</p></div>
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
        {can("spk:view") && <button type="button" onClick={() => navigate("/spk")} data-testid="master-spk-card" className="group w-full rounded-2xl border bg-card p-4 sm:p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
          <div className="flex items-center gap-4"><div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><ClipboardList className="h-6 w-6" /></div><div className="min-w-0 flex-1"><h3 className="font-head text-base font-semibold">SPK</h3><p className="mt-1 text-xs sm:text-sm text-muted-foreground line-clamp-2">Master Surat Perintah Kerja: nilai SPK, budget procurement, budget control policy, dan dokumen.</p></div><ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
        </button>}
        {can("vendor_contract:view") && <button type="button" onClick={() => navigate("/vendor-contracts")} data-testid="master-vendor-contract-card" className="group w-full rounded-2xl border bg-card p-4 sm:p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
          <div className="flex items-center gap-4"><div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Handshake className="h-6 w-6" /></div><div className="min-w-0 flex-1"><h3 className="font-head text-base font-semibold">Kontrak Harga Vendor</h3><p className="mt-1 text-xs sm:text-sm text-muted-foreground line-clamp-2">Master kontrak harga vendor: item harga, diskon, net price, periode berlaku, tolerance, histori harga, dan dokumen.</p></div><ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
        </button>}
      </div></section>}
    {MASTER_GROUPS.filter((group) => group.cards.some((card) => can("view", MASTER_MODULE[card.key] || card.key))).map((group) => <section key={group.title}><div className="mb-3"><h2 className="font-head text-sm font-semibold">{group.title}</h2><p className="mt-1 text-xs text-muted-foreground">{group.subtitle}</p></div><div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">{group.cards.filter((card) => can("view", MASTER_MODULE[card.key] || card.key)).map((card) => <MasterCard key={card.key} card={card} count={counts[card.key]} onClick={() => setActive(card.key)} />)}</div></section>)}</div></div>;
}
