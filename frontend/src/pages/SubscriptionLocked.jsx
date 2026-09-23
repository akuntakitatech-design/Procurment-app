import { LockKeyhole, LogOut, RefreshCw, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

const fmtDate = (value) => {
  if (!value) return "-";
  try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "long", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
};

export default function SubscriptionLocked() {
  const { user, subscription, logout, refreshSubscription } = useAuth();
  const suspended = subscription?.status === "suspended";

  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center p-5">
      <div className="w-full max-w-xl rounded-3xl border bg-white shadow-xl overflow-hidden">
        <div className="bg-slate-950 text-white p-7 sm:p-9">
          <div className="h-12 w-12 rounded-2xl bg-white/10 flex items-center justify-center mb-5">
            {suspended ? <ShieldAlert className="h-6 w-6" /> : <LockKeyhole className="h-6 w-6" />}
          </div>
          <div className="text-xs uppercase tracking-[0.18em] text-slate-400 font-semibold">Workspace</div>
          <h1 className="font-head text-2xl sm:text-3xl font-bold mt-2">
            {suspended ? "Workspace Ditangguhkan" : "Langganan Berakhir"}
          </h1>
          <p className="text-sm text-slate-300 mt-3 leading-6">
            {subscription?.message || "Akses workspace sedang dikunci. Hubungi administrator platform untuk mengaktifkan kembali langganan."}
          </p>
        </div>

        <div className="p-7 sm:p-9 space-y-5">
          <div className="grid sm:grid-cols-2 gap-3 text-sm">
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="text-xs text-muted-foreground">Tenant</div>
              <div className="font-semibold mt-1">{subscription?.tenant_name || "-"}</div>
              <div className="font-mono text-xs mt-1 text-muted-foreground">{subscription?.tenant_code || "-"}</div>
            </div>
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="text-xs text-muted-foreground">User</div>
              <div className="font-semibold mt-1 break-all">{user?.email || "-"}</div>
            </div>
          </div>

          <div className="rounded-2xl border p-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Status akses</span>
              <span className="font-semibold">Terkunci</span>
            </div>
            {subscription?.post_expiry_access_ends_at && (
              <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t">
                <span className="text-muted-foreground">Akses terbatas berakhir</span>
                <span className="font-semibold text-right">{fmtDate(subscription.post_expiry_access_ends_at)}</span>
              </div>
            )}
          </div>

          <div className="rounded-2xl bg-amber-50 border border-amber-200 p-4 text-sm text-amber-900 leading-6">
            Data perusahaan tidak dihapus. Setelah langganan diperpanjang oleh Platform Admin, akses aplikasi akan kembali normal.
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            <Button className="w-full rounded-xl" onClick={refreshSubscription}>
              <RefreshCw className="h-4 w-4 mr-2" />Cek Status Langganan
            </Button>
            <Button variant="outline" className="w-full rounded-xl" onClick={logout}>
              <LogOut className="h-4 w-4 mr-2" />Keluar
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
