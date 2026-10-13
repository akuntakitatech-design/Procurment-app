import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { ArrowDownUp } from "lucide-react";

// Mobile (< sm): header kolom tabel disembunyikan (tampilan kartu) -> urutkan lewat pilihan kolom + arah.
// sort = { key, dir } | null; onChange menerima objek sort baru (atau null = urutan bawaan).
export function MobileSortBar({ columns, sort, onChange, testidPrefix }) {
  const key = sort?.key || "__none";
  return (
    <div className="flex w-full items-center gap-2 sm:hidden" data-testid={`${testidPrefix}-mobile-sort`}>
      <Select value={key} onValueChange={(k) => onChange(k === "__none" ? null : { key: k, dir: sort?.key === k ? sort.dir : "asc" })}>
        <SelectTrigger className="h-11 flex-1" aria-label="Urutkan berdasarkan" data-testid={`${testidPrefix}-mobile-sort-key`}><SelectValue placeholder="Urutkan" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="__none">Urutan bawaan</SelectItem>
          {columns.filter((c) => c.label).map((c) => <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>)}
        </SelectContent>
      </Select>
      <Button type="button" variant="outline" className="h-11 shrink-0 gap-1.5" disabled={!sort?.key}
        onClick={() => onChange({ key: sort.key, dir: sort.dir === "asc" ? "desc" : "asc" })} aria-label="Balik arah urutan" data-testid={`${testidPrefix}-mobile-sort-dir`}>
        <ArrowDownUp className="h-4 w-4" />{sort?.key ? (sort.dir === "asc" ? "Naik" : "Turun") : "Arah"}
      </Button>
    </div>
  );
}
