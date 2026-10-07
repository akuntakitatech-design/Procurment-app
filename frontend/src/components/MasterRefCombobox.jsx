import { createContext, useCallback, useContext, useRef, useState } from "react";
import { Combobox } from "@/components/Combobox";
import { MasterQuickCreate } from "@/pages/MasterData";
import { useAuth } from "@/context/AuthContext";
import { canInlineCreate, inlineCreateLabel } from "@/lib/masterInline";

// Modal create master dirender sekali di level aplikasi agar tidak ikut ter-unmount
// saat baris/form transaksi re-render — state form transaksi tetap utuh.
const MasterCreateCtx = createContext(null);

export function MasterCreateProvider({ children }) {
  const [req, setReq] = useState(null);
  const open = useCallback((name, opts = {}) => setReq({ name, ...opts, key: `${name}-${Date.now()}` }), []);
  return <MasterCreateCtx.Provider value={open}>
    {children}
    {req && <MasterQuickCreate key={req.key} name={req.name} open prefill={req.prefill} onClose={() => setReq(null)} onCreated={(doc) => req.onCreated?.(doc)} />}
  </MasterCreateCtx.Provider>;
}

/**
 * Combobox master + aksi "+ Tambah ... Baru" (hanya bila user punya izin create master tsb).
 * Setelah Save: master tersimpan, daftar di-refresh, dan id baru dipilih HANYA pada field pemanggil
 * (onChange milik header / baris tertentu).
 */
export function MasterRefCombobox({ name, masters, options, value, onChange, onCreated, prefill, testid, disabled, ...rest }) {
  const { can } = useAuth();
  const ctxOpen = useContext(MasterCreateCtx);
  const [local, setLocal] = useState(null);
  const latest = useRef({});
  latest.current = { onChange, onCreated, masters };
  const allowed = !disabled && canInlineCreate(can, name);
  const handleCreated = (doc) => {
    const c = latest.current;
    c.masters?.upsert?.(name, doc);
    c.onCreated?.(doc);
    c.onChange?.(doc.id, doc);
    c.masters?.reload?.(name);
  };
  const openCreate = () => {
    const opts = { prefill: typeof prefill === "function" ? prefill() : prefill, onCreated: handleCreated };
    if (ctxOpen) ctxOpen(name, opts); else setLocal({ ...opts, key: Date.now() });
  };
  const footerAction = allowed ? { label: inlineCreateLabel(name), testid: `${testid || name}-create-new`, onClick: openCreate } : null;
  return <>
    <Combobox {...rest} options={options} value={value} onChange={onChange} testid={testid} disabled={disabled} footerAction={footerAction} />
    {local && <MasterQuickCreate key={local.key} name={name} open prefill={local.prefill} onClose={() => setLocal(null)} onCreated={local.onCreated} />}
  </>;
}

export const MasterProjectCombobox = (props) => <MasterRefCombobox name="projects" {...props} />;
export const MasterUnitCombobox = (props) => <MasterRefCombobox name="units" {...props} />;
