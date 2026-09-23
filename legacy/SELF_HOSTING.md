# Procurement — Self-Hosted Production

Stack produksi:

- Frontend: React build + Nginx container
- Backend: FastAPI + Uvicorn
- Database: MongoDB 7
- Attachment storage: MinIO (S3-compatible) atau local volume
- Reverse proxy publik: Nginx host + Let's Encrypt

## 1. Persiapan server

Contoh Ubuntu 22.04/24.04:

```bash
sudo apt update
sudo apt install -y git nginx certbot python3-certbot-nginx ca-certificates curl
```

Install Docker Engine + Compose plugin dari repository resmi Docker, kemudian cek:

```bash
docker --version
docker compose version
```

## 2. Clone repository

```bash
sudo mkdir -p /opt/procurement
sudo chown -R $USER:$USER /opt/procurement
git clone https://github.com/agustrnt-bit/Procurement.git /opt/procurement
cd /opt/procurement
git checkout self-hosted-production
```

Karena repository private, gunakan GitHub SSH key atau Personal Access Token yang hanya memiliki akses repo yang diperlukan.

## 3. Environment production

```bash
cp deploy.env.example .env
nano .env
```

Wajib ganti seluruh `CHANGE_ME`.

Untuk secret yang kuat:

```bash
openssl rand -hex 32
```

Gunakan password MongoDB yang URL-safe atau URL-encode password tersebut pada `MONGO_URL`.

Contoh public URL:

```env
PUBLIC_URL=https://procurement.domainanda.com
```

## 4. Jalankan stack

```bash
chmod +x deploy/*.sh
docker compose build
docker compose up -d
docker compose ps
```

Aplikasi hanya dibind ke localhost server pada port `8088` secara default. MongoDB dan MinIO tidak diekspos langsung ke internet.

Test dari server:

```bash
curl -I http://127.0.0.1:8088
```

## 5. Nginx host

Copy template:

```bash
sudo cp deploy/nginx-host.conf /etc/nginx/sites-available/procurement
sudo nano /etc/nginx/sites-available/procurement
```

Ganti:

```text
procurement.example.com
```

menjadi domain sebenarnya.

Aktifkan:

```bash
sudo ln -s /etc/nginx/sites-available/procurement /etc/nginx/sites-enabled/procurement
sudo nginx -t
sudo systemctl reload nginx
```

Pastikan DNS A record domain sudah mengarah ke IP server.

## 6. HTTPS

```bash
sudo certbot --nginx -d procurement.domainanda.com
```

Production wajib HTTPS karena authentication menggunakan secure cookies.

Setelah HTTPS aktif, cek:

```bash
curl -I https://procurement.domainanda.com
```

## 7. Update aplikasi

Setelah versi baru masuk ke branch production:

```bash
cd /opt/procurement
./deploy/deploy.sh
```

Atau manual:

```bash
git pull --ff-only
docker compose build --pull
docker compose up -d --remove-orphans
```

## 8. Backup

Jalankan:

```bash
./deploy/backup.sh
```

Hasil default berada di:

```text
backups/YYYYMMDD_HHMMSS/
```

Backup mencakup:

- MongoDB
- MinIO attachment data
- local attachment volume (jika digunakan)

Disarankan menyalin backup ke lokasi/server kedua, bukan hanya disk server production.

Contoh cron harian pukul 02:00:

```cron
0 2 * * * cd /opt/procurement && ./deploy/backup.sh >> /var/log/procurement-backup.log 2>&1
```

## 9. Restore

> Restore menggunakan `--drop` untuk database. Jalankan hanya ketika benar-benar diperlukan dan setelah memastikan backup yang dipilih benar.

```bash
./deploy/restore.sh /opt/procurement/backups/20260916_020000
```

## 10. Log dan troubleshooting

Semua service:

```bash
docker compose logs -f --tail=200
```

Backend:

```bash
docker compose logs -f backend
```

Frontend:

```bash
docker compose logs -f frontend
```

MongoDB:

```bash
docker compose logs -f mongodb
```

MinIO:

```bash
docker compose logs -f minio
```

Restart satu service:

```bash
docker compose restart backend
```

## 11. Security minimum

- Jangan commit file `.env`.
- Jangan expose port MongoDB `27017` ke internet.
- Jangan expose MinIO `9000/9001` ke internet kecuali ada alasan dan proteksi tambahan.
- Gunakan HTTPS.
- Gunakan password berbeda untuk admin aplikasi, MongoDB, dan MinIO.
- Backup ke lokasi kedua.
- Update OS dan Docker secara berkala.
- Batasi SSH dengan key authentication dan firewall.

## 12. Attachment storage

Default production menggunakan:

```env
STORAGE_DRIVER=minio
```

Backend sekarang tidak membutuhkan Emergent Object Storage. Alternatif sederhana:

```env
STORAGE_DRIVER=local
```

Jika menggunakan `local`, file disimpan pada persistent Docker volume di `/app/data/uploads`.

## 13. Alur release yang disarankan

```text
Emergent / development
        ↓
feature branch / test
        ↓
GitHub
        ↓
review + merge
        ↓
production branch
        ↓
server ./deploy/deploy.sh
```

Jangan menjadikan server production sebagai tempat utama mengedit source code.
