import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertTriangle, CheckCircle2, History, Layers, ListTree, Lock, PlayCircle, RefreshCw } from "lucide-react";
import { num, rupiah } from "@/lib/format";
import { OPENING_STATUS_TONE, valuationAccess } from "@/lib/openingValuation";
import { toast } from "sonner";

export function OpeningStatusBadge({ status, label, testid }) {
  return <Badge variant="outline" className={OPENING_STATUS_TONE[status] || ""} data-testid={testid}>{label}</Badge>;
}

function Stat({ label, value, tone = "", testid }) {
  return <div className="rounded-lg border bg-white/60 px-3 py-2 dark:bg-slate-900/40" data-testid={testid}>
    <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
    <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
  </div>;
}

const day = (v) => (v ? String(v).slice(0, 10) : "—");

// Urutan simulasi satu pool: Opening -> movement kronologis -> MWA tiap langkah -> nilai keluar/HPP -> saldo akhir.
function TimelineDialog({ pool, item, onClose }) {
  return <Dialog open={!!pool} onOpenChange={(o) => !o && onClose()}>
    <DialogContent className="max-w-5xl" data-testid="oc-timeline-dialog">
      <DialogHeader><DialogTitle>Simulasi Replay — {item?.item_code} {item?.item_name} · {pool?.warehouse_name}</DialogTitle>
        <DialogDescription>Dry run: tidak ada data yang diubah. Kolom "Tercatat" = nilai di ledger saat ini.</DialogDescription></DialogHeader>
      <div className="max-h-[60vh] overflow-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left text-xs text-muted-foreground dark:bg-slate-900"><tr>
            <th className="px-3 py-2">Tanggal</th><th className="px-3 py-2">Transaksi</th><th className="px-3 py-2 text-right">Masuk</th><th className="px-3 py-2 text-right">Keluar</th>
            <th className="px-3 py-2 text-right">Nilai Keluar/HPP (Tercatat → Replay)</th><th className="px-3 py-2 text-right">MWA Sesudah</th><th className="px-3 py-2 text-right">Saldo Nilai (Tercatat → Replay)</th></tr></thead>
          <tbody>{(pool?.timeline || []).map((x, i) => <tr key={x.id || `inj-${i}`} className={`border-t ${x.changed ? "bg-amber-50/60 dark:bg-amber-950/20" : ""}`} data-testid={`oc-timeline-row-${i}`}>
            <td className="px-3 py-2 whitespace-nowrap">{day(x.at)}</td>
            <td className="px-3 py-2">{x.kind === "opening" ? <b>Opening (Import Saldo Awal) {rupiah(x.opening_value)}</b> : `${x.doc_type || ""} ${x.doc_no || ""}`}</td>
            <td className="px-3 py-2 text-right tabular-nums">{x.qty_in ? num(x.qty_in) : ""}</td>
            <td className="px-3 py-2 text-right tabular-nums">{x.qty_out ? num(x.qty_out) : ""}</td>
            <td className="px-3 py-2 text-right tabular-nums">{x.qty_out ? `${rupiah(x.recorded_value_out)} → ${rupiah(x.value_out)}` : ""}</td>
            <td className="px-3 py-2 text-right tabular-nums">{rupiah(x.avg_after)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{x.kind === "opening" ? rupiah(x.value_after) : `${rupiah(x.recorded_value_after)} → ${rupiah(x.value_after)}`}</td></tr>)}</tbody>
        </table>
      </div>
      <DialogFooter><Button variant="outline" onClick={onClose} data-testid="oc-timeline-close">Tutup</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}

// Koreksi Nilai Awal Persediaan: Tetapkan Massal (tanpa mutasi) + Revaluasi Saldo Awal / Valuation Replay (dry run dulu).
// Harga dasar hanya dari Import Saldo Awal Persediaan (Σ nilai saldo awal / Σ qty saldo awal).
export function OpeningCorrection() {
  const { can } = useAuth();
  const { canView, canApply } = valuationAccess(can);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mass, setMass] = useState(false);
  const [massBusy, setMassBusy] = useState(false);
  const [dry, setDry] = useState(null);
  const [dryBusy, setDryBusy] = useState(false);
  const [applyOpen, setApplyOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [applyBusy, setApplyBusy] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get("/valuation/opening-status").then((r) => setData(r.data)).catch((e) => toast.error(apiError(e))).finally(() => setLoading(false));
  }, []);
  useEffect(() => { if (canView) load(); }, [load, canView]);
  if (!canView) return null;

  const s = data?.summary || {};
  const ready = (data?.rows || []).filter((r) => r.status === "ready");

  const doMass = async () => {
    setMassBusy(true);
    try {
      const r = await api.post("/valuation/opening-mass/apply", {});
      toast.success(`${r.data.applied} pool ditetapkan nilai awalnya`);
      if (r.data.skipped?.length) toast.warning(`${r.data.skipped.length} pool dilewati`);
      setMass(false); load(); setDry(null);
    } catch (e) { toast.error(apiError(e)); } finally { setMassBusy(false); }
  };
  const doDry = async () => {
    setDryBusy(true);
    try { const r = await api.post("/valuation/replay/dry-run", {}); setDry(r.data); }
    catch (e) { toast.error(apiError(e)); } finally { setDryBusy(false); }
  };
  const doApply = async () => {
    setApplyBusy(true);
    try {
      const r = await api.post("/valuation/replay/apply", { fingerprint: dry.fingerprint, confirm: phrase });
      toast.success(r.data.already_applied ? "Revaluasi ini sudah pernah diterapkan" : "Revaluasi Saldo Awal diterapkan");
      setApplyOpen(false); setPhrase(""); setDry(null); load();
    } catch (e) { toast.error(apiError(e)); } finally { setApplyBusy(false); }
  };
  const ds = dry?.summary || {};

  return <Card data-testid="opening-correction">
    <CardContent className="space-y-5 pt-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">Koreksi Nilai Awal Persediaan</h3>
          <p className="max-w-3xl text-sm text-muted-foreground">Stok dari Import Saldo Awal bernilai Rp 0 sampai nilai awalnya ditetapkan. Harga dasar hanya dari Import Saldo Awal (Σ nilai saldo awal / Σ qty saldo awal) — bukan harga PO, kontrak, master, atau avg saat ini.</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} data-testid="opening-correction-refresh"><RefreshCw className={`mr-1.5 h-4 w-4 ${loading ? "animate-spin" : ""}`} />Muat ulang</Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <Stat label="Siap Ditetapkan" value={num(s.ready || 0)} tone="text-emerald-700 dark:text-emerald-300" testid="oc-sum-ready" />
        <Stat label="Perlu Revaluasi" value={num(s.needs_replay || 0)} tone="text-amber-700 dark:text-amber-300" testid="oc-sum-replay" />
        <Stat label="Tidak Ada Nilai Sumber" value={num(s.no_source || 0)} testid="oc-sum-nosource" />
        <Stat label="Sudah Dinilai" value={num(s.valued || 0)} tone="text-sky-700 dark:text-sky-300" testid="oc-sum-valued" />
        <Stat label="Nilai persediaan sekarang" value={rupiah(s.inventory_value_now || 0)} testid="oc-sum-now" />
        <Stat label="Sesudah Tetapkan Massal" value={rupiah(s.inventory_value_after_mass || 0)} testid="oc-sum-after-mass" />
        <Stat label="Nilai awal siap ditetapkan" value={rupiah(s.ready_opening_value || 0)} testid="oc-sum-ready-value" />
      </div>

      {canApply ? <div className="flex flex-wrap gap-2">
        <Button onClick={() => setMass(true)} disabled={!s.ready} data-testid="oc-mass-preview-btn"><Layers className="mr-1.5 h-4 w-4" />Tetapkan Massal ({num(s.ready || 0)})</Button>
        <Button variant="outline" onClick={doDry} disabled={!s.needs_replay || dryBusy} data-testid="oc-dryrun-btn"><PlayCircle className="mr-1.5 h-4 w-4" />{dryBusy ? "Menghitung…" : `Dry Run Revaluasi Saldo Awal (${num(s.needs_replay || 0)})`}</Button>
      </div> : <div className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground" data-testid="oc-no-action-note">
        <Lock className="h-3.5 w-3.5" />Menetapkan atau merevaluasi nilai memerlukan izin Lihat Harga Beli dan Penyesuaian Stok.</div>}

      {dry && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50/40 p-4 dark:border-amber-900 dark:bg-amber-950/20" data-testid="oc-dryrun-result">
        <div className="flex items-center gap-2 text-sm font-semibold"><History className="h-4 w-4" />Hasil Dry Run — belum ada data yang diubah</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <Stat label="Nilai persediaan sebelum" value={rupiah(ds.before_value || 0)} testid="oc-dry-before" />
          <Stat label="Nilai opening dimasukkan" value={rupiah(ds.opening_value || 0)} testid="oc-dry-opening" />
          <Stat label="Nilai sesudah replay" value={rupiah(ds.after_value || 0)} testid="oc-dry-after" />
          <Stat label="Transaksi terdampak" value={num(ds.affected_txns || 0)} testid="oc-dry-txns" />
          <Stat label="Transaksi keluar terdampak" value={num(ds.affected_out || 0)} testid="oc-dry-out" />
          <Stat label="HPP terdampak" value={num(ds.affected_hpp || 0)} testid="oc-dry-hpp" />
          <Stat label="Barang diblokir" value={num(ds.blocked || 0)} tone={ds.blocked ? "text-amber-700" : ""} testid="oc-dry-blocked" />
        </div>
        <div className="max-h-96 overflow-auto rounded-md border bg-white dark:bg-slate-950">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 text-left text-xs text-muted-foreground dark:bg-slate-900"><tr>
              <th className="px-3 py-2">Barang</th><th className="px-3 py-2">Gudang</th><th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Nilai Sebelum</th><th className="px-3 py-2 text-right">Opening</th><th className="px-3 py-2 text-right">Nilai Sesudah</th>
              <th className="px-3 py-2 text-right">Selisih</th><th className="px-3 py-2 text-right">Avg Sebelum → Sesudah</th>
              <th className="px-3 py-2 text-right">Trx / Keluar / HPP</th><th className="px-3 py-2">Keterangan</th><th className="px-3 py-2" /></tr></thead>
            <tbody>
              {(dry.items || []).flatMap((it) => it.blocked
                ? [<tr key={it.item_id} className="border-t" data-testid={`oc-dry-row-${it.item_id}`}><td className="px-3 py-2">{it.item_code} — {it.item_name}</td><td className="px-3 py-2" colSpan={8}>
                    {it.blocked_detail && <span className="text-xs text-muted-foreground" data-testid={`oc-dry-blocked-detail-${it.item_id}`}>{it.blocked_detail.doc_type} {it.blocked_detail.doc_no} ({day(it.blocked_detail.at)}): tercatat {rupiah(it.blocked_detail.recorded?.value_after)}, hasil hitung {rupiah(it.blocked_detail.replay?.value_after)}</span>}</td>
                    <td className="px-3 py-2 text-amber-700" colSpan={2}><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />Diblokir: {it.blocked}</td></tr>]
                : (it.pools || []).map((p, i) => <tr key={`${it.item_id}-${p.warehouse_id}`} className="border-t" data-testid={`oc-dry-row-${it.item_id}-${p.warehouse_id}`}>
                    <td className="px-3 py-2">{i === 0 ? `${it.item_code || ""} — ${it.item_name || ""}` : ""}</td><td className="px-3 py-2">{p.warehouse_name}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{num(p.qty)}</td><td className="px-3 py-2 text-right tabular-nums">{rupiah(p.before_value)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.opening_value ? rupiah(p.opening_value) : "—"}</td><td className="px-3 py-2 text-right font-medium tabular-nums">{rupiah(p.after_value)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{rupiah(p.after_value - p.before_value)}</td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{rupiah(p.before_avg)} → {rupiah(p.after_avg)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{`${p.affected_txns} / ${p.affected_out} / ${p.affected_hpp}`}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{p.seed ? "Saldo awal dinilai ulang" : "Terdampak transfer/pinjaman"}</td>
                    <td className="px-3 py-2"><Button size="sm" variant="ghost" onClick={() => setDetail({ pool: p, item: it })} data-testid={`oc-dry-detail-${it.item_id}-${p.warehouse_id}`}><ListTree className="h-4 w-4" /></Button></td></tr>))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">Qty, tanggal, sumber transaksi dan harga barang masuk yang tercatat tidak berubah. Yang dihitung ulang hanya hasil valuasi (rata-rata, nilai keluar/HPP, saldo) sesudah saldo awal. Fingerprint: <code>{dry.fingerprint}</code></p>
          {canApply && ds.replayable > 0 && <Button variant="destructive" onClick={() => setApplyOpen(true)} data-testid="oc-apply-btn">Terapkan Revaluasi…</Button>}
        </div>
      </div>}

      <TimelineDialog pool={detail?.pool} item={detail?.item} onClose={() => setDetail(null)} />

      <Dialog open={mass} onOpenChange={setMass}>
        <DialogContent className="max-w-4xl" data-testid="oc-mass-dialog">
          <DialogHeader><DialogTitle>Preview Tetapkan Massal</DialogTitle>
            <DialogDescription>Hanya saldo awal yang belum memiliki mutasi setelah tanggal saldo awal. Nilai awal tercatat pada tanggal saldo awal.</DialogDescription></DialogHeader>
          <div className="flex flex-wrap gap-3 text-sm">
            <span data-testid="oc-mass-sum-ready">Bisa ditetapkan: <b>{num(s.ready || 0)}</b></span>
            <span data-testid="oc-mass-sum-replay">Perlu Revaluasi (tidak ikut): <b>{num(s.needs_replay || 0)}</b></span>
            <span data-testid="oc-mass-sum-nosource">Tidak Ada Nilai Sumber: <b>{num(s.no_source || 0)}</b></span>
          </div>
          <div className="max-h-[50vh] overflow-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs text-muted-foreground dark:bg-slate-900"><tr>
                <th className="px-3 py-2">Item</th><th className="px-3 py-2">Gudang</th><th className="px-3 py-2 text-right">Qty Awal</th>
                <th className="px-3 py-2 text-right">Harga Awal</th><th className="px-3 py-2 text-right">Nilai Awal</th><th className="px-3 py-2">Status</th></tr></thead>
              <tbody>{ready.map((r) => <tr key={`${r.item_id}-${r.warehouse_id}`} className="border-t" data-testid={`oc-mass-row-${r.item_id}-${r.warehouse_id}`}>
                <td className="px-3 py-2">{r.item_code} — {r.item_name}</td><td className="px-3 py-2">{r.warehouse_name}</td>
                <td className="px-3 py-2 text-right tabular-nums">{num(r.opening_qty)}</td><td className="px-3 py-2 text-right tabular-nums">{rupiah(r.opening_cost)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{rupiah(r.opening_value)}</td><td className="px-3 py-2"><OpeningStatusBadge status={r.status} label={r.status_label} /></td></tr>)}</tbody>
            </table>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setMass(false)}>Batal</Button>
            <Button onClick={doMass} disabled={massBusy || !ready.length} data-testid="oc-mass-apply-btn"><CheckCircle2 className="mr-1.5 h-4 w-4" />{massBusy ? "Menetapkan…" : `Tetapkan ${num(ready.length)} pool`}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={applyOpen} onOpenChange={setApplyOpen}>
        <DialogContent data-testid="oc-apply-dialog">
          <DialogHeader><DialogTitle>Terapkan Revaluasi Saldo Awal</DialogTitle>
            <DialogDescription>Hasil valuasi {num(ds.replayable || 0)} barang ({num(ds.affected_txns || 0)} transaksi, {num(ds.affected_hpp || 0)} HPP) akan diganti sesuai Dry Run. Proses tercatat (siapa, kapan, sebelum/sesudah) dan hanya dapat diterapkan sekali.</DialogDescription></DialogHeader>
          <p className="text-sm">Ketik <b>{dry?.confirm_phrase}</b> untuk melanjutkan.</p>
          <Input value={phrase} onChange={(e) => setPhrase(e.target.value)} data-testid="oc-apply-phrase" />
          <DialogFooter><Button variant="outline" onClick={() => setApplyOpen(false)}>Batal</Button>
            <Button variant="destructive" disabled={applyBusy || phrase.trim().toUpperCase() !== dry?.confirm_phrase} onClick={doApply} data-testid="oc-apply-confirm">{applyBusy ? "Menerapkan…" : "Terapkan"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </CardContent>
  </Card>;
}
