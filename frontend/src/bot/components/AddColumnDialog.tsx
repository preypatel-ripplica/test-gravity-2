import { useState } from "react";
import { useStore } from "../store";
import type { CustomColumnType } from "../types";
import { Icon } from "../lib/ui";
import Select from "./Select";

const TYPES: { value: CustomColumnType; label: string; hint: string }[] = [
  { value: "text", label: "Text", hint: "free text" },
  { value: "number", label: "Number", hint: "e.g. amount" },
  { value: "date", label: "Date", hint: "date picker" },
  { value: "checkbox", label: "Checkbox", hint: "tick / untick" },
  { value: "dropdown", label: "Dropdown", hint: "pick from options" },
];

/** "Add custom column" — the Google-Sheets column types, per client. */
export default function AddColumnDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { addCustomColumn, setToast } = useStore();
  const [label, setLabel] = useState("");
  const [type, setType] = useState<CustomColumnType>("text");
  const [options, setOptions] = useState("");
  if (!open) return null;
  const reset = () => { setLabel(""); setType("text"); setOptions(""); };
  const opts = options.split(",").map((o) => o.trim()).filter(Boolean);
  const ready = label.trim().length > 0 && (type !== "dropdown" || opts.length > 0);
  const create = () => {
    if (!ready) return;
    addCustomColumn({ label, type, options: type === "dropdown" ? opts : undefined });
    setToast(`Column “${label.trim()}” added`);
    reset(); onClose();
  };
  const inputCls = "w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-[13px] outline-none focus:border-accent/50";
  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 sm:items-center" onClick={onClose}>
      <div className="w-full max-w-sm overflow-hidden rounded-t-2xl border border-line bg-panel shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-[14px] font-semibold">Add a column</div>
          <button onClick={onClose} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
        </div>
        <div className="space-y-3 p-4">
          <div><label className="mb-1 block text-[11.5px] text-muted">Column name</label><input autoFocus value={label} onChange={(e) => setLabel(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()} placeholder="e.g. Follow-up done" className={inputCls} /></div>
          <div><label className="mb-1 block text-[11.5px] text-muted">Type</label><Select label="Type" value={type} onChange={(v) => setType(v as CustomColumnType)} options={TYPES} /></div>
          {type === "dropdown" && <div><label className="mb-1 block text-[11.5px] text-muted">Options (comma separated)</label><input value={options} onChange={(e) => setOptions(e.target.value)} placeholder="Yes, No, Maybe" className={inputCls} /></div>}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-line px-4 py-3">
          <button onClick={onClose} className="rounded-lg border border-line px-3 py-1.5 text-[13px] text-muted hover:text-ink">Cancel</button>
          <button onClick={create} disabled={!ready} className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg disabled:opacity-40">Add column</button>
        </div>
      </div>
    </div>
  );
}
