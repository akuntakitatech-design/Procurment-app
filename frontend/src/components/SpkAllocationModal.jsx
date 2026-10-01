import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Combobox } from "@/components/Combobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Plus, Trash2, ShieldCheck, Layers, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const num = (v) => Number(v || 0);
const rupiah = (v) => `Rp ${num(v).toLocaleString("id-ID")}`;

// Horizontal compact allocation text, e.g. "SPK-001: 3 • SPK-002: 4 • Non-SPK: 3"
export function formatAllocText(summary) {
  if (!summary) return "Non-SPK";
  const parts = (summary.allocations || []).map((a) => `${a.spk_number || a.spk_id}: ${num(a.allocated_qty)}`);
  const nonSpk = num(summary.non_spk_qty);
  if (parts.length === 0) return `Non-SPK: ${num(summary.item_qty)}`;
  if (nonSpk > 1e-9) parts.push(`Non-SPK: ${nonSpk}`);
  return parts.join(" • ");
}

// Doc-level allocation fetch -> map lineId->summary + server-authoritative perms
export function useDocAllocations(sourceType, docId) {
  const [data, setData] = useState(null);
  const reload = useCallback(() => {
    if (!docId) { setData(null); return; }
    api.get(`/spk-allocations/${sourceType}/doc/${docId}`).then((r) => setData(r.data)).catch(() => setData(null));
  }, [sourceType, docId]);
  useEffect(() => { reload(); }, [reload]);
  const map = {};
  (data?.lines || []).forEach((l) => { map[l.item_line_id] = l; });
  return { map, status: data?.status, canManage: !!data?.can_manage, canVerify: !!data?.can_verify, reload };
}

// ---------------------------------------------------------------------------
// Reusable "Alokasi SPK" modal for a single MRO / RO / PO item line.
// Non-SPK is the automatic remainder (never entered by the user).
// ---------------------------------------------------------------------------
export function SpkAllocationModal({ open, onClose, sourceType, lineId, docStatus, canManage, canVerify, poId, onChanged, localMode = false, itemQty: itemQtyProp, unit: unitProp, initialAllocations, onLocalSave }) {
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [spks, setSpks] = useState([]);
  const [reason, setReason] = useState("");
  const [available, setAvailable] = useState(null);
  const [saving, setSaving] = useState(false);
  const isPo = sourceType === "po";
  const editable = canManage && (sourceType !== "po" ? (docStatus !== "Cancelled") : ["Draft", "Waiting Approval"].includes(docStatus));

  const load = useCallback(() => {
    if (!open) return;
    api.get("/spk?status=active&page_size=200").then((r) => setSpks(r.data.items || r.data || [])).catch(() => {});
    if (localMode) {
      setSummary({ item_qty: num(itemQtyProp), unit: unitProp, allocations: initialAllocations || [] });
      setRows((initialAllocations || []).map((a) => ({ spk_id: a.spk_id, allocated_qty: a.allocated_qty })));
      return;
    }
    if (!lineId) return;
    api.get(`/spk-allocations/${sourceType}/line/${lineId}`).then((r) => {
      setSummary(r.data);
      setRows((r.data.allocations || []).map((a) => ({ spk_id: a.spk_id, allocated_qty: a.allocated_qty })));
    }).catch((e) => toast.error(apiError(e.response?.data?.detail)));
    if (isPo) api.get(`/spk-allocations/po/line/${lineId}/available`).then((r) => setAvailable(r.data)).catch(() => {});
  }, [open, lineId, sourceType, isPo, localMode, itemQtyProp, unitProp, initialAllocations]);
  useEffect(() => { load(); }, [load]);

  if (!open) return null;
  const itemQty = num(summary?.item_qty);
  const totalSpk = rows.reduce((s, r) => s + num(r.allocated_qty), 0);
  const nonSpk = Math.max(0, itemQty - totalSpk);
  const over = totalSpk - itemQty > 1e-6;

  const setRow = (i, k, v) => setRows((cur) => cur.map((r, idx) => idx === i ? { ...r, [k]: v } : r));
  const addRow = () => setRows((cur) => [...cur, { spk_id: "", allocated_qty: "" }]);
  const delRow = (i) => setRows((cur) => cur.filter((_, idx) => idx !== i));

  const spkOpts = spks.map((s) => ({ value: s.id, label: `${s.spk_number} — ${s.project_name || ""}` }));

  const save = async () => {
    if (over) { toast.error("Total alokasi SPK melebihi Qty item"); return; }
    const cleaned = rows.filter((r) => r.spk_id && num(r.allocated_qty) > 0)
      .map((r) => ({ spk_id: r.spk_id, allocated_qty: num(r.allocated_qty) }));
    if (localMode) {
      // detect duplicate SPK locally
      const seen = new Set();
      for (const c of cleaned) { if (seen.has(c.spk_id)) { toast.error("SPK duplikat pada satu item"); return; } seen.add(c.spk_id); }
      onLocalSave?.(cleaned);
      toast.success("Alokasi SPK disimpan (akan dipersist saat MRO disimpan)");
      onClose?.();
      return;
    }
    if (sourceType !== "mro" && (summary?.allocations || []).length > 0 && !reason.trim()) {
      toast.error("Alasan perubahan wajib diisi untuk alokasi warisan"); return;
    }
    const payload = { allocations: cleaned, reason: reason || undefined };
    setSaving(true);
    try {
      await api.put(`/spk-allocations/${sourceType}/line/${lineId}`, payload);
      toast.success("Alokasi SPK tersimpan");
      onChanged?.(); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const verify = async () => {
    try {
      const r = await api.post(`/spk-allocations/po/${poId}/verify`);
      toast.success("Alokasi SPK PO terverifikasi");
      (r.data?.warnings || []).forEach((w) => toast.warning(w));
      onChanged?.(); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose?.()}>
      <DialogContent className="max-w-2xl" data-testid="spk-alloc-modal">
        <DialogHeader>
          <DialogTitle>Alokasi SPK</DialogTitle>
          <DialogDescription>
            Qty Item: <b>{itemQty} {summary?.unit || ""}</b>. Non-SPK dihitung otomatis sebagai sisa; Anda tidak perlu membuat baris Non-SPK.
          </DialogDescription>
        </DialogHeader>

        {isPo && available && (
          <div className="rounded-lg border bg-muted/30 p-3 text-xs" data-testid="spk-alloc-available">
            <div className="font-semibold mb-1">Sisa Alokasi dari RO (dapat dipakai PO ini):</div>
            {available.spk.length === 0 ? <span className="text-muted-foreground">Tidak ada alokasi SPK dari RO.</span> :
              available.spk.map((a) => <span key={a.spk_id} className="mr-3">{a.spk_number}: <b>{a.available}</b></span>)}
          </div>
        )}

        <div className="space-y-2">
          {rows.map((r, i) => (
            <div key={i} className="flex items-center gap-2" data-testid={`spk-alloc-row-${i}`}>
              <div className="flex-1"><Combobox options={spkOpts} value={r.spk_id} onChange={(v) => setRow(i, "spk_id", v)} placeholder="Pilih SPK (Active)" disabled={!editable} /></div>
              <Input type="number" min="0" step="any" className="w-28" value={r.allocated_qty} onChange={(e) => setRow(i, "allocated_qty", e.target.value)} placeholder="Qty" disabled={!editable} data-testid={`spk-alloc-qty-${i}`} />
              {editable && <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => delRow(i)} data-testid={`spk-alloc-del-${i}`}><Trash2 className="h-4 w-4 text-destructive" /></Button>}
            </div>
          ))}
          {rows.length === 0 && <p className="text-sm text-muted-foreground">Belum ada alokasi SPK. Seluruh qty dianggap Non-SPK.</p>}
          {editable && <Button variant="outline" size="sm" onClick={addRow} data-testid="spk-alloc-add"><Plus className="h-4 w-4 mr-1" />Tambah SPK</Button>}
        </div>

        <div className="rounded-lg border p-3 text-sm grid grid-cols-3 gap-2" data-testid="spk-alloc-totals">
          <div>Total SPK: <b data-testid="spk-alloc-total-spk">{totalSpk}</b></div>
          <div>Non-SPK: <b data-testid="spk-alloc-non-spk">{nonSpk}</b></div>
          <div className={over ? "text-destructive font-semibold" : "text-emerald-600"}>{totalSpk + nonSpk} / {itemQty} {over ? "⚠ melebihi" : "✓"}</div>
        </div>

        {editable && (sourceType !== "mro") && (
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Alasan perubahan (wajib bila mengubah alokasi warisan)" data-testid="spk-alloc-reason" />
        )}

        <DialogFooter className="gap-2">
          {isPo && canVerify && ["Draft", "Waiting Approval"].includes(docStatus) && (
            <Button variant="outline" onClick={verify} data-testid="spk-alloc-verify"><ShieldCheck className="h-4 w-4 mr-1" />Verifikasi</Button>
          )}
          <Button variant="outline" onClick={onClose} data-testid="spk-alloc-close">Tutup</Button>
          {editable && <Button onClick={save} disabled={saving || over} data-testid="spk-alloc-save">{saving ? "Menyimpan..." : "Simpan Alokasi"}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// PO Budget Summary per SPK (doc-level) — shows Current Procurement Budget,
// existing commitment, projected remaining and policy decision per SPK.
// ---------------------------------------------------------------------------
export function PoBudgetSummary({ poId, refreshKey }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!poId) return;
    api.get(`/spk-allocations/po/${poId}/budget-summary`).then((r) => setData(r.data)).catch(() => setData(null));
  }, [poId, refreshKey]);
  if (!data) return null;
  const perSpk = data.per_spk || [];
  const tone = (st) => st === "block" ? "text-destructive" : st === "warning" ? "text-amber-600" : "text-emerald-600";
  const label = (st) => st === "block" ? "HARD_BLOCK" : st === "warning" ? "WARNING" : "OK";
  return (
    <div className="mt-3" data-testid="po-budget-summary">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-semibold text-sm">Ringkasan Budget per SPK</span>
        {data.committed
          ? <Badge variant="secondary" data-testid="po-budget-committed">Commitment Aktif</Badge>
          : <Badge variant="outline" data-testid="po-budget-uncommitted">Belum Commit</Badge>}
        {data.verified && <Badge variant="secondary" data-testid="po-budget-verified"><CheckCircle2 className="h-3 w-3 mr-1" />Terverifikasi</Badge>}
      </div>
      {perSpk.length === 0 ? (
        <p className="text-sm text-muted-foreground">Tidak ada alokasi SPK pada PO ini (seluruhnya Non-SPK, tidak di-commit).</p>
      ) : (
        <div className="border rounded-md overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr className="text-left text-xs uppercase text-muted-foreground">
                <th className="p-2">SPK</th>
                <th className="p-2 text-right">Budget</th>
                <th className="p-2 text-right">Commitment Berjalan</th>
                <th className="p-2 text-right">Nilai PO Ini</th>
                <th className="p-2 text-right">Sisa Proyeksi</th>
                <th className="p-2">Policy</th>
              </tr>
            </thead>
            <tbody>
              {perSpk.map((s, i) => (
                <tr key={s.spk_id} className="border-t" data-testid={`po-budget-row-${i}`}>
                  <td className="p-2"><b>{s.spk_number}</b><div className="text-xs text-muted-foreground">{s.project_name || ""}</div></td>
                  <td className="p-2 text-right">{rupiah(s.current_procurement_budget)}</td>
                  <td className="p-2 text-right">{rupiah(s.existing_commitment)}</td>
                  <td className="p-2 text-right">{rupiah(s.po_amount)}</td>
                  <td className={`p-2 text-right font-semibold ${s.projected_remaining < 0 ? "text-destructive" : ""}`}>{rupiah(s.projected_remaining)}</td>
                  <td className={`p-2 font-semibold ${tone(s.status)}`}>
                    <span className="inline-flex items-center gap-1">
                      {s.status === "block" ? <AlertTriangle className="h-3.5 w-3.5" /> : s.status === "warning" ? <AlertTriangle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                      {label(s.status)}
                      <span className="text-xs font-normal text-muted-foreground">({s.policy})</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.blocked && (
        <p className="text-xs text-destructive mt-2" data-testid="po-budget-block-note">
          HARD_BLOCK: finalisasi (Approve) akan ditolak selama ada SPK melebihi Current Procurement Budget.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Doc-level allocation panel — usable during create/edit AND detail view.
// Lists each item line with its SPK/Non-SPK split and opens the modal.
// Server-authoritative can_manage / can_verify from the doc endpoint.
// ---------------------------------------------------------------------------
export function AllocationPanel({ sourceType, docId, docStatus, poId, onChanged }) {
  const [data, setData] = useState(null);
  const [allocLine, setAllocLine] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    if (!docId) return;
    api.get(`/spk-allocations/${sourceType}/doc/${docId}`).then((r) => setData(r.data)).catch(() => setData(null));
  }, [sourceType, docId]);
  useEffect(() => { load(); }, [load]);

  if (!docId) return null;
  const lines = data?.lines || [];
  const canManage = !!data?.can_manage;
  const canVerify = !!data?.can_verify;
  const bump = () => { setRefreshKey((k) => k + 1); load(); onChanged?.(); };

  return (
    <Card data-testid="spk-alloc-panel">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base font-head">
          <Layers className="h-4 w-4" />Alokasi SPK per Item
          {sourceType === "po" && data?.status && <Badge variant="outline">{data.status}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {lines.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada item untuk dialokasikan.</p>
        ) : (
          <div className="border rounded-md overflow-x-auto">
            <table className="w-full text-sm zebra">
              <thead className="bg-muted">
                <tr className="text-left text-xs uppercase text-muted-foreground">
                  <th className="p-2">Barang</th>
                  <th className="p-2 text-right">Qty</th>
                  <th className="p-2 text-right">Total SPK</th>
                  <th className="p-2 text-right">Non-SPK</th>
                  <th className="p-2">SPK</th>
                  <th className="p-2 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={l.item_line_id} className="border-t" data-testid={`spk-alloc-panel-row-${i}`}>
                    <td className="p-2">{l.item_id}</td>
                    <td className="p-2 text-right">{num(l.item_qty)} {l.unit || ""}</td>
                    <td className="p-2 text-right font-semibold">{num(l.total_spk_qty)}</td>
                    <td className="p-2 text-right">{num(l.non_spk_qty)}</td>
                    <td className="p-2">
                      {(l.allocations || []).length === 0
                        ? <span className="text-xs text-muted-foreground">Non-SPK penuh</span>
                        : (l.allocations || []).map((a) => <Badge key={a.spk_id} variant="outline" className="mr-1 mb-1">{a.spk_number}: {num(a.allocated_qty)}</Badge>)}
                      {l.is_over && <Badge variant="destructive" className="ml-1">melebihi</Badge>}
                    </td>
                    <td className="p-2 text-right">
                      <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setAllocLine(l.item_line_id)} data-testid={`${sourceType}-alloc-btn-${i}`}>
                        {canManage ? "Alokasi SPK" : "Lihat"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {sourceType === "po" && <PoBudgetSummary poId={poId || docId} refreshKey={refreshKey} />}
      </CardContent>

      {allocLine && (
        <SpkAllocationModal
          open={!!allocLine}
          onClose={() => setAllocLine(null)}
          sourceType={sourceType}
          lineId={allocLine}
          docStatus={docStatus || data?.status}
          poId={poId || docId}
          canManage={canManage}
          canVerify={canVerify}
          onChanged={bump}
        />
      )}
    </Card>
  );
}
