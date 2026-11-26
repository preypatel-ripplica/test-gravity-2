import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useStore, CORE_COLUMNS } from "../store";
import { DISPOSITIONS, type Lead, type CustomColumn } from "../types";
import { Badge, Icon, clockOnly, dayLabel, enumColor, portalRoot } from "../lib/ui";
import Select from "./Select";
import RemarkEditor from "./RemarkEditor";
import CallHistoryModal from "./CallHistoryModal";

/**
 * The lead-level controls shared by the Leads table, the inbox Properties
 * drawer and the phone lead sheet, so a lead looks and edits the same everywhere.
 */

export const stop = (e: React.SyntheticEvent) => e.stopPropagation();

export const DISPOSITION_OPTIONS = [{ value: "", label: "—" }, ...DISPOSITIONS.map((s) => ({ value: s, label: s, color: enumColor(s) }))];

function statusWhen(iso: string | null): string {
  if (!iso) return "";
  return `${dayLabel(iso)} ${clockOnly(iso)}`;
}

/** From → to for each status change on this lead, newest first. */
function DispositionHistory({ lead }: { lead: Lead }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const items = [...(lead.conversation.disposition_history ?? [])].reverse();

  useEffect(() => {
    if (!open) return;
    const r = btnRef.current?.getBoundingClientRect();
    if (r) {
      const width = 280;
      setPos({ top: r.bottom + 4, left: Math.min(Math.max(8, r.right - width), window.innerWidth - width - 8) });
    }
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!btnRef.current?.contains(t) && !panelRef.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <>
      <button ref={btnRef} type="button" onClick={(e) => { stop(e); setOpen((v) => !v); }} onMouseDown={stop} title="Status history" className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted hover:bg-panel2 hover:text-ink">
        <Icon name="history" size={13} />
      </button>
      {open && pos && createPortal(
        <div ref={panelRef} style={{ top: pos.top, left: pos.left }} className="fixed z-[80] w-[280px] rounded-xl border border-line bg-panel p-2.5 shadow-2xl" onClick={stop} onMouseDown={stop}>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Status history</div>
          {items.length === 0 && <div className="py-2 text-[12px] text-muted">No changes yet</div>}
          <div className="max-h-64 space-y-1.5 overflow-y-auto">
            {items.map((item, i) => (
              <div key={`${item.at ?? ""}-${i}`} className="rounded-lg bg-panel2 px-2 py-1.5">
                <div className="text-[10.5px] tabular-nums text-muted">{statusWhen(item.at)}{item.source === "sync" ? " · sheet" : ""}</div>
                <div className="mt-0.5 text-[12px] font-medium leading-snug">{item.from || "None"} → {item.to || "None"}</div>
              </div>
            ))}
          </div>
        </div>,
        portalRoot(),
      )}
    </>
  );
}

export function DispositionSelect({ lead, size, placeholder = "Disposition" }: { lead: Lead; size?: "sm"; placeholder?: string }) {
  const { setCrm } = useStore();
  const onChange = (v: string) => setCrm(lead.id, { disposition: v as Lead["crm"]["disposition"] });
  // The "none" entry carries the placeholder text, so an unset lead reads
  // "Disposition" rather than a bare dash (the Select shows the matched option's label).
  const options = [{ value: "", label: placeholder }, ...DISPOSITION_OPTIONS.slice(1)];
  const select = (
    <div className={size ? "min-w-0 flex-1" : "min-w-0 max-w-[200px] flex-1"}>
      <Select size={size} variant={size ? "input" : "inline"} label="Disposition" value={lead.crm.disposition} onChange={onChange} options={options} placeholder={placeholder} />
    </div>
  );
  return (
    <div onClick={stop} className="flex items-center gap-1">
      {select}
      <DispositionHistory lead={lead} />
    </div>
  );
}

/** Every FasterQ call on this lead, inbound and outbound.
 *  Click to see each call with its recording. */
export function CallTriedCell({ lead }: { lead: Lead }) {
  const [open, setOpen] = useState(false);
  const n = lead.crm.call_tried;
  return (
    <>
      <button onClick={(e) => { stop(e); setOpen(true); }} onMouseDown={stop} title="Call history" className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[12.5px] tabular-nums transition-colors ${n ? "bg-accent/15 text-accent hover:bg-accent/25" : "bg-panel2 text-muted hover:text-ink"}`}>
        <Icon name="phone" size={11} />{n}
      </button>
      {open && <CallHistoryModal lead={lead} onClose={() => setOpen(false)} />}
    </>
  );
}

/** A user-defined column cell, by type. */
export function CustomCell({ lead, col }: { lead: Lead; col: CustomColumn }) {
  const { setCustomValue } = useStore();
  const v = lead.crm.custom[col.key];
  const inputCls = "rounded border border-transparent bg-transparent px-1 py-0.5 text-[12px] outline-none hover:border-line focus:border-accent/60";
  if (col.type === "checkbox") return <div onClick={stop}><input type="checkbox" checked={v === true} onChange={(e) => setCustomValue(lead.id, col.key, e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" /></div>;
  if (col.type === "number") return <div onClick={stop}><input type="number" value={v === undefined || v === "" ? "" : String(v)} onChange={(e) => setCustomValue(lead.id, col.key, e.target.value === "" ? "" : Number(e.target.value))} placeholder="—" className={`${inputCls} w-20 tabular-nums`} /></div>;
  if (col.type === "date") return <div onClick={stop}><input type="date" value={typeof v === "string" ? v : ""} onChange={(e) => setCustomValue(lead.id, col.key, e.target.value)} className={`${inputCls} ${v ? "" : "text-muted"}`} /></div>;
  if (col.type === "dropdown") return <div onClick={stop} className="max-w-[200px]"><Select variant="inline" label={col.label} value={typeof v === "string" ? v : ""} onChange={(x) => setCustomValue(lead.id, col.key, x)} options={[{ value: "", label: "—" }, ...(col.options ?? []).map((o) => ({ value: o, label: o }))]} placeholder="—" /></div>;
  return <RemarkEditor single label={col.label} rows={3} value={typeof v === "string" ? v : ""} onSave={(t) => setCustomValue(lead.id, col.key, t)} placeholder={`Add ${col.label.toLowerCase()}…`} />;
}

/** A flow-collected value rendered like the grid: enum badge, file/link, or text. */
export function FieldValue({ lead, fieldKey }: { lead: Lead; fieldKey: string }) {
  const { flow } = useStore();
  const f = flow.fields.find((x) => x.key === fieldKey);
  const v = lead.fields[fieldKey] || "";
  if (!v) return <span className="text-muted/50">—</span>;
  if (f?.type === "enum") return <Badge color={enumColor(v)}>{v}</Badge>;
  if (f?.type === "media" || /^https?:\/\//.test(v)) return <a href={v} target="_blank" rel="noopener" onClick={stop} className="block truncate text-sky-500 underline">{f?.type === "media" ? "📎 Open file" : v}</a>;
  return <span className="break-words text-muted">{v}</span>;
}

/** Dial this number: opens the phone's dialer with it filled in (phones only). */
export function CallLink({ phone, className, title = "Call", children }: { phone: string; className?: string; title?: string; children: React.ReactNode }) {
  return <a href={`tel:+${phone}`} onClick={stop} title={title} className={className}>{children}</a>;
}

export type LeadColumn = { key: string; label: string; custom?: CustomColumn };

/** The lead columns the clinic has switched on under Leads → "Columns +"
 *  (flow fields and custom columns; the chat-level ones are left out). */
export function useLeadColumns(): LeadColumn[] {
  const { flow, customColumns, visibleColumns } = useStore();
  return useMemo(() => {
    const core = new Set(CORE_COLUMNS.map((c) => c.key));
    const fields = new Map(flow.fields.map((f) => [f.key, f.label]));
    const custom = new Map(customColumns.map((c) => [c.key, c]));
    return visibleColumns
      .filter((k) => !core.has(k) && (fields.has(k) || custom.has(k)))
      .map((k) => ({ key: k, label: custom.get(k)?.label ?? fields.get(k) ?? k, custom: custom.get(k) }));
  }, [flow, customColumns, visibleColumns]);
}
