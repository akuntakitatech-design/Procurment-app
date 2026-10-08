import { useState } from "react";
import { AlertCircle, Check, ChevronsUpDown, Loader2, Lock, Plus, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LOOKUP_MESSAGES } from "@/lib/lookupCore";

/**
 * `lookup` (opsional): status data referensi { state: loading|ready|denied|auth|error, message, retry }.
 * Bila tidak diberikan, dibaca dari `options.__lookup` (dipasang oleh useMasters().opts()).
 * Error/izin TIDAK pernah ditampilkan sebagai "Belum ada data".
 */
export function Combobox({ options, value, onChange, placeholder = "Pilih...", testid, disabled, dense = false, footerAction = null, invalid = false, lookup = undefined }) {
  const [open, setOpen] = useState(false);
  const list = options || [];
  const lk = lookup !== undefined ? lookup : list.__lookup;
  const state = lk?.state || "ready";
  const failed = state === "error" || state === "auth" || state === "denied";
  const loadingNoData = state === "loading" && list.length === 0;
  const selected = list.find((o) => o.value === value);
  const selectedText = selected ? (selected.selectedLabel ?? selected.label)
    : loadingNoData ? LOOKUP_MESSAGES.loading
    : failed && list.length === 0 ? (state === "denied" ? "Tidak ada izin" : "Gagal memuat data") : placeholder;
  const lt = testid ? `${testid}-lookup` : undefined;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" disabled={disabled} data-testid={testid} aria-invalid={invalid || (failed && !selected) || undefined}
          aria-busy={loadingNoData || undefined} data-lookup-state={lk ? state : undefined}
          className={cn("w-full justify-between font-normal h-9 text-sm", dense && "px-2", (invalid || (failed && !selected)) && "border-destructive ring-1 ring-destructive")}>
          <span className={cn("flex min-w-0 items-center gap-1.5 truncate", !selected && "text-muted-foreground", failed && !selected && "text-destructive")}>
            {loadingNoData && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />}
            {failed && !selected && (state === "denied" ? <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />)}
            <span className="truncate">{selectedText}</span>
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0 bg-popover z-50 max-w-[calc(100vw-2rem)]"
        style={{ width: "min(520px, calc(100vw - 2rem))", minWidth: "var(--radix-popover-trigger-width)" }}
        align="start"
      >
        {failed && (
          <div role="alert" className="flex items-start justify-between gap-2 border-b px-3 py-2.5 text-sm text-destructive" data-testid={lt ? `${lt}-error` : undefined}>
            <span className="flex items-start gap-2">{state === "denied" ? <Lock className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}{lk?.message || LOOKUP_MESSAGES.error}</span>
            {state !== "denied" && lk?.retry && <button type="button" onClick={() => lk.retry()} data-testid={lt ? `${lt}-retry` : undefined}
              className="flex shrink-0 items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><RotateCw className="h-3.5 w-3.5" />Muat ulang</button>}
          </div>
        )}
        <Command>
          <CommandInput placeholder="Cari..." className="h-10" />
          <CommandList className="max-h-[320px]">
            <CommandEmpty>
              <span data-testid={lt ? `${lt}-empty` : undefined}>
                {loadingNoData ? <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />{LOOKUP_MESSAGES.loading}</span>
                  : failed && list.length === 0 ? (state === "denied" ? "Data tidak dapat ditampilkan." : "Data belum dapat dimuat.")
                  : list.length === 0 ? LOOKUP_MESSAGES.empty : "Tidak ada data yang cocok"}
              </span>
            </CommandEmpty>
            <CommandGroup>
              {list.map((o) => (
                <CommandItem key={o.value} value={o.label} onSelect={() => { onChange(o.value); setOpen(false); }} className="items-start py-2.5">
                  <Check className={cn("mr-2 mt-0.5 h-4 w-4 shrink-0", value === o.value ? "opacity-100" : "opacity-0")} />
                  <span className="whitespace-normal break-words leading-5">{o.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          {footerAction && <div className="border-t p-1"><button type="button" onClick={() => { setOpen(false); footerAction.onClick(); }} data-testid={footerAction.testid}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-2 text-sm font-medium text-primary transition-colors hover:bg-accent"><Plus className="h-4 w-4" />{footerAction.label}</button></div>}
        </Command>
      </PopoverContent>
    </Popover>
  );
}
