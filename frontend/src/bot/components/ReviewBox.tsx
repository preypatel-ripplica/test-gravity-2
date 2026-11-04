import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, isMobile } from "../lib/ui";

/**
 * A read-only sibling of RemarkEditor: the same anchored popover on desktop and
 * bottom sheet on a phone, but nothing to edit, so one close() replaces
 * commit/cancel and outside-click may close it on mobile too (no keyboard to
 * fight). Wider and taller than the remark box, since a call review is prose.
 */
export default function ReviewBox({ label, trigger, children, width = 420 }: {
  label: string;
  /** What the cell shows; clicking it opens the box. */
  trigger: (open: () => void, ref: React.RefObject<HTMLButtonElement | null>) => ReactNode;
  children: ReactNode;
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, up: false });
  const btnRef = useRef<HTMLButtonElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const W = width, H = 320;

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    const up = window.innerHeight - r.bottom < H + 8 && r.top > H + 8;
    const left = Math.min(Math.max(8, r.left), window.innerWidth - W - 8);
    setPos({ top: up ? r.top - 4 : r.bottom + 4, left, up });
  };
  useLayoutEffect(() => { if (open) place(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!btnRef.current?.contains(t) && !boxRef.current?.contains(t)) close();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
    const onScroll = (e: Event) => { if (boxRef.current?.contains(e.target as Node)) return; close(); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDoc);
    if (!isMobile()) {
      window.addEventListener("scroll", onScroll, true);
      window.addEventListener("resize", close);
    }
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const sheet = open && isMobile();

  return (
    <>
      {trigger(() => setOpen(true), btnRef)}
      {open && !sheet && createPortal(
        <div
          ref={boxRef}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          style={{ position: "fixed", left: pos.left, width: W, ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }) }}
          className="z-[80] max-h-[60vh] overflow-y-auto rounded-xl border border-line bg-panel p-3 shadow-2xl"
        >
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</span>
            <button onClick={() => setOpen(false)} className="grid h-6 w-6 place-items-center rounded text-muted hover:bg-panel2"><Icon name="x" size={13} /></button>
          </div>
          {children}
        </div>,
        document.body,
      )}
      {sheet && createPortal(
        <div className="fixed inset-0 z-[80] flex items-end bg-black/40" onMouseDown={(e) => e.stopPropagation()} onClick={() => setOpen(false)}>
          <div className="max-h-[85dvh] w-full overflow-y-auto rounded-t-2xl border border-line bg-panel pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between border-b border-line bg-panel px-4 py-3">
              <span className="text-[13px] font-semibold">{label}</span>
              <button onClick={() => setOpen(false)} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
            </div>
            <div className="px-4 pt-3">{children}</div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
