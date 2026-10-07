import { Field } from "@/components/DatePicker";
import { MasterProjectCombobox, MasterUnitCombobox } from "@/components/MasterRefCombobox";
import { inlinePrefill, projectOption, unitOption } from "@/lib/masterInline";
import { Input } from "@/components/ui/input";

export function DocumentHeaderDefaults({ h, setH, masters, readOnly = false, showTaxMode = false, hideSpk = false, testidPrefix = "doc" }) {
  const projects = (masters.data.projects || []).map(projectOption);
  const units = (masters.data.units || []).map(unitOption);

  return <>
    {!hideSpk && <Field label="SPK"><Input value={h.spk || ""} onChange={(e) => setH({ ...h, spk: e.target.value })} disabled={readOnly} placeholder="Nomor / referensi SPK" /></Field>}
    <Field label="Proyek Default"><MasterProjectCombobox masters={masters} options={projects} value={h.default_project_id || ""} onChange={(v) => setH((s) => ({ ...s, default_project_id: v }))} disabled={readOnly} testid={`${testidPrefix}-hdr-project`} /></Field>
    <Field label="Unit/Aset Default"><MasterUnitCombobox masters={masters} options={units} value={h.default_unit_id || ""} onChange={(v) => setH((s) => ({ ...s, default_unit_id: v }))} disabled={readOnly} prefill={() => inlinePrefill("units", { division_id: h.division_id })} testid={`${testidPrefix}-hdr-unit`} /></Field>
    {showTaxMode && <Field label="Perlakuan Pajak"><label className="flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm cursor-pointer"><input type="checkbox" checked={!!h.tax_inclusive} onChange={(e) => setH({ ...h, tax_inclusive: e.target.checked })} disabled={readOnly} /><span>Harga sudah termasuk pajak (Include)</span></label></Field>}
  </>;
}
