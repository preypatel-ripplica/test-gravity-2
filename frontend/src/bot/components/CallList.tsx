import type { CallRecord } from "../types";
import { Badge, Icon, clockOnly, fullDate } from "../lib/ui";
import * as api from "../api";

export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.max(0, s) % 60).padStart(2, "0")}`;
export const callTime = (c: CallRecord) => c.started_at ?? c.created_at ?? "";

/** The recording control for one call, by state. */
export function Recording({ c, compact = false }: { c: CallRecord; compact?: boolean }) {
  // Chrome's native player gives the seek bar only what is left after its buttons,
  // so it needs real width to be draggable.
  if (c.recording_status === "stored") return <audio controls preload="none" src={api.callRecordingUrl(c.id)} className={`h-8 w-full ${compact ? "min-w-[300px]" : "max-w-xl"}`} />;
  if (c.recording_status === "pending") return <span className="text-[11.5px] text-muted">recording processing…</span>;
  if (c.recording_status === "failed") return <span title={c.recording_error ?? undefined} className="text-[11.5px] text-amber-600">recording not copied yet</span>;
  return <span className="text-[11.5px] text-muted/60">no recording</span>;
}

export function DirectionBadge({ c }: { c: CallRecord }) {
  return <Badge color={c.direction === "outbound" ? "#6366f1" : "#0ea5e9"}>{c.direction === "outbound" ? "Outbound" : "Inbound"}</Badge>;
}
export function AnsweredBadge({ c }: { c: CallRecord }) {
  return <Badge color={c.answered ? "#22c55e" : "#ef4444"}>{c.answered ? "answered" : "missed"}</Badge>;
}
export const viaLabel = (c: CallRecord) => (c.source === "whatsapp" ? "WhatsApp call" : c.source === "sim" ? "SIM call" : "—");

/** One call, as a vertical card: when · what · who · how long · recording. */
export function CallEntry({ c, showDate = true }: { c: CallRecord; showDate?: boolean }) {
  const when = callTime(c);
  return (
    <div className="flex flex-col gap-1.5 py-2.5">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
        <span className="tabular-nums font-medium">{showDate ? fullDate(when) : clockOnly(when)}</span>
        <DirectionBadge c={c} />
        <AnsweredBadge c={c} />
        <span className="tabular-nums text-muted">{c.duration_seconds ? mmss(c.duration_seconds) : "—"}</span>
        <span className="text-muted">· {viaLabel(c)}</span>
        {c.agent_name && <span className="text-muted">· {c.agent_name}</span>}
      </div>
      <Recording c={c} />
    </div>
  );
}

/** A patient's calls, newest first, one under another. Shared by the Calls page and the popup. */
export function CallHistoryList({ calls, showDate = true }: { calls: CallRecord[]; showDate?: boolean }) {
  const sorted = [...calls].sort((a, b) => (callTime(b) < callTime(a) ? -1 : 1));
  if (sorted.length === 0) return <div className="py-6 text-center text-[12.5px] text-muted"><Icon name="phone" size={14} className="mx-auto mb-1 text-muted/60" />No calls recorded for this patient yet.</div>;
  return <div className="divide-y divide-line/60">{sorted.map((c) => <CallEntry key={c.id} c={c} showDate={showDate} />)}</div>;
}
