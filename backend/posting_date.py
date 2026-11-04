"""Normalisasi tanggal posting ke kalender WIB (Asia/Jakarta, UTC+7).

Aplikasi mengirim tanggal bisnis dari DatePicker lewat `toISOString()`, sehingga tanggal
02/11/2026 WIB tersimpan sebagai `2026-11-01T17:00:00.000Z`. Sebagian transaksi sistem
memakai timestamp UTC apa adanya. Keduanya tidak boleh dibandingkan sebagai potongan
string, karena hasilnya bisa menganggap transaksi di hari yang sama sebagai "mundur".

Semua perbandingan tanggal stok memakai tanggal kalender WIB (tanggal tanpa jam/zona).
Tanpa dependensi DB agar bisa diuji terpisah.
"""
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))


def wib_date(value) -> str:
    """Tanggal kalender WIB `YYYY-MM-DD` dari tanggal (YYYY-MM-DD) atau ISO timestamp.

    - `"2026-11-02"`              -> `"2026-11-02"` (sudah tanggal kalender)
    - `"2026-11-01T17:00:00Z"`    -> `"2026-11-02"` (tengah malam WIB)
    - `"2026-11-02T02:30:03Z"`    -> `"2026-11-02"`
    - timestamp tanpa zona dianggap UTC, sesuai `server.now_iso()`.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(WIB).date().isoformat()


def is_backdated(new_at, last_at) -> bool:
    """True hanya jika tanggal (WIB) transaksi baru BENAR-BENAR lebih awal dari tanggal terakhir.

    Tanggal sama (termasuk beda jam) tidak dianggap mundur.
    """
    new_d, last_d = wib_date(new_at), wib_date(last_at)
    return bool(new_d and last_d and new_d < last_d)
