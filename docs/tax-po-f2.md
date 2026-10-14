# F2 — Integrasi PPN (Tax Engine v2) ke Purchase Order

Status: siap review (PR F2). Tidak ada perubahan production/deploy otomatis.

## Ruang lingkup
- **Master Data → Pajak** (Jenis Transaksi PPN): tarif, faktor DPP Nilai Lain (pembilang/penyebut), kode transaksi
  faktur (01..10), fasilitas (Tanpa fasilitas / Tidak Dipungut / DTP / Dibebaskan), masa berlaku (dari–sampai).
  Validasi backend (`po_tax.normalize_tax_master`): fasilitas Tidak Dipungut/DTP = kode 07, Dibebaskan = kode 08,
  kode 07/08 hanya untuk fasilitas, faktor 0 < num ≤ den, tanggal YYYY-MM-DD, `valid_to ≥ valid_from`.
  PUT parsial tidak mereset konfigurasi lain.
- **Kelengkapan**: master tanpa kode faktur / faktor DPP Nilai Lain ditandai *Belum lengkap* dan **ditolak** pada PO v2
  (HTTP 400, pesan meminta Accounting melengkapi). Tidak ada fallback diam-diam ke v1.
- **Form PO**: perlakuan per baris *Exclude / Include / Tanpa PPN* (chip + drawer), default header (mode + Jenis PPN,
  "Terapkan ke semua baris"), rincian per baris (DPP, DPP Nilai Lain, PPN, dasar biaya perolehan) dan Ringkasan PO
  (DPP, Nilai Tanpa PPN, PPN, kelompok faktur). **Semua nominal dari backend** (`POST /api/po/tax-preview`, engine yang
  sama dengan simpan); frontend hanya mengirim input.
- **Cetak PO** (template referensi & generik): ringkasan v2 dari nilai TERSIMPAN (DPP, Nilai Tanpa PPN, PPN per
  kelompok faktur dengan label dari snapshot aturan, fasilitas "tidak ditagih"), catatan perlakuan per baris.
- **Audit read-only kesiapan go-live** (`GET /api/po/tax-readiness`, panel di Master Pajak): Jenis PPN belum lengkap,
  Supplier Non-PKP yang masih ber-Default Pajak bertarif atau memiliki PO ber-PPN. Tidak menulis data, tanpa nominal.

## Kontrak versi (v1 / v2)
| | PO lama (tanpa `tax_engine_version`) | PO baru (`tax_engine_version = 2`) |
|---|---|---|
| Mesin | `_compute_po_totals_v1` (tidak diubah) | `tax_engine.compute_po` (F1) via `po_tax.compute_v2` |
| Edit | tetap v1; tarif baris dikunci ke nilai tersimpan bila Jenis PPN tidak diganti | tetap v2; baris yang Jenis PPN-nya tidak diubah memakai **snapshot lama** |
| Nominal historis | tidak pernah dihitung ulang dengan aturan baru | snapshot aturan per baris + `tax_rules_snapshot` header |

Versi ditentukan dokumen tersimpan, bukan klien. Dispatcher: `doc_procurement.compute_po_totals`.

Snapshot per baris: `tax_code, tax_name, tax_rate, tax_dpp_factor_num, tax_dpp_factor_den, tax_trx_code, tax_facility`
+ `tax_mode`, `tax_engine_version`. Header: `tax_engine_version, supplier_pkp, dpp_total, dpp_other_total,
non_ppn_total, ppnbm_total, tax_facility_total, tax_groups, tax_rules_snapshot`.

## Kompatibilitas hilir (tidak diubah)
- `dpp` tetap = nilai tanpa PPN setelah diskon (dasar biaya perolehan). DPP Nilai Lain disimpan terpisah (`dpp_other`).
- DO/stok/MWA/HPP/stock & valuation ledger, Vendor Invoice, Supplier DP: **rumus tidak diubah**. Field legacy
  (`tax_amount`, `total`, `tax_inclusive` per baris, `tax` = tarif efektif %, `grand_total`, `tax_total`) tetap terisi.
  Terverifikasi: DO dari PO v2 → `valuation_ledger.unit_cost = dpp/qty` (PPN tidak dikapitalisasi).
- Estimasi budget SPK pra-simpan memakai tarif efektif hasil backend (Include/fasilitas = 0) agar sama dengan commitment.

## Aturan bisnis
- Supplier **Non-PKP tidak boleh dikenakan PPN** (v2 dan jalur API lama bertarif numerik) → 400; form mengunci baris
  ke *Tanpa PPN*. Koreksi via Master Supplier (lihat audit kesiapan).
- **PPnBM belum diaktifkan** di PO (menunggu dukungan Vendor Invoice): input `ppnbm_rate` ditolak, UI tidak menyediakan.
- Fasilitas tidak dapat dikombinasikan dengan Include. Jenis PPN di luar masa berlaku pada tanggal PO ditolak.
- Kreditabilitas PPN Masukan bukan kontrol Purchasing; kapitalisasi PPN tidak dapat dikreditkan **ditunda** (fase
  tersendiri setelah evaluasi Accounting).
- Jalur API lama (tarif numerik tanpa Jenis PPN & tanpa `tax_mode`, bukan UI/impor Excel) tetap kontrak v1 untuk
  kompatibilitas integrasi; bukan fallback dari master belum lengkap.

## Hak akses & redaksi
- `/api/po/tax-options`, `/api/po/tax-readiness`: izin modul PO. `/api/po/tax-preview`: + `view_purchase_price`;
  preview dengan `po_id` memakai aturan akses detail PO (divisi lain -> 403, tenant lain -> 404).
- Semua query PPN ter-scope tenant (lapisan isolasi tenant); audit kesiapan tidak memuat nominal harga.
- Nominal v2 baru (`dpp_other`, `tax_facility_amount`, `ppnbm_amount`, `include_rounding_diff`, `net_amount`,
  `final_discount_share`, header `dpp_total` dst. dan `tax_groups`) ikut diredaksi; klasifikasi non-nominal (mode,
  kode faktur) tetap tampil.

## Pengujian
- `backend/tests/tax_engine_golden_test.py`, `tax_engine_parity_test.py` (F1, golden & parity Python↔JS).
- `backend/tests/po_tax_f2_test.py` — dua fase: A (backend `main` pra-F2 membuat PO v1 asli) → B (backend F2, DB sama):
  historis, Master Pajak, preview = simpan = engine F1, validasi, Include/Exclude/diskon, edit+snapshot, approval,
  DO, hak akses/redaksi, audit kesiapan, kompatibilitas, alur MRO -> RO -> PO v2 + tracking lifecycle,
  isolasi divisi/tenant pada route PPN.
- Catatan: `GET /api/lifecycle/po/{id}` untuk PO langsung (tanpa sumber MRO) mengembalikan 404 "Sumber MRO transaksi
  tidak ditemukan" — perilaku `main` sebelum F2; komponen tracker di UI menyembunyikan diri pada kondisi ini.
- Fixture test lama yang membuat PO ber-PPN kini menandai supplier `pkp: true` (aturan Non-PKP F2).
- `frontend/src/lib/poTaxV2.test.mjs` — konfigurasi master, payload (tanpa nominal), pemetaan hasil backend, cetak.

## Ditunda (di luar F2)
Vendor Invoice & Supplier DP berbasis Tax Engine v2, PPnBM pada PO, kapitalisasi PPN tidak dapat dikreditkan,
laporan berbasis snapshot v2.
