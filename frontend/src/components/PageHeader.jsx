const NEW_TRANSACTION_LABELS = [
  [/^MRO Baru$/i, "No. MRO"],
  [/^RO Baru$/i, "No. RO"],
  [/^PO Baru$/i, "No. PO"],
  [/^DO Baru$/i, "No. DO"],
  [/^MI Baru$/i, "No. MI"],
  [/^Transfer Baru$/i, "No. Transfer"],
  [/^Pinjaman Baru$/i, "No. Pinjaman"],
  [/^Stock Adjustment Baru$/i, "No. Adjustment"],
];

export function PageHeader({ title, subtitle, children, transactionLabel, transactionNo }) {
  const titleText = typeof title === "string" ? title : "";
  const autoLabel = NEW_TRANSACTION_LABELS.find(([pattern]) => pattern.test(titleText))?.[1];
  const numberLabel = transactionLabel || autoLabel;
  const numberValue = transactionNo || (numberLabel ? "Otomatis saat disimpan" : null);

  return (
    <div className="sticky top-0 z-20 -mx-4 sm:-mx-6 lg:-mx-7 mb-5 border-b border-border/80 bg-background/95 px-4 sm:px-6 lg:px-7 py-3.5 backdrop-blur-xl supports-[backdrop-filter]:bg-background/88 shadow-[0_8px_24px_-24px_rgba(15,23,42,0.55)] no-print">
      <div className="min-h-[54px] flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl sm:text-2xl font-bold tracking-tight font-head">{title}</h1>
          {numberLabel && (
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold text-muted-foreground">{numberLabel}</span>
              <span className="rounded-md border bg-muted/50 px-2 py-0.5 font-mono font-semibold text-foreground">{numberValue}</span>
            </div>
          )}
          {subtitle && <div className="mt-1 text-sm text-muted-foreground line-clamp-2">{subtitle}</div>}
        </div>
        {children && <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0 [&>*]:shrink-0">{children}</div>}
      </div>
    </div>
  );
}
