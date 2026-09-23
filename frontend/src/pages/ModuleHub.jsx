import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import {
  FileText, ClipboardList, PackageCheck, PackageMinus, ShoppingCart, ArrowLeftRight,
  Handshake, SlidersHorizontal, ClipboardCheck, Boxes, GitBranch, BarChart3, Settings,
  Users, ArrowUpRight, Activity, FileSpreadsheet
} from "lucide-react";

const HUBS = {
  warehouse: {
    title: "Gudang",
    subtitle: "Kelola kebutuhan, penerimaan, dan pengeluaran material dalam satu alur kerja.",
    cards: [
      { to: "/mro", code: "MRO", title: "Permintaan Material", desc: "Material Request Order untuk kebutuhan barang dari divisi atau unit.", icon: FileText },
      { to: "/ro", code: "RO", title: "Permintaan Pembelian", desc: "Request Order sebagai dasar proses pembelian ke Purchasing.", icon: ClipboardList },
      { to: "/do", code: "DO", title: "Penerimaan Barang", desc: "Catat penerimaan fisik barang dari supplier dan update stok.", icon: PackageCheck },
      { to: "/mi", code: "MI", title: "Pengeluaran Barang", desc: "Material Issued untuk distribusi atau pemakaian barang dari gudang.", icon: PackageMinus },
    ],
  },
  purchasing: {
    title: "Pembelian",
    subtitle: "Kelola purchase order, supplier, nilai pembelian, dan proses penerimaan.",
    cards: [
      { to: "/po", code: "PO", title: "Pesanan Pembelian", desc: "Purchase Order lengkap dengan supplier, pajak, harga, approval, dan penerimaan.", icon: ShoppingCart },
    ],
  },
  inventory: {
    title: "Persediaan",
    subtitle: "Kontrol mutasi internal, pinjaman, koreksi, dan validasi fisik stok.",
    cards: [
      { to: "/transfer", title: "Transfer Antar Gudang", desc: "Perpindahan stok permanen antar lokasi penyimpanan.", icon: ArrowLeftRight },
      { to: "/loan", title: "Pinjam Antar Gudang", desc: "Pinjaman barang dengan pencatatan outstanding dan pengembalian.", icon: Handshake },
      { to: "/adjustment", title: "Penyesuaian Stok", desc: "Koreksi stok rusak, hilang, expired, selisih, atau ditemukan.", icon: SlidersHorizontal },
      { to: "/opname", title: "Stock Opname", desc: "Snapshot, hitung fisik, approval, dan posting selisih stok.", icon: ClipboardCheck },
    ],
  },
  reporting: {
    title: "Laporan",
    subtitle: "Pantau posisi stok, keterlacakan transaksi, dan analisis operasional.",
    cards: [
      { to: "/inventory", title: "Inventory / Stock", desc: "Posisi stok per barang dan gudang beserta status minimum-maksimum.", icon: Boxes },
      { to: "/traceability", title: "Traceability", desc: "Telusuri alur MRO sampai RO, PO, DO, dan MI secara end-to-end.", icon: GitBranch },
      { to: "/reports", title: "Reporting", desc: "Laporan procurement, inventory, lead time, dan pemakaian unit.", icon: BarChart3 },
    ],
  },
  system: {
    title: "Sistem",
    subtitle: "Konfigurasi aplikasi, user, hak akses, layout dokumen, import data, dan jejak aktivitas sistem.",
    cards: [
      { to: "/settings", title: "Pengaturan", desc: "Perusahaan, penomoran dokumen, approval, dan konfigurasi sistem.", icon: Settings },
      { to: "/users", title: "User & Hak Akses", desc: "Kelola user, role, divisi, gudang, serta permission granular.", icon: Users },
      { to: "/print-layouts", title: "Layout Dokumen", desc: "Desain print-out MRO, RO, PO, DO, MI dan transaksi persediaan secara independen.", icon: FileText },
      { to: "/excel-import", title: "Import Excel", desc: "Upload master data dan seluruh transaksi dari template Excel resmi yang dapat diunduh.", icon: FileSpreadsheet },
      { to: "/activity-log", title: "Log Aktivitas", desc: "Audit trail aktivitas user, perubahan transaksi, penghapusan, approval, dan aksi sistem lainnya.", icon: Activity },
    ],
  },
};

export default function ModuleHub({ type }) {
  const nav = useNavigate();
  const hub = HUBS[type] || HUBS.warehouse;
  return <div className="space-y-6">
    <PageHeader title={hub.title} subtitle={hub.subtitle} />
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {hub.cards.map(({ to, code, title, desc, icon: Icon }) => (
        <button key={to} onClick={() => nav(to)}
          className="group premium-module-card text-left rounded-2xl border bg-card p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-[0_18px_45px_-28px_rgba(15,23,42,0.45)]">
          <div className="flex items-start justify-between gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/8 text-primary ring-1 ring-primary/10">
              <Icon className="h-5 w-5" />
            </div>
            <ArrowUpRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
          </div>
          <div className="mt-5">
            {code && <div className="text-[11px] font-bold tracking-[0.18em] text-primary/70">{code}</div>}
            <h3 className="mt-1 font-head text-base font-semibold text-foreground">{title}</h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{desc}</p>
          </div>
          <div className="mt-5 text-xs font-semibold text-primary">Buka modul →</div>
        </button>
      ))}
    </div>
  </div>;
}
