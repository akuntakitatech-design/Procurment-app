import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Eye, EyeOff, KeyRound, Save, ShieldCheck, UserRound } from "lucide-react";
import { toast } from "sonner";

const ROLE_LABEL = { admin: "Admin", director: "Direktur", manager: "Manager", purchasing: "Purchasing", warehouse: "Gudang", finance: "Finance", staff: "Staff" };

function FieldRow({ label, htmlFor, children, hint }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function PasswordInput({ id, value, onChange, testid, autoComplete }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input id={id} type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} data-testid={testid} className="pr-10" />
      <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Sembunyikan password" : "Tampilkan password"}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground" data-testid={`${testid}-toggle`}>
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

export default function Profile() {
  const { user, refreshUser, replaceSessionToken } = useAuth();
  const [form, setForm] = useState(null);
  const [orig, setOrig] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [pwErr, setPwErr] = useState("");
  const [pwSaving, setPwSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try { const r = await api.get("/profile"); const f = { name: r.data.name, email: r.data.email, phone: r.data.phone }; setForm(f); setOrig({ ...r.data }); }
    catch (e) { setError(apiError(e.response?.data?.detail)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const dirty = form && orig && ["name", "email", "phone"].some((k) => (form[k] || "") !== (orig[k] || ""));
  const saveProfile = async (e) => {
    e.preventDefault();
    if (!form.name?.trim()) return toast.error("Nama wajib diisi.");
    if (!form.email?.trim()) return toast.error("Email wajib diisi.");
    setSaving(true);
    try {
      const body = {};
      ["name", "email", "phone"].forEach((k) => { if ((form[k] || "") !== (orig[k] || "")) body[k] = form[k] || ""; });
      const r = await api.put("/profile", body);
      setOrig(r.data); setForm({ name: r.data.name, email: r.data.email, phone: r.data.phone });
      toast.success("Profil berhasil diperbarui.");
      refreshUser().catch(() => {});
    } catch (err) { toast.error(apiError(err.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    setPwErr("");
    if (!pw.current_password) return setPwErr("Password saat ini wajib diisi.");
    if (pw.new_password.length < 8) return setPwErr("Password baru minimal 8 karakter.");
    if (pw.new_password !== pw.confirm_password) return setPwErr("Konfirmasi password baru tidak sama.");
    setPwSaving(true);
    try {
      const r = await api.post("/auth/change-password", pw);
      replaceSessionToken(r.data?.token);
      setPw({ current_password: "", new_password: "", confirm_password: "" });
      toast.success(r.data?.message || "Password berhasil diubah.");
    } catch (err) { setPwErr(apiError(err.response?.data?.detail)); }
    finally { setPwSaving(false); }
  };

  if (error) return <Card><CardContent className="p-8 text-center" data-testid="profile-error"><p className="mb-3 text-destructive">{error}</p><Button variant="outline" onClick={load}>Coba lagi</Button></CardContent></Card>;

  return (
    <div data-testid="profile-page">
      <PageHeader title="Profil Saya" subtitle="Kelola informasi pribadi dan keamanan akun Anda." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardContent className="space-y-5 p-6">
          <div className="flex items-center gap-2 font-head font-semibold"><UserRound className="h-4 w-4 text-primary" />Informasi Profil</div>
          {!form ? <div className="space-y-3"><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /></div> :
            <form onSubmit={saveProfile} className="space-y-4">
              <FieldRow label="Nama *" htmlFor="profile-name"><Input id="profile-name" value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="profile-name" /></FieldRow>
              <FieldRow label="Email *" htmlFor="profile-email" hint="Email dipakai untuk login dan penugasan approval."><Input id="profile-email" type="email" value={form.email || ""} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="profile-email" /></FieldRow>
              <FieldRow label="Nomor Telepon" htmlFor="profile-phone"><Input id="profile-phone" value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="Contoh: +62 812-3456-7890" data-testid="profile-phone" /></FieldRow>
              <div className="grid gap-3 rounded-lg border bg-muted/30 p-3 text-sm sm:grid-cols-2" data-testid="profile-readonly">
                <div><div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Role</div><div className="font-medium" data-testid="profile-role">{ROLE_LABEL[user?.role] || user?.role || "-"}</div></div>
                <div><div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Hak Akses &amp; Divisi</div><div className="text-muted-foreground">Dikelola Admin melalui User Management</div></div>
              </div>
              <Button type="submit" disabled={!dirty || saving} data-testid="profile-save"><Save className="mr-2 h-4 w-4" />{saving ? "Menyimpan..." : "Simpan Profil"}</Button>
            </form>}
        </CardContent></Card>

        <Card><CardContent className="space-y-5 p-6">
          <div className="flex items-center gap-2 font-head font-semibold"><ShieldCheck className="h-4 w-4 text-primary" />Keamanan / Ubah Password</div>
          <form onSubmit={changePassword} className="space-y-4">
            <FieldRow label="Password Saat Ini" htmlFor="pw-current"><PasswordInput id="pw-current" value={pw.current_password} onChange={(v) => setPw({ ...pw, current_password: v })} testid="profile-pw-current" autoComplete="current-password" /></FieldRow>
            <FieldRow label="Password Baru" htmlFor="pw-new" hint="Minimal 8 karakter dan berbeda dari password saat ini."><PasswordInput id="pw-new" value={pw.new_password} onChange={(v) => setPw({ ...pw, new_password: v })} testid="profile-pw-new" autoComplete="new-password" /></FieldRow>
            <FieldRow label="Konfirmasi Password Baru" htmlFor="pw-confirm"><PasswordInput id="pw-confirm" value={pw.confirm_password} onChange={(v) => setPw({ ...pw, confirm_password: v })} testid="profile-pw-confirm" autoComplete="new-password" /></FieldRow>
            {pwErr && <p role="alert" className="text-sm font-medium text-destructive" data-testid="profile-pw-error">{pwErr}</p>}
            <p className="text-xs text-muted-foreground">Setelah password diganti, sesi di perangkat lain otomatis berakhir. Sesi ini tetap aktif.</p>
            <Button type="submit" disabled={pwSaving} data-testid="profile-pw-submit"><KeyRound className="mr-2 h-4 w-4" />{pwSaving ? "Memproses..." : "Ubah Password"}</Button>
          </form>
        </CardContent></Card>
      </div>
    </div>
  );
}
