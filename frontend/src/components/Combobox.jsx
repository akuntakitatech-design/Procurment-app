import { useState } from "react";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function Combobox({ options, value, onChange, placeholder = "Pilih...", testid, disabled, dense = false, footerAction = null, invalid = false }) {
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);
  const selectedText = selected ? (selected.selectedLabel ?? selected.label) : placeholder;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" disabled={disabled} data-testid={testid} aria-invalid={invalid || undefined}
          className={cn("w-full justify-between font-normal h-9 text-sm", dense && "px-2", invalid && "border-destructive ring-1 ring-destructive")}>
          <span className={cn("truncate", !selected && "text-muted-foreground")}>{selectedText}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0 bg-popover z-50 max-w-[calc(100vw-2rem)]"
        style={{ width: "min(520px, calc(100vw - 2rem))", minWidth: "var(--radix-popover-trigger-width)" }}
        align="start"
      >
        <Command>
          <CommandInput placeholder="Cari..." className="h-10" />
          <CommandList className="max-h-[320px]">
            <CommandEmpty>Tidak ada data</CommandEmpty>
            <CommandGroup>
              {options.map((o) => (
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
