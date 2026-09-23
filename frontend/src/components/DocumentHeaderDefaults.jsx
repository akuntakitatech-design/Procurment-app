import { Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { Input } from "@/components/ui/input";

export function DocumentHeaderDefaults({ h, setH, masters, readOnly = false, showTaxMode = false }) {
  const projects = (masters.data.projects || []).map((d) => ({
    value: d.id,
    label: `${d.code ? d.code + " — " : ""}${d.name}${d.pic ? ` · PIC ${d.pic}` : ""}`,
    selectedLabel: d.name,
  }));
  const units = (masters.data.units || []).map((d) => ({
    value: d.id,
    label: `${d.code ? d.code + " — " : ""}${d.name}${d.plate_no ? ` (${d.plate_no})` : ""}${d.asset_no ? ` · Asset ${d.asset_no}` : ""}`,
    selectedLabel: d.plate_no || d.name,
  }));

  return <>
    <Field label="SPK"><Input value={h.spk || ""} onChange={(e) => setH({ ...h, spk: e.target.value })} disabled={readOnly} placeholder="Nomor / referensi SPK" /></Field>
    <Field label="Proyek Default"><Combobox options={projects} value={h.default_project_id || ""} onChange={(v) => setH({ ...h, default_project_id: v })} disabled={readOnly} /></Field>
    <Field label="Unit/Aset Default"><Combobox options={units} value={h.default_unit_id || ""} onChange={(v) => setH({ ...h, default_unit_id: v })} disabled={readOnly} /></Field>
    {showTaxMode && <Field label="Perlakuan Pajak"><label className="flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm cursor-pointer"><input type="checkbox" checked={!!h.tax_inclusive} onChange={(e) => setH({ ...h, tax_inclusive: e.target.checked })} disabled={readOnly} /><span>Harga sudah termasuk pajak (Include)</span></label></Field>}
  </>;
}
