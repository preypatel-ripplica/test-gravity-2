import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { CallRecord, Lead } from "../types";
import { Avatar, Icon } from "../lib/ui";
import * as api from "../api";
import { CallHistoryList } from "./CallList";

/** Every FasterQ call for one patient, opened from the Calls count anywhere a lead is shown. */
export default function CallHistoryModal({ lead, onClose }: { lead: Lead; onClose: () => void }) {
  const [calls, setCalls] = useState<CallRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.listCalls({ conversation_id: lead.id }, 500).then((r) => { if (alive) setCalls(r); }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [lead.id]);
  const outbound = (calls ?? []).filter((c) => c.direction === "outbound").length;

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/50 sm:items-center" onMouseDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onClose(); }}>
      <div className="flex max-h-[85dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-line bg-panel shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <Avatar name={lead.name} size={36} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-semibold">{lead.name}</div>
            <div className="text-[11.5px] tabular-nums text-muted">+{lead.phone}{calls && ` · ${calls.length} call${calls.length === 1 ? "" : "s"} · ${outbound} outbound`}</div>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          {error && <div className="py-6 text-center text-[12.5px] text-red-500">Could not load calls: {error}</div>}
          {!error && calls === null && <div className="py-6 text-center text-[12.5px] text-muted">Loading…</div>}
          {calls && <CallHistoryList calls={calls} />}
        </div>
      </div>
    </div>,
    document.body,
  );
}
