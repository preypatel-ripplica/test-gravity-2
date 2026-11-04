import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import type { Lead } from "../types";
import { Avatar, Badge, Icon, SOURCE_COLOR, SOURCE_LABEL, listTime, timeAgo } from "../lib/ui";
import RemarkEditor from "./RemarkEditor";
import { CallLink, CallTriedCell, CustomCell, DispositionSelect, FieldValue, useLeadColumns } from "./LeadFields";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2.5">
      <span className="shrink-0 text-[12px] text-muted">{label}</span>
      <span className="min-w-0 text-right text-[12.5px] font-medium">{children}</span>
    </div>
  );
}

/** Phone: everything about one lead in a bottom sheet — call, fields, disposition, remark. */
export default function LeadSheet({ lead, onClose }: { lead: Lead; onClose: () => void }) {
  const store = useStore();
  const navigate = useNavigate();
  const columns = useLeadColumns();
  const c = lead.conversation;
  const btn = "grid h-9 w-9 place-items-center rounded-full border border-line text-muted hover:text-ink";

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50" onClick={onClose}>
      <div className="flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-line bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-line" />
        <div className="flex items-center gap-3 px-4 py-3">
          <Avatar name={lead.name} size={40} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-semibold">{lead.name}</div>
            <div className="text-[11.5px] text-muted">{listTime(lead.lastActivityAt)}</div>
          </div>
          <CallLink phone={lead.phone} className={`${btn} border-emerald-500/40 bg-emerald-500/10 text-emerald-600`}><Icon name="phone" size={17} /></CallLink>
          <button onClick={onClose} className={btn}><Icon name="x" size={17} /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <div className="divide-y divide-line/60 rounded-xl border border-line bg-panel2/40">
            <Row label="Phone"><CallLink phone={lead.phone} className="tabular-nums text-accent">+{lead.phone}</CallLink></Row>
            <Row label="Source"><Badge color={SOURCE_COLOR[c.source]}>{SOURCE_LABEL[c.source]}</Badge></Row>
            {columns.map((col) => (
              <Row key={col.key} label={col.label}>{col.custom ? <CustomCell lead={lead} col={col.custom} /> : <FieldValue lead={lead} fieldKey={col.key} />}</Row>
            ))}
            <Row label="Calls"><CallTriedCell lead={lead} /></Row>
            <Row label="Last activity"><span className="text-muted">{timeAgo(lead.lastActivityAt)}</span></Row>
            {lead.fields.lead_id && !columns.some((c) => c.key === "lead_id") && <Row label="Conversation ID"><span className="tabular-nums text-muted">{lead.fields.lead_id}</span></Row>}
          </div>

          {store.features.disposition && (
            <div className="mt-4">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted">Disposition</div>
              <DispositionSelect lead={lead} size="sm" />
            </div>
          )}
          <div className="mt-4">
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted">Remark</div>
            <RemarkEditor block value={lead.crm.remark} onSave={(t) => store.setRemark(lead.id, t)} />
          </div>

          <button onClick={() => { onClose(); navigate(`/bot/inbox/${lead.id}`); }} className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-line py-2.5 text-[13px] font-medium hover:bg-panel2">
            <Icon name="inbox" size={15} /> Open chat
          </button>
        </div>
      </div>
    </div>
  );
}
