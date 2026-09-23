import { useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Save } from "lucide-react";
import { toast } from "sonner";

function previewFormat(format, seq = 1) {
  const raw = String(format || "");
  const m = raw.match(/\{seq(?::0?(\d+)d)?\}/);
  if (!m) return "Format belum valid";
  const width = Number(m[1] || 0);
  const value = width ? String(seq).padStart(width, "0") : String(seq);
  return raw.replace(m[0], value);
}

export function MasterCodeSettings() {
  const [formats, setFormats] = useState({});
  const [rows, setRows] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/settings/master_codes").then((r) => {
      setFormats(r.data?.formats || {});
      setRows(r.data?.rows || []);
    }).catch((e) => toast.error(apiError(e.response?.data?.detail)));
  }, []);

  const orderedRows = useMemo(() => rows.map((r) => ({ ...r, format: formats[r.key] ?? r.format ?? "" })), [rows, formats]);

  const save = async () => {
    try {
      setSaving(true);
      const r = await api.put("/settings/master_codes", { formats });
      setFormats(r.data?.formats || formats);
      setRows(r.data?.rows || rows);
      toast.success("Format kode master tersimpan");
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return <div className="space-y-4">
    <Card><CardContent className="pt-6 space-y-2">
      <div className="font-head font-semibold">Format Kode Master Data</div>
      <p className="text-sm text-muted-foreground leading-6">Atur pola kode otomatis untuk data master baru. Gunakan <code>{"{seq}"}</code> untuk nomor biasa atau <code>{"{seq:05d}"}</code> untuk nomor 5 digit. Contoh: <code>BRG-{"{seq:05d}"}</code>, <code>ITEM/{"{seq:04d}"}</code>, atau <code>{"{seq:06d}"}</code>.</p>
      <p className="text-xs text-muted-foreground">Perubahan hanya berlaku untuk kode baru. Kode master yang sudah ada tidak diubah, dan nomor urut tetap melanjutkan sequence sebelumnya.</p>
    </CardContent></Card>

    <Card><CardContent className="pt-6 space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {orderedRows.map((row) => <div key={row.key} className="rounded-xl border p-4 space-y-2 bg-background">
          <div className="flex items-center justify-between gap-3"><div className="font-medium">{row.label}</div><span className="text-[11px] font-mono rounded bg-muted px-2 py-1">{row.key}</span></div>
          <Input className="font-mono" value={formats[row.key] ?? row.format ?? ""} onChange={(e) => setFormats((cur) => ({ ...cur, [row.key]: e.target.value }))} placeholder="BRG-{seq:05d}" />
          <div className="text-xs text-muted-foreground">Contoh hasil: <span className="font-mono font-medium text-foreground">{previewFormat(formats[row.key] ?? row.format, 1)}</span></div>
        </div>)}
      </div>
      <Button onClick={save} disabled={saving}><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Format Kode Master"}</Button>
    </CardContent></Card>
  </div>;
}
