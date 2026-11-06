import { cn } from "@/lib/utils";
import { nextSort } from "@/lib/txnList";

/**
 * Header tabel yang bisa diklik untuk mengurutkan (klik = A→Z / kecil→besar, klik lagi = Z→A / besar→kecil).
 *
 * - `k`   : key sort yang dikirim ke backend (mis. `code`, `total_stock`, `wh:<warehouse_id>`).
 *           Bila `k` kosong, header dirender sebagai teks biasa (tidak bisa diklik).
 * - `align` : "right" untuk kolom angka.
 * - `sticky`: header menempel di atas saat isi tabel di-scroll (wajib di dalam kontainer ber-`overflow`
 *             dengan tinggi terbatas, mis. `max-h-[calc(100dvh-22rem)]`).
 */
export function SortTh({ label, k, sort, onSort, align = "left", sticky = false, className = "", style, testidPrefix = "sort" }) {
  const active = !!k && sort?.key === k;
  const numeric = align === "right";
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : k ? "none" : undefined}
      className={cn("p-3 whitespace-nowrap", numeric && "text-right", className,
        // isolate: wajib agar latar header sticky dicat di atas baris yang bergulir di belakangnya
        // (tanpa ini teks baris tembus menembus header pada tabel border-collapse).
        sticky && "sticky top-0 z-20 isolate bg-muted shadow-[inset_0_-1px_0_hsl(var(--border))]")}
      style={style}
    >
      {k ? (
        <button
          type="button"
          onClick={() => onSort(k)}
          data-testid={`${testidPrefix}-${k}`}
          title={`Urutkan menurut ${label}`}
          className={cn("inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground",
            numeric && "flex-row-reverse", active && "text-foreground font-semibold")}
        >
          <span>{label}</span>
          <span className="w-3 text-[10px]" aria-hidden="true">{active ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
        </button>
      ) : label}
    </th>
  );
}

/** Handler siap pakai: dua keadaan (asc ⇄ desc) seperti pola Master Barang. */
export const sortToggle = (setSort) => (k) => setSort((cur) => nextSort(cur, k));

export default SortTh;
