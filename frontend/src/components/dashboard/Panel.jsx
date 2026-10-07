/** Panel dashboard: putih, border tipis, shadow sangat halus. */
export function Panel({ title, subtitle, icon: Icon, action, children, className = "", testid, delay = 0 }) {
  return (
    <section data-testid={testid} style={{ "--d": `${delay}ms` }}
      className={`dash-rise flex min-w-0 flex-col rounded-2xl border border-slate-200/70 bg-card p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)] dark:border-slate-800 ${className}`}>
      <header className="mb-4 flex items-center justify-between gap-3">
        <h3 className="flex min-w-0 items-center gap-2 font-head text-[15px] font-semibold text-slate-800 dark:text-slate-100">
          {Icon && <Icon className="h-4 w-4 shrink-0 text-[#3D5A80]" />}<span className="min-w-0"><span className="block truncate">{title}</span>
            {subtitle && <span className="block truncate font-['Inter'] text-[11.5px] font-normal text-slate-400" data-testid={testid && `${testid}-subtitle`}>{subtitle}</span>}</span>
        </h3>
        {action}
      </header>
      {children}
    </section>
  );
}

export function EmptyNote({ children = "Belum ada data untuk filter ini." }) {
  return <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-slate-200 py-10 text-sm text-slate-400">{children}</div>;
}
