import { Fragment, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import type { CallRecord } from "../types";
import { Avatar, Icon, dayKey, dayLabel, clockOnly, displayName } from "../lib/ui";
import Select from "../components/Select";
import { AnsweredBadge, CallHistoryList, DirectionBadge, Recording, callTime, mmss } from "../components/CallList";
import CallReviewCell from "../components/CallReviewCell";

const DIRECTION_OPTIONS = [{ value: "all", label: "All calls" }, { value: "outbound", label: "Outbound" }, { value: "inbound", label: "Inbound" }];
const STATUS_OPTIONS = [{ value: "all", label: "Answered + missed" }, { value: "answered", label: "Answered" }, { value: "missed", label: "Missed" }];

/** One patient's calls: the latest is the row, the rest open underneath. */
type PatientCalls = { key: string; latest: CallRecord; earlier: CallRecord[] };

/** Every phone call FasterQ reported for this clinic, one row per patient per day (latest call), history on expand. */
export default function Calls() {
  const store = useStore();
  const { calls, client, features } = store;
  const navigate = useNavigate();
  const [direction, setDirection] = useState("all");
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => { store.ensureCalls(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const matching = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return calls
      .filter((c) => direction === "all" || c.direction === direction)
      .filter((c) => status === "all" || (status === "answered" ? c.answered : !c.answered))
      .filter((c) => !needle || (c.contact_name ?? "").toLowerCase().includes(needle) || c.contact_phone.includes(needle) || (c.agent_name ?? "").toLowerCase().includes(needle))
      .sort((a, b) => (callTime(b) < callTime(a) ? -1 : 1));
  }, [calls, direction, status, q]);

  // Group by patient (newest first within), then by the day of each patient's latest call.
  const days = useMemo(() => {
    const byPatient = new Map<string, PatientCalls>();
    for (const c of matching) {
      const key = c.conversation_id ?? `phone:${c.contact_phone}`;
      const p = byPatient.get(key);
      if (!p) byPatient.set(key, { key, latest: c, earlier: [] }); else p.earlier.push(c);
    }
    const groups = new Map<string, PatientCalls[]>();
    for (const p of byPatient.values()) { const k = dayKey(callTime(p.latest)); (groups.get(k) ?? groups.set(k, []).get(k)!).push(p); }
    return [...groups.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).map(([key, items]) => ({ key, label: dayLabel(callTime(items[0].latest)), items }));
  }, [matching]);

  const agentsSaved = (client.call_recording?.agent_names ?? []).length > 0;
  const th = "sticky top-0 z-10 whitespace-nowrap border-b border-line bg-panel px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted";

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2.5">
        <div><div className="text-[14px] font-semibold">Calls</div><div className="text-[11px] text-muted">{client.name} · {calls.length} calls recorded by FasterQ</div></div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="w-64 max-w-[40vw]"><div className="flex items-center gap-1.5 rounded-lg border border-line bg-panel2 px-2.5"><Icon name="search" size={14} className="shrink-0 text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, number or agent…" className="w-full bg-transparent py-1.5 text-[12.5px] outline-none placeholder:text-muted" /></div></div>
          <div className="w-36"><Select size="sm" label="Direction" value={direction} onChange={setDirection} options={DIRECTION_OPTIONS} /></div>
          <div className="w-44"><Select size="sm" label="Status" value={status} onChange={setStatus} options={STATUS_OPTIONS} /></div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-[12.5px]">
          <thead><tr>{["Patient", "Latest call", "Direction", "Status", "Duration", "Call review", "Recording", ""].map((h, i) => <th key={i} className={`${th} ${h === "Recording" ? "w-[380px]" : ""}`}>{h}</th>)}</tr></thead>
          <tbody>
            {days.map((g) => (
              <Fragment key={g.key}>
                <tr><td colSpan={8} className="sticky top-8 z-[9] border-b border-line bg-panel2/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted backdrop-blur">{g.label} <span className="text-muted/60 tabular-nums">· {g.items.length} patient{g.items.length === 1 ? "" : "s"}</span></td></tr>
                {g.items.map((p) => {
                  const c = p.latest;
                  const isOpen = !!open[p.key];
                  const name = displayName(c.contact_name, c.contact_phone);
                  return (
                    <Fragment key={p.key}>
                      <tr onClick={() => p.earlier.length && setOpen((o) => ({ ...o, [p.key]: !isOpen }))} className={`${p.earlier.length ? "cursor-pointer" : ""} [&>td]:border-b [&>td]:border-line/70 [&>td]:px-3 [&>td]:py-2 hover:[&>td]:bg-panel2/60 ${isOpen ? "[&>td]:bg-panel2/40" : ""}`}>
                        <td>
                          <div className="flex items-center gap-2">
                            <Avatar name={name} size={26} />
                            <div className="min-w-0">
                              {c.conversation_id
                                ? <button onClick={(e) => { e.stopPropagation(); navigate(`/bot/inbox/${c.conversation_id}`); }} className="block truncate font-medium hover:underline">{name}</button>
                                : <span className="block tabular-nums">+{c.contact_phone}</span>}
                              <div className="text-[11px] text-muted">{c.conversation_id ? `+${c.contact_phone}` : "not in inbox"}</div>
                            </div>
                          </div>
                        </td>
                        <td className="whitespace-nowrap tabular-nums text-muted">{clockOnly(callTime(c))}</td>
                        <td><DirectionBadge c={c} /></td>
                        <td><AnsweredBadge c={c} /></td>
                        <td className="tabular-nums">{c.duration_seconds ? mmss(c.duration_seconds) : "—"}</td>
                        <td>{features.callReview
                          ? <CallReviewCell phone={c.contact_phone} calls={[p.latest, ...p.earlier]} />
                          : <span className="text-muted/60">—</span>}</td>
                        <td><Recording c={c} compact /></td>
                        <td className="whitespace-nowrap text-right">
                          {p.earlier.length > 0 && (
                            <button onClick={(e) => { e.stopPropagation(); setOpen((o) => ({ ...o, [p.key]: !isOpen })); }} className="inline-flex items-center gap-1 rounded-md bg-accent/15 px-2 py-1 text-[11.5px] font-medium text-accent transition-colors hover:bg-accent/25">
                              +{p.earlier.length} earlier <Icon name="chevronDown" size={12} className={`transition-transform ${isOpen ? "rotate-180" : ""}`} />
                            </button>
                          )}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr><td colSpan={8} className="border-b border-line/70 bg-panel2/30 px-3 py-1 pl-12">
                          <div className="mb-1 pt-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted">Earlier calls</div>
                          <CallHistoryList calls={p.earlier} />
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
        {matching.length === 0 && (
          <div className="px-6 py-16 text-center text-[13px] text-muted">
            {calls.length === 0
              ? (agentsSaved ? "No calls yet. They appear here as FasterQ reports them." : "No calls yet. Add your FasterQ agent names under Settings → Call recording so calls can be attached to this clinic.")
              : "No calls match."}
          </div>
        )}
      </div>
    </div>
  );
}
