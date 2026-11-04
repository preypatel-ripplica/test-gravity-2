import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon, isMobile } from "../lib/ui";

export interface SelectOption {
  value: string;
  label: string;
  /** Optional swatch (stages, dispositions, categories). */
  color?: string;
  /** Optional right-aligned secondary text. */
  hint?: string;
}

/**
 * Themed dropdown replacing native <select>. The menu is rendered in a portal
 * (never clipped by tables/drawers), positioned from the trigger and flipped
 * upward when there's no room below; on phones it opens as a bottom sheet so
 * it always stays inside the viewport (native popups don't).
 */
export default function Select({
  value, onChange, options, placeholder = "—", variant = "input", size = "md", className = "", disabled, label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  variant?: "input" | "inline";
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
  /** Bottom-sheet title on mobile. */
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ top: number; left: number; width: number; up: boolean } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    const menuH = Math.min(256, options.length * 36 + 8);
    const up = window.innerHeight - r.bottom < menuH + 8 && r.top > menuH + 8;
    const width = Math.max(r.width, 176);
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    setPos({ top: up ? r.top - 4 : r.bottom + 4, left, width, up });
  };

  useLayoutEffect(() => { if (open) { place(); setActive(Math.max(0, options.findIndex((o) => o.value === value))); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { const t = e.target as Node; if (!btnRef.current?.contains(t) && !menuRef.current?.contains(t)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, options.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
      if (e.key === "Enter") { e.preventDefault(); const o = options[active]; if (o) { onChange(o.value); setOpen(false); } }
    };
    const onScroll = (e: Event) => { if (menuRef.current?.contains(e.target as Node)) return; setOpen(false); };
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    // On a phone the list is a sheet over a scrim: a viewport resize (keyboard,
    // rotation) or a scroll must not dismiss it.
    const mobile = isMobile();
    if (!mobile) { window.addEventListener("scroll", onScroll, true); window.addEventListener("resize", onResize); }
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
      if (!mobile) { window.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", onResize); }
    };
  }, [open, active, options, onChange]);

  const pick = (v: string) => { onChange(v); setOpen(false); };

  const triggerCls = variant === "inline"
    ? "flex max-w-full items-center gap-1.5 rounded border border-transparent bg-transparent py-0.5 pl-1 pr-1 text-left text-[12px] hover:border-line focus:border-accent/60 disabled:opacity-50"
    : `flex w-full items-center gap-2 rounded-lg border border-line bg-panel2 text-left outline-none focus:border-accent/50 disabled:opacity-50 ${size === "sm" ? "px-2 py-1.5 text-[12px]" : "px-3 py-2 text-[13px]"}`;

  const rows = (big: boolean) => options.map((o, i) => (
    <button
      key={o.value || "__empty"}
      type="button"
      onMouseDown={stop}
      onClick={(e) => { stop(e); pick(o.value); }}
      onMouseEnter={() => setActive(i)}
      className={`flex w-full items-center gap-2 text-left ${big ? "px-4 py-3 text-[14px]" : "px-3 py-2 text-[13px]"} ${i === active ? "bg-panel2" : ""} ${o.value === value ? "text-ink" : "text-muted"}`}
    >
      {o.color && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: o.color }} />}
      <span className="min-w-0 flex-1 truncate" style={o.color && o.value === value ? { color: o.color } : undefined}>{o.label}</span>
      {o.hint && <span className="shrink-0 text-[11px] text-muted">{o.hint}</span>}
      {o.value === value && <Icon name="check" size={13} className="shrink-0 text-accent" />}
    </button>
  ));

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        onMouseDown={stop}
        onClick={(e) => { stop(e); setOpen((v) => !v); }}
        className={`${triggerCls} ${className}`}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {selected?.color && <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: selected.color }} />}
        <span className={`min-w-0 flex-1 truncate ${selected ? "" : "text-muted"}`} style={variant === "inline" && selected?.color ? { color: selected.color } : undefined}>
          {selected ? selected.label : placeholder}
        </span>
        <Icon name="chevronDown" size={variant === "inline" ? 13 : 14} className="shrink-0 text-muted" />
      </button>

      {open && pos && createPortal(
        isMobile() ? (
          <div className="fixed inset-0 z-[80]" onMouseDown={stop} onClick={(e) => { stop(e); setOpen(false); }}>
            <div className="absolute inset-0 bg-black/40" />
            <div ref={menuRef} onClick={stop} className="absolute inset-x-0 bottom-0 max-h-[60vh] overflow-y-auto rounded-t-2xl border border-line bg-panel pb-[env(safe-area-inset-bottom)] shadow-2xl">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <span className="text-[13px] font-semibold">{label ?? "Choose"}</span>
                <button type="button" onClick={(e) => { stop(e); setOpen(false); }} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
              </div>
              <div className="py-1">{rows(true)}</div>
            </div>
          </div>
        ) : (
          <div
            ref={menuRef}
            onMouseDown={stop}
            onClick={stop}
            role="listbox"
            style={{ position: "fixed", left: pos.left, width: pos.width, ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }) }}
            className="z-[80] max-h-64 overflow-y-auto rounded-xl border border-line bg-panel py-1 shadow-2xl"
          >
            {rows(false)}
          </div>
        ),
        document.body,
      )}
    </>
  );
}
