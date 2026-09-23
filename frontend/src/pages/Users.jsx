import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field } from "@/components/DatePicker";
import { Copy, Link2, Plus, Pencil, ShieldCheck, UserPlus, XCircle } from "lucide-react";
import { toast } from "sonner";

const ROLES = ["admin", "director", "manager", "purchasing", "warehouse"];

const fmtDate = (value) => {
  if (!value) return "-";
  try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
};

const inviteStatusLabel = (status) => ({
  pending: "Menunggu",
  used: "Dipakai",
  expired: "Kedaluwarsa",
  cancelled: "Dibatalkan",
  activating: "Diproses",
}[status] || status || "-");

export default function Users() {
  const { can, user } = useAuth();
  const [users, setUsers] = useState([]);
  const [divisions, setDivisions] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [catalog, setCatalog] = useState({ permissions: [], role_defaults: {} });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({});
  const [invites, setInvites] = useState([]);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteSaving, setInviteSaving] = useState(false);
  const [inviteForm, setInviteForm] = useState({});

  const load = () => api.get("/users").then((r) => setUsers(r.data));
  const loadInvites = () => {
    if (user?.role !== "admin") return Promise.resolve();
    return api.get("/invitations").then((r) => setInvites(r.data || [])).catch(() => setInvites([]));
  };

  useEffect(() => {
    load();
    loadInvites();
    api.get("/master/divisions?active_only=true").then((r) => setDivisions(r.data));
    api.get("/master/warehouses?active_only=true").then((r) => setWarehouses(r.data));
    api.get("/permissions/catalog").then((r) => setCatalog(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openNew = () => { setForm({ role: "warehouse", scope: "limited", divisions: [], warehouses: [], permissions: catalog.role_defaults.warehouse || [], is_active: true }); setOpen(true); };
  const openEdit = (u) => { setForm({ ...u, password: "" }); setOpen(true); };
  const setRole = (role) => setForm({ ...form, role, permissions: catalog.role_defaults[role] || [] });
  const togglePerm = (p) => setForm({ ...form, permissions: form.permissions.includes(p) ? form.permissions.filter((x) => x !== p) : [...form.permissions, p] });
  const toggleArr = (key, id) => setForm({ ...form, [key]: (form[key] || []).includes(id) ? form[key].filter((x) => x !== id) : [...(form[key] || []), id] });

  const save = async () => {
    try {
      const payload = { ...form };
      if (!payload.password) delete payload.password;
      if (form.id) await api.put(`/users/${form.id}`, payload);
      else await api.post("/users", payload);
      toast.success("User tersimpan"); setOpen(false); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  const openInvite = () => {
    setInviteForm({
      name: "",
      email: "",
      role: "warehouse",
      scope: "limited",
      divisions: [],
      warehouses: [],
      expires_hours: 72,
    });
    setInviteOpen(true);
  };

  const setInviteRole = (role) => {
    const forceGlobal = ["admin", "director", "purchasing"].includes(role);
    setInviteForm((x) => ({
      ...x,
      role,
      scope: forceGlobal ? "global" : x.scope || "limited",
      divisions: forceGlobal ? [] : x.divisions || [],
      warehouses: forceGlobal ? [] : x.warehouses || [],
    }));
  };

  const toggleInviteArr = (key, id) => setInviteForm((x) => ({
    ...x,
    [key]: (x[key] || []).includes(id) ? x[key].filter((v) => v !== id) : [...(x[key] || []), id],
  }));

  const saveInvite = async () => {
    if (!inviteForm.name || !inviteForm.email) {
      toast.error("Nama dan email wajib diisi");
      return;
    }
    setInviteSaving(true);
    try {
      const r = await api.post("/invitations", inviteForm);
      toast.success(`Undangan dibuat: ${r.data?.code || "berhasil"}`);
      setInviteOpen(false);
      await loadInvites();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setInviteSaving(false);
    }
  };

  const copyInviteLink = async (invite) => {
    const url = `${window.location.origin}/invite/${invite.code}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link undangan disalin");
    } catch {
      window.prompt("Salin link undangan ini:", url);
    }
  };

  const cancelInvite = async (invite) => {
    try {
      await api.post(`/invitations/${invite.id}/cancel`);
      toast.success("Undangan dibatalkan");
      await loadInvites();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail) || e.message);
    }
  };

  return (
    <div>
      <PageHeader title="User & Hak Akses" subtitle="Kelola user, role, divisi, gudang, permission, dan undangan user">
        <div className="flex flex-wrap gap-2">
          {user?.role === "admin" && <Button variant="outline" onClick={openInvite}><UserPlus className="h-4 w-4 mr-2" />Undang User</Button>}
          {can("create") && <Button onClick={openNew} data-testid="user-create-btn"><Plus className="h-4 w-4 mr-2" />Tambah User</Button>}
        </div>
      </PageHeader>

      {user?.role === "admin" && (
        <Card className="mb-5">
          <CardContent className="p-0">
            <div className="p-4 border-b flex items-center justify-between gap-3">
              <div>
                <div className="font-semibold text-sm flex items-center gap-2"><Link2 className="h-4 w-4" />Undangan User</div>
                <div className="text-xs text-muted-foreground mt-1">Kode/link sekali pakai. User membuat password sendiri saat aktivasi.</div>
              </div>
              <Button size="sm" variant="outline" onClick={openInvite}><UserPlus className="h-4 w-4 mr-2" />Buat Undangan</Button>
            </div>
            {invites.length === 0 ? (
              <div className="p-5 text-sm text-muted-foreground">Belum ada undangan user.</div>
            ) : (
              <div className="divide-y">
                {invites.slice(0, 10).map((inv) => (
                  <div key={inv.id} className="p-4 flex flex-col lg:flex-row lg:items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-sm truncate">{inv.name}</span>
                        <span className="font-mono text-[11px] rounded-md bg-slate-100 px-2 py-1">{inv.code}</span>
                        <span className="text-[10px] rounded-full border px-2 py-0.5">{inviteStatusLabel(inv.status)}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1 truncate">{inv.email} · Role {inv.role} · Berlaku sampai {fmtDate(inv.expires_at)}</div>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <Button size="sm" variant="outline" onClick={() => copyInviteLink(inv)} disabled={inv.status !== "pending"}><Copy className="h-3.5 w-3.5 mr-2" />Salin Link</Button>
                      {inv.status === "pending" && <Button size="sm" variant="ghost" onClick={() => cancelInvite(inv)}><XCircle className="h-3.5 w-3.5 mr-2" />Batalkan</Button>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">Nama</th><th className="p-3">Email</th><th className="p-3">Role</th><th className="p-3">Scope</th><th className="p-3 text-right">Permission</th><th className="p-3">Status</th><th className="p-3 w-16"></th></tr></thead>
        <tbody>{users.map((u) => (<tr key={u.id} className="border-t hover:bg-accent/40 transition-colors"><td className="p-3 font-medium">{u.name}</td><td className="p-3">{u.email}</td><td className="p-3 capitalize">{u.role}</td><td className="p-3 capitalize">{u.scope}</td><td className="p-3 text-right">{(u.permissions || []).length}</td><td className="p-3">{u.is_active ? <span className="text-emerald-600 text-xs font-semibold">Aktif</span> : <span className="text-muted-foreground text-xs">Nonaktif</span>}</td><td className="p-3">{can("edit") && <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(u)} data-testid={`user-edit-${u.email}`}><Pencil className="h-4 w-4" /></Button>}</td></tr>))}</tbody></table></div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle className="font-head flex items-center gap-2"><ShieldCheck className="h-5 w-5" />{form.id ? "Edit User" : "Tambah User"}</DialogTitle></DialogHeader>
          <div className="space-y-5 py-2">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Nama *"><Input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="user-name" /></Field>
              <Field label="Email *"><Input type="email" value={form.email || ""} onChange={(e) => setForm({ ...form, email: e.target.value })} disabled={!!form.id} data-testid="user-email" /></Field>
              <Field label={form.id ? "Password (kosongkan jika tetap)" : "Password *"}><Input type="password" value={form.password || ""} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="user-password" /></Field>
              <Field label="Role"><Select value={form.role} onValueChange={setRole}><SelectTrigger data-testid="user-role"><SelectValue /></SelectTrigger><SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r} className="capitalize">{r}</SelectItem>)}</SelectContent></Select></Field>
              <Field label="Scope"><Select value={form.scope} onValueChange={(v) => setForm({ ...form, scope: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="limited">Terbatas</SelectItem><SelectItem value="global">Global</SelectItem></SelectContent></Select></Field>
              <Field label="Status"><label className="flex items-center gap-2 h-9"><Checkbox checked={form.is_active} onCheckedChange={(v) => setForm({ ...form, is_active: !!v })} />Aktif</label></Field>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Divisi</div>
              <div className="flex flex-wrap gap-3">{divisions.map((d) => <label key={d.id} className="flex items-center gap-2 text-sm"><Checkbox checked={(form.divisions || []).includes(d.id)} onCheckedChange={() => toggleArr("divisions", d.id)} data-testid={`user-div-${d.code}`} />{d.name}</label>)}</div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Gudang</div>
              <div className="flex flex-wrap gap-3">{warehouses.map((w) => <label key={w.id} className="flex items-center gap-2 text-sm"><Checkbox checked={(form.warehouses || []).includes(w.id)} onCheckedChange={() => toggleArr("warehouses", w.id)} />{w.name}</label>)}</div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Permission</div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">{catalog.permissions.map((p) => <label key={p} className="flex items-center gap-2 text-sm"><Checkbox checked={(form.permissions || []).includes(p)} onCheckedChange={() => togglePerm(p)} data-testid={`user-perm-${p}`} /><span className="font-mono text-xs">{p}</span></label>)}</div>
            </div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Batal</Button><Button onClick={save} data-testid="user-save-btn">Simpan</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><UserPlus className="h-5 w-5" />Buat Undangan User</DialogTitle></DialogHeader>
          <div className="space-y-5 py-2">
            <div className="rounded-xl border bg-slate-50 p-4 text-xs text-muted-foreground leading-5">User tidak perlu diberi password oleh Admin. Sistem membuat kode/link sekali pakai dan user menentukan password sendiri saat aktivasi.</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Nama *"><Input value={inviteForm.name || ""} onChange={(e) => setInviteForm({ ...inviteForm, name: e.target.value })} /></Field>
              <Field label="Email *"><Input type="email" value={inviteForm.email || ""} onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })} /></Field>
              <Field label="Role"><Select value={inviteForm.role || "warehouse"} onValueChange={setInviteRole}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r} className="capitalize">{r}</SelectItem>)}</SelectContent></Select></Field>
              <Field label="Scope"><Select value={inviteForm.scope || "limited"} onValueChange={(v) => setInviteForm({ ...inviteForm, scope: v })} disabled={["admin", "director", "purchasing"].includes(inviteForm.role)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="limited">Terbatas</SelectItem><SelectItem value="global">Global</SelectItem></SelectContent></Select></Field>
              <Field label="Masa Berlaku"><Select value={String(inviteForm.expires_hours || 72)} onValueChange={(v) => setInviteForm({ ...inviteForm, expires_hours: Number(v) })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="24">24 jam</SelectItem><SelectItem value="72">3 hari</SelectItem><SelectItem value="168">7 hari</SelectItem></SelectContent></Select></Field>
            </div>
            {inviteForm.scope === "limited" && (
              <>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Divisi</div>
                  <div className="flex flex-wrap gap-3">{divisions.length ? divisions.map((d) => <label key={d.id} className="flex items-center gap-2 text-sm"><Checkbox checked={(inviteForm.divisions || []).includes(d.id)} onCheckedChange={() => toggleInviteArr("divisions", d.id)} />{d.name}</label>) : <span className="text-sm text-muted-foreground">Belum ada divisi.</span>}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Gudang</div>
                  <div className="flex flex-wrap gap-3">{warehouses.length ? warehouses.map((w) => <label key={w.id} className="flex items-center gap-2 text-sm"><Checkbox checked={(inviteForm.warehouses || []).includes(w.id)} onCheckedChange={() => toggleInviteArr("warehouses", w.id)} />{w.name}</label>) : <span className="text-sm text-muted-foreground">Belum ada gudang.</span>}</div>
                </div>
              </>
            )}
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setInviteOpen(false)}>Batal</Button><Button onClick={saveInvite} disabled={inviteSaving}>{inviteSaving ? "Membuat..." : "Buat Undangan"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
