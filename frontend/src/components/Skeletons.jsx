import { Skeleton } from "@/components/ui/skeleton";

/*
 * Skeleton dipakai di dua tempat sekaligus:
 *  - App.js  : fallback saat chunk halaman (lazy) belum selesai dimuat
 *  - halaman : saat data pertama masih diambil
 * Bentuk, urutan, dan tingginya mengikuti tampilan asli supaya tidak ada lompatan
 * layout ketika data masuk. Tidak ada teks "Memuat..." — hanya teks statis halaman.
 */

// Panel dashboard asli: header berwarna 58px + grid KPI. Tinggi panel mengikuti
// ukuran sebenarnya di tiap breakpoint (diukur di production 1440px & 1920px).
function PanelSkeleton({ className = "", kpiClassName = "sm:grid-cols-2", rows = 4 }) {
  return (
    <div className={`flex min-w-0 flex-col rounded-2xl border border-slate-200/70 bg-card p-2 dark:border-slate-800 ${className}`}>
      <Skeleton className="h-[58px] shrink-0 rounded-xl" />
      <div className={`mt-3 grid flex-1 auto-rows-fr gap-2.5 p-2 ${kpiClassName}`}>
        {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="rounded-xl" />)}
      </div>
    </div>
  );
}

function DashboardPanels() {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 min-[1680px]:grid-cols-[11fr_7fr_6fr]">
      <PanelSkeleton className="h-[764px] sm:h-[422px] lg:h-[281px] xl:col-span-2 xl:h-[254px] min-[1680px]:col-span-1 min-[1680px]:h-[430px]"
        kpiClassName="sm:grid-cols-2 lg:grid-cols-4" />
      <PanelSkeleton className="h-[680px] sm:h-[380px] xl:h-[430px]" />
      <PanelSkeleton className="h-[504px] sm:h-[361px] xl:h-[430px]" />
    </div>
  );
}

// Header dashboard: judul + subjudul statis (sama dengan aslinya) dan tombol-tombol
// berupa blok, sehingga tinggi baris header tidak berubah saat halaman asli tampil.
function DashboardHeaderSkeleton() {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-head text-[26px] font-semibold tracking-tight text-slate-900 dark:text-slate-50">Dashboard Procurement &amp; Finance</h1>
        <p className="mt-1 text-sm text-slate-500">Ringkasan pembelian, penerimaan, invoice, dan hutang supplier.</p>
      </div>
      <div className="flex items-center gap-2">
        <Skeleton className="hidden h-4 w-[106px] md:block" />
        <Skeleton className="h-11 w-[118px] rounded-xl sm:h-8" />
        <Skeleton className="h-11 w-[110px] rounded-xl sm:h-8" />
      </div>
    </div>
  );
}

// Kartu filter: label asli tetap tampil (bukan area abu-abu), hanya kontrolnya yang skeleton.
function DashboardFiltersSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-200/70 bg-card p-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:grid-cols-2 lg:grid-cols-[1.2fr_1fr_1fr_1fr_auto] dark:border-slate-800">
      {["Periode", "Divisi", "Project", "Supplier"].map((label) => (
        <div key={label} className="flex min-w-0 flex-col gap-1.5">
          <span className="text-xs font-medium text-slate-500">{label}</span>
          <Skeleton className="h-11 rounded-xl sm:h-10" />
        </div>
      ))}
      <div className="flex items-end"><Skeleton className="h-11 w-full rounded-xl sm:h-10 lg:w-[104px]" /></div>
    </div>
  );
}

// Dipakai halaman Dashboard saat data pertama belum ada (header & filter asli sudah tampil).
export function DashboardPanelsSkeleton() {
  return (
    <div className="space-y-5" data-testid="dash-loading" role="status" aria-label="Memuat dashboard">
      <DashboardPanels />
    </div>
  );
}

// Dipakai App sebagai fallback rute "/" sebelum chunk Dashboard selesai dimuat.
export function DashboardSkeleton() {
  return (
    <div className="space-y-5" data-testid="dash-loading" role="status" aria-label="Memuat dashboard">
      <DashboardHeaderSkeleton />
      <DashboardFiltersSkeleton />
      <DashboardPanels />
    </div>
  );
}

// Fallback umum untuk halaman lain yang chunk-nya belum selesai dimuat.
export function PageSkeleton() {
  return (
    <div className="space-y-5" data-testid="page-loading" role="status" aria-label="Memuat halaman">
      <div className="space-y-2">
        <Skeleton className="h-[30px] w-64 max-w-full" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <Skeleton className="h-[96px] rounded-2xl" />
      <Skeleton className="h-[320px] rounded-2xl" />
    </div>
  );
}
