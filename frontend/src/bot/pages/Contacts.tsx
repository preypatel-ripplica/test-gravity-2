import { useMemo, useRef, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import { Avatar, Badge, DENSITY, Icon, SOURCE_COLOR, SOURCE_LABEL, timeAgo, displayName } from "../lib/ui";
import { parseSheetFile, guessColumns, toRecipients } from "../lib/sheet";
import Select from "../components/Select";

export default function Contacts() {
  const store = useStore();
  const { contacts, density, selectMode, setSelectMode, selectedIds, toggleSelect, selectMany, clearSelection, conversationByPhone } = store;
  const navigate = useNavigate();
  const d = DENSITY[density];
  const [tag, setTag] = useState<string>("all");
  const [q, setQ] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => { store.ensureContacts(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const tags = useMemo(() => Array.from(new Set(contacts.flatMap((c) => c.tags))).sort(), [contacts]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return contacts
      .filter((c) => tag === "all" || c.tags.includes(tag))
      .filter((c) => !needle || (c.name ?? "").toLowerCase().includes(needle) || c.phone.includes(needle))
      .sort((a, b) => ((b.last_inbound_at ?? b.created_at) < (a.last_inbound_at ?? a.created_at) ? -1 : 1));
  }, [contacts, tag, q]);
  const allSelected = rows.length > 0 && rows.every((c) => selectedIds.includes(c.phone));

  const onImport = async (f: File | undefined) => {
    if (!f) return;
    const data = await parseSheetFile(f);
    const g = guessColumns(data.headers);
    const res = toRecipients(data, g.name, g.phone);
    try {
      const r = await store.importContacts(res.recipients.map((x) => ({ phone: x.phone, name: x.name, tags: [f.name.replace(/\.[^.]+$/, "").slice(0, 24)] })));
      store.setToast(`Imported ${r.added} new, ${r.updated} updated · ${res.invalid.length} invalid, ${res.duplicates} duplicates skipped`);
    } catch (e) { store.setToast(`Import failed: ${(e as Error).message}`); }
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2.5">
        <div><div className="text-[14px] font-semibold">Contacts</div><div className="text-[11px] text-muted">{store.flow.name} · {contacts.length} total</div></div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="w-72 max-w-[45vw]"><div className="flex items-center gap-1.5 rounded-lg border border-line bg-panel2 px-2.5"><Icon name="search" size={14} className="shrink-0 text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or number…" className="w-full bg-transparent py-1.5 text-[12.5px] outline-none placeholder:text-muted" /></div></div>
          <div className="w-36"><Select size="sm" label="Tag" value={tag} onChange={setTag} options={[{ value: "all", label: "All tags" }, ...tags.map((t) => ({ value: t, label: t }))]} /></div>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-muted hover:text-ink"><Icon name="upload" size={14} /> Import<input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => onImport(e.target.files?.[0])} /></label>
          {selectMode && <button onClick={() => selectMany(allSelected ? [] : rows.map((c) => c.phone))} className="rounded-lg border border-line px-2 py-1 text-[12px] text-muted hover:text-ink">{allSelected ? "Deselect all" : "Select all"}</button>}
          <button onClick={() => (selectMode ? clearSelection() : setSelectMode(true))} className={`rounded-lg border px-2.5 py-1.5 text-[12px] ${selectMode ? "border-accent bg-accent/15 text-ink" : "border-line text-muted hover:text-ink"}`}>{selectMode ? "Done" : "Select"}</button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-24">
        {rows.map((c) => {
          const sel = selectedIds.includes(c.phone);
          const conv = conversationByPhone(c.phone);
          return (
            <div key={c.id} onClick={() => (selectMode ? toggleSelect(c.phone) : conv ? navigate(`/bot/inbox/${conv.id}`) : store.openTemplateSend([c.phone]))} className={`flex cursor-pointer items-center gap-3 border-b border-line/60 px-3 ${d.pad} hover:bg-panel2/60`}>
              {selectMode && <span className={`grid h-5 w-5 shrink-0 place-items-center rounded border ${sel ? "border-accent bg-accent text-accent-fg" : "border-line"}`}>{sel && <Icon name="check" size={12} />}</span>}
              <Avatar name={displayName(c.name, c.phone)} size={34} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className={`truncate font-medium ${d.text}`}>{displayName(c.name, c.phone)}</span>{c.tags.map((t) => <span key={t} className="rounded-md bg-accent/10 px-1.5 py-0.5 text-[10.5px] text-muted">{t}</span>)}</div>
                <div className="truncate text-[12px] text-muted tabular-nums">+{c.phone}{!conv && <span className="ml-2 text-[11px]">· no chat yet</span>}</div>
              </div>
              <Badge color={SOURCE_COLOR[c.source]}>{SOURCE_LABEL[c.source]}</Badge>
              <span className="hidden w-14 text-right text-[11px] text-muted sm:inline">{timeAgo(c.last_inbound_at ?? c.created_at)}</span>
            </div>
          );
        })}
        {rows.length === 0 && <div className="py-16 text-center text-[13px] text-muted">No contacts.</div>}
      </div>
    </div>
  );
}
