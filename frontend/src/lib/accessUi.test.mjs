// Node test (no deps): node frontend/src/lib/accessUi.test.mjs
// UI gating: Approval 2 (view/submit/approve/print; pengaju != approver) + Dokumen Supplier (attachment existing).
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, "..", p), "utf8");
const tmp = join(tmpdir(), `approval2.access.${process.pid}.mjs`);
writeFileSync(tmp, src("lib/approval2.js").replace(/^import .*$/gm, ""));
const A = await import(tmp);
unlinkSync(tmp);

let pass = 0, fail = 0;
const t = (name, cond) => { if (cond) { pass += 1; console.log("PASS " + name); } else { fail += 1; console.log("FAIL " + name); } };
const canOf = (...keys) => (k) => keys.includes(k);

// ---- Approval 2: pengaju (view+submit+print) != approver (view+approve)
const sub = A.a2Access(canOf("po_approval2.view", "po_approval2.submit", "po_approval2.print"), "Draft");
const subSent = A.a2Access(canOf("po_approval2.view", "po_approval2.submit", "po_approval2.print"), "Diajukan");
const appr = A.a2Access(canOf("po_approval2.view", "po_approval2.approve"), "Diajukan");
const none = A.a2Access(canOf(), "Diajukan");
t("Pengaju: dapat export/preview batch Draft", sub.canExport && sub.canPreview);
t("Pengaju: tidak dapat Approve Terpilih", !sub.approve && !subSent.approve);
t("Approver: dapat approve, tidak dapat export/preview tanpa print/submit", appr.approve && !appr.canExport && !appr.canPreview);
t("Approver: dapat unggah bukti", appr.canUploadEvidence);
t("Tanpa akses: semua aksi tertutup", !none.view && !none.canExport && !none.canPreview && !none.approve && !none.canUploadEvidence);

const panel = src("components/approval2/Approval2Panel.jsx");
const batch = src("pages/Approval2Batch.jsx");
const approval = src("pages/Approval.jsx");
t("Tombol Buat Pengajuan hanya untuk po_approval2.submit", /canSubmit = can\("po_approval2\.submit"\)/.test(panel) && /canSubmit && <Button[\s\S]{0,200}?approval2-create-open/.test(panel));
t("Tombol Approve Terpilih hanya jika acc.approve (pesan Bahasa Indonesia bila tidak)", /acc\.approve \? <Button[\s\S]*approval2-approve-selected[\s\S]*Anda tidak memiliki izin Approve Approval 2\./.test(batch));
t("Checkbox item mengikuti can_approve backend (exact assignee + divisi)", /disabled=\{!i\.can_approve\}/.test(batch));
t("Export/Preview JPEG mengikuti canExport/canPreview", /acc\.canExport && <Button/.test(batch) && /acc\.canPreview && <Button/.test(batch));
t("Tab/menu Approval 2 hanya dengan po_approval2.view", /can\("po_approval2\.view"\)/.test(approval));

// ---- Dokumen Supplier
const sd = src("components/master/SupplierDocuments.jsx");
const md = src("pages/MasterData.jsx");
const cats = ["NPWP", "KTP", "NIB", "SIUP", "Akta Perusahaan", "Rekening Bank", "Surat Penawaran", "Kontrak", "Dokumen Pendukung", "Lainnya"];
const m = sd.match(/SUPPLIER_DOC_CATEGORIES = \[([^\]]+)\]/);
const got = m ? m[1].split(",").map((s) => s.trim().replace(/^"|"$/g, "")) : [];
t("Kategori Dokumen Supplier lengkap & berurutan", JSON.stringify(got) === JSON.stringify(cats));
t("Upload memakai /attachments existing (entity=supplier, entity_id=supplier.id)", /api\.post\("\/attachments"/.test(sd) && /fd\.append\("entity", "supplier"\)/.test(sd) && /fd\.append\("entity_id", supplierId\)/.test(sd));
t("Daftar memuat lampiran entity supplier", /params: \{ entity: "supplier", entity_id: supplierId \}/.test(sd));
t("Lihat/Download via endpoint download terproteksi (bukan URL publik)", /\/attachments\/\$\{f\.id\}\/download/.test(sd) && !/storage_path/.test(sd));
t("Upload/hapus hanya suppliers.edit + upload_attachment", /canManage = can\("edit", "suppliers"\) && can\("upload_attachment"\)/.test(sd) && /canManage && <Button[\s\S]{0,250}?supplier-doc-delete/.test(sd));
t("Tanpa suppliers.view: pesan tanpa akses", /!canView\) return[\s\S]*Anda tidak memiliki akses melihat dokumen supplier\./.test(sd));
t("Supplier baru: diminta simpan dulu", /Simpan supplier terlebih dahulu/.test(sd));
t("Dipasang di form Master Supplier", /<SupplierDocuments supplierId=\{form\.id\} \/>/.test(md));
t("Empty, loading (Skeleton) & error + Coba lagi tersedia", /Belum ada dokumen supplier/.test(sd) && /<Skeleton/.test(sd) && /Coba lagi/.test(sd));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
