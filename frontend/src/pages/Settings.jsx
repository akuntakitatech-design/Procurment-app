import { useEffect, useMemo, useRef, useState } from "react";
import api, { API, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { clearDocumentMessageDefaultsCache } from "@/components/DocumentMessageEditor";
import { EmailOutbound } from "@/components/EmailOutboundSettings";
import { Save, Trash2, Image as ImageIcon, Plus, ArrowUp, ArrowDown, FileText } from "lucide-react";
import { toast } from "sonner";

function Company() {
  const [c, setC] = useState({});
  const [logoFile, setLogoFile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [previewVersion, setPreviewVersion] = useState(Date.now());
  const fileRef = useRef(null);
  useEffect(() => { api.get("/settings/company").then((r) => setC(r.data)); }, []);
  const localPreview = useMemo(() => logoFile ? URL.createObjectURL(logoFile) : null, [logoFile]);
  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview); }, [localPreview]);
  const savedLogo = c.logo_path ? `${API}/company/logo?v=${encodeURIComponent(c.logo_version || previewVersion)}` : null;
  const logoPreview = localPreview || savedLogo;
  const clearFileInput = () => { setLogoFile(null); if (fileRef.current) fileRef.current.value = ""; };
  const save = async () => {
    try {
      setSaving(true);
      const payload = { ...c, name: c.name || "", address: c.address || "", app_subtitle: c.app_subtitle || "Procurement & Inventory" };
      delete payload.logo_url;
      let company = (await api.put("/settings/company", payload)).data;
      if (logoFile) {
        const form = new FormData(); form.append("file", logoFile);
        company = (await api.post("/settings/company/logo", form, { headers: { "Content-Type": "multipart/form-data" } })).data;
      }
      setC(company); clearFileInput(); setPreviewVersion(Date.now());
      toast.success(logoFile ? "Data perusahaan dan logo tersimpan" : "Data perusahaan tersimpan");
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };
  const deleteLogo = async () => {
    try { await api.delete("/settings/company/logo"); setC((cur) => ({ ...cur, logo_path: null, logo_filename: null, logo_version: null })); clearFileInput(); setPreviewVersion(Date.now()); toast.success("Logo perusahaan dihapus"); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  return <Card><CardContent className="pt-6 space-y-6">
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4"><Field label="Nama Perusahaan"><Input value={c.name || ""} onChange={(e) => setC({ ...c, name: e.target.value })} /></Field><Field label="Subjudul Aplikasi"><Input value={c.app_subtitle || "Procurement & Inventory"} onChange={(e) => setC({ ...c, app_subtitle: e.target.value })} /></Field><Field label="Alamat"><Input value={c.address || ""} onChange={(e) => setC({ ...c, address: e.target.value })} /></Field></div>
    <div className="rounded-xl border bg-muted/20 p-4"><div className="mb-3"><div className="font-head font-semibold">Logo Perusahaan</div><p className="text-xs text-muted-foreground">PNG, JPG/JPEG, atau WEBP, maksimal 5 MB.</p></div><div className="flex flex-col gap-4 sm:flex-row sm:items-center"><div className="flex h-24 w-40 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-background">{logoPreview ? <img src={logoPreview} alt="Logo perusahaan" className="h-full w-full object-contain p-2" /> : <div className="flex flex-col items-center gap-1 text-muted-foreground"><ImageIcon className="h-7 w-7" /><span className="text-[11px]">Belum ada logo</span></div>}</div><div className="flex-1 space-y-3"><Input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setLogoFile(e.target.files?.[0] || null)} />{logoFile && <p className="text-xs font-medium text-primary">Logo baru dipilih: {logoFile.name}</p>}{!logoFile && c.logo_filename && <p className="text-xs text-muted-foreground">Logo tersimpan: {c.logo_filename}</p>}{(c.logo_path || logoFile) && <Button type="button" variant="outline" onClick={deleteLogo} disabled={saving}><Trash2 className="mr-2 h-4 w-4" />Hapus Logo</Button>}</div></div></div>
    <Button onClick={save} disabled={saving}><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Data Perusahaan"}</Button>
  </CardContent></Card>;
}

function Numbering() {
  const [n, setN] = useState({ formats: {} });
  useEffect(() => { api.get("/settings/numbering").then((r) => setN(r.data)); }, []);
  const save = async () => { await api.put("/settings/numbering", n); toast.success("Tersimpan"); };
  return <Card><CardContent className="pt-6 space-y-4"><p className="text-sm text-muted-foreground">Placeholder: <code>{"{year}"}</code>, <code>{"{month}"}</code>, <code>{"{seq}"}</code></p><div className="grid grid-cols-1 md:grid-cols-2 gap-4">{Object.entries(n.formats || {}).map(([k, v]) => <Field key={k} label={k}><Input value={v} onChange={(e) => setN({ ...n, formats: { ...n.formats, [k]: e.target.value } })} className="font-mono" /></Field>)}</div><Button onClick={save}><Save className="h-4 w-4 mr-2" />Simpan</Button></CardContent></Card>;
}

const APPROVAL_MODULES = [
  { key: "mro", code: "MRO", name: "Material Request Order", desc: "Approval kebutuhan material sebelum dapat ditarik ke RO/MI." },
  { key: "ro", code: "RO", name: "Request Order", desc: "Approval permintaan pembelian sebelum dapat ditarik menjadi PO." },
  { key: "po", code: "PO", name: "Purchase Order", desc: "Approval pesanan pembelian sebelum dapat diterima melalui DO." },
];

function ApprovalLevels() {
  const [cfg, setCfg] = useState({ modules: {} });
  const [users, setUsers] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api.get("/settings/approval_modules"), api.get("/settings/approval_levels"), api.get("/users")]).then(([modulesRes, legacyRes, usersRes]) => {
      const modules = modulesRes.data?.modules || {};
      if (Object.keys(modules).length === 0 && (legacyRes.data?.levels || []).length > 0) {
        modules.po = { enabled: true, levels: legacyRes.data.levels };
      }
      const normalized = {};
      APPROVAL_MODULES.forEach((m) => {
        normalized[m.key] = {
          enabled: !!modules[m.key]?.enabled,
          levels: (modules[m.key]?.levels || []).map((x, i) => ({ ...x, level: i + 1 })),
        };
      });
      setCfg({ modules: normalized });
      setUsers((usersRes.data || []).filter((u) => u.is_active !== false));
    });
  }, []);

  const userOptions = users.map((u) => ({ value: u.id, label: `${u.name || u.email} — ${u.email}`, selectedLabel: u.name || u.email }));
  const moduleCfg = (key) => cfg.modules?.[key] || { enabled: false, levels: [] };
  const setModule = (key, patch) => setCfg((cur) => ({ modules: { ...cur.modules, [key]: { ...moduleCfg(key), ...patch } } }));
  const toggle = (key) => setModule(key, { enabled: !moduleCfg(key).enabled });
  const choose = (key, idx, uid) => {
    const u = users.find((x) => x.id === uid);
    const levels = moduleCfg(key).levels.map((r, i) => i === idx ? { level: i + 1, user_id: uid, email: u?.email || "", name: u?.name || u?.email || "" } : r);
    setModule(key, { levels });
  };
  const add = (key) => setModule(key, { levels: [...moduleCfg(key).levels, { level: moduleCfg(key).levels.length + 1, user_id: "", email: "", name: "" }] });
  const remove = (key, idx) => setModule(key, { levels: moduleCfg(key).levels.filter((_, i) => i !== idx).map((r, i) => ({ ...r, level: i + 1 })) });
  const move = (key, idx, dir) => {
    const arr = [...moduleCfg(key).levels]; const j = idx + dir;
    if (j < 0 || j >= arr.length) return;
    [arr[idx], arr[j]] = [arr[j], arr[idx]];
    setModule(key, { levels: arr.map((r, i) => ({ ...r, level: i + 1 })) });
  };
  const save = async () => {
    try {
      for (const m of APPROVAL_MODULES) {
        const row = moduleCfg(m.key);
        if (row.enabled && row.levels.length === 0) return toast.error(`${m.code}: tambahkan minimal 1 approver`);
        if (row.enabled && row.levels.some((x) => !x.user_id || !x.email)) return toast.error(`${m.code}: semua level harus memilih user`);
      }
      setSaving(true);
      const payload = { modules: {} };
      APPROVAL_MODULES.forEach((m) => {
        const row = moduleCfg(m.key);
        payload.modules[m.key] = {
          enabled: !!row.enabled,
          levels: row.levels.map((x, i) => ({ ...x, level: i + 1 })),
        };
      });
      const res = await api.put("/settings/approval_modules", payload);
      setCfg({ modules: res.data?.modules || payload.modules });
      toast.success("Pengaturan approval per modul tersimpan");
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  return <Card><CardContent className="pt-6 space-y-5">
    <div><div className="font-head font-semibold">Approval per Modul</div><p className="text-sm text-muted-foreground mt-1">Aktifkan hanya modul yang membutuhkan approval. Setiap modul dapat memiliki urutan dan PIC approver yang berbeda berdasarkan email user.</p></div>
    <div className="grid gap-4">
      {APPROVAL_MODULES.map((m) => {
        const row = moduleCfg(m.key);
        return <div key={m.key} className={`rounded-xl border p-4 transition-colors ${row.enabled ? "border-primary/50 bg-primary/[0.02]" : "bg-muted/10"}`}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0"><div className="flex items-center gap-2"><span className="rounded-md bg-muted px-2 py-1 font-mono text-xs font-semibold">{m.code}</span><div className="font-head font-semibold">{m.name}</div></div><p className="mt-1 text-xs text-muted-foreground">{m.desc}</p></div>
            <label className="flex shrink-0 cursor-pointer items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm font-medium"><input type="checkbox" checked={!!row.enabled} onChange={() => toggle(m.key)} className="h-4 w-4 accent-current" />Gunakan Approval</label>
          </div>
          {row.enabled && <div className="mt-4 space-y-3 border-t pt-4">
            {row.levels.length === 0 && <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">Belum ada approver untuk {m.code}. Tambahkan minimal satu level.</div>}
            {row.levels.map((level, i) => <div key={i} className="grid grid-cols-1 md:grid-cols-[110px_1fr_auto] gap-3 items-end rounded-lg border bg-background p-3">
              <Field label="Tingkatan"><div className="h-9 flex items-center font-semibold">Level {i + 1}</div></Field>
              <Field label="User / Email"><Combobox options={userOptions} value={level.user_id || ""} onChange={(v) => choose(m.key, i, v)} placeholder="Pilih user approver" /></Field>
              <div className="flex gap-1"><Button variant="outline" size="icon" onClick={() => move(m.key, i, -1)} disabled={i === 0}><ArrowUp className="h-4 w-4" /></Button><Button variant="outline" size="icon" onClick={() => move(m.key, i, 1)} disabled={i === row.levels.length - 1}><ArrowDown className="h-4 w-4" /></Button><Button variant="ghost" size="icon" onClick={() => remove(m.key, i)}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>
              {level.email && <div className="md:col-start-2 text-xs text-muted-foreground">{level.email}</div>}
            </div>)}
            <Button variant="outline" size="sm" onClick={() => add(m.key)}><Plus className="h-4 w-4 mr-2" />Tambah Level {m.code}</Button>
          </div>}
        </div>;
      })}
    </div>
    <div className="rounded-lg bg-muted/40 p-3 text-xs text-muted-foreground">Modul yang tidak dicentang akan mengikuti alur normal tanpa approval. Untuk saat ini approval pra-proses tersedia pada MRO, RO, dan PO; transaksi yang langsung memengaruhi stok tetap diposting melalui alur gudang normal.</div>
    <Button onClick={save} disabled={saving}><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Approval"}</Button>
  </CardContent></Card>;
}

const MESSAGE_MODULES = [
  ["mro", "MRO", "Permintaan Material"], ["ro", "RO", "Permintaan Pembelian"], ["po", "PO", "Pesanan Pembelian"],
  ["do", "DO", "Penerimaan Barang"], ["mi", "MI", "Pengeluaran Barang"], ["transfer", "TRF", "Transfer Antar Gudang"],
  ["loan", "LOAN", "Pinjam Antar Gudang"], ["adjustment", "ADJ", "Penyesuaian Stok"], ["opname", "OPN", "Stock Opname"],
];

function DocumentMessages() {
  const [modules, setModules] = useState({});
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.get("/settings/document_messages").then((r) => setModules(r.data?.modules || {})); }, []);
  const save = async () => {
    try {
      setSaving(true);
      const r = await api.put("/settings/document_messages", { modules });
      setModules(r.data?.modules || modules);
      clearDocumentMessageDefaultsCache();
      toast.success("Pesan default dokumen tersimpan");
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };
  return <div className="space-y-4">
    <Card><CardContent className="pt-6"><div className="flex items-start gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/8 text-primary"><FileText className="h-4.5 w-4.5" /></div><div><div className="font-head font-semibold">Pesan Default per Transaksi</div><p className="mt-1 text-sm leading-6 text-muted-foreground">Pesan otomatis dimasukkan saat membuat transaksi baru, tetapi tetap dapat diedit pada transaksi tersebut. Setelah disimpan, teks menjadi snapshot sehingga perubahan default berikutnya tidak mengubah transaksi lama.</p></div></div></CardContent></Card>
    <div className="grid gap-4">
      {MESSAGE_MODULES.map(([key, code, name]) => <Card key={key} className="rounded-2xl shadow-none"><CardContent className="pt-5 space-y-3"><div><div className="flex items-center gap-2"><span className="rounded-md bg-muted px-2 py-1 font-mono text-xs font-semibold">{code}</span><div className="font-head font-semibold">{name}</div></div><p className="mt-1 text-xs text-muted-foreground">Teks ini akan muncul di bagian bawah form {name} baru.</p></div><textarea rows={key === "po" ? 14 : 7} value={modules[key] || ""} onChange={(e) => setModules((cur) => ({ ...cur, [key]: e.target.value }))} placeholder={`Pesan default ${name}...`} className="w-full resize-y rounded-xl border border-input bg-background px-3.5 py-3 text-sm leading-6 outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/10" /></CardContent></Card>)}
    </div>
    <Button onClick={save} disabled={saving} className="rounded-xl"><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Pesan Default"}</Button>
  </div>;
}

export default function Settings() {
  return <div><PageHeader title="System Settings" subtitle="Konfigurasi perusahaan, branding, email outbound, penomoran, approval, dan pesan dokumen" /><Tabs defaultValue="company"><TabsList className="flex-wrap h-auto"><TabsTrigger value="company">Perusahaan</TabsTrigger><TabsTrigger value="email">Email Outbound</TabsTrigger><TabsTrigger value="numbering">Penomoran</TabsTrigger><TabsTrigger value="approval">Approval</TabsTrigger><TabsTrigger value="messages">Pesan Default Dokumen</TabsTrigger></TabsList><TabsContent value="company" className="mt-4"><Company /></TabsContent><TabsContent value="email" className="mt-4"><EmailOutbound /></TabsContent><TabsContent value="numbering" className="mt-4"><Numbering /></TabsContent><TabsContent value="approval" className="mt-4"><ApprovalLevels /></TabsContent><TabsContent value="messages" className="mt-4"><DocumentMessages /></TabsContent></Tabs></div>;
}
