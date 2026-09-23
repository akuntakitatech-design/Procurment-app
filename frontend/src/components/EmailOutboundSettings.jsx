import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/DatePicker";
import { Mail, Send, Save, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";

const EMAIL_DEFAULTS = {
  enabled: true,
  provider: "gmail",
  host: "smtp.gmail.com",
  port: 587,
  username: "",
  from_email: "",
  from_name: "Procurement",
  security: "starttls",
  password_set: false,
  configured: false,
  ready: false,
};

export function EmailOutbound() {
  const [cfg, setCfg] = useState(EMAIL_DEFAULTS);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/settings/email_outbound");
      setCfg({ ...EMAIL_DEFAULTS, ...(r.data || {}) });
      if (!testTo && r.data?.from_email) setTestTo(r.data.from_email);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setProvider = (provider) => {
    setCfg((cur) => provider === "gmail"
      ? { ...cur, provider, host: "smtp.gmail.com", port: 587, security: "starttls", from_email: cur.from_email || cur.username || "" }
      : { ...cur, provider, host: cur.host === "smtp.gmail.com" ? "" : cur.host, port: cur.port || 587 });
  };

  const save = async () => {
    try {
      setSaving(true);
      const payload = {
        enabled: !!cfg.enabled,
        provider: cfg.provider,
        host: cfg.host || "",
        port: Number(cfg.port || 587),
        username: cfg.username || "",
        from_email: cfg.from_email || (cfg.provider === "gmail" ? cfg.username : ""),
        from_name: cfg.from_name || "Procurement",
        security: cfg.security || "starttls",
      };
      if (password) payload.password = password;
      const r = await api.put("/settings/email_outbound", payload);
      setCfg({ ...EMAIL_DEFAULTS, ...(r.data || {}) });
      setPassword("");
      if (!testTo && r.data?.from_email) setTestTo(r.data.from_email);
      toast.success("Pengaturan email outbound tersimpan");
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const sendTest = async () => {
    try {
      setTesting(true);
      const target = testTo || cfg.from_email || cfg.username;
      if (!target) return toast.error("Isi email tujuan tes");
      await api.post("/settings/email_outbound/test", { to: target });
      toast.success(`Email tes berhasil dikirim ke ${target}`);
      await load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setTesting(false); }
  };

  const statusText = !cfg.enabled ? "Nonaktif" : cfg.ready ? "Siap digunakan" : "Belum lengkap";
  return <div className="space-y-4">
    <Card><CardContent className="pt-6 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/8 text-primary"><Mail className="h-5 w-5" /></div><div><div className="font-head font-semibold">Email Outbound</div><p className="mt-1 text-sm leading-6 text-muted-foreground">Dipakai untuk tombol Kirim Email pada Purchase Order. Pilih Gmail atau SMTP email perusahaan. Password disimpan terenkripsi dan tidak ditampilkan kembali.</p></div></div>
        <div className={`rounded-full px-3 py-1 text-xs font-semibold ${cfg.enabled && cfg.ready ? "bg-emerald-50 text-emerald-700" : "bg-muted text-muted-foreground"}`}>{statusText}</div>
      </div>

      <label className="flex cursor-pointer items-center gap-2 rounded-xl border bg-muted/10 px-4 py-3 text-sm font-medium"><input type="checkbox" checked={!!cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} className="h-4 w-4 accent-current" />Aktifkan pengiriman email dari aplikasi</label>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <button type="button" onClick={() => setProvider("gmail")} className={`rounded-xl border p-4 text-left transition ${cfg.provider === "gmail" ? "border-primary bg-primary/[0.03] ring-1 ring-primary/20" : "bg-background hover:bg-muted/20"}`}><div className="font-head font-semibold">Gmail</div><p className="mt-1 text-xs leading-5 text-muted-foreground">Untuk akun Gmail / Google Workspace. Menggunakan smtp.gmail.com, port 587, STARTTLS, dan App Password.</p></button>
        <button type="button" onClick={() => setProvider("smtp")} className={`rounded-xl border p-4 text-left transition ${cfg.provider === "smtp" ? "border-primary bg-primary/[0.03] ring-1 ring-primary/20" : "bg-background hover:bg-muted/20"}`}><div className="font-head font-semibold">SMTP Perusahaan</div><p className="mt-1 text-xs leading-5 text-muted-foreground">Untuk mail server perusahaan, hosting, Microsoft 365 relay, atau provider SMTP lainnya.</p></button>
      </div>

      {cfg.provider === "gmail" ? <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Email Gmail / Username"><Input type="email" value={cfg.username || ""} onChange={(e) => { const next = e.target.value; setCfg((cur) => ({ ...cur, username: next, from_email: !cur.from_email || cur.from_email === cur.username ? next : cur.from_email })); }} placeholder="procurement@perusahaan.com" /></Field>
        <Field label="Nama Pengirim"><Input value={cfg.from_name || ""} onChange={(e) => setCfg({ ...cfg, from_name: e.target.value })} placeholder="Procurement PT REAL" /></Field>
        <Field label="Email Pengirim"><Input type="email" value={cfg.from_email || ""} onChange={(e) => setCfg({ ...cfg, from_email: e.target.value })} placeholder="Sama dengan akun Gmail" /></Field>
        <Field label={cfg.password_set ? "App Password (sudah tersimpan)" : "App Password Gmail"}><div className="relative"><Input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cfg.password_set ? "Kosongkan jika tidak ingin mengganti" : "16 karakter App Password"} className="pr-10" /><button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground">{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></div></Field>
      </div> : <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="SMTP Host"><Input value={cfg.host || ""} onChange={(e) => setCfg({ ...cfg, host: e.target.value })} placeholder="mail.perusahaan.com" /></Field>
        <Field label="Port"><Input type="number" min="1" max="65535" value={cfg.port || ""} onChange={(e) => setCfg({ ...cfg, port: e.target.value })} placeholder="587" /></Field>
        <Field label="Username"><Input value={cfg.username || ""} onChange={(e) => setCfg({ ...cfg, username: e.target.value })} placeholder="procurement@perusahaan.com" /></Field>
        <Field label={cfg.password_set ? "Password SMTP (sudah tersimpan)" : "Password SMTP"}><div className="relative"><Input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cfg.password_set ? "Kosongkan jika tidak ingin mengganti" : "Password SMTP"} className="pr-10" /><button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground">{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></div></Field>
        <Field label="Email Pengirim"><Input type="email" value={cfg.from_email || ""} onChange={(e) => setCfg({ ...cfg, from_email: e.target.value })} placeholder="procurement@perusahaan.com" /></Field>
        <Field label="Nama Pengirim"><Input value={cfg.from_name || ""} onChange={(e) => setCfg({ ...cfg, from_name: e.target.value })} placeholder="Procurement PT REAL" /></Field>
        <Field label="Keamanan Koneksi"><select value={cfg.security || "starttls"} onChange={(e) => setCfg({ ...cfg, security: e.target.value })} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"><option value="starttls">STARTTLS (umumnya port 587)</option><option value="ssl">SSL/TLS (umumnya port 465)</option><option value="none">Tanpa TLS</option></select></Field>
      </div>}

      {cfg.provider === "gmail" && <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3 text-xs leading-5 text-amber-900">Untuk Gmail, gunakan <b>App Password</b> dari akun Google yang sudah mengaktifkan Verifikasi 2 Langkah. Jangan gunakan password login Gmail biasa.</div>}
      {cfg.source === "environment" && <div className="rounded-xl border bg-muted/20 p-3 text-xs text-muted-foreground">Saat ini aplikasi masih membaca konfigurasi lama dari environment server. Setelah disimpan di sini, pengaturan aplikasi akan menjadi prioritas.</div>}

      <Button onClick={save} disabled={saving}><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Email Outbound"}</Button>
    </CardContent></Card>

    <Card><CardContent className="pt-6 space-y-4">
      <div><div className="font-head font-semibold">Tes Pengiriman</div><p className="mt-1 text-sm text-muted-foreground">Simpan konfigurasi terlebih dahulu, lalu kirim email tes untuk memastikan koneksi dan kredensial benar.</p></div>
      <div className="flex flex-col gap-3 sm:flex-row"><Input type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="email tujuan tes" className="max-w-xl" /><Button type="button" variant="outline" onClick={sendTest} disabled={testing || !cfg.enabled}><Send className="h-4 w-4 mr-2" />{testing ? "Mengirim..." : "Kirim Email Tes"}</Button></div>
      {cfg.last_test_at && <p className="text-xs text-muted-foreground">Tes terakhir berhasil dikirim ke {cfg.last_test_to || "-"}.</p>}
    </CardContent></Card>
  </div>;
}
