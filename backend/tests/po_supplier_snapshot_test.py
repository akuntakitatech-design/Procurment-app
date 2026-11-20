"""Uji regresi snapshot supplier pada PO (tanpa DB, tanpa server).

Bug yang dijaga: saat Edit PO mengganti supplier, `supplier_bank_id` diperbarui tetapi field snapshot
`supplier_bank_name/_account_no/_account_name` tetap milik supplier lama. Cetak PO memprioritaskan
snapshot itu, sehingga PO mencetak rekening supplier lain.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import supplier_po_layer as SPL  # noqa: E402

BANK_A = {"id": "bank-a", "bank_name": "BCA", "account_no": "029-697-777-7",
          "account_name": "PT. Adiratna Alam Lestari", "currency": "IDR", "is_primary": True}
BANK_B = {"id": "bank-b", "bank_name": "BANK MANDIRI", "account_no": "108-001-248-620-6",
          "account_name": "Toko Zhafira DC", "currency": "IDR"}

SUP_A = {"id": "sup-a", "legal_name": "PT. Adiratna Alam Lestari", "banks": [BANK_A],
         "supplier_category_name": "Sparepart", "npwp": "01.234", "pkp": True}
SUP_B = {"id": "sup-b", "legal_name": "Zhafira DC", "banks": [BANK_B],
         "supplier_category_name": "Umum", "npwp": "02.345", "pkp": False}


def main():
    # 1. Rekening yang dipilih memang milik supplier -> snapshot dari rekening itu.
    snap = SPL.snapshot_fields(SUP_A, "bank-a")
    assert snap["supplier_bank_name"] == "BCA", snap
    assert snap["supplier_bank_account_no"] == "029-697-777-7", snap
    assert snap["supplier_bank_account_name"] == "PT. Adiratna Alam Lestari", snap
    assert snap["supplier_npwp"] == "01.234" and snap["supplier_pkp"] is True, snap
    assert snap["supplier_category_name"] == "Sparepart", snap

    # 2. Rekening supplier LAIN dikirim (mis. sisa pilihan sebelumnya) -> jatuh ke rekening utama.
    snap = SPL.snapshot_fields(SUP_A, "bank-b")
    assert snap["supplier_bank_id"] == "bank-a", snap
    assert snap["supplier_bank_account_no"] == "029-697-777-7", snap
    assert snap["supplier_bank_account_name"] == "PT. Adiratna Alam Lestari", snap

    # 3. Supplier tanpa rekening -> field rekening kosong (bukan rekening supplier lain), data lain tetap.
    snap = SPL.snapshot_fields({**SUP_B, "banks": []}, "bank-a")
    assert snap["supplier_bank_id"] is None and snap["supplier_bank_name"] is None, snap
    assert snap["supplier_bank_account_no"] is None and snap["supplier_bank_account_name"] is None, snap
    assert snap["supplier_npwp"] == "02.345", snap

    # 4. Kapan snapshot harus dihitung ulang saat edit.
    doc = {"supplier_id": "sup-a", "supplier_bank_id": "bank-a"}
    assert SPL.needs_refresh(doc, "sup-b", "bank-b") is True          # ganti supplier + rekening
    assert SPL.needs_refresh(doc, "sup-a", "bank-b2") is True         # ganti rekening saja
    assert SPL.needs_refresh(dict(doc, supplier_id="sup-x"), "sup-a", "bank-a") is True  # supplier kembali
    assert SPL.needs_refresh(doc, "sup-a", "bank-a") is False         # tidak ada perubahan -> snapshot historis tetap
    assert SPL.needs_refresh(doc, "", "bank-a") is False              # tanpa supplier -> tidak diubah

    # 5. Kasus nyata PO 229: supplier diganti Era -> Adiratna, bank id ikut berubah,
    #    snapshot harus jadi rekening Adiratna (bukan Milik Era).
    era = {"id": "sup-era", "legal_name": "PT. Era Teknik Multipolar",
           "banks": [{"id": "bank-era", "bank_name": "BANK MANDIRI",
                      "account_no": "146-000-537-821-6", "account_name": "PT. Era Teknik Multipolar"}]}
    po = {"supplier_id": "sup-era", "supplier_bank_id": "bank-era",
          "supplier_bank_account_no": "146-000-537-821-6"}
    assert SPL.needs_refresh(po, "sup-a", "bank-a") is True
    fixed = SPL.snapshot_fields(SUP_A, "bank-a")
    assert fixed["supplier_bank_account_no"] == "029-697-777-7", fixed
    assert SPL.snapshot_fields(era, "bank-era")["supplier_bank_account_no"] == "146-000-537-821-6"

    print("po_supplier_snapshot_test: 5 kelompok kasus OK")


if __name__ == "__main__":
    main()
