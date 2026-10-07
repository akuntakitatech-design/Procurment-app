import { useEffect, useState } from "react";
import { compactRupiah } from "@/lib/dashboard";
import { Trophy } from "lucide-react";
import { EmptyNote, Panel } from "./Panel";

export function TopSuppliers({ rank, onPick, delay }) {
  const items = rank?.items || [];
  const byValue = rank?.metric === "po_value";
  const max = Math.max(1, ...items.map((x) => (byValue ? x.value : x.count) || 0));
  const [shown, setShown] = useState(false);
  useEffect(() => { const t = setTimeout(() => setShown(true), 120); return () => clearTimeout(t); }, [rank]);
  return (
    <Panel title="Top 5 Supplier" icon={Trophy} testid="dash-top-suppliers" delay={delay}
      action={<span className="rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-500">{byValue ? "Nilai PO" : "Jumlah PO"}</span>}>
      {!items.length ? <EmptyNote /> :
        <ol className="space-y-3.5">
          {items.map((x, i) => (
            <li key={x.supplier_id}>
              <button type="button" onClick={() => onPick?.(x.supplier_id)} data-testid={`dash-supplier-${i + 1}`}
                className="group w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30">
                <div className="flex items-center gap-3 text-[13px]">
                  <span className="w-4 text-xs tabular-nums text-slate-400">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-700 group-hover:text-[#2C4A6E] dark:text-slate-200">{x.supplier_name}</span>
                  <span className="shrink-0 tabular-nums text-slate-800 dark:text-slate-100">{byValue ? compactRupiah(x.value) : `${x.count} PO`}</span>
                </div>
                <div className="ml-7 mt-1.5 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className="h-full origin-left rounded-full bg-[#7FA7CF] transition-transform duration-700 ease-out group-hover:bg-[#5F8BB8]"
                      style={{ transform: `scaleX(${shown ? ((byValue ? x.value : x.count) || 0) / max : 0})` }} />
                  </div>
                  <span className="w-12 text-right text-[11px] tabular-nums text-slate-400">{x.count} PO</span>
                </div>
              </button>
            </li>
          ))}
        </ol>}
    </Panel>
  );
}
