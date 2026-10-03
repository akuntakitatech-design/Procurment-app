import { toNum } from "@/lib/format";

export const todayDate = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
export const dateOnly = (s) => String(s || "").slice(0, 10);
export const fmtD = (s) => { const d = dateOnly(s); return d ? `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}` : "-"; };
export const round2 = (n) => Math.round(toNum(n) * 100) / 100;
export const TOL = 1;

export const splitVals = (rows, key) => [...new Set(rows.flatMap((r) => String(r[key] || "").split(",").map((x) => x.trim()).filter(Boolean)))].sort();
export const optsOf = (vals, all) => [{ value: "", label: all }, ...vals.map((v) => ({ value: v, label: v }))];
export const hasVal = (row, key, v) => !v || String(row[key] || "").split(",").map((x) => x.trim()).includes(v);
