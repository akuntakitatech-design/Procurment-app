import { Calendar as CalIcon } from "lucide-react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function DatePicker({ value, onChange, testid }) {
  const date = value ? new Date(value) : undefined;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" data-testid={testid} className={cn("w-full justify-start font-normal h-9", !date && "text-muted-foreground")}>
          <CalIcon className="mr-2 h-4 w-4" />
          {date ? format(date, "dd/MM/yyyy") : "Pilih tanggal"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0 bg-popover z-50" align="start">
        <Calendar mode="single" selected={date} onSelect={(d) => onChange(d ? d.toISOString() : null)} initialFocus />
      </PopoverContent>
    </Popover>
  );
}

export function Field({ label, children }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
