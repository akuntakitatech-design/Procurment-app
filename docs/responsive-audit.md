# Audit & Perbaikan Responsive Design — Procurement & Warehouse PT REAL

Branch `feat/responsive-ui` (base `main` 5865db3, sudah termasuk merge PR #69/#70/#71). **Frontend/CSS/layout saja**: tidak ada perubahan backend,
API, database, permission, approval workflow, stock ledger, HPP/valuasi, atau kalkulasi.

## Strategi
- **Mobile-first**, breakpoint Tailwind existing (`sm` 640, `md` 768, `lg` 1024, `xl` 1280). Semua aturan mobile
  dipasang di `max-width: 639.98px` atau kelas `sm:` sehingga tampilan desktop tidak berubah.
- **Sidebar**: desktop (≥1024px) tetap statis; < 1024px menjadi drawer (hamburger, overlay, tombol tutup, Escape,
  otomatis tutup saat pindah halaman). Overlay dimulai dari tepi kanan drawer agar seluruh area gelap bisa di-tap.
- **Hybrid table**:
  - Daftar transaksi utama (MRO/RO/PO/DO/MI/Invoice via `TxnList` & `invoice/DataTable`) dan tabel prioritas
    (Inventory, Supplier DP, baris item MRO/MI/DO/Transfer/Pinjam/Adjustment/Opname) memakai `.m-stack`:
    tabel → kartu bertumpuk di < 640px, label kolom dari `data-label`. DOM sama, **tidak ada kolom/aksi yang dihilangkan**.
  - Header tabel tersembunyi di kartu → urutkan lewat `MobileSortBar` (pilih kolom + arah).
  - Tabel lain tetap scroll horizontal di dalam container `overflow-x-auto` (bukan scroll halaman).
- **Form**: grid multi-kolom → 1 kolom di mobile; editor baris ber-lebar-tetap (`.m-flex`) → grid 2 kolom.
  Aksi halaman pindah ke action bar bawah (fixed) di mobile.
- **Dialog/AlertDialog**: lebar `100% - 1.5rem`, tinggi maksimal `100dvh - 1.5rem` dengan scroll internal.
- **Target sentuh**: di < 640px, Button/Select/Input shadcn di konten & dialog min. 44px; tombol ikon min. 44×44;
  tab list membungkus; header sortable min. 44px; tombol teks kecil (no. dokumen, link laporan, toggle dashboard)
  diberi `min-h-11 sm:min-h-0`.

## Temuan baseline (`main`) → hasil
Audit otomatis Playwright: 44 route × 9 viewport (320, 375, 390, 430, 768, 1024, 1366, 1440, 1920) = 396 kombinasi.

| Metrik | Baseline `main` | Setelah perbaikan |
|---|---|---|
| Kombinasi dengan overflow horizontal halaman / elemen keluar layar | 13 | **0** |
| Kontrol < 36px di mobile (heuristik awal, 4 viewport mobile) | 2588 | 8 |
| Kontrol < 44px di mobile (heuristik ketat, checkbox dikecualikan) | tidak diukur | 8 — seluruhnya badge stok mini di input qty (`do-stock-0`, `mi-stock-0`); area tap diperluas via pseudo-element |

Overflow baseline: `/ro/{id}` (320–390), `/reports` (320), `/invoice` (320–375), `/dp-supplier` (mobile + 768/1024),
`/activity-log` (1024, input filter melebar). Semua sudah 0.

## Verifikasi
- `CI=true yarn build` — sukses.
- Unit test frontend `node --test src/**/*.test.mjs` — 29/29 pass (`yarn test`/Jest: tidak ada test Jest di repo).
- `testing_agent_v3` iterasi 7: 1 temuan (klik overlay drawer tertutup sidebar) → diperbaiki;
  iterasi 8: **0 temuan** (verifikasi fix + regresi drawer, kartu list, overflow, desktop);
  iterasi 9 (setelah rebase ke `main` 5865db3): **0 temuan** (kartu tahap MRO + regresi).
- Audit ulang setelah rebase: 0 overflow / 396.
- Screenshot before/after disimpan di luar repo (sandbox QA), tidak di-commit.

## Batasan yang disengaja
- Badge stok mini (`*-stock-N`) di atas input qty tetap ringkas agar tidak menutupi input; area tap diperluas
  ke atas/samping saja.
- Tabel non-prioritas (mis. SPK, Kontrak Vendor, Master, Report Center) memakai scroll horizontal dalam container.
