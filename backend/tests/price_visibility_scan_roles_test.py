"""Pemindai harga untuk role manager & finance TANPA view_purchase_price (tenant uji terpisah dari
price_visibility_scan_test.py karena batas user per tenant paket starter). Menjalankan pemindai yang sama sebagai
subproses dengan SCAN_USERS=manager_deny_price,finance_deny_price; exit code & ringkasan diteruskan apa adanya.

Pakai: TEST_API_URL=http://127.0.0.1:8013/api python price_visibility_scan_roles_test.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    env = {**os.environ, "SCAN_USERS": os.environ.get("SCAN_ROLES_USERS", "manager_deny_price,finance_deny_price")}
    r = subprocess.run([sys.executable, os.path.join(HERE, "price_visibility_scan_test.py"), *sys.argv[1:]], env=env, cwd=HERE)
    sys.exit(r.returncode)
