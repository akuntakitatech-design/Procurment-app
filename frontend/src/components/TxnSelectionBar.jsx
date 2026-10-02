import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Printer, Pencil, Trash2, Mail, X } from "lucide-react";
import { toast } from "sonner";

export function TxnSelectionBar({ module, selected, onClear, onPrint, onEdit, onEmail, emailEligible, canEditRow, onBulkDelete, testidPrefix }) {
  const { can } = useAuth();
  const [cap, setCap] = useState(null);
  const single = selected.length === 1 ? selected[0] : null;

  useEffect(() => {
    setCap(null);
    if (!single || !module) return;
    api.get(`/transactions/${module}/${single.id}/capability`).then((r) => setCap(r.data)).catch(() => setCap({ can_edit: false, can_delete: false }));
  }, [single, module]);

  if (!selected.length) return null;
  const rowEdit = single && canEditRow ? canEditRow(single) : true;
  const editOk = !!cap?.can_edit && rowEdit === true;
  const editReason = rowEdit !== true && typeof rowEdit === "string" ? rowEdit : cap?.reason;
  const blockedToast = (reason) => toast.error(reason || "Transaksi tidak dapat diproses pada status ini");

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm animate-in fade-in slide-in-from-top-1" data-testid={`${testidPrefix}-selection-bar`}>
      <span className="font-semibold" data-testid={`${testidPrefix}-selected-count`}>{selected.length} dipilih</span>
      <span className="h-4 w-px bg-border" />
      {single && onPrint && <Button size="sm" variant="outline" onClick={() => onPrint(single)} data-testid={`${testidPrefix}-action-print`}><Printer className="mr-1.5 h-3.5 w-3.5" />Cetak</Button>}
      {single && onEdit && can("edit") && <Button size="sm" variant="outline" disabled={!cap} onClick={() => (editOk ? onEdit(single) : blockedToast(editReason))} className={!editOk && cap ? "opacity-50" : ""} title={!editOk ? editReason || "" : ""} data-testid={`${testidPrefix}-action-edit`}><Pencil className="mr-1.5 h-3.5 w-3.5" />Edit</Button>}
      {single && onEmail && can("print") && (!emailEligible || emailEligible(single)) && <Button size="sm" variant="outline" onClick={() => onEmail(single)} data-testid={`${testidPrefix}-action-email`}><Mail className="mr-1.5 h-3.5 w-3.5" />Kirim Email</Button>}
      {single && can("delete") && <Button size="sm" variant="outline" disabled={!cap} onClick={() => (cap?.can_delete ? onBulkDelete() : blockedToast(cap?.reason))} className={!cap?.can_delete && cap ? "opacity-50" : ""} data-testid={`${testidPrefix}-action-delete`}><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />Hapus</Button>}
      {!single && can("delete") && <Button size="sm" variant="outline" onClick={onBulkDelete} data-testid={`${testidPrefix}-action-bulk-delete`}><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />Hapus Massal</Button>}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear} data-testid={`${testidPrefix}-clear-selection`}><X className="mr-1 h-3.5 w-3.5" />Batal pilih</Button>
    </div>
  );
}
