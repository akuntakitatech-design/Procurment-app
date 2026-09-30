import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Check, Loader2, ShieldCheck, KeyRound, Building2 } from "lucide-react";

const fmtDate = (value) => {
  if (!value) return "-";
  try {
    return new Intl.DateTimeFormat("id-ID", { dateStyle: "full", timeStyle: "short" }).format(new Date(value));
  } catch {
    return value;
  }
};

export default function ActivateTenant() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError("");
    api.get(`/platform/activation/${encodeURIComponent(token || "")}`)
      .then((r) => setInfo(r.data))
      .catch((e) => setError(apiError(e.response?.data?.detail) || e.message))
      .finally(() => setLoading(false));
  }, [token]);

  const activate = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) { setError("Password minimal 8 karakter."); return; }
    if (password !== confirmPassword) { setError("Konfirmasi password belum sama."); return; }
    setSaving(true);
    try {
      const r = await api.post(`/platform/activation/${encodeURIComponent(token || "")}/accept`, { password });
      setDone(r.data || {});
    } catch (e) {
      setError(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="min-h-screen bg-slate-50 flex items-center justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 mr-2 animate-spin" />Memeriksa token aktivasi...</div>;
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border bg-white shadow-sm overflow-hidden" data-testid="activation-card">
          <div className="p-6 bg-slate-950 text-white">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-white/10 flex items-center justify-center"><ShieldCheck className="h-5 w-5" /></div>
              <div>
                <div className="font-head font-bold">Aktivasi Tenant Admin</div>
                <div className="text-xs text-slate-300">KelolaKita Procurement</div>
              </div>
            </div>
          </div>

          {done ? (
            <div className="p-6 text-center space-y-4" data-testid="activation-done">
              <div className="h-14 w-14 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center mx-auto"><Check className="h-7 w-7" /></div>
              <div className="font-head font-bold text-lg">Akun berhasil diaktifkan</div>
              <p className="text-sm text-muted-foreground">{done.message || "Silakan masuk menggunakan email dan password baru."}</p>
              <div className="rounded-xl bg-slate-50 p-3 text-sm">
                <div><span className="text-muted-foreground">Kode Tenant:</span> <b>{done.tenant_code}</b></div>
                <div className="truncate"><span className="text-muted-foreground">Email:</span> <b>{done.email}</b></div>
              </div>
              <Button asChild className="w-full"><Link to="/login" data-testid="go-login-btn">Masuk sekarang</Link></Button>
            </div>
          ) : error && !info ? (
            <div className="p-6 text-center space-y-4">
              <div className="text-sm text-destructive">{error}</div>
              <Button asChild variant="outline" className="w-full"><Link to="/login">Kembali ke Login</Link></Button>
            </div>
          ) : (
            <form onSubmit={activate} className="p-6 space-y-4">
              <div className="rounded-xl border p-4 bg-slate-50 text-sm space-y-1">
                <div className="flex items-center gap-2 font-semibold"><Building2 className="h-4 w-4" />{info?.tenant_name}</div>
                <div className="text-xs text-muted-foreground">Kode Tenant: <b>{info?.tenant_code}</b></div>
                <div className="text-xs text-muted-foreground">Admin: {info?.name} · {info?.email_hint}</div>
                {info?.expires_at && <div className="text-xs text-muted-foreground">Berlaku sampai {fmtDate(info.expires_at)}</div>}
              </div>
              <div className="space-y-2">
                <Label>Password Baru</Label>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Minimal 8 karakter" data-testid="activation-password" required />
              </div>
              <div className="space-y-2">
                <Label>Konfirmasi Password</Label>
                <Input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Ulangi password" data-testid="activation-confirm" required />
              </div>
              {error && <div className="text-sm text-destructive">{error}</div>}
              <Button type="submit" className="w-full" disabled={saving} data-testid="activation-submit">
                {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <KeyRound className="h-4 w-4 mr-2" />}Aktifkan & Set Password
              </Button>
            </form>
          )}
        </div>
        <p className="text-center text-xs text-muted-foreground mt-4">Setelah aktivasi, akun Anda menjadi Tenant Admin pertama dan tenant berstatus Active.</p>
      </div>
    </div>
  );
}
