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
  from_name: "",
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
      const data = { ...(r.data || {}) };
      if (!data.username && data.from_email) data.username = data.from_email; // data lama: email tersimpan di from_email
      setCfg({ ...EMAIL_DEFAULTS, ...data });
      if (!testTo && data.from_email) setTestTo(data.from_email);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const changeEmail = (value) => {
    const email = value.trim();
    const domain = (email.match(/@([^@\s]+)$/) || [])[1] || "";
    const googleDomain = /^(gmail|googlemail)\.com$/i.test(domain);
    setCfg((cur) => {
      const next = { ...cur, username: value, from_email: value };
      if (cur.provider === "smtp" && (!cur.host || cur.host === "smtp.gmail.com")) {
        next.host = domain && !googleDomain ? `mail.${domain.toLowerCase()}` : "";
      }
      return next;
    });
  };

  const useGmail = () => setCfg((cur) => ({ ...cur, provider: "gmail", host: "smtp.gmail.com", port: 587, security: "starttls" }));
  const useSmtp = () => setCfg((cur) => {
    const domain = (String(cur.username || "").match(/@([^@\s]+)$/) || [])[1] || "";
    const googleDomain = /^(gmail|googlemail)\.com$/i.test(domain);
    return {
      ...cur, provider: "smtp",
      host: cur.host && cur.host !== "smtp.gmail.com" ? cur.host : (domain && !googleDomain ? `mail.${domain.toLowerCase()}` : ""),
      port: cur.port === 587 ? 587 : cur.port || 587,
      security: cur.security || "starttls",
    };
  });

  const save = async () => {
    try {
      setSaving(true);
      const sender = (cfg.username || cfg.from_email || "").trim();
      const payload = {
        enabled: !!cfg.enabled,
        provider: cfg.provider,
        host: cfg.provider === "gmail" ? "smtp.gmail.com" : (cfg.host || ""),
        port: Number(cfg.provider === "gmail" ? 587 : (cfg.port || 587)),
        username: sender,
        from_email: sender,
        from_name: cfg.from_name || "",
        security: cfg.provider === "gmail" ? "starttls" : (cfg.security || "starttls"),
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
  const senderEmail = cfg.username || cfg.from_email || "";
  const senderLabel = cfg.from_name ? `${cfg.from_name} <${senderEmail}>` : senderEmail;

  return <div className="space-y-4">
    <Card><CardContent className="pt-6 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/8 text-primary"><Mail className="h-5 w-5" /></div><div><div className="font-head font-semibold">Email Outbound</div><p className="mt-1 text-sm leading-6 text-muted-foreground">Dipakai untuk tombol Kirim Email pada Purchase Order. Cukup isi email pengirim dan App Password. Password disimpan terenkripsi dan tidak ditampilkan kembali.</p></div></div>
        <div className={`rounded-full px-3 py-1 text-xs font-semibold ${cfg.enabled && cfg.ready ? "bg-emerald-50 text-emerald-700" : "bg-muted text-muted-foreground"}`}>{statusText}</div>
      </div>

      <label className="flex cursor-pointer items-center gap-2 rounded-xl border bg-muted/10 px-4 py-3 text-sm font-medium"><input type="checkbox" checked={!!cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} className="h-4 w-4 accent-current" />Aktifkan pengiriman email dari aplikasi</label>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Email Pengirim">
          <Input type="email" value={cfg.username || ""} onChange={(e) => changeEmail(e.target.value)} placeholder="procurement@perusahaan.com" data-testid="email-outbound-username" />
        </Field>
        <Field label={cfg.provider === "gmail" ? (cfg.password_set ? "App Password (sudah tersimpan)" : "App Password Gmail") : (cfg.password_set ? "Password SMTP (sudah tersimpan)" : "Password SMTP")}>
          <div className="relative"><Input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cfg.password_set ? "Kosongkan jika tidak ingin mengganti" : (cfg.provider === "gmail" ? "16 karakter App Password" : "Kosongkan bila server tidak memakai login")} className="pr-10" data-testid="email-outbound-password" /><button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground">{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></div>
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>Jenis akun: <b className="text-foreground">{cfg.provider === "gmail" ? "Gmail / Google Workspace" : "SMTP perusahaan"}</b></span>
        {cfg.provider === "gmail"
          ? <button type="button" onClick={useSmtp} className="underline underline-offset-2 hover:text-foreground">Pakai SMTP perusahaan</button>
          : <button type="button" onClick={useGmail} className="underline underline-offset-2 hover:text-foreground">Kembali ke Gmail</button>}
        {senderEmail && <span className="ml-auto">Dikirim sebagai: <b className="text-foreground">{senderLabel}</b></span>}
      </div>

      {cfg.provider === "smtp" && <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 rounded-xl border bg-muted/10 p-3">
        <Field label="Server SMTP"><Input value={cfg.host || ""} onChange={(e) => setCfg({ ...cfg, host: e.target.value })} placeholder="mail.perusahaan.com" /></Field>
        <Field label="Port"><Input type="number" min="1" max="65535" value={cfg.port || ""} onChange={(e) => setCfg({ ...cfg, port: e.target.value })} placeholder="587" /></Field>
        <Field label="Keamanan"><select value={cfg.security || "starttls"} onChange={(e) => setCfg({ ...cfg, security: e.target.value })} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"><option value="starttls">STARTTLS (587)</option><option value="ssl">SSL/TLS (465)</option><option value="none">Tanpa TLS</option></select></Field>
      </div>}

      {cfg.provider === "gmail" && <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3 text-xs leading-5 text-amber-900">Gunakan <b>App Password</b> 16 karakter dari akun Google yang sudah mengaktifkan Verifikasi 2 Langkah. Jangan gunakan password login Gmail biasa.</div>}
      {cfg.source === "environment" && <div className="rounded-xl border bg-muted/20 p-3 text-xs text-muted-foreground">Saat ini aplikasi masih membaca konfigurasi lama dari environment server. Setelah disimpan di sini, pengaturan aplikasi akan menjadi prioritas.</div>}

      <Button onClick={save} disabled={saving} data-testid="email-outbound-save"><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Email Outbound"}</Button>
    </CardContent></Card>

    <Card><CardContent className="pt-6 space-y-4">
      <div><div className="font-head font-semibold">Tes Pengiriman</div><p className="mt-1 text-sm text-muted-foreground">Simpan konfigurasi terlebih dahulu, lalu kirim email tes untuk memastikan koneksi dan kredensial benar.</p></div>
      <div className="flex flex-col gap-3 sm:flex-row"><Input type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="email tujuan tes" className="max-w-xl" /><Button type="button" variant="outline" onClick={sendTest} disabled={testing || !cfg.enabled}><Send className="h-4 w-4 mr-2" />{testing ? "Mengirim..." : "Kirim Email Tes"}</Button></div>
      {cfg.last_test_at && <p className="text-xs text-muted-foreground">Tes terakhir berhasil dikirim ke {cfg.last_test_to || "-"}.</p>}
    </CardContent></Card>
  </div>;
}