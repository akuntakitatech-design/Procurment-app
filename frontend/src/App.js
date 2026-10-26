import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { legacyReportPath } from "@/lib/reportCenter";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { MasterCreateProvider } from "@/components/MasterRefCombobox";
import { AppErrorBoundary } from "@/components/AppErrorBoundary";
import { Layout } from "@/components/Layout";
import BrandingHead from "@/components/BrandingHead";
import { lazy, Suspense } from "react";

// P7: halaman dimuat per rute (code splitting) -> bundle awal lebih kecil; Login tetap langsung.
const RegisterTenant = lazy(() => import("@/pages/RegisterTenant"));
const AcceptInvite = lazy(() => import("@/pages/AcceptInvite"));
const ActivateTenant = lazy(() => import("@/pages/ActivateTenant"));
const PlatformAdmin = lazy(() => import("@/pages/PlatformAdmin"));
const SubscriptionLocked = lazy(() => import("@/pages/SubscriptionLocked"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const ModuleHub = lazy(() => import("@/pages/ModuleHub"));
const ActivityLog = lazy(() => import("@/pages/ActivityLog"));
const PrintLayouts = lazy(() => import("@/pages/PrintLayouts"));
const ExcelImport = lazy(() => import("@/pages/ExcelImport"));
const MasterData = lazy(() => import("@/pages/MasterData"));
const Inventory = lazy(() => import("@/pages/Inventory"));
const Users = lazy(() => import("@/pages/Users"));
const Profile = lazy(() => import("@/pages/Profile"));
const Settings = lazy(() => import("@/pages/Settings"));
const ReportCenter = lazy(() => import("@/pages/ReportCenter"));
const TraceabilityPage = lazy(() => import("@/pages/Traceability"));
const Approval2Batch = lazy(() => import("@/pages/Approval2Batch"));
const Approval = lazy(() => import("@/pages/Approval"));
const Verify = lazy(() => import("@/pages/Verify"));
const MroList = lazy(() => import("@/pages/Mro").then((m) => ({ default: m.MroList })));
const MroForm = lazy(() => import("@/pages/Mro").then((m) => ({ default: m.MroForm })));
const RoList = lazy(() => import("@/pages/Ro").then((m) => ({ default: m.RoList })));
const RoForm = lazy(() => import("@/pages/Ro").then((m) => ({ default: m.RoForm })));
const PoList = lazy(() => import("@/pages/Po").then((m) => ({ default: m.PoList })));
const PoForm = lazy(() => import("@/pages/Po").then((m) => ({ default: m.PoForm })));
const DoList = lazy(() => import("@/pages/Do").then((m) => ({ default: m.DoList })));
const DoForm = lazy(() => import("@/pages/Do").then((m) => ({ default: m.DoForm })));
const MiList = lazy(() => import("@/pages/Mi").then((m) => ({ default: m.MiList })));
const MiForm = lazy(() => import("@/pages/Mi").then((m) => ({ default: m.MiForm })));
const Transfer = lazy(() => import("@/pages/Transfer"));
const Loan = lazy(() => import("@/pages/Loan"));
const Adjustment = lazy(() => import("@/pages/Adjustment"));
const Opname = lazy(() => import("@/pages/Opname"));
const SpkList = lazy(() => import("@/pages/Spk").then((m) => ({ default: m.SpkList })));
const SpkForm = lazy(() => import("@/pages/Spk").then((m) => ({ default: m.SpkForm })));
const SpkDetail = lazy(() => import("@/pages/Spk").then((m) => ({ default: m.SpkDetail })));
const VendorContractList = lazy(() => import("@/pages/VendorContract").then((m) => ({ default: m.VendorContractList })));
const VendorContractForm = lazy(() => import("@/pages/VendorContract").then((m) => ({ default: m.VendorContractForm })));
const VendorContractDetail = lazy(() => import("@/pages/VendorContract").then((m) => ({ default: m.VendorContractDetail })));
const InvoiceMonitoring = lazy(() => import("@/pages/InvoiceMonitoring"));
const InvoiceForm = lazy(() => import("@/pages/InvoiceForm"));
const InvoiceDetail = lazy(() => import("@/pages/InvoiceDetail"));
const InvoiceTransmittal = lazy(() => import("@/pages/InvoiceTransmittal"));
const InvoiceTransmittalForm = lazy(() => import("@/pages/InvoiceTransmittalForm"));
const SupplierDp = lazy(() => import("@/pages/SupplierDp"));
const SupplierDpDetail = lazy(() => import("@/pages/SupplierDpDetail"));
import Login from "@/pages/Login";

function Loading() {
  const auth = useAuth();
  // Gangguan sementara saat memulihkan sesi (5xx/network): jangan dianggap anonim, tawarkan coba lagi.
  if (auth?.authError) return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 px-6 text-center" role="alert" data-testid="auth-bootstrap-error">
      <p className="text-sm text-muted-foreground">{auth.authError}</p>
      <button type="button" onClick={auth.retryBootstrap} data-testid="auth-bootstrap-retry"
        className="rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Coba lagi</button>
    </div>
  );
  return <div className="min-h-screen flex items-center justify-center text-muted-foreground">Memuat...</div>;
}

function RouteLoading() {
  return <div className="flex min-h-[40vh] items-center justify-center text-sm text-muted-foreground" data-testid="route-loading">Memuat halaman...</div>;
}

// URL lama /reports (dan ?tab=trace|lead|usage) -> laporan padanan di Pusat Laporan; endpoint API lama tetap tersedia.
function LegacyReportsRedirect() {
  const { search } = useLocation();
  return <Navigate to={legacyReportPath(search)} replace />;
}

function Protected({ children }) {
  const { user, subscription } = useAuth();
  if (user === null) return <Loading />;
  if (user === false) return <Navigate to="/login" replace />;
  if (user?.is_platform_admin) return <Navigate to="/platform" replace />;
  if (subscription === null) return <Loading />;
  if (subscription?.access_mode === "locked") return <SubscriptionLocked />;
  return <Layout><Suspense fallback={<RouteLoading />}>{children}</Suspense></Layout>;
}

function PlatformProtected({ children }) {
  const { user } = useAuth();
  if (user === null) return <Loading />;
  if (user === false) return <Navigate to="/login" replace />;
  if (!user?.is_platform_admin) return <Navigate to="/" replace />;
  return children;
}

function App() {
  return (
    <AppErrorBoundary>
      <div className="App">
        <BrowserRouter>
          <AuthProvider>
            <BrandingHead />
            <Toaster position="top-right" />
            <MasterCreateProvider>
            <Suspense fallback={<RouteLoading />}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/daftar" element={<RegisterTenant />} />
              <Route path="/invite/:code" element={<AcceptInvite />} />
              <Route path="/activation/:token" element={<ActivateTenant />} />
              <Route path="/platform" element={<PlatformProtected><PlatformAdmin /></PlatformProtected>} />
              <Route path="/verify/:code" element={<Verify />} />
              <Route path="/" element={<Protected><Dashboard /></Protected>} />
              <Route path="/warehouse" element={<Protected><ModuleHub type="warehouse" /></Protected>} />
              <Route path="/purchasing" element={<Protected><ModuleHub type="purchasing" /></Protected>} />
              <Route path="/persediaan" element={<Protected><ModuleHub type="inventory" /></Protected>} />
              <Route path="/laporan" element={<Protected><ModuleHub type="reporting" /></Protected>} />
              <Route path="/system" element={<Protected><ModuleHub type="system" /></Protected>} />
              <Route path="/activity-log" element={<Protected><ActivityLog /></Protected>} />
              <Route path="/print-layouts" element={<Protected><PrintLayouts /></Protected>} />
              <Route path="/excel-import" element={<Protected><ExcelImport /></Protected>} />
              <Route path="/approval" element={<Protected><Approval /></Protected>} />
              <Route path="/approval/approval2/:id" element={<Protected><Approval2Batch /></Protected>} />
              <Route path="/mro" element={<Protected><MroList /></Protected>} />
              <Route path="/mro/new" element={<Protected><MroForm /></Protected>} />
              <Route path="/mro/:id" element={<Protected><MroForm /></Protected>} />
              <Route path="/ro" element={<Protected><RoList /></Protected>} />
              <Route path="/ro/new" element={<Protected><RoForm /></Protected>} />
              <Route path="/ro/:id" element={<Protected><RoForm /></Protected>} />
              <Route path="/po" element={<Protected><PoList /></Protected>} />
              <Route path="/po/new" element={<Protected><PoForm /></Protected>} />
              <Route path="/po/:id" element={<Protected><PoForm /></Protected>} />
              <Route path="/do" element={<Protected><DoList /></Protected>} />
              <Route path="/do/new" element={<Protected><DoForm /></Protected>} />
              <Route path="/do/:id" element={<Protected><DoForm /></Protected>} />
              <Route path="/mi" element={<Protected><MiList /></Protected>} />
              <Route path="/mi/new" element={<Protected><MiForm /></Protected>} />
              <Route path="/mi/:id" element={<Protected><MiForm /></Protected>} />
              <Route path="/transfer" element={<Protected><Transfer /></Protected>} />
              <Route path="/loan" element={<Protected><Loan /></Protected>} />
              <Route path="/adjustment" element={<Protected><Adjustment /></Protected>} />
              <Route path="/opname" element={<Protected><Opname /></Protected>} />
              <Route path="/inventory" element={<Protected><Inventory /></Protected>} />
              <Route path="/traceability" element={<Protected><TraceabilityPage /></Protected>} />
              <Route path="/reports" element={<Protected><LegacyReportsRedirect /></Protected>} />
              <Route path="/report-center" element={<Protected><ReportCenter /></Protected>} />
              <Route path="/report-center/:key" element={<Protected><ReportCenter /></Protected>} />
              <Route path="/master" element={<Protected><MasterData /></Protected>} />
              <Route path="/spk" element={<Protected><SpkList /></Protected>} />
              <Route path="/spk/new" element={<Protected><SpkForm /></Protected>} />
              <Route path="/spk/:id" element={<Protected><SpkDetail /></Protected>} />
              <Route path="/spk/:id/edit" element={<Protected><SpkForm /></Protected>} />
              <Route path="/vendor-contracts" element={<Protected><VendorContractList /></Protected>} />
              <Route path="/vendor-contracts/new" element={<Protected><VendorContractForm /></Protected>} />
              <Route path="/vendor-contracts/:id" element={<Protected><VendorContractDetail /></Protected>} />
              <Route path="/vendor-contracts/:id/edit" element={<Protected><VendorContractForm /></Protected>} />
              <Route path="/invoice" element={<Protected><InvoiceMonitoring /></Protected>} />
              <Route path="/invoice/new" element={<Protected><InvoiceForm /></Protected>} />
              <Route path="/invoice/:id" element={<Protected><InvoiceDetail /></Protected>} />
              <Route path="/invoice/:id/edit" element={<Protected><InvoiceForm /></Protected>} />
              <Route path="/transmittal" element={<Protected><InvoiceTransmittal /></Protected>} />
              <Route path="/transmittal/new" element={<Protected><InvoiceTransmittalForm /></Protected>} />
              <Route path="/transmittal/:id" element={<Protected><InvoiceTransmittalForm /></Protected>} />
              <Route path="/dp-supplier" element={<Protected><SupplierDp /></Protected>} />
              <Route path="/dp-supplier/:poId" element={<Protected><SupplierDpDetail /></Protected>} />
              <Route path="/users" element={<Protected><Users /></Protected>} />
              <Route path="/profile" element={<Protected><Profile /></Protected>} />
              <Route path="/settings" element={<Protected><Settings /></Protected>} />
            </Routes>
            </Suspense>
            </MasterCreateProvider>
          </AuthProvider>
        </BrowserRouter>
      </div>
    </AppErrorBoundary>
  );
}

export default App;
