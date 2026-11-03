import { useEffect, useState } from "react";
import { useStore } from "../store";
import type { Lead } from "../types";
import { Badge, Icon, SOURCE_COLOR, SOURCE_LABEL, fullDate } from "../lib/ui";
import RemarkEditor from "./RemarkEditor";
import { CallTriedCell, CustomCell, DispositionSelect, FieldValue, useLeadColumns } from "./LeadFields";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted">{title}</div>
      <div className="divide-y divide-line/60 rounded-lg border border-line bg-panel px-2">{children}</div>
    </div>
  );
}
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 py-1.5">
      <div className="w-24 shrink-0 pt-1 text-[11px] text-muted">{label}</div>
      <div className="min-w-0 flex-1 text-[12.5px]">{children}</div>
    </div>
  );
}
const inputCls = "w-full rounded border border-transparent bg-transparent px-1.5 py-1 outline-none hover:border-line focus:border-accent/60 focus:bg-panel2";

/**
 * The contact and the lead, as the Leads table shows it: whatever columns the
 * clinic has switched on, plus Calls, Disposition and Remark. Engine detail
 * (run state, CRM push, Q&A trail) is deliberately not here.
 */
export default function PropertiesPanel({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const store = useStore();
  // The contact comes from the conversation; the lead part only exists once the
  // person has written to us or a flow has run (see the leads rule in the store).
  const c = store.conversations.find((x) => x.id === conversationId);
  const lead: Lead | undefined = store.leadFor(conversationId);
  const columns = useLeadColumns();
  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  useEffect(() => { setEditing(false); setNameDraft(c?.contact_name ?? ""); }, [conversationId, c?.contact_name]);
  const phone = c?.contact_phone;
  useEffect(() => { if (phone) store.ensureRunForConversation(phone); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [phone]);
  if (!c) return null;
  const saveName = () => { store.updateContact(c.id, { contact_name: nameDraft.trim() }); setEditing(false); };

  return (
    <div className="flex h-full min-h-0 flex-col bg-panel">
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">Properties</div>
        <button onClick={onClose} title="Hide" className="grid h-7 w-7 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name="chevron" size={15} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <Section title="Contact">
          <Row label="Name">
            {editing ? (
              <div className="flex items-center gap-1">
                <input autoFocus value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") saveName(); if (e.key === "Escape") setEditing(false); }} className={`${inputCls} border-line`} />
                <button onClick={saveName} className="text-emerald-600"><Icon name="check" size={14} /></button>
              </div>
            ) : (
              <button onClick={() => setEditing(true)} className="group flex items-center gap-1.5 px-1.5 py-1 font-medium">{c.contact_name || <span className="text-muted">—</span>}<span className="text-[10px] text-muted opacity-0 group-hover:opacity-100">✎</span></button>
            )}
          </Row>
          <Row label="Phone"><span className="px-1.5 py-1 tabular-nums text-muted">+{c.contact_phone}</span></Row>
          <Row label="Source"><span className="px-1.5"><Badge color={SOURCE_COLOR[c.source]}>{SOURCE_LABEL[c.source]}</Badge></span></Row>
          <Row label="First contact"><span className="px-1.5 py-1 text-muted">{fullDate(c.created_at)}</span></Row>
          <Row label="Last seen"><span className="px-1.5 py-1 text-muted">{fullDate(c.last_message_at)}</span></Row>
        </Section>

        {c.source === "ctwa" && (
          <Section title="Ad attribution (CTWA)">
            <Row label="Headline"><span className="px-1.5 py-1">{c.headline ?? "—"}</span></Row>
            <Row label="Type"><span className="px-1.5 py-1 text-muted">{c.source_type ?? "—"}</span></Row>
            <Row label="Ad ID"><span className="px-1.5 py-1 tabular-nums text-muted">{c.source_id ?? "—"}</span></Row>
            <Row label="Ad link">{c.source_url ? <a href={c.source_url} target="_blank" rel="noopener" className="px-1.5 py-1 text-sky-500 underline">{c.source_url}</a> : <span className="px-1.5 text-muted">—</span>}</Row>
          </Section>
        )}

        {lead ? <Section title="Lead">
          {columns.map((col) => (
            <Row key={col.key} label={col.label}>
              <div className="px-1.5 py-1">{col.custom ? <CustomCell lead={lead} col={col.custom} /> : <FieldValue lead={lead} fieldKey={col.key} />}</div>
            </Row>
          ))}
          <Row label="Calls"><div className="px-1.5 py-0.5"><CallTriedCell lead={lead} /></div></Row>
          {store.features.disposition && <div className="py-2"><div className="mb-1 text-[11px] text-muted">Disposition</div><DispositionSelect lead={lead} size="sm" /></div>}
          <div className="py-2"><div className="mb-1 text-[11px] text-muted">Remark</div><RemarkEditor block value={lead.crm.remark} onSave={(t) => store.setRemark(lead.id, t)} /></div>
        </Section> : <Section title="Lead"><div className="py-2 text-[12px] text-muted">Not a lead yet — this thread was started by us. It becomes a lead when they reply.</div></Section>}
        <div className="px-1 text-[11px] text-muted">Created {fullDate(c.created_at)} · {store.flow.name}. Columns follow Leads → Columns +.</div>
      </div>
    </div>
  );
}
