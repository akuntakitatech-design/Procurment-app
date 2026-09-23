import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Check, Loader2, ShieldCheck, UserPlus } from "lucide-react";

const fmtDate = (value) => {
  if (!value) return "-";
  try {
    return new Intl.DateTimeFormat("id-ID", { dateStyle: "full", timeStyle: "short" }).format(new Date(value));
  } catch {
    return value;
  }
};

export default function AcceptInvite() {
  const { code } = useParams();
  const [invite, setInvite] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError("");
    api.get(`/invitations/public/${encodeURIComponent(code || "")}`)
      .then((r) => setInvite(r.data))
      .catch((e) => setError(apiError(e.response?.data?.detail) || e.message))
      .finally(() => setLoading(false));
  }, [code]);

  const activate = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password minimal 8 karakter.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Konfirmasi password belum sama.");
      return;
    }
    setSaving(true);
    try {
      const r = await api.post(`/invitations/public/${encodeURIComponent(code || "")}/accept`, { password });
      setDone(r.data || {});
    } catch (e) {
      setError(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="min-h-screen bg-slate-50 flex items-center justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 mr-2 animate-spin" />Memeriksa undangan...</div>;
  }

  if (done) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-2xl border bg-white p-8 shadow-sm">
          <div className="h-12 w-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mb-5"><Check className="h-6 w-6" /></div>
          <h1 className="text-2xl font-bold font-head">Akun berhasil diaktifkan</h1>
          <p className="text-sm text-muted-foreground mt-2">Gunakan email undangan dan password yang baru dibuat untuk masuk ke aplikasi.</p>
          <div className="mt-6 rounded-xl border bg-slate-50 p-4 text-sm space-y-2">
            <div className="flex justify-between gap-4"><span className="text-muted-foreground">Kode Tenant</span><span className="font-mono font-semibold">{done.tenant_code || invite?.tenant_code || "-"}</span></div>
            <div className="flex justify-between gap-4"><span className="text-muted-foreground">Email</span><span className="font-medium text-right">{done.email || "Email undangan"}</span></div>
          </div>
          <Button asChild className="w-full mt-6"><Link to="/login">Masuk ke Aplikasi</Link></Button>
        </div>
      </div>
    );
  }

  if (!invite) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-2xl border bg-white p-8 shadow-sm">
          <ShieldCheck className="h-10 w-10 text-slate-400 mb-5" />
          <h1 className="text-xl font-bold">Undangan tidak dapat digunakan</h1>
          <p className="text-sm text-muted-foreground mt-2">{error || "Kode undangan tidak valid atau sudah tidak aktif."}</p>
          <Button asChild variant="outline" className="w-full mt-6"><Link to="/login">Kembali ke Login</Link></Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-5 sm:p-8">
      <div className="w-full max-w-xl rounded-2xl border bg-white shadow-sm overflow-hidden">
        <div className="bg-slate-950 text-white p-7">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-white/10 flex items-center justify-center"><UserPlus className="h-5 w-5" /></div>
            <div>
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Undangan User</div>
              <div className="font-head font-bold text-xl mt-1">{invite.tenant_name}</div>
            </div>
          </div>
          <div className="mt-5 inline-flex rounded-lg bg-white/10 px-3 py-2 font-mono text-sm">{invite.tenant_code}</div>
        </div>

        <form onSubmit={activate} className="p-7 space-y-6">
          {error && <div className="rounded-xl bg-destructive/10 text-destructive px-4 py-3 text-sm">{error}</div>}

          <div className="grid sm:grid-cols-2 gap-3 text-sm">
            <div className="rounded-xl bg-slate-50 p-4"><div className="text-xs text-muted-foreground">Nama</div><div className="font-semibold mt-1">{invite.name}</div></div>
            <div className="rounded-xl bg-slate-50 p-4"><div className="text-xs text-muted-foreground">Email</div><div className="font-semibold mt-1 break-all">{invite.email_hint}</div></div>
            <div className="rounded-xl bg-slate-50 p-4"><div className="text-xs text-muted-foreground">Role</div><div className="font-semibold capitalize mt-1">{invite.role}</div></div>
            <div className="rounded-xl bg-slate-50 p-4"><div className="text-xs text-muted-foreground">Berlaku sampai</div><div className="font-semibold mt-1">{fmtDate(invite.expires_at)}</div></div>
          </div>

          <div className="space-y-4">
            <div className="space-y-2"><Label>Password Baru</Label><Input type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required /></div>
            <div className="space-y-2"><Label>Ulangi Password</Label><Input type="password" minLength={8} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" required /></div>
          </div>

          <div className="rounded-xl border bg-slate-50 p-4 text-xs text-muted-foreground leading-5">
            Kode undangan hanya dapat digunakan satu kali. Setelah aktivasi berhasil, akun otomatis terhubung ke tenant dan hak akses yang ditentukan Admin.
          </div>

          <Button type="submit" className="w-full h-11" disabled={saving}>{saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Aktifkan Akun</Button>
        </form>
      </div>
    </div>
  );
}
