import { useStore } from "../store";
import { Icon } from "../lib/ui";

/** Floating bar while selecting leads/contacts → opens the global send-template modal. */
export default function SelectionBar() {
  const { selectMode, selectedIds, clearSelection, openTemplateSend } = useStore();
  if (!selectMode || selectedIds.length === 0) return null;
  return (
    <div className="fixed inset-x-0 bottom-16 z-40 flex justify-center px-4 md:bottom-6">
      <div className="flex items-center gap-3 rounded-full border border-line bg-panel px-3 py-2 shadow-2xl">
        <span className="pl-1 text-[13px] font-medium tabular-nums">{selectedIds.length} selected</span>
        <button onClick={() => openTemplateSend(selectedIds)} className="flex items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg"><Icon name="send" size={14} /> Send template</button>
        <button onClick={clearSelection} className="rounded-full px-2 py-1.5 text-[13px] text-muted hover:text-ink">Clear</button>
      </div>
    </div>
  );
}
