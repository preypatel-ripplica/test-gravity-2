import { useEffect, useMemo, useState } from "react";
import { useStore } from "../store";
import { TEMPLATE_CATEGORIES } from "../types";
import { Badge, CATEGORY_COLOR, Icon, STATUS_COLOR, STATUS_LABEL } from "../lib/ui";
import { templateBody, templateFooter } from "../lib/templates";
import SubmitTemplateModal from "../components/SubmitTemplateModal";

export default function Templates() {
  const store = useStore();
  const { templates, flow, openTemplateSend, remote } = store;
  const [modal, setModal] = useState(false);
  const [syncing, setSyncing] = useState(false);
  useEffect(() => { store.ensureTemplates(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    if (!remote) return;
    const t = window.setInterval(() => { store.refreshTemplates().catch(() => { /* next tick */ }); }, 60_000);
    return () => window.clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote]);
  const sync = async () => { if (syncing) return; setSyncing(true); try { await store.syncTemplates(); } catch (e) { store.setToast(`Sync failed: ${(e as Error).message}`); } finally { setSyncing(false); } };
  const sorted = useMemo(() => [...templates].sort((a, b) => a.name.localeCompare(b.name)), [templates]);

  return (
    <div className="h-full overflow-y-auto p-4 pb-24">
      <div className="mb-4 flex items-center gap-3">
        <div>
          <h1 className="text-[18px] font-semibold">Templates</h1>
          <p className="text-[12px] text-muted">{flow.name} · WhatsApp message templates</p>
        </div>
        {remote && <button onClick={sync} disabled={syncing} title="Pull the latest approval status from Meta" className="ml-auto flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[13px] text-muted hover:text-ink disabled:opacity-50"><Icon name="refresh" size={14} /> {syncing ? "Syncing…" : "Sync from Meta"}</button>}
        <button onClick={() => setModal(true)} className={`${remote ? "" : "ml-auto "}flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg`}><Icon name="plus" size={15} /> Submit template</button>
      </div>

      {TEMPLATE_CATEGORIES.map((cat) => {
        const items = sorted.filter((t) => t.category === cat);
        return (
          <div key={cat} className="mb-5">
            <div className="mb-2 flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: CATEGORY_COLOR[cat] }} /><h2 className="text-[12.5px] font-semibold">{cat}</h2><span className="text-[11px] text-muted">{items.length}</span></div>
            {items.length === 0 ? (
              <div className="rounded-lg border border-dashed border-line py-5 text-center text-[12px] text-muted">No {cat.toLowerCase()} templates</div>
            ) : (
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                {items.map((t) => (
                  <div key={t.id} className="flex flex-col rounded-xl border border-line bg-panel p-3">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-medium">{t.name}</span>
                      <span className="ml-auto shrink-0"><Badge color={STATUS_COLOR[t.status]}>{t.status === "PENDING" ? "⏳ " : t.status === "APPROVED" ? "✓ " : "✕ "}{STATUS_LABEL[t.status]}</Badge></span>
                    </div>
                    <div className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg bg-panel2 p-2 text-[12px] text-muted">{templateBody(t.components)}</div>
                    {templateFooter(t.components) && <div className="mt-1 px-1 text-[11px] text-muted/70">{templateFooter(t.components)}</div>}
                    <div className="mt-auto pt-3">
                      {t.status === "APPROVED"
                        ? <button onClick={() => openTemplateSend([], t.id)} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent/15 px-3 py-1.5 text-[12.5px] font-medium text-ink hover:bg-accent/25"><Icon name="send" size={13} /> Send</button>
                        : <div className="rounded-lg border border-dashed border-line px-3 py-1.5 text-center text-[11.5px] text-muted">{t.status === "PENDING" ? "In review at Meta" : "Rejected"}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
      <SubmitTemplateModal open={modal} onClose={() => setModal(false)} />
    </div>
  );
}
