import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";

export function TransactionMutationActions({ module, id, onEdit, onDeleted, compact = false, ready = true }) {
  const { can } = useAuth();
  const [cap, setCap] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!module || !id) return;
    api.get(`/transactions/${module}/${id}/capability`)
      .then((r) => setCap(r.data))
      .catch(() => setCap(null));
  }, [module, id]);

  useEffect(() => { load(); }, [load]);

  // List shortcut: /module/:id?edit=1 opens edit mode once, only if the document allows editing.
  const [params, setParams] = useSearchParams();
  const autoDone = useRef(false);
  useEffect(() => {
    if (autoDone.current || params.get("edit") !== "1" || !cap || !ready) return;
    autoDone.current = true;
    params.delete("edit"); setParams(params, { replace: true });
    if (cap.can_edit && can("edit")) onEdit?.();
    else toast.error(cap.reason || "Transaksi tidak dapat diedit pada status ini");
  }, [cap, ready, params, setParams, can, onEdit]);

  if (!id || (!can("edit") && !can("delete"))) return null;

  const blocked = (kind) => {
    if (!cap) return false;
    return kind === "edit" ? !cap.can_edit : !cap.can_delete;
  };

  const explain = () => {
    if (cap?.reason) toast.error(cap.reason);
    else toast.error("Transaksi tidak dapat diproses dengan hak akses saat ini");
  };

  const edit = () => {
    if (blocked("edit")) return explain();
    onEdit?.();
  };

  const remove = async () => {
    if (blocked("delete")) return explain();
    if (!window.confirm(`Hapus ${cap?.no || "transaksi ini"}? Tindakan akan dicatat di audit trail.`)) return;
    try {
      setBusy(true);
      await api.delete(`/transactions/${module}/${id}`);
      toast.success(`${cap?.no || "Transaksi"} dihapus`);
      onDeleted?.();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
      load();
    } finally {
      setBusy(false);
    }
  };

  return <div className="flex gap-2">
    {can("edit") && <Button type="button" variant="outline" size={compact ? "sm" : "default"} onClick={edit} disabled={busy}>
      <Pencil className="h-4 w-4 mr-2" />Edit
    </Button>}
    {can("delete") && <Button type="button" variant="outline" size={compact ? "sm" : "default"} onClick={remove} disabled={busy}>
      <Trash2 className="h-4 w-4 mr-2 text-destructive" />Hapus
    </Button>}
  </div>;
}
