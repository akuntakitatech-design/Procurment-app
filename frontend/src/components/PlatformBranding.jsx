import { useEffect, useState } from "react";
import api, { API, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Image,
  Loader2,
  Save,
  Trash2,
  Upload,
} from "lucide-react";

export default function PlatformBranding() {
  const [data, setData] = useState({
    name: "KelolaKita Procurement",
    tagline: "Kelola Bersama. Tumbuh Bersama.",
    subtitle: "Procurement • Warehouse • Inventory",
    logo_available: false,
    logo_version: null,
  });

  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  const load = async () => {
    setLoading(true);
    setErr("");

    try {
      const r = await api.get("/platform-branding");
      setData(r.data || {});
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const logoUrl = data.logo_available
    ? `${API}/platform-branding/logo?v=${encodeURIComponent(
        data.logo_version || "1"
      )}`
    : null;

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setErr("");
    setSuccess("");

    try {
      const r = await api.patch("/platform/branding", {
        name: data.name,
        tagline: data.tagline,
        subtitle: data.subtitle,
      });

      setData(r.data || data);
      setSuccess("Branding aplikasi berhasil disimpan.");
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  const upload = async () => {
    if (!file) return;

    setUploading(true);
    setErr("");
    setSuccess("");

    try {
      const form = new FormData();
      form.append("file", file);

      const r = await api.post("/platform/branding/logo", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setData(r.data || data);
      setFile(null);
      setSuccess("Logo KelolaKita berhasil diupload.");
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    } finally {
      setUploading(false);
    }
  };

  const removeLogo = async () => {
    if (!window.confirm("Hapus logo aplikasi saat ini?")) return;

    setErr("");
    setSuccess("");

    try {
      await api.delete("/platform/branding/logo");

      setData((x) => ({
        ...x,
        logo_available: false,
        logo_version: null,
      }));

      setFile(null);
      setSuccess("Logo aplikasi berhasil dihapus.");
    } catch (e) {
      setErr(apiError(e.response?.data?.detail) || e.message);
    }
  };

  if (loading) {
    return (
      <div className="rounded-2xl border bg-white p-6 shadow-sm">
        <div className="flex items-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Memuat branding aplikasi...
        </div>
      </div>
    );
  }

  return (
    <section className="mb-6 rounded-2xl border bg-white shadow-sm overflow-hidden">
      <div className="border-b px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-950 text-white">
            <Image className="h-5 w-5" />
          </div>

          <div>
            <div className="font-semibold">Branding Aplikasi</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Identitas global KelolaKita Procurement, terpisah dari logo perusahaan.
            </div>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-[220px_1fr] gap-6 p-5">
        <div>
          <div className="rounded-2xl border bg-slate-50 min-h-[170px] flex items-center justify-center p-5">
            {logoUrl ? (
              <img
                src={logoUrl}
                alt="Logo aplikasi"
                className="max-h-28 max-w-full object-contain"
              />
            ) : (
              <div className="text-center">
                <Image className="h-9 w-9 mx-auto text-slate-300" />
                <div className="mt-2 text-xs text-muted-foreground">
                  Belum ada logo
                </div>
              </div>
            )}
          </div>

          <div className="mt-3">
            <Input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>

          <Button
            type="button"
            variant="outline"
            className="mt-2 w-full"
            disabled={!file || uploading}
            onClick={upload}
          >
            {uploading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Upload Logo
          </Button>

          {data.logo_available && (
            <Button
              type="button"
              variant="ghost"
              className="mt-1 w-full text-red-600 hover:text-red-700"
              onClick={removeLogo}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Hapus Logo
            </Button>
          )}

          <p className="mt-2 text-[11px] text-muted-foreground">
            PNG, JPG, atau WEBP. Maksimal 5 MB.
          </p>
        </div>

        <form onSubmit={save} className="space-y-4">
          <div className="space-y-2">
            <Label>Nama Aplikasi</Label>
            <Input
              value={data.name || ""}
              onChange={(e) =>
                setData((x) => ({ ...x, name: e.target.value }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label>Subtitle</Label>
            <Input
              value={data.subtitle || ""}
              onChange={(e) =>
                setData((x) => ({ ...x, subtitle: e.target.value }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label>Tagline</Label>
            <Input
              value={data.tagline || ""}
              onChange={(e) =>
                setData((x) => ({ ...x, tagline: e.target.value }))
              }
            />
          </div>

          {err && (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
              {err}
            </div>
          )}

          {success && (
            <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {success}
            </div>
          )}

          <Button type="submit" disabled={saving}>
            {saving ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Simpan Branding
          </Button>
        </form>
      </div>
    </section>
  );
}
