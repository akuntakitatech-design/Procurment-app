export const rupiah = (n) => {
  if (n == null || n === "") return "-";
  return "Rp " + Number(n).toLocaleString("id-ID", { maximumFractionDigits: 0 });
};

export const num = (n) => {
  if (n == null) return "0";
  const s = Number(n).toLocaleString("id-ID", { maximumFractionDigits: 2 });
  return s === "-0" ? "0" : s; // nilai sisa float (mis. -6e-15) dibulatkan ke 0, jangan tampil "-0"
};

// Numeric coercion helper for ARITHMETIC. `num()` is a DISPLAY formatter and
// returns a localized string — never use it inside math (e.g. reduce/+/-),
// otherwise `0 + num(2) + num(3)` becomes the string "023". Use toNum() instead.
export const toNum = (n) => {
  if (n == null || n === "") return 0;
  const v = Number(n);
  return Number.isFinite(v) ? v : 0;
};

export const fmtDate = (d) => {
  if (!d) return "-";
  try {
    const dt = new Date(d);
    return dt.toLocaleDateString("id-ID", { day: "2-digit", month: "2-digit", year: "numeric" });
  } catch { return d; }
};

export const fmtDateTime = (d) => {
  if (!d) return "-";
  try {
    const dt = new Date(d);
    return dt.toLocaleString("id-ID", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " WIB";
  } catch { return d; }
};

export const todayISO = () => new Date().toISOString();
