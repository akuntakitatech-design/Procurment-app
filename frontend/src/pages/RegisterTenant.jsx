import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Building2, Check, KeyRound, Loader2, ShieldCheck, Users, Warehouse } from "lucide-react";

const emptyForm = {
  company_name: "",
  pic_name: "",
  email: "",
  whatsapp: "",
  workspace_slug: "",
  plan_code: "starter",
  password: "",
  address: "",
  terms_accepted: false,
};

const fmtLimit = (value) => (value == null ? "Tanpa batas" : value);

export default function RegisterTenant() {
  const [config, setConfig] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    api.get("/saas/public-config")
      .then((r) => {
        setConfig(r.data || {});
        const plans = r.data?.plans || [];
        if (plans.length && !plans.some((p) => p.code === form.plan_code)) {
          setForm((x) => ({ ...x, plan_code: plans[0].code }));
        }
      })
      .catch((e) => setErr(apiError(e.response?.data?.detail)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const plans = useMemo(() => config?.plans || [], [config]);
  const set = (key, value) => setForm((x) => ({ ...x, [key]: value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      const payload = { ...form, workspace_slug: form.workspace_slug || null };
      const r = await api.post("/saas/register", payload);
      setResult(r.data);
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setLoading(false);
    }
  };

  if (!config && !err) {
    return <div className="min-h-screen flex items-center justify-center bg-background text-muted-foreground">Memuat formulir registrasi...</div>;
  }

  if (result) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-2xl border bg-white p-8 shadow-sm">
          <div className="h-12 w-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mb-5"><Check className="h-6 w-6" /></div>
          <h1 className="text-2xl font-bold font-head">Workspace berhasil dibuat</h1>
          <p className="text-sm text-muted-foreground mt-2">Akun Owner dan perusahaan pertama sudah disiapkan. Simpan Kode Tenant sebagai identitas permanen untuk kebutuhan support dan administrasi.</p>

          {result.tenant_code && (
            <div className="mt-6 rounded-2xl border border-sky-200 bg-sky-50 p-5">
              <div className="flex items-center gap-2 text-sky-700 text-xs font-semibold uppercase tracking-[0.14em]"><KeyRound className="h-4 w-4" /> Kode Tenant</div>
              <div className="font-mono text-2xl font-bold text-slate-950 mt-2 tracking-wider">{result.tenant_code}</div>
              <p className="text-xs text-slate-600 mt-2">Kode ini tidak berubah walaupun nama perusahaan, email Owner, atau workspace diperbarui. Kode ini bukan password.</p>
            </div>
          )}

          <div className="mt-5 rounded-xl border bg-slate-50 p-4 text-sm space-y-2">
            <div className="flex justify-between gap-4"><span className="text-muted-foreground">Perusahaan</span><span className="font-medium text-right">{result.company_name}</span></div>
            <div className="flex justify-between gap-4"><span className="text-muted-foreground">Workspace</span><span className="font-mono text-xs">{result.workspace}</span></div>
            <div className="flex justify-between gap-4"><span className="text-muted-foreground">Paket</span><span className="font-medium">{result.plan?.name}</span></div>
            <div className="flex justify-between gap-4"><span className="text-muted-foreground">Owner</span><span className="font-medium text-right">{result.owner_email}</span></div>
          </div>
          <Button asChild className="w-full mt-6"><Link to="/login">Masuk ke Aplikasi</Link></Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-6xl mx-auto grid lg:grid-cols-[0.8fr_1.2fr] min-h-screen">
        <aside className="hidden lg:flex flex-col justify-between bg-slate-950 text-white p-10 xl:p-12">
          <div>
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-white/10 flex items-center justify-center"><Building2 className="h-5 w-5" /></div>
              <div><div className="font-head font-bold">App Proc</div><div className="text-xs text-slate-400">Procurement & Inventory</div></div>
            </div>
            <div className="mt-20 max-w-md">
              <div className="text-xs tracking-[0.2em] uppercase text-sky-300 font-semibold">Workspace Baru</div>
              <h1 className="font-head text-4xl font-extrabold leading-tight mt-4">Mulai sistem procurement perusahaan Anda.</h1>
              <p className="mt-4 text-slate-400 leading-7">Satu workspace untuk pembelian, gudang, persediaan, approval, dan pelaporan. Data setiap perusahaan dipisahkan per tenant.</p>
            </div>
          </div>
          <div className="space-y-3 text-sm text-slate-300">
            <div className="flex gap-3"><ShieldCheck className="h-5 w-5 text-sky-300" /> Data tenant terisolasi</div>
            <div className="flex gap-3"><Users className="h-5 w-5 text-sky-300" /> Pengguna sesuai paket</div>
            <div className="flex gap-3"><Warehouse className="h-5 w-5 text-sky-300" /> Gudang dan divisi fleksibel</div>
          </div>
        </aside>

        <main className="p-5 sm:p-8 lg:p-12 flex items-center">
          <div className="w-full max-w-3xl mx-auto">
            <div className="flex items-center justify-between gap-4 mb-8">
              <div>
                <h2 className="text-2xl sm:text-3xl font-bold font-head">Daftarkan perusahaan</h2>
                <p className="text-sm text-muted-foreground mt-1">Buat workspace dan akun Owner dalam satu proses.</p>
              </div>
              <Button variant="outline" asChild><Link to="/login">Sudah punya akun</Link></Button>
            </div>

            {!config?.registration_enabled ? (
              <div className="rounded-2xl border bg-white p-8 shadow-sm">
                <h3 className="font-semibold text-lg">Registrasi belum dibuka</h3>
                <p className="text-sm text-muted-foreground mt-2">Pendaftaran workspace baru saat ini masih dinonaktifkan oleh administrator platform.</p>
                <Button asChild className="mt-5"><Link to="/login">Kembali ke Login</Link></Button>
              </div>
            ) : (
              <form onSubmit={submit} className="rounded-2xl border bg-white p-5 sm:p-7 shadow-sm space-y-7">
                {err && <div className="rounded-xl bg-destructive/10 text-destructive px-4 py-3 text-sm">{err}</div>}

                <section>
                  <div className="font-semibold mb-4">1. Data perusahaan</div>
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div className="space-y-2 sm:col-span-2"><Label>Nama Perusahaan</Label><Input value={form.company_name} onChange={(e) => set("company_name", e.target.value)} required /></div>
                    <div className="space-y-2"><Label>Nama PIC / Owner</Label><Input value={form.pic_name} onChange={(e) => set("pic_name", e.target.value)} required /></div>
                    <div className="space-y-2"><Label>WhatsApp</Label><Input value={form.whatsapp} onChange={(e) => set("whatsapp", e.target.value)} required /></div>
                    <div className="space-y-2"><Label>Email Owner</Label><Input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} required /></div>
                    <div className="space-y-2"><Label>Nama Workspace</Label><Input value={form.workspace_slug} onChange={(e) => set("workspace_slug", e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} placeholder="contoh-perusahaan" /></div>
                    <div className="space-y-2 sm:col-span-2"><Label>Alamat</Label><Input value={form.address} onChange={(e) => set("address", e.target.value)} /></div>
                  </div>
                </section>

                <section>
                  <div className="font-semibold mb-4">2. Pilih paket</div>
                  <div className="grid md:grid-cols-2 gap-3">
                    {plans.map((p) => {
                      const active = form.plan_code === p.code;
                      return (
                        <button type="button" key={p.code} onClick={() => set("plan_code", p.code)}
                          className={`text-left rounded-xl border p-4 transition ${active ? "border-primary ring-2 ring-primary/10 bg-primary/[0.03]" : "hover:border-slate-400"}`}>
                          <div className="flex items-center justify-between gap-3"><span className="font-semibold">{p.name}</span>{active && <Check className="h-4 w-4 text-primary" />}</div>
                          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                            <span>User: <b className="text-foreground">{fmtLimit(p.limits?.max_users)}</b></span>
                            <span>Gudang: <b className="text-foreground">{fmtLimit(p.limits?.max_warehouses)}</b></span>
                            <span>Divisi: <b className="text-foreground">{fmtLimit(p.limits?.max_divisions)}</b></span>
                            <span>Perusahaan: <b className="text-foreground">{fmtLimit(p.limits?.max_companies)}</b></span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-xs text-muted-foreground mt-3">Masa trial: {config?.trial_days || 0} hari.</p>
                </section>

                <section>
                  <div className="font-semibold mb-4">3. Keamanan akun</div>
                  <div className="space-y-2"><Label>Password Owner</Label><Input type="password" minLength={8} value={form.password} onChange={(e) => set("password", e.target.value)} required autoComplete="new-password" /></div>
                  <label className="mt-4 flex gap-3 text-sm cursor-pointer">
                    <input type="checkbox" checked={form.terms_accepted} onChange={(e) => set("terms_accepted", e.target.checked)} className="mt-1" />
                    <span>Saya menyetujui syarat penggunaan dan kebijakan layanan.</span>
                  </label>
                </section>

                <Button type="submit" className="w-full h-11" disabled={loading || !form.terms_accepted}>
                  {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />} Buat Workspace
                </Button>
              </form>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
