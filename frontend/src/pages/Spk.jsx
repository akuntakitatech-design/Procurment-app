import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { API, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { Field } from "@/components/DatePicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import {
  Plus, Search, Pencil, ArrowLeft, FileText, Upload, Trash2, Download, ShieldCheck,
  Wallet, TrendingUp, Layers3, Info, ChevronLeft, ChevronRight, ClipboardList,
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
  { value: "WARNING_ONLY", label: "Warning Only" },
  { value: "HARD_BLOCK", label: "Hard Block" },
];
const statusMap = { draft: "Draft", active: "Normal", closed: "Selesai", cancelled: "cancelled" };
const policyLabel = (p) => (p === "HARD_BLOCK" ? "Hard Block" : p === "WARNING_ONLY" ? "Warning Only" : "-");

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
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 20 });
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [divisionId, setDivisionId] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [divisions, setDivisions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.get("/master/divisions?active_only=true").then((r) => setDivisions(r.data || [])).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ q, status, division_id: divisionId, sort, page: String(page), page_size: "20" });
      const r = await api.get(`/spk?${params.toString()}`);
      setData(r.data || { items: [], total: 0 });
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [q, status, divisionId, sort, page]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

  const totalPages = Math.max(1, Math.ceil(data.total / (data.page_size || 20)));
  const toggleSort = (key) => setSort((s) => (s === key ? `-${key}` : s === `-${key}` ? key : `-${key}`));

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

      <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-sm zebra">
          <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="p-3 cursor-pointer" onClick={() => toggleSort("spk_number")}>No SPK</th>
            <th className="p-3">Nama Pekerjaan</th>
            <th className="p-3">Customer</th>
            <th className="p-3">Divisi</th>
            <th className="p-3">PIC</th>
            <th className="p-3 text-right cursor-pointer" onClick={() => toggleSort("spk_value")}>Nilai SPK</th>
            <th className="p-3 text-right">Budget Proc.</th>
            <th className="p-3">Periode</th>
            <th className="p-3">Policy</th>
            <th className="p-3">Status</th>
            <th className="p-3 w-14"></th>
          </tr></thead>
          <tbody>
            {loading && <tr><td colSpan={11} className="p-8 text-center text-muted-foreground">Memuat...</td></tr>}
            {!loading && data.items.length === 0 && <tr><td colSpan={11} className="p-8 text-center text-muted-foreground">Belum ada SPK</td></tr>}
            {!loading && data.items.map((r) => (
              <tr key={r.id} className="border-t hover:bg-accent/40 cursor-pointer transition-colors" onClick={() => nav(`/spk/${r.id}`)} data-testid={`spk-row-${r.spk_number}`}>
                <td className="p-3 font-mono text-xs font-semibold">{r.spk_number}</td>
                <td className="p-3">{r.project_name}</td>
                <td className="p-3 text-muted-foreground">{r.customer || "-"}</td>
                <td className="p-3 text-muted-foreground">{r.division_name || "-"}</td>
                <td className="p-3 text-muted-foreground">{r.pic_name || "-"}</td>
                <td className="p-3 text-right">{rupiah(r.spk_value)}</td>
                <td className="p-3 text-right font-semibold">{rupiah(r.procurement_budget)}</td>
                <td className="p-3 text-xs text-muted-foreground">{r.start_date || "-"}{r.end_date ? ` s/d ${r.end_date}` : ""}</td>
                <td className="p-3 text-xs"><span className="rounded-md bg-muted px-2 py-1">{r.effective_policy?.global === "HARD_BLOCK" ? "Hard" : "Warn"}/{r.effective_policy?.category === "HARD_BLOCK" ? "Hard" : "Warn"}</span></td>
                <td className="p-3"><StatusBadge status={statusMap[r.status] || r.status} /></td>
                <td className="p-3"><Button variant="ghost" size="icon" className="h-8 w-8"><ChevronRight className="h-4 w-4" /></Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-4 text-sm text-muted-foreground">
        <div>Total {data.total} SPK</div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
          <span>Hal {data.page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>
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
    api.get("/master/divisions?active_only=true").then((r) => setDivisions(r.data || [])).catch(() => {});
    api.get("/master/contacts?active_only=true").then((r) => setContacts(r.data || [])).catch(() => {});
    api.get("/master/projects?active_only=true").then((r) => setProjects(r.data || [])).catch(() => {});
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
            <Field label="Project / Site"><Combobox options={projects.map((p) => ({ value: p.id, label: p.name }))} value={form.project_id} onChange={(v) => set("project_id", v)} placeholder="Pilih project" /></Field>
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
    ["Nilai SPK", bs.spk_value, "text-slate-700"],
    ["Budget Procurement", bs.procurement_budget, "text-sky-700"],
    ["Commitment", bs.commitment, "text-amber-700"],
    ["Realisasi", bs.realisasi, "text-violet-700"],
    ["Sisa Budget", bs.available_budget, "text-emerald-700"],
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
        {cards.map(([label, val, color]) => (
          <div key={label} className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className={`text-lg font-bold font-head mt-1.5 ${color}`}>{rupiah(val)}</div>
          </div>
        ))}
      </div>

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
        {[["summary", "Ringkasan"], ["commitment", "Commitment & Realisasi"], ["documents", "Dokumen"], ["notes", "Catatan"]].map(([k, l]) => (
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
      {tab === "documents" && <SpkDocuments spkId={id} canManage={canManage} />}
      {tab === "notes" && (
        <div className="rounded-xl border bg-card p-5">
          {spk.notes ? <p className="text-sm whitespace-pre-wrap">{spk.notes}</p> : <p className="text-sm text-muted-foreground">Belum ada catatan.</p>}
          {canManage && <Button variant="outline" size="sm" className="mt-4" onClick={() => nav(`/spk/${id}/edit`)}><Pencil className="h-4 w-4 mr-2" />Edit Catatan</Button>}
        </div>
      )}
    </div>
  );
}
