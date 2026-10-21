import { useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RefreshCw, Save } from "lucide-react";
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
  const [sequences, setSequences] = useState({});
  const [rows, setRows] = useState([]);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState("");

  const applyResponse = (data) => {
    if (!data) return;
    setFormats(data.formats || {});
    setSequences(data.sequences || {});
    setRows(data.rows || []);
  };

  useEffect(() => {
    api.get("/settings/master_codes").then((r) => {
      const data = r.data || {};
      setFormats(data.formats || {});
      setSequences(data.sequences || {});
      setRows(data.rows || []);
    }).catch((e) => toast.error(apiError(e.response?.data?.detail)));
  }, []);

  const orderedRows = useMemo(() => rows.map((r) => ({
    ...r,
    format: formats[r.key] ?? r.format ?? "",
    last_seq: sequences[r.key] ?? r.last_seq ?? 0,
  })), [rows, formats, sequences]);

  const save = async () => {
    try {
      setSaving(true);
      const payloadSequences = {};
      orderedRows.forEach((row) => {
        payloadSequences[row.key] = Number(sequences[row.key] ?? row.last_seq ?? 0);
      });
      const r = await api.put("/settings/master_codes", { formats, sequences: payloadSequences });
      applyResponse(r.data);
      toast.success("Format dan nomor urut kode master tersimpan");
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const syncSequence = async (row) => {
    try {
      setSyncing(row.key);
      const r = await api.post(`/settings/master_codes/${row.key}/sync-sequence`);
      const data = r.data || {};
      setSequences((cur) => ({ ...cur, [row.key]: data.last_seq ?? 0 }));
      setRows((cur) => cur.map((x) => x.key === row.key
        ? { ...x, last_seq: data.last_seq ?? 0, next_code: data.next_code ?? x.next_code }
        : x));
      if (data.changed) toast.success(`${row.label}: nomor urut disetel ke ${data.last_seq}`);
      else toast.info(`${row.label}: nomor urut sudah sesuai data (${data.last_seq})`);
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally {
      setSyncing("");
    }
  };

  return <div className="space-y-4">
    <Card><CardContent className="pt-6 space-y-2">
      <div className="font-head font-semibold">Format Kode Master Data</div>
      <p className="text-sm text-muted-foreground leading-6">Atur pola kode otomatis untuk data master baru. Gunakan <code>{"{seq}"}</code> untuk nomor biasa atau <code>{"{seq:05d}"}</code> untuk nomor 5 digit. Contoh: <code>BRG-{"{seq:05d}"}</code>, <code>ITEM/{"{seq:04d}"}</code>, atau <code>{"{seq:06d}"}</code>.</p>
      <p className="text-xs text-muted-foreground">Nomor urut terakhir menentukan kode berikutnya. Setelah impor data lama, tekan <b>Sinkron dari data</b> agar nomor melanjutkan kode yang sudah ada. Kode yang sudah tersimpan tidak diubah.</p>
    </CardContent></Card>

    <Card><CardContent className="pt-6 space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {orderedRows.map((row) => <div key={row.key} className="rounded-xl border p-4 space-y-3 bg-background">
          <div className="flex items-center justify-between gap-3"><div className="font-medium">{row.label}</div><span className="text-[11px] font-mono rounded bg-muted px-2 py-1">{row.key}</span></div>

          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Format kode</div>
            <Input className="font-mono" value={formats[row.key] ?? row.format ?? ""} onChange={(e) => setFormats((cur) => ({ ...cur, [row.key]: e.target.value }))} placeholder="BRG-{seq:05d}" />
          </div>

          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Nomor urut terakhir</div>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                inputMode="numeric"
                className="font-mono"
                value={row.last_seq}
                onChange={(e) => {
                  const raw = e.target.value;
                  const value = raw === "" ? 0 : Math.max(0, Number.parseInt(raw, 10) || 0);
                  setSequences((cur) => ({ ...cur, [row.key]: value }));
                }}
              />
              <Button type="button" variant="outline" onClick={() => syncSequence(row)} disabled={syncing === row.key}>
                <RefreshCw className={`h-4 w-4 mr-2 ${syncing === row.key ? "animate-spin" : ""}`} />
                Sinkron dari data
              </Button>
            </div>
          </div>

          <div className="text-xs text-muted-foreground">Kode berikutnya: <span className="font-mono font-medium text-foreground">{previewFormat(formats[row.key] ?? row.format, Number(row.last_seq || 0) + 1)}</span></div>
        </div>)}
      </div>
      <Button onClick={save} disabled={saving}><Save className="h-4 w-4 mr-2" />{saving ? "Menyimpan..." : "Simpan Format & Nomor Urut"}</Button>
    </CardContent></Card>
  </div>;
}