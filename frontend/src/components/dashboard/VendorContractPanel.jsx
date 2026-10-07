import { ArrowRight, BadgeCheck, CalendarClock, CalendarX2, FileSignature, Layers, PackageSearch, Scale, TrendingUp, Unlink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PRICE_STATUS, asOfLabel, compactRupiah, contractKpiCards, exceptionColumns, pctText, poDetailLink, priceKpiCards } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import { EmptyNote, Panel } from "./Panel";
import { RingKpi, SubLabel } from "./RingKpi";

const C_ICONS = { active: BadgeCheck, expiring: CalendarClock, expired: CalendarX2, items: Layers };
const P_ICONS = { ok: Scale, over: TrendingUp, no_contract: Unlink, diff: PackageSearch };

export function PriceBadge({ status, testid }) {
  const m = PRICE_STATUS[status] || PRICE_STATUS.ok;
  return <span className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${m.cls}`} data-testid={testid}>{m.label}</span>;
}

/** Layer 2 — Kontrak Harga Vendor: status kontrak POSISI s/d cut-off (date_to). Selalu count. */
export function ContractStatusPanel({ vc, posLabel, onDrill, canDrill, nav, delay = 0 }) {
  const cards = contractKpiCards(vc?.contracts);
  return <Panel title="Kontrak Harga Vendor" subtitle={<span data-testid="dash-contract-asof">{posLabel}</span>} icon={FileSignature} testid="dash-contract" delay={delay} className="h-full"
    action={canDrill && <Button variant="ghost" size="sm" onClick={() => nav("/vendor-contracts")} className="h-8 shrink-0 rounded-lg text-[#3D5A80]" data-testid="dash-contract-detail">Lihat Detail<ArrowRight className="ml-1 h-3.5 w-3.5" /></Button>}>
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-2" data-testid="dash-contract-kpis">
      {cards.map((c, i) => <RingKpi key={c.key} label={c.label} icon={C_ICONS[c.key]} tone={c.tone} value={c.value} pct={c.pct} sub={c.sub}
        delay={delay + i * 40} onClick={canDrill && c.drill ? () => onDrill(c.drill) : undefined} testid={`dash-contract-kpi-${c.key}`} />)}
    </div>
  </Panel>;
}

/** Price Control — TRANSAKSI periode (date_from + date_to), PO Approved final. Nominal hanya bila backend mengirim. */
export function PriceControlPanel({ vc, actLabel, onDrill, delay = 0 }) {
  const pc = vc?.price_control;
  const wv = !!vc?.with_value;
  const cards = priceKpiCards(pc, wv);
  return <Panel title="Price Control" icon={Scale} testid="dash-price-control" delay={delay}>
    <SubLabel testid="dash-price-period" extra={<span className="text-[11px] text-slate-400">PO Approved final · harga sebelum pajak</span>}>{actLabel}</SubLabel>
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2" data-testid="dash-price-kpis">
      {cards.map((c, i) => <RingKpi key={c.key} label={c.label} icon={P_ICONS[c.key]} tone={c.tone} value={c.value} pct={c.pct} sub={c.sub}
        format={c.money ? compactRupiah : undefined} title={c.money ? rupiah(c.value) : undefined} delay={delay + i * 40}
        onClick={() => onDrill(c.drill)} testid={`dash-price-kpi-${c.key}`} />)}
    </div>
    {!wv && <p className="mt-3 text-[12px] text-slate-400" data-testid="dash-price-novalue">Harga kontrak, harga PO, dan selisih hanya tampil untuk pengguna dengan izin Lihat Kontrak Vendor dan Lihat Harga Beli.</p>}
  </Panel>;
}

/** Price Exception — maks. 8 baris; klik PO membuka detail PO existing. Read-only. */
export function PriceExceptionTable({ vc, actLabel, nav, onDrill, delay = 0 }) {
  const rows = vc?.price_control?.exceptions || [];
  const wv = !!vc?.with_value;
  const cols = exceptionColumns(wv);
  const right = new Set(["Harga Kontrak", "Harga PO", "Tolerance", "Selisih"]);
  const k = vc?.price_control?.kpi || {};
  const total = (k.lines_over || 0) + (k.lines_no_contract || 0);
  return <Panel title="Price Exception" icon={TrendingUp} testid="dash-price-exceptions" delay={delay}
    action={<span className="flex items-center gap-2"><span className="hidden rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-500 sm:inline dark:bg-slate-900" data-testid="dash-price-exceptions-period">{actLabel}</span>
      {total > rows.length && <Button variant="ghost" size="sm" onClick={() => onDrill("all")} className="h-8 rounded-lg text-[#3D5A80]" data-testid="dash-price-exceptions-all">Semua<ArrowRight className="ml-1 h-3.5 w-3.5" /></Button>}</span>}>
    {!rows.length ? <EmptyNote>Semua PO Approved pada periode ini sesuai harga kontrak.</EmptyNote> :
      <div className="-mx-1 overflow-x-auto" data-testid="dash-price-exceptions-scroll">
        <table className="w-full min-w-[720px] text-[13px]">
          <thead><tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-400 dark:border-slate-800">
            {cols.map((c) => <th key={c} className={`whitespace-nowrap px-2 py-2 font-medium ${right.has(c) ? "text-right" : ""}`}>{c}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={`${r.po_id}-${r.item_id}-${i}`} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60 dark:border-slate-800/60 dark:hover:bg-slate-800/30" data-testid={`dash-price-row-${i + 1}`}>
            <td className="px-2 py-2.5"><button type="button" onClick={() => nav(poDetailLink(r.po_id))} className="rounded font-medium text-[#3D5A80] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30" data-testid={`dash-price-row-${i + 1}-po`}>{r.po_no}</button>
              <div className="text-[11px] text-slate-400">{asOfLabel(r.po_date)}</div></td>
            <td className="max-w-[180px] truncate px-2 py-2.5 text-slate-700 dark:text-slate-200">{r.supplier_name}</td>
            <td className="max-w-[220px] px-2 py-2.5"><div className="truncate text-slate-700 dark:text-slate-200">{r.item_name}</div><div className="text-[11px] text-slate-400">{r.qty?.toLocaleString("id-ID")} {r.uom || ""}</div></td>
            {wv && <><td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-slate-600">{r.contract_price == null ? "–" : rupiah(r.contract_price)}</td>
              <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-slate-800 dark:text-slate-100">{rupiah(r.po_price)}</td>
              <td className="px-2 py-2.5 text-right tabular-nums text-slate-500">{r.tolerance_pct == null ? "–" : pctText(r.tolerance_pct)}</td>
              <td className={`whitespace-nowrap px-2 py-2.5 text-right tabular-nums ${r.status === "over" ? "font-semibold text-[#A34B4B]" : "text-slate-500"}`} data-testid={`dash-price-row-${i + 1}-diff`}>
                {r.diff == null ? "–" : <>{rupiah(r.diff)}<div className="text-[10.5px] font-normal">{pctText(r.diff_pct)}</div></>}</td></>}
            <td className="px-2 py-2.5"><PriceBadge status={r.status} testid={`dash-price-row-${i + 1}-status`} /></td>
          </tr>)}</tbody>
        </table>
      </div>}
  </Panel>;
}
