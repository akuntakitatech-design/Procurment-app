import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Copy, Loader2, RefreshCw, Save, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

const fmtDate = (value) => {
  if (!value) return "-";
  try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
};

const labels = {
  pending: "Menunggu",
  used: "Dipakai",
  expired: "Kedaluwarsa",
  cancelled: "Dibatalkan",
  activating: "Diproses",
};

export default function PlatformInvitations({ tenantId }) {
  const [rows, setRows] = useState([]);
  const [tenant, setTenant] = useState(null);
  const [accessDays, setAccessDays] = useState("3");
  const [loading, setLoading] = useState(true);
  const [savingAccess, setSavingAccess] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    if (!tenantId) return;
    setLoading(true);
    setError("");
    try {
      const [inviteRes, tenantRes] = await Promise.all([
        api.get(`/platform/tenants/${tenantId}/invitations`),
        api.get(`/platform/tenants/${tenantId}`),
      ]);
      setRows(inviteRes.data || []);
      setTenant(tenantRes.data || null);
      setAccessDays(String(tenantRes.data?.subscription?.post_expiry_access_days ?? 3));
    } catch (e) {
      setError(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [tenantId]);

  const saveAccessDays = async () => {
    const days = Number(accessDays);
    if (!Number.isInteger(days) || days < 0 || days > 365) {
      toast.error("Batas akses harus 0 sampai 365 hari");
      return;
    }
    setSavingAccess(true);
    try {
      await api.patch(`/platform/tenants/${tenantId}/subscription-dates`, {
        trial_ends_at: tenant?.subscription?.trial_ends_at || "",
        ends_at: tenant?.subscription?.ends_at || "",
        post_expiry_access_days: days,
      });
      toast.success(`Akses setelah jatuh tempo diset ${days} hari`);
      await load();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setSavingAccess(false);
    }
  };

  const copyLink = async (row) => {
    const url = `${window.location.origin}/invite/${row.code}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link undangan disalin");
    } catch {
      window.prompt("Salin link undangan ini:", url);
    }
  };

  if (loading) return <div className="p-8 flex items-center justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 mr-2 animate-spin" />Memuat kontrol tenant...</div>;

  return (
    <div className="p-5 space-y-5 max-h-[calc(100vh-18rem)] overflow-auto">
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldAlert className="h-5 w-5 text-amber-700 mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-sm text-amber-950">Akses Setelah Masa Aktif Berakhir</div>
            <p className="text-xs text-amber-900/80 mt-1 leading-5">
              Berlaku sama untuk Trial dan langganan berbayar. Selama periode ini tenant hanya dapat melihat data, laporan, stok, print dan export. Setelah periode selesai, workspace terkunci penuh.
            </p>
            <div className="mt-4 flex items-end gap-2 max-w-xs">
              <div className="space-y-2 flex-1">
                <Label className="text-xs">Durasi akses terbatas</Label>
                <div className="flex items-center gap-2">
                  <Input type="number" min="0" max="365" value={accessDays} onChange={(e) => setAccessDays(e.target.value)} />
                  <span className="text-xs text-amber-900">hari</span>
                </div>
              </div>
              <Button size="sm" onClick={saveAccessDays} disabled={savingAccess}>
                {savingAccess ? <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-2" />}Simpan
              </Button>
            </div>
            <p className="text-[11px] text-amber-900/70 mt-2">Default 3 hari. Isi 0 jika ingin langsung terkunci pada saat masa aktif berakhir.</p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">Monitoring kode undangan tenant. Pembuatan dan pembatalan dilakukan oleh Admin tenant.</p>
        <Button size="sm" variant="ghost" onClick={load}><RefreshCw className="h-3.5 w-3.5 mr-2" />Refresh</Button>
      </div>
      {error && <div className="rounded-lg bg-destructive/10 text-destructive px-3 py-2 text-xs">{error}</div>}
      {!error && rows.length === 0 && <div className="text-sm text-muted-foreground text-center py-8">Belum ada undangan user.</div>}
      {rows.map((row) => (
        <div key={row.id} className="rounded-xl border p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold text-sm truncate">{row.name || row.email}</div>
              <div className="text-xs text-muted-foreground truncate mt-1">{row.email}</div>
            </div>
            <span className="text-[10px] rounded-full border px-2 py-0.5 whitespace-nowrap">{labels[row.status] || row.status || "-"}</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            <span className="font-mono rounded-md bg-slate-100 px-2 py-1">{row.code}</span>
            <span className="rounded-md bg-slate-100 px-2 py-1">Role: {row.role || "-"}</span>
            <span className="rounded-md bg-slate-100 px-2 py-1">Dibuat: {fmtDate(row.created_at)}</span>
            <span className="rounded-md bg-slate-100 px-2 py-1">Berakhir: {fmtDate(row.expires_at)}</span>
          </div>
          {row.status === "pending" && <Button size="sm" variant="outline" className="mt-3" onClick={() => copyLink(row)}><Copy className="h-3.5 w-3.5 mr-2" />Salin Link</Button>}
        </div>
      ))}
    </div>
  );
}
