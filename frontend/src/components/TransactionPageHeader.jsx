import { PageHeader } from "@/components/PageHeader";

// Satu sumber kebenaran untuk kode & nama lengkap transaksi.
export const TRANSACTION_TYPES = {
  mro: { code: "MRO", title: "Permintaan Material", numberLabel: "No. MRO" },
  ro: { code: "RO", title: "Permintaan Pembelian", numberLabel: "No. RO" },
  po: { code: "PO", title: "Pesanan Pembelian", numberLabel: "No. PO" },
  do: { code: "DO", title: "Penerimaan Barang", numberLabel: "No. DO" },
  mi: { code: "MI", title: "Pengeluaran Material", numberLabel: "No. MI" },
  transfer: { code: "Transfer", title: "Transfer Antar Gudang", numberLabel: "No. Transfer" },
  loan: { code: "Pinjam", title: "Pinjam Barang", numberLabel: "No. Pinjaman" },
  adjustment: { code: "Penyesuaian", title: "Penyesuaian Stok", numberLabel: "No. Adjustment" },
  opname: { code: "Stock Opname", title: "Stock Opname" },
  invoice: { code: "Invoice Vendor", title: "Invoice Vendor" },
  supplier_dp: { code: "DP Supplier", title: "Uang Muka Supplier", numberLabel: "No. DP" },
};

const MODE_LABELS = { new: "Buat Baru", edit: "Edit", view: "Lihat" };

const clean = (v) => (v === undefined || v === null ? "" : String(v).trim());

/**
 * Header standar seluruh halaman transaksi.
 *  [Kode]
 *  [Nama lengkap transaksi]
 *  Buat Baru | Edit • [No] | Lihat • [No]   (kosong untuk halaman daftar)
 *
 * Props:
 *  - type: kunci TRANSACTION_TYPES (mro, ro, po, do, mi, transfer, loan, adjustment, opname, invoice)
 *  - mode: "list" | "new" | "edit" | "view" (null/undefined = tanpa konteks, mis. saat dokumen dimuat)
 *  - number: nomor transaksi untuk mode edit/view
 *  - showNumberField: tampilkan baris "No. X — Otomatis saat disimpan" pada mode new
 *  - numberInput: input nomor manual (mis. MRO) pada mode new
 *  - subtitle: status / informasi tambahan (badge, peringatan)
 *  - children: tombol aksi existing
 */
export function TransactionPageHeader({ type, mode, number, subtitle, numberInput, showNumberField = false, children }) {
  const cfg = TRANSACTION_TYPES[type] || { code: "", title: "" };
  const no = clean(number);
  const label = MODE_LABELS[mode];
  const context = label ? (
    <>
      <span data-testid={`${type}-header-mode`}>{label}</span>
      {mode !== "new" && no && <><span aria-hidden="true" className="text-muted-foreground/60">•</span><span data-testid={`${type}-header-number`} className="font-mono font-semibold text-foreground/80">{no}</span></>}
    </>
  ) : null;
  const isNew = mode === "new";
  const withNumberRow = isNew && (numberInput || (showNumberField && cfg.numberLabel));

  return (
    <PageHeader
      testid={`${type}-page-header`}
      eyebrow={cfg.code}
      title={cfg.title}
      context={context}
      subtitle={subtitle}
      transactionLabel={withNumberRow ? cfg.numberLabel : undefined}
      numberInput={isNew ? numberInput : undefined}
    >
      {children}
    </PageHeader>
  );
}
