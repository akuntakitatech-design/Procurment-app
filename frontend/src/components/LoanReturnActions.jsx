import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";

export function LoanReturnActions({ row, onEdit, onDeleted }) {
  const { can } = useAuth();
  const [cap,setCap]=useState(null); const [busy,setBusy]=useState(false);
  const load=()=>row?.id&&api.get(`/loan-returns/${row.id}/capability`).then(r=>setCap(r.data)).catch(()=>setCap(null));
  useEffect(()=>{load();},[row?.id]);
  if(!row||(!can("edit")&&!can("delete"))) return null;
  const explain=()=>toast.error(cap?.reason||"Return tidak dapat diubah saat ini");
  const remove=async()=>{if(cap&&!cap.can_delete)return explain();if(!window.confirm(`Hapus ${row.no}? Stok return akan direversal.`))return;try{setBusy(true);await api.delete(`/loan-returns/${row.id}`);toast.success(`${row.no} dihapus`);onDeleted?.();}catch(e){toast.error(apiError(e.response?.data?.detail));load();}finally{setBusy(false);}};
  return <div className="flex gap-2">{can("edit")&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>cap&&!cap.can_edit?explain():onEdit?.(row)}><Pencil className="h-4 w-4 mr-1"/>Edit</Button>}{can("delete")&&<Button size="sm" variant="outline" disabled={busy} onClick={remove}><Trash2 className="h-4 w-4 mr-1 text-destructive"/>Hapus</Button>}</div>;
}
