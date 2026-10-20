import api, { API } from "@/lib/api";

// Aset gambar cetak (logo perusahaan, tanda tangan/stempel PO) di-embed sebagai data URL:
// jendela cetak (document.write), iframe pratinjau, dan "Save as PDF" tidak bergantung pada
// cookie sesi / URL relatif. Gagal ambil -> fallback URL absolut (perilaku lama), tidak melempar error.
const blobToDataUrl = (blob) => new Promise((resolve) => {
  try {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result || ""));
    fr.onerror = () => resolve("");
    fr.readAsDataURL(blob);
  } catch { resolve(""); }
});

export async function printImage(path) {
  if (!path) return "";
  try {
    const r = await api.get(path, { responseType: "blob" });
    const blob = r?.data;
    if (blob && blob.size && String(blob.type || "").startsWith("image/")) {
      const url = await blobToDataUrl(blob);
      if (url.startsWith("data:image/")) return url;
    }
  } catch (e) {
    if (e?.response?.status === 404) return ""; // file tidak ada -> jangan tampilkan gambar rusak
  }
  return `${API}${path}`;
}

export const companyLogoPath = (company) => (company?.logo_path ? `/company/logo?v=${encodeURIComponent(company.logo_version || "1")}` : "");
export const poSignaturePath = (status) => (status?.available ? `/settings/print_layouts/po/signature?v=${encodeURIComponent(status.version || "1")}` : "");
