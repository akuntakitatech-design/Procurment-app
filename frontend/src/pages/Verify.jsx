import { useState } from "react";
import { useParams } from "react-router-dom";
import { useEffect } from "react";
import api from "@/lib/api";
import { CheckCircle2, XCircle, ShieldCheck } from "lucide-react";
import { fmtDateTime } from "@/lib/format";

export default function Verify() {
  const { code } = useParams();
  const [res, setRes] = useState(null);
  useEffect(() => { api.get(`/verify/${code}`).then((r) => setRes(r.data)).catch(() => setRes({ valid: false, message: "Gagal memverifikasi" })); }, [code]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted p-6">
      <div className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-lg text-center">
        <div className="flex items-center justify-center gap-2 mb-6"><ShieldCheck className="h-6 w-6 text-primary" /><span className="font-head font-bold text-lg">ProcureFlow Verify</span></div>
        {!res && <div className="text-muted-foreground">Memverifikasi...</div>}
        {res && res.valid && (<>
          <CheckCircle2 className="h-16 w-16 text-emerald-500 mx-auto mb-4" />
          <h1 className="font-head text-xl font-bold">Dokumen Valid</h1>
          <div className="mt-6 text-left space-y-2 text-sm border-t pt-4">
            <div className="flex justify-between"><span className="text-muted-foreground">Jenis</span><span className="font-semibold">{res.doc_type}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Nomor</span><span className="font-mono font-semibold">{res.doc_no}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Status</span><span className="font-semibold">{res.status}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Dibuat oleh</span><span className="font-semibold">{res.created_by}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Waktu cetak</span><span className="font-semibold">{fmtDateTime(res.created_at)}</span></div>
          </div>
        </>)}
        {res && !res.valid && (<><XCircle className="h-16 w-16 text-destructive mx-auto mb-4" /><h1 className="font-head text-xl font-bold">Tidak Valid</h1><p className="text-muted-foreground mt-2">{res.message}</p></>)}
      </div>
    </div>
  );
}
