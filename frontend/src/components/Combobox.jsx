import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function Combobox({ options, value, onChange, placeholder = "Pilih...", testid, disabled }) {
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);
  const selectedText = selected ? (selected.selectedLabel ?? selected.label) : placeholder;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" disabled={disabled} data-testid={testid}
          className="w-full justify-between font-normal h-9 text-sm">
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
        </Command>
      </PopoverContent>
    </Popover>
  );
}
