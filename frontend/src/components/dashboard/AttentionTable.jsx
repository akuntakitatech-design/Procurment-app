import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { ATTENTION_TABS, attentionRows, drillLink } from "@/lib/dashboard";
import { rupiah, fmtDate } from "@/lib/format";
import { ArrowRight, ListChecks } from "lucide-react";
import { EmptyNote, Panel } from "./Panel";

const SEE_ALL = { approval: "waiting_approval", not_received: "not_received", unbilled: "invoice_unbilled", unpaid: "unpaid", due: "due_soon" };
const PRIO_DOT = { 1: "bg-[#C46A6A]", 2: "bg-[#D4A04E]", 3: "bg-[#C46A6A]/70", 4: "bg-[#D4A04E]/70" };
const SHOW = 8;

export function AttentionTable({ attention, finance, filters, delay }) {
  const nav = useNavigate();
  const [tab, setTab] = useState("all");
  const tabs = ATTENTION_TABS.filter((t) => !t.finance || finance);
  const rows = useMemo(() => attentionRows(attention, tab), [attention, tab]);
  const counts = attention?.counts || {};
  const seeAll = tab !== "all" ? drillLink(SEE_ALL[tab], filters, {}) : null;
  return (
    <Panel title="PO / Invoice yang Perlu Ditindaklanjuti" icon={ListChecks} testid="dash-attention" delay={delay}
      action={seeAll && <button type="button" onClick={() => nav(seeAll)} className="flex items-center gap-1 text-xs font-medium text-[#3F6E9C] hover:underline" data-testid="dash-attention-see-all">Lihat Semua<ArrowRight className="h-3.5 w-3.5" /></button>}>
      <div className="mb-3 flex flex-wrap gap-1.5" role="tablist">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)} data-testid={`dash-attention-tab-${t.key}`}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 ${tab === t.key ? "bg-[#2C4A6E] text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100 dark:bg-slate-800/60 dark:text-slate-300"}`}>
            {t.label} <span className="tabular-nums opacity-80">({counts[t.key] ?? 0})</span>
          </button>
        ))}
      </div>
      {!rows.length ? <EmptyNote>Tidak ada dokumen yang perlu ditindaklanjuti.</EmptyNote> :
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full min-w-[600px] text-[13px]" data-testid="dash-attention-table">
            <thead><tr className="border-b border-slate-100 text-left text-[11px] font-medium uppercase tracking-wide text-slate-400 dark:border-slate-800">
              {["No", "Dokumen", "Supplier / Project", "Nilai", "Status", "Jatuh Tempo"].map((h, i) =>
                <th key={i} className={`px-1.5 py-2 font-medium ${h === "Nilai" ? "text-right" : ""}`}>{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.slice(0, SHOW).map((r, i) => (
                <tr key={r.key} onClick={() => nav(r.path)} className="cursor-pointer border-b border-slate-50 transition-colors duration-150 hover:bg-slate-50/70 dark:border-slate-800/60 dark:hover:bg-slate-800/30" data-testid={`dash-attention-row-${i}`}>
                  <td className="px-1.5 py-2.5 text-slate-400 tabular-nums"><span className="flex items-center gap-2"><i className={`h-1.5 w-1.5 rounded-full ${PRIO_DOT[r.priority] || "bg-slate-300"}`} title={r.reason} />{i + 1}</span></td>
                  <td className="px-1.5 py-2.5"><button type="button" onClick={(e) => { e.stopPropagation(); nav(r.path); }} className="text-left font-medium text-[#3F6E9C] hover:underline" data-testid={`dash-attention-doc-${i}`}>{r.no || "-"}</button><div className="text-[11px] text-slate-400">{r.doc_type} · {r.reason}</div></td>
                  <td className="max-w-[180px] px-1.5 py-2.5"><div className="truncate text-slate-700" title={r.supplier_name}>{r.supplier_name || "-"}</div>
                    <div className="truncate text-[11px] text-slate-400" title={[r.project, r.division].filter(Boolean).join(" · ")}>{[r.project, r.division].filter(Boolean).join(" · ") || "-"}</div></td>
                  <td className="whitespace-nowrap px-1.5 py-2.5 text-right tabular-nums text-slate-800">{r.value == null ? "***" : rupiah(r.value)}</td>
                  <td className="px-1.5 py-2.5"><div className="flex flex-col items-start gap-1">{r.document_status ? <StatusBadge status={r.document_status} /> : "-"}{r.payment_status && <StatusBadge status={r.payment_status} />}</div></td>
                  <td className={`whitespace-nowrap px-1.5 py-2.5 tabular-nums ${r.priority === 1 ? "text-[#A34B4B]" : "text-slate-600"}`}>{r.due_date ? fmtDate(r.due_date) : r.eta && r.priority === 3 ? <span className="text-[#A34B4B]"><span className="block text-[10px] uppercase tracking-wide">ETA</span>{fmtDate(r.eta)}</span> : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > SHOW && <div className="px-2 pt-2 text-xs text-slate-400">Menampilkan {SHOW} dari {rows.length} dokumen paling urgent.</div>}
        </div>}
    </Panel>
  );
}
