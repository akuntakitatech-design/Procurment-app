import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import api, { API, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import PlatformInvitations from "@/components/PlatformInvitations";
import PlatformBranding from "@/components/PlatformBranding";
import {
  Activity, Building2, CalendarClock, Clock3, Copy, Hash, HardDrive, Link2, Loader2, LogOut, Mail,
  Pencil, Phone, Plus, RefreshCw, RotateCcw, Search, Send, ShieldCheck, ShieldOff, TriangleAlert,
  UserRound, Users,
} from "lucide-react";

const badgeClass = (status) => {
  const s = String(status || "").toLowerCase();
  if (s === "active") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (s === "pending_activation") return "bg-indigo-50 text-indigo-700 border-indigo-200";
  if (s === "expiring_soon" || s === "grace" || s === "trial") return "bg-amber-50 text-amber-700 border-amber-200";
  if (s === "suspended") return "bg-orange-50 text-orange-700 border-orange-200";
  if (s === "expired") return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-slate-50 text-slate-600 border-slate-200";
};
const statusLabel = (s) => ({
  active: "Aktif", pending_activation: "Pending Activation", suspended: "Suspended",
  expired: "Expired", expiring_soon: "Akan Expired", grace: "Masa Tenggang", trial: "Trial",
}[String(s || "").toLowerCase()] || (s || "-"));

const showLimit = (v) => (v == null ? "∞" : v);
const fmtDate = (value) => {
  if (!value) return "-";
  try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium" }).format(new Date(value)); }
  catch { return value; }
};
const fmtDateTime = (value) => {
  if (!value) return "-";
  try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
};
const toDateInput = (value) => {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return String(value);
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const copy = (text) => { try { navigator.clipboard.writeText(text); toast.success("Disalin ke clipboard"); } catch { /* noop */ } };

function UsageBar({ icon: Icon, label, valueText, percent, danger }) {
  const pct = percent == null ? null : Math.min(100, Math.max(0, percent));
  return (
    <div className="rounded-xl border p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 text-muted-foreground"><Icon className="h-3.5 w-3.5" />{label}</span>
        <span className={`font-semibold ${danger ? "text-rose-600" : ""}`}>{valueText}</span>
      </div>
      {pct != null && <Progress value={pct} className={`h-2 mt-2 ${pct >= 80 ? "[&>div]:bg-rose-500" : pct >= 60 ? "[&>div]:bg-amber-500" : ""}`} />}
    </div>
  );
}

/* ------------------------------ Create Tenant ------------------------------ */
function CreateTenantDialog({ open, onOpenChange, plans, onCreated }) {
  const empty = {
    company_name: "", workspace_slug: "", phone: "", address: "", logo: "",
    pic_name: "", pic_position: "", whatsapp: "", email: "",
    plan_code: "", ends_at: "", max_users: "", storage_limit_gb: "20", notes: "",
  };
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);
  const set = (k, v) => setForm((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (open) { setForm(empty); setResult(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onLogo = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 400 * 1024) { toast.error("Logo maksimal 400KB"); return; }
    const reader = new FileReader();
    reader.onload = () => set("logo", reader.result);
    reader.readAsDataURL(file);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        company_name: form.company_name.trim(),
        workspace_slug: form.workspace_slug.trim() || null,
        phone: form.phone.trim() || null,
        address: form.address.trim() || null,
        logo: form.logo || null,
        pic_name: form.pic_name.trim(),
        pic_position: form.pic_position.trim() || null,
        whatsapp: form.whatsapp.trim(),
        email: form.email.trim().toLowerCase(),
        plan_code: form.plan_code || null,
        ends_at: form.ends_at || null,
        max_users: form.max_users !== "" ? Number(form.max_users) : null,
        storage_limit_gb: form.storage_limit_gb !== "" ? Number(form.storage_limit_gb) : null,
        notes: form.notes.trim() || null,
      };
      const r = await api.post("/platform/tenants", payload);
      setResult(r.data);
      toast.success(`Tenant ${r.data.tenant_code} dibuat`);
      onCreated?.();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-auto">
        <DialogHeader>
          <DialogTitle>Tambah Tenant</DialogTitle>
          <DialogDescription>Kode tenant dibuat otomatis & permanen. Tenant Admin pertama dibuat dengan status Pending Activation.</DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-4" data-testid="create-tenant-result">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm">
              <div className="font-semibold text-emerald-800">Tenant {result.tenant_code} berhasil dibuat</div>
              <div className="text-emerald-700 mt-1">{result.message}</div>
            </div>
            <div className="space-y-2">
              <Label>Link Aktivasi Tenant Admin</Label>
              <div className="flex gap-2">
                <Input readOnly value={result.activation_url} className="font-mono text-xs" data-testid="activation-url" />
                <Button type="button" variant="outline" onClick={() => copy(result.activation_url)}><Copy className="h-4 w-4" /></Button>
              </div>
              <p className="text-[11px] text-muted-foreground">Email service belum tersedia di preview — bagikan link ini ke {result.primary_email}. Berlaku sampai {fmtDateTime(result.activation_expires_at)}.</p>
            </div>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)} data-testid="create-tenant-close">Selesai</Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-5">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Informasi Perusahaan</div>
              <div className="grid sm:grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label>Nama Perusahaan *</Label><Input value={form.company_name} onChange={(e) => set("company_name", e.target.value)} required data-testid="ct-company-name" /></div>
                <div className="space-y-1.5"><Label>Workspace / Slug *</Label><Input value={form.workspace_slug} onChange={(e) => set("workspace_slug", e.target.value)} placeholder="mis. pt-maju" data-testid="ct-slug" /></div>
                <div className="space-y-1.5"><Label>No. Telepon</Label><Input value={form.phone} onChange={(e) => set("phone", e.target.value)} /></div>
                <div className="space-y-1.5"><Label>Logo Tenant (opsional)</Label><Input type="file" accept="image/*" onChange={onLogo} /></div>
                <div className="space-y-1.5 sm:col-span-2"><Label>Alamat</Label><Input value={form.address} onChange={(e) => set("address", e.target.value)} /></div>
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">PIC & Email Utama</div>
              <div className="grid sm:grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label>Nama PIC *</Label><Input value={form.pic_name} onChange={(e) => set("pic_name", e.target.value)} required data-testid="ct-pic-name" /></div>
                <div className="space-y-1.5"><Label>Jabatan PIC</Label><Input value={form.pic_position} onChange={(e) => set("pic_position", e.target.value)} /></div>
                <div className="space-y-1.5"><Label>No. HP / WhatsApp *</Label><Input value={form.whatsapp} onChange={(e) => set("whatsapp", e.target.value)} required data-testid="ct-whatsapp" /></div>
                <div className="space-y-1.5"><Label>Email Utama Tenant *</Label><Input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} required data-testid="ct-email" /></div>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1.5">Email utama menjadi akun Tenant Admin pertama, penerima aktivasi, reset password, dan notifikasi subscription. Harus unik.</p>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Subscription</div>
              <div className="grid sm:grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label>Paket</Label>
                  <select value={form.plan_code} onChange={(e) => set("plan_code", e.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm">
                    <option value="">(Tanpa paket)</option>
                    {plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
                  </select>
                </div>
                <div className="space-y-1.5"><Label>Langganan Berakhir</Label><Input type="date" value={form.ends_at} onChange={(e) => set("ends_at", e.target.value)} data-testid="ct-ends" /></div>
                <div className="space-y-1.5"><Label>User Limit</Label><Input type="number" min="1" value={form.max_users} onChange={(e) => set("max_users", e.target.value)} placeholder="Ikuti paket" data-testid="ct-max-users" /></div>
                <div className="space-y-1.5"><Label>Storage Limit (GB)</Label><Input type="number" min="0" step="0.5" value={form.storage_limit_gb} onChange={(e) => set("storage_limit_gb", e.target.value)} data-testid="ct-storage" /></div>
                <div className="space-y-1.5 sm:col-span-2"><Label>Catatan</Label><Input value={form.notes} onChange={(e) => set("notes", e.target.value)} /></div>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
              <Button type="submit" disabled={saving} data-testid="ct-submit">{saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Buat Tenant</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------ Renew ------------------------------ */
function RenewDialog({ open, onOpenChange, tenant, plans, onDone }) {
  const [form, setForm] = useState({ start_date: "", ends_at: "", plan_code: "", max_users: "", storage_limit_gb: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm((x) => ({ ...x, [k]: v }));
  useEffect(() => {
    if (open && tenant) setForm({
      start_date: "", ends_at: "", plan_code: tenant.plan?.code || "",
      max_users: tenant.effective_limits?.max_users ?? "", storage_limit_gb: tenant.effective_limits?.storage_limit_gb ?? "", notes: "",
    });
  }, [open, tenant]);
  const submit = async (e) => {
    e.preventDefault();
    if (!form.ends_at) { toast.error("Tanggal akhir wajib diisi"); return; }
    setSaving(true);
    try {
      await api.post(`/platform/tenants/${tenant.id}/renew`, {
        start_date: form.start_date || null, ends_at: form.ends_at, plan_code: form.plan_code || null,
        max_users: form.max_users !== "" ? Number(form.max_users) : null,
        storage_limit_gb: form.storage_limit_gb !== "" ? Number(form.storage_limit_gb) : null,
        notes: form.notes.trim() || null,
      });
      toast.success("Langganan diperpanjang");
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || e.message); }
    finally { setSaving(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Perpanjang Langganan</DialogTitle>
          <DialogDescription>Periode lama diarsipkan ke histori. Kode tenant tidak berubah.</DialogDescription></DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="space-y-1.5"><Label>Tanggal Mulai</Label><Input type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>Tanggal Akhir *</Label><Input type="date" value={form.ends_at} onChange={(e) => set("ends_at", e.target.value)} required data-testid="renew-ends" /></div>
            <div className="space-y-1.5"><Label>Paket</Label>
              <select value={form.plan_code} onChange={(e) => set("plan_code", e.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm">
                <option value="">(Tetap)</option>
                {plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
              </select></div>
            <div className="space-y-1.5"><Label>User Limit</Label><Input type="number" min="1" value={form.max_users} onChange={(e) => set("max_users", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>Storage Limit (GB)</Label><Input type="number" min="0" step="0.5" value={form.storage_limit_gb} onChange={(e) => set("storage_limit_gb", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>Catatan</Label><Input value={form.notes} onChange={(e) => set("notes", e.target.value)} /></div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
            <Button type="submit" disabled={saving} data-testid="renew-submit">{saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Perpanjang</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------ Suspend ------------------------------ */
function SuspendDialog({ open, onOpenChange, tenant, onDone }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (open) setReason(""); }, [open]);
  const submit = async (e) => {
    e.preventDefault();
    if (reason.trim().length < 3) { toast.error("Alasan wajib diisi (min 3 karakter)"); return; }
    setSaving(true);
    try {
      await api.post(`/platform/tenants/${tenant.id}/suspend`, { reason: reason.trim() });
      toast.success("Tenant ditangguhkan");
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || e.message); }
    finally { setSaving(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>Suspend Tenant</DialogTitle>
          <DialogDescription>Tenant suspended tidak dapat melakukan aktivitas operasional. Data tidak dihapus.</DialogDescription></DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5"><Label>Alasan *</Label>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} className="w-full min-h-24 rounded-md border bg-background px-3 py-2 text-sm" placeholder="Alasan penangguhan" data-testid="suspend-reason" /></div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
            <Button type="submit" variant="destructive" disabled={saving} data-testid="suspend-submit">{saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Suspend</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------ Edit Profile ------------------------------ */
function EditProfileDialog({ open, onOpenChange, tenant, onDone }) {
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm((x) => ({ ...x, [k]: v }));
  useEffect(() => {
    if (open && tenant) setForm({
      company_name: tenant.name || "", phone: tenant.contact?.phone || "", address: tenant.address || "",
      pic_name: tenant.contact?.pic_name || "", pic_position: tenant.contact?.pic_position || "",
      whatsapp: tenant.contact?.whatsapp || "", email: tenant.contact?.email || "",
      max_users: tenant.limits?.max_users ?? "", storage_limit_gb: tenant.limits?.storage_limit_gb ?? "",
      notes: tenant.admin_notes || "",
    });
  }, [open, tenant]);
  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        company_name: form.company_name?.trim(), phone: form.phone?.trim() || null, address: form.address?.trim() || null,
        pic_name: form.pic_name?.trim(), pic_position: form.pic_position?.trim() || null, whatsapp: form.whatsapp?.trim(),
        email: form.email?.trim().toLowerCase(),
        max_users: form.max_users !== "" ? Number(form.max_users) : null,
        storage_limit_gb: form.storage_limit_gb !== "" ? Number(form.storage_limit_gb) : null,
        notes: form.notes?.trim() || null,
      };
      const r = await api.patch(`/platform/tenants/${tenant.id}/profile`, payload);
      if (r.data?.warning) toast.warning(r.data.warning); else toast.success("Perubahan disimpan");
      onOpenChange(false); onDone?.();
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || e.message); }
    finally { setSaving(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl max-h-[90vh] overflow-auto">
        <DialogHeader><DialogTitle>Edit Tenant</DialogTitle>
          <DialogDescription>Kode tenant permanen dan tidak berubah. Mengubah email utama akan menyinkronkan akun Tenant Admin.</DialogDescription></DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="space-y-1.5"><Label>Nama Perusahaan</Label><Input value={form.company_name || ""} onChange={(e) => set("company_name", e.target.value)} data-testid="edit-company-name" /></div>
            <div className="space-y-1.5"><Label>No. Telepon</Label><Input value={form.phone || ""} onChange={(e) => set("phone", e.target.value)} /></div>
            <div className="space-y-1.5 sm:col-span-2"><Label>Alamat</Label><Input value={form.address || ""} onChange={(e) => set("address", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>Nama PIC</Label><Input value={form.pic_name || ""} onChange={(e) => set("pic_name", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>Jabatan PIC</Label><Input value={form.pic_position || ""} onChange={(e) => set("pic_position", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>WhatsApp</Label><Input value={form.whatsapp || ""} onChange={(e) => set("whatsapp", e.target.value)} /></div>
            <div className="space-y-1.5"><Label>Email Utama</Label><Input type="email" value={form.email || ""} onChange={(e) => set("email", e.target.value)} data-testid="edit-email" /></div>
            <div className="space-y-1.5"><Label>User Limit</Label><Input type="number" min="1" value={form.max_users} onChange={(e) => set("max_users", e.target.value)} data-testid="edit-max-users" /></div>
            <div className="space-y-1.5"><Label>Storage Limit (GB)</Label><Input type="number" min="0" step="0.5" value={form.storage_limit_gb} onChange={(e) => set("storage_limit_gb", e.target.value)} /></div>
            <div className="space-y-1.5 sm:col-span-2"><Label>Catatan Internal</Label><Input value={form.notes || ""} onChange={(e) => set("notes", e.target.value)} /></div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
            <Button type="submit" disabled={saving} data-testid="edit-submit">{saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Simpan</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ============================== MAIN ============================== */
export default function PlatformAdmin() {
  const { user, logout } = useAuth();
  const [dashboard, setDashboard] = useState({ attention: [] });
  const [tenants, setTenants] = useState([]);
  const [plans, setPlans] = useState([]);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [detailTab, setDetailTab] = useState("overview");
  const [platformBrand, setPlatformBrand] = useState({ name: "KelolaKita Procurement", logo_available: false, logo_version: null });
  const [dlg, setDlg] = useState({ create: false, renew: false, suspend: false, edit: false });

  useEffect(() => { api.get("/platform-branding").then((r) => setPlatformBrand(r.data || {})).catch(() => {}); }, []);
  const platformLogoUrl = platformBrand.logo_available ? `${API}/platform-branding/logo?v=${encodeURIComponent(platformBrand.logo_version || "1")}` : null;

  const load = async () => {
    const selectedId = selected?.id;
    setLoading(true); setErr("");
    try {
      const [d, t, p] = await Promise.all([
        api.get("/platform/dashboard"),
        api.get("/platform/tenants"),
        api.get("/saas/public-config"),
      ]);
      setDashboard(d.data || { attention: [] });
      setTenants(t.data || []);
      setPlans(p.data?.plans || []);
      if (selectedId) { const r = await api.get(`/platform/tenants/${selectedId}/cp0`); setSelected(r.data); }
    } catch (e) { setErr(apiError(e.response?.data?.detail) || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openTenant = async (t) => {
    setErr(""); setDetailTab("overview");
    try { const r = await api.get(`/platform/tenants/${t.id}/cp0`); setSelected(r.data); }
    catch (e) { setErr(apiError(e.response?.data?.detail) || e.message); }
  };
  const refreshSelected = async () => { if (selected) await openTenant(selected); await load(); };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return tenants.filter((t) => {
      if (statusFilter !== "all") {
        const st = String(t.status || "").toLowerCase();
        if (statusFilter === "expiring" || statusFilter === "expired") {
          const end = t.subscription?.ends_at ? new Date(t.subscription.ends_at) : null;
          if (!end) return false;
          const days = Math.floor((end - new Date()) / 86400000);
          if (statusFilter === "expired" && !(days < 0)) return false;
          if (statusFilter === "expiring" && !(days >= 0 && days <= 30)) return false;
        } else if (st !== statusFilter) return false;
      }
      if (!q) return true;
      return [t.tenant_code, t.name, t.slug, t.contact?.email, t.contact?.pic_name, t.contact?.whatsapp, t.plan?.name]
        .some((v) => String(v || "").toLowerCase().includes(q));
    });
  }, [tenants, query, statusFilter]);

  const doAction = async (fn, okMsg) => {
    setBusy(true);
    try { await fn(); if (okMsg) toast.success(okMsg); await refreshSelected(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail) || e.message); }
    finally { setBusy(false); }
  };
  const reactivate = () => doAction(() => api.post(`/platform/tenants/${selected.id}/reactivate`, { reason: "Reaktivasi dari Platform Admin" }), "Tenant diaktifkan kembali");
  const resend = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/platform/tenants/${selected.id}/resend-activation`);
      copy(r.data.activation_url);
      toast.success("Link aktivasi baru dibuat & disalin");
      await refreshSelected();
    } catch (e) { toast.error(apiError(e.response?.data?.detail) || e.message); }
    finally { setBusy(false); }
  };

  const kpis = [
    ["Total Tenant", dashboard.total_tenants ?? "-", Building2],
    ["Tenant Aktif", dashboard.active_tenants ?? "-", ShieldCheck],
    ["Akan Expired ≤30 Hari", dashboard.expiring_30_days ?? "-", CalendarClock],
    ["Perlu Perhatian", dashboard.attention_count ?? (dashboard.attention?.length || 0), TriangleAlert],
    ["Total User Aktif", dashboard.active_users ?? "-", Users],
  ];

  const s = selected;
  const storage = s?.storage || {};
  const userUsage = s?.user_usage || {};

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-20 border-b bg-white/95 backdrop-blur">
        <div className="max-w-[1700px] mx-auto h-16 px-4 sm:px-6 flex items-center gap-4">
          <div className="h-10 min-w-10 flex items-center justify-center">
            {platformLogoUrl ? <img src={platformLogoUrl} alt={platformBrand.name} className="h-9 max-w-[150px] object-contain" />
              : <div className="h-9 w-9 rounded-xl bg-slate-950 text-white flex items-center justify-center"><ShieldCheck className="h-5 w-5" /></div>}
          </div>
          <div className="min-w-0">
            <div className="font-head font-bold text-sm">{platformBrand.name || "KelolaKita Procurement"}</div>
            <div className="text-[11px] text-muted-foreground truncate">{user?.name || user?.email}</div>
          </div>
          <div className="flex-1" />
          <Button size="sm" onClick={() => setDlg((d) => ({ ...d, create: true }))} data-testid="add-tenant-btn"><Plus className="h-4 w-4 mr-2" />Tambah Tenant</Button>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}><RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />Refresh</Button>
          <Button variant="ghost" size="icon" onClick={logout} title="Keluar"><LogOut className="h-5 w-5" /></Button>
        </div>
      </header>

      <main className="max-w-[1700px] mx-auto p-4 sm:p-6 lg:p-8">
        <div className="mb-6">
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-semibold">SaaS Control Center</div>
          <h1 className="text-2xl sm:text-3xl font-head font-bold mt-1">Tenant Registry</h1>
          <p className="text-sm text-muted-foreground mt-1">Pusat kendali customer: kode tenant, user, paket, langganan, storage, undangan, dan audit aktivitas platform.</p>
        </div>

        {err && <div className="mb-5 rounded-xl bg-destructive/10 text-destructive px-4 py-3 text-sm">{err}</div>}

        <PlatformBranding />

        <div className="grid sm:grid-cols-2 xl:grid-cols-5 gap-4 mb-6">
          {kpis.map(([label, value, Icon]) => (
            <div key={label} className="rounded-2xl border bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between"><span className="text-sm text-muted-foreground">{label}</span><Icon className="h-4 w-4 text-muted-foreground" /></div>
              <div className="text-3xl font-bold font-head mt-3">{value}</div>
            </div>
          ))}
        </div>

        {dashboard.attention?.length > 0 && (
          <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50/60 p-4" data-testid="attention-panel">
            <div className="flex items-center gap-2 font-semibold text-sm text-amber-900 mb-3"><TriangleAlert className="h-4 w-4" />Perlu Perhatian ({dashboard.attention.length})</div>
            <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-2">
              {dashboard.attention.slice(0, 12).map((a, i) => (
                <button key={i} onClick={() => openTenant({ id: a.tenant_id })} className="text-left rounded-xl border bg-white px-3 py-2 hover:bg-slate-50 transition">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeClass(a.type === "expiring_soon" ? "expiring_soon" : a.severity === "danger" ? "expired" : "grace")}`}>{a.tenant_code}</span>
                    <span className="text-xs font-semibold truncate">{a.name}</span>
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-1">{a.message}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="grid xl:grid-cols-[1.05fr_0.95fr] gap-6 items-start">
          {/* LIST */}
          <section className="rounded-2xl border bg-white shadow-sm overflow-hidden">
            <div className="p-4 sm:p-5 border-b space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <div>
                  <div className="font-semibold">Daftar Tenant</div>
                  <div className="text-xs text-muted-foreground mt-0.5">Kode Tenant adalah identitas permanen customer.</div>
                </div>
                <div className="flex-1" />
                <div className="relative w-full sm:w-80">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari kode, perusahaan, WA, email..." className="pl-9" data-testid="tenant-search" />
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {[["all", "Semua"], ["active", "Aktif"], ["pending_activation", "Pending"], ["expiring", "Akan Expired"], ["expired", "Expired"], ["suspended", "Suspended"]].map(([v, l]) => (
                  <button key={v} onClick={() => setStatusFilter(v)} className={`h-8 px-3 rounded-lg text-xs font-medium border ${statusFilter === v ? "bg-slate-950 text-white border-slate-950" : "bg-white text-slate-600 hover:bg-slate-50"}`} data-testid={`filter-${v}`}>{l}</button>
                ))}
              </div>
            </div>

            {loading ? (
              <div className="p-12 flex items-center justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 mr-2 animate-spin" />Memuat tenant...</div>
            ) : filtered.length === 0 ? (
              <div className="p-12 text-center text-sm text-muted-foreground">Belum ada tenant yang sesuai.</div>
            ) : (
              <div className="divide-y max-h-[70vh] overflow-auto">
                {filtered.map((t) => (
                  <button key={t.id} onClick={() => openTenant(t)} className={`w-full text-left p-4 sm:p-5 hover:bg-slate-50 transition ${s?.id === t.id ? "bg-slate-50" : ""}`} data-testid={`tenant-row-${t.tenant_code}`}>
                    <div className="flex items-start gap-4">
                      <div className="h-10 w-10 rounded-xl bg-slate-100 flex items-center justify-center shrink-0 overflow-hidden">
                        {t.logo ? <img src={t.logo} alt="" className="h-full w-full object-contain" /> : <Building2 className="h-5 w-5 text-slate-600" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[11px] font-bold px-2 py-1 rounded-md bg-slate-950 text-white">{t.tenant_code || "NO-CODE"}</span>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeClass(t.status)}`}>{statusLabel(t.status)}</span>
                        </div>
                        <div className="font-semibold truncate mt-2">{t.name}</div>
                        <div className="text-xs text-muted-foreground mt-1 truncate">{t.slug} · {t.contact?.email || "-"} · {t.contact?.whatsapp || "-"}</div>
                        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                          <span>Paket <b className="text-foreground">{t.plan?.name || "-"}</b></span>
                          <span>User <b className="text-foreground">{t.usage?.users ?? 0}/{showLimit(t.limits?.max_users ?? t.plan?.limits?.max_users)}</b></span>
                          {t.subscription?.ends_at && <span>Berakhir <b className="text-foreground">{fmtDate(t.subscription.ends_at)}</b></span>}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          {/* DETAIL */}
          <aside className="rounded-2xl border bg-white shadow-sm xl:sticky xl:top-24 overflow-hidden">
            {!s ? (
              <div className="p-10 text-center text-sm text-muted-foreground">Pilih tenant untuk melihat ringkasan, user, subscription, dan audit aktivitas.</div>
            ) : (
              <div>
                <div className="p-5 border-b bg-slate-950 text-white">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Kode Tenant</div>
                      <div className="font-mono font-bold text-lg mt-1" data-testid="detail-tenant-code">{s.tenant_code || "-"}</div>
                    </div>
                    <span className={`text-[10px] px-2 py-1 rounded-full border ${badgeClass(s.status)}`}>{statusLabel(s.status)}</span>
                  </div>
                  <div className="font-head font-bold text-xl mt-4 truncate">{s.name}</div>
                  <div className="text-xs text-slate-400 mt-1">{s.slug}</div>
                  <div className="mt-4 grid sm:grid-cols-2 gap-2 text-xs text-slate-300">
                    <div className="flex items-center gap-2 min-w-0"><Mail className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{s.contact?.email || "-"}</span></div>
                    <div className="flex items-center gap-2"><Phone className="h-3.5 w-3.5 shrink-0" /><span>{s.contact?.whatsapp || "-"}</span></div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setDlg((d) => ({ ...d, edit: true }))} data-testid="edit-tenant-btn"><Pencil className="h-3.5 w-3.5 mr-1.5" />Edit</Button>
                    <Button size="sm" variant="secondary" onClick={() => setDlg((d) => ({ ...d, renew: true }))} data-testid="renew-btn"><RotateCcw className="h-3.5 w-3.5 mr-1.5" />Perpanjang</Button>
                    {s.status === "suspended"
                      ? <Button size="sm" variant="secondary" onClick={reactivate} disabled={busy} data-testid="reactivate-btn"><ShieldCheck className="h-3.5 w-3.5 mr-1.5" />Reactivate</Button>
                      : <Button size="sm" variant="secondary" className="text-orange-700" onClick={() => setDlg((d) => ({ ...d, suspend: true }))} data-testid="suspend-btn"><ShieldOff className="h-3.5 w-3.5 mr-1.5" />Suspend</Button>}
                  </div>
                </div>

                {/* Pending activation banner */}
                {s.pending_activation && s.activation && (
                  <div className="m-4 rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-xs" data-testid="pending-activation-banner">
                    <div className="font-semibold text-indigo-800 flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" />Menunggu Aktivasi Tenant Admin</div>
                    <div className="mt-2 flex gap-2">
                      <Input readOnly value={s.activation.activation_url} className="font-mono text-[11px] h-8" />
                      <Button size="sm" variant="outline" className="h-8" onClick={() => copy(s.activation.activation_url)}><Copy className="h-3.5 w-3.5" /></Button>
                      <Button size="sm" className="h-8" onClick={resend} disabled={busy} data-testid="resend-activation-btn"><Send className="h-3.5 w-3.5 mr-1" />Kirim ulang</Button>
                    </div>
                  </div>
                )}

                <div className="border-b p-2 flex gap-1 overflow-x-auto">
                  {[["overview", "Ringkasan", Building2], ["users", `User (${s.users?.length ?? 0})`, UserRound], ["subscription", "Subscription", CalendarClock], ["invitations", "Undangan", Link2], ["activity", "Aktivitas", Activity]].map(([key, label, Icon]) => (
                    <button key={key} type="button" onClick={() => setDetailTab(key)} className={`shrink-0 h-9 px-3 rounded-lg text-xs font-medium flex items-center gap-2 ${detailTab === key ? "bg-slate-950 text-white" : "hover:bg-slate-100 text-slate-600"}`} data-testid={`tab-${key}`}>
                      <Icon className="h-3.5 w-3.5" />{label}
                    </button>
                  ))}
                </div>

                <div className="p-5 max-h-[calc(100vh-22rem)] overflow-auto">
                  {detailTab === "overview" && (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 gap-3">
                        <UsageBar icon={Users} label="User Aktif" valueText={`${userUsage.active ?? 0} / ${showLimit(userUsage.limit)}`} percent={userUsage.limit ? (userUsage.active / userUsage.limit) * 100 : null} danger={userUsage.limit != null && userUsage.active >= userUsage.limit} />
                        <UsageBar icon={HardDrive} label="Storage" valueText={`${storage.used_gb ?? 0} / ${showLimit(storage.limit_gb)} GB`} percent={storage.percent} danger={storage.percent != null && storage.percent >= 80} />
                      </div>
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Email Utama</div><div className="font-semibold mt-1 truncate">{s.contact?.email || "-"}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">PIC</div><div className="font-semibold mt-1 truncate">{s.contact?.pic_name || "-"}{s.contact?.pic_position ? ` · ${s.contact.pic_position}` : ""}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Paket</div><div className="font-semibold mt-1">{s.plan?.name || s.plan_code || "-"}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Masa Berlaku</div><div className="font-semibold mt-1">{fmtDate(s.subscription?.ends_at)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Tanggal Daftar</div><div className="font-semibold mt-1">{fmtDate(s.created_at)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Aktivasi</div><div className="font-semibold mt-1">{fmtDate(s.subscription?.activated_at)}</div></div>
                      </div>
                      {s.address && <div className="rounded-xl border p-3 text-xs"><div className="text-muted-foreground">Alamat</div><div className="mt-1">{s.address}</div></div>}
                      {s.admin_notes && <div className="rounded-xl border p-3 text-xs"><div className="text-muted-foreground">Catatan Internal</div><div className="mt-1">{s.admin_notes}</div></div>}
                      <div className="rounded-xl border p-3 text-xs"><div className="text-muted-foreground">Tenant ID Internal</div><div className="font-mono break-all mt-1">{s.id}</div></div>
                    </div>
                  )}

                  {detailTab === "users" && (
                    <div className="space-y-3">
                      {(s.users || []).length === 0 ? <div className="text-sm text-muted-foreground text-center py-8">Belum ada user.</div> : s.users.map((u) => (
                        <div key={u.id} className="rounded-xl border p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0"><div className="font-semibold truncate">{u.name || u.email}</div><div className="text-xs text-muted-foreground truncate mt-1">{u.email}</div></div>
                            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeClass(u.status === "pending_activation" ? "pending_activation" : u.is_active === false ? "expired" : "active")}`}>{u.status === "pending_activation" ? "pending" : u.is_active === false ? "nonaktif" : "aktif"}</span>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                            <span className="rounded-md bg-slate-100 px-2 py-1">Role: {u.role || "-"}</span>
                            <span className="rounded-md bg-slate-100 px-2 py-1">Scope: {u.scope || "-"}</span>
                            {u.last_login_at && <span className="rounded-md bg-slate-100 px-2 py-1">Login: {fmtDateTime(u.last_login_at)}</span>}
                            <span className="rounded-md bg-slate-100 px-2 py-1">Dibuat: {fmtDate(u.created_at)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {detailTab === "subscription" && (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Status</div><div className="font-semibold mt-1">{statusLabel(s.subscription_view?.display_status || s.subscription?.status)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Sisa Hari</div><div className="font-semibold mt-1">{s.subscription_view?.days_remaining == null ? "Tanpa batas" : `${s.subscription_view.days_remaining} hari`}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Mulai</div><div className="font-semibold mt-1">{fmtDate(s.subscription?.started_at)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Berakhir</div><div className="font-semibold mt-1">{fmtDate(s.subscription?.ends_at)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">User Limit</div><div className="font-semibold mt-1">{showLimit(s.effective_limits?.max_users)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Storage Limit</div><div className="font-semibold mt-1">{showLimit(s.effective_limits?.storage_limit_gb)} GB</div></div>
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => setDlg((d) => ({ ...d, renew: true }))}><RotateCcw className="h-3.5 w-3.5 mr-1.5" />Perpanjang</Button>
                      </div>
                      <div>
                        <div className="text-sm font-semibold mb-2">Histori Periode</div>
                        {(s.subscription_history || []).length === 0 ? <div className="text-xs text-muted-foreground">Belum ada histori perpanjangan.</div> : (
                          <div className="space-y-2">
                            {s.subscription_history.map((h, i) => (
                              <div key={i} className="rounded-xl border p-3 text-xs">
                                <div className="flex items-center justify-between"><b>Periode {h.period_no}</b><span className="text-muted-foreground">{fmtDate(h.started_at)} — {fmtDate(h.ends_at)}</span></div>
                                <div className="text-muted-foreground mt-1">Paket: {h.plan_code || "-"} · User: {showLimit(h.max_users)} · Storage: {showLimit(h.storage_limit_gb)} GB</div>
                                <div className="text-[10px] text-muted-foreground mt-1">Diarsipkan {fmtDateTime(h.archived_at)} oleh {h.archived_by || "-"}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      {(s.suspend_history || []).length > 0 && (
                        <div>
                          <div className="text-sm font-semibold mb-2">Histori Suspend / Reactivate</div>
                          <div className="space-y-2">
                            {s.suspend_history.map((h, i) => (
                              <div key={i} className="rounded-xl border p-3 text-xs">
                                <div className="flex items-center justify-between"><b className={h.action === "suspend" ? "text-orange-700" : "text-emerald-700"}>{h.action === "suspend" ? "Suspend" : "Reactivate"}</b><span className="text-muted-foreground">{fmtDateTime(h.at)}</span></div>
                                {h.reason && <div className="text-muted-foreground mt-1">Alasan: {h.reason}</div>}
                                <div className="text-[10px] text-muted-foreground mt-1">Oleh {h.by || "-"}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {detailTab === "invitations" && <PlatformInvitations tenantId={s.id} />}

                  {detailTab === "activity" && (
                    <div className="space-y-3">
                      {(s.audit_logs || []).length === 0 ? <div className="text-sm text-muted-foreground text-center py-8">Belum ada aktivitas platform.</div> : s.audit_logs.map((log) => (
                        <div key={log.id} className="rounded-xl border p-4">
                          <div className="flex items-start justify-between gap-3"><div className="font-semibold text-sm">{log.action}</div><div className="text-[10px] text-muted-foreground whitespace-nowrap">{fmtDateTime(log.at)}</div></div>
                          <div className="text-xs text-muted-foreground mt-1">Oleh: {log.user_email || "system"}</div>
                          {log.after && <pre className="mt-3 text-[10px] bg-slate-50 rounded-lg p-3 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(log.after, null, 2)}</pre>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </aside>
        </div>
      </main>

      <CreateTenantDialog open={dlg.create} onOpenChange={(v) => setDlg((d) => ({ ...d, create: v }))} plans={plans} onCreated={load} />
      {s && <RenewDialog open={dlg.renew} onOpenChange={(v) => setDlg((d) => ({ ...d, renew: v }))} tenant={s} plans={plans} onDone={refreshSelected} />}
      {s && <SuspendDialog open={dlg.suspend} onOpenChange={(v) => setDlg((d) => ({ ...d, suspend: v }))} tenant={s} onDone={refreshSelected} />}
      {s && <EditProfileDialog open={dlg.edit} onOpenChange={(v) => setDlg((d) => ({ ...d, edit: v }))} tenant={s} onDone={refreshSelected} />}
    </div>
  );
}
