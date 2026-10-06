// Node test (no deps): node frontend/src/lib/poPrice.test.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tmp = join(tmpdir(), `poPrice.${process.pid}.mjs`);
writeFileSync(tmp, readFileSync(join(here, "poPrice.js"), "utf8"));
const P = await import(tmp);
let fail = 0;
const check = (n, c, info = "") => { console.log(`${c ? "PASS" : "FAIL"} ${n}${!c && info ? " — " + JSON.stringify(info) : ""}`); if (!c) fail++; };

check("Harga 0 = kosong", P.isPriceMissing({ item_id: "a", price: 0 }));
check("Harga '' = kosong", P.isPriceMissing({ item_id: "a", price: "" }));
check("Harga null/undefined = kosong", P.isPriceMissing({ item_id: "a", price: null }) && P.isPriceMissing({ item_id: "a" }));
check("Harga negatif ditolak", P.isPriceMissing({ item_id: "a", price: -1 }));
check("Harga > 0 valid", !P.isPriceMissing({ item_id: "a", price: 1500 }) && !P.isPriceMissing({ item_id: "a", price: "0.5" }));
check("Baris tanpa barang diabaikan", !P.isPriceMissing({ item_id: "", price: 0 }));
const rows = P.missingPriceRows([{ item_id: "a", price: 0 }, { item_id: "b", price: 10 }, { item_id: "c", price: "" }]);
check("Nomor baris yang belum diisi (1-based)", rows.join() === "1,3", rows);
check("Semua terisi -> kosong", P.missingPriceRows([{ item_id: "a", price: 1 }]).length === 0);
console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED");
process.exit(fail ? 1 : 0);
