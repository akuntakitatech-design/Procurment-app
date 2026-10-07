import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DRILL_ENDPOINT, SPK_LEVEL, asOfLabel, contractDetailLink, pctText, poDetailLink, spkDetailLink } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import { PriceBadge } from "./VendorContractPanel";

const TITLES = {
  spk: { active: "SPK Aktif", over: "SPK Over Budget", critical: "SPK Kritis (> 90%)", attention: "SPK Perlu Perhatian", expiring: "SPK Akan Berakhir ≤ 30 Hari" },
  contract: { active: "Kontrak Aktif", expiring: "Kontrak Akan Berakhir ≤ 30 Hari", expired: "Kontrak Kedaluwarsa" },
  price: { ok: "PO Sesuai Harga Kontrak", over: "PO Di Atas Tolerance", no_contract: "PO Tanpa Kontrak Aktif", all: "Seluruh Baris Price Control" },
};

function Th({ children, right }) {
  return <th className={`whitespace-nowrap px-3 py-2 font-medium ${right ? "text-right" : ""}`}>{children}</th>;
}

function LinkBtn({ onClick, children, testid }) {
  return <button type="button" onClick={onClick} data-testid={testid}
    className="rounded font-medium text-[#3D5A80] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30">{children}</button>;
}

/** Drill-down Dashboard (SPK / Kontrak / Price Control). Data dari endpoint drill backend — fungsi & predikat sama
 *  dengan KPI, jadi jumlah/nilai = kartu. Klik baris membuka detail existing (SPK / Kontrak / PO). */
export function DashboardDrillDialog({ drill, onOpenChange, nav }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const type = drill?.type;
  useEffect(() => {
    if (!drill) return;
    setData(null); setErr(null);
    api.get(DRILL_ENDPOINT[drill.type], { params: drill.params })
      .then((r) => setData(r.data)).catch((e) => setErr(apiError(e.response?.data?.detail) || "Data gagal dimuat."));
  }, [drill]);
  const kind = drill?.params?.kind || drill?.params?.status;
  const title = (TITLES[type] || {})[kind] || "Detail";
  const desc = type === "price"
    ? `${drill?.params?.date_from ? `Transaksi periode ${asOfLabel(drill.params.date_from)} – ${asOfLabel(drill.params.date_to)}` : "Transaksi semua periode"} · PO Approved final · harga efektif sebelum pajak`
    : `Posisi s/d ${asOfLabel(drill?.params?.date_to)}`;
  const go = (url) => { onOpenChange(false); nav(url); };
  const rows = data?.rows || [];
  const wv = type === "spk" ? true : !!data?.with_value;
  return <Dialog open={!!drill} onOpenChange={onOpenChange}>
    <DialogContent className="max-h-[90vh] w-[calc(100vw-1.5rem)] max-w-5xl overflow-hidden" data-testid="dash-drill-dialog">
      <DialogHeader><DialogTitle data-testid="dash-drill-title">{title}</DialogTitle>
        <DialogDescription data-testid="dash-drill-desc">{desc}</DialogDescription></DialogHeader>
      {err && <div className="rounded-xl border border-[#EEDADA] bg-[#FBF3F3] p-3 text-sm text-[#8F3F3F]" data-testid="dash-drill-error">{err}</div>}
      {data && <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600" data-testid="dash-drill-summary">
        <span>Jumlah: <b className="tabular-nums text-slate-800" data-testid="dash-drill-count">{type === "price" ? `${data.po_count} PO · ${data.count} baris` : data.count}</b></span>
        {type === "spk" && data.totals && <>
          <span>Budget: <b className="tabular-nums" data-testid="dash-drill-total-budget">{rupiah(data.totals.budget)}</b></span>
          <span>Commitment: <b className="tabular-nums">{rupiah(data.totals.commitment)}</b></span>
          <span>Realisasi: <b className="tabular-nums">{rupiah(data.totals.realization)}</b></span>
          <span>Sisa Budget: <b className="tabular-nums">{rupiah(data.totals.remaining)}</b></span></>}
        {type === "price" && data.diff_value != null && <span>Nilai Selisih: <b className="tabular-nums" data-testid="dash-drill-diff">{rupiah(data.diff_value)}</b></span>}
      </div>}
      <div className="max-h-[58vh] overflow-auto rounded-xl border border-slate-200/70 dark:border-slate-800">
        {!data && !err ? <div className="space-y-2 p-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-7 w-full" />)}</div> :
          <table className="w-full min-w-[720px] text-[13px]">
            <thead className="sticky top-0 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-400 dark:bg-slate-900">
              {type === "spk" && <tr><Th>SPK</Th><Th>Project</Th><Th>Berakhir</Th><Th right>Budget</Th><Th right>Commitment</Th><Th right>Realisasi</Th><Th right>Open</Th><Th right>Sisa</Th><Th right>Pemakaian</Th></tr>}
              {type === "contract" && <tr><Th>No. Kontrak</Th><Th>Vendor</Th><Th>Mulai</Th><Th>Berakhir</Th><Th right>Item</Th><Th>Status per posisi</Th></tr>}
              {type === "price" && <tr><Th>PO</Th><Th>Vendor</Th><Th>Barang</Th>{wv && <><Th right>Harga Kontrak</Th><Th right>Harga PO</Th><Th right>Tolerance</Th><Th right>Selisih</Th></>}<Th>Status</Th></tr>}
            </thead>
            <tbody>
              {type === "spk" && rows.map((x, i) => { const lv = SPK_LEVEL[x.level] || SPK_LEVEL.normal; return <tr key={x.id} className="border-t border-slate-100 dark:border-slate-800" data-testid={`dash-drill-row-${i + 1}`}>
                <td className="px-3 py-2"><LinkBtn onClick={() => go(spkDetailLink(x.id))} testid={`dash-drill-row-${i + 1}-link`}>{x.spk_number}</LinkBtn>
                  {x.flags?.length > 0 && <div className="mt-0.5 flex flex-wrap gap-1">{x.flags.map((fl) => <span key={fl} className={`rounded-full px-1.5 py-px text-[10.5px] ${/Over|Kritis/.test(fl) ? SPK_LEVEL.over.chip : SPK_LEVEL.warning.chip}`}>{fl}</span>)}</div>}</td>
                <td className="px-3 py-2 text-slate-600">{x.project_name || "-"}</td><td className="whitespace-nowrap px-3 py-2 text-slate-500">{asOfLabel(x.end_date)}</td>
                {["budget", "commitment", "realization", "open_commitment", "remaining"].map((k) => <td key={k} className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${k === "remaining" && x[k] < 0 ? "text-[#A34B4B]" : "text-slate-700 dark:text-slate-200"}`}>{rupiah(x[k])}</td>)}
                <td className={`px-3 py-2 text-right font-semibold tabular-nums ${lv.text}`}>{pctText(x.usage_pct)}</td></tr>; })}
              {type === "contract" && rows.map((x, i) => <tr key={x.id} className="border-t border-slate-100 dark:border-slate-800" data-testid={`dash-drill-row-${i + 1}`}>
                <td className="px-3 py-2"><LinkBtn onClick={() => go(contractDetailLink(x.id))} testid={`dash-drill-row-${i + 1}-link`}>{x.contract_number}</LinkBtn></td>
                <td className="px-3 py-2 text-slate-600">{x.supplier_name}</td><td className="whitespace-nowrap px-3 py-2 text-slate-500">{asOfLabel(x.start_date)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-500">{asOfLabel(x.end_date)}</td><td className="px-3 py-2 text-right tabular-nums">{x.items}</td>
                <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-[11px] ${x.expired ? SPK_LEVEL.over.chip : x.expiring ? SPK_LEVEL.warning.chip : "bg-[#EEF6F2] text-[#3D7A62]"}`}>{x.expired ? "Kedaluwarsa" : x.expiring ? "Akan berakhir" : "Aktif"}</span></td></tr>)}
              {type === "price" && rows.map((r, i) => <tr key={`${r.po_id}-${r.item_id}-${i}`} className="border-t border-slate-100 dark:border-slate-800" data-testid={`dash-drill-row-${i + 1}`}>
                <td className="px-3 py-2"><LinkBtn onClick={() => go(poDetailLink(r.po_id))} testid={`dash-drill-row-${i + 1}-link`}>{r.po_no}</LinkBtn><div className="text-[11px] text-slate-400">{asOfLabel(r.po_date)}</div></td>
                <td className="px-3 py-2 text-slate-600">{r.supplier_name}</td>
                <td className="px-3 py-2"><div className="text-slate-700 dark:text-slate-200">{r.item_name}</div><div className="text-[11px] text-slate-400">{r.qty?.toLocaleString("id-ID")} {r.uom || ""}</div></td>
                {wv && <><td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{r.contract_price == null ? "–" : rupiah(r.contract_price)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{rupiah(r.po_price)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">{r.tolerance_pct == null ? "–" : pctText(r.tolerance_pct)}</td>
                  <td className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${r.status === "over" ? "font-semibold text-[#A34B4B]" : "text-slate-500"}`}>{r.diff == null ? "–" : rupiah(r.diff)}</td></>}
                <td className="px-3 py-2"><PriceBadge status={r.status} testid={`dash-drill-row-${i + 1}-status`} /></td></tr>)}
              {data && !rows.length && <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-400" data-testid="dash-drill-empty">Tidak ada data untuk filter ini.</td></tr>}
            </tbody>
          </table>}
      </div>
      <div className="flex justify-end"><Button variant="outline" onClick={() => onOpenChange(false)} className="rounded-xl" data-testid="dash-drill-close">Tutup</Button></div>
    </DialogContent>
  </Dialog>;
}
