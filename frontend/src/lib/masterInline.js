// Inline "Tambah Baru" master dari form transaksi (Project & Unit/Aset).
// Data selalu dibuat ke Master (POST /api/master/{name}); transaksi hanya menyimpan referensi id.
export const INLINE_MASTERS = {
  projects: { label: "Tambah Project Baru", field: "project_id" },
  units: { label: "Tambah Unit Baru", field: "unit_id" },
};

export const isInlineMaster = (name) => Object.prototype.hasOwnProperty.call(INLINE_MASTERS, name);

// Tombol hanya untuk user dengan izin create master terkait (backend tetap enforce 403).
export const canInlineCreate = (can, name) => isInlineMaster(name) && typeof can === "function" && !!can("create", name);

export const inlineCreateLabel = (name) => INLINE_MASTERS[name]?.label || "Tambah Baru";

// Prefill modal: hanya field master existing yang memang ada (Unit/Aset punya division_id opsional;
// Master Project tidak punya Divisi sehingga tidak di-prefill/dikunci).
export const inlinePrefill = (name, ctx = {}) => {
  if (name === "units" && ctx.division_id) return { division_id: ctx.division_id };
  return {};
};

// Label opsi standar: kode + nama dapat dicari, tampilan terpilih ringkas.
export const projectOption = (d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.pic ? ` · PIC ${d.pic}` : ""}`, selectedLabel: d.name });
export const unitOption = (d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.plate_no ? ` (${d.plate_no})` : ""}${d.asset_no ? ` · Asset ${d.asset_no}` : ""}`, selectedLabel: d.plate_no || d.name });

// Terapkan pilihan hasil create HANYA ke baris pemanggil (index i), baris lain tidak tersentuh.
export const applyToLine = (lines, i, field, id) => lines.map((l, x) => (x === i ? { ...l, [field]: id } : l));
