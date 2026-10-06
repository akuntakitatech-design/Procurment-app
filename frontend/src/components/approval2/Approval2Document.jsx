import { forwardRef } from "react";
import { batchTotals, fmtA2Date, fmtMoney, fmtPpn, fmtPpnRp, fmtRp } from "@/lib/approval2";

// Area dokumen yang dirender menjadi JPEG (landscape). Warna dipaksa terang agar hasil export
// konsisten walau aplikasi dalam dark mode. 1 PO = 1 baris; Keterangan Transaksi di-wrap (tidak dipotong).
const COLS = [
  { key: "date", label: "Tanggal", w: 112 },
  { key: "supplier", label: "Nama Supplier", w: 210 },
  { key: "desc", label: "Keterangan Transaksi", w: 400 },
  { key: "po", label: "No PO", w: 176 },
  { key: "project", label: "Project", w: 150 },
  { key: "podate", label: "PO Date", w: 112 },
  { key: "dpp", label: "DPP", w: 150, num: true },
  { key: "ppn", label: "PPN", w: 128, num: true },
  { key: "total", label: "Total", w: 160, num: true },
  { key: "pic", label: "PIC", w: 142 },
];
export const A2_DOC_WIDTH = COLS.reduce((s, c) => s + c.w, 0) + 96;

export const Approval2Document = forwardRef(function Approval2Document({ batch, items }, ref) {
  const t = batchTotals(items);
  return (
    <div ref={ref} data-testid="approval2-document" className="bg-white text-slate-900 px-12 py-10" style={{ width: A2_DOC_WIDTH, fontFamily: "Inter, Arial, sans-serif" }}>
      <div className="mb-6 flex items-end justify-between gap-6 border-b-4 border-slate-800 pb-4">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Pengajuan Approval 2 PO</div>
          <h1 className="mt-1 text-4xl font-extrabold leading-tight text-slate-900" data-testid="approval2-doc-title">{batch?.title}</h1>
        </div>
        <div className="text-right text-sm text-slate-600">
          <div className="font-mono text-base font-bold text-slate-800" data-testid="approval2-doc-no">{batch?.no}</div>
          <div>Tanggal Pengajuan: <span className="font-semibold text-slate-800">{fmtA2Date(batch?.submission_date)}</span></div>
        </div>
      </div>
      <table className="w-full border-collapse text-[15px] leading-snug" style={{ tableLayout: "fixed" }}>
        <colgroup>{COLS.map((c) => <col key={c.key} style={{ width: c.w }} />)}</colgroup>
        <thead>
          <tr className="bg-slate-800 text-white">
            {COLS.map((c) => <th key={c.key} className={`border border-slate-700 px-3 py-3 text-[13px] font-bold uppercase tracking-wide ${c.num ? "text-right" : "text-left"}`}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {items.map((r, i) => (
            <tr key={r.id || r.po_id} className={i % 2 ? "bg-slate-50" : "bg-white"} data-testid={`approval2-doc-row-${i}`}>
              <td className="border border-slate-300 px-3 py-2.5 align-top whitespace-nowrap">{fmtA2Date(batch?.submission_date)}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top break-words font-semibold">{r.supplier_name}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top break-words whitespace-normal" data-testid={`approval2-doc-desc-${i}`}>{r.transaction_description}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top break-all font-mono text-[14px] font-semibold">{r.po_no}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top break-words">{r.project_text}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top whitespace-nowrap">{fmtA2Date(r.po_date)}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top text-right tabular-nums whitespace-nowrap">{fmtMoney(r.dpp)}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top text-right tabular-nums whitespace-nowrap">{fmtPpn(r.ppn)}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top text-right tabular-nums whitespace-nowrap font-bold">{fmtMoney(r.grand_total)}</td>
              <td className="border border-slate-300 px-3 py-2.5 align-top break-words">{r.pic_name}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-6 flex justify-end">
        <table className="text-[17px]" data-testid="approval2-doc-footer">
          <tbody>
            {[["Jumlah PO", String(t.count)], ["Total DPP", fmtRp(t.dpp)], ["Total PPN", fmtPpnRp(t.ppn)], ["Total Nilai", fmtRp(t.total)]].map(([k, v], i) => (
              <tr key={k} className={i === 3 ? "border-t-2 border-slate-800 font-extrabold" : ""}>
                <td className="py-1 pr-6 font-semibold text-slate-600">{k}</td><td className="py-1 pr-3">:</td>
                <td className="py-1 text-right tabular-nums font-bold text-slate-900" data-testid={`approval2-doc-footer-${i}`}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});
