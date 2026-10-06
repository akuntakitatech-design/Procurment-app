// Harga Satuan PO wajib diisi (> 0). Mengembalikan nomor baris (1-based) yang harganya kosong/0/negatif.
export const PO_PRICE_REQUIRED_MSG = "Harga Satuan wajib diisi (lebih dari 0)";

export const isPriceMissing = (line) => !!line && !!line.item_id && !(Number(line.price) > 0);

export const missingPriceRows = (lines = []) => lines.reduce((out, l, i) => (isPriceMissing(l) ? [...out, i + 1] : out), []);
