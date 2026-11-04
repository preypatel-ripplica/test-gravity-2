import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon, isMobile } from "../lib/ui";

/**
 * Collapsed text cell that shows the LAST line of the value; clicking opens an
 * in-place popover editor (bottom sheet on phones). Saves on ⌘/Ctrl+Enter,
 * the Save button, or clicking away; Escape cancels.
 */
export default function RemarkEditor({ value, onSave, placeholder = "Add a remark…", label = "Remark", rows = 5, single = false, block = false }: {
  value: string;
  onSave: (text: string) => void;
  placeholder?: string;
  label?: string;
  rows?: number;
  /** single-line value (custom text columns): show the whole value, not the last line */
  single?: boolean;
  /** a full-width, multi-line box (sheet / drawer): tapping anywhere in it opens the editor */
  block?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [pos, setPos] = useState<{ top: number; left: number; up: boolean } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const draftRef = useRef(draft); draftRef.current = draft;
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  const W = 300, H = 40 + rows * 24 + 44;

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    const up = window.innerHeight - r.bottom < H + 8 && r.top > H + 8;
    const left = Math.min(Math.max(8, r.left), window.innerWidth - W - 8);
    setPos({ top: up ? r.top - 4 : r.bottom + 4, left, up });
  };
  useLayoutEffect(() => { if (open) { setDraft(value); place(); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [open]);

  const commit = () => { const t = draftRef.current.trim(); if (t !== value) onSave(t); setOpen(false); };
  const cancel = () => { setDraft(value); setOpen(false); };

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { const t = e.target as Node; if (!btnRef.current?.contains(t) && !boxRef.current?.contains(t)) commit(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); cancel(); } };
    const onScroll = (e: Event) => { if (boxRef.current?.contains(e.target as Node)) return; commit(); };
    document.addEventListener("keydown", onKey);
    if (isMobile()) {
      // The virtual keyboard resizes the viewport and scrolls the page; neither
      // may close the sheet. Instead keep the box in view as the keyboard opens.
      const keep = () => boxRef.current?.scrollIntoView({ block: "end" });
      window.visualViewport?.addEventListener("resize", keep);
      return () => { document.removeEventListener("keydown", onKey); window.visualViewport?.removeEventListener("resize", keep); };
    }
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", commit);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); window.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", commit); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, value]);

  const lines = value.split("\n").map((s) => s.trim()).filter(Boolean);
  const shown = single ? value.trim() : (lines[lines.length - 1] ?? "");

  const editor = (big: boolean) => (
    <>
      <textarea
        autoFocus
        rows={big ? Math.max(rows, 6) : rows}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onFocus={(e) => { if (big) { const el = e.currentTarget; window.setTimeout(() => el.scrollIntoView({ block: "end" }), 350); } }}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); commit(); } }}
        placeholder={placeholder}
        className="w-full resize-none rounded-lg border border-line bg-panel2 px-2.5 py-2 text-[13px] outline-none focus:border-accent/50"
      />
      <div className="mt-1.5 flex items-center gap-1.5 text-[11.5px]">
        <span className="mr-auto text-muted">{big ? "" : "⌘/Ctrl + Enter to save"}</span>
        <button type="button" onClick={cancel} className="rounded-md border border-line px-2.5 py-1 text-muted hover:text-ink">Cancel</button>
        <button type="button" onClick={commit} className="rounded-md bg-accent px-2.5 py-1 font-medium text-accent-fg">Save</button>
      </div>
    </>
  );

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        title={value || placeholder}
        onMouseDown={stop}
        onClick={(e) => { stop(e); setOpen(true); }}
        className={block
          ? `block min-h-[4.5rem] w-full whitespace-pre-wrap rounded-lg border border-line bg-panel2/40 px-3 py-2 text-left text-[13px] hover:border-accent/50 ${value.trim() ? "" : "text-muted"}`
          : `block max-w-full truncate rounded border border-transparent px-1 py-0.5 text-left text-[12px] hover:border-line ${shown ? "" : "text-muted"}`}
      >
        {block ? (value.trim() || placeholder) : (shown || "—")}
      </button>
      {open && pos && createPortal(
        isMobile() ? (
          <div className="fixed inset-0 z-[80]" onMouseDown={stop} onClick={(e) => { stop(e); commit(); }}>
            <div className="absolute inset-0 bg-black/40" />
            <div ref={boxRef} onClick={stop} className="fixed inset-x-0 bottom-0 rounded-t-2xl border border-line bg-panel p-3 pb-[env(safe-area-inset-bottom)] shadow-2xl">
              <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-semibold">{label}</span><button type="button" onClick={cancel} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button></div>
              {editor(true)}
            </div>
          </div>
        ) : (
          <div ref={boxRef} onMouseDown={stop} onClick={stop} style={{ position: "fixed", left: pos.left, width: W, ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }) }} className="z-[80] rounded-xl border border-line bg-panel p-2 shadow-2xl">
            <div className="mb-1 px-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-muted">{label}</div>
            {editor(false)}
          </div>
        ),
        document.body,
      )}
    </>
  );
}
