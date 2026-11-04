import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import type { BroadcastPreview, Template } from "../types";
import { Badge, CATEGORY_COLOR, Icon, displayName } from "../lib/ui";
import { renderTemplateBody, templateFooter, firstName } from "../lib/templates";
import { parseSheetFile, guessColumns, toRecipients, normalizePhone, type SheetData } from "../lib/sheet";
import Select from "./Select";

type Recipient = { phone: string; name: string; params: string[] };
/** Params sized to the template: keep what was typed, default {{1}} to the first name. */
const padParams = (r: { name: string; params: string[] }, n: number) => Array.from({ length: n }, (_, i) => r.params[i] ?? (i === 0 ? firstName(r.name) : ""));

/**
 * Global "send template" modal, opened via store.openTemplateSend(phones, templateId?).
 * Two ways: to individual people (pick contacts, per-person variables) or upload
 * an Excel/CSV for a bulk send (→ Broadcast with preview + confirm).
 */
export default function SendTemplateModal() {
  const store = useStore();
  const navigate = useNavigate();
  const target = store.templateTarget;
  // Opened for specific people (from a chat or a lead selection): the recipients
  // are known, so no picking and no bulk upload — those live on Templates/Broadcasts.
  const targeted = (target?.phones.length ?? 0) > 0;
  const open = !!target;
  const approved = useMemo(() => store.templates.filter((t) => t.status === "APPROVED"), [store.templates]);
  const [tab, setTab] = useState<"people" | "excel">("people");
  const [tmplId, setTmplId] = useState<string>("");
  const [recips, setRecips] = useState<Recipient[]>([]);
  const [q, setQ] = useState("");
  const [manual, setManual] = useState({ name: "", phone: "" });
  // excel
  const [sheet, setSheet] = useState<SheetData | null>(null);
  const [cols, setCols] = useState({ name: 0, phone: 1 });
  const [bName, setBName] = useState("");
  const [preview, setPreview] = useState<BroadcastPreview | null>(null);
  const [parsed, setParsed] = useState<{ recipients: Recipient[]; duplicates: number; invalid: number } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [sending, setSending] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  const tmpl: Template | undefined = approved.find((t) => t.id === tmplId);
  const nVars = tmpl?.body_variable_count ?? 0;

  useEffect(() => {
    if (!open) return;
    store.ensureTemplates(); store.ensureContacts();
    setTab("people"); setQ(""); setManual({ name: "", phone: "" }); setSheet(null); setParsed(null); setPreview(null); setConfirm(false); setBName("");
    setTmplId(target?.templateId ?? approved[0]?.id ?? "");
    const initial = (target?.phones ?? []).map((p) => { const c = store.conversationByPhone(p) ?? undefined; const ct = store.contacts.find((x) => x.phone === p); const name = c?.contact_name ?? ct?.name ?? ""; return { phone: p, name, params: [] as string[] }; });
    setRecips(initial.map((r) => ({ ...r, params: padParams(r, nVars) })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  // Size params to the template (and prefill {{1}}) whenever the template changes or the modal opens —
  // the modal keeps its state while closed, so this must not depend on nVars changing.
  useEffect(() => { setRecips((rs) => rs.map((r) => ({ ...r, params: padParams(r, nVars) }))); }, [nVars, open]);

  if (!open) return null;

  const candidates = store.contacts.filter((c) => !recips.some((r) => r.phone === c.phone)).filter((c) => { const n = q.trim().toLowerCase(); return n && ((c.name ?? "").toLowerCase().includes(n) || c.phone.includes(n)); }).slice(0, 6);
  const addRecipient = (phone: string, name: string) => {
    if (recips.some((r) => r.phone === phone)) { store.setToast(`+${phone} is already in the list`); return; }
    setRecips((rs) => [...rs, { phone, name, params: padParams({ name, params: [] }, nVars) }]);
  };
  const addManual = () => { const p = normalizePhone(manual.phone); if (!p) return; addRecipient(p, manual.name.trim()); setManual({ name: "", phone: "" }); };
  const setParam = (phone: string, i: number, v: string) => setRecips((rs) => rs.map((r) => (r.phone === phone ? { ...r, params: padParams(r, Math.max(nVars, i + 1)).map((x, j) => (j === i ? v : x)) } : r)));
  const ready = !!tmpl && recips.length > 0 && recips.every((r) => padParams(r, nVars).every((p) => p.trim()));

  const sendPeople = async () => {
    if (!tmpl || !ready || sending) return;
    setSending(true);
    let last = ""; let ok = 0; const failed: string[] = [];
    for (const r of recips) {
      try { last = await store.sendTemplate(r.phone, r.name || null, tmpl, r.params.slice(0, nVars)); ok++; }
      catch (e) { failed.push(`+${r.phone}: ${(e as Error).message}`); }
    }
    setSending(false);
    if (failed.length) { store.setToast(`Sent ${ok}/${recips.length} · failed: ${failed.join("; ")}`.slice(0, 300)); if (ok === 0) return; }
    else store.setToast(`“${tmpl.name}” sent to ${ok} ${ok === 1 ? "person" : "people"}`);
    store.clearSelection(); store.closeTemplateSend();
    if (recips.length === 1 && last) navigate(`/bot/inbox/${last}`);
  };
  /** Backend bulk sends fill only {{1}} (= contact name); multi-variable templates must go one by one. */
  const excelBlocked = store.remote && nVars > 1;

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    const data = await parseSheetFile(f);
    setSheet(data); setCols(guessColumns(data.headers)); setParsed(null); setPreview(null); setConfirm(false);
    if (!bName) setBName(f.name.replace(/\.[^.]+$/, ""));
  };
  const buildRows = async () => {
    if (!sheet || !tmpl || excelBlocked || previewing) return;
    const res = toRecipients(sheet, cols.name, cols.phone);
    const recipients: Recipient[] = res.recipients.map((r) => ({ phone: r.phone, name: r.name, params: Array.from({ length: nVars }, (_, i) => (i === 0 ? firstName(r.name) : r.extras[i - 1] ?? "")) }));
    setParsed({ recipients, duplicates: res.duplicates, invalid: res.invalid.length });
    setPreviewing(true);
    try { setPreview(await store.previewBroadcast(recipients, tmpl)); }
    catch (e) { store.setToast(`Preview failed: ${(e as Error).message}`); }
    finally { setPreviewing(false); }
  };
  const sendExcel = async () => {
    if (!tmpl || !parsed || !preview || preview.over_hard_cap || sending) return;
    if (preview.requires_confirmation && !confirm) { setConfirm(true); return; }
    setSending(true);
    try {
      const id = await store.createBroadcast(bName || `${tmpl.name} — ${new Date().toLocaleDateString()}`, tmpl, parsed.recipients, confirm);
      store.setToast(`Broadcast started · ${preview.sendable} recipients`);
      store.closeTemplateSend();
      navigate(`/bot/broadcasts/${id}`);
    } catch (e) { store.setToast(`Could not start broadcast: ${(e as Error).message}`); }
    finally { setSending(false); }
  };

  const inputCls = "w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-[13px] outline-none focus:border-accent/50";

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 sm:items-center" onClick={store.closeTemplateSend}>
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl border border-line bg-panel shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-[14px] font-semibold">Send template</div>
          <button onClick={store.closeTemplateSend} className="grid h-7 w-7 place-items-center rounded-lg text-muted hover:bg-panel2"><Icon name="x" size={16} /></button>
        </div>

        {/* template picker + tabs */}
        <div className="border-b border-line px-4 py-3">
          <label className="mb-1 block text-[11.5px] text-muted">Template (approved only)</label>
          <Select label="Template" value={tmplId} onChange={setTmplId} placeholder="Choose a template" options={approved.map((t) => ({ value: t.id, label: t.name, hint: t.category, color: CATEGORY_COLOR[t.category] }))} />
          {tmpl && (
            <div className="mt-2 rounded-lg bg-panel2 p-2.5 text-[12px]">
              <div className="mb-1 flex items-center gap-2"><Badge color={CATEGORY_COLOR[tmpl.category]}>{tmpl.category}</Badge></div>
              <div className="max-h-40 overflow-y-auto whitespace-pre-wrap text-muted">{renderTemplateBody(tmpl.components, recips[0]?.params ?? [])}</div>
              {templateFooter(tmpl.components) && <div className="mt-1 text-[11px] text-muted/70">{templateFooter(tmpl.components)}</div>}
            </div>
          )}
          {!targeted && <div className="mt-3 flex gap-1 rounded-lg border border-line p-0.5 text-[12.5px]">
            {(["people", "excel"] as const).map((t) => <button key={t} onClick={() => setTab(t)} className={`flex-1 rounded-md py-1.5 ${tab === t ? "bg-accent/15 text-ink" : "text-muted hover:text-ink"}`}>{t === "people" ? "👤 Individual people" : "📄 Upload Excel / CSV"}</button>)}
          </div>}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {tab === "people" ? (
            <>
              {!targeted && <><div className="relative">
                <div className="flex items-center gap-2 rounded-lg border border-line bg-panel2 px-2.5"><Icon name="search" size={14} className="text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search contacts by name or phone…" className="w-full bg-transparent py-2 text-[13px] outline-none placeholder:text-muted" /></div>
                {candidates.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-line bg-panel shadow-xl">
                    {candidates.map((c) => <button key={c.id} onClick={() => { addRecipient(c.phone, c.name ?? ""); setQ(""); }} className="flex w-full items-center justify-between px-3 py-2 text-left text-[13px] hover:bg-panel2"><span>{displayName(c.name, c.phone)}</span><span className="text-[11.5px] text-muted tabular-nums">+{c.phone}</span></button>)}
                  </div>
                )}
              </div>
              <div className="mt-2 flex gap-2">
                <input value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} placeholder="Name" className={inputCls} />
                <input value={manual.phone} onChange={(e) => setManual({ ...manual, phone: e.target.value })} placeholder="Phone (10-digit or 91…)" className={inputCls} onKeyDown={(e) => e.key === "Enter" && addManual()} />
                <button onClick={addManual} className="shrink-0 rounded-lg border border-line px-3 text-[12.5px] text-muted hover:text-ink">Add</button>
              </div></>}

              <div className="mt-3 space-y-2">
                {recips.length === 0 && <div className="py-6 text-center text-[12.5px] text-muted">No recipients yet — search a contact or add a number.</div>}
                {recips.map((r) => (
                  <div key={r.phone} className="rounded-lg border border-line p-2.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium">{r.name || `+${r.phone}`}</span>
                      <span className="text-[11.5px] text-muted tabular-nums">+{r.phone}</span>
                      <button onClick={() => setRecips((rs) => rs.filter((x) => x.phone !== r.phone))} className="ml-auto text-muted hover:text-ink"><Icon name="x" size={14} /></button>
                    </div>
                    {nVars > 0 && (
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        {Array.from({ length: nVars }, (_, i) => (
                          <label key={i} className="text-[11px] text-muted">{`{{${i + 1}}}`}<input value={r.params[i] ?? ""} onChange={(e) => setParam(r.phone, i, e.target.value)} className={`${inputCls} mt-0.5 py-1.5`} /></label>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              {excelBlocked && <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-600">This template has {nVars} variables. Bulk sends fill only {"{{1}}"} with the person's name — send it from the “Individual people” tab instead.</div>}
              <label className="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-line py-6 text-[12.5px] text-muted hover:border-accent/50">
                <Icon name="upload" size={20} />
                {sheet ? <span>{sheet.rows.length} rows loaded — choose another file to replace</span> : <span>Click to upload <b>.xlsx</b> / <b>.csv</b> with names and phone numbers</span>}
                <input type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
              </label>
              {sheet && (
                <div className="mt-3 space-y-3">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <label className="text-[11px] text-muted">Broadcast name<input value={bName} onChange={(e) => setBName(e.target.value)} className={`${inputCls} mt-0.5`} /></label>
                    <div className="text-[11px] text-muted">Name column<div className="mt-0.5"><Select label="Name column" value={String(cols.name)} onChange={(v) => setCols({ ...cols, name: +v })} options={sheet.headers.map((h, i) => ({ value: String(i), label: h || `Column ${i + 1}` }))} /></div></div>
                    <div className="text-[11px] text-muted">Phone column<div className="mt-0.5"><Select label="Phone column" value={String(cols.phone)} onChange={(v) => setCols({ ...cols, phone: +v })} options={sheet.headers.map((h, i) => ({ value: String(i), label: h || `Column ${i + 1}` }))} /></div></div>
                  </div>
                  <div className="overflow-x-auto rounded-lg border border-line">
                    <table className="w-full text-[12px]"><thead><tr>{sheet.headers.map((h, i) => <th key={i} className={`border-b border-line bg-panel2 px-2 py-1 text-left font-medium ${i === cols.name || i === cols.phone ? "text-accent" : "text-muted"}`}>{h || "—"}</th>)}</tr></thead>
                      <tbody>{sheet.rows.slice(0, 4).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="border-b border-line/60 px-2 py-1 text-muted">{v}</td>)}</tr>)}</tbody></table>
                    {sheet.rows.length > 4 && <div className="px-2 py-1 text-[11px] text-muted">… {sheet.rows.length - 4} more rows</div>}
                  </div>
                  <button onClick={buildRows} disabled={!tmpl || excelBlocked || previewing} className="rounded-lg border border-line px-3 py-1.5 text-[12.5px] hover:bg-panel2 disabled:opacity-40">{previewing ? "Checking…" : "Preview recipients"}</button>
                  {preview && parsed && (
                    <div className="rounded-lg border border-line bg-panel2 p-3 text-[12.5px]">
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                        <div>Matched <b className="tabular-nums">{preview.matched}</b></div>
                        <div className="text-emerald-600">Sendable <b className="tabular-nums">{preview.sendable}</b></div>
                        <div className="text-amber-600">Skipped <b className="tabular-nums">{preview.skipped}</b></div>
                        {preview.cooldown_skipped > 0 && <div className="text-amber-600">Already sent in last {preview.cooldown_days} days <b className="tabular-nums">{preview.cooldown_skipped}</b></div>}
                        <div className="text-muted">Duplicates skipped {preview.duplicates}</div>
                        <div className="text-muted">Invalid numbers {parsed.invalid}</div>
                      </div>
                      {preview.over_hard_cap && <div className="mt-2 text-red-500">Over the hard cap of {preview.hard_cap} recipients — split the list.</div>}
                      {preview.requires_confirmation && !preview.over_hard_cap && <div className="mt-2 text-amber-600">More than {preview.confirm_threshold} recipients — you'll be asked to confirm.</div>}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line px-4 py-3">
          {tab === "excel" && preview?.requires_confirmation && !preview.over_hard_cap && <label className="mr-auto flex items-center gap-2 text-[12px] text-muted"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> I confirm sending to {preview.sendable} people</label>}
          <button onClick={store.closeTemplateSend} className="rounded-lg border border-line px-3 py-1.5 text-[13px] text-muted hover:text-ink">Cancel</button>
          {tab === "people"
            ? <button disabled={!ready || sending} onClick={sendPeople} className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg disabled:opacity-40"><Icon name="send" size={14} /> Send to {recips.length || ""}</button>
            : <button disabled={!tmpl || !preview || preview.sendable === 0 || preview.over_hard_cap || (preview.requires_confirmation && !confirm) || sending} onClick={sendExcel} className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-fg disabled:opacity-40"><Icon name="megaphone" size={14} /> Start broadcast{preview ? ` (${preview.sendable})` : ""}</button>}
        </div>
      </div>
    </div>
  );
}
