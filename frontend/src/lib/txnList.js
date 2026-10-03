const collator = new Intl.Collator("id", { numeric: true, sensitivity: "base" });

export const colValue = (col, row) => (col.value ? col.value(row) : row[col.key]);

const isEmpty = (v) => v === null || v === undefined || v === "";

export function compareValues(a, b, type) {
  if (isEmpty(a) && isEmpty(b)) return 0;
  if (isEmpty(a)) return 1;
  if (isEmpty(b)) return -1;
  if (type === "num") return (Number(a) || 0) - (Number(b) || 0);
  return collator.compare(String(a), String(b));
}

export function sortRows(rows, columns, sort) {
  if (!sort?.key) return rows;
  const col = columns.find((c) => c.key === sort.key);
  if (!col) return rows;
  const type = col.sortType || (col.num ? "num" : "text");
  const dir = sort.dir === "desc" ? -1 : 1;
  return [...rows].sort((x, y) => {
    const c = compareValues(colValue(col, x), colValue(col, y), type);
    if (c !== 0) return (isEmpty(colValue(col, x)) || isEmpty(colValue(col, y))) ? c : c * dir;
    return collator.compare(String(x.no || ""), String(y.no || "")) || collator.compare(String(x.id || ""), String(y.id || ""));
  });
}

export function searchRows(rows, columns, q) {
  const needle = String(q || "").trim().toLowerCase();
  if (!needle) return rows;
  const terms = needle.split(/\s+/);
  return rows.filter((r) => {
    const hay = [r.no, r.items_search, ...columns.map((c) => colValue(c, r))].filter((v) => !isEmpty(v)).join(" ").toLowerCase();
    return terms.every((t) => hay.includes(t));
  });
}

export const nextSort = (sort, key) => (sort?.key === key && sort.dir === "asc" ? { key, dir: "desc" } : { key, dir: "asc" });

const TRACE = {
  mro: ["trace_mro", "No. MRO"], ro: ["trace_ro", "No. RO"], po: ["trace_po", "No. PO"], project: ["trace_project", "Project"],
  division: ["trace_division", "Divisi"], spk: ["trace_spk", "No. SPK"], warehouse: ["trace_warehouse", "Gudang"],
  unit: ["trace_unit", "Unit/Aset"], requester: ["trace_requester", "Pemohon"],
};
export const traceCol = (k) => ({ key: TRACE[k][0], label: TRACE[k][1], wrap: true });
export const noCol = (label) => ({ key: "no", label, hover: true });
export const dateCol = (fmt) => ({ key: "date", label: "Tanggal", value: (r) => (r.date ? String(r.date).slice(0, 10) : ""), render: (r) => fmt(r.date) });
