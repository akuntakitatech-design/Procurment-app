# F1 — Tax Calculation Engine (PPN) & Golden Test

Status: **modul murni** — belum dipasang ke API, form PO, Invoice, DP, laporan, ataupun persistensi dokumen.
Tidak ada perubahan pada `dpp` existing, MWA, HPP, stock ledger, approval, maupun logika transaksi.

## File
| File | Peran |
|---|---|
| `backend/tax_engine.py` | Engine backend (**sumber kebenaran**). `Decimal`/`Fraction`, tanpa float. |
| `frontend/src/lib/taxEngine.js` | Mirror frontend (rasional `BigInt`, tanpa float, tanpa `**`). Belum diimpor UI. |
| `backend/tests/fixtures/tax_engine_golden.json` | Golden test **bersama** (nilai expected dihitung manual). |
| `backend/tests/tax_engine_golden_test.py` | Runner golden backend + invarian + unit pembulatan/parsing. |
| `frontend/src/lib/taxEngine.test.mjs` | Runner golden frontend (fixture yang sama). |
| `backend/tests/tax_engine_parity_test.py` | Parity Python == JS untuk **seluruh field** (golden + fuzz 3 seed) & kesetaraan v1 legacy. |

Jalankan:
```bash
python3 backend/tests/tax_engine_golden_test.py
node frontend/src/lib/taxEngine.test.mjs
python3 backend/tests/tax_engine_parity_test.py   # butuh node
```

## Model per baris
Purchasing memilih: **mode harga** (`INCLUDE` | `EXCLUDE` | `NONE`) + **jenis transaksi PPN** (master Accounting).
Pengaturan lanjutan: fasilitas & PPnBM. Pengaturan Accounting (bukan pilihan Purchasing):
`input_vat_creditable`, `cost_treatment` (`CAPITALIZE_TAX` | `EXCLUDE_TAX`), `acquisition_type` (`INVENTORY` | `ASSET` | `SERVICE`).

Aturan pajak (`tax_rule`): `code, name, rate, dpp_factor_num/den, trx_code, facility`
- `facility`: `NORMAL` | `TIDAK_DIPUNGUT` | `DTP` | `DIBEBASKAN` (dibedakan, tidak digabung dengan "Tanpa PPN").
- `trx_code` (kode transaksi faktur) **wajib dari master** — tidak diturunkan dari tarif. Master lama (hanya tarif) → faktor 1/1, kode kosong → ditolak bila dipakai.

## Rumus (PO, presisi sen, HALF_UP berantai)
```
gross = qty × harga                     → sen
diskon item (Rp atau %)                 → sen, dibatasi 0..gross
Diskon Final (Rp/%)                     → prorata ke net baris, sisa terbesar per sen
net   = gross − diskon item − porsi Diskon Final
DPP   = net (Exclude)  |  net ÷ (1 + tarif×faktor + tarif PPnBM) (Include)
DPP Nilai Lain (dpp_other) = DPP × faktor        (mis. 11/12)
PPN   = DPP Nilai Lain × tarif
PPnBM = DPP × tarif PPnBM                         (komponen terpisah)
Total = DPP + PPN(ditagih) + PPnBM
```
- `dpp` **tetap** = nilai komersial tanpa PPN setelah semua diskon (dasar nilai perolehan existing).
- Fasilitas: PPN tidak ditagih (`tax_amount = 0`), nilainya dicatat di `tax_facility_amount`; tidak boleh Include atau PPnBM.
- Include: selisih rekonstruksi ditampilkan eksplisit di `include_rounding_diff` (contoh Rp1.005 → 0,01).
- `cost_base` = DPP + PPnBM (+ PPN bila tidak dapat dikreditkan **dan** kebijakan `CAPITALIZE_TAX`); `cost_by_type` per persediaan/aset/jasa.
  Ini hanya **informasi**; tidak memposting ke persediaan/HPP.
- Supplier Non-PKP (`supplier_pkp = false`) + baris ber-PPN → ditolak (koreksi via Master Supplier).
- Tidak ada pembulatan rupiah di PO. Grand total = jumlah total baris (identik form & cetak).

## Invoice
- Tagihan parsial / multi-DO: net = net PO × qty/qty PO (sen HALF_UP); tagihan yang menggenapi qty PO memakai **sisa** (tanpa drift).
  Entri berulang untuk baris PO yang sama dalam satu invoice diakumulasi otomatis.
- Faktur per kelompok (kode transaksi + aturan): jumlah baris → **rupiah penuh HALF_UP** (PER-11/PJ/2025 Ps.129(3)).
- `expected_payable` = DPP + non-PPN + PPN faktur + PPnBM faktur; `rounding_adjustment` = selisih terhadap jumlah baris.
- Rekonsiliasi faktur aktual: selisih 0 = `MATCH`; ≤ Rp1 = `WARNING`; > Rp1 = `NEEDS_APPROVAL` (`requires_reason = true`).

## Supplier DP
- `compute_dp(amount, rule, with_faktur)`: DP bruto; dengan faktur uang muka → DPP/DPP NL/PPN DP (rupiah HALF_UP).
- `settle_with_dp(invoice, dps)`: faktur pelunasan = faktur invoice − faktur DP; PPN diakui total = PPN invoice (**tidak ganda**).
  DP > invoice atau PPN DP > PPN invoice → ditolak.

## Versi & snapshot (output engine; penyimpanan pada fase integrasi)
- `tax_engine_version = 2` di dokumen & tiap baris; `rounding_policy` di output.
- Snapshot per baris: `tax_code, tax_name, tax_rate, tax_dpp_factor_num/den, tax_trx_code, tax_facility`.
- Snapshot dokumen: `tax_rules_snapshot` (unik per kelompok, urut kemunculan).
- Dokumen tanpa versi = v1 legacy → `compute_v1` (salinan beku `compute_po_totals`; parity test memastikan identik dengan produksi).
  `compute_document` memilih mesin dari versi **tersimpan** di dokumen.

## Parsing angka
Hanya format `123`, `123.45`, `1e3` (titik desimal). `1.000,50`, `1,5`, `1_000`, NaN/Infinity, eksponen ekstrem → ditolak (tidak ditebak).

## Ditunda ke fase berikutnya
- F2: integrasi ke form PO (UI sesuai desain disetujui), API preview/simpan, penyimpanan snapshot & versi.
- F3+: Vendor Invoice (faktur aktual, approval selisih), Supplier DP, laporan membaca snapshot, master jenis transaksi PPN (field `dpp_factor`, `coretax_trx_code`, `facility`).
