import assert from "node:assert/strict";
import { BG_EXPORT_ROWS, exportMode, jobLabel, pollDelay, JOB_FAILED } from "./exportJob.js";

let passed = 0;
const t = (name, fn) => { fn(); passed += 1; console.log(`ok - ${name}`); };

t("export kecil Excel tetap langsung", () => assert.equal(exportMode(BG_EXPORT_ROWS, "xlsx"), "direct"));
t("export Excel > batas -> background", () => assert.equal(exportMode(BG_EXPORT_ROWS + 1, "xlsx"), "background"));
t("PDF selalu langsung", () => assert.equal(exportMode(99999, "pdf"), "direct"));
t("total tidak diketahui -> langsung", () => { assert.equal(exportMode(undefined, "xlsx"), "direct"); assert.equal(exportMode("x", "xlsx"), "direct"); });
t("label selesai memuat jumlah baris", () => assert.match(jobLabel({ status: "done", rows: 20000 }), /20\.000 baris/));
t("label gagal memakai pesan server", () => assert.equal(jobLabel({ status: "failed", error: "Data 100.001 baris melebihi batas" }), "Data 100.001 baris melebihi batas"));
t("status gagal/kedaluwarsa dikenali", () => { assert.ok(JOB_FAILED.has("failed")); assert.ok(JOB_FAILED.has("expired")); assert.ok(!JOB_FAILED.has("done")); });
t("polling melambat", () => { assert.equal(pollDelay(0), 1500); assert.equal(pollDelay(10), 3000); assert.equal(pollDelay(50), 5000); });

console.log(`\n${passed}/${passed} passed`);
