import { cn } from "@/lib/utils";

const MAP = {
  draft: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-300 dark:border-slate-700",
  open: "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 border-blue-200 dark:border-blue-800",
  "waiting approval": "bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300 border-amber-200 dark:border-amber-800",
  submitted: "bg-amber-50 text-amber-700 border-amber-200",
  counting: "bg-amber-50 text-amber-700 border-amber-200",
  review: "bg-amber-50 text-amber-700 border-amber-200",
  approved: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800",
  rejected: "bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300 border-rose-200 dark:border-rose-800",
  partial: "bg-sky-50 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300 border-sky-200 dark:border-sky-800",
  "partial ordered": "bg-sky-50 text-sky-700 border-sky-200",
  "partial returned": "bg-sky-50 text-sky-700 border-sky-200",
  "partially received": "bg-sky-50 text-sky-700 border-sky-200",
  "fully ordered": "bg-emerald-50 text-emerald-700 border-emerald-200",
  "fully received": "bg-emerald-50 text-emerald-700 border-emerald-200",
  posted: "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800",
  completed: "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800",
  closed: "bg-indigo-50 text-indigo-700 border-indigo-200",
  cancelled: "bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-500 line-through border-slate-300",
  "out of stock": "bg-rose-50 text-rose-700 border-rose-200",
  "low stock": "bg-amber-50 text-amber-700 border-amber-200",
  normal: "bg-emerald-50 text-emerald-700 border-emerald-200",
  overstock: "bg-violet-50 text-violet-700 border-violet-200",
};

export function StatusBadge({ status, className }) {
  const key = String(status || "").toLowerCase();
  const cls = MAP[key] || "bg-slate-100 text-slate-700 border-slate-300";
  return (
    <span data-testid={`status-badge-${key.replace(/\s+/g, "-")}`}
      className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap", cls, className)}>
      {status || "-"}
    </span>
  );
}
