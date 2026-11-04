import { Fragment, useMemo, useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useStore, CORE_COLUMNS } from "../store";
import { type Lead, type Density } from "../types";
import { Avatar, Badge, DENSITY, Icon, SOURCE_COLOR, SOURCE_LABEL, enumColor, timeAgo, dayKey, dayLabel, clockOnly, listTime } from "../lib/ui";
import ColumnPicker from "../components/ColumnPicker";
import Select from "../components/Select";
import RemarkEditor from "../components/RemarkEditor";
import AddColumnDialog from "../components/AddColumnDialog";
import LeadSheet from "../components/LeadSheet";
import { StatusDot } from "../components/ConversationList";
import { CallLink, CallTriedCell, CustomCell, DispositionSelect, stop } from "../components/LeadFields";

const DENSITIES: Density[] = ["compact", "cozy", "comfortable"];
const DLABEL: Record<Density, string> = { compact: "S", cozy: "M", comfortable: "L" };
const PERMANENT = ["Time", "Patient", "Phone", "Disposition", "Call tried", "Remark"];

function Check({ on }: { on: boolean }) {
  return <span className={`grid h-5 w-5 shrink-0 place-items-center rounded border ${on ? "border-accent bg-accent text-accent-fg" : "border-line"}`}>{on && <Icon name="check" size={12} />}</span>;
}
const timeOfDay = (iso: string) => clockOnly(iso);

const SOURCE_OPTIONS = [
  { value: "All", label: "All sources" },
  { value: "ctwa", label: "CTWA ad", color: SOURCE_COLOR.ctwa },
  { value: "whatsapp", label: "WhatsApp", color: SOURCE_COLOR.whatsapp },
];

export default function LeadsGrid() {
  const { remote, features, leads, leadFeed, loadLeads, loadMoreLeads, setLeadsWatched, flow, visibleColumns, toggleColumn, clearColumns, customColumns, removeCustomColumn, density, setDensity, selectMode, setSelectMode, selectedIds, toggleSelect, selectMany, clearSelection, setRemark } = useStore();
  const navigate = useNavigate();
  const [sourceF, setSourceF] = useState<string>("All");
  const [q, setQ] = useState("");
  const [addCol, setAddCol] = useState(false);
  const [sheetKey, setSheetKey] = useState<string | null>(null);
  // The feed is server-paged: page 1 on mount (or after a reload), filters are
  // server-side (debounced), live events refresh it only while this page is open.
  const filtersRef = useRef({ q, source: sourceF });
  filtersRef.current = { q, source: sourceF };
  useEffect(() => { setLeadsWatched(true); return () => setLeadsWatched(false); }, [setLeadsWatched]);
  // Always (re)fetch on mount. Skipping while `loading` left the page stuck on
  // "Loading leads…" after a hung API request; loadLeads increments a seq so a
  // newer call supersedes an in-flight one.
  useEffect(() => {
    if (!remote) return;
    void loadLeads({ q: filtersRef.current.q.trim(), source: filtersRef.current.source === "All" ? "" : filtersRef.current.source });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote, loadLeads]);
  const firstFilter = useRef(true);
  useEffect(() => {
    if (!remote) return;
    if (firstFilter.current) { firstFilter.current = false; return; }
    const t = window.setTimeout(() => void loadLeads({ q: q.trim(), source: sourceF === "All" ? "" : sourceF }), 350);
    return () => window.clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, sourceF]);
  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 600) void loadMoreLeads();
  }, [loadMoreLeads]);

  const fieldByKey = useMemo(() => Object.fromEntries(flow.fields.map((f) => [f.key, f])), [flow]);
  const customByKey = useMemo(() => Object.fromEntries(customColumns.map((c) => [c.key, c])), [customColumns]);
  const available = useMemo(() => [...CORE_COLUMNS, ...flow.fields.map((f) => ({ key: f.key, label: f.label })), ...customColumns.map((c) => ({ key: c.key, label: c.label, custom: true }))], [flow, customColumns]);
  const columns = visibleColumns.filter((k) => available.some((a) => a.key === k));

  // Remote: the server already filtered and ordered the feed (newest arrival first).
  // Mock mode keeps the client-side filter over the seeded leads.
  const rows = useMemo(() => {
    if (remote) return leads;
    const needle = q.trim().toLowerCase();
    return leads
      .filter((l) => sourceF === "All" || l.conversation.source === sourceF)
      .filter((l) => !needle || l.name.toLowerCase().includes(needle) || l.phone.includes(needle))
      .sort((a, b) => (a.arrivedAt < b.arrivedAt ? 1 : -1));
  }, [leads, sourceF, q, remote]);

  const groups = useMemo(() => {
    const map = new Map<string, Lead[]>();
    for (const l of rows) { const k = dayKey(l.arrivedAt); (map.get(k) ?? map.set(k, []).get(k)!).push(l); }
    return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).map(([key, items]) => ({ key, label: dayLabel(items[0].arrivedAt), items }));
  }, [rows]);

  const emptyText = leadFeed.loading && rows.length === 0 ? "Loading leads…" : !leadFeed.ready ? "Loading leads…" : "No leads match.";
  const footer = remote && rows.length > 0 && (
    <div className="flex items-center justify-center gap-3 py-4 text-[12px] text-muted">
      <span className="tabular-nums">{rows.length} of {leadFeed.total}</span>
      {leadFeed.hasMore && <button onClick={() => void loadMoreLeads()} disabled={leadFeed.loading} className="rounded-lg border border-line px-3 py-1.5 text-[12px] text-ink hover:border-accent/40 disabled:opacity-60">{leadFeed.loading ? "Loading…" : "Load more"}</button>}
    </div>
  );

  const d = DENSITY[density];
  const open = (id: string) => navigate(`/bot/inbox/${id}`);
  const rowClick = (l: Lead) => (selectMode ? toggleSelect(l.phone) : open(l.id));
  const allSelected = rows.length > 0 && rows.every((r) => selectedIds.includes(r.phone));
  const labelFor = (key: string) => available.find((a) => a.key === key)?.label ?? key;

  function cell(l: Lead, key: string) {
    if (key === "phone") return <button onClick={(e) => { stop(e); open(l.id); }} className="tabular-nums text-accent hover:underline">+{l.phone}</button>;
    if (key === "source") return <Badge color={SOURCE_COLOR[l.conversation.source]}>{SOURCE_LABEL[l.conversation.source]}</Badge>;
    if (key === "status") return <span className="flex items-center gap-1.5 capitalize"><StatusDot c={l.conversation} />{l.conversation.status}{l.conversation.bot_paused ? " · agent" : ""}</span>;
    if (key === "lastActivity") return <span className="whitespace-nowrap text-muted">{timeAgo(l.lastActivityAt)}</span>;
    const cc = customByKey[key];
    if (cc) return <CustomCell lead={l} col={cc} />;
    const f = fieldByKey[key]; const v = l.fields[key] || "";
    if (!v) return <span className="text-muted/50">—</span>;
    if (f?.type === "enum") return <Badge color={enumColor(v)}>{v}</Badge>;
    return <span className="truncate text-muted">{v}</span>;
  }

  const fixedCount = PERMANENT.length;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2.5">
        <div className="w-28 md:w-36"><Select size="sm" label="Source" value={sourceF} onChange={setSourceF} options={SOURCE_OPTIONS} /></div>
        <div className="min-w-0 flex-1 md:w-72 md:flex-none"><div className="flex items-center gap-1.5 rounded-lg border border-line bg-panel2 px-2.5"><Icon name="search" size={14} className="shrink-0 text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className="w-full min-w-0 bg-transparent py-1.5 text-[12.5px] outline-none placeholder:text-muted" /></div></div>
        {/* Phone: the column chooser sits here (it picks the phone set). */}
        <div className="md:hidden"><ColumnPicker compact available={available} visible={columns} onToggle={toggleColumn} onClear={clearColumns} /></div>
        <button onClick={() => (selectMode ? clearSelection() : setSelectMode(true))} className={`shrink-0 rounded-lg border px-2.5 py-1.5 text-[12px] ${selectMode ? "border-accent bg-accent/15 text-ink" : "border-line text-muted hover:text-ink"}`}>{selectMode ? "Done" : "Select"}</button>
        <div className="hidden items-center gap-1.5 md:flex">
          <span className="text-[11.5px] text-muted">Size</span>
          <div className="flex items-center gap-0.5 rounded-lg border border-line p-0.5">{DENSITIES.map((dd) => <button key={dd} onClick={() => setDensity(dd)} title={dd} className={`h-6 w-6 rounded-md text-[11px] font-semibold ${density === dd ? "bg-accent/15 text-ink" : "text-muted hover:text-ink"}`}>{DLABEL[dd]}</button>)}</div>
        </div>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          <ColumnPicker available={available} visible={columns} onToggle={toggleColumn} onClear={clearColumns} onAddCustom={features.customColumns ? () => setAddCol(true) : undefined} onRemoveCustom={removeCustomColumn} />
        </div>
      </div>

      {/* Desktop table */}
      <div className="hidden min-h-0 flex-1 overflow-auto md:block" onScroll={onScroll}>
        <table className={`w-full border-separate border-spacing-0 ${d.text}`}>
          <thead><tr>
            {selectMode && <th className="sticky top-0 z-10 w-8 border-b border-line bg-panel px-2 py-2"><button onClick={() => selectMany(allSelected ? [] : rows.map((r) => r.phone))}><Check on={allSelected} /></button></th>}
            {PERMANENT.map((h) => <th key={h} className="sticky top-0 z-10 whitespace-nowrap border-b border-line bg-panel px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted">{h}</th>)}
            {columns.map((k) => <th key={k} className="sticky top-0 z-10 whitespace-nowrap border-b border-line bg-panel px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted">{labelFor(k)}</th>)}
          </tr></thead>
          <tbody>
            {groups.map((g) => (
              <Fragment key={g.key}>
                <tr><td colSpan={fixedCount + (selectMode ? 1 : 0) + columns.length} className="sticky top-8 z-[9] border-b border-line bg-panel2/70 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted backdrop-blur">{g.label} <span className="text-muted/60 tabular-nums">· {g.items.length}</span></td></tr>
                {g.items.map((l) => (
                  <tr key={l.rowKey} onClick={() => rowClick(l)} className="group cursor-pointer [&>td]:border-b [&>td]:border-line/70 [&>td]:px-2 hover:[&>td]:bg-panel2/60">
                    {selectMode && <td className={d.pad}><Check on={selectedIds.includes(l.phone)} /></td>}
                    <td className={`${d.pad} whitespace-nowrap tabular-nums text-muted`}>{timeOfDay(l.arrivedAt)}</td>
                    <td className={d.pad}><button onClick={(e) => { stop(e); open(l.id); }} className="flex items-center gap-2 font-medium hover:underline"><Avatar name={l.name} size={22} /><span className="truncate">{l.name}</span>{l.conversation.unread_count > 0 && <span className="rounded-full bg-emerald-500 px-1.5 text-[10px] font-semibold text-white">{l.conversation.unread_count}</span>}</button></td>
                    <td className={d.pad}>{cell(l, "phone")}</td>
                    <td className={d.pad}><DispositionSelect lead={l} /></td>
                    <td className={d.pad}><CallTriedCell lead={l} /></td>
                    <td className={`${d.pad} max-w-[260px]`}><RemarkEditor value={l.crm.remark} onSave={(t) => setRemark(l.id, t)} /></td>
                    {columns.map((k) => <td key={k} className={d.pad}>{cell(l, k)}</td>)}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="py-16 text-center text-[13px] text-muted">{emptyText}</div>}
        {footer}
      </div>

      {/* Phone: one card per lead — call, disposition and remark at hand; tap for the full sheet. */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3 md:hidden" onScroll={onScroll}>
        {groups.map((g) => (
          <div key={g.key} className="mb-3">
            <div className="sticky top-0 z-10 -mx-1 mb-1.5 bg-bg/80 px-1 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted backdrop-blur">{g.label} <span className="text-muted/60 tabular-nums">· {g.items.length}</span></div>
            <div className="space-y-2">
              {g.items.map((l) => {
                const firstEnum = columns.map((k) => ({ k, v: l.fields[k] || "" })).find(({ k, v }) => v && fieldByKey[k]?.type === "enum");
                return (
                  <div key={l.rowKey} className="rounded-xl border border-line bg-panel">
                    <div onClick={() => (selectMode ? toggleSelect(l.phone) : setSheetKey(l.rowKey))} className="flex items-start gap-3 px-3 pt-3">
                      {selectMode && <Check on={selectedIds.includes(l.phone)} />}
                      <Avatar name={l.name} size={40} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2"><span className="truncate text-[14px] font-semibold">{l.name}</span>{l.conversation.unread_count > 0 && <span className="rounded-full bg-emerald-500 px-1.5 text-[10px] font-semibold text-white">{l.conversation.unread_count}</span>}<span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted">{listTime(l.lastActivityAt)}</span></div>
                        <div className="text-[12.5px] tabular-nums text-accent">+{l.phone}</div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                          <Badge color={SOURCE_COLOR[l.conversation.source]}>{SOURCE_LABEL[l.conversation.source]}</Badge>
                          <span className="flex items-center gap-1 text-[11.5px] tabular-nums text-muted"><Icon name="phone" size={11} /> {l.crm.call_tried}</span>
                          {firstEnum && <Badge color={enumColor(firstEnum.v)}>{firstEnum.v}</Badge>}
                        </div>
                      </div>
                      <Icon name="chevron" size={14} className="mt-3 shrink-0 text-muted" />
                    </div>
                    <div className="mt-2.5 flex items-center gap-2 border-t border-line/60 px-3 py-2">
                      <CallLink phone={l.phone} className="flex shrink-0 items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-[12.5px] font-medium text-emerald-600"><Icon name="phone" size={14} /> Call</CallLink>
                      <div className="min-w-0 flex-1"><DispositionSelect lead={l} size="sm" /></div>
                    </div>
                    {l.crm.remark && (
                      <div className="border-t border-line/60 px-3 py-2">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">Remark</div>
                        <div className="max-w-full"><RemarkEditor value={l.crm.remark} onSave={(t) => setRemark(l.id, t)} /></div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {rows.length === 0 && <div className="py-16 text-center text-[13px] text-muted">{emptyText}</div>}
        {footer}
      </div>

      {sheetKey && (() => { const l = leads.find((x) => x.rowKey === sheetKey); return l ? <LeadSheet lead={l} onClose={() => setSheetKey(null)} /> : null; })()}
      <AddColumnDialog open={addCol} onClose={() => setAddCol(false)} />
    </div>
  );
}
