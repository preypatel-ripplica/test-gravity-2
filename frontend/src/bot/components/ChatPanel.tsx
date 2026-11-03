import { useEffect, useMemo, useRef, useState } from "react";
import type { Conversation, MessageRecord, Note } from "../types";
import { useStore, isWithinWindow, remainingMs } from "../store";
import { Avatar, Icon, clockTime, dayKey, dayLabel, displayName, fullDate } from "../lib/ui";
import Ticks from "./Ticks";
import Lightbox from "./Lightbox";
import VoiceMessage, { mmss } from "./VoiceMessage";

const PAGE = 30;

// ---------- pieces ----------

function StatusPill({ c }: { c: Conversation }) {
  const cls = c.status === "expired" ? "bg-red-500/15 text-red-500" : c.status === "resolved" ? "bg-muted/15 text-muted" : c.bot_paused ? "bg-amber-500/15 text-amber-500" : "bg-emerald-500/15 text-emerald-500";
  const label = c.status === "expired" ? "expired" : c.status === "resolved" ? `resolved${c.resolved_by ? ` · ${c.resolved_by}` : ""}` : c.bot_paused ? "agent" : "open · bot";
  return <span className={`rounded-full px-2 py-[1px] text-[10.5px] font-medium ${cls}`}>{label}</span>;
}

function senderLabel(m: MessageRecord): { text: string; cls: string } {
  const sb = m.metadata.sent_by;
  if (m.message_type === "template" || m.metadata.template) return { text: `📋 Template${m.metadata.template?.name ? ` · ${m.metadata.template.name}` : ""}${sb === "broadcast" ? " · 📣 broadcast" : ""}`, cls: "text-amber-500" };
  if (sb === "agent") return { text: "Agent", cls: "text-emerald-600" };
  if (sb === "inactivity_timeout") return { text: "⏱ Timeout", cls: "text-muted" };
  if (sb === "broadcast") return { text: "📣 Broadcast", cls: "text-amber-500" };
  return { text: "Bot", cls: "text-emerald-600/80" };
}

function QuotedReply({ quoted, contact }: { quoted: MessageRecord; contact: string }) {
  const who = quoted.direction === "incoming" ? contact : quoted.metadata.sent_by === "agent" ? "Agent" : "Bot";
  return (
    <div className="mb-1 rounded-md border-l-[3px] border-emerald-500 bg-black/10 px-2 py-1 text-[11.5px]">
      <div className="font-medium text-emerald-600">{who}</div>
      <div className="line-clamp-2 text-muted">{quoted.metadata.reply_title ?? quoted.text ?? (quoted.metadata.media ? `${quoted.metadata.media.type}` : "")}</div>
    </div>
  );
}

function InteractivePreview({ m }: { m: MessageRecord }) {
  if (m.message_type === "interactive_buttons" && m.metadata.options?.length)
    return (
      <div className="mt-1.5 divide-y divide-line/60 overflow-hidden rounded-lg border border-line/60">
        {m.metadata.options.map((o, i) => <div key={i} className="px-2 py-1.5 text-center text-[12.5px] font-medium text-sky-500">{o.label}</div>)}
      </div>
    );
  if (m.message_type === "interactive_list" && m.metadata.list_config)
    return (
      <div className="mt-1.5 rounded-lg border border-line/60 px-2 py-1.5 text-[12px]">
        <div className="mb-1 text-center font-medium text-sky-500">≡ {m.metadata.list_config.button_text ?? "Choose option"}</div>
        {m.metadata.list_config.sections.map((s, i) => (
          <div key={i} className="mt-1">
            <div className="text-[10px] uppercase tracking-wide text-muted">{s.title}</div>
            {s.rows.map((r, j) => <div key={j} className="text-muted">• {r.label}</div>)}
          </div>
        ))}
      </div>
    );
  return null;
}

function MediaAttachment({ m, onOpen }: { m: MessageRecord; onOpen: (src: string, name?: string, caption?: string) => void }) {
  const media = m.metadata.media;
  if (!media) return null;
  if (media.error) return <div className="rounded bg-black/10 px-2 py-1 text-[11.5px] text-muted">⚠️ media unavailable</div>;
  if (media.type === "audio") return <VoiceMessage src={media.src ?? ""} seed={m.id} voice={media.voice} duration={media.duration} />;
  if (media.type === "image")
    return (
      <button onClick={() => onOpen(media.src ?? "", media.filename, media.caption)} className="block overflow-hidden rounded-lg">
        <img src={media.src} alt={media.caption ?? media.filename ?? "image"} loading="lazy" className="max-h-64 w-auto rounded-lg" />
        {media.caption && <div className="px-1 pt-1 text-left text-[12.5px]">{media.caption}</div>}
      </button>
    );
  return <a href={media.src ?? "#"} target="_blank" rel="noopener" className="flex items-center gap-2 rounded-lg bg-black/10 px-2.5 py-2 text-[12.5px]"><Icon name="doc" size={16} /> {media.filename ?? "Document"}</a>;
}

function StatusAudit({ m }: { m: MessageRecord }) {
  const [open, setOpen] = useState(false);
  const hist = m.metadata.status_history ?? [];
  return (
    <span className="relative">
      <button onClick={() => setOpen((v) => !v)} className="align-middle"><Ticks status={m.status} error={m.metadata.send_error} /></button>
      {open && (
        <div className="absolute bottom-5 right-0 z-20 w-56 rounded-lg border border-line bg-panel p-2 text-left text-[11px] shadow-xl" onMouseLeave={() => setOpen(false)}>
          <div className="mb-1 font-semibold text-ink">Delivery</div>
          {hist.length === 0 && <div className="text-muted">{m.status === "failed" ? m.metadata.send_error ?? "Failed" : "Pending"}</div>}
          {hist.map((h, i) => <div key={i} className="flex justify-between text-muted"><span className="capitalize">{h.status}</span><span>{clockTime(h.received_at)}</span></div>)}
          {m.metadata.send_error && <div className="mt-1 text-red-500">{m.metadata.send_error}</div>}
        </div>
      )}
    </span>
  );
}

type Item = { kind: "msg"; at: string; m: MessageRecord } | { kind: "note"; at: string; n: Note };

// ---------- panel ----------

export default function ChatPanel({ conversation: c, onBack, onOpenProperties, propertiesOpen }: { conversation: Conversation; onBack: () => void; onOpenProperties: () => void; propertiesOpen: boolean }) {
  const store = useStore();
  const all = store.messagesFor(c.id);
  const notes = store.notesFor(c.id);
  const [pageCount, setPageCount] = useState(1);
  const [menu, setMenu] = useState(false);
  const [mode, setMode] = useState<"message" | "note">("message");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [lightbox, setLightbox] = useState<{ src: string; name?: string; caption?: string } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<number | null>(null);

  // recording
  const [recording, setRecording] = useState(false);
  const [recSecs, setRecSecs] = useState(0);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recTimer = useRef<number | null>(null);
  const cancelRef = useRef(false);
  const canRecord = store.features.voiceNotes && typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && "MediaRecorder" in window;

  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 30_000); return () => window.clearInterval(t); }, []);
  useEffect(() => { store.ensureMessages(c.id); store.ensureNotes(c.id); store.markViewed(c.id); store.setOpenConversation(c.id); setPageCount(1); setDraft(""); setError(null); setMenu(false); return () => store.setOpenConversation(null); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [c.id]);
  // Left-edge swipe-to-go-back for installed iOS apps, which have no OS back
  // gesture. Passive (no preventDefault) so scrolling and audio seeking are unaffected.
  const swipeStart = useRef<{ x: number; y: number } | null>(null);
  const onSwipeStart = (e: React.TouchEvent) => { const t = e.touches[0]; swipeStart.current = t && t.clientX <= 24 ? { x: t.clientX, y: t.clientY } : null; };
  const onSwipeEnd = (e: React.TouchEvent) => {
    const start = swipeStart.current; swipeStart.current = null;
    const t = e.changedTouches[0];
    if (!start || !t || !onBack) return;
    const dx = t.clientX - start.x, dy = t.clientY - start.y;
    if (dx > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) onBack();
  };
  const loadingOlder = useRef(false);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const items = useMemo<Item[]>(() => {
    const merged: Item[] = [...all.map((m) => ({ kind: "msg" as const, at: m.created_at, m })), ...notes.map((n) => ({ kind: "note" as const, at: n.at, n }))];
    merged.sort((a, b) => (a.at < b.at ? -1 : 1));
    return merged;
  }, [all, notes]);
  const visible = store.remote ? items : items.slice(Math.max(0, items.length - PAGE * pageCount));
  const hasMore = store.remote ? store.hasMoreMessages(c.id) : visible.length < items.length;
  const byWamid = useMemo(() => new Map(all.filter((m) => m.metadata.meta_message_id).map((m) => [m.metadata.meta_message_id!, m])), [all]);

  // auto-scroll to bottom on open / new message if near bottom; keep anchor on load-older
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (anchorRef.current !== null) { el.scrollTop = el.scrollHeight - anchorRef.current; anchorRef.current = null; return; }
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    if (near || items.length <= PAGE) el.scrollTop = el.scrollHeight;
  }, [items.length, pageCount]);
  useEffect(() => { const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight; }, [c.id]);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el || !hasMore || el.scrollTop >= 80) return;
    anchorRef.current = el.scrollHeight;
    if (!store.remote) { setPageCount((p) => p + 1); return; }
    if (loadingOlder.current) return;
    loadingOlder.current = true;
    store.loadOlderMessages(c.id).catch((e) => setError((e as Error).message)).finally(() => { loadingOlder.current = false; });
  };

  const resolved = c.status === "resolved";
  const windowOpen = isWithinWindow(c, now);
  const remaining = remainingMs(c, now);
  const canReply = !resolved && windowOpen;
  const fmtRemaining = (ms: number) => { const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000); return h > 0 ? `${h}h ${m}m` : `${m}m`; };

  const [sending, setSending] = useState(false);
  const send = async () => {
    const t = draft.trim();
    if (!t || sending) return;
    setError(null);
    try {
      if (mode === "note") { store.addNote(c.id, t); setDraft(""); return; }
      setSending(true);
      await store.sendAgentMessage(c.id, t);
      setDraft("");
    } catch (e) { setError((e as Error).message); }
    finally { setSending(false); }
  };

  async function startRecording() {
    if (!canReply || !canRecord) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "audio/mp4";
      const rec = new MediaRecorder(stream, { mimeType: mime });
      chunksRef.current = []; cancelRef.current = false;
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        if (recTimer.current) window.clearInterval(recTimer.current);
        const secs = recSecsRef.current;
        setRecording(false); setRecSecs(0);
        if (cancelRef.current || !chunksRef.current.length) return;
        const blob = new Blob(chunksRef.current, { type: mime });
        store.sendAgentAudio(c.id, blob, secs).catch((e) => setError((e as Error).message));
      };
      recRef.current = rec; rec.start(250);
      setRecording(true); setRecSecs(0); recSecsRef.current = 0;
      recTimer.current = window.setInterval(() => { recSecsRef.current += 1; setRecSecs(recSecsRef.current); }, 1000);
    } catch { setError("Microphone permission denied"); }
  }
  const recSecsRef = useRef(0);
  const stopRecording = (cancel: boolean) => { cancelRef.current = cancel; recRef.current?.stop(); };

  const contact = displayName(c.contact_name, c.contact_phone);
  let lastDay = "";

  return (
    <div className="relative flex h-full min-h-0 flex-col" onTouchStart={onSwipeStart} onTouchEnd={onSwipeEnd}>
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-line bg-panel px-3 py-2">
        <button onClick={onBack} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink md:hidden"><Icon name="back" size={16} /></button>
        <button onClick={onOpenProperties} title="Contact details" className="flex min-w-0 items-center gap-2 rounded-lg px-1 py-0.5 text-left hover:bg-panel2">
          <Avatar name={contact} size={30} />
          <div className="min-w-0">
            <div className="flex items-center gap-2"><span className="truncate text-[14px] font-semibold">{contact}</span><StatusPill c={c} /></div>
            <div className="text-[11px] text-muted tabular-nums">+{c.contact_phone}</div>
          </div>
        </button>
        <div className="ml-auto flex items-center gap-1.5">
          {!store.remote && <button onClick={() => store.simulateIncoming(c.id)} title="Demo: simulate an incoming customer message" className="hidden rounded-lg border border-dashed border-line px-2 py-1 text-[11px] text-muted hover:text-ink lg:block">⚡ simulate reply</button>}
          <a href={`tel:+${c.contact_phone}`} title="Call" className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink md:hidden"><Icon name="phone" size={16} /></a>
          <button onClick={onOpenProperties} title="Properties" className={`hidden items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] md:flex ${propertiesOpen ? "border-accent bg-accent/15 text-ink" : "border-line text-muted hover:bg-panel2"}`}>
            <Icon name="info" size={14} /><span className="hidden sm:inline">Properties</span>
          </button>
          <div className="relative" ref={menuRef}>
            <button onClick={() => setMenu((v) => !v)} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name="more" size={16} /></button>
            {menu && (
              <div className="absolute right-0 z-40 mt-1 w-56 overflow-hidden rounded-xl border border-line bg-panel py-1 text-[12.5px] shadow-2xl">
                <button disabled={resolved} onClick={() => { store.closeConversation(c.id); setMenu(false); }} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-panel2 disabled:opacity-40 disabled:hover:bg-transparent"><Icon name="check" size={14} /> Close / resolve chat</button>
                <button disabled={!resolved} onClick={() => { store.reopenConversation(c.id); setMenu(false); }} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-panel2 disabled:opacity-40 disabled:hover:bg-transparent"><Icon name="refresh" size={14} /> Re-open chat</button>
                <div className="my-1 border-t border-line" />
                <button onClick={() => { if (window.confirm("Delete this chat permanently? All its messages will be removed. This cannot be undone.")) { store.deleteConversation(c.id); onBack(); } setMenu(false); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-red-500 hover:bg-red-500/10"><Icon name="x" size={14} /> Delete chat</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Banners */}
      {c.bot_paused && !resolved && (
        <div className="border-b border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[12px] text-amber-600">
          👨‍💻 Agent is handling this chat — bot is paused. Close/resolve the chat (⋮ menu) to hand it back to the bot.
        </div>
      )}
      {!resolved && !windowOpen && (
        <div className="flex flex-wrap items-center gap-2 border-b border-red-500/30 bg-red-500/10 px-3 py-1.5 text-[12px] text-red-500">
          ⏳ The 24-hour messaging window has closed — the customer must message again before you can reply.
          {store.features.templates && <button onClick={() => store.openTemplateSend([c.contact_phone])} className="ml-auto rounded-md bg-red-500 px-2.5 py-1 text-[11.5px] font-medium text-white hover:bg-red-600">Send a template instead</button>}
        </div>
      )}

      {/* Thread */}
      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {hasMore && <div className="text-center text-[11px] text-muted">Loading earlier messages…</div>}
        {visible.map((it) => {
          const day = dayKey(it.at);
          const sep = day !== lastDay; lastDay = day;
          const separator = sep ? <div className="my-2 flex justify-center"><span className="rounded-full bg-panel2 px-2.5 py-0.5 text-[10.5px] text-muted">{dayLabel(it.at)}</span></div> : null;
          if (it.kind === "note")
            return (<div key={it.n.id}>{separator}<div className="mx-auto max-w-[80%] rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12.5px]"><div className="mb-0.5 text-[10.5px] font-medium text-amber-500">Internal note</div>{it.n.text}<div className="mt-0.5 text-[10px] text-muted">{clockTime(it.at)}</div></div></div>);
          const m = it.m; const out = m.direction === "outgoing";
          const quoted = m.metadata.reply_to_wamid ? byWamid.get(m.metadata.reply_to_wamid) : undefined;
          const label = out ? senderLabel(m) : null;
          return (
            <div key={m.id}>
              {separator}
              <div className={`flex ${out ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] rounded-2xl px-3 py-1.5 text-[13px] ${out ? "rounded-tr-sm bg-accent/20" : "rounded-tl-sm bg-panel2"}`}>
                  {label && <div className={`-mb-0.5 text-[10px] font-medium ${label.cls}`}>{label.text}</div>}
                  {quoted && <QuotedReply quoted={quoted} contact={contact} />}
                  <MediaAttachment m={m} onOpen={(src, name, caption) => setLightbox({ src, name, caption })} />
                  {(m.metadata.reply_title ?? m.text) && <div className="whitespace-pre-wrap break-words">{m.metadata.reply_title ?? m.text}</div>}
                  <InteractivePreview m={m} />
                  <div className="mt-0.5 flex items-center justify-end gap-1 text-[10px] text-muted">
                    <span title={fullDate(m.created_at)}>{clockTime(m.created_at)}</span>
                    {out && <StatusAudit m={m} />}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
        {items.length === 0 && <div className="py-10 text-center text-[12.5px] text-muted">No messages yet</div>}
      </div>

      {/* Composer */}
      <div className="border-t border-line bg-panel p-3">
        {resolved && <div className="mb-2 text-[11.5px] text-muted">This chat is resolved — re-open it from the ⋮ menu to reply.</div>}
        {canReply && remaining < 3600_000 && <div className="mb-2 rounded-md bg-amber-500/10 px-2 py-1 text-[11.5px] text-amber-600">⏳ Messaging window closes in {fmtRemaining(remaining)}</div>}
        {error && <div className="mb-2 text-[11.5px] text-red-500">Send failed: {error}</div>}
        <div className="mb-2 flex gap-1">
          {(store.features.notes ? (["message", "note"] as const) : (["message"] as const)).map((mm) => <button key={mm} onClick={() => setMode(mm)} className={`rounded-md px-2.5 py-1 text-[12px] ${mode === mm ? "bg-accent/15 text-ink" : "text-muted hover:text-ink"}`}>{mm === "message" ? "Reply" : "Internal note"}</button>)}
          {store.features.templates && <button onClick={() => store.openTemplateSend([c.contact_phone])} className="ml-auto flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] text-muted hover:text-ink"><Icon name="doc" size={13} /> Template</button>}
        </div>
        {recording ? (
          <div className="flex items-center gap-3 rounded-lg border border-line bg-panel2 px-3 py-2">
            <button onClick={() => stopRecording(true)} className="text-muted hover:text-ink"><Icon name="x" size={16} /></button>
            <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" />
            <span className="text-[13px] tabular-nums">{mmss(recSecs)}</span>
            <span className="text-[12px] text-muted">Recording…</span>
            <button onClick={() => stopRecording(false)} className="ml-auto grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg"><Icon name="send" size={16} /></button>
          </div>
        ) : (
          <div className="flex items-end gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              rows={1}
              disabled={mode === "message" && !canReply}
              placeholder={mode === "note" ? "Add an internal note…" : resolved ? "Chat is resolved" : !windowOpen ? "24-hour messaging window closed" : "Reply to patient…"}
              className="flex-1 resize-none rounded-lg border border-line bg-panel2 px-3 py-2 text-[13px] outline-none focus:border-accent/50 disabled:opacity-50"
            />
            {mode === "message" && !draft.trim() && canRecord ? (
              <button onClick={startRecording} disabled={!canReply} title="Record voice note" className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg disabled:opacity-40"><Icon name="mic" size={16} /></button>
            ) : (
              <button onClick={send} disabled={(mode === "message" && !canReply) || sending} className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg disabled:opacity-40"><Icon name="send" size={16} /></button>
            )}
          </div>
        )}
      </div>

      {lightbox && <Lightbox src={lightbox.src} filename={lightbox.name} caption={lightbox.caption} onClose={() => setLightbox(null)} />}
    </div>
  );
}
