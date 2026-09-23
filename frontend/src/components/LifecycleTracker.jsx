import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { num, fmtDate } from "@/lib/format";
import { Check, Circle, Clock3, AlertTriangle, Minus, ChevronDown, ChevronUp } from "lucide-react";

const STATE = {
  done: { icon: Check, dot: "bg-emerald-500 text-white", line: "bg-emerald-300", text: "text-emerald-700" },
  partial: { icon: Clock3, dot: "bg-amber-500 text-white", line: "bg-amber-300", text: "text-amber-700" },
  active: { icon: Circle, dot: "bg-blue-600 text-white", line: "bg-blue-300", text: "text-blue-700" },
  error: { icon: AlertTriangle, dot: "bg-red-500 text-white", line: "bg-red-300", text: "text-red-700" },
  pending: { icon: Circle, dot: "bg-muted text-muted-foreground", line: "bg-border", text: "text-muted-foreground" },
  na: { icon: Minus, dot: "bg-muted text-muted-foreground", line: "bg-border", text: "text-muted-foreground" },
};

function StageCard({ stage, current }) {
  const [open, setOpen] = useState(false);
  const s = STATE[stage.state] || STATE.pending;
  const Icon = s.icon;
  const docs = stage.documents || [];
  const active = current?.type === stage.key;

  return (
    <div className={`relative min-w-0 flex-1 rounded-xl border bg-card p-3 transition ${active ? "border-primary shadow-sm ring-1 ring-primary/20" : ""}`}>
      <div className="flex items-start gap-2.5">
        <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${s.dot}`}><Icon className="h-3.5 w-3.5" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-bold uppercase tracking-wider">{stage.label}</div>
            {active && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">Sedang Dibuka</span>}
          </div>
          <div className={`mt-1 text-xs font-semibold ${s.text}`}>{stage.status}</div>
          <div className="mt-1 text-lg font-bold tabular-nums">{num(stage.qty || 0)}</div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Qty</div>
        </div>
      </div>

      <div className="mt-3 border-t pt-2">
        {docs.length === 0 ? (
          <div className="text-xs text-muted-foreground">Belum ada dokumen</div>
        ) : (
          <>
            <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-2 text-left text-xs font-medium hover:text-primary">
              <span>{docs.length} dokumen</span>
              {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
            <div className={`${open || docs.length === 1 ? "block" : "hidden"} mt-2 space-y-1.5`}>
              {docs.map((d) => (
                <Link key={d.id} to={`/${stage.key}/${d.id}`} className="block rounded-md bg-muted/40 px-2 py-1.5 text-xs hover:bg-muted">
                  <div className="truncate font-mono font-semibold text-primary">{d.no || "-"}</div>
                  <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                    <span>{d.date ? fmtDate(d.date) : "-"}</span><span>{num(d.qty || 0)}</span>
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function LifecycleTracker({ entity, docId, className = "" }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!entity || !docId) { setData(null); return; }
    let alive = true;
    setLoading(true);
    api.get(`/lifecycle/${entity}/${docId}`)
      .then((r) => { if (alive) setData(r.data); })
      .catch(() => { if (alive) setData(null); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [entity, docId]);

  if (!docId) return null;
  if (loading) return <div className={`mb-4 rounded-xl border bg-card p-4 text-sm text-muted-foreground ${className}`}>Memuat tracking transaksi...</div>;
  if (!data) return null;

  const s = data.summary || {};
  return (
    <section className={`mb-4 rounded-2xl border bg-card p-4 shadow-sm ${className}`}>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-xs font-bold uppercase tracking-wider text-primary">Tracking Transaksi</div>
          <h3 className="mt-1 font-head text-base font-semibold">MRO → RO → PO → DO → MI</h3>
          <p className="mt-1 text-xs text-muted-foreground">Status dihitung dari dokumen yang benar-benar terhubung dan kuantitas yang sudah diproses.</p>
        </div>
        <div className="grid grid-cols-3 gap-x-4 gap-y-1 rounded-xl bg-muted/40 px-3 py-2 text-right text-xs sm:min-w-[290px]">
          <span className="text-muted-foreground">Request</span><span className="text-muted-foreground">MI</span><span className="text-muted-foreground">Outstanding</span>
          <span className="font-bold tabular-nums">{num(s.request || 0)}</span><span className="font-bold tabular-nums">{num(s.mi || 0)}</span><span className="font-bold tabular-nums">{num(s.outstanding || 0)}</span>
        </div>
      </div>

      {data.direct && <div className="mb-3 rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">MI ini dibuat Direct, sehingga tidak memiliki sumber MRO/RO/PO/DO.</div>}

      <div className="overflow-x-auto pb-1">
        <div className="flex min-w-[900px] items-stretch gap-2">
          {(data.stages || []).map((stage, i) => (
            <div key={stage.key} className="flex min-w-0 flex-1 items-center gap-2">
              <StageCard stage={stage} current={data.current} />
              {i < data.stages.length - 1 && <div className={`h-0.5 w-5 shrink-0 ${(STATE[stage.state] || STATE.pending).line}`} />}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
