import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { PermissionGrid, SpecialList, CheckCell } from "@/components/access/PermissionGrid";
import { Loader2, Lock, Search, Save } from "lucide-react";
import { toast } from "sonner";

export function DivisionScopeEditor({ value, onChange, divisions, allowInherit, testid }) {
  const mode = value === null ? "inherit" : value?.mode || "all";
  const set = (m) => onChange(m === "inherit" ? null : { mode: m, divisions: m === "selected" ? value?.divisions || [] : [] });
  const toggle = (id) => onChange({ mode: "selected", divisions: (value?.divisions || []).includes(id) ? value.divisions.filter((x) => x !== id) : [...(value?.divisions || []), id] });
  return <div className="space-y-3" data-testid={testid}>
    <div className="flex flex-wrap gap-2">{[...(allowInherit ? [["inherit", "Ikuti Role"]] : []), ["all", "Semua Divisi"], ["selected", "Divisi Tertentu"]].map(([k, l]) =>
      <Button key={k} type="button" size="sm" variant={mode === k ? "default" : "outline"} onClick={() => set(k)} data-testid={`${testid}-${k}`}>{l}</Button>)}</div>
    {mode === "selected" && <div className="flex flex-wrap gap-3 rounded-lg border bg-muted/20 p-3">{divisions.length ? divisions.map((d) =>
      <label key={d.id} className="flex items-center gap-2 text-sm"><Checkbox checked={(value?.divisions || []).includes(d.id)} onCheckedChange={() => toggle(d.id)} data-testid={`${testid}-div-${d.code || d.id}`} />{d.name}</label>)
      : <span className="text-sm text-muted-foreground">Belum ada divisi.</span>}</div>}
  </div>;
}

export function RoleAccessTab() {
  const [catalog, setCatalog] = useState(null);
  const [roles, setRoles] = useState([]);
  const [divisions, setDivisions] = useState([]);
  const [active, setActive] = useState("warehouse");
  const [perms, setPerms] = useState(new Set());
  const [scope, setScope] = useState({ mode: "all", divisions: [] });
  const [dirty, setDirty] = useState(false);
  const [q, setQ] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => api.get("/access/roles").then((r) => setRoles(r.data));
  useEffect(() => {
    api.get("/access/catalog").then((r) => setCatalog(r.data));
    api.get("/lookup/divisions").then((r) => setDivisions(r.data)).catch(() => {});
    load();
  }, []);
  const role = roles.find((r) => r.role === active);
  useEffect(() => { if (role) { setPerms(new Set(role.permissions)); setScope(role.division_scope); setDirty(false); } }, [role]);
  useEffect(() => {
    const warn = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const pick = (r) => { if (dirty && !window.confirm("Perubahan hak akses belum disimpan. Tinggalkan tanpa menyimpan?")) return; setActive(r); };
  const toggle = (k, v) => { setPerms((s) => { const n = new Set(s); v ? n.add(k) : n.delete(k); return n; }); setDirty(true); };
  const save = async () => {
    setSaving(true);
    try { const r = await api.put(`/access/roles/${active}`, { permissions: [...perms], division_scope: scope }); toast.success(`Hak akses role ${role.label} tersimpan (${r.data.changed} perubahan)`); setDirty(false); await load(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };
  if (!catalog || !role) return <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Memuat hak akses...</div>;
  const locked = role.locked;
  const cell = (k) => <CheckCell checked={perms.has(k)} disabled={locked} onChange={(v) => toggle(k, v)} testid={`role-perm-${k}`} />;
  return <div className="space-y-4" data-testid="role-access-tab">
    <div className="flex flex-wrap items-center gap-2">{roles.map((r) => <Button key={r.role} size="sm" variant={r.role === active ? "default" : "outline"} onClick={() => pick(r.role)} data-testid={`role-tab-${r.role}`}>{r.label}</Button>)}</div>
    {locked ? <div className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="role-admin-locked"><Lock className="h-4 w-4" />Role Admin selalu memiliki akses penuh dan tidak dapat diubah.</div> : <>
      <div className="rounded-xl border bg-card p-4"><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cakupan Divisi Default</div>
        <DivisionScopeEditor value={scope} onChange={(v) => { setScope(v); setDirty(true); }} divisions={divisions} testid="role-scope" /></div>
      <div className="sticky top-0 z-20 flex flex-wrap items-center gap-3 rounded-xl border bg-background/95 p-3 backdrop-blur">
        <div className="relative max-w-xs flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari modul..." className="pl-9" data-testid="role-perm-search" /></div>
        {dirty && <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800" data-testid="role-perm-dirty">Ada perubahan belum disimpan</span>}
        <Button className="ml-auto" onClick={save} disabled={!dirty || saving} data-testid="role-perm-save">{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Simpan</Button>
      </div>
      <PermissionGrid catalog={catalog} search={q} renderCell={cell} testid="role-perm-grid" />
      <SpecialList catalog={catalog} renderCell={cell} />
    </>}
  </div>;
}
