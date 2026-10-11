import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fmtApproval2, approval2Note, approval2SortValue, approval2SortFrom, APPROVAL2_SORT_OPTIONS } from "./poApproval2Date.js";
import { nextSort } from "./txnList.js";

test("format tanggal Approval 2: DD/MM/YYYY · Approval 2 (WIB) dari stempel WIB backend", () => {
  assert.equal(fmtApproval2("2026-10-11 06:15:00"), "11/10/2026 · Approval 2 (WIB)");
  assert.equal(fmtApproval2("2026-01-02 23:59:59"), "02/01/2026 · Approval 2 (WIB)");
});

test("tanpa riwayat / bukan tanggal -> tidak ada tanggal (tanpa perkiraan)", () => {
  for (const v of [null, undefined, "", "-", "bukan tanggal"]) assert.equal(fmtApproval2(v), null);
});

test("hanya status Disetujui (Approved) yang menampilkan tanggal; status lain tetap", () => {
  const stamp = "2026-10-11 06:15:00";
  assert.equal(approval2Note({ document_status: "Approved", approval2_at: stamp }), "11/10/2026 · Approval 2 (WIB)");
  for (const s of ["Draft", "Waiting Approval 1", "Ready Approval 2", "Waiting Approval 2", "Rejected", "Closed", "Cancelled"]) {
    assert.equal(approval2Note({ document_status: s, approval2_at: stamp }), null, s);
  }
  assert.equal(approval2Note({ document_status: "Approved", approval2_at: null }), null, "PO legacy tanpa riwayat");
});

test("dropdown sorting <-> sort daftar server (sort=approval2_at&dir=asc|desc)", () => {
  assert.deepEqual(APPROVAL2_SORT_OPTIONS.map((o) => o.value), ["", "asc", "desc"]);
  assert.deepEqual(approval2SortFrom("asc"), { key: "approval2_at", dir: "asc", ui: "document_status" });
  assert.deepEqual(approval2SortFrom("desc"), { key: "approval2_at", dir: "desc", ui: "document_status" });
  assert.equal(approval2SortFrom(""), null);
  assert.equal(approval2SortValue({ key: "approval2_at", dir: "desc" }), "desc");
  assert.equal(approval2SortValue({ key: "date", dir: "asc" }), "");
  assert.equal(approval2SortValue(null), "");
});

test("klik judul Status Dokumen: klik 1 terlama -> terbaru, klik 2 terbaru -> terlama (serverSort approval2_at)", () => {
  const one = nextSort(null, "document_status");
  assert.deepEqual(one, { key: "document_status", dir: "asc" });
  assert.deepEqual(nextSort(one, "document_status"), { key: "document_status", dir: "desc" });
  const po = readFileSync(new URL("../pages/Po.jsx", import.meta.url), "utf8");
  assert.match(po, /key:"document_status",label:"Status Dokumen",status:true,serverSort:APPROVAL2_SORT_FIELD/);
  assert.match(po, /data-testid="po-approval2-sort"/);
});
