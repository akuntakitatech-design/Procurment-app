import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { API, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Boxes, Loader2 } from "lucide-react";

export default function Login() {
  const { login, user } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [brand, setBrand] = useState({ name: "App Proc", subtitle: "Procurement & Inventory", logo_available: false, logo_version: null });

  useEffect(() => { if (user) nav("/"); }, [user, nav]);
  useEffect(() => {
    api.get("/branding").then((r) => {
      setBrand(r.data || {});
      document.title = r.data?.name ? `App Proc | ${r.data.name}` : "App Proc";
    }).catch(() => { document.title = "App Proc"; });
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setLoading(true);
    try { await login(email, password); nav("/"); }
    catch (e) { setErr(apiError(e.response?.data?.detail) || e.message); }
    setLoading(false);
  };

  const logoSrc = brand.logo_available ? `${API}/company/logo?v=${encodeURIComponent(brand.logo_version || "1")}` : null;

  const BrandMark = ({ compact = false }) => (
    <div className="flex items-center gap-3 min-w-0">
      {logoSrc ? (
        <div className={`${compact ? "h-9 w-9" : "h-10 w-10"} shrink-0 overflow-hidden rounded-xl bg-white p-1`}><img src={logoSrc} alt="Logo perusahaan" className="h-full w-full object-contain" /></div>
      ) : (
        <div className={`${compact ? "h-9 w-9" : "h-10 w-10"} shrink-0 rounded-xl bg-white/15 flex items-center justify-center`}><Boxes className={compact ? "h-5 w-5" : "h-6 w-6"} /></div>
      )}
      <div className="min-w-0">
        <div className={`${compact ? "text-lg text-foreground" : "text-xl"} truncate font-head font-bold`}>{brand.name || "App Proc"}</div>
        <div className={`${compact ? "text-muted-foreground" : "text-primary-foreground/70"} truncate text-[11px]`}>{brand.subtitle || "Procurement & Inventory"}</div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      <div className="hidden lg:flex flex-col justify-between p-12 bg-primary text-primary-foreground relative overflow-hidden">
        <BrandMark />
        <div className="relative z-10">
          <h1 className="font-head text-4xl font-extrabold leading-tight">Procurement, Warehouse & Inventory Control System</h1>
          <p className="mt-4 text-primary-foreground/80 max-w-md">Traceability penuh dari MRO → RO → PO → DO → MI. Kendalikan seluruh siklus kebutuhan dan pergerakan barang dalam satu sistem.</p>
          <div className="mt-8 flex flex-wrap gap-2 font-mono text-xs">
            {["MRO", "RO", "PO", "DO", "MI"].map((x, i) => (
              <span key={x} className="flex items-center gap-2">
                <span className="rounded-md bg-white/15 px-3 py-1.5">{x}</span>
                {i < 4 && <span className="opacity-60">→</span>}
              </span>
            ))}
          </div>
        </div>
        <div className="text-xs text-primary-foreground/60">© 2026 App Proc</div>
      </div>

      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5">
          <div className="lg:hidden mb-4"><BrandMark compact /></div>
          <div>
            <h2 className="font-head text-2xl font-bold">Masuk ke akun Anda</h2>
            <p className="text-sm text-muted-foreground mt-1">Silakan login untuk melanjutkan</p>
          </div>
          {err && <div className="rounded-md bg-destructive/10 text-destructive text-sm px-3 py-2" data-testid="login-error">{err}</div>}
          <div className="space-y-2">
            <Label>Email</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required data-testid="login-email" autoComplete="username" />
          </div>
          <div className="space-y-2">
            <Label>Password</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required data-testid="login-password" autoComplete="current-password" />
          </div>
          <Button type="submit" className="w-full" disabled={loading} data-testid="login-submit">
            {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />} Masuk
          </Button>
        </form>
      </div>
    </div>
  );
}
