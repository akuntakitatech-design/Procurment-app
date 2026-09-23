import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Layout } from "@/components/Layout";
import Login from "@/pages/Login";
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

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null) return <div className="min-h-screen flex items-center justify-center text-muted-foreground">Memuat...</div>;
  if (user === false) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <Toaster position="top-right" />
          <Routes>
            <Route path="/login" element={<Login />} />
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
            <Route path="/users" element={<Protected><Users /></Protected>} />
            <Route path="/settings" element={<Protected><Settings /></Protected>} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;