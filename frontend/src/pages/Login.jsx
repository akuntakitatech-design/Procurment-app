import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { API, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Boxes,
  Loader2,
  ClipboardList,
  Warehouse,
  ShoppingCart,
  PackageCheck,
  ShieldCheck,
  Mail,
  LockKeyhole,
  Eye,
  EyeOff,
  ArrowRight,
} from "lucide-react";

export default function Login() {
  const { login, user } = useAuth();
  const nav = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [brand, setBrand] = useState({
    name: "KelolaKita Procurement",
    subtitle: "Procurement • Warehouse • Inventory",
    logo_available: false,
    logo_version: null,
  });

  useEffect(() => {
    if (user) {
      nav(user?.is_platform_admin ? "/platform" : "/", { replace: true });
    }
  }, [user, nav]);

  useEffect(() => {
    api.get("/platform-branding")
      .then((r) => {
        setBrand(r.data || {});
        document.title = r.data?.name
          ? `${r.data.name} | Procurement`
          : "Procurement";
      })
      .catch(() => {
        document.title = "Procurement";
      });
  }, []);

  const logoSrc = brand.logo_available
    ? `${API}/platform-branding/logo?v=${encodeURIComponent(brand.logo_version || "1")}`
    : null;

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);

    try {
      const logged = await login(email, password);
      nav(logged?.is_platform_admin ? "/platform" : "/", { replace: true });
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    }

    setLoading(false);
  };

  const flows = [
    {
      no: "01",
      stage: "REQUEST",
      team: "Tim Lapangan",
      trx: "MRO",
      desc: "Permintaan Barang",
      icon: ClipboardList,
    },
    {
      no: "02",
      stage: "VERIFY",
      team: "Tim Warehouse",
      trx: "RO",
      desc: "Verifikasi Kebutuhan",
      icon: Warehouse,
    },
    {
      no: "03",
      stage: "PROCURE",
      team: "Tim Purchasing",
      trx: "PO",
      desc: "Proses Pengadaan",
      icon: ShoppingCart,
    },
    {
      no: "04",
      stage: "RECEIVE",
      team: "Tim Warehouse",
      trx: "DO • MI",
      desc: "Penerimaan & Stok",
      icon: PackageCheck,
    },
  ];

  return (
    <div className="min-h-screen bg-[#f6f8fb] lg:grid lg:grid-cols-[56%_44%]">

      <section className="relative hidden min-h-screen overflow-hidden bg-[#12375e] text-white lg:flex lg:flex-col">

        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle at 85% 18%, rgba(74,144,203,.24), transparent 35%), linear-gradient(135deg, #102f51 0%, #184a77 100%)",
          }}
        />

        <div
          className="absolute inset-0 opacity-[0.055]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.8) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.8) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
          }}
        />

        <div className="absolute right-[-120px] top-[150px] h-[520px] w-[520px] rounded-full border border-white/[0.07]" />
        <div className="absolute right-[80px] top-[260px] h-[330px] w-[330px] rounded-full border border-white/[0.05]" />

        <div className="relative z-10 flex h-full flex-col px-14 py-11 xl:px-16">

          <div className="flex items-center justify-between">
            <div className="flex items-center">
              {logoSrc ? (
                <div className="flex h-[82px] w-[270px] items-center justify-center rounded-2xl border border-white/80 bg-white px-6 py-3 shadow-[0_12px_30px_rgba(0,0,0,0.16)]">
                  <img
                    src={logoSrc}
                    alt={brand.name || "KelolaKita Procurement"}
                    className="max-h-[62px] max-w-[230px] object-contain"
                  />
                </div>
              ) : (
                <div className="flex items-center gap-4">
                  <Boxes className="h-9 w-9" />
                  <div>
                    <div className="text-xl font-semibold">KelolaKita</div>
                    <div className="text-sm text-white/70">Procurement</div>
                  </div>
                </div>
              )}
            </div>

            <div className="hidden text-right xl:block">
              <div className="text-[10px] font-semibold tracking-[0.2em] text-white/40">
                PEOPLE • PROCESS • CONTROL
              </div>
              <div className="mt-1 text-xs text-white/60">
                Operasional yang lebih terkontrol
              </div>
            </div>
          </div>

          <div className="mt-24 max-w-[720px]">
            <div className="mb-5 text-[11px] font-semibold tracking-[0.34em] text-[#a9c8e5]">
              PROCUREMENT • WAREHOUSE • INVENTORY
            </div>

            <h1 className="font-head text-[46px] font-semibold leading-[1.13] tracking-[-0.035em] xl:text-[52px]">
              Kelola Pengadaan
              <br />
              Lebih Mudah, Terintegrasi
            </h1>

            <p className="mt-5 max-w-[590px] text-[16px] leading-7 text-white/68">
              Dari permintaan hingga barang diterima, semua terkontrol dalam
              satu sistem.
            </p>

            <div className="mt-10 grid grid-cols-4 gap-3">
              {flows.map((flow, index) => {
                const Icon = flow.icon;

                return (
                  <div key={flow.no} className="relative">
                    <div className="rounded-xl border border-white/10 bg-white/[0.065] p-4 backdrop-blur-sm">
                      <div className="flex items-start justify-between">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10">
                          <Icon className="h-[18px] w-[18px] text-white/85" />
                        </div>

                        <span className="text-[10px] font-semibold text-white/30">
                          {flow.no}
                        </span>
                      </div>

                      <div className="mt-4 text-[10px] font-semibold tracking-[0.16em] text-[#a8c8e5]">
                        {flow.stage}
                      </div>

                      <div className="mt-1 text-[13px] font-semibold text-white">
                        {flow.team}
                      </div>

                      <div className="mt-3 inline-flex rounded-md bg-white/10 px-2.5 py-1 text-[12px] font-bold tracking-wide text-white">
                        {flow.trx}
                      </div>

                      <div className="mt-2 min-h-[32px] text-[11px] leading-4 text-white/48">
                        {flow.desc}
                      </div>
                    </div>

                    {index < flows.length - 1 && (
                      <div className="absolute -right-[11px] top-[64px] z-20 flex h-5 w-5 items-center justify-center rounded-full bg-[#173f69]">
                        <ArrowRight className="h-3 w-3 text-white/40" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mt-8 grid grid-cols-3 gap-7 border-t border-white/10 pt-7">
              <div>
                <div className="text-[13px] font-semibold">Efisiensi Proses</div>
                <div className="mt-1 text-[11px] text-white/45">
                  Lebih cepat dan terdokumentasi
                </div>
              </div>

              <div>
                <div className="text-[13px] font-semibold">Kontrol Lebih Baik</div>
                <div className="mt-1 text-[11px] text-white/45">
                  Transparan dan terukur
                </div>
              </div>

              <div>
                <div className="text-[13px] font-semibold">Kolaborasi Tim</div>
                <div className="mt-1 text-[11px] text-white/45">
                  Satu alur antar divisi
                </div>
              </div>
            </div>
          </div>

          <div className="mt-auto flex items-center justify-between pt-8 text-[10px] text-white/35">
            <span>© 2026 KelolaKita Procurement</span>
            <span>Kelola Bersama. Tumbuh Bersama.</span>
          </div>
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-6 py-10 lg:px-12">
        <div className="w-full max-w-[500px]">

          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#163d66]">
              <Boxes className="h-6 w-6 text-white" />
            </div>

            <div>
              <div className="font-head text-lg font-semibold">
                KelolaKita Procurement
              </div>
              <div className="text-xs text-slate-500">
                Procurement • Warehouse • Inventory
              </div>
            </div>
          </div>

          <div className="rounded-[22px] border border-slate-200/80 bg-white px-10 py-10 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">

            <div className="mb-8">
              <div className="mb-7 flex justify-center">
                {logoSrc ? (
                  <div className="flex h-[86px] w-[250px] items-center justify-center rounded-2xl border border-slate-200 bg-white px-5 py-3 shadow-sm">
                    <img
                      src={logoSrc}
                      alt={brand.name || "KelolaKita Procurement"}
                      className="max-h-[64px] max-w-[215px] object-contain"
                    />
                  </div>
                ) : (
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#eef4fa]">
                    <Boxes className="h-7 w-7 text-[#17456f]" strokeWidth={1.8} />
                  </div>
                )}
              </div>

              <h2 className="font-head text-[30px] font-semibold tracking-[-0.025em] text-slate-900">
                Selamat datang kembali
              </h2>

              <p className="mt-2 text-sm text-slate-500">
                Masuk untuk mengakses sistem KelolaKita Procurement.
              </p>
            </div>

            {err && (
              <div
                className="mb-5 rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600"
                data-testid="login-error"
              >
                {err}
              </div>
            )}

            <form onSubmit={submit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="email" className="text-[13px] font-medium text-slate-700">
                  Email
                </Label>

                <div className="relative">
                  <Mail className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />

                  <Input
                    id="email"
                    type="email"
                    placeholder="Masukkan email Anda"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    data-testid="login-email"
                    autoComplete="username"
                    className="h-12 rounded-xl border-slate-200 bg-[#fbfcfd] pl-10 pr-4 text-sm focus-visible:ring-[#17456f]"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-[13px] font-medium text-slate-700">
                  Password
                </Label>

                <div className="relative">
                  <LockKeyhole className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />

                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Masukkan password Anda"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    data-testid="login-password"
                    autoComplete="current-password"
                    className="h-12 rounded-xl border-slate-200 bg-[#fbfcfd] pl-10 pr-11 text-sm focus-visible:ring-[#17456f]"
                  />

                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 transition hover:text-slate-700"
                    aria-label={showPassword ? "Sembunyikan password" : "Tampilkan password"}
                  >
                    {showPassword ? (
                      <EyeOff className="h-[18px] w-[18px]" />
                    ) : (
                      <Eye className="h-[18px] w-[18px]" />
                    )}
                  </button>
                </div>
              </div>

              <Button
                type="submit"
                disabled={loading}
                data-testid="login-submit"
                className="mt-2 h-12 w-full rounded-xl bg-[#17456f] text-sm font-semibold text-white shadow-none hover:bg-[#10385e]"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Memproses...
                  </>
                ) : (
                  <>
                    Masuk
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </form>

            <div className="mt-7 flex items-center justify-center gap-2 border-t border-slate-100 pt-6 text-[11px] text-slate-400">
              <ShieldCheck className="h-4 w-4 text-[#17456f]/60" />
              <span>Aman & Terpercaya</span>
              <span className="mx-2 text-slate-200">•</span>
              <span>Siap Digunakan</span>
            </div>
          </div>

          <div className="mt-5 text-center text-[11px] text-slate-400">
            KelolaKita Procurement • Procurement Management System
          </div>
        </div>
      </section>
    </div>
  );
}
