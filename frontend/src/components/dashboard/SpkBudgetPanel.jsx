import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Briefcase, CircleAlert, FileCheck2, Landmark, PackageCheck, PiggyBank, ShieldAlert, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SPK_LEVEL, barPct, compactRupiah, pctText, spkDetailLink, spkSummaryCards } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import { EmptyNote, Panel } from "./Panel";
import { RingKpi, SubLabel } from "./RingKpi";

const ICONS = { active: Briefcase, budget: Landmark, commitment: FileCheck2, realization: PackageCheck, open_commitment: Wallet,
  remaining: PiggyBank, over_budget: CircleAlert, critical: ShieldAlert, attention: AlertTriangle };

function Flag({ children }) {
  return <span className={`rounded-full px-1.5 py-px text-[10.5px] ${/Over|Kritis/.test(children) ? SPK_LEVEL.over.chip : SPK_LEVEL.warning.chip}`}>{children}</span>;
}

/** Layer 2 — kartu ringkas SPK & Budget Control (posisi s/d cut-off). Nominal hanya bila backend mengirim (spk:view). */
export function SpkSummaryCard({ spk, subtitle, onDrill, delay = 0 }) {
  const wv = !!spk?.with_value;
  const [shown, setShown] = useState(false);
  useEffect(() => { const t = setTimeout(() => setShown(true), 140); return () => clearTimeout(t); }, [spk]);
  const cards = spkSummaryCards(spk);
  const usage = spk?.kpi?.usage_pct;
  const lv = SPK_LEVEL[usage > 100 ? "over" : usage > 90 ? "critical" : usage >= 80 ? "warning" : "normal"];
  return <Panel title="SPK & Budget Control" subtitle={subtitle} icon={Briefcase} testid="dash-spk" delay={delay} className="h-full"
    action={wv && <Button variant="ghost" size="sm" onClick={() => onDrill("active")} className="h-8 shrink-0 rounded-lg text-[#3D5A80]" data-testid="dash-spk-detail">Lihat Detail<ArrowRight className="ml-1 h-3.5 w-3.5" /></Button>}>
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2" data-testid="dash-spk-kpis">
      {cards.map((c, i) => <RingKpi key={c.key} label={c.label} icon={ICONS[c.key]} tone={c.tone} value={c.value} pct={c.pct}
        format={c.money ? compactRupiah : undefined} title={c.money ? rupiah(c.value) : undefined} sub={c.sub} delay={delay + i * 40}
        onClick={wv && c.drill ? () => onDrill(c.drill) : undefined} testid={`dash-spk-kpi-${c.key}`} />)}
    </div>
    {wv && <div className="mt-3.5" data-testid="dash-spk-usage">
      <div className="flex items-center justify-between text-[11.5px] text-slate-500"><span>Pemakaian budget (commitment ÷ budget)</span>
        <b className={`tabular-nums ${lv.text}`} data-testid="dash-spk-usage-pct">{pctText(usage)}</b></div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className="h-full origin-left rounded-full transition-transform duration-700 ease-out" style={{ background: lv.bar, transform: `scaleX(${shown ? barPct(usage) / 100 : 0})` }} />
      </div>
    </div>}
    {!wv && <p className="mt-3 text-[12px] text-slate-400" data-testid="dash-spk-novalue">Nilai budget, commitment, dan daftar SPK hanya tampil untuk pengguna dengan izin Lihat SPK.</p>}
  </Panel>;
}

/** Detail SPK (section lanjutan): Top 5 Pemakaian Budget + SPK Perlu Perhatian. Hanya dengan spk:view (daftar dari backend). */
export function SpkDetailPanel({ spk, onDrill, nav, delay = 0 }) {
  const [shown, setShown] = useState(false);
  useEffect(() => { const t = setTimeout(() => setShown(true), 140); return () => clearTimeout(t); }, [spk]);
  if (!spk?.with_value) return null;
  return <Panel title="Pemakaian Budget SPK" icon={Briefcase} testid="dash-spk-lists" delay={delay}>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="min-w-0" data-testid="dash-spk-top">
        <SubLabel>Top 5 Pemakaian Budget SPK</SubLabel>
        {!spk?.top?.length ? <EmptyNote>Belum ada SPK aktif untuk filter ini.</EmptyNote> :
          <ol className="space-y-3.5">
            {spk.top.map((x, i) => { const lv = SPK_LEVEL[x.level] || SPK_LEVEL.normal; return <li key={x.id}>
              <button type="button" onClick={() => nav(spkDetailLink(x.id))} data-testid={`dash-spk-top-${i + 1}`}
                title={`Budget ${rupiah(x.budget)} · Commitment ${rupiah(x.commitment)} · Realisasi ${rupiah(x.realization)}`}
                className="group w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30">
                <div className="flex items-center gap-2 text-[13px]">
                  <span className="min-w-0 flex-1 truncate"><span className="font-medium text-slate-700 group-hover:text-[#2C4A6E] dark:text-slate-200">{x.spk_number}</span>
                    <span className="text-slate-400"> — {x.project_name || "Tanpa project"}</span></span>
                  <span className={`shrink-0 rounded-full px-1.5 py-px text-[10.5px] ${lv.chip}`}>{lv.label}</span>
                  <span className={`w-14 shrink-0 text-right font-semibold tabular-nums ${lv.text}`} data-testid={`dash-spk-top-${i + 1}-pct`}>{pctText(x.usage_pct)}</span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div className="h-full origin-left rounded-full transition-transform duration-700 ease-out" style={{ background: lv.bar, transform: `scaleX(${shown ? barPct(x.usage_pct) / 100 : 0})` }} />
                </div>
              </button></li>; })}
          </ol>}
        <div className="mt-4 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400" data-testid="dash-spk-legend">
          {Object.entries({ normal: "< 80%", warning: "80–90%", critical: "> 90%", over: "> 100%" }).map(([k2, t]) =>
            <span key={k2} className="flex items-center gap-1"><span className="h-1.5 w-3 rounded-full" style={{ background: SPK_LEVEL[k2].bar }} />{SPK_LEVEL[k2].label} {t}</span>)}
        </div>
      </div>
      <div className="min-w-0" data-testid="dash-spk-attention">
        <SubLabel extra={spk?.kpi?.attention > (spk?.attention?.length || 0) && <button type="button" onClick={() => onDrill("attention")} className="text-[11px] font-medium text-[#3D5A80] hover:underline" data-testid="dash-spk-attention-all">Lihat {spk.kpi.attention} SPK</button>}>SPK Perlu Perhatian</SubLabel>
        {!spk?.attention?.length ? <EmptyNote>Tidak ada SPK yang perlu perhatian.</EmptyNote> :
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {spk.attention.map((x, i) => { const lv = SPK_LEVEL[x.level] || SPK_LEVEL.normal; return <li key={x.id}>
              <button type="button" onClick={() => nav(spkDetailLink(x.id))} data-testid={`dash-spk-attn-${i + 1}`}
                className="flex w-full items-start gap-2.5 rounded-md px-1 py-2 text-left transition-colors hover:bg-slate-50/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30 dark:hover:bg-slate-800/40">
                <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${lv.chip}`}><AlertTriangle className="h-3 w-3" /></span>
                <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium text-slate-700 dark:text-slate-200">{x.spk_number} <span className="font-normal text-slate-400">· {x.project_name || "-"}</span></span>
                  <span className="mt-1 flex flex-wrap gap-1">{x.flags.map((fl) => <Flag key={fl}>{fl}</Flag>)}</span></span>
                <span className="shrink-0 text-right"><span className={`block text-xs font-semibold tabular-nums ${lv.text}`}>{pctText(x.usage_pct)}</span>
                  <span className="block text-[10.5px] tabular-nums text-slate-400">sisa {compactRupiah(x.remaining)}</span></span>
              </button></li>; })}
          </ul>}
      </div>
    </div>
  </Panel>;
}
