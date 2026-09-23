const normalize = (v) => String(v || "").trim().toLowerCase();

export function TransactionProgress({ stages = [], status, className = "" }) {
  const current = normalize(status || stages[0]);
  const currentIndex = stages.findIndex((s) => normalize(s) === current);
  const negative = ["cancelled", "canceled", "rejected"].includes(current);

  return (
    <div className={`rounded-xl border bg-card px-4 py-3 shadow-sm ${className}`}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status Transaksi</div>
        <div className={`text-xs font-semibold ${negative ? "text-destructive" : "text-primary"}`}>{status || stages[0]}</div>
      </div>
      <div className="flex items-start overflow-x-auto pb-1">
        {stages.map((stage, i) => {
          const active = currentIndex >= 0 && i <= currentIndex && !negative;
          const isCurrent = currentIndex === i && !negative;
          return (
            <div key={stage} className="flex min-w-[110px] flex-1 items-start last:min-w-[90px]">
              <div className="flex min-w-0 flex-1 flex-col items-center">
                <div className={`h-3 w-3 rounded-full border-2 ${active ? "border-primary bg-primary" : "border-muted-foreground/35 bg-background"} ${isCurrent ? "ring-4 ring-primary/10" : ""}`} />
                <div className={`mt-1.5 text-center text-[10px] leading-tight ${isCurrent ? "font-semibold text-foreground" : active ? "text-foreground/80" : "text-muted-foreground"}`}>{stage}</div>
              </div>
              {i < stages.length - 1 && <div className={`mt-[5px] h-0.5 flex-1 ${active && currentIndex > i ? "bg-primary" : "bg-muted"}`} />}
            </div>
          );
        })}
      </div>
      {negative && <div className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">Transaksi berstatus {status}.</div>}
    </div>
  );
}
