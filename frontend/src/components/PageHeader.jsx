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

// eyebrow / context / testid bersifat opsional — dipakai oleh TransactionPageHeader.
// Halaman non-transaksi tetap memakai PageHeader seperti sebelumnya.
export function PageHeader({ title, subtitle, children, transactionLabel, transactionNo, numberInput, eyebrow, context, testid }) {
  const titleText = typeof title === "string" ? title : "";
  const autoLabel = NEW_TRANSACTION_LABELS.find(([pattern]) => pattern.test(titleText))?.[1];
  const numberLabel = transactionLabel || autoLabel;
  const numberValue = transactionNo || (numberLabel ? "Otomatis saat disimpan" : null);
  const tid = (part) => (testid ? `${testid}-${part}` : undefined);

  return (
    // Mobile (< sm): tombol aksi pindah ke action bar bawah (fixed, mudah dijangkau satu tangan, membungkus — tidak terpotong).
    // backdrop-filter hanya sm+ karena backdrop-filter menjadikan header containing block bagi elemen fixed.
    <div data-testid={testid} className="sticky top-0 z-20 -mx-3 sm:-mx-6 lg:-mx-7 -mt-3 sm:mt-0 mb-4 sm:mb-5 border-b border-border/80 bg-background px-3 sm:px-6 lg:px-7 py-3 sm:py-3.5 sm:bg-background/95 sm:backdrop-blur-xl sm:supports-[backdrop-filter]:bg-background/88 shadow-[0_8px_24px_-24px_rgba(15,23,42,0.55)] no-print">
      <div className="sm:min-h-[54px] flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1 sm:min-w-[16rem]">
          {eyebrow && <div data-testid={tid("code")} className="text-xs font-bold tracking-wide text-primary leading-none mb-1">{eyebrow}</div>}
          <h1 data-testid={tid("title")} className="text-lg leading-snug sm:truncate sm:text-2xl font-bold tracking-tight font-head">{title}</h1>
          {context && <div data-testid={tid("context")} className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">{context}</div>}
          {(numberLabel || numberInput) && (
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold text-muted-foreground">{numberLabel || "No. MRO"}</span>
              {numberInput
                ? numberInput
                : <span className="rounded-md border bg-muted/50 px-2 py-0.5 font-mono font-semibold text-foreground">{numberValue}</span>}
            </div>
          )}
          {subtitle && <div data-testid={tid("subtitle")} className="mt-1 text-sm text-muted-foreground line-clamp-2">{subtitle}</div>}
        </div>
        {children && <div data-testid={tid("actions") || "page-header-actions"} className="page-actions fixed inset-x-0 bottom-0 z-30 flex flex-wrap items-center justify-end gap-2 border-t bg-background/[0.97] px-3 pt-2.5 pb-[calc(0.625rem+env(safe-area-inset-bottom))] shadow-[0_-10px_28px_-18px_rgba(15,23,42,0.5)] max-sm:[&>*]:min-h-11 max-sm:[&>*]:grow sm:static sm:z-auto sm:border-0 sm:bg-transparent sm:p-0 sm:shadow-none sm:[&>*]:shrink-0">{children}</div>}
      </div>
    </div>
  );
}
