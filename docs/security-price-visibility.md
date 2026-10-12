# Kebijakan Visibilitas Harga Beli (PR #70)

Izin acuan: `view_purchase_price` (Lihat Harga Beli). Seluruh pembatasan diterapkan **server-side / API**
(`backend/price_redaction_layer.py`, dipasang paling luar setelah layer tenant, izin & cakupan divisi). Frontend hanya
menampilkan apa yang dikirim API. Data di database tidak diubah; bentuk respon (nama field) tetap — nilai yang tidak
berhak diganti `null`.

## 1. PO (daftar, paging, detail) & Log Aktivitas
User tanpa `view_purchase_price` tidak menerima: harga satuan / harga tampilan, diskon nominal baris, gross, DPP,
diskon final nominal, PPN, Grand Total, nominal DP, sisa setelah DP, serta nilai harga pada before/after Log Aktivitas.
Ketentuan berbentuk persen (diskon %, DP %) tetap tampil sebagai *ketentuan*, **kecuali** bagi user yang juga dapat
melihat nominal DP (lihat §3).

## 2. DP Supplier (keputusan pemilik — opsi C)
Modul DP Supplier memakai izin modulnya sendiri (`supplier_dp.view / .approve / .print`). Untuk user dengan izin modul
DP **tetapi tanpa** `view_purchase_price`:

| Tetap tampil (kewenangan pembayaran DP) | Disembunyikan (`null`) |
|---|---|
| Nominal DP yang harus dibayar (`dp_amount`) | Nilai PO (`po_value`) |
| Sudah dibayar (`paid_amount`), terpakai (`dp_used`), sisa DP (`dp_available`) | `po.grand_total` |
| Riwayat pembayaran (`payments[]`: no, nominal, tanggal, sumber dana, referensi, status, bukti) | `po.dp_remaining` (= Grand Total − DP) |
| Status & label status, pemakaian DP di Invoice Vendor, riwayat audit | Persentase DP (`dp_value` bila `dp_type`=persen, juga di `payments[]`) |
| Tipe DP (`dp_type`), teks ketentuan generik "Persentase dari Grand Total" | Angka persen pada `dp_terms` ("40% dari Grand Total") |

Berlaku untuk: `GET /api/supplier-dp` (termasuk `?page=&page_size=`), `GET /api/supplier-dp/{po_id}`,
`GET /api/supplier-dp/payments/{pid}/print`, respon `POST …/{po_id}/draft`, `PUT …/payments/{pid}`,
`POST …/payments/{pid}/approve`, `POST …/payments/{pid}/cancel`, laporan & export Excel/PDF "Daftar DP Supplier"
(`report-center/txn-supplier-dp`), serta baris DP yang dipakai Dashboard/Laporan (`SUPPLIER_DP_REPORT`).
Kemampuan memproses DP (draft, edit, unggah bukti, approve, batal), validasi nilai DP mengikuti PO, tenant isolation,
izin & cakupan divisi **tidak berubah** (route asli tetap yang memeriksa; redaksi hanya pada keluaran).

## 3. Analisis rekonstruksi harga
- **Nominal DP + persen DP → Grand Total** (`GT = DP / persen`). Karena itu, bagi user yang dapat melihat nominal DP
  (izin `supplier_dp.*` atau `invoice.view`) tanpa izin harga, persen DP disembunyikan di **semua** jalur: modul DP,
  laporan/export DP, dan PO daftar/detail.
- **DP tipe nominal**: nominal DP adalah angka yang disepakati, bukan turunan langsung harga; tidak dapat dipakai sendiri
  untuk menghitung Grand Total.
- **Sisa PO setelah DP** (`dp_remaining`) + nominal DP = Grand Total → disembunyikan.
- **Risiko residu (tidak dapat dicegah otomatis, perlu kebijakan operasional):**
  1. Catatan bebas (`payment_notes`/`notes`) yang diketik pengguna (mis. "DP 40%") tidak diredaksi — hindari menulis
     harga/persen di catatan.
  2. Persentase DP standar perusahaan yang sudah diketahui umum (mis. selalu 30%) memungkinkan estimasi Grand Total.
  3. DP 100% berarti nominal DP = Grand Total (melekat pada kewenangan membayar DP).
  4. Modul Invoice Vendor / Tagihan DO (izin `invoice.view`) menampilkan Nilai DO (`do_value`, `do_net`, `do_tax`)
     yang diturunkan dari harga PO × qty diterima. **Diputuskan pemilik: boleh tampil** (lihat §4) — dibutuhkan untuk
     membayar. Pada DO satu-baris, Nilai DO ÷ qty diterima ≈ harga netto satuan; risiko ini **diterima** sebagai bagian
     dari kewenangan modul tagihan.

## 4. Tagihan DO / Invoice Vendor (keputusan pemilik)
Dua izin berbeda dan independen:

| Izin | Memberi akses ke |
|---|---|
| `invoice.view` (+ `invoice.create/edit/pay/print`) — modul Invoice Vendor | Nominal tagihan: Nilai DO yang dapat ditagih / sudah ditagih / sisa (`do_value`, `do_net`, `do_tax`, `billed`, `remaining`), nominal Invoice, alokasi DP, pembayaran, outstanding, aging, rekap hutang (laporan `ap-*`) beserta export & lampiran |
| `view_purchase_price` — Lihat Harga Beli | Harga satuan PO, diskon baris & diskon final, gross/DPP/PPN per PO, Grand Total PO, sisa PO setelah DP, persen DP, nilai harga di Log Aktivitas |

- Finance (atau role apa pun) **tanpa** `view_purchase_price` tetapi **dengan** izin modul tagihan: melihat dan memproses
  tagihan seperti biasa (buat invoice, catat/batalkan pembayaran, unggah bukti). Alur pembayaran tidak diubah.
  Modul Invoice Vendor tidak mengembalikan harga satuan/diskon/Grand Total PO; PO detail tetap diredaksi.
- **Tanpa** izin `invoice.view` → `403` pada daftar, paging, ringkasan, Tagihan DO, DO layak ditagih, detail, cetak,
  kandidat DP, laporan & export hutang (`ap-*`), daftar & unduh lampiran invoice/pembayaran — termasuk user ber-role
  Finance (izin dicek per permission efektif, bukan nama role). Cakupan divisi & tenant tetap berlaku (tenant lain `404`).
- Diuji: `tests/vendor_invoice_price_policy_test.py` + `tests/vendor_invoice_test.py` (izin/divisi/tenant/lampiran).

## 5. Pengujian
- `tests/supplier_dp_price_policy_test.py` — finance tanpa izin harga: draft/edit/bukti/approve/batal tetap bisa,
  respon tiap langkah diredaksi; list/paging/detail/print/PO detail/export Excel & PDF tanpa Grand Total/sisa PO/harga/
  persen; nominal DP tetap tampil di export; kontrol admin & finance berizin harga melihat nilai lengkap; tenant lain 404.
- `tests/price_visibility_scan_test.py` (purchasing-deny, warehouse divisi, warehouse global) dan
  `tests/price_visibility_scan_roles_test.py` (manager-deny, finance-deny): pemindai berbasis nilai atas seluruh GET
  OpenAPI (+ export Excel/PDF Pusat Laporan). Nominal DP dikecualikan dari nilai rahasia **hanya** untuk user yang
  memiliki akses modul DP. Endpoint yang gagal diperiksa (5xx/koneksi/respon tak terbaca) dilaporkan **BELUM DIUJI**,
  tidak dihitung lulus, dan tidak menghentikan pemeriksaan endpoint lain. Persona dibuat dengan override yang divalidasi
  (gagal keras bila override ditolak). Jalur Invoice Vendor ikut dipindai (invoice + pembayaran dibuat admin); nominal DP
  dikecualikan bagi pemegang `supplier_dp.*` atau `invoice.view` (sesuai `DP_NOMINAL_PERMS`).
- `tests/vendor_invoice_price_policy_test.py` — kebijakan §4: finance tanpa izin harga memproses tagihan, nominal tampil,
  tanpa harga PO di JSON/cetak/paging/export Excel & PDF `ap-*`/lampiran; tanpa `invoice.*` → 403; tenant lain 404.
