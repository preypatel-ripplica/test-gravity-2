import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useStore } from "../store";
import type { Broadcast, RecipientStatus } from "../types";
import { Badge, Icon, fullDate, timeAgo, displayName } from "../lib/ui";

const R_COLOR: Record<RecipientStatus, string> = { pending: "#64748b", sending: "#3b82f6", sent: "#94a3b8", delivered: "#3b82f6", read: "#22c55e", failed: "#ef4444", skipped: "#f59e0b" };
const WENT_OUT: RecipientStatus[] = ["sent", "delivered", "read"];

/** Staff-facing summary. Backend counters are cumulative: `sent` already includes delivered + read. */
function summary(b: Broadcast) {
  const c = b.counts;
  return { total: c.total, sent: c.sent, failed: c.failed, skipped: c.skipped, pending: c.pending };
}

export default function Broadcasts() {
  const { id } = useParams();
  const navigate = useNavigate();
  const store = useStore();
  const { broadcasts, recipientsFor, openTemplateSend, remote } = store;
  const sorted = useMemo(() => [...broadcasts].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)), [broadcasts]);
  const b = id ? broadcasts.find((x) => x.id === id) : undefined;
  const [filter, setFilter] = useState<"all" | "sent" | "failed" | "skipped">("all");
  // recipients are named from contacts, so both come in together
  useEffect(() => { store.ensureBroadcasts(); store.ensureContacts(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  const inFlight = !!b && (b.counts.pending > 0 || b.status === "running" || b.status === "queued");
  useEffect(() => {
    if (!remote || !id) return;
    const tick = () => store.refreshBroadcast(id).catch(() => { /* retry next tick */ });
    tick();
    if (!inFlight) return;
    const t = window.setInterval(tick, 3000);
    return () => window.clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote, id, inFlight]);

  if (b) {
    const s = summary(b);
    const recs = recipientsFor(b.id).filter((r) => filter === "all" || (filter === "sent" ? WENT_OUT.includes(r.status) : r.status === filter));
    const tiles: { key: typeof filter; label: string; value: number; color?: string }[] = [
      { key: "all", label: "Total", value: s.total },
      { key: "sent", label: "Sent", value: s.sent, color: R_COLOR.read },
      { key: "failed", label: "Failed", value: s.failed, color: R_COLOR.failed },
      { key: "skipped", label: "Skipped", value: s.skipped, color: R_COLOR.skipped },
    ];
    return (
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-panel px-4 py-3">
          <button onClick={() => navigate("/bot/broadcasts")} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name="back" size={16} /></button>
          <div className="min-w-0">
            <div className="flex items-center gap-2"><span className="truncate text-[15px] font-semibold">{b.name}</span>{s.pending > 0 && <span className="text-[11.5px] text-muted">Sending…</span>}</div>
            <div className="text-[11.5px] text-muted">📋 {b.template_name} · {fullDate(b.started_at ?? b.created_at)}</div>
          </div>
        </div>
        <div className="border-b border-line bg-panel px-4 py-3">
          <div className="grid grid-cols-4 gap-2">
            {tiles.map((t) => (
              <button key={t.key} onClick={() => setFilter(t.key)} className={`rounded-lg border px-3 py-2 text-left ${filter === t.key ? "border-accent bg-accent/10" : "border-line hover:bg-panel2"}`}>
                <div className="text-[10px] uppercase tracking-wide text-muted">{t.label}</div>
                <div className="text-[18px] font-semibold tabular-nums" style={{ color: t.color }}>{t.value}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full text-[12.5px]">
            <thead><tr>{["#", "Name", "Number", "Status", "Sent", "Error"].map((h) => <th key={h} className="sticky top-0 border-b border-line bg-panel px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted">{h}</th>)}</tr></thead>
            <tbody>
              {recs.map((r, i) => (
                <tr key={r.id} className="[&>td]:border-b [&>td]:border-line/60 [&>td]:px-3 [&>td]:py-1.5">
                  <td className="w-10 text-right tabular-nums text-muted">{i + 1}</td>
                  <td className="font-medium">{displayName(r.contact_name, r.contact_phone)}</td>
                  <td className="tabular-nums text-muted">+{r.contact_phone}</td>
                  <td><span title={r.error ?? undefined}><Badge color={R_COLOR[r.status]}>{r.status}</Badge></span></td>
                  <td className="text-muted">{r.sent_at ? timeAgo(r.sent_at) : "—"}</td>
                  <td className={r.status === "failed" ? "text-red-500" : "text-muted"}>{r.error ?? (r.status === "failed" ? "Failed (no reason from Meta)" : "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {recs.length === 0 && <div className="py-12 text-center text-[13px] text-muted">No one here.</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-line bg-panel px-4 py-3">
        <div><h1 className="text-[16px] font-semibold">Broadcasts</h1><p className="text-[11.5px] text-muted">Bulk template sends</p></div>
        <button onClick={() => openTemplateSend([])} className="ml-auto flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg"><Icon name="megaphone" size={14} /> Send template</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3 pb-24">
        {sorted.map((b) => {
          const s = summary(b);
          return (
            <button key={b.id} onClick={() => navigate(`/bot/broadcasts/${b.id}`)} className="mb-2 flex w-full items-center gap-3 rounded-xl border border-line bg-panel p-3 text-left hover:border-accent/40">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13.5px] font-medium">{b.name}</div>
                <div className="mt-0.5 text-[11.5px] text-muted">📋 {b.template_name} · {timeAgo(b.created_at)}</div>
              </div>
              <div className="shrink-0 text-right text-[12.5px] tabular-nums">
                {s.pending > 0 && <div className="text-[11px] text-muted">Sending…</div>}
                <span style={{ color: R_COLOR.read }}>{s.sent} sent</span>
                <span className="text-muted"> · </span>
                <span style={{ color: s.failed ? R_COLOR.failed : undefined }} className={s.failed ? "" : "text-muted"}>{s.failed} failed</span>
              </div>
              <Icon name="chevron" size={15} className="shrink-0 text-muted" />
            </button>
          );
        })}
        {sorted.length === 0 && <div className="py-16 text-center text-[13px] text-muted">No bulk sends yet.</div>}
      </div>
    </div>
  );
}
