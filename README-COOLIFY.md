# Deploy Procurement (ProcureFlow) di Coolify — MariaDB + Cloudflare R2

Monorepo:

```
/backend   -> FastAPI (Python 3.12), Dockerfile, port 8000
/frontend  -> React CRA build, disajikan Nginx, Dockerfile, port 80 (proxy /api ke backend)
```

Database **MariaDB** (skema otomatis: 46 tabel + `v_ringkasan_data`, terbaca di phpMyAdmin) dan lampiran di
**Cloudflare R2** (bucket privat, file dialirkan lewat backend).

---

## 1. Resource `Backend-Procurement` (Application)

| Pengaturan | Nilai |
|---|---|
| Build Pack | **Dockerfile** |
| Base Directory | `/backend` |
| Dockerfile Location | `/backend/Dockerfile` |
| Ports Exposes | `8000` |
| Port mappings | *(kosong)* |
| **Network aliases** | `backend-procurement` ← wajib, dipakai frontend |
| Health check path | `/api/_healthcheck` |

Environment variables (lihat `backend/.env.example`):

```
DATABASE_URL=mysql://mariadb:<password>@<host-internal-mariadb>:3306/default
DB_NAME=default
JWT_SECRET=<nilai lama dari production.env — jangan diganti agar user lama tetap valid>
ADMIN_EMAIL=agustrnt@gmail.com
ADMIN_PASSWORD=<nilai lama; hanya dipakai bila admin belum ada>
FRONTEND_URL=https://app.domain-anda.com
COOKIE_SECURE=auto
STORAGE_DRIVER=s3
R2_ACCOUNT_ID=<account id cloudflare>
R2_ACCESS_KEY_ID=<access key>
R2_SECRET_ACCESS_KEY=<secret>
R2_BUCKET=media-procurmentapp

# --- Multi-tenant / SaaS (versi KelolaKita) — WAJIB ---
DEFAULT_TENANT_ID=tenant-pt-real
DEFAULT_COMPANY_ID=company-pt-real
DEFAULT_TENANT_SLUG=pt-real
DEFAULT_TENANT_NAME=PT REAL
DEFAULT_TENANT_MAX_USERS=25
ENABLE_PUBLIC_TENANT_REGISTRATION=false
TENANT_TRIAL_DAYS=14
DISABLE_LEGACY_USER_SELF_REGISTER=true
PLATFORM_ADMIN_EMAIL=<email super admin platform>
PLATFORM_ADMIN_PASSWORD=<password kuat>
PLATFORM_ADMIN_NAME=Akuntakita Super Admin
# Opsional: batas upload lampiran (MB), default 15
# MAX_UPLOAD_MB=15
# Opsional: SMTP untuk email PO/undangan (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_FROM_NAME, SMTP_USE_TLS)
```

> **Penting (data dari staging KelolaKita di VPS):** data staging memakai `DEFAULT_TENANT_ID=tenant-pt-real-staging`,
> `DEFAULT_COMPANY_ID=company-pt-real-staging`, `DEFAULT_TENANT_SLUG=pt-real-staging`, `DEFAULT_TENANT_NAME=PT REAL STAGING`.
> Bila data yang dimigrasi berasal dari staging tersebut, **samakan nilai `DEFAULT_*` dengan sumbernya** agar tenant pertama
> tidak dibuat ganda. Platform Super Admin: `PLATFORM_ADMIN_EMAIL` yang sama dengan sumber (`platform-staging@akuntakita.com`)
> — bila sudah ada, password lama dipertahankan.

Backend tidak perlu domain publik; frontend mem-proxy `/api`. Bila memakai domain terpisah untuk API,
isi `FRONTEND_URL`/`CORS_ORIGINS` dengan origin frontend (cookie otomatis `SameSite=None; Secure` di HTTPS).

## 2. Resource `Frontend-Procurement` (Application)

| Pengaturan | Nilai |
|---|---|
| Build Pack | **Dockerfile** |
| Base Directory | `/frontend` |
| Dockerfile Location | `/frontend/Dockerfile` |
| Ports Exposes | `80` |
| Port mappings | *(kosong)* |
| Domain | `https://app.domain-anda.com` (awali **https://**) |

Environment variables:

```
BACKEND_URL=http://backend-procurement:8000
```

> Nilai harus URL lengkap dengan `http://` dan port **8000**. Image otomatis memperbaiki nilai tanpa skema,
> tanda kutip, atau awalan `BACKEND_URL=` yang tidak sengaja ikut, dan menghapus `/` di akhir.
> Nama container Coolify (`<uuid>-<timestamp>`) berubah tiap redeploy — gunakan **Network alias** backend.

Nginx me-resolve host backend saat request: jika backend belum siap, frontend tetap *healthy* dan `/api`
membalas `502 {"detail": "Server aplikasi belum dapat dihubungi..."}` lalu pulih otomatis (≤10 detik).

## 3. phpMyAdmin (Service)

```
PMA_HOST=<host mariadb>      # internal atau IP publik
PMA_PORT=3306                # atau port publik yang dibuka Coolify
PMA_ARBITRARY=0
UPLOAD_LIMIT=64M
PMA_ABSOLUTE_URI=$SERVICE_URL_PHPMYADMIN
```
Login user `mariadb`. Database `default` berisi tabel per koleksi (`items`, `po`, `mro`, `stock_ledger`, …).
Kolom `doc` = dokumen JSON lengkap; kolom lain (mis. `code`, `name`, `status`, `*_id`) adalah kolom *generated*
terindeks yang otomatis mengikuti `doc`. View `v_ringkasan_data` menampilkan jumlah baris per tabel.

> Ubah data lewat aplikasi/API. Jika terpaksa edit manual, ubah kolom **`doc`** (JSON); kolom generated akan ikut.

## 4. Urutan deploy pertama

1. Buat/verifikasi MariaDB & bucket R2. Migrasikan data (bagian 5) **sebelum** backend dipakai.
2. Deploy **Backend-Procurement** → tunggu *Running* & health check hijau. Log start harus memuat
   `Database: MariaDB`, `Attachment storage: r2`, `Admin user already exists; preserving current password`.
3. Isi *Network aliases* backend = `backend-procurement` (Save → Redeploy bila baru diisi).
4. Deploy **Frontend-Procurement** dengan `BACKEND_URL=http://backend-procurement:8000`.
5. Buka `https://<domain>/api/_system` → `{"ok":true,"db":"mariadb","storage":"s3","cookieSecure":true,"requestProto":"https"}`.
6. Login dengan akun admin lama (password yang berlaku di produksi lama).

## 5. Migrasi data dari produksi lama (MongoDB)

Dari mesin yang punya `mongorestore` dan akses ke MariaDB (mis. laptop/VPS lama):

```bash
cd backend && pip install -r requirements.txt
export DATABASE_URL='mysql://mariadb:<password>@<host>:<port>/default'

# 1) data: dump Mongo -> MariaDB (idempoten; --truncate untuk cut-over bersih)
python scripts/migrate_mongo_to_mariadb.py --archive /path/mongodb.archive.gz --archive-db procurement \
       --mongo mongodb://localhost:27017 --db procurement_migrasi --truncate --report migrasi.json
#    -> mencetak count Mongo vs MariaDB per koleksi; harus "SEMUA COCOK"

# 2) lampiran: folder uploads lama / tar.gz -> R2 (key identik dengan storage_path di DB)
export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=media-procurmentapp
python scripts/migrate_attachments_to_r2.py --source /path/local-attachments.tar.gz

# 3) (opsional) validasi: bandingkan API backend Mongo vs MariaDB
python scripts/poc_diff_endpoints.py --mariadb http://localhost:8000 --mongo-url mongodb://localhost:27017 \
       --mongo-db procurement_migrasi --email <admin> --password <pass> --start-mongo-backend
```

Riwayat migrasi:
- 2026-09-23 (versi lama PT Rajawali, `/opt/procurement`): 41/41 koleksi cocok, 5 lampiran, differential test 56/59 identik.
- 2026-09-23 (versi **KelolaKita** multi-tenant, `procurement-tenant-test` / `procurement_saas_staging`): **47/47 koleksi cocok**
  (2 tenant, 3 user, 10 item, 2 PO, 36 stock_ledger, platform_settings + branding), 4 file branding (logo platform & company) ke R2,
  differential test tenant admin **72/75** dan platform admin **59/61** identik (sisanya stempel `updated_at` startup & logo pada
  instance uji berstorage lokal), 13 test integritas penulis (`*_test.py` via HTTP) lulus di MariaDB
  (`bash scripts/run_integrity_tests_mariadb.sh`).

Catatan multi-tenant pada MariaDB: dokumen dengan `id` sama di beberapa tenant (mis. `settings.numbering` per tenant)
disimpan dengan `pk = "<tenant_id>:<id>"`; lookup tetap memakai kolom generated `id` yang terindeks.

## 6. Skema & regenerasi

- Skema diterapkan otomatis saat backend start (`DB_AUTO_SCHEMA=true`), dilewati bila hash `schema.sql` sama
  (tabel `_schema_meta`). Paksa: `DB_FORCE_SCHEMA=1`.
- Tabel baru untuk koleksi yang belum ada dibuat otomatis saat pertama dipakai (`pk`, `doc`, `id`).
- Regenerasi kolom generated dari data terbaru: `python scripts/generate_schema.py --mongo ... --db ... --code-dir . --out database/schema.sql`
  (atau sesuaikan generator untuk membaca MariaDB).

## 7. Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| Frontend 502 JSON "Server aplikasi belum dapat dihubungi" | `BACKEND_URL` tidak resolve | Isi *Network aliases* backend `backend-procurement`, redeploy backend; cek `BACKEND_URL=http://backend-procurement:8000` |
| Login sukses lalu "Not authenticated" | Cookie `Secure` di situs `http://` | Pakai HTTPS atau `COOKIE_SECURE=false` sementara |
| `Bucket R2 ... tidak dapat diakses` saat start | Kredensial/bucket R2 salah | Cek `R2_*`; token harus *Object Read & Write* untuk bucket itu |
| Respons lambat | Latensi DB (backend dan MariaDB beda server/jaringan) | Gunakan host **internal** MariaDB di `DATABASE_URL` |
| Cek cepat | – | `GET /api/_system`, `GET /api/_healthcheck` |

## 8. Backup

- MariaDB: fitur backup terjadwal Coolify (ke S3/R2).
- Lampiran sudah di R2 (aktifkan *Object Versioning* bila perlu).
