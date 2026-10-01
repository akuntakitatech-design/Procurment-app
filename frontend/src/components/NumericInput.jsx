import { useLayoutEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";

// Shared Indonesian-locale numeric input for ALL procurement transactions.
// Display uses "." as thousands separator and "," as decimal separator, formatted live
// while typing. onChange always emits a CLEAN numeric string (JS style: dot decimal, no
// grouping) or "" when empty — storage/calculations stay numeric, never formatted strings.
// Modes: "quantity" | "money" (grouped, decimals allowed) · "percent" (no grouping) ·
// "integer" (no decimals).

const onlyDigits = (s) => (String(s).match(/\d/g) || []).join("");
const stripLead = (s) => s.replace(/^0+(?=\d)/, "");
const group = (d) => d.replace(/\B(?=(\d{3})+(?!\d))/g, ".");

// Typing rule (deterministic): our own display only ever uses "." for thousands and ","
// for decimal, so strip all dots and treat the first comma as the decimal separator.
function partsFromTyped(s, allowDecimal) {
  s = String(s ?? "");
  const ci = allowDecimal ? s.indexOf(",") : -1;
  if (ci >= 0) return { intPart: stripLead(onlyDigits(s.slice(0, ci))), decPart: onlyDigits(s.slice(ci + 1)), hasDec: true };
  return { intPart: stripLead(onlyDigits(s)), decPart: "", hasDec: false };
}

// External raw value (number or clean "1250.75") -> parts.
function partsFromRaw(v, allowDecimal) {
  if (v === "" || v == null) return { intPart: "", decPart: "", hasDec: false };
  const [i, d] = String(v).split(".");
  const decPart = d != null ? onlyDigits(d) : "";
  return { intPart: stripLead(onlyDigits(i)), decPart, hasDec: allowDecimal && d != null && decPart !== "" };
}

// Paste/foreign formats -> parts, using a safe id-ID-consistent heuristic.
function partsFromPaste(s, allowDecimal) {
  s = String(s).replace(/\s/g, "").replace(/[^\d.,]/g, "");
  const dot = (s.match(/\./g) || []).length, com = (s.match(/,/g) || []).length;
  let decSep = null;
  if (dot && com) decSep = s.lastIndexOf(".") > s.lastIndexOf(",") ? "." : ",";
  else if (com === 1) decSep = ",";
  else if (dot === 1) decSep = (s.split(".")[1] || "").length === 3 ? null : ".";
  if (!allowDecimal) decSep = null;
  if (decSep) {
    const idx = s.lastIndexOf(decSep);
    return { intPart: stripLead(onlyDigits(s.slice(0, idx))), decPart: onlyDigits(s.slice(idx + 1)), hasDec: true };
  }
  return { intPart: stripLead(onlyDigits(s)), decPart: "", hasDec: false };
}

function toDisplay({ intPart, decPart, hasDec }, grouping) {
  let ip = intPart === "" ? (hasDec ? "0" : "") : intPart;
  let out = ip === "" ? "" : (grouping ? group(ip) : ip);
  if (hasDec) out = (out === "" ? "0" : out) + "," + decPart;
  return out;
}

function toRaw({ intPart, decPart, hasDec }) {
  if (intPart === "" && !hasDec) return "";
  const ip = intPart === "" ? "0" : intPart;
  return hasDec && decPart !== "" ? `${ip}.${decPart}` : ip;
}

export function NumericInput({ value, onChange, mode = "quantity", className, disabled, placeholder, ...rest }) {
  const allowDecimal = mode !== "integer";
  const grouping = mode === "quantity" || mode === "money";
  const ref = useRef(null);
  const caretRef = useRef(null);
  const [display, setDisplay] = useState(() => toDisplay(partsFromRaw(value, allowDecimal), grouping));
  const lastRaw = useRef(toRaw(partsFromRaw(value, allowDecimal)));

  // Reflect external value changes (auto-fill, load, programmatic) only when they differ
  // from the value we last emitted — avoids clobbering the user's in-progress typing.
  useLayoutEffect(() => {
    const incoming = value === "" || value == null ? "" : String(value);
    if (incoming !== lastRaw.current) {
      const parts = partsFromRaw(value, allowDecimal);
      setDisplay(toDisplay(parts, grouping));
      lastRaw.current = toRaw(parts);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Restore caret after a reformat (anchored by digits-to-the-right -> separator-safe).
  useLayoutEffect(() => {
    if (caretRef.current != null && ref.current) {
      const pos = caretRef.current; caretRef.current = null;
      try { ref.current.setSelectionRange(pos, pos); } catch { /* noop */ }
    }
  });

  const emit = (parts, caret) => {
    const formatted = toDisplay(parts, grouping);
    caretRef.current = caret != null ? caret : formatted.length;
    const raw = toRaw(parts);
    lastRaw.current = raw;
    setDisplay(formatted);
    if (onChange) onChange(raw);
  };

  const handle = (e) => {
    const typed = e.target.value;
    const selEnd = e.target.selectionStart ?? typed.length;
    const digitsRight = (typed.slice(selEnd).match(/\d/g) || []).length;
    const parts = partsFromTyped(typed, allowDecimal);
    const formatted = toDisplay(parts, grouping);
    let c = formatted.length, seen = 0;
    while (c > 0 && seen < digitsRight) { c--; if (/\d/.test(formatted[c])) seen++; }
    emit(parts, c);
  };

  const handlePaste = (e) => {
    const txt = (e.clipboardData || window.clipboardData)?.getData("text");
    if (txt == null) return;
    e.preventDefault();
    emit(partsFromPaste(txt, allowDecimal));
  };

  return <Input {...rest} ref={ref} type="text" inputMode="decimal" className={className} disabled={disabled} placeholder={placeholder} value={display} onChange={handle} onPaste={handlePaste} />;
}
