#!/bin/sh
# Jalankan seluruh suite regresi backend berurutan (DB remote lambat; paralel memicu 502).
cd /app
mkdir -p /tmp/reg
for t in backend/tests/stock_info_test.py backend/tests/vendor_invoice_test.py backend/tests/receipt_control_test.py \
         scripts/access_control_test.py scripts/division_hardening_test.py backend/tests/master_tenant_isolation_test.py \
         backend/tests/valuation_hardening_test.py; do
  n=$(basename "$t" .py)
  echo "START $n $(date +%T)" >> /tmp/reg/progress.log
  python3 -u "$t" > "/tmp/reg/$n.log" 2>&1
  echo "END $n exit=$? $(date +%T)" >> /tmp/reg/progress.log
done
echo ALLDONE >> /tmp/reg/progress.log
