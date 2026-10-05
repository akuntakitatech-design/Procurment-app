import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { AppErrorBoundary } from "@/components/AppErrorBoundary";
import { Layout } from "@/components/Layout";
import BrandingHead from "@/components/BrandingHead";
import Login from "@/pages/Login";
import RegisterTenant from "@/pages/RegisterTenant";
import AcceptInvite from "@/pages/AcceptInvite";
import ActivateTenant from "@/pages/ActivateTenant";
import PlatformAdmin from "@/pages/PlatformAdmin";
import SubscriptionLocked from "@/pages/SubscriptionLocked";
import Dashboard from "@/pages/Dashboard";
import ModuleHub from "@/pages/ModuleHub";
import ActivityLog from "@/pages/ActivityLog";
import PrintLayouts from "@/pages/PrintLayouts";
import ExcelImport from "@/pages/ExcelImport";
import MasterData from "@/pages/MasterData";
import Inventory from "@/pages/Inventory";
import Users from "@/pages/Users";
import Settings from "@/pages/Settings";
import Reports from "@/pages/Reports";
import TraceabilityPage from "@/pages/Traceability";
import Approval from "@/pages/Approval";
import Verify from "@/pages/Verify";
import { MroList, MroForm } from "@/pages/Mro";
import { RoList, RoForm } from "@/pages/Ro";
import { PoList, PoForm } from "@/pages/Po";
import { DoList, DoForm } from "@/pages/Do";
import { MiList, MiForm } from "@/pages/Mi";
import Transfer from "@/pages/Transfer";
import Loan from "@/pages/Loan";
import Adjustment from "@/pages/Adjustment";
import Opname from "@/pages/Opname";
import { SpkList, SpkForm, SpkDetail } from "@/pages/Spk";
import { VendorContractList, VendorContractForm, VendorContractDetail } from "@/pages/VendorContract";
import InvoiceMonitoring from "@/pages/InvoiceMonitoring";
import InvoiceForm from "@/pages/InvoiceForm";
import InvoiceDetail from "@/pages/InvoiceDetail";
import SupplierDp from "@/pages/SupplierDp";
import SupplierDpDetail from "@/pages/SupplierDpDetail";

function Loading() {
  return <div className="min-h-screen flex items-center justify-center text-muted-foreground">Memuat...</div>;
}

function Protected({ children }) {
  const { user, subscription } = useAuth();
  if (user === null) return <Loading />;
  if (user === false) return <Navigate to="/login" replace />;
  if (user?.is_platform_admin) return <Navigate to="/platform" replace />;
  if (subscription === null) return <Loading />;
  if (subscription?.access_mode === "locked") return <SubscriptionLocked />;
  return <Layout>{children}</Layout>;
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
              <Route path="/reports" element={<Protected><Reports /></Protected>} />
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
              <Route path="/dp-supplier" element={<Protected><SupplierDp /></Protected>} />
              <Route path="/dp-supplier/:poId" element={<Protected><SupplierDpDetail /></Protected>} />
              <Route path="/users" element={<Protected><Users /></Protected>} />
              <Route path="/settings" element={<Protected><Settings /></Protected>} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </div>
    </AppErrorBoundary>
  );
}

export default App;
