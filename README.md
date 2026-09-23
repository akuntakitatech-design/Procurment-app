# Procurement (ProcureFlow) — Akuntakita

Aplikasi web **pengadaan & pengelolaan gudang** (procurement-to-warehouse) untuk perusahaan dengan banyak
divisi/gudang: permintaan barang (MRO), permintaan pembelian (RO), purchase order (PO) dengan alur
approval, penerimaan barang (DO), pengeluaran barang (MI), pinjaman & retur, transfer antar gudang,
stock opname, penyesuaian, jejak audit, laporan (lead time, traceability, unit usage), impor Excel,
serta pengaturan layout cetak/tanda tangan dan pesan dokumen.

> Versi ini adalah **migrasi penuh dari MongoDB ke MariaDB** dengan lampiran di **Cloudflare R2**,
> disusun sebagai monorepo `/backend` + `/frontend` untuk deploy di **Coolify**. Panduan deploy:
> [`README-COOLIFY.md`](./README-COOLIFY.md).

---

## 1. Overview Project

| Modul | Fungsi |
|---|---|
| Dashboard & Dashboard Premium | Ringkasan stok, dokumen terbuka (MRO/RO/PO), PO menunggu approval, DO/MI hari ini, notifikasi |
| Master Data | Item (kode otomatis `BRG-xxxxx`), gudang, supplier, proyek, unit/divisi, UoM & konversi, kategori, pajak, kontak, template cetak |
| MRO (Material Request Order) | Permintaan barang dari divisi → dipenuhi dari stok (MI) atau dibeli (RO) |
| RO (Request Order) | Permintaan pembelian, ditarik dari MRO |
| PO (Purchase Order) | Pesanan ke supplier, approval bertingkat (inbox approval, email opsional), cetak dengan tanda tangan |
| DO (Delivery/Receipt) | Penerimaan barang dari PO ke gudang → stock ledger + item_warehouse |
| MI (Material Issue) | Pengeluaran barang untuk MRO |
| Pinjaman & Retur, Transfer, Opname, Adjustment | Mutasi stok lainnya dengan jejak ledger |
| Inventory | Posisi stok per gudang, kartu stok (ledger), saldo awal (opening inventory) |
| Laporan | Lead time, MRO traceability (+ ekspor XLSX), unit usage, pencarian global |
| Activity Log & Audit | Jejak semua perubahan (siapa, kapan, apa) |
| Pengaturan | Branding perusahaan (logo), layout cetak & tanda tangan PO, pesan dokumen, kode master, email keluar, pengguna & hak akses |

Bahasa antarmuka: **Indonesia**. Peran pengguna: `admin`, `approver`, `purchasing`, `warehouse`, `requester`
(hak akses granular per modul, dibatasi per divisi/gudang).

---

## 2. Tech Stack

| Lapisan | Teknologi | Catatan |
|---|---|---|
| Frontend | **React 19** (Create React App + craco), React Router, shadcn/ui + Radix, Tailwind CSS, lucide-react, axios | Build statis disajikan **Nginx** (Docker). Memanggil API relatif `/api/...` |
| Backend | **FastAPI** (Python 3.12), Uvicorn, Pydantic | ~30 modul "layer" yang dipasang oleh `production_bootstrap.py` di atas `server.py` |
| Database | **MariaDB 11** via `mariadb_motor.py` (lapisan kompatibel-Motor di atas `aiomysql`) | 1 tabel per koleksi: `pk`, `doc` (JSON) + **kolom generated** terindeks agar terbaca di phpMyAdmin. Skema: `backend/database/schema.sql` (idempoten, otomatis saat start) |
| Auth | JWT (access 1 jam + refresh 7 hari) dalam **cookie HttpOnly**; password **bcrypt**; rate-limit login; `token_version` untuk revoke | Flag `Secure`/`SameSite` mengikuti protokol request (`COOKIE_SECURE=auto`) |
| Storage objek | **Cloudflare R2** (S3-compatible, `boto3`) untuk lampiran dokumen, logo, tanda tangan | Fallback `local` (disk) bila env R2 kosong; file diunduh melalui backend (bucket privat) |
| Email | SMTP (opsional) untuk notifikasi approval | |
| Deploy | Docker (multi-stage), **Coolify**, Traefik (HTTPS), phpMyAdmin | Lihat `README-COOLIFY.md` |
| Kualitas | Differential test Mongo-vs-MariaDB (`scripts/poc_diff_endpoints.py`), pytest (`backend/tests`), testing agent E2E | |

---

## 3. Folder Structure

```
.
├── backend/                         # API FastAPI (resource Coolify: Backend-Procurement, port 8000)
│   ├── server.py                    # App utama: auth, master data, endpoint dasar, CORS, /api/_healthcheck, /api/_system
│   ├── production_bootstrap.py      # Entry produksi: memasang semua layer lalu menjalankan uvicorn
│   ├── mariadb_motor.py             # Lapisan kompatibel-Motor -> MariaDB (find/update/aggregate/...)
│   ├── auth.py                      # JWT, bcrypt, cookie (COOKIE_SECURE=auto), seed admin
│   ├── storage.py                   # Adapter storage: R2/S3 (boto3) atau lokal
│   ├── doc_procurement.py           # MRO / RO / PO / approval
│   ├── doc_warehouse.py             # DO / MI / pinjaman / transfer / opname / adjustment / ledger
│   ├── doc_reports.py               # Dashboard & laporan
│   ├── *_layer.py                   # Fitur tambahan modular (activity log, print layout, excel import, dst.)
│   ├── master_auto.py               # Master data generik + penomoran kode otomatis (counters)
│   ├── database/schema.sql          # Skema MariaDB (46 tabel + v_ringkasan_data), digenerate & idempoten
│   ├── scripts/
│   │   ├── generate_schema.py       # Regenerasi schema.sql dari data/kode
│   │   ├── migrate_mongo_to_mariadb.py  # Migrasi data produksi Mongo -> MariaDB (+ laporan count)
│   │   ├── migrate_attachments_to_r2.py # Upload lampiran lokal -> R2 (key sama dengan storage_path)
│   │   └── poc_diff_endpoints.py    # Differential test API Mongo vs MariaDB
│   ├── tests/                       # pytest
│   ├── requirements.txt
│   ├── .env.example                 # Semua env berkomentar (tanpa rahasia)
│   └── Dockerfile                   # python:3.12-slim, healthcheck /api/_healthcheck
├── frontend/                        # React CRA (resource Coolify: Frontend-Procurement, port 80)
│   ├── src/
│   │   ├── pages/                   # Satu file per halaman: Dashboard, Mro, Ro, Po, Do, Mi, Loan, Transfer, Opname, ...
│   │   ├── components/              # Komponen bersama (DocList, ItemLines, PullDialog, StatusBadge, Layout, ui/*)
│   │   ├── context/AuthContext.js   # Sesi pengguna & hak akses
│   │   ├── hooks/                   # useMasters, use-toast
│   │   ├── lib/api.js               # Klien axios (withCredentials, base URL relatif)
│   │   └── lib/format.js, print.js  # Format angka/tanggal, cetak dokumen
│   ├── nginx/
│   │   ├── default.conf.template    # Proxy /api -> ${BACKEND_URL} (resolver runtime), SPA fallback, cache
│   │   ├── 05-normalize-backend-url.envsh  # Normalisasi BACKEND_URL (http://, kutip, slash)
│   │   └── 16-resolver-fallback.envsh      # Fallback DNS Docker 127.0.0.11
│   ├── craco.config.js, tailwind.config.js, package.json
│   └── Dockerfile                   # node build -> nginx:alpine
├── legacy/                          # Artefak lama (CI workflow, dsb.) — tidak dipakai Coolify
├── docker-compose.yml, SELF_HOSTING.md, deploy.env.example  # Referensi self-host VPS lama (MongoDB)
├── README-COOLIFY.md                # Panduan deploy Coolify (env, Network Alias, troubleshooting)
└── README.md
```

---

## 4. Data Flow

### 4.1 Alur request umum

```
Browser (React SPA)
   │  axios  GET/POST /api/...  (cookie access_token/refresh_token ikut otomatis)
   ▼
Nginx (container frontend)  ── /api/*  ──►  http://backend-procurement:8000   (jaringan internal Coolify)
   │  (selain /api: sajikan build statis, SPA fallback ke index.html)
   ▼
FastAPI (server.py + layer)
   │  Depends(current_user)  → auth.py verifikasi JWT dari cookie, cek role/permission/divisi/gudang
   │  handler  →  db.<koleksi>.find / update_one / find_one_and_update ...
   ▼
mariadb_motor.py
   │  1) pushdown filter sederhana ke SQL (kolom generated terindeks)
   │  2) muat dokumen JSON, terapkan filter/sort/proyeksi dengan semantik Mongo di Python
   │  3) update: transaksi + SELECT ... FOR UPDATE (aman untuk counter/$inc)
   ▼
MariaDB  (tabel per koleksi: pk | doc JSON | kolom generated | created_at | updated_at)
   ▲
phpMyAdmin (baca/kelola data; kolom generated membuat JSON terbaca sebagai kolom biasa)
```

### 4.2 Login & sesi

1. `POST /api/auth/login` → cek `login_attempts` (maks 5/15 menit) → `users.find_one({email})` → `bcrypt.checkpw`.
2. Backend menerbitkan **access token (1 jam)** + **refresh token (7 hari)** sebagai cookie HttpOnly.
   `Secure`/`SameSite=None` otomatis bila request HTTPS (dibaca dari `X-Forwarded-Proto` yang diteruskan Nginx/Traefik).
3. Setiap request: `current_user` memverifikasi token dan `token_version` (berubah saat password/hak diubah → sesi lama gugur).

### 4.3 Dokumen & stok (contoh MRO → PO → DO)

```
MRO (requester)  ─► RO (pull dari MRO)  ─► PO (approval bertingkat, email opsional)
                                               │ approved
                                               ▼
                                     DO (penerimaan ke gudang)
                                               │  stock_ledger (+qty)  →  item_warehouse (saldo per gudang)
                                               ▼
MI (pengeluaran untuk MRO)  ─► stock_ledger (−qty)  →  item_warehouse
```
Setiap mutasi menulis `audit_logs`/`activity_log`, dan penomoran dokumen memakai `counters`
(`find_one_and_update` + `$inc`, atomik di MariaDB lewat `FOR UPDATE`).

### 4.4 Lampiran

`POST /api/attachments` (base64/multipart) → `storage.put_object(key, bytes)` → **R2** (`procureflow/uploads/<doc>/<uuid>.<ext>`)
→ metadata (`storage_path`, nama, ukuran) disimpan di tabel `attachments`. Unduh: `GET /api/attachments/{id}/download`
→ backend `get_object` dari R2 dan mengalirkan file (bucket tetap privat). Logo & tanda tangan PO mengikuti pola yang sama.

### 4.5 Migrasi data (sekali jalan)

```
mongodb.archive.gz ─► mongorestore (lokal) ─► scripts/migrate_mongo_to_mariadb.py ─► MariaDB   (laporan count per koleksi)
local-attachments.tar.gz ─► scripts/migrate_attachments_to_r2.py ─► R2 (key identik dengan storage_path)
scripts/poc_diff_endpoints.py ─► bandingkan respons API backend Mongo vs MariaDB
```

---

## 5. Coding Conventions

### Umum
- **Bahasa**: identifier kode & nama file **Inggris**; teks UI, pesan error API (`detail`), komentar penjelas, dokumentasi **Indonesia**.
- Tidak ada rahasia di repo — semua lewat env (`backend/.env.example` sebagai acuan). Nilai default aman di Dockerfile.
- Setiap perubahan lewat **Pull Request** berbahasa Indonesia berisi: masalah, perbaikan, cara uji, tindakan di Coolify.

### Backend (Python / FastAPI)
| Hal | Konvensi |
|---|---|
| File | `snake_case.py`; fitur tambahan sebagai `*_layer.py` dengan fungsi `install(server)` yang dipasang di `production_bootstrap.py` (jangan ubah urutan tanpa alasan — layer belakangan boleh menimpa route). |
| Fungsi/variabel | `snake_case`; konstanta `UPPER_CASE`; kelas `PascalCase`. Handler async: `async def list_mro(...)`. |
| Route | Prefix `/api`; dokumen: `/api/{mro,ro,po,do,mi,loans,transfers,opname,adjustments}` + `/{id}` + aksi (`/submit`, `/approve`, `/cancel`). Master: `/api/master/{name}`. Sistem: `/api/_healthcheck`, `/api/_system`. |
| Auth | Selalu `user=Depends(current_user)`; cek hak dengan helper `require_perm`/role; batasi divisi/gudang dari `user["divisions"]`/`user["warehouses"]`. |
| Akses data | **Hanya** lewat `server.db.<koleksi>` (API Motor: `find`, `find_one`, `insert_one`, `update_one`, `find_one_and_update`, `count_documents`, `delete_many`, `aggregate`). Jangan menulis SQL langsung di handler — dukungan operator baru ditambahkan di `mariadb_motor.py` beserta uji. |
| Dokumen | Setiap dokumen punya `id` (UUID v4 string, `gid()`), `created_at` ISO-8601 UTC (`now_iso()`), soft-state via `submitted`/`cancelled`/`status`. Proyeksi selalu `{"_id": 0}`. |
| Penomoran | Kode/nomor lewat `counters` + `find_one_and_update({"id": key}, {"$inc": {"seq": 1}}, upsert=True)` — jangan hitung `count()+1`. |
| Error | `HTTPException(status_code, detail="pesan Indonesia")`. 400 validasi, 401 belum login, 403 hak akses, 404 tidak ditemukan, 409 konflik. |
| Gaya | PEP 8, 4 spasi, f-string, type hint pada fungsi publik, `logger = logging.getLogger("procureflow")`. |
| Skema | Jangan edit `schema.sql` manual: jalankan `scripts/generate_schema.py` lalu commit hasilnya. Nama tabel = nama koleksi (`snake_case`), kolom generated = nama field. |

### Frontend (React)
| Hal | Konvensi |
|---|---|
| File | Halaman `PascalCase.jsx` di `pages/` (satu modul = satu halaman); komponen `PascalCase.jsx` di `components/`; util `camelCase.js` di `lib/`; hooks `useX.js`. |
| Komponen | Function component + hooks; props `camelCase`; state lokal dengan `useState`, data master via `useMasters`. |
| API | Selalu lewat `lib/api.js` (axios, `withCredentials: true`, base URL relatif `/api`); jangan hardcode host. Tangani error dengan `toast` (`use-toast`). |
| UI | shadcn/ui + Tailwind; kelas utilitas, hindari CSS inline; ikon `lucide-react`; tabel dokumen memakai `DocList`, baris item `ItemLines`, status `StatusBadge`. |
| Format | Angka/uang/tanggal lewat `lib/format.js` (locale `id-ID`). |
| Routing | React Router; path `kebab-case` (`/mro`, `/po`, `/print-layouts`); halaman dilindungi `AuthContext`. |
| Atribut uji | Tambahkan `data-testid` pada elemen interaktif baru (tombol, input, baris tabel) untuk testing E2E. |

### Nginx / Docker / Coolify
- Template Nginx di `frontend/nginx/default.conf.template` diproses `envsubst`; hanya variabel `${BACKEND_URL}`, `${NGINX_PORT}`, `${CLIENT_MAX_BODY_SIZE}`, `${NGINX_LOCAL_RESOLVERS}` yang boleh dipakai (variabel Nginx `$host` dsb. tetap aman).
- Script `docker-entrypoint.d/*.envsh` harus POSIX `sh`, executable, dan bernomor agar urutan jelas (`05-`, `16-`).
- Backend didengarkan di `0.0.0.0:8000`, health check `GET /api/_healthcheck`; frontend `GET /healthz`.

### Git
- Branch: `feature/<topik>`, `fix/<topik>`, `docs/<topik>`; commit *conventional*: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`.
- Jangan push ke branch yang PR-nya sudah merged; hapus branch setelah merge.

---

## Menjalankan lokal (tanpa Docker)

```bash
# Backend
cd backend && pip install -r requirements.txt
cp .env.example .env            # isi DATABASE_URL (MariaDB), JWT_SECRET, ADMIN_*, R2_* (opsional -> STORAGE_DRIVER=local)
python production_bootstrap.py  # http://localhost:8000/api/_healthcheck

# Frontend (terminal lain)
cd frontend && yarn install
REACT_APP_BACKEND_URL=http://localhost:8000 yarn start   # http://localhost:3000
```

Migrasi data dari dump Mongo lama: lihat bagian **4.5** dan `README-COOLIFY.md` § Migrasi data.
