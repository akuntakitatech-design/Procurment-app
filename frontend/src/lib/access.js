// Mirrors backend access_control_layer: legacy action + module -> granular key `module.action`.
const PATH_MODULE = [
  ["/mro", "mro"], ["/ro", "ro"], ["/po", "po"], ["/do", "do"], ["/mi", "mi"], ["/transfer", "transfer"],
  ["/loan", "loan"], ["/adjustment", "adjustment"], ["/opname", "opname"], ["/spk", "spk"],
  ["/vendor-contracts", "vendor_contracts"], ["/users", "users"], ["/invoice", "invoice"],
];
const LEGACY_ACTION = { view: "view", create: "create", edit: "edit", delete: "delete", submit: "post", cancel: "cancel", approve: "approve", reject: "reject", print: "print" };
const TRANSLATE = {
  direct_mi: ["mi.direct"], post_stock_opname: ["opname.post"], stock_adjustment: ["adjustment.create"],
  "spk:view": ["spk.view"], "spk:manage": ["spk.create", "spk.edit"],
  "vendor_contract:view": ["vendor_contracts.view"], "vendor_contract:manage": ["vendor_contracts.create", "vendor_contracts.edit"],
};
const STOCK_POSTING = ["do", "mi", "transfer", "loan", "adjustment"];
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
  if (act === "create" && STOCK_POSTING.includes(mod)) return eff.has(`${mod}.create`) && eff.has(`${mod}.post`);
  if (act === "delete" && STOCK_POSTING.includes(mod)) return eff.has(`${mod}.delete`) && eff.has(`${mod}.cancel`);
  return eff.has(`${mod}.${act}`);
}
