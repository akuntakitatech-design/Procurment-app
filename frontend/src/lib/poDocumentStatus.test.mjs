// Node test (no deps): node frontend/src/lib/poDocumentStatus.test.mjs
// Status Dokumen PO (derived backend) -> label & warna StatusBadge; list & detail PO memakai field yang sama.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const badge = readFileSync(join(here, "../components/StatusBadge.jsx"), "utf8");
const po = readFileSync(join(here, "../pages/Po.jsx"), "utf8");

let fail = 0;
const check = (name, cond, info = "") => { console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };

const block = (name) => badge.slice(badge.indexOf(`const ${name} = {`), badge.indexOf("};", badge.indexOf(`const ${name} = {`)));
const MAP = block("MAP"), LABEL = block("LABEL_ID");
const cls = (k) => (MAP.match(new RegExp(`(?:"${k}"|\\b${k}): "([^"]+)"`)) || [])[1] || "";
const label = (k) => (LABEL.match(new RegExp(`(?:"${k}"|\\b${k}): "([^"]+)"`)) || [])[1] || "";

const expected = [
  ["draft", "Draft", "slate"],
  ["waiting approval 1", "Menunggu Approval 1", "amber"],
  ["ready approval 2", "Siap Diajukan Approval 2", "sky"],
  ["waiting approval 2", "Menunggu Approval 2", "amber"],
  ["approved", "Disetujui", "emerald"],
  ["rejected", "Ditolak", "rose"],
  ["cancelled", "Dibatalkan", "slate"],
  ["closed", "Ditutup", "indigo"],
];
for (const [key, lbl, color] of expected) {
  check(`Label ${key} -> ${lbl}`, label(key) === lbl, label(key));
  check(`Warna ${key} -> ${color}`, cls(key).includes(`${color}-`), cls(key));
}
check("Dibatalkan dicoret (line-through)", cls("cancelled").includes("line-through"));
check("Status Penerimaan existing tetap terpetakan",
  label("over receipt") === "Penerimaan Berlebih" && cls("diterima sebagian") && cls("diterima penuh") && cls("belum diterima"));
check("Badge memakai lower-case key (internal key backend)", /String\(status \|\| ""\)\.toLowerCase\(\)/.test(badge));

check("List PO: kolom Status Dokumen = document_status", /\{key:"document_status",label:"Status Dokumen",status:true\}/.test(po));
check("List PO: kolom Status Penerimaan tetap receipt_status", /\{key:"receipt_status",label:"Status Penerimaan",status:true\}/.test(po));
check("Detail PO: badge Status Dokumen dari document_status (sama dengan list)", /data-testid="po-document-status"><StatusBadge status=\{doc\.document_status\}/.test(po));
check("Detail PO: badge PO.status mentah hanya fallback bila document_status kosong", /\{!doc\.document_status&&<StatusBadge status=\{doc\.status\}\/>\}/.test(po));
check("Detail PO: Status Penerimaan tetap terpisah", /data-testid="po-receipt-status"><StatusBadge status=\{doc\.receipt_status\}/.test(po));
check("Aksi workflow tetap memakai PO.status internal (Draft/Waiting Approval)", /draft=!doc\|\|doc\.status==="Draft",waiting=doc\?\.status==="Waiting Approval"/.test(po));

console.log(fail ? `\n${fail} FAILED` : "\nALL PASSED");
process.exit(fail ? 1 : 0);
