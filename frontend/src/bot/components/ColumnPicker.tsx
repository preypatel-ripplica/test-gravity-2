import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon, isMobile } from "../lib/ui";

export interface PickerColumn { key: string; label: string; custom?: boolean }

/**
 * Column chooser: tick columns on/off, add a custom column, remove custom ones.
 * A popover on desktop; on a phone the same list as a bottom sheet, opened from
 * a compact icon button.
 */
export default function ColumnPicker({ available, visible, onToggle, onClear, onAddCustom, onRemoveCustom, compact = false }: {
  available: PickerColumn[];
  visible: string[];
  onToggle: (key: string) => void;
  onClear: () => void;
  onAddCustom?: () => void;
  onRemoveCustom?: (key: string) => void;
  /** icon-only trigger (phone toolbar) */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const sheet = open && isMobile();
  useEffect(() => {
    if (sheet) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [sheet]);
  const selected = available.filter((c) => visible.includes(c.key));
  const filtered = available.filter((c) => !q || c.label.toLowerCase().includes(q.toLowerCase()));

  const body = (
    <>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1 border-b border-line p-2">
          {selected.map((c) => <button key={c.key} onClick={() => onToggle(c.key)} className="inline-flex items-center gap-1 rounded-md bg-accent/15 px-1.5 py-0.5 text-[11px] text-ink">{c.label}<Icon name="x" size={11} className="text-muted" /></button>)}
          <button onClick={onClear} className="ml-auto rounded-md px-1.5 py-0.5 text-[11px] text-muted hover:text-ink">Clear</button>
        </div>
      )}
      <div className="flex items-center gap-2 border-b border-line px-2.5">
        <Icon name="search" size={14} className="text-muted" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search columns…" className="w-full bg-transparent py-2 text-[13px] outline-none placeholder:text-muted" />
        <span className="shrink-0 text-[11px] text-muted">{selected.length} shown</span>
      </div>
      <div className={`overflow-y-auto p-1 ${sheet ? "max-h-[50vh]" : "max-h-64"}`}>
        {filtered.map((c) => {
          const on = visible.includes(c.key);
          return (
            <div key={c.key} className="flex items-center rounded-lg hover:bg-panel2">
              <button onClick={() => onToggle(c.key)} className={`flex min-w-0 flex-1 items-center gap-2.5 px-2.5 text-left text-[13px] ${sheet ? "py-2.5" : "py-1.5"}`}>
                <span className={`grid h-4 w-4 shrink-0 place-items-center rounded border ${on ? "border-accent bg-accent text-accent-fg" : "border-line"}`}>{on && <Icon name="check" size={11} />}</span>
                <span className="truncate">{c.label}</span>
                {c.custom && <span className="ml-1 rounded bg-panel2 px-1 text-[10px] text-muted">custom</span>}
              </button>
              {c.custom && onRemoveCustom && !sheet && (
                <button onClick={() => { if (window.confirm(`Remove the column “${c.label}”? Its values will be deleted.`)) onRemoveCustom(c.key); }} title="Remove column" className="mr-1 grid h-6 w-6 place-items-center rounded text-muted hover:text-red-500"><Icon name="x" size={12} /></button>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && <div className="px-3 py-4 text-center text-[12px] text-muted">No match</div>}
      </div>
      {onAddCustom && !sheet && (
        <button onClick={() => { setOpen(false); onAddCustom(); }} className="flex w-full items-center gap-2 border-t border-line px-3 py-2 text-left text-[12.5px] text-accent hover:bg-panel2"><Icon name="plus" size={14} /> Add custom column</button>
      )}
    </>
  );

  return (
    <div className="relative" ref={ref}>
      {compact
        ? <button onClick={() => setOpen((v) => !v)} title="Columns" className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:border-accent/40 hover:text-ink"><Icon name="table" size={15} /></button>
        : <button onClick={() => setOpen((v) => !v)} title="Add / remove columns" className="flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-[12.5px] text-muted hover:border-accent/40 hover:text-ink">Columns <Icon name="plus" size={15} /></button>}
      {open && !sheet && (
        <div className="absolute right-0 z-30 mt-1 w-72 overflow-hidden rounded-xl border border-line bg-panel shadow-2xl">{body}</div>
      )}
      {sheet && createPortal(
        <div className="fixed inset-0 z-[80] flex items-end bg-black/40" onClick={() => setOpen(false)}>
          <div className="w-full overflow-hidden rounded-t-2xl border border-line bg-panel pb-[env(safe-area-inset-bottom)] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="text-[13px] font-semibold">Columns on this phone</span>
              <button onClick={() => setOpen(false)} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
            </div>
            {body}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
