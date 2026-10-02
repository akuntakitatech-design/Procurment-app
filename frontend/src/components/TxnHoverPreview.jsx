import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { num } from "@/lib/format";
import { Eye } from "lucide-react";

function PreviewTable({ row }) {
  const items = row.items || [];
  return (
    <div data-testid={`txn-hover-${row.no || row.id}`}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="font-mono text-xs font-semibold">{row.no}</span>
        <span className="text-[11px] text-muted-foreground">{items.length} item</span>
      </div>
      {items.length === 0 ? <div className="py-3 text-xs text-muted-foreground">Tidak ada item</div> : (
        <div className="max-h-72 overflow-auto rounded border">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-muted text-left uppercase tracking-wide text-muted-foreground">
              <tr><th className="p-1.5">Barang</th><th className="p-1.5">Deskripsi</th><th className="p-1.5 text-right">Qty</th><th className="p-1.5">Satuan</th><th className="p-1.5">Project</th><th className="p-1.5">Divisi</th><th className="p-1.5">No. SPK</th></tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} className="border-t align-top">
                  <td className="p-1.5 font-medium">{it.item}</td><td className="p-1.5 text-muted-foreground">{it.desc || "-"}</td>
                  <td className="p-1.5 text-right tabular-nums">{it.qty === null || it.qty === undefined ? "-" : num(it.qty)}</td>
                  <td className="p-1.5">{it.unit || "-"}</td><td className="p-1.5">{it.project || "-"}</td><td className="p-1.5">{it.division || "-"}</td><td className="p-1.5">{it.spk || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function TxnHoverPreview({ row, onOpen }) {
  const open = (e) => { e.stopPropagation(); onOpen?.(row); };
  return (
    <span className="inline-flex items-center gap-1">
      <HoverCard openDelay={300} closeDelay={80}>
        <HoverCardTrigger asChild>
          <button type="button" onClick={open} data-testid={`txn-no-${row.no || row.id}`} className="font-mono text-xs font-semibold text-primary underline decoration-dotted underline-offset-4 transition-colors hover:text-primary/80">{row.no || "-"}</button>
        </HoverCardTrigger>
        <HoverCardContent align="start" className="w-[640px] max-w-[90vw] p-3" onClick={(e) => e.stopPropagation()}><PreviewTable row={row} /></HoverCardContent>
      </HoverCard>
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" onClick={(e) => e.stopPropagation()} className="text-muted-foreground md:hidden" aria-label="Lihat item" data-testid={`txn-preview-tap-${row.no || row.id}`}><Eye className="h-3.5 w-3.5" /></button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[92vw] p-3" onClick={(e) => e.stopPropagation()}><PreviewTable row={row} /></PopoverContent>
      </Popover>
    </span>
  );
}
