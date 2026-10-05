// Cache data referensi (lookup) bersama antar form/halaman: mengurangi puluhan request saat membuka transaksi.
// Dikosongkan otomatis setiap ada perubahan data (request non-GET berhasil), login/logout, atau ganti token.
export const LOOKUP_TTL_MS = 60000;
export const lookupCache = new Map(); // name -> { t, data }
export const lookupInflight = new Map(); // key -> Promise
export const clearLookupCache = () => { lookupCache.clear(); lookupInflight.clear(); };
