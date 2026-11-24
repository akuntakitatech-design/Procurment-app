// Mirrors backend access_control_layer: legacy action + module -> granular key `module.action`.
const PATH_MODULE = [
  ["/mro", "mro"], ["/ro", "ro"], ["/po", "po"], ["/do", "do"], ["/mi", "mi"], ["/transfer", "transfer"],
  ["/loan", "loan"], ["/adjustment", "adjustment"], ["/opname", "opname"], ["/spk", "spk"],
  ["/vendor-contracts", "vendor_contracts"], ["/users", "users"], ["/invoice", "invoice"], ["/dp-supplier", "supplier_dp"],
  // Halaman yang sebelumnya tidak dipetakan (kartu menu selalu tampil walau tanpa izin).
  ["/transmittal", "transmittal"], ["/inventory", "inventory"], ["/report-center", "report_center"],
  ["/traceability", "report_center"], ["/activity-log", "activity_log"], ["/print-layouts", "print_layout"],
  ["/excel-import", "excel_import"], ["/settings", "settings"],
];
const LEGACY_ACTION = { view: "view", create: "create", edit: "edit", delete: "delete", submit: "post", cancel: "cancel", approve: "approve", reject: "reject", print: "print" };
const TRANSLATE = {
  direct_mi: ["mi.direct"], post_stock_opname: ["opname.post"], stock_adjustment: ["adjustment.create"],
  "spk:view": ["spk.view"], "spk:manage": ["spk.create", "spk.edit"],
  "vendor_contract:view": ["vendor_contracts.view"], "vendor_contract:manage": ["vendor_contracts.create", "vendor_contracts.edit"],
};
const STOCK_POSTING = ["do", "mi", "transfer", "loan", "adjustment"];
// Modul yang tindakan utamanya bukan CRUD (hanya izin khusus), agar kartu menu ikut izin yang benar.
const MODULE_VIEW_ALIAS = { print_layout: "print_layout.manage", settings: "settings.edit" };
export const MASTER_MODULE = { iw: "stock_minmax", item_warehouse: "stock_minmax" };

export function moduleFromPath(pathname) {
  const hit = PATH_MODULE.find(([p]) => pathname === p || pathname.startsWith(`${p}/`));
  return hit ? hit[1] : null;
}

export function resolveCan(user, perm, module) {
  if (!user) return false;
  if (user.role === "admin") return true;
  const eff = new Set(user.effective_permissions || user.permissions || []);
  if (eff.has(perm)) return true;
  if (perm === "view_all_division") return user.division_scope?.mode === "all";
  if (TRANSLATE[perm]) return TRANSLATE[perm].some((k) => eff.has(k));
  const act = LEGACY_ACTION[perm];
  if (!act) return false;
  const mod = module || moduleFromPath(window.location.pathname);
  if (!mod) return [...eff].some((k) => k.endsWith(`.${act}`));
  if (act === "view" && MODULE_VIEW_ALIAS[mod]) return eff.has(MODULE_VIEW_ALIAS[mod]);
  if (act === "create" && STOCK_POSTING.includes(mod)) return eff.has(`${mod}.create`) && eff.has(`${mod}.post`);
  if (act === "delete" && STOCK_POSTING.includes(mod)) return eff.has(`${mod}.delete`) && eff.has(`${mod}.cancel`);
  return eff.has(`${mod}.${act}`);
}
