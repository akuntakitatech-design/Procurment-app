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
import { Plus, Pencil, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

const ROLES = ["admin", "director", "manager", "purchasing", "warehouse"];

export default function Users() {
  const { can } = useAuth();
  const [users, setUsers] = useState([]);
  const [divisions, setDivisions] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [catalog, setCatalog] = useState({ permissions: [], role_defaults: {} });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({});

  const load = () => api.get("/users").then((r) => setUsers(r.data));
  useEffect(() => {
    load();
    api.get("/master/divisions?active_only=true").then((r) => setDivisions(r.data));
    api.get("/master/warehouses?active_only=true").then((r) => setWarehouses(r.data));
    api.get("/permissions/catalog").then((r) => setCatalog(r.data));
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

  return (
    <div>
      <PageHeader title="User & Hak Akses" subtitle="Kelola user, role, divisi, gudang, dan permission">
        {can("create") && <Button onClick={openNew} data-testid="user-create-btn"><Plus className="h-4 w-4 mr-2" />Tambah User</Button>}
      </PageHeader>
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
    </div>
  );
}
