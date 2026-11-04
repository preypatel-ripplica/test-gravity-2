import { useEffect, useMemo, useState } from "react";
import type { Conversation, ConversationStatus } from "../types";
import { useStore } from "../store";
import { Avatar, DENSITY, Icon, listTime, displayName } from "../lib/ui";

const FILTERS = ["all", "unread", "template"] as const;
type Filter = (typeof FILTERS)[number];
/** The pills render a label map rather than the key: "Template msg." cannot come
 * from `capitalize` on a key. */
const FILTER_LABEL: Record<Filter, string> = { all: "All", unread: "Unread", template: "Template msg." };
const TIER: Record<ConversationStatus, number> = { open: 0, resolved: 1, expired: 2 };

/** Status dot: red expired · grey resolved · amber agent handling · green bot active. */
export function StatusDot({ c }: { c: Conversation }) {
  const [color, title] =
    c.status === "expired" ? ["bg-red-500", "expired (24h window closed)"]
    : c.status === "resolved" ? ["bg-muted/60", "resolved"]
    : c.bot_paused ? ["bg-amber-500", "agent handling"]
    : ["bg-emerald-500", "bot active"];
  return <span title={title} className={`inline-block h-2 w-2 shrink-0 rounded-full ${color}`} />;
}

export default function ConversationList({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string) => void }) {
  const { conversations, density, hasMoreConversations, loadMoreConversations, convCounts, setConversationView } = useStore();
  const d = DENSITY[density];
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  // Which server view this tab reads. All/Unread share one; Template msg. pages
  // separately, so a clinic with 1200 of them never drags them through All.
  const view = filter === "template" ? "template" : "inbox";
  useEffect(() => { setConversationView(view); }, [view, setConversationView]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return conversations
      .filter((c) => (filter === "template" ? c.awaiting_template_reply : !c.awaiting_template_reply))
      .filter((c) => filter !== "unread" || c.unread_count > 0)
      .filter((c) => !needle || (c.contact_name ?? "").toLowerCase().includes(needle) || c.contact_phone.includes(needle) || (c.last_message_text ?? "").toLowerCase().includes(needle))
      .sort((a, b) => TIER[a.status] - TIER[b.status] || ((b.last_message_at ?? "") < (a.last_message_at ?? "") ? -1 : 1));
  }, [conversations, filter, q]);

  // Only the unread figure is actionable; a running total of every conversation
  // ever would just grow without telling anyone anything.
  // Both figures describe All/Unread only: once the template tab has been
  // opened its rows live in the same array and would otherwise be counted here.
  const inboxRows = useMemo(() => conversations.filter((c) => !c.awaiting_template_reply), [conversations]);
  const unreadChats = useMemo(() => inboxRows.filter((c) => c.unread_count > 0).length, [inboxRows]);
  const unread = inboxRows.reduce((n, c) => n + c.unread_count, 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Inbox</span>
          {unread > 0 && <span className="rounded-full bg-emerald-500 px-1.5 text-[10.5px] font-semibold text-white tabular-nums">{unread}</span>}
        </div>
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-line bg-panel2 px-2">
          <Icon name="search" size={13} className="text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, phone or message" className="w-full bg-transparent py-1.5 text-[12.5px] outline-none placeholder:text-muted" />
        </div>
        <div className="mt-2 flex gap-1 overflow-x-auto">
          {FILTERS.map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11.5px] ${filter === f ? "bg-accent/15 text-ink" : "text-muted hover:text-ink"}`}>
              {FILTER_LABEL[f]}
              {f === "unread" && <span className="text-muted/70 tabular-nums"> {unreadChats}</span>}
              {f === "template" && convCounts.template > 0 && <span className="text-muted/70 tabular-nums"> {convCounts.template}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" onScroll={(e) => { const el = e.currentTarget; if (hasMoreConversations(view) && el.scrollHeight - el.scrollTop - el.clientHeight < 240) void loadMoreConversations(view); }}>
        {rows.map((c) => (
          <button key={c.id} onClick={() => onSelect(c.id)} className={`flex w-full items-center gap-2.5 border-b border-line/60 px-3 text-left ${d.pad} ${selectedId === c.id ? "bg-panel2" : "hover:bg-panel2/60"}`}>
            <Avatar name={displayName(c.contact_name, c.contact_phone)} size={38} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <StatusDot c={c} />
                <span className={`truncate font-medium ${d.text}`}>{displayName(c.contact_name, c.contact_phone)}</span>
                <span className="ml-auto shrink-0 text-[10.5px] text-muted">{listTime(c.last_message_at ?? c.created_at)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="truncate text-[12px] text-muted">{c.last_message_direction === "outgoing" ? "You: " : ""}{c.last_message_text ?? "—"}</span>
                {c.unread_count > 0 && <span className="ml-auto shrink-0 rounded-full bg-emerald-500 px-1.5 text-[10px] font-semibold text-white tabular-nums">{c.unread_count}</span>}
              </div>
            </div>
          </button>
        ))}
        {rows.length === 0 && <div className="py-16 text-center text-[13px] text-muted">No conversations</div>}
        {hasMoreConversations(view) && <button onClick={() => void loadMoreConversations(view)} className="w-full py-3 text-center text-[11.5px] text-muted hover:text-ink">Load more…</button>}
      </div>
    </div>
  );
}
