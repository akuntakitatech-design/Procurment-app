import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { PermissionGrid, SpecialList } from "@/components/access/PermissionGrid";
import { DivisionScopeEditor } from "@/components/access/RoleAccessTab";
import { Loader2, Search } from "lucide-react";

const NEXT = { undefined: "allow", allow: "deny", deny: undefined };
const OV = { allow: "Izinkan", deny: "Tolak" };

// Pengaturan Khusus Pengguna: tri-state per izin (Ikuti Role / Izinkan / Tolak). Parent saves {overrides, division_override}.
export function UserAccessPanel({ uid, divisions, onChange }) {
  const [info, setInfo] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [ov, setOv] = useState({});
  const [div, setDiv] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    api.get("/access/catalog").then((r) => setCatalog(r.data));
    api.get(`/access/users/${uid}`).then((r) => { setInfo(r.data); setOv(r.data.overrides || {}); setDiv(r.data.division_override); });
  }, [uid]);
  const updOv = (next) => { setOv(next); onChange({ overrides: next, division_override: div }); };
  const updDiv = (next) => { setDiv(next); onChange({ overrides: ov, division_override: next }); };
  const role = useMemo(() => new Set(info?.role_permissions || []), [info]);
  const labelOf = useMemo(() => {
    const m = {};
    (catalog?.groups || []).forEach((g) => g.modules.forEach((x) => x.actions.forEach((a) => { m[`${x.key}.${a}`] = `${x.label} → ${catalog.actions[a]}`; })));
    (catalog?.specials || []).forEach((s) => { m[s.key] = s.label; });
    return m;
  }, [catalog]);
  if (!info || !catalog) return <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Memuat hak akses pengguna...</div>;
  const effective = (k) => (ov[k] === "allow" ? true : ov[k] === "deny" ? false : role.has(k));
  const cell = (k) => {
    const e = effective(k), o = ov[k];
    return <button type="button" onClick={() => { const n = { ...ov }; const nx = NEXT[o]; if (nx) n[k] = nx; else delete n[k]; updOv(n); }}
      title={`Role: ${role.has(k) ? "Ya" : "Tidak"} · Pengaturan Khusus: ${OV[o] || "Ikuti Role"} · Efektif: ${e ? "Ya" : "Tidak"}`}
      className={`inline-flex h-6 min-w-6 items-center justify-center rounded-md border px-1 text-[11px] font-bold transition-colors ${e ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-400"} ${o ? "ring-2 ring-offset-1 " + (o === "allow" ? "ring-sky-400" : "ring-rose-400") : ""}`}
      data-testid={`user-perm-${k}`} data-state={o || "inherit"}>{e ? "✓" : "✕"}</button>;
  };
  const changed = Object.keys(ov);
  return <div className="space-y-4" data-testid="user-access-panel">
    <div className="rounded-xl border bg-card p-4"><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cakupan Divisi</div>
      <DivisionScopeEditor value={div} onChange={updDiv} divisions={divisions} allowInherit testid="user-scope" />
      <p className="mt-2 text-xs text-muted-foreground">Default role: {info.role_division_scope?.mode === "all" ? "Semua Divisi" : `Divisi Tertentu (${(info.role_division_scope?.divisions || []).length})`}</p></div>
    <div className="rounded-xl border bg-muted/20 p-3 text-xs text-muted-foreground">Klik sel untuk mengganti: <b>Ikuti Role</b> → <b className="text-sky-700">Izinkan</b> → <b className="text-rose-700">Tolak</b>. Sel bergaris warna = pengaturan khusus pengguna. ✓/✕ = hak akses efektif.</div>
    {changed.length > 0 && <div className="rounded-xl border bg-card" data-testid="user-override-summary">
      <div className="border-b p-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pengaturan Khusus Pengguna ({changed.length})</div>
      <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th className="p-2.5">Hak Akses</th><th className="p-2.5">Role</th><th className="p-2.5">Pengaturan Khusus</th><th className="p-2.5">Efektif</th></tr></thead>
        <tbody>{changed.map((k) => <tr key={k} className="border-t" data-testid={`user-override-${k}`}><td className="p-2.5">{labelOf[k] || k}</td><td className="p-2.5">{role.has(k) ? "Ya" : "Tidak"}</td><td className="p-2.5 font-semibold">{OV[ov[k]]}</td><td className="p-2.5">{effective(k) ? "Ya" : "Tidak"} <span className="text-xs text-muted-foreground">(dari Pengaturan Khusus)</span></td></tr>)}</tbody></table>
    </div>}
    <div className="relative max-w-xs"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari modul..." className="pl-9" data-testid="user-perm-search" /></div>
    <PermissionGrid catalog={catalog} search={q} renderCell={cell} testid="user-perm-grid" />
    <SpecialList catalog={catalog} renderCell={cell} />
  </div>;
}
