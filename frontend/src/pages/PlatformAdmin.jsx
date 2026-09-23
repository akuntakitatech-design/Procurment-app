import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import api, { API, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import PlatformInvitations from "@/components/PlatformInvitations";
import PlatformBranding from "@/components/PlatformBranding";
import {
  Activity, Building2, CircleDollarSign, Clock3, Hash, Link2, Loader2, LogOut, Mail,
  Phone, RefreshCw, Search, ShieldCheck, TriangleAlert, UserRound, Users
} from "lucide-react";

const badgeClass = (status) => {
  const s = String(status || "").toLowerCase();
  if (s === "active") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (s === "trial") return "bg-sky-50 text-sky-700 border-sky-200";
  if (s === "suspended" || s === "grace") return "bg-amber-50 text-amber-700 border-amber-200";
  if (s === "expired") return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-slate-50 text-slate-600 border-slate-200";
};

const showLimit = (v) => (v == null ? "∞" : v);
const fmtDate = (value) => {
  if (!value) return "-";
  try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
};
const toDateInput = (value) => {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return String(value);
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const endOfLocalDayIso = (value) => {
  if (!value) return "";
  const d = new Date(`${value}T23:59:59.999`);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
};

export default function PlatformAdmin() {
  const { user, logout } = useAuth();
  const [summary, setSummary] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [plans, setPlans] = useState([]);
  const [subscriptionOverview, setSubscriptionOverview] = useState({ counts: {}, items: [], attention: [] });
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [platformBrand, setPlatformBrand] = useState({
    name: "KelolaKita Procurement",
    subtitle: "Procurement • Warehouse • Inventory",
    logo_available: false,
    logo_version: null,
  });
  const [detailTab, setDetailTab] = useState("overview");
  const [form, setForm] = useState({
    status: "active",
    plan_code: "starter",
    subscription_status: "trial",
    subscription_trial_ends_at: "",
    subscription_ends_at: "",
    max_users: "",
    max_companies: "",
    max_warehouses: "",
    max_divisions: "",
    notes: "",
  });

  const subscriptionByTenant = useMemo(() => new Map((subscriptionOverview.items || []).map((x) => [x.tenant_id, x])), [subscriptionOverview]);
  const selectedSubscription = selected ? subscriptionByTenant.get(selected.id) : null;

  useEffect(() => {
    api.get("/platform-branding")
      .then((r) => setPlatformBrand(r.data || {}))
      .catch(() => {});
  }, []);

  const platformLogoUrl = platformBrand.logo_available
    ? `${API}/platform-branding/logo?v=${encodeURIComponent(
        platformBrand.logo_version || "1"
      )}`
    : null;

  const syncForm = (t) => {
    if (!t) return;
    setForm({
      status: t.status || "active",
      plan_code: t.plan?.code || "starter",
      subscription_status: t.subscription?.status || "active",
      subscription_trial_ends_at: toDateInput(t.subscription?.trial_ends_at),
      subscription_ends_at: toDateInput(t.subscription?.ends_at),
      max_users: t.limits?.max_users ?? "",
      max_companies: t.limits?.max_companies ?? "",
      max_warehouses: t.limits?.max_warehouses ?? "",
      max_divisions: t.limits?.max_divisions ?? "",
      notes: t.admin_notes || "",
    });
  };

  const load = async () => {
    const selectedId = selected?.id;
    setLoading(true);
    setErr("");
    try {
      const [s, t, p, sub] = await Promise.all([
        api.get("/platform/summary"),
        api.get("/platform/tenants"),
        api.get("/saas/public-config"),
        api.get("/platform/subscriptions/overview"),
      ]);
      setSummary(s.data || {});
      setTenants(t.data || []);
      setPlans(p.data?.plans || []);
      setSubscriptionOverview(sub.data || { counts: {}, items: [], attention: [] });
      if (selectedId) {
        const d = await api.get(`/platform/tenants/${selectedId}`);
        setSelected(d.data);
        syncForm(d.data);
      }
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tenants;
    return tenants.filter((t) => [
      t.tenant_code, t.name, t.slug, t.contact?.email, t.contact?.pic_name,
      t.contact?.whatsapp, t.plan?.name,
    ].some((v) => String(v || "").toLowerCase().includes(q)));
  }, [tenants, query]);

  const planOptions = useMemo(() => {
    const list = [...plans];
    if (selected?.plan?.code && !list.some((p) => p.code === selected.plan.code)) list.unshift(selected.plan);
    return list;
  }, [plans, selected]);

  const openTenant = async (tenant) => {
    setErr("");
    setDetailTab("overview");
    try {
      const r = await api.get(`/platform/tenants/${tenant.id}`);
      setSelected(r.data);
      syncForm(r.data);
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    }
  };

  const saveTenant = async (e) => {
    e.preventDefault();
    if (!selected) return;
    setSaving(true);
    setErr("");
    try {
      const payload = {
        status: form.status,
        plan_code: form.plan_code,
        subscription_status: form.subscription_status,
        notes: form.notes,
      };
      for (const key of ["max_users", "max_companies", "max_warehouses", "max_divisions"]) {
        if (form[key] !== "" && form[key] != null) payload[key] = Number(form[key]);
      }
      await api.patch(`/platform/tenants/${selected.id}`, payload);
      await api.patch(`/platform/tenants/${selected.id}/subscription-dates`, {
        trial_ends_at: form.subscription_trial_ends_at ? endOfLocalDayIso(form.subscription_trial_ends_at) : "",
        ends_at: form.subscription_ends_at ? endOfLocalDayIso(form.subscription_ends_at) : "",
      });
      const [d, t, sub] = await Promise.all([
        api.get(`/platform/tenants/${selected.id}`),
        api.get("/platform/tenants"),
        api.get("/platform/subscriptions/overview"),
      ]);
      setSelected(d.data);
      syncForm(d.data);
      setTenants(t.data || []);
      setSubscriptionOverview(sub.data || { counts: {}, items: [], attention: [] });
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  const set = (key, value) => setForm((x) => ({ ...x, [key]: value }));

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-20 border-b bg-white/95 backdrop-blur">
        <div className="max-w-[1700px] mx-auto h-16 px-4 sm:px-6 flex items-center gap-4">
          <div className="h-10 min-w-10 flex items-center justify-center">
            {platformLogoUrl ? (
              <img
                src={platformLogoUrl}
                alt={platformBrand.name || "KelolaKita Procurement"}
                className="h-9 max-w-[150px] object-contain"
              />
            ) : (
              <div className="h-9 w-9 rounded-xl bg-slate-950 text-white flex items-center justify-center">
                <ShieldCheck className="h-5 w-5" />
              </div>
            )}
          </div>
          <div className="min-w-0">
            <div className="font-head font-bold text-sm">
              {platformBrand.name || "KelolaKita Procurement"}
            </div>
            <div className="text-[11px] text-muted-foreground truncate">
              {user?.name || user?.email}
            </div>
          </div>
          <div className="flex-1" />
          <Button variant="outline" size="sm" onClick={load} disabled={loading}><RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />Refresh</Button>
          <Button variant="ghost" size="icon" onClick={logout} title="Keluar"><LogOut className="h-5 w-5" /></Button>
        </div>
      </header>

      <main className="max-w-[1700px] mx-auto p-4 sm:p-6 lg:p-8">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-semibold">SaaS Control Center</div>
            <h1 className="text-2xl sm:text-3xl font-head font-bold mt-1">Tenant Registry</h1>
            <p className="text-sm text-muted-foreground mt-1">Pusat kendali customer, Kode Tenant, user, paket, langganan, undangan, dan audit aktivitas platform.</p>
          </div>
        </div>

        {err && <div className="mb-5 rounded-xl bg-destructive/10 text-destructive px-4 py-3 text-sm">{err}</div>}

        <PlatformBranding />

        <div className="grid sm:grid-cols-2 xl:grid-cols-5 gap-4 mb-6">
          {[
            ["Total Tenant", summary?.tenants ?? "-", Building2],
            ["Tenant Aktif", summary?.active_tenants ?? "-", ShieldCheck],
            ["Masa Trial", subscriptionOverview.counts?.trial ?? summary?.trial_tenants ?? "-", CircleDollarSign],
            ["Perlu Perhatian", subscriptionOverview.counts?.attention ?? "-", TriangleAlert],
            ["User Aktif", summary?.active_users ?? "-", Users],
          ].map(([label, value, Icon]) => (
            <div key={label} className="rounded-2xl border bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between"><span className="text-sm text-muted-foreground">{label}</span><Icon className="h-4 w-4 text-muted-foreground" /></div>
              <div className="text-3xl font-bold font-head mt-3">{value}</div>
            </div>
          ))}
        </div>

        {subscriptionOverview.attention?.length > 0 && (
          <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-sm text-amber-900"><Clock3 className="h-4 w-4" />Monitoring Langganan</div>
            <div className="text-xs text-amber-800 mt-1">{subscriptionOverview.counts?.due_7_days || 0} tenant jatuh tempo ≤7 hari. {subscriptionOverview.counts?.grace || 0} masa tenggang dan {subscriptionOverview.counts?.expired || 0} sudah berakhir.</div>
          </div>
        )}

        <div className="grid xl:grid-cols-[1.05fr_0.95fr] gap-6 items-start">
          <section className="rounded-2xl border bg-white shadow-sm overflow-hidden">
            <div className="p-4 sm:p-5 border-b flex flex-col sm:flex-row sm:items-center gap-3">
              <div>
                <div className="font-semibold">Daftar Tenant</div>
                <div className="text-xs text-muted-foreground mt-0.5">Kode Tenant adalah identitas permanen customer.</div>
              </div>
              <div className="flex-1" />
              <div className="relative w-full sm:w-96">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari kode, perusahaan, WA, email, workspace..." className="pl-9" />
              </div>
            </div>

            {loading ? (
              <div className="p-12 flex items-center justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 mr-2 animate-spin" />Memuat tenant...</div>
            ) : filtered.length === 0 ? (
              <div className="p-12 text-center text-sm text-muted-foreground">Belum ada tenant yang sesuai.</div>
            ) : (
              <div className="divide-y">
                {filtered.map((t) => {
                  const life = subscriptionByTenant.get(t.id);
                  return (
                    <button key={t.id} onClick={() => openTenant(t)} className={`w-full text-left p-4 sm:p-5 hover:bg-slate-50 transition ${selected?.id === t.id ? "bg-slate-50" : ""}`}>
                      <div className="flex items-start gap-4">
                        <div className="h-10 w-10 rounded-xl bg-slate-100 flex items-center justify-center shrink-0"><Building2 className="h-5 w-5 text-slate-600" /></div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[11px] font-bold px-2 py-1 rounded-md bg-slate-950 text-white">{t.tenant_code || "NO-CODE"}</span>
                            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeClass(t.status)}`}>{t.status || "-"}</span>
                            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeClass(life?.status || t.subscription?.status)}`}>{life?.status || t.subscription?.status || "-"}</span>
                          </div>
                          <div className="font-semibold truncate mt-2">{t.name}</div>
                          <div className="text-xs text-muted-foreground mt-1 truncate">{t.slug} · {t.contact?.email || "-"} · {t.contact?.whatsapp || "-"}</div>
                          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                            <span>Paket <b className="text-foreground">{t.plan?.name || "-"}</b></span>
                            <span>User <b className="text-foreground">{t.usage?.users ?? 0}/{showLimit(t.limits?.max_users ?? t.plan?.limits?.max_users)}</b></span>
                            <span>Gudang <b className="text-foreground">{t.usage?.warehouses ?? 0}/{showLimit(t.limits?.max_warehouses ?? t.plan?.limits?.max_warehouses)}</b></span>
                            {life?.deadline && <span>Jatuh tempo <b className="text-foreground">{fmtDate(life.deadline)}</b>{life.days_remaining != null ? ` · ${life.days_remaining} hari` : ""}</span>}
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <aside className="rounded-2xl border bg-white shadow-sm xl:sticky xl:top-24 overflow-hidden">
            {!selected ? (
              <div className="p-10 text-center text-sm text-muted-foreground">Pilih tenant untuk melihat detail, user, undangan, paket, dan audit aktivitas.</div>
            ) : (
              <div>
                <div className="p-5 border-b bg-slate-950 text-white">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Kode Tenant</div>
                      <div className="font-mono font-bold text-lg mt-1">{selected.tenant_code || "-"}</div>
                    </div>
                    <Hash className="h-5 w-5 text-slate-400" />
                  </div>
                  <div className="font-head font-bold text-xl mt-4 truncate">{selected.name}</div>
                  <div className="text-xs text-slate-400 mt-1">{selected.slug}</div>
                  <div className="mt-4 grid sm:grid-cols-2 gap-2 text-xs text-slate-300">
                    <div className="flex items-center gap-2 min-w-0"><Mail className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{selected.contact?.email || "-"}</span></div>
                    <div className="flex items-center gap-2"><Phone className="h-3.5 w-3.5 shrink-0" /><span>{selected.contact?.whatsapp || "-"}</span></div>
                  </div>
                </div>

                <div className="border-b p-2 flex gap-1 overflow-x-auto">
                  {[
                    ["overview", "Ringkasan", Building2],
                    ["users", `User (${selected.users?.length ?? selected.usage?.users ?? 0})`, UserRound],
                    ["invitations", "Undangan", Link2],
                    ["activity", "Aktivitas", Activity],
                  ].map(([key, label, Icon]) => (
                    <button key={key} type="button" onClick={() => setDetailTab(key)}
                      className={`shrink-0 h-9 px-3 rounded-lg text-xs font-medium flex items-center gap-2 ${detailTab === key ? "bg-slate-950 text-white" : "hover:bg-slate-100 text-slate-600"}`}>
                      <Icon className="h-3.5 w-3.5" />{label}
                    </button>
                  ))}
                </div>

                {detailTab === "overview" && (
                  <form onSubmit={saveTenant}>
                    <div className="p-5 space-y-5 max-h-[calc(100vh-18rem)] overflow-auto">
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">User Aktif</div><div className="font-bold text-lg mt-1">{selected.usage?.users ?? 0}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Perusahaan</div><div className="font-bold text-lg mt-1">{selected.usage?.companies ?? 0}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">Tanggal Daftar</div><div className="font-semibold mt-1">{fmtDate(selected.created_at)}</div></div>
                        <div className="rounded-xl bg-slate-50 p-3"><div className="text-muted-foreground">PIC / Owner</div><div className="font-semibold mt-1 truncate">{selected.contact?.pic_name || "-"}</div></div>
                      </div>

                      {selectedSubscription && (
                        <div className={`rounded-xl border p-4 text-xs ${selectedSubscription.severity === "danger" ? "border-rose-200 bg-rose-50" : selectedSubscription.severity === "warning" ? "border-amber-200 bg-amber-50" : "bg-slate-50"}`}>
                          <div className="flex items-center justify-between gap-3">
                            <div className="font-semibold">Status Langganan</div>
                            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeClass(selectedSubscription.status)}`}>{selectedSubscription.status}</span>
                          </div>
                          <div className="mt-2 leading-5 text-muted-foreground">{selectedSubscription.message}</div>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <div><span className="text-muted-foreground">Jatuh tempo:</span><br /><b>{fmtDate(selectedSubscription.deadline)}</b></div>
                            <div><span className="text-muted-foreground">Sisa:</span><br /><b>{selectedSubscription.days_remaining == null ? "Tanpa batas" : `${selectedSubscription.days_remaining} hari`}</b></div>
                          </div>
                          {selectedSubscription.last_reminder_at && <div className="mt-2 text-[11px] text-muted-foreground">Reminder terakhir: {fmtDate(selectedSubscription.last_reminder_at)} · {selectedSubscription.last_reminder_type}</div>}
                        </div>
                      )}

                      <div className="rounded-xl border p-3 text-xs">
                        <div className="text-muted-foreground">Tenant ID Internal</div>
                        <div className="font-mono break-all mt-1">{selected.id}</div>
                        <p className="text-[11px] text-muted-foreground mt-2">Gunakan Kode Tenant untuk operasional/support. Tenant ID hanya untuk kebutuhan teknis.</p>
                      </div>

                      <div className="grid sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2 gap-4">
                        <div className="space-y-2"><Label>Status Tenant</Label><select value={form.status} onChange={(e) => set("status", e.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm"><option value="active">Aktif</option><option value="suspended">Ditangguhkan</option></select></div>
                        <div className="space-y-2"><Label>Paket</Label><select value={form.plan_code} onChange={(e) => set("plan_code", e.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm">{planOptions.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select></div>
                        <div className="space-y-2"><Label>Status Langganan</Label><select value={form.subscription_status} onChange={(e) => set("subscription_status", e.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm"><option value="trial">Trial</option><option value="active">Aktif</option><option value="grace">Masa Tenggang</option><option value="expired">Berakhir</option><option value="suspended">Ditangguhkan</option></select></div>
                        <div className="space-y-2">
                          <Label>Trial Berakhir</Label>
                          <Input type="date" value={form.subscription_trial_ends_at} onChange={(e) => set("subscription_trial_ends_at", e.target.value)} />
                          <p className="text-[11px] text-muted-foreground">Dipakai saat status langganan masih Trial.</p>
                        </div>
                        <div className="space-y-2 sm:col-span-2 xl:col-span-1 2xl:col-span-2">
                          <Label>Langganan Berakhir</Label>
                          <Input type="date" value={form.subscription_ends_at} onChange={(e) => set("subscription_ends_at", e.target.value)} />
                          <p className="text-[11px] text-muted-foreground">Dipakai saat status Aktif. Kosongkan jika langganan tidak memiliki batas waktu.</p>
                        </div>
                      </div>

                      <div>
                        <div className="text-sm font-semibold mb-3">Override Limit</div>
                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-2"><Label>Max User</Label><Input type="number" min="1" value={form.max_users} onChange={(e) => set("max_users", e.target.value)} placeholder="Ikuti paket" /></div>
                          <div className="space-y-2"><Label>Max Perusahaan</Label><Input type="number" min="1" value={form.max_companies} onChange={(e) => set("max_companies", e.target.value)} placeholder="Ikuti paket" /></div>
                          <div className="space-y-2"><Label>Max Gudang</Label><Input type="number" min="1" value={form.max_warehouses} onChange={(e) => set("max_warehouses", e.target.value)} placeholder="Ikuti paket" /></div>
                          <div className="space-y-2"><Label>Max Divisi</Label><Input type="number" min="1" value={form.max_divisions} onChange={(e) => set("max_divisions", e.target.value)} placeholder="Ikuti paket" /></div>
                        </div>
                      </div>

                      <div className="space-y-2"><Label>Catatan Internal</Label><textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} className="w-full min-h-20 rounded-md border bg-background px-3 py-2 text-sm" placeholder="Catatan untuk tenant ini" /></div>
                      <Button type="submit" className="w-full" disabled={saving}>{saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Simpan Perubahan</Button>
                    </div>
                  </form>
                )}

                {detailTab === "users" && (
                  <div className="p-5 space-y-3 max-h-[calc(100vh-18rem)] overflow-auto">
                    {(selected.users || []).length === 0 ? (
                      <div className="text-sm text-muted-foreground text-center py-8">Belum ada user.</div>
                    ) : selected.users.map((u) => (
                      <div key={u.id} className="rounded-xl border p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="font-semibold truncate">{u.name || u.email}</div>
                            <div className="text-xs text-muted-foreground truncate mt-1">{u.email}</div>
                          </div>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${u.is_active === false ? badgeClass("expired") : badgeClass("active")}`}>{u.is_active === false ? "nonaktif" : "aktif"}</span>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                          <span className="rounded-md bg-slate-100 px-2 py-1">Role: {u.role || "-"}</span>
                          <span className="rounded-md bg-slate-100 px-2 py-1">Scope: {u.scope || "-"}</span>
                          <span className="rounded-md bg-slate-100 px-2 py-1">Dibuat: {fmtDate(u.created_at)}</span>
                        </div>
                      </div>
                    ))}
                    <p className="text-[11px] text-muted-foreground">User tenant dimonitor dari Platform. Pengelolaan akses lanjutan tetap akan memakai audit dan kontrol terpisah.</p>
                  </div>
                )}

                {detailTab === "invitations" && <PlatformInvitations tenantId={selected.id} />}

                {detailTab === "activity" && (
                  <div className="p-5 space-y-3 max-h-[calc(100vh-18rem)] overflow-auto">
                    {(selected.audit_logs || []).length === 0 ? (
                      <div className="text-sm text-muted-foreground text-center py-8">Belum ada aktivitas platform.</div>
                    ) : selected.audit_logs.map((log) => (
                      <div key={log.id} className="rounded-xl border p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="font-semibold text-sm">{log.action}</div>
                          <div className="text-[10px] text-muted-foreground whitespace-nowrap">{fmtDate(log.at)}</div>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">Oleh: {log.user_email || "system"}</div>
                        {log.after && <pre className="mt-3 text-[10px] bg-slate-50 rounded-lg p-3 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(log.after, null, 2)}</pre>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </aside>
        </div>
      </main>
    </div>
  );
}
