import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { num } from "@/lib/format";
import { Search, X, AlertTriangle } from "lucide-react";

/**
 * Inline source-document picker.
 *
 * Kept under the historical PullDialog name so transaction pages do not need a
 * second modal/page just to pull source documents. The picker now lives inside
 * the same transaction workspace and closes after selected rows are inserted.
 */
export function PullDialog({ open, onClose, url, title, columns, idKey = "line_id", qtyKey = "outstanding", onConfirm }) {
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState({});
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setSel({});
    setQ("");
    setError("");
    setLoading(true);
    api.get(url)
      .then((r) => {
        setRows(Array.isArray(r.data) ? r.data : []);
        setError("");
      })
      .catch((e) => {
        setRows([]);
        setError(apiError(e.response?.data?.detail));
      })
      .finally(() => setLoading(false));
  }, [open, url]);

  if (!open) return null;

  const filtered = rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));

  const toggle = (r) => {
    const id = r[idKey];
    setSel((s) => {
      const n = { ...s };
      if (n[id]) delete n[id];
      else n[id] = { row: r, qty: r[qtyKey] };
      return n;
    });
  };

  const setQty = (id, v) => setSel((s) => ({ ...s, [id]: { ...s[id], qty: v } }));
  const allChecked = filtered.length > 0 && filtered.every((r) => sel[r[idKey]]);
  const toggleAll = () => {
    if (allChecked) return setSel({});
    const n = {};
    filtered.forEach((r) => { n[r[idKey]] = { row: r, qty: r[qtyKey] }; });
    setSel(n);
  };

  const confirm = () => {
    const picked = Object.values(sel)
      .filter((x) => Number(x.qty) > 0)
      .map((x) => ({ ...x.row, _qty: Number(x.qty) }));
    onConfirm(picked);
    onClose();
  };

  const selectedCount = Object.keys(sel).length;
  const emptyText = q ? "Tidak ada data yang cocok dengan pencarian" : "Tidak ada dokumen yang memenuhi syarat untuk ditarik";

  return (
    <section className="mb-5 rounded-xl border bg-card shadow-sm overflow-hidden" data-testid="inline-source-picker">
      <div className="flex flex-col gap-3 border-b bg-muted/35 p-4 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold uppercase tracking-wider text-primary">Sumber Dokumen</div>
          <h2 className="font-head text-base font-semibold">{title}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">Pilih baris dan tentukan qty yang akan dimasukkan. Tidak perlu pindah halaman.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="self-end sm:self-auto">
          <X className="mr-2 h-4 w-4" />Tutup
        </Button>
      </div>

      <div className="p-4 space-y-3">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" data-testid="pull-error">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div><div className="font-semibold">Sumber dokumen gagal dimuat</div><div className="text-xs mt-0.5">{error}</div></div>
          </div>
        )}

        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input data-testid="pull-search" placeholder="Cari nomor dokumen, barang, proyek..." value={q}
            onChange={(e) => setQ(e.target.value)} className="h-10 pl-9" autoFocus />
        </div>

        {/* Mobile: source rows as cards, easier for warehouse users on phones. */}
        <div className="space-y-2 md:hidden">
          {loading && <div className="rounded-lg border p-5 text-center text-sm text-muted-foreground">Memuat dokumen...</div>}
          {!loading && !error && filtered.length === 0 && <div className="rounded-lg border p-5 text-center text-sm text-muted-foreground">{emptyText}</div>}
          {filtered.map((r) => {
            const id = r[idKey];
            const checked = !!sel[id];
            return (
              <div key={id} className={`rounded-lg border p-3 transition-colors ${checked ? "border-primary/50 bg-primary/5" : "bg-background"}`}>
                <div className="flex items-start gap-3">
                  <Checkbox checked={checked} onCheckedChange={() => toggle(r)} className="mt-1" />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    {columns.map((c) => (
                      <div key={c.key} className="flex gap-3 text-sm">
                        <span className="w-24 shrink-0 text-xs text-muted-foreground">{c.label}</span>
                        <span className={`min-w-0 flex-1 break-words ${c.mono ? "font-mono text-xs" : ""} ${c.num ? "text-right tabular-nums" : ""}`}>
                          {c.num ? num(r[c.key]) : (r[c.key] ?? "-")}
                        </span>
                      </div>
                    ))}
                    <div className="flex items-center gap-3 pt-1">
                      <span className="w-24 shrink-0 text-xs font-medium">Qty Ambil</span>
                      <Input type="number" disabled={!checked} value={checked ? sel[id].qty : r[qtyKey]}
                        onChange={(e) => setQty(id, e.target.value)} className="h-9 text-right" />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Desktop: dense table for fast operational input. */}
        <div className="hidden md:block max-h-[430px] overflow-auto rounded-md border">
          <table className="w-full text-sm zebra">
            <thead className="sticky top-0 z-10 bg-muted">
              <tr className="text-left">
                <th className="p-2 w-10"><Checkbox checked={allChecked} onCheckedChange={toggleAll} data-testid="pull-select-all" /></th>
                {columns.map((c) => <th key={c.key} className="p-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap">{c.label}</th>)}
                <th className="p-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground w-28">Qty Ambil</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={columns.length + 2} className="p-6 text-center text-muted-foreground">Memuat dokumen...</td></tr>}
              {!loading && error && <tr><td colSpan={columns.length + 2} className="p-6 text-center text-destructive">Gagal memuat sumber dokumen. Lihat pesan di atas.</td></tr>}
              {!loading && !error && filtered.length === 0 && <tr><td colSpan={columns.length + 2} className="p-6 text-center text-muted-foreground">{emptyText}</td></tr>}
              {filtered.map((r) => {
                const id = r[idKey]; const checked = !!sel[id];
                return (
                  <tr key={id} className={`border-t transition-colors ${checked ? "bg-primary/5" : "hover:bg-accent/40"}`}>
                    <td className="p-2"><Checkbox checked={checked} onCheckedChange={() => toggle(r)} data-testid={`pull-row-${id}`} /></td>
                    {columns.map((c) => (
                      <td key={c.key} className={`p-2 whitespace-nowrap ${c.mono ? "font-mono text-xs" : ""} ${c.num ? "text-right tabular-nums" : ""}`}>
                        {c.num ? num(r[c.key]) : (r[c.key] ?? "-")}
                      </td>
                    ))}
                    <td className="p-2">
                      <Input type="number" disabled={!checked} value={checked ? sel[id].qty : r[qtyKey]}
                        onChange={(e) => setQty(id, e.target.value)} className="h-8 text-right" data-testid={`pull-qty-${id}`} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col-reverse gap-2 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-muted-foreground">{selectedCount ? `${selectedCount} baris dipilih` : "Pilih dokumen sumber yang diperlukan"}</div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Batal</Button>
            <Button onClick={confirm} disabled={selectedCount === 0} data-testid="pull-confirm">Masukkan ke Form ({selectedCount})</Button>
          </div>
        </div>
      </div>
    </section>
  );
}