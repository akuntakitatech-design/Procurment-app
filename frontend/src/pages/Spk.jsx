import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { API, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox } from "@/components/MasterRefCombobox";
import { StatusBadge } from "@/components/StatusBadge";
import { Field } from "@/components/DatePicker";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ListPager, SortTh } from "@/components/ListPager";
import { MasterDeleteDialog } from "@/components/MasterDeleteDialog";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import {
  Plus, Search, Pencil, ArrowLeft, FileText, Upload, Trash2, Download, ShieldCheck,
  Wallet, TrendingUp, Layers3, Info, ClipboardList,
} from "lucide-react";
import { toast } from "sonner";

const rupiah = (v) => "Rp " + (Number(v || 0)).toLocaleString("id-ID");
const parseMoney = (s) => {
  const n = String(s ?? "").replace(/[^\d]/g, "");
  return n === "" ? "" : Number(n);
};
const STATUS_OPTS = [
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "closed", label: "Closed" },
  { value: "cancelled", label: "Cancelled" },
];
const POLICY_OPTS = [
  { value: "WARNING_ONLY", label: "Hanya Peringatan" },
  { value: "HARD_BLOCK", label: "Blokir Tegas" },
];
const statusMap = { draft: "Draft", active: "Normal", closed: "Selesai", cancelled: "cancelled" };
const policyLabel = (p) => (p === "HARD_BLOCK" ? "Blokir Tegas" : p === "WARNING_ONLY" ? "Hanya Peringatan" : "-");

function MoneyInput({ value, onChange, ...props }) {
  return <Input inputMode="numeric" value={value === "" || value == null ? "" : Number(value).toLocaleString("id-ID")}
    onChange={(e) => onChange(parseMoney(e.target.value))} {...props} />;
}

// Stable module-scope component so SpkForm re-renders (on every keystroke) never
// recreate/remount this subtree — preventing input focus loss while typing.
function FormSection({ title, icon: Icon, children, desc }) {
  return (
    <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
      <div className="flex items-center gap-2"><Icon className="h-4 w-4 text-primary" /><h3 className="font-head font-semibold">{title}</h3></div>
      {desc && <p className="text-xs text-muted-foreground -mt-2">{desc}</p>}
      {children}
    </div>
  );
}

/* ============================== LIST ============================== */
export function SpkList() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [sel, setSel] = useState(new Set()); const [delRows, setDelRows] = useState(null);
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 20 });
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [divisionId, setDivisionId] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState("-created_at");
  const [divisions, setDivisions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.get("/lookup/divisions").then((r) => setDivisions(r.data || [])).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ q, status, division_id: divisionId, sort, page: String(page), page_size: String(pageSize) });
      const r = await api.get(`/spk?${params.toString()}`);
      setData(r.data || { items: [], total: 0 });
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [q, status, divisionId, sort, page, pageSize]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);
  useEffect(() => { setSel(new Set()); }, [q, status, divisionId, sort, page, pageSize]);

  const sortObj = { key: sort.replace(/^-/, ""), dir: sort.startsWith("-") ? "desc" : "asc" };
  const toggleSort = (key) => { setPage(1); setSort((s) => (s === key ? `-${key}` : s === `-${key}` ? key : `-${key}`)); };
  const th = (label, k, cls = "") => <SortTh label={label} k={k} sort={sortObj} onSort={toggleSort} className={cls} testid="spk" />;

  return (
    <div>
      <PageHeader title="Master SPK" subtitle="Surat Perintah Kerja sebagai sumber kontrol budget Procurement">
        {can("spk:manage") && <Button onClick={() => nav("/spk/new")} data-testid="spk-add-btn"><Plus className="h-4 w-4 mr-2" />Tambah SPK</Button>}
      </PageHeader>

      <div className="flex flex-col lg:flex-row gap-3 mb-4">
        <div className="relative flex-1 max-w-md"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => { setPage(1); setQ(e.target.value); }} placeholder="Cari No SPK, pekerjaan, customer, PIC..." className="pl-9" data-testid="spk-search" /></div>
        <div className="w-full sm:w-48"><Combobox options={[{ value: "", label: "Semua Status" }, ...STATUS_OPTS]} value={status} onChange={(v) => { setPage(1); setStatus(v); }} placeholder="Status" /></div>
        <div className="w-full sm:w-56"><Combobox options={[{ value: "", label: "Semua Divisi" }, ...divisions.map((d) => ({ value: d.id, label: d.name }))]} value={divisionId} onChange={(v) => { setPage(1); setDivisionId(v); }} placeholder="Divisi" /></div>
      </div>

      {sel.size>0&&<div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm" data-testid="spk-selection-bar"><span className="font-semibold" data-testid="spk-selected-count">{sel.size} dipilih</span>{sel.size===1&&can("spk:manage")&&<Button size="sm" variant="outline" data-testid="spk-bar-edit" onClick={()=>{const r=data.items.find((x)=>sel.has(x.id));if(r)nav(`/spk/${r.id}/edit`);}}><Pencil className="mr-1.5 h-3.5 w-3.5" />Edit</Button>}{can("delete")&&<Button size="sm" variant="outline" data-testid="spk-bar-delete" onClick={()=>setDelRows(data.items.filter((x)=>sel.has(x.id)).map((r)=>({id:r.id,label:[r.spk_number, r.project_name].filter(Boolean).join(" — ")})))}><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />{sel.size===1?"Hapus":"Hapus Massal"}</Button>}<Button size="sm" variant="ghost" className="ml-auto" onClick={()=>setSel(new Set())} data-testid="spk-clear-selection">Batal pilih</Button></div>}<MasterDeleteDialog open={!!delRows} rows={delRows||[]} checkName="spk" entityLabel="SPK" onDeselect={(ids)=>setSel((c)=>new Set([...c].filter((x)=>!ids.includes(x))))} onClose={()=>setDelRows(null)} onDone={()=>{setDelRows(null);setSel(new Set());load();}} />
      <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-sm zebra">
          <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="w-10 p-3"><Checkbox checked={data.items.length>0&&data.items.every((x)=>sel.has(x.id))} onCheckedChange={()=>setSel(data.items.every((x)=>sel.has(x.id))?new Set():new Set(data.items.map((x)=>x.id)))} aria-label="Pilih semua" data-testid="spk-select-all" /></th>
            {th("No SPK", "spk_number")}
            {th("Nama Pekerjaan", "project_name")}
            {th("Customer", "customer")}
            <th className="p-3">Divisi</th>
            {th("PIC", "pic_name")}
            {th("Nilai SPK", "spk_value", "text-right")}
            {th("Budget Pengadaan", "procurement_budget", "text-right")}
            {th("Periode", "start_date")}
            <th className="p-3">Kebijakan</th>
            {th("Status", "status")}
            <th className="p-3 w-44 text-right">Aksi</th>
          </tr></thead>
          <tbody>
            {loading && <tr><td colSpan={11} className="p-8 text-center text-muted-foreground">Memuat...</td></tr>}
            {!loading && data.items.length === 0 && <tr><td colSpan={11} className="p-8 text-center text-muted-foreground">Belum ada SPK</td></tr>}
            {!loading && data.items.map((r) => (
              <tr key={r.id} className="border-t hover:bg-accent/40 cursor-pointer transition-colors" onClick={() => nav(`/spk/${r.id}`)} data-testid={`spk-row-${r.spk_number}`}>
                <td className="p-3" onClick={(e)=>e.stopPropagation()}><Checkbox checked={sel.has(r.id)} onCheckedChange={()=>setSel((c)=>{const n=new Set(c);n.has(r.id)?n.delete(r.id):n.add(r.id);return n;})} data-testid={`spk-select-${r.spk_number}`} /></td>
                <td className="p-3 font-mono text-xs font-semibold">{r.spk_number}</td>
                <td className="p-3">{r.project_name}</td>
                <td className="p-3 text-muted-foreground">{r.customer || "-"}</td>
                <td className="p-3 text-muted-foreground">{r.division_name || "-"}</td>
                <td className="p-3 text-muted-foreground">{r.pic_name || "-"}</td>
                <td className="p-3 text-right">{rupiah(r.spk_value)}</td>
                <td className="p-3 text-right font-semibold">{rupiah(r.procurement_budget)}</td>
                <td className="p-3 text-xs text-muted-foreground">{r.start_date || "-"}{r.end_date ? ` s/d ${r.end_date}` : ""}</td>
                <td className="p-3 text-xs"><span className="rounded-md bg-muted px-2 py-1">{r.effective_policy?.global === "HARD_BLOCK" ? "Blokir" : "Peringatan"}/{r.effective_policy?.category === "HARD_BLOCK" ? "Blokir" : "Peringatan"}</span></td>
                <td className="p-3"><StatusBadge status={statusMap[r.status] || r.status} /></td>
                <td className="p-3" onClick={(e)=>e.stopPropagation()}><div className="flex justify-end gap-1">{can("spk:manage")&&<Button variant="ghost" size="sm" className="h-8" onClick={()=>nav(`/spk/${r.id}/edit`)} data-testid={`spk-edit-${r.spk_number}`}><Pencil className="mr-1 h-3.5 w-3.5" />Edit</Button>}{can("delete")&&<Button variant="ghost" size="sm" className="h-8 text-destructive hover:text-destructive" onClick={()=>setDelRows([{id:r.id,label:[ r.spk_number, r.project_name].filter(Boolean).join(" — ")}])} data-testid={`spk-delete-${r.spk_number}`}><Trash2 className="mr-1 h-3.5 w-3.5" />Hapus</Button>}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ListPager total={data.total} page={data.page || page} pageSize={pageSize} setPage={setPage} setPageSize={(n) => { setPage(1); setPageSize(n); }} testid="spk" unit="SPK" />
    </div>
  );
}

/* ============================== FORM (Add/Edit) ============================== */
export function SpkForm() {
  const nav = useNavigate();
  const { id } = useParams();
  const { can } = useAuth();
  const editing = !!id;
  const canPolicy = can("procurement_budget_policy:manage");
  const [form, setForm] = useState({
    spk_number: "", project_name: "", customer: "", spk_date: "", start_date: "", end_date: "",
    division_id: "", pic_id: "", project_id: "", spk_value: "", procurement_budget: "",
    status: "draft", notes: "", budget_policy_mode: "USE_TENANT_DEFAULT",
    custom_global_budget_policy: "WARNING_ONLY", custom_category_budget_policy: "WARNING_ONLY",
  });
  const [divisions, setDivisions] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [projects, setProjects] = useState([]);
  const [tenantPolicy, setTenantPolicy] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  useEffect(() => {
    api.get("/lookup/divisions").then((r) => setDivisions(r.data || [])).catch(() => {});
    api.get("/lookup/contacts").then((r) => setContacts(r.data || [])).catch(() => {});
    api.get("/lookup/projects").then((r) => setProjects(r.data || [])).catch(() => {});
    api.get("/procurement/budget-policy").then((r) => setTenantPolicy(r.data)).catch(() => {});
    if (editing) api.get(`/spk/${id}`).then((r) => {
      const d = r.data;
      setForm({
        spk_number: d.spk_number || "", project_name: d.project_name || "", customer: d.customer || "",
        spk_date: d.spk_date || "", start_date: d.start_date || "", end_date: d.end_date || "",
        division_id: d.division_id || "", pic_id: d.pic_id || "", project_id: d.project_id || "",
        spk_value: d.spk_value ?? "", procurement_budget: d.procurement_budget ?? "",
        status: d.status || "draft", notes: d.notes || "",
        budget_policy_mode: d.budget_policy_mode || "USE_TENANT_DEFAULT",
        custom_global_budget_policy: d.custom_global_budget_policy || "WARNING_ONLY",
        custom_category_budget_policy: d.custom_category_budget_policy || "WARNING_ONLY",
      });
    }).catch((e) => toast.error(apiError(e.response?.data?.detail)));
  }, [id, editing]);

  const submit = async () => {
    setSaving(true);
    try {
      const payload = {
        ...form,
        spk_value: form.spk_value === "" ? 0 : Number(form.spk_value),
        procurement_budget: form.procurement_budget === "" ? 0 : Number(form.procurement_budget),
        division_name: divisions.find((d) => d.id === form.division_id)?.name || null,
        pic_name: contacts.find((c) => c.id === form.pic_id)?.name || null,
      };
      const r = editing ? await api.put(`/spk/${id}`, payload) : await api.post("/spk", payload);
      toast.success(editing ? "SPK diperbarui" : `SPK dibuat — ${r.data.spk_number}`);
      nav(`/spk/${r.data.id || id}`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const Section = FormSection;

  return (
    <div>
      <PageHeader title={editing ? "Edit SPK" : "Tambah SPK"} subtitle="Fondasi Master SPK & kontrol budget Procurement">
        <Button variant="outline" onClick={() => nav(editing ? `/spk/${id}` : "/spk")}><ArrowLeft className="h-4 w-4 mr-2" />Kembali</Button>
      </PageHeader>

      <div className="grid gap-4 max-w-4xl">
        <Section title="Informasi SPK" icon={FileText}>
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Nomor SPK *"><Input value={form.spk_number} onChange={(e) => set("spk_number", e.target.value)} className="font-mono font-semibold" data-testid="spk-number" /></Field>
            <Field label="Status"><Combobox options={STATUS_OPTS} value={form.status} onChange={(v) => set("status", v)} /></Field>
            <div className="md:col-span-2"><Field label="Nama Pekerjaan / Project *"><Input value={form.project_name} onChange={(e) => set("project_name", e.target.value)} data-testid="spk-project" /></Field></div>
            <Field label="Customer / Project Owner"><Input value={form.customer} onChange={(e) => set("customer", e.target.value)} /></Field>
            <Field label="Tanggal SPK"><Input type="date" value={form.spk_date || ""} onChange={(e) => set("spk_date", e.target.value)} /></Field>
          </div>
        </Section>

        <Section title="Periode & Organisasi" icon={Layers3}>
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Tanggal Mulai"><Input type="date" value={form.start_date || ""} onChange={(e) => set("start_date", e.target.value)} /></Field>
            <Field label="Tanggal Berakhir"><Input type="date" value={form.end_date || ""} onChange={(e) => set("end_date", e.target.value)} /></Field>
            <Field label="Divisi"><Combobox options={divisions.map((d) => ({ value: d.id, label: d.name }))} value={form.division_id} onChange={(v) => set("division_id", v)} placeholder="Pilih divisi" /></Field>
            <Field label="PIC"><Combobox options={contacts.map((c) => ({ value: c.id, label: c.name }))} value={form.pic_id} onChange={(v) => set("pic_id", v)} placeholder="Pilih PIC" /></Field>
            <Field label="Project / Site"><MasterProjectCombobox options={projects.map((p) => ({ value: p.id, label: p.name }))} value={form.project_id} onChange={(v) => set("project_id", v)} onCreated={(doc) => setProjects((s) => [...s.filter((x) => x.id !== doc.id), doc])} placeholder="Pilih project" testid="spk-project-site" /></Field>
          </div>
        </Section>

        <Section title="Nilai & Budget" icon={Wallet} desc="Nilai SPK dan Budget Procurement dipisah. Budget Procurement menjadi dasar kontrol Procurement dan tidak boleh melebihi Nilai SPK.">
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Nilai SPK (Rp)"><MoneyInput value={form.spk_value} onChange={(v) => set("spk_value", v)} data-testid="spk-value" /></Field>
            <Field label="Budget Procurement (Rp)"><MoneyInput value={form.procurement_budget} onChange={(v) => set("procurement_budget", v)} data-testid="spk-budget" /></Field>
          </div>
          {Number(form.procurement_budget || 0) > Number(form.spk_value || 0) &&
            <p className="text-xs text-destructive">Budget Procurement melebihi Nilai SPK.</p>}
        </Section>

        <Section title="Budget Control Policy" icon={ShieldCheck} desc="Perilaku ketika budget terlampaui. Global dan Category dapat berbeda.">
          {!canPolicy && <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">Anda tidak memiliki izin mengubah Budget Control Policy (read-only). Field policy mengikuti nilai saat ini.</div>}
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Mode Policy">
              <Combobox options={[{ value: "USE_TENANT_DEFAULT", label: "Use Tenant Default" }, { value: "CUSTOM", label: "Custom" }]}
                value={form.budget_policy_mode} onChange={(v) => canPolicy && set("budget_policy_mode", v)} />
            </Field>
            {form.budget_policy_mode === "USE_TENANT_DEFAULT" && tenantPolicy && (
              <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs self-end">
                Default tenant: Global <b>{policyLabel(tenantPolicy.default_global_budget_policy)}</b> · Category <b>{policyLabel(tenantPolicy.default_category_budget_policy)}</b>
              </div>
            )}
          </div>
          {form.budget_policy_mode === "CUSTOM" && (
            <div className="grid md:grid-cols-2 gap-4">
              <Field label="Global Budget Control"><Combobox options={POLICY_OPTS} value={form.custom_global_budget_policy} onChange={(v) => canPolicy && set("custom_global_budget_policy", v)} /></Field>
              <Field label="Category Budget Control"><Combobox options={POLICY_OPTS} value={form.custom_category_budget_policy} onChange={(v) => canPolicy && set("custom_category_budget_policy", v)} /></Field>
            </div>
          )}
        </Section>

        <Section title="Catatan" icon={Info}>
          <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} className="w-full min-h-24 rounded-md border bg-background px-3 py-2 text-sm" placeholder="Catatan internal SPK" />
          {!editing && <p className="text-xs text-muted-foreground">Dokumen SPK dapat diunggah setelah SPK disimpan (buka Detail SPK).</p>}
        </Section>

        <div className="flex gap-2">
          <Button onClick={submit} disabled={saving} data-testid="spk-save">{saving ? "Menyimpan..." : "Simpan SPK"}</Button>
          <Button variant="outline" onClick={() => nav(editing ? `/spk/${id}` : "/spk")}>Batal</Button>
        </div>
      </div>
    </div>
  );
}

/* ============================== DETAIL ============================== */
function SpkDocuments({ spkId, canManage }) {
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const load = useCallback(() => api.get(`/spk/${spkId}/documents`).then((r) => setDocs(r.data || [])).catch(() => {}), [spkId]);
  useEffect(() => { load(); }, [load]);
  const upload = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    if (file.size > 10 * 1024 * 1024) { toast.error("Ukuran file maksimal 10 MB"); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      await api.post(`/spk/${spkId}/documents`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Dokumen terunggah"); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setUploading(false); e.target.value = ""; }
  };
  const del = async (docId) => {
    if (!window.confirm("Hapus dokumen ini?")) return;
    try { await api.delete(`/spk/${spkId}/documents/${docId}`); toast.success("Dokumen dihapus"); load(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  const download = (d) => window.open(`${API}/spk/${spkId}/documents/${d.id}/download`, "_blank");
  return (
    <div className="space-y-3">
      {canManage && (
        <label className="inline-flex items-center gap-2 rounded-lg border border-dashed px-4 py-2 text-sm cursor-pointer hover:bg-accent/40" data-testid="spk-doc-upload-label">
          <Upload className="h-4 w-4" />{uploading ? "Mengunggah..." : "Upload Dokumen (PDF/JPG/PNG/WEBP, maks 10MB)"}
          <input type="file" className="hidden" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={upload} disabled={uploading} data-testid="spk-doc-input" />
        </label>
      )}
      {docs.length === 0 ? <div className="text-sm text-muted-foreground py-6 text-center">Belum ada dokumen SPK.</div> : (
        <div className="space-y-2">
          {docs.map((d) => (
            <div key={d.id} className="flex items-center justify-between rounded-xl border p-3">
              <div className="flex items-center gap-3 min-w-0"><FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="min-w-0"><div className="text-sm font-medium truncate">{d.file_name}</div>
                  <div className="text-[11px] text-muted-foreground">{(d.file_size / 1024).toFixed(0)} KB · {d.mime_type} · {new Date(d.uploaded_at).toLocaleString("id-ID")} · {d.uploaded_by}</div></div></div>
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

const ADD_TYPE_OPTS = [
  { value: "PROCUREMENT_BUDGET", label: "Budget Procurement" },
  { value: "SPK_VALUE", label: "Nilai SPK" },
  { value: "BOTH", label: "Keduanya" },
];
const addStatusMap = { draft: "Draft", effective: "Normal", cancelled: "cancelled" };

function AddendumPanel({ spk, onChanged }) {
  const canManage = spk.can_manage_addendum;
  const canFinalize = spk.can_finalize_addendum;
  const list = spk.addendums || [];
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const blank = { addendum_number: "", addendum_date: "", addendum_type: "PROCUREMENT_BUDGET", effective_date: "", reason: "", pic_name: "", division_name: "", sv_dir: "+", sv_mag: "", bud_dir: "+", bud_mag: "" };
  const [f, setF] = useState(blank);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const curSv = spk.budget_summary?.spk_value || 0;
  const curBud = spk.budget_summary?.procurement_budget || 0;
  const svDelta = (f.addendum_type === "PROCUREMENT_BUDGET") ? 0 : (f.sv_dir === "-" ? -1 : 1) * Number(f.sv_mag || 0);
  const budDelta = (f.addendum_type === "SPK_VALUE") ? 0 : (f.bud_dir === "-" ? -1 : 1) * Number(f.bud_mag || 0);
  const newSv = curSv + svDelta;
  const newBud = curBud + budDelta;

  const submit = async () => {
    setSaving(true);
    try {
      await api.post(`/spk/${spk.id}/addendums`, {
        addendum_number: f.addendum_number, addendum_date: f.addendum_date, addendum_type: f.addendum_type,
        effective_date: f.effective_date || null, reason: f.reason, pic_name: f.pic_name || null, division_name: f.division_name || null,
        spk_value_change: svDelta, budget_change: budDelta,
      });
      toast.success("Addendum draft dibuat"); setOpen(false); setF(blank); onChanged?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  const finalize = async (a) => {
    try {
      const r = await api.post(`/spk/${spk.id}/addendums/${a.id}/finalize`, { expected_spk_value: curSv, expected_procurement_budget: curBud });
      if (r.data?.warning) toast.warning(r.data.warning); else toast.success("Addendum effective — nilai SPK diperbarui");
      onChanged?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  const cancel = async (a) => { if (!window.confirm("Batalkan addendum ini?")) return; try { await api.post(`/spk/${spk.id}/addendums/${a.id}/cancel`); toast.success("Addendum dibatalkan"); onChanged?.(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };

  return (
    <div className="space-y-4">
      {canManage && <Button onClick={() => setOpen(true)} data-testid="addendum-add-btn"><Plus className="h-4 w-4 mr-2" />Tambah Addendum</Button>}
      {list.length === 0 ? <div className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">Belum ada Addendum pada SPK ini.</div> : (
        <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
          <table className="w-full text-sm"><thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground">
            <th className="p-3">No</th><th className="p-3">Tanggal</th><th className="p-3">Tipe</th>
            <th className="p-3 text-right">Perubahan Nilai SPK</th><th className="p-3 text-right">Perubahan Budget</th>
            <th className="p-3 text-right">Budget Sebelum/Sesudah</th><th className="p-3">Status</th><th className="p-3">Aksi</th></tr></thead>
            <tbody>
            {list.map((a) => (
              <tr key={a.id} className="border-t" data-testid={`addendum-row-${a.addendum_number}`}>
                <td className="p-3 font-mono text-xs">{a.addendum_number}</td>
                <td className="p-3 text-xs">{a.addendum_date || "-"}</td>
                <td className="p-3 text-xs">{a.addendum_type}</td>
                <td className="p-3 text-right text-xs">{a.spk_value_change ? rupiah(a.spk_value_change) : "-"}</td>
                <td className="p-3 text-right text-xs">{a.budget_change ? rupiah(a.budget_change) : "-"}</td>
                <td className="p-3 text-right text-xs">{a.status === "effective" ? `${rupiah(a.before_procurement_budget)} -> ${rupiah(a.after_procurement_budget)}` : "-"}</td>
                <td className="p-3"><StatusBadge status={addStatusMap[a.status] || a.status} /></td>
                <td className="p-3">
                  {a.status === "draft" && canFinalize && <Button size="sm" variant="outline" className="h-7 text-xs mr-1" onClick={() => finalize(a)} data-testid={`addendum-finalize-${a.addendum_number}`}>Finalisasi</Button>}
                  {a.status === "draft" && canManage && <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => cancel(a)}>Batal</Button>}
                </td>
              </tr>
            ))}
            </tbody></table>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-auto">
          <DialogHeader><DialogTitle>Tambah Addendum</DialogTitle>
            <DialogDescription>SPK {spk.spk_number} - {spk.project_name} - Status {spk.status}</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="grid md:grid-cols-2 gap-3">
              <Field label="Nomor Addendum *"><Input value={f.addendum_number} onChange={(e) => set("addendum_number", e.target.value)} data-testid="addendum-number" /></Field>
              <Field label="Tanggal Addendum *"><Input type="date" value={f.addendum_date} onChange={(e) => set("addendum_date", e.target.value)} data-testid="addendum-date" /></Field>
              <Field label="Tipe Addendum *"><Combobox options={ADD_TYPE_OPTS} value={f.addendum_type} onChange={(v) => set("addendum_type", v)} /></Field>
              <Field label="Tanggal Efektif"><Input type="date" value={f.effective_date} onChange={(e) => set("effective_date", e.target.value)} /></Field>
              <Field label="PIC Pengaju"><Input value={f.pic_name} onChange={(e) => set("pic_name", e.target.value)} /></Field>
              <Field label="Divisi"><Input value={f.division_name} onChange={(e) => set("division_name", e.target.value)} /></Field>
            </div>
            {f.addendum_type !== "PROCUREMENT_BUDGET" && (
              <div className="rounded-xl border p-3 space-y-2">
                <div className="text-xs font-semibold">Perubahan Nilai SPK</div>
                <div className="grid grid-cols-3 gap-2 items-end">
                  <Field label="Arah"><Combobox options={[{ value: "+", label: "Tambah (+)" }, { value: "-", label: "Kurang (-)" }]} value={f.sv_dir} onChange={(v) => set("sv_dir", v)} /></Field>
                  <Field label="Nilai"><MoneyInput value={f.sv_mag} onChange={(v) => set("sv_mag", v)} data-testid="addendum-sv-mag" /></Field>
                  <div className="text-xs">Current {rupiah(curSv)}<br />Baru <b data-testid="addendum-new-sv">{rupiah(newSv)}</b></div>
                </div>
              </div>
            )}
            {f.addendum_type !== "SPK_VALUE" && (
              <div className="rounded-xl border p-3 space-y-2">
                <div className="text-xs font-semibold">Perubahan Budget Procurement</div>
                <div className="grid grid-cols-3 gap-2 items-end">
                  <Field label="Arah"><Combobox options={[{ value: "+", label: "Tambah (+)" }, { value: "-", label: "Kurang (-)" }]} value={f.bud_dir} onChange={(v) => set("bud_dir", v)} /></Field>
                  <Field label="Nilai"><MoneyInput value={f.bud_mag} onChange={(v) => set("bud_mag", v)} data-testid="addendum-bud-mag" /></Field>
                  <div className="text-xs">Current {rupiah(curBud)}<br />Baru <b data-testid="addendum-new-bud">{rupiah(newBud)}</b></div>
                </div>
              </div>
            )}
            {(newBud > newSv) && <p className="text-xs text-destructive">Budget hasil melebihi Nilai SPK hasil - tidak dapat difinalisasi.</p>}
            <Field label="Alasan / Deskripsi *"><textarea value={f.reason} onChange={(e) => set("reason", e.target.value)} className="w-full min-h-20 rounded-md border bg-background px-3 py-2 text-sm" data-testid="addendum-reason" /></Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Batal</Button>
            <Button onClick={submit} disabled={saving} data-testid="addendum-save">{saving ? "Menyimpan..." : "Simpan Draft"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function SpkDetail() {
  const nav = useNavigate();
  const { id } = useParams();
  const [spk, setSpk] = useState(null);
  const [tab, setTab] = useState("summary");
  const load = useCallback(() => api.get(`/spk/${id}`).then((r) => setSpk(r.data)).catch((e) => toast.error(apiError(e.response?.data?.detail))), [id]);
  useEffect(() => { load(); }, [load]);

  if (!spk) return <div className="p-10 text-center text-muted-foreground">Memuat SPK...</div>;
  const bs = spk.budget_summary || {};
  const ep = spk.effective_policy || {};
  const canManage = spk.can_manage;

  const changeStatus = async (v) => {
    try { await api.patch(`/spk/${id}/status`, { status: v }); toast.success("Status diperbarui"); load(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  const cards = [
    ["Nilai SPK", bs.spk_value, "text-slate-700", bs.original_spk_value !== bs.spk_value ? bs.original_spk_value : null],
    ["Budget Procurement", bs.procurement_budget, "text-sky-700", bs.original_procurement_budget !== bs.procurement_budget ? bs.original_procurement_budget : null],
    ["Commitment", bs.commitment, "text-amber-700", null],
    ["Realisasi", bs.realisasi, "text-violet-700", null],
    ["Sisa Budget", bs.available_budget, "text-emerald-700", null],
  ];

  return (
    <div>
      <PageHeader title={`SPK ${spk.spk_number}`} subtitle={spk.project_name}>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => nav("/spk")}><ArrowLeft className="h-4 w-4 mr-2" />Daftar</Button>
          {canManage && <Button onClick={() => nav(`/spk/${id}/edit`)} data-testid="spk-edit-btn"><Pencil className="h-4 w-4 mr-2" />Edit</Button>}
        </div>
      </PageHeader>

      {/* header info */}
      <div className="rounded-xl border bg-card p-5 shadow-sm mb-4">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <div><div className="text-xs text-muted-foreground">No SPK</div><div className="font-mono font-semibold">{spk.spk_number}</div></div>
          <div><div className="text-xs text-muted-foreground">Customer</div><div className="font-medium">{spk.customer || "-"}</div></div>
          <div><div className="text-xs text-muted-foreground">Divisi</div><div className="font-medium">{spk.division_name || "-"}</div></div>
          <div><div className="text-xs text-muted-foreground">PIC</div><div className="font-medium">{spk.pic_name || "-"}</div></div>
          <div><div className="text-xs text-muted-foreground">Periode</div><div className="font-medium">{spk.start_date || "-"}{spk.end_date ? ` s/d ${spk.end_date}` : ""}</div></div>
          <div><div className="text-xs text-muted-foreground">Status</div><div className="mt-1"><StatusBadge status={statusMap[spk.status] || spk.status} /></div></div>
          {canManage && (
            <div><div className="text-xs text-muted-foreground mb-1">Ubah Status</div>
              <Combobox options={STATUS_OPTS} value={spk.status} onChange={changeStatus} /></div>
          )}
        </div>
      </div>

      {/* summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-4">
        {cards.map(([label, val, color, orig]) => (
          <div key={label} className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className={`text-lg font-bold font-head mt-1.5 ${color}`}>{rupiah(val)}</div>
            {orig != null && <div className="text-[11px] text-muted-foreground mt-0.5">Original {rupiah(orig)}</div>}
          </div>
        ))}
      </div>
      {bs.over_budget && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700 mb-4" data-testid="over-budget-indicator">Status: OVER_BUDGET — budget saat ini lebih kecil dari commitment berjalan.</div>}

      {/* budget policy */}
      <div className="rounded-xl border bg-card p-5 shadow-sm mb-4">
        <div className="flex items-center gap-2 mb-3"><ShieldCheck className="h-4 w-4 text-primary" /><h3 className="font-head font-semibold">Budget Control Policy</h3></div>
        <div className="grid sm:grid-cols-3 gap-4 text-sm">
          <div><div className="text-xs text-muted-foreground">Policy Mode</div><div className="font-medium mt-1">{ep.source === "CUSTOM" ? "Custom" : "Tenant Default"}</div></div>
          <div><div className="text-xs text-muted-foreground">Effective Global Policy</div><div className="font-medium mt-1">{policyLabel(ep.global)}</div></div>
          <div><div className="text-xs text-muted-foreground">Effective Category Policy</div><div className="font-medium mt-1">{policyLabel(ep.category)}</div></div>
        </div>
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1"><span>Commitment / Budget Procurement</span><span>{bs.commitment_pct || 0}%</span></div>
          <div className="h-2 rounded-full bg-muted overflow-hidden"><div className="h-full bg-sky-500" style={{ width: `${Math.min(100, bs.commitment_pct || 0)}%` }} /></div>
        </div>
      </div>

      {/* tabs */}
      <div className="border-b flex gap-1 mb-4">
        {[["summary", "Ringkasan"], ["commitment", "Commitment & Realisasi"], ["addendum", "Addendum"], ["documents", "Dokumen"], ["notes", "Catatan"]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`h-10 px-4 text-sm font-medium border-b-2 -mb-px ${tab === k ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`} data-testid={`spk-tab-${k}`}>{l}</button>
        ))}
      </div>

      {tab === "summary" && (
        <div className="grid sm:grid-cols-2 gap-4 text-sm">
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Tanggal SPK</div><div className="font-medium mt-1">{spk.spk_date || "-"}</div></div>
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Dibuat oleh</div><div className="font-medium mt-1">{spk.created_by} · {new Date(spk.created_at).toLocaleString("id-ID")}</div></div>
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Terakhir diubah</div><div className="font-medium mt-1">{spk.updated_by} · {new Date(spk.updated_at).toLocaleString("id-ID")}</div></div>
          <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">Jumlah Dokumen</div><div className="font-medium mt-1">{spk.document_count || 0}</div></div>
        </div>
      )}
      {tab === "commitment" && (
        <div className="rounded-xl border bg-card p-10 text-center" data-testid="spk-commitment-empty">
          <ClipboardList className="h-10 w-10 mx-auto text-muted-foreground/50" />
          <p className="mt-3 text-sm text-muted-foreground">Belum ada transaksi Procurement yang menggunakan SPK ini.</p>
        </div>
      )}
      {tab === "addendum" && <AddendumPanel spk={spk} onChanged={load} />}
      {tab === "documents" && <SpkDocuments spkId={id} canManage={canManage} />}      {tab === "notes" && (
        <div className="rounded-xl border bg-card p-5">
          {spk.notes ? <p className="text-sm whitespace-pre-wrap">{spk.notes}</p> : <p className="text-sm text-muted-foreground">Belum ada catatan.</p>}
          {canManage && <Button variant="outline" size="sm" className="mt-4" onClick={() => nav(`/spk/${id}/edit`)}><Pencil className="h-4 w-4 mr-2" />Edit Catatan</Button>}
        </div>
      )}
    </div>
  );
}
