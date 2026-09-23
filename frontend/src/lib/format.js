export const rupiah = (n) => {
  if (n == null || n === "") return "-";
  return "Rp " + Number(n).toLocaleString("id-ID", { maximumFractionDigits: 0 });
};

export const num = (n) => (n == null ? "0" : Number(n).toLocaleString("id-ID", { maximumFractionDigits: 2 }));

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
