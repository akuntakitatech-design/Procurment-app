import { useEffect, useState } from "react";
import { useNavigate, useLocation, NavLink } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutDashboard, Warehouse, ShoppingCart, ClipboardCheck, Boxes, Database, Users, Bell, Search,
  Sun, Moon, LogOut, BarChart3, Settings, Menu, ChevronRight
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api, { API } from "@/lib/api";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/warehouse", label: "Gudang", icon: Warehouse, match: ["/warehouse", "/mro", "/ro", "/do", "/mi"] },
  { to: "/purchasing", label: "Pembelian", icon: ShoppingCart, match: ["/purchasing", "/po"] },
  { to: "/approval", label: "Approval", icon: ClipboardCheck, match: ["/approval"] },
  { to: "/persediaan", label: "Persediaan", icon: Boxes, match: ["/persediaan", "/transfer", "/loan", "/adjustment", "/opname"] },
  { to: "/laporan", label: "Laporan", icon: BarChart3, match: ["/laporan", "/inventory", "/traceability", "/reports"] },
  { to: "/master", label: "Master Data", icon: Database, match: ["/master"] },
  { to: "/system", label: "Sistem", icon: Settings, match: ["/system", "/settings", "/users", "/activity-log", "/print-layouts", "/excel-import"] },
];

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState([]);
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const run = async (val) => {
    setQ(val);
    if (val.length < 2) { setRes([]); setOpen(false); return; }
    const r = await api.get(`/search?q=${encodeURIComponent(val)}`);
    setRes(r.data); setOpen(true);
  };
  const go = (item) => {
    setOpen(false); setQ("");
    const routes = { mro: "/mro/", ro: "/ro/", po: "/po/", do: "/do/", mi: "/mi/" };
    if (routes[item.type]) nav(routes[item.type] + item.id);
    else nav("/master");
  };
  return (
    <div className="relative w-full max-w-md">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
      <Input data-testid="global-search-input" value={q} onChange={(e) => run(e.target.value)}
        onFocus={() => q.length >= 2 && setOpen(true)}
        placeholder="Cari transaksi, barang, supplier..." className="pl-9 h-10 bg-background/80 border-border/80 rounded-xl" />
      {open && res.length > 0 && (
        <div className="absolute z-50 mt-2 w-full max-h-80 overflow-auto rounded-xl border bg-popover shadow-xl">
          {res.map((r) => (
            <button key={r.type + r.id} data-testid="search-result-item" onClick={() => go(r)}
              className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-accent transition-colors">
              <span className="font-mono text-xs uppercase text-muted-foreground w-10">{r.type}</span>
              <span className="font-mono text-xs font-semibold">{r.no}</span>
              <span className="truncate text-muted-foreground">{r.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function NotifBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const load = async () => { const r = await api.get("/notifications"); setItems(r.data); };
  const toggle = () => { if (!open) load(); setOpen(!open); };
  const unread = items.filter((i) => !i.read).length;
  return (
    <div className="relative">
      <Button variant="ghost" size="icon" onClick={toggle} data-testid="notif-bell" className="rounded-xl">
        <Bell className="h-5 w-5" />
        {unread > 0 && <span className="absolute top-1 right-1 h-4 min-w-4 px-1 rounded-full bg-destructive text-[10px] text-white flex items-center justify-center">{unread}</span>}
      </Button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 max-h-96 overflow-auto rounded-xl border bg-popover shadow-xl">
          <div className="flex items-center justify-between border-b px-3 py-2.5">
            <span className="text-sm font-semibold">Notifikasi</span>
            <button className="text-xs text-primary" onClick={async () => { await api.post("/notifications/read-all"); load(); }}>Tandai dibaca</button>
          </div>
          {items.length === 0 && <div className="p-4 text-sm text-muted-foreground">Tidak ada notifikasi</div>}
          {items.map((n) => (
            <div key={n.id} className={`border-b px-3 py-2.5 text-sm ${!n.read ? "bg-accent/40" : ""}`}>
              <div className="font-medium">{n.title}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{n.message}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Layout({ children }) {
  const { user, logout } = useAuth();
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  const [mobileOpen, setMobileOpen] = useState(false);
  const [brand, setBrand] = useState({ name: "App Proc", subtitle: "Procurement & Inventory", logo_available: false, logo_version: null });
  const location = useLocation();

  useEffect(() => {
    api.get("/branding").then((r) => {
      setBrand(r.data || {});
      document.title = r.data?.name ? `App Proc | ${r.data.name}` : "App Proc";
    }).catch(() => { document.title = "App Proc"; });
  }, []);

  const toggleDark = () => { document.documentElement.classList.toggle("dark"); setDark(!dark); };
  const logoSrc = brand.logo_available ? `${API}/company/logo?v=${encodeURIComponent(brand.logo_version || "1")}` : null;
  const initial = (brand.name || "A").trim().charAt(0).toUpperCase();
  const activeFor = (n) => n.exact ? location.pathname === n.to : (n.match || [n.to]).some((p) => location.pathname === p || location.pathname.startsWith(`${p}/`));

  return (
    <div className="h-screen overflow-hidden flex bg-background">
      <aside className={`${mobileOpen ? "flex" : "hidden"} lg:flex fixed lg:static inset-y-0 left-0 z-40 h-screen w-[268px] shrink-0 flex-col premium-sidebar text-slate-100`}>
        <div className="flex shrink-0 items-center gap-3 px-5 h-[72px] border-b border-white/10 premium-sidebar z-10">
          {logoSrc ? (
            <div className="h-10 w-10 overflow-hidden rounded-xl border border-white/10 bg-white p-1.5"><img src={logoSrc} alt="Logo perusahaan" className="h-full w-full object-contain" /></div>
          ) : (
            <div className="h-10 w-10 rounded-xl bg-white/10 ring-1 ring-white/15 flex items-center justify-center text-white font-bold font-head">{initial}</div>
          )}
          <div className="min-w-0 leading-tight">
            <div className="truncate font-head font-bold text-sm text-white" title={brand.name}>{brand.name || "App Proc"}</div>
            <div className="truncate text-[10px] text-slate-400 mt-1">{brand.subtitle || "Procurement & Inventory"}</div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="px-5 pt-5 pb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Workspace</div>
          <nav className="px-3 pb-6 space-y-1.5">
            {NAV.map((n) => {
              const active = activeFor(n);
              return <NavLink key={n.to} to={n.to} end={n.exact} onClick={() => setMobileOpen(false)}
                data-testid={`nav-${n.to.replace("/", "") || "dashboard"}`}
                className={`group flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all ${active ? "bg-white/10 text-white shadow-[inset_3px_0_0_0_rgba(96,165,250,0.95)]" : "text-slate-300 hover:bg-white/[0.06] hover:text-white"}`}>
                <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${active ? "bg-white/10 text-sky-300" : "text-slate-400 group-hover:text-slate-200"}`}>
                  <n.icon className="h-4 w-4 shrink-0" />
                </div>
                <span className="truncate flex-1">{n.label}</span>
                <ChevronRight className={`h-3.5 w-3.5 transition-all ${active ? "text-sky-300" : "text-slate-600 group-hover:text-slate-400"}`} />
              </NavLink>;
            })}
          </nav>
        </div>

        <div className="shrink-0 mx-4 mb-5 rounded-xl border border-white/10 bg-white/[0.04] p-3 text-[11px] leading-5 text-slate-400">
          <div className="font-semibold text-slate-300">Procurement Control</div>
          <div>Gudang · Pembelian · Persediaan · Reporting</div>
        </div>
      </aside>
      {mobileOpen && <div className="fixed inset-0 z-30 bg-slate-950/55 backdrop-blur-sm lg:hidden" onClick={() => setMobileOpen(false)} />}

      <div className="h-screen min-w-0 flex-1 overflow-hidden flex flex-col">
        <header className="shrink-0 z-20 flex items-center gap-3 h-[72px] border-b bg-card/85 backdrop-blur-xl px-4 sm:px-6 no-print">
          <Button variant="ghost" size="icon" className="lg:hidden rounded-xl" onClick={() => setMobileOpen(true)}><Menu className="h-5 w-5" /></Button>
          <GlobalSearch />
          <div className="flex-1" />
          <NotifBell />
          <Button variant="ghost" size="icon" onClick={toggleDark} data-testid="theme-toggle" className="rounded-xl">
            {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
          <div className="flex items-center gap-2.5 pl-3 border-l">
            <div className="text-right leading-tight hidden sm:block">
              <div className="text-sm font-semibold">{user?.name}</div>
              <div className="text-[11px] text-muted-foreground capitalize mt-0.5">{user?.role}</div>
            </div>
            <Button variant="ghost" size="icon" onClick={logout} data-testid="logout-btn" className="rounded-xl"><LogOut className="h-5 w-5" /></Button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="p-4 sm:p-6 lg:p-7 max-w-[1680px] w-full mx-auto">{children}</div>
        </main>
      </div>
    </div>
  );
}
