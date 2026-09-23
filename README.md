# Procurement / ProcureFlow

Sistem Procurement, Warehouse & Inventory Control dengan traceability:

```text
MRO -> RO -> PO -> DO -> MI
```

Fitur utama mencakup multi gudang, proyek/unit, approval PO, SPK, penerimaan supplier, material issued, transfer, pinjam-return antar gudang, stock adjustment, stock opname, attachment, print/signature, access control, serta reporting traceability.

## Struktur

- `frontend/` — React UI
- `backend/` — FastAPI API + MongoDB
- `docker-compose.yml` — stack self-hosted
- `deploy/` — script deploy, backup, restore dan template Nginx
- `SELF_HOSTING.md` — panduan deployment production

## Self-hosted production

Lihat [SELF_HOSTING.md](SELF_HOSTING.md).

Production stack menggunakan MongoDB dan MinIO milik server sendiri; runtime attachment tidak bergantung pada Emergent Object Storage.
