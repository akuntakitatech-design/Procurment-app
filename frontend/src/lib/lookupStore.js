// Cache data referensi (lookup) bersama antar form/halaman: mengurangi puluhan request saat membuka transaksi.
// Dikosongkan otomatis setiap ada perubahan data (request non-GET berhasil), login/logout, atau ganti token.
// ATURAN: cache HANYA berisi hasil HTTP 200 dari backend. Error (401/403/5xx/network) atau nama yang
// `denied` tidak pernah ditulis ke cache — sehingga tidak ada "master kosong palsu" yang tersimpan.
export const LOOKUP_TTL_MS = 60000;
export const lookupCache = new Map(); // name -> { t, data }
export const lookupInflight = new Map(); // key -> Promise
// Generasi cache: naik setiap cache dikosongkan, agar request yang dimulai sebelum logout/ganti token
// tidak menulis hasilnya ke cache generasi baru.
export const lookupMeta = { gen: 0 };
export const clearLookupCache = () => { lookupCache.clear(); lookupInflight.clear(); lookupMeta.gen += 1; };
