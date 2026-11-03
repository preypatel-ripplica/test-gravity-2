import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type {
  Conversation, MessageRecord, MessageStatus, Note, Contact, Template, TemplateCategory, Broadcast,
  BroadcastRecipient, BroadcastPreview, WorkflowRun, NodeResponse, CrmFields, Lead, Density, Flow, CallReview,
  WhatsAppAccount, ClientSettings, AiUsage, CustomColumn, CustomColumnType, CustomValue, FieldDef,
  CallRecord,
} from "./types";
import { TEMPLATE_CATEGORIES } from "./types";
import { ACTIVE_FLOW } from "./data/flows";
import { makeSeed, ACCOUNT_ID, WABA_ID, type DB } from "./data/seed";
import { renderTemplateBody, countBodyVariables, componentsFrom, firstName } from "./lib/templates";
import { utcMs, isMobile } from "./lib/ui";
import { playNotificationTone, notify } from "./lib/sound";
import * as api from "./api";
import type { ConvView } from "./api";
import { resolveFeatures, grantedFeatures, clean as cleanFeatures, type Feature, type Features } from "./features";

/*
 * Single client-side store. Two modes, same `db` shape and action names:
 *  - remote (VITE_API_BASE_URL set): every action calls the backend endpoint
 *    it is named after, data loads over HTTP and stays fresh over SSE.
 *  - mock (no env): seed data + local simulations (ticks, broadcast drain…).
 */

/** True when the CRM is talking to a real backend. */
export const remote = api.enabled;

const LS = { db: "crm.db.v4", theme: "crm.theme.v2", density: "crm.density.v1", sidebar: "crm.sidebar.v1", cols: "crm.cols.v4", colsRemote: "crm.cols.remote.v1", sound: "crm.sound.v1", customcols: "crm.customcols.v1" };
type Theme = "dark" | "light";

export const SESSION_WINDOW_MS = 24 * 60 * 60 * 1000;
export const BROADCAST_CONFIRM_THRESHOLD = 200;
export const BROADCAST_HARD_CAP = 5000;

/** Toggleable Leads-table columns (Time/Patient/Phone/Disposition are permanent). */
export const CORE_COLUMNS = [
  { key: "source", label: "Source" },
  { key: "status", label: "Chat status" },
  { key: "lastActivity", label: "Last activity" },
];
// First few substantive fields: ids, the language choice and file uploads make
// poor default columns (JPC: Pain · Appointment Type · Able To Visit · Consult Mode).
export const defaultColumns = (fields: FieldDef[] = ACTIVE_FLOW.fields, phone = false): string[] =>
  ["source", ...fields.filter((f) => !/^(lead_id|language)$/i.test(f.key) && f.type !== "media").slice(0, phone ? 3 : 4).map((f) => f.key), "lastActivity"];
/** Column sets are shared per client: one for every desktop, one for every phone. */
type ColumnView = { desktop: string[]; phone: string[] };
const DEVICE: keyof ColumnView = typeof window !== "undefined" && isMobile() ? "phone" : "desktop";

const uid = (p: string) => `${p}:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
const nowIso = () => new Date().toISOString();
const DEFAULT_CRM: CrmFields = { disposition: "", call_tried: 0, remark: "", custom: {} };
/** Old persisted crm objects may lack the newer fields. */
const normCrm = (c?: Partial<CrmFields>): CrmFields => ({ ...DEFAULT_CRM, ...(c ?? {}), custom: { ...(c?.custom ?? {}) } });

export const isWithinWindow = (c: Conversation, now = Date.now()) => !!c.last_inbound_at && utcMs(c.last_inbound_at) + SESSION_WINDOW_MS > now;
export const remainingMs = (c: Conversation, now = Date.now()) => (c.last_inbound_at ? utcMs(c.last_inbound_at) + SESSION_WINDOW_MS - now : 0);
export const WINDOW_CLOSED_ERROR = "The 24-hour messaging window has closed. The customer must send a new message before you can reply.";

function loadJSON<T>(key: string, fallback: () => T): T {
  try { const raw = localStorage.getItem(key); if (raw) return JSON.parse(raw) as T; } catch { /* fall back */ }
  return fallback();
}
const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

// --------------------------------------------------------------------------- //
// Backend payload → store shapes (remote mode)
// --------------------------------------------------------------------------- //
type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
interface FeedItem { key: string; convId: string; runId: string | null; arrivedAt: string }
interface FeedState { items: FeedItem[]; total: number; offset: number; loading: boolean; ready: boolean; q: string; source: string }
export interface LeadFeedInfo { total: number; loaded: number; loading: boolean; ready: boolean; hasMore: boolean; q: string; source: string }
const LEADS_PAGE = 100;
const emptyFeed = (): FeedState => ({ items: [], total: 0, offset: 0, loading: false, ready: !remote, q: "", source: "" });
const feedItem = (l: api.LeadRow): FeedItem => ({ key: l.key, convId: l.conversation.id, runId: (l.run?.id as string | undefined) ?? null, arrivedAt: l.arrived_at });

const HIDDEN_VARS = new Set(["sheet_insert", "http_status", "contact"]);
/** Run variables as the Leads table wants them: scalars only, internals hidden, report → its url. */
function flattenVars(v: Raw | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, val] of Object.entries(v ?? {})) {
    if (k.startsWith("_") || HIDDEN_VARS.has(k)) continue;
    if (val === null || val === undefined) { out[k] = ""; continue; }
    if (typeof val === "object") {
      if (!Array.isArray(val) && typeof val.url === "string") out[k] = val.url;
      continue;
    }
    out[k] = String(val);
  }
  return out;
}
const mapConv = (c: Raw): Conversation => ({ ...(c as Conversation), awaiting_template_reply: !!c.awaiting_template_reply, contact_name: c.contact_name ?? null, tags: Array.isArray(c.tags) ? c.tags : [], attributes: c.attributes ?? {}, active_workflow_run_id: c.active_workflow_run_id ?? null, unread_count: Number(c.unread_count ?? 0) || 0 });
const crmFrom = (c: Raw): CrmFields => normCrm({ disposition: (c.disposition ?? "") as CrmFields["disposition"], call_tried: Number(c.crm?.call_tried ?? 0) || 0, remark: c.disposition_remark ?? c.crm?.remark ?? "", custom: c.crm?.custom ?? {} });
const mapNote = (n: Raw): Note => ({ id: n.id, conversation_id: n.conversation_id, text: n.text ?? "", at: n.created_at ?? n.at ?? nowIso() });
function mapTemplate(t: Raw): Template {
  const st = String(t.status ?? "PENDING").toUpperCase();
  const status: Template["status"] = st === "APPROVED" ? "APPROVED" : st === "PENDING" || st === "IN_APPEAL" ? "PENDING" : "REJECTED";
  const cat = String(t.category ?? "UTILITY").toUpperCase() as TemplateCategory;
  const components = Array.isArray(t.components) ? t.components : [];
  return {
    id: t.id, whatsapp_account_id: t.whatsapp_account_id, waba_id: t.waba_id ?? "", name: t.name, language: t.language ?? "en",
    category: (TEMPLATE_CATEGORIES as readonly string[]).includes(cat) ? cat : "UTILITY", components,
    body_variable_count: typeof t.body_variable_count === "number" ? t.body_variable_count : countBodyVariables(components),
    status, meta_template_id: t.meta_template_id ?? null, rejected_reason: t.rejected_reason ?? (status === "REJECTED" && st !== "REJECTED" ? st : null), created_at: t.created_at ?? nowIso(),
  };
}
const zeroCounts = () => ({ total: 0, pending: 0, sent: 0, delivered: 0, read: 0, failed: 0, skipped: 0 });
/** Counters the way the backend keeps them: `sent` = everything that went out, delivered/read are subsets. */
const countsOf = (recs: BroadcastRecipient[]) => {
  const c = zeroCounts(); c.total = recs.length;
  for (const r of recs) {
    if (r.status === "pending" || r.status === "sending") c.pending++;
    else if (r.status === "failed") c.failed++;
    else if (r.status === "skipped") c.skipped++;
    else { c.sent++; if (r.status !== "sent") c.delivered++; if (r.status === "read") c.read++; }
  }
  return c;
};
const mapBroadcast = (b: Raw): Broadcast => ({
  id: b.id, whatsapp_account_id: b.whatsapp_account_id, name: b.name ?? b.template_name, template_name: b.template_name, template_language: b.template_language ?? "en",
  variable_mapping: b.variable_mapping ?? {}, audience: { type: b.audience?.type ?? "phones", tag: b.audience?.tag, count: b.audience?.phones?.length ?? b.counts?.total },
  status: b.status ?? "queued", counts: { ...zeroCounts(), ...(b.counts ?? {}) }, created_at: b.created_at ?? nowIso(), started_at: b.started_at ?? null, completed_at: b.completed_at ?? null,
});
const mapRecipient = (r: Raw, nameByPhone: Map<string, string | null>): BroadcastRecipient => ({
  id: r.id, broadcast_id: r.broadcast_id, contact_phone: r.contact_phone, contact_name: r.contact_name ?? nameByPhone.get(r.contact_phone) ?? null,
  params: Array.isArray(r.params) ? r.params : [], status: r.status ?? "pending", meta_message_id: r.meta_message_id ?? null, error: r.error ?? null, sent_at: r.sent_at ?? null,
});
const mapContact = (c: Raw): Contact => ({ id: c.id, whatsapp_account_id: c.whatsapp_account_id, phone: c.phone, name: c.name ?? null, source: c.source ?? "import", opted_out: !!c.opted_out, marketing_opt_in: !!c.marketing_opt_in, tags: Array.isArray(c.tags) ? c.tags : [], last_inbound_at: c.last_inbound_at ?? null, created_at: c.created_at ?? nowIso() });
const mapRun = (r: Raw): WorkflowRun => ({ id: r.id, whatsapp_account_id: r.whatsapp_account_id, workflow_id: r.workflow_id, contact_phone: r.contact_phone, status: r.status, variables: flattenVars(r.variables), crm_pushed_at: r.crm_pushed_at ?? null, crm_push_result: r.crm_push_result ?? null, token_usage: r.token_usage ?? null, started_at: r.started_at ?? r.created_at ?? nowIso(), completed_at: r.completed_at ?? null });
const mapNodeResponse = (n: Raw, i: number): NodeResponse => ({ id: n.id ?? `${n.workflow_run_id}:${i}`, workflow_run_id: n.workflow_run_id, variable_name: n.variable_name ?? "", question: n.question ?? "", response: n.response ?? "", at: n.created_at ?? n.at ?? "" });
const emptyAccount = (): WhatsAppAccount => ({ id: "", name: "", phone_number_id: "", display_phone_number: "", whatsapp_business_account_id: "", verified_name: null, quality_rating: "UNKNOWN", status: "disconnected", inactivity_timeout_enabled: true, inactivity_timeout_minutes: 15, inactivity_timeout_message: "" });
const mapAccount = (a: Raw): WhatsAppAccount => ({ ...emptyAccount(), ...a, display_phone_number: a.display_phone_number ?? "", whatsapp_business_account_id: a.whatsapp_business_account_id ?? "", verified_name: a.verified_name ?? null, quality_rating: (["GREEN", "YELLOW", "RED"].includes(a.quality_rating) ? a.quality_rating : "UNKNOWN") });
const mapClient = (c: Raw): ClientSettings => ({
  id: c.id, name: c.name ?? "Client", username: c.username ?? "",
  crm_push: c.crm_push ? { enabled: !!c.crm_push.enabled, url: c.crm_push.url ?? "", method: c.crm_push.method ?? "POST", fire_on: c.crm_push.fire_on ?? [] } : null,
  disposition_sync: c.disposition_sync ? { enabled: !!c.disposition_sync.enabled, sheet_name: c.disposition_sync.sheet_name ?? "", lookback_hours: c.disposition_sync.lookback_hours ?? 6 } : null,
  users: Array.isArray(c.users) ? c.users : [], crm_columns: Array.isArray(c.crm_columns) ? (c.crm_columns as CustomColumn[]) : [],
  feature_prefs: c.feature_prefs && typeof c.feature_prefs === "object" ? (c.feature_prefs as Record<string, boolean>) : {},
  crm_view: c.crm_view && typeof c.crm_view === "object" ? (c.crm_view as ClientSettings["crm_view"]) : {},
  call_recording: { agent_names: Array.isArray(c.call_recording?.agent_names) ? (c.call_recording.agent_names as string[]) : [] },
});
const emptyUsage = (): AiUsage => ({ current_month: null, months: [], totals: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, turns: 0, cost_usd: 0 } });
const mapUsage = (u: Raw): AiUsage => ({ ...emptyUsage(), ...u, months: Array.isArray(u.months) ? u.months : [] });
const mapSchema = (s: { workflow_id: string | null; fields: api.SchemaField[] }, name: string): Flow => ({
  id: s.workflow_id ?? "remote", name,
  fields: (s.fields ?? []).map((f) => ({ key: f.key, label: f.label || f.key, type: f.type === "enum" ? "enum" : f.type === "date" ? "date" : f.type === "media" ? "media" : "text", ...(f.type === "enum" && f.options?.length ? { options: f.options } : {}) })),
});
const emptyDb = (): DB => ({ conversations: [], messages: {}, notes: {}, crm: {}, contacts: [], templates: [], broadcasts: [], recipients: {}, runs: [], calls: [], nodeResponses: {}, account: emptyAccount(), client: { id: "", name: "Ripplica", username: "", crm_push: null, disposition_sync: null, users: [] }, usage: emptyUsage() });
const byTime = <T extends { created_at: string }>(a: T, b: T) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0);

// --------------------------------------------------------------------------- //

interface Store {
  /** Which parts of the app this client is allowed to see. */
  features: Features;
  /** The clinic's own choice, saved on the client record. Can only hide what Ripplica granted. */
  setFeature: (key: Feature, on: boolean) => void;
  /** Ripplica's grant: the switches Settings may show at all. */
  granted: Features;
  featurePrefs: Partial<Features>;
  /** Talking to a real backend (VITE_API_BASE_URL set)? */
  remote: boolean;
  authed: boolean;
  loading: boolean;
  apiDown: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  flow: Flow;
  account: WhatsAppAccount;
  client: ClientSettings;
  usage: AiUsage;
  // data
  conversations: Conversation[];
  leads: Lead[];
  contacts: Contact[];
  templates: Template[];
  broadcasts: Broadcast[];
  runs: WorkflowRun[];
  messagesFor: (convId: string) => MessageRecord[];
  notesFor: (convId: string) => Note[];
  recipientsFor: (broadcastId: string) => BroadcastRecipient[];
  responsesFor: (runId: string) => NodeResponse[];
  leadFor: (convId: string) => Lead | undefined;
  conversationByPhone: (phone: string) => Conversation | undefined;
  // lazy loads (no-ops in mock mode)
  ensureMessages: (convId: string) => void;
  loadOlderMessages: (convId: string) => Promise<void>;
  hasMoreMessages: (convId: string) => boolean;
  ensureNotes: (convId: string) => void;
  ensureRunDetail: (runId: string) => void;
  /** Desktop pages pull their own data on first visit; a phone never asks for it. */
  ensureTemplates: () => void;
  ensureBroadcasts: () => void;
  ensureContacts: () => void;
  ensureRuns: () => void;
  ensureUsage: () => void;
  /** Leads feed: one row per arrival, newest first, pulled from the server 100 at a time. */
  leadFeed: LeadFeedInfo;
  /** (Re)load page 1 of the feed, optionally with new name/phone + source filters. */
  loadLeads: (filters?: { q?: string; source?: string }) => Promise<void>;
  loadMoreLeads: () => Promise<void>;
  /** Only while the Leads page is on screen do live events refresh the feed. */
  setLeadsWatched: (on: boolean) => void;
  /** One contact's runs, so the properties panel works without preloading every run. */
  ensureRunForConversation: (phone: string) => void;
  /** The inbox boots with one page and pulls more as the list is scrolled.
   * Each tab pages independently: All/Unread use "inbox", Template msg. uses "template". */
  loadMoreConversations: (view?: ConvView) => Promise<void>;
  hasMoreConversations: (view?: ConvView) => boolean;
  /** Server-side totals per tab, so a badge is right before the tab is paged. */
  convCounts: { inbox: number; template: number };
  /** Tells the store which tab is on screen (loads it on first open). */
  setConversationView: (view: ConvView) => void;
  refreshBroadcast: (id: string) => Promise<void>;
  refreshTemplates: () => Promise<void>;
  syncTemplates: () => Promise<void>;
  // conversations (→ /conversations/*)
  markViewed: (id: string) => void;
  /** Which chat is on screen (null when none); drives instant read receipts. */
  setOpenConversation: (id: string | null) => void;
  closeConversation: (id: string) => void;
  reopenConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  updateContact: (id: string, patch: { contact_name?: string; tags?: string[]; attributes?: Record<string, string> }) => void;
  setCrm: (id: string, patch: Partial<CrmFields>) => void;
  /** FasterQ calls for this client (loaded on the Calls page). */
  calls: CallRecord[];
  ensureCalls: () => void;
  /** AI call reviews, keyed by the patient's phone. Loaded with the calls. */
  callReviews: Record<string, CallReview>;
  /** Queue a review for one patient; the result arrives over SSE. */
  startCallReview: (phone: string) => void;
  /** Settings → Call recording: the FasterQ agent names that route calls to this clinic. */
  setCallAgents: (names: string[]) => Promise<void>;
  setRemark: (id: string, text: string) => void;
  setCustomValue: (id: string, key: string, value: CustomValue) => void;
  customColumns: CustomColumn[];
  addCustomColumn: (def: { label: string; type: CustomColumnType; options?: string[] }) => string;
  removeCustomColumn: (key: string) => void;
  addNote: (id: string, text: string) => void;
  // sending
  sendAgentMessage: (id: string, text: string) => Promise<void>;
  sendAgentAudio: (id: string, blob: Blob, duration: number) => Promise<void>;
  sendTemplate: (phone: string, name: string | null, template: Template, params: string[], sentBy?: "template" | "broadcast", broadcastId?: string) => Promise<string>;
  // templates (→ /whatsapp-accounts/{id}/templates)
  submitTemplate: (t: { name: string; category: TemplateCategory; language: string; body: string; footer?: string }) => Promise<void>;
  // contacts + broadcasts
  importContacts: (rows: { phone: string; name: string; tags?: string[] }[]) => Promise<{ added: number; updated: number }>;
  addContactTags: (id: string, tags: string[]) => void;
  previewBroadcast: (rows: { phone: string; name: string; params: string[] }[], template: Template) => Promise<BroadcastPreview>;
  createBroadcast: (name: string, template: Template, rows: { phone: string; name: string; params: string[] }[], confirm?: boolean) => Promise<string>;
  setBroadcastState: (id: string, action: "pause" | "resume" | "cancel") => void;
  updateAccount: (patch: Partial<WhatsAppAccount>) => void;
  // demo controls
  simulateIncoming: (id: string, text?: string) => void;
  reset: () => void;
  // ui
  visibleColumns: string[]; toggleColumn: (k: string) => void; clearColumns: () => void;
  density: Density; setDensity: (d: Density) => void;
  /** Desktop sidebar collapsed to an icon rail. */
  sidebarCollapsed: boolean; toggleSidebar: () => void;
  theme: Theme; toggleTheme: () => void;
  sound: boolean; toggleSound: () => void;
  selectMode: boolean; setSelectMode: (b: boolean) => void;
  selectedIds: string[]; toggleSelect: (id: string) => void; selectMany: (ids: string[]) => void; clearSelection: () => void;
  toast: string | null; setToast: (s: string | null) => void;
  /** Open the send-template modal for these conversation/contact phones (from inbox CTA / selection). */
  templateTarget: { phones: string[]; templateId?: string } | null;
  openTemplateSend: (phones: string[], templateId?: string) => void;
  closeTemplateSend: () => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [db, setDb] = useState<DB>(() => (remote ? emptyDb() : loadJSON(LS.db, makeSeed)));
  // Remote: hydrated from the client record at boot (shared across devices).
  // Demo: this browser only.
  const [view, setView] = useState<ColumnView>(() => (remote ? { desktop: [], phone: [] } : { desktop: loadJSON(LS.cols, () => defaultColumns()), phone: defaultColumns(undefined, true) }));
  const cols = view[DEVICE];
  const viewPatchTimer = useRef<number | null>(null);
  /** Change this device kind's set; persist to the client record (debounced). */
  const setCols = (fn: (v: string[]) => string[]) => setView((cur) => {
    const next = { ...cur, [DEVICE]: fn(cur[DEVICE]) };
    if (remote && dbRef.current.client.id) {
      if (viewPatchTimer.current) window.clearTimeout(viewPatchTimer.current);
      const id = dbRef.current.client.id, payload = { [DEVICE]: next[DEVICE] };
      viewPatchTimer.current = window.setTimeout(() => { api.patchClient(id, { crm_view: payload }).catch((e) => setToast(`Could not save columns: ${errMsg(e)}`)); }, 500);
    }
    return next;
  });
  const [customColumns, setCustomColumns] = useState<CustomColumn[]>(() => (remote ? [] : loadJSON(LS.customcols, () => [])));
  const [density, setDensityState] = useState<Density>(() => (localStorage.getItem(LS.density) as Density) || "cozy");
  // Default light to match bot.ripplica.com; user can still toggle. v2 key drops a
  // stuck "dark" from earlier Beacon mounts / OS prefers-color-scheme.
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem(LS.theme);
    return saved === "dark" || saved === "light" ? saved : "light";
  });
  const [sound, setSound] = useState<boolean>(() => localStorage.getItem(LS.sound) !== "0");
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => localStorage.getItem(LS.sidebar) === "1");
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [toast, setToastState] = useState<string | null>(null);
  const [templateTarget, setTemplateTarget] = useState<Store["templateTarget"]>(null);
  // remote-mode state
  const [authed, setAuthed] = useState<boolean>(() => remote && !!api.getToken());
  const [loading, setLoading] = useState<boolean>(remote);
  const [apiDown, setApiDown] = useState(false);
  const [schemaFlow, setSchemaFlow] = useState<Flow | null>(null);
  const [features, setFeatures] = useState<Features>(() => resolveFeatures());
  const clientFeaturesRef = useRef<unknown>(undefined);
  const [featurePrefs, setFeaturePrefs] = useState<Partial<Features>>({});
  const [msgMeta, setMsgMeta] = useState<Record<string, { hasMore: boolean }>>({});
  const loadingMsgs = useRef(new Set<string>());
  // The conversation the agent is looking at: inbound messages on it are marked
  // viewed straight away (customer sees blue ticks) instead of growing its badge.
  const openConvRef = useRef<string | null>(null);
  // Refetches the open thread after an SSE reconnect; bound once ensureMessages exists.
  const resyncOpen = useRef<() => void>(() => {});
  // once-only loaders keyed by what they fetched; cleared on (re)boot and logout
  const loadedSets = useRef(new Set<string>());
  // A page can mount before boot has the account id; its loader parks here and
  // runs the moment boot finishes instead of firing with an empty account.
  const booted = useRef(false);
  const parkedLoads = useRef(new Map<string, () => Promise<unknown>>());
  const [bootTick, setBootTick] = useState(0);
  const [feed, setFeed] = useState<FeedState>(emptyFeed);
  const [callReviews, setCallReviews] = useState<Record<string, CallReview>>({});
  const feedRef = useRef(feed); feedRef.current = feed;
  const feedReq = useRef(0);
  const leadsWatched = useRef(false);
  const leadsRefreshTimer = useRef<number | null>(null);
  const emptyCursor = () => ({ total: 0, loaded: 0 });
  const [convPaging, setConvPaging] = useState<Record<ConvView, { total: number; loaded: number }>>(
    { inbox: emptyCursor(), template: emptyCursor() });
  const convPagingRef = useRef(convPaging); convPagingRef.current = convPaging;
  // Per view: one shared guard would let a template fetch block an inbox fetch.
  const loadingMore = useRef<Record<ConvView, boolean>>({ inbox: false, template: false });
  const [convCounts, setConvCounts] = useState<api.ConvCounts>({ inbox: 0, template: 0 });
  // Which tab is on screen; only that one is refreshed alongside the inbox.
  const convWatched = useRef<ConvView>("inbox");
  // Bound once refreshTemplateView exists, the way resyncOpen is.
  const refreshTemplateRef = useRef<() => void>(() => {});
  const loadedNotes = useRef(new Set<string>());
  const loadedRuns = useRef(new Set<string>());
  const accountPatchTimer = useRef<number | null>(null);
  const accountPatchBuf = useRef<Partial<WhatsAppAccount>>({});
  const toastTimer = useRef<number | null>(null);
  const soundRef = useRef(sound); soundRef.current = sound;
  const dbRef = useRef(db); dbRef.current = db;

  useEffect(() => {
    // Scope theme to .bot-app only — Beacon owns :root --bg / body styles.
    document.querySelector(".bot-app")?.setAttribute("data-theme", theme);
    localStorage.setItem(LS.theme, theme);
  }, [theme]);
  useEffect(() => { if (remote) return; try { localStorage.setItem(LS.db, JSON.stringify(db)); } catch { /* quota */ } }, [db]);
  useEffect(() => { if (!remote) localStorage.setItem(LS.cols, JSON.stringify(view.desktop)); }, [view]);
  useEffect(() => { if (!remote) localStorage.setItem(LS.customcols, JSON.stringify(customColumns)); }, [customColumns]);
  useEffect(() => localStorage.setItem(LS.density, density), [density]);
  useEffect(() => localStorage.setItem(LS.sound, sound ? "1" : "0"), [sound]);
  useEffect(() => localStorage.setItem(LS.sidebar, sidebarCollapsed ? "1" : "0"), [sidebarCollapsed]);

  const setToast = (s: string | null) => {
    setToastState(s);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    if (s) toastTimer.current = window.setTimeout(() => setToastState(null), 3000);
  };

  // ---- helpers over db ----
  const patchConv = (id: string, fn: (c: Conversation) => Conversation) =>
    setDb((d) => ({ ...d, conversations: d.conversations.map((c) => (c.id === id ? fn(c) : c)) }));
  const patchMsg = (convId: string, msgId: string, fn: (m: MessageRecord) => MessageRecord) =>
    setDb((d) => ({ ...d, messages: { ...d.messages, [convId]: (d.messages[convId] ?? []).map((m) => (m.id === msgId ? fn(m) : m)) } }));
  /** Insert or replace a conversation from a backend payload (also refreshes its crm slice). */
  // A broadcast or a migration can push hundreds of conversation events, each
  // arriving as its own task so React cannot batch them. Buffer the rows and
  // apply them in one setDb; the per-row side effects below still run at once.
  const convBuf = useRef<Conversation[]>([]);
  const convFlush = useRef<number | null>(null);
  const queueConv = (c: Conversation) => {
    convBuf.current.push(c);
    if (convFlush.current !== null) return;
    convFlush.current = window.setTimeout(() => {
      convFlush.current = null;
      const batch = convBuf.current; convBuf.current = [];
      if (!batch.length) return;
      setDb((d) => {
        const byId = new Map(batch.map((x) => [x.id, x]));
        const conversations = d.conversations.map((x) => byId.get(x.id) ?? x);
        const seen = new Set(d.conversations.map((x) => x.id));
        const fresh = batch.filter((x) => !seen.has(x.id));
        return { ...d, conversations: fresh.length ? [...fresh, ...conversations] : conversations };
      });
    }, 60);
  };

  const upsertConv = useCallback((raw: Raw, notifyIncoming = false) => {
    let c = mapConv(raw);
    const prev = dbRef.current.conversations.find((x) => x.id === c.id);
    const onScreen = c.id === openConvRef.current && typeof document !== "undefined" && document.visibilityState === "visible";
    if (onScreen && c.unread_count > 0) {
      c = { ...c, unread_count: 0 };
      if (remote) api.markViewed(c.id).catch(() => { /* best effort */ });
    }
    // Keep the tab badges honest between polls: a reply moves the row out of
    // Template msg. instantly, so the number beside it must move too.
    const was = prev ? prev.awaiting_template_reply : null;
    if (was !== c.awaiting_template_reply) {
      setConvCounts((n) => ({
        inbox: Math.max(0, n.inbox + (c.awaiting_template_reply ? (was === false ? -1 : 0) : 1)),
        template: Math.max(0, n.template + (c.awaiting_template_reply ? 1 : (was ? -1 : 0))),
      }));
    }
    queueConv(c);
    setDb((d) => (d.crm[c.id] ? { ...d, crm: { ...d.crm, [c.id]: crmFrom(raw) } } : { ...d, crm: { ...d.crm, [c.id]: crmFrom(raw) } }));
    if (notifyIncoming && !onScreen && c.last_message_direction === "incoming" && c.unread_count > (prev?.unread_count ?? 0)) {
      if (soundRef.current) playNotificationTone();
      notify(c.contact_name ?? c.contact_phone, c.last_message_text ?? "New message");
    }
  }, []);
  const upsertMessage = useCallback((raw: Raw) => {
    const m = api.withMediaSrc(raw as MessageRecord);
    const conv = dbRef.current.conversations.find((c) => c.whatsapp_account_id === m.whatsapp_account_id && c.contact_phone === m.contact_phone);
    if (!conv) return;
    setDb((d) => {
      const cur = d.messages[conv.id];
      if (!cur) return d; // thread not opened yet; it loads fresh on open
      const next = cur.some((x) => x.id === m.id) ? cur.map((x) => (x.id === m.id ? { ...x, ...m } : x)) : [...cur, m].sort(byTime);
      return { ...d, messages: { ...d.messages, [conv.id]: next } };
    });
  }, []);
  const upsertNote = useCallback((raw: Raw) => {
    const n = mapNote(raw);
    setDb((d) => {
      const cur = d.notes[n.conversation_id] ?? [];
      if (cur.some((x) => x.id === n.id)) return d;
      return { ...d, notes: { ...d.notes, [n.conversation_id]: [...cur, n] } };
    });
  }, []);

  /** Simulate Meta's status webhook: created → sent → delivered → (read). Mock only. */
  const simulateTicks = (convId: string, msgId: string, fail = false) => {
    const step = (status: MessageStatus, delay: number) => window.setTimeout(() => {
      patchMsg(convId, msgId, (m) => ({ ...m, status, metadata: { ...m.metadata, status_history: [...(m.metadata.status_history ?? []), { status, received_at: nowIso(), previous_status: m.status }] } }));
    }, delay);
    if (fail) { step("failed", 900); return; }
    step("sent", 500); step("delivered", 1600);
    if (Math.random() < 0.7) step("read", 4000);
  };

  /** Mirrors storage.upsert_conversation_on_message for an outgoing message. */
  const appendOutgoing = (d: DB, conv: Conversation, m: MessageRecord, preview: string): DB => {
    const msgs = { ...d.messages, [conv.id]: [...(d.messages[conv.id] ?? []), m] };
    // A template does NOT reopen a closed window (the server stopped claiming
    // that too); it only marks the chat as awaiting a reply.
    const convs = d.conversations.map((c) => c.id === conv.id ? { ...c, awaiting_template_reply: m.message_type === "template" ? true : c.awaiting_template_reply, last_message_text: preview, last_message_at: m.created_at, last_message_direction: "outgoing" as const } : c);
    return { ...d, messages: msgs, conversations: convs };
  };

  // ---- remote: boot / refresh ----
  const reloadConversations = useCallback(async () => {
    const page = await api.listConversationsPage({ limit: 50, view: "inbox" });
    const raws = page.conversations;
    if (page.counts) setConvCounts(page.counts);
    // The template tab changes only when a template goes out or a reply lands,
    // and both already arrive over SSE — so refresh it only while it is on screen.
    if (convWatched.current === "template") refreshTemplateRef.current();
    setDb((d) => {
      const incoming = new Set(raws.map((c) => c.id));
      return {
        ...d,
        conversations: [...raws.map(mapConv), ...d.conversations.filter((c) => !incoming.has(c.id))],
        crm: { ...d.crm, ...Object.fromEntries(raws.map((c) => [c.id, crmFrom(c)])) },
      };
    });
    setConvPaging((p) => ({ ...p, inbox: { total: page.total, loaded: Math.max(p.inbox.loaded, raws.length) } }));
    setApiDown(false);
    return raws;
  }, []);
  const reloadContacts = useCallback(async (accountId: string) => {
    const cs = await api.listContacts(accountId);
    setDb((d) => ({ ...d, contacts: cs.map(mapContact) }));
  }, []);
  const loadAll = useCallback(async () => {
    setLoading(true);
    booted.current = false;
    try {
      const meRes = await api.me();
      const client = mapClient(meRes.client);
      clientFeaturesRef.current = (meRes.client as Raw).features;
      const prefs = cleanFeatures(client.feature_prefs);
      setFeaturePrefs(prefs);
      setFeatures(resolveFeatures(clientFeaturesRef.current, prefs));
      const accounts = await api.listAccounts(client.id);
      const account = accounts[0] ? mapAccount(accounts[0]) : emptyAccount();
      const aid = account.id;
      // Boot fetches only what the inbox paints: one page of conversations and
      // the lead schema (tiny; labels the properties panel). Templates, campaigns,
      // contacts, runs and usage load when — and only if — their page is opened,
      // so a phone, which only ever shows the inbox, never pays for them.
      const [page, schema] = await Promise.all([
        api.listConversationsPage({ limit: 50, view: "inbox" }),
        api.leadSchema().catch(() => ({ workflow_id: null, fields: [] as api.SchemaField[] })),
      ]);
      const convs = page.conversations;
      const flow = mapSchema(schema, client.name);
      setSchemaFlow(flow);
      setCustomColumns(client.crm_columns ?? []);
      setView({
        desktop: client.crm_view?.desktop?.length ? client.crm_view.desktop : defaultColumns(flow.fields),
        phone: client.crm_view?.phone?.length ? client.crm_view.phone : defaultColumns(flow.fields, true),
      });
      void aid;
      setDb((d) => ({
        ...d, account, client, usage: emptyUsage(),
        conversations: convs.map(mapConv), crm: Object.fromEntries(convs.map((c) => [c.id, crmFrom(c)])),
        templates: [], broadcasts: [], contacts: [], runs: [],
        messages: {}, notes: {}, recipients: {}, nodeResponses: {},
      }));
      setConvPaging({ inbox: { total: page.total, loaded: convs.length }, template: emptyCursor() });
      if (page.counts) setConvCounts(page.counts);
      loadingMsgs.current.clear(); loadedNotes.current.clear(); loadedRuns.current.clear(); loadedSets.current.clear(); setFeed(emptyFeed()); setCallReviews({});
      setMsgMeta({});
      setApiDown(false);
      booted.current = true;
      setBootTick((t) => t + 1);
    } catch (e) {
      if (!(e instanceof api.ApiError && e.status === 401)) { setApiDown(true); setToast(`Could not load data: ${errMsg(e)}`); }
    } finally { setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const logout = useCallback(() => {
    api.setToken(null);
    setAuthed(false);
    setDb(emptyDb());
    setSchemaFlow(null);
    setCustomColumns([]);
    loadedSets.current.clear(); parkedLoads.current.clear(); booted.current = false;
    setConvPaging({ inbox: emptyCursor(), template: emptyCursor() });
    setConvCounts({ inbox: 0, template: 0 });
    convWatched.current = "inbox";
    setFeed(emptyFeed());
    setCallReviews({});
  }, []);

  useEffect(() => {
    if (!remote) return;
    const onLogout = () => logout();
    window.addEventListener("crm:logout", onLogout);
    return () => window.removeEventListener("crm:logout", onLogout);
  }, [logout]);

  useEffect(() => {
    if (!remote) return;
    if (!authed) { setLoading(false); return; }
    void loadAll();
  }, [authed, loadAll]);

  // ---- remote: leads feed ----
  /** Fold a feed page into db: its conversations (fresh from the server), crm slices and runs. */
  const absorbLeadPage = useCallback((page: api.LeadsPage) => {
    const raws = page.leads.map((l) => l.conversation as Raw);
    const runs = page.leads.flatMap((l) => (l.run ? [mapRun(l.run as Raw)] : []));
    setDb((d) => {
      const fresh = new Map(raws.map((r) => [r.id as string, mapConv(r)]));
      const conversations = d.conversations.map((c) => fresh.get(c.id) ?? c);
      const have = new Set(d.conversations.map((c) => c.id));
      for (const [id, c] of fresh) if (!have.has(id)) conversations.push(c);
      const runIds = new Set(runs.map((r) => r.id));
      return { ...d, conversations, crm: { ...d.crm, ...Object.fromEntries(raws.map((r) => [r.id, crmFrom(r)])) }, runs: [...d.runs.filter((r) => !runIds.has(r.id)), ...runs] };
    });
  }, []);
  const loadLeads = useCallback(async (filters?: { q?: string; source?: string }) => {
    if (!remote) return;
    const q = filters?.q ?? feedRef.current.q;
    const source = filters?.source ?? feedRef.current.source;
    // Before boot the account/schema are not in; park like the other loaders.
    if (!booted.current) { parkedLoads.current.set("leads-feed", () => loadLeads({ q, source })); return; }
    const req = ++feedReq.current;
    setFeed((f) => ({ ...f, q, source, loading: true }));
    try {
      const page = await api.listLeadsPage({ q: q || undefined, source: source || undefined, limit: LEADS_PAGE, offset: 0 });
      if (req !== feedReq.current) return;
      absorbLeadPage(page);
      setFeed({ items: page.leads.map(feedItem), total: page.total, offset: page.limit, loading: false, ready: true, q, source });
    } catch (e) {
      if (req !== feedReq.current) return;
      setFeed((f) => ({ ...f, loading: false, ready: true }));
      setToast(`Could not load leads: ${errMsg(e)}`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [absorbLeadPage]);
  const loadMoreLeads = useCallback(async () => {
    const f = feedRef.current;
    if (!remote || !f.ready || f.loading || f.offset >= f.total) return;
    const req = feedReq.current;
    setFeed((x) => ({ ...x, loading: true }));
    try {
      const page = await api.listLeadsPage({ q: f.q || undefined, source: f.source || undefined, limit: LEADS_PAGE, offset: f.offset });
      if (req !== feedReq.current) return;
      absorbLeadPage(page);
      setFeed((x) => {
        const have = new Set(x.items.map((i) => i.key));
        return { ...x, items: [...x.items, ...page.leads.filter((l) => !have.has(l.key)).map(feedItem)], total: page.total, offset: f.offset + page.limit, loading: false };
      });
    } catch (e) {
      if (req !== feedReq.current) return;
      setFeed((x) => ({ ...x, loading: false }));
      setToast(`Could not load more leads: ${errMsg(e)}`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [absorbLeadPage]);
  /** Re-pull page 1 and merge it on top: new arrivals appear, rows that page 1 no longer lists are dropped. */
  const refreshLeads = useCallback(async () => {
    const f = feedRef.current;
    if (!remote || !f.ready || !leadsWatched.current) return;
    const req = feedReq.current;
    try {
      const page = await api.listLeadsPage({ q: f.q || undefined, source: f.source || undefined, limit: LEADS_PAGE, offset: 0 });
      if (req !== feedReq.current) return;
      absorbLeadPage(page);
      setFeed((x) => {
        const top = page.leads.map(feedItem);
        const keys = new Set(top.map((i) => i.key));
        const oldest = top.length ? top[top.length - 1].arrivedAt : "";
        // A short page 1 is the whole feed; otherwise keep what lies below it.
        const rest = page.leads.length >= page.limit ? x.items.filter((i) => !keys.has(i.key) && i.arrivedAt < oldest) : [];
        const items = [...top, ...rest];
        return { ...x, items, total: page.total, offset: Math.max(top.length, x.offset + (items.length - x.items.length)) };
      });
    } catch { /* the next resync retries */ }
  }, [absorbLeadPage]);
  // Stable: the Leads page toggles this from a mount effect, so it must not change identity per render.
  const setLeadsWatched = useCallback((on: boolean) => {
    leadsWatched.current = on;
    if (!on && leadsRefreshTimer.current !== null) { window.clearTimeout(leadsRefreshTimer.current); leadsRefreshTimer.current = null; }
  }, []);
  const scheduleLeadsRefresh = useCallback(() => {
    if (!leadsWatched.current || !feedRef.current.ready || leadsRefreshTimer.current !== null) return;
    leadsRefreshTimer.current = window.setTimeout(() => { leadsRefreshTimer.current = null; void refreshLeads(); }, 2500);
  }, [refreshLeads]);

  // ---- remote: SSE (conversation / message / note / call) ----
  // Android freezes a backgrounded app and drops its connections; a frozen
  // EventSource may never retry on its own. So the stream is reconnectable,
  // and every "we are back" signal (visible / focus / online / pageshow)
  // reconnects it if needed and resyncs what was missed meanwhile.
  useEffect(() => {
    if (!remote || !authed) return;
    let es: EventSource | null = null;
    let everOpened = false;
    let downSince: number | null = null;
    let closed = false;
    const resync = () => { void reloadConversations(); resyncOpen.current(); void refreshLeads(); };
    const connect = () => {
      // Close hard before opening another — browser EventSource auto-retries on
      // error, and with Vite's proxy that stacked dozens of /events sockets and
      // starved the API thread pool (hanging /health).
      if (es) { try { es.onerror = null; es.close(); } catch { /* ignore */ } }
      const next = new EventSource(api.eventsUrl());
      es = next;
      next.onopen = () => { if (next !== es) return; setApiDown(false); downSince = null; if (everOpened) resync(); everOpened = true; };
      next.onerror = () => {
        if (next !== es) return;
        setApiDown(true);
        if (downSince === null) downSince = Date.now();
        // Stop the browser's built-in reconnect; the watchdog calls connect().
        try { next.close(); } catch { /* ignore */ }
      };
      next.addEventListener("conversation", (e) => { try { upsertConv(JSON.parse((e as MessageEvent).data), true); scheduleLeadsRefresh(); } catch { /* ignore */ } });
      next.addEventListener("message", (e) => { try { upsertMessage(JSON.parse((e as MessageEvent).data)); } catch { /* ignore */ } });
      next.addEventListener("note", (e) => { try { upsertNote(JSON.parse((e as MessageEvent).data)); } catch { /* ignore */ } });
      next.addEventListener("call_review", (e) => { try {
        const r = JSON.parse((e as MessageEvent).data) as CallReview;
        // Merge, never replace: a queued event carries no result and must not
        // blank the review already on screen (the contact_name hazard below).
        setCallReviews((m) => ({ ...m, [r.contact_phone]: { ...m[r.contact_phone], ...r } }));
      } catch { /* ignore */ } });
      next.addEventListener("call", (e) => { try {
        const call = JSON.parse((e as MessageEvent).data) as CallRecord;
        setDb((d) => {
          const cur = d.calls ?? [];
          const prev = cur.find((x) => x.id === call.id);
          // Never let a name-less event blank a name we already have; fall back to the loaded conversation.
          const fromConv = call.conversation_id ? d.conversations.find((c) => c.id === call.conversation_id)?.contact_name ?? null : null;
          const merged: CallRecord = { ...prev, ...call, contact_name: call.contact_name ?? prev?.contact_name ?? fromConv };
          return { ...d, calls: prev ? cur.map((x) => (x.id === call.id ? merged : x)) : [merged, ...cur] };
        });
      } catch { /* ignore */ } });
    };
    const back = () => {
      if (closed || document.visibilityState !== "visible") return;
      if (!es || es.readyState !== EventSource.OPEN) connect();
      resync();
    };
    connect();
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    window.addEventListener("online", back);
    window.addEventListener("pageshow", back);
    // Watchdog: a stream stuck in CONNECTING raises no further events; after
    // 8s down while visible, start over.
    const dog = window.setInterval(() => {
      if (closed || document.visibilityState !== "visible") return;
      if (downSince !== null && Date.now() - downSince > 8000) { downSince = Date.now(); connect(); resync(); }
    }, 2000);
    return () => {
      closed = true;
      es?.close();
      window.clearInterval(dog);
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("focus", back);
      window.removeEventListener("online", back);
      window.removeEventListener("pageshow", back);
    };
  }, [authed, reloadConversations, upsertConv, upsertMessage, upsertNote, refreshLeads, scheduleLeadsRefresh]);

  // Safety net: a half-open EventSource that never errors would leave the list
  // frozen, so re-sync every 60s while the tab is visible (as the old inbox did).
  useEffect(() => {
    if (!remote || !authed) return;
    const t = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void reloadConversations(); resyncOpen.current(); void refreshLeads();
    }, 60_000);
    return () => window.clearInterval(t);
  }, [authed, reloadConversations, refreshLeads]);

  /** Mock-mode only: stand in for storage.expire_stale_conversations. Against a
   * real backend the server owns this — running it here invented an "expired"
   * the server disagreed with, and the two overwrote each other every 30s,
   * which is what made rows flicker and jump. */
  useEffect(() => {
    if (remote) return;
    const sweep = () => setDb((d) => {
      const now = Date.now();
      let changed = false;
      const conversations = d.conversations.map((c) => {
        if (c.status !== "expired" && !isWithinWindow(c, now)) { changed = true; return { ...c, status: "expired" as const, bot_paused: false, active_workflow_run_id: null }; }
        return c;
      });
      return changed ? { ...d, conversations } : d;
    });
    sweep();
    const t = window.setInterval(sweep, 30_000);
    return () => window.clearInterval(t);
  }, []);

  /** Broadcast worker: drain running broadcasts 10 per tick (mirrors drain_broadcasts). Mock only. */
  useEffect(() => {
    if (remote) return;
    const t = window.setInterval(() => {
      setDb((d) => {
        const running = d.broadcasts.filter((b) => b.status === "running");
        if (!running.length) return d;
        let next = d;
        for (const b of running) {
          const recs = next.recipients[b.id] ?? [];
          const pending = recs.filter((r) => r.status === "pending").slice(0, 10);
          const tmpl = next.templates.find((t) => t.name === b.template_name);
          const updated = recs.map((r) => {
            if (!pending.includes(r)) return r;
            const fail = Math.random() < 0.04;
            return { ...r, status: fail ? "failed" as const : "sent" as const, error: fail ? "131026: recipient not on WhatsApp" : null, sent_at: nowIso(), meta_message_id: fail ? null : `wamid.${uid("b").toUpperCase()}` };
          });
          for (const r of updated.filter((r) => pending.includes(recs[recs.indexOf(r)] ?? r) && r.status === "sent")) {
            if (!tmpl) continue;
            const existing = next.conversations.find((c) => c.contact_phone === r.contact_phone);
            const conv: Conversation = existing ?? newConversation(r.contact_phone, r.contact_name);
            if (!existing) next = { ...next, conversations: [conv, ...next.conversations] };
            const m: MessageRecord = { id: uid("msg"), whatsapp_account_id: ACCOUNT_ID, contact_phone: r.contact_phone, direction: "outgoing", message_type: "template", text: renderTemplateBody(tmpl.components, r.params), metadata: { sent_by: "broadcast", broadcast_id: b.id, template: { name: tmpl.name, language: tmpl.language, params: r.params }, meta_message_id: r.meta_message_id ?? undefined }, status: "sent", created_at: nowIso() };
            next = appendOutgoing(next, conv, m, `📋 ${tmpl.name}`);
          }
          const counts = countsOf(updated);
          const done = counts.pending === 0;
          next = { ...next, recipients: { ...next.recipients, [b.id]: updated }, broadcasts: next.broadcasts.map((x) => x.id === b.id ? { ...x, counts, status: done ? "completed" : x.status, completed_at: done ? nowIso() : x.completed_at } : x) };
        }
        return next;
      });
      setDb((d) => {
        let changed = false;
        const recipients = { ...d.recipients };
        for (const id of Object.keys(recipients)) {
          recipients[id] = recipients[id].map((r) => {
            if (r.status === "sent" && Math.random() < 0.5) { changed = true; return { ...r, status: "delivered" as const }; }
            if (r.status === "delivered" && Math.random() < 0.25) { changed = true; return { ...r, status: "read" as const }; }
            return r;
          });
        }
        if (!changed) return d;
        const broadcasts = d.broadcasts.map((b) => {
          const counts = countsOf(recipients[b.id] ?? []);
          return { ...b, counts };
        });
        return { ...d, recipients, broadcasts };
      });
    }, 1500);
    return () => window.clearInterval(t);
  }, []);

  // ---- remote: lazy loaders ----
  const ensureMessages = useCallback((convId: string) => {
    if (!remote || loadingMsgs.current.has(convId)) return;
    loadingMsgs.current.add(convId);
    api.getMessages(convId, { limit: 30 }).then((r) => {
      const msgs = r.messages.map(api.withMediaSrc).sort(byTime);
      setDb((d) => ({ ...d, messages: { ...d.messages, [convId]: msgs } }));
      setMsgMeta((m) => ({ ...m, [convId]: { hasMore: !!r.has_more } }));
      if (r.conversation) upsertConv(r.conversation);
    }).catch((e) => { loadingMsgs.current.delete(convId); setToast(`Could not load messages: ${errMsg(e)}`); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upsertConv]);
  resyncOpen.current = () => {
    const id = openConvRef.current;
    if (!id) return;
    loadingMsgs.current.delete(id);
    ensureMessages(id);
  };
  const loadOlderMessages = useCallback(async (convId: string) => {
    if (!remote) return;
    const cur = dbRef.current.messages[convId] ?? [];
    const before = cur[0]?.created_at;
    if (!before) return;
    const r = await api.getMessages(convId, { limit: 30, before });
    const older = r.messages.map(api.withMediaSrc).sort(byTime);
    setDb((d) => { const have = new Set((d.messages[convId] ?? []).map((m) => m.id)); return { ...d, messages: { ...d.messages, [convId]: [...older.filter((m) => !have.has(m.id)), ...(d.messages[convId] ?? [])] } }; });
    setMsgMeta((m) => ({ ...m, [convId]: { hasMore: !!r.has_more } }));
  }, []);
  const ensureNotes = useCallback((convId: string) => {
    if (!remote || loadedNotes.current.has(convId)) return;
    loadedNotes.current.add(convId);
    api.listNotes(convId).then((ns) => setDb((d) => ({ ...d, notes: { ...d.notes, [convId]: ns.map(mapNote).sort((a, b) => (a.at < b.at ? -1 : 1)) } }))).catch(() => loadedNotes.current.delete(convId));
  }, []);
  const ensureRunDetail = useCallback((runId: string) => {
    if (!remote || loadedRuns.current.has(runId)) return;
    loadedRuns.current.add(runId);
    api.getRun(runId).then((r) => setDb((d) => ({
      ...d,
      runs: d.runs.map((x) => (x.id === runId && r.workflow_run ? mapRun(r.workflow_run) : x)),
      nodeResponses: { ...d.nodeResponses, [runId]: (r.node_responses ?? []).map(mapNodeResponse) },
    }))).catch(() => loadedRuns.current.delete(runId));
  }, []);
  const refreshBroadcast = useCallback(async (id: string) => {
    if (!remote) return;
    const [b, recs] = await Promise.all([api.getBroadcast(id), api.listRecipients(id)]);
    const nameByPhone = new Map(dbRef.current.contacts.map((c) => [c.phone, c.name]));
    setDb((d) => ({ ...d, broadcasts: d.broadcasts.some((x) => x.id === id) ? d.broadcasts.map((x) => (x.id === id ? mapBroadcast(b) : x)) : [mapBroadcast(b), ...d.broadcasts], recipients: { ...d.recipients, [id]: recs.map((r) => mapRecipient(r, nameByPhone)) } }));
  }, []);
  const refreshTemplates = useCallback(async () => {
    if (!remote || !dbRef.current.account.id) return;
    const ts = await api.listTemplates(dbRef.current.account.id);
    setDb((d) => ({ ...d, templates: ts.map(mapTemplate) }));
  }, []);

  /** Run a fetch at most once per boot; a failure re-arms it and surfaces a toast. */
  const once = useCallback((key: string, fn: () => Promise<unknown>) => {
    if (!remote || loadedSets.current.has(key)) return;
    if (!booted.current) { parkedLoads.current.set(key, fn); return; }
    loadedSets.current.add(key);
    fn().catch((e) => { loadedSets.current.delete(key); setToast(`Could not load ${key}: ${errMsg(e)}`); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Parked loaders run after the boot render, when dbRef already holds the account.
  useEffect(() => {
    if (!booted.current) return;
    const parked = [...parkedLoads.current]; parkedLoads.current.clear();
    for (const [key, fn] of parked) {
      // leads-feed is not a once-per-boot resource — always run the parked call.
      if (key === "leads-feed") { void fn(); continue; }
      once(key, fn);
    }
  }, [bootTick, once]);
  const ensureTemplates = useCallback(() => once("templates", refreshTemplates), [once, refreshTemplates]);
  const ensureContacts = useCallback(() => once("contacts", () => reloadContacts(dbRef.current.account.id)), [once, reloadContacts]);
  const ensureBroadcasts = useCallback(() => once("campaigns", async () => {
    const aid = dbRef.current.account.id; if (!aid) return;
    const bs = await api.listBroadcasts(aid);
    setDb((d) => ({ ...d, broadcasts: bs.map(mapBroadcast).sort((a, b) => (a.created_at < b.created_at ? 1 : -1)) }));
  }), [once]);
  const ensureRuns = useCallback(() => once("leads", async () => {
    const runs = await api.listRuns({}, 1000);
    setDb((d) => ({ ...d, runs: runs.map(mapRun) }));
  }), [once]);
  const ensureCalls = useCallback(() => once("calls", async () => {
    const calls = await api.listCalls({}, 1000);
    setDb((d) => ({ ...d, calls }));
    // Reviews are one small doc per patient; pulled with the calls so the
    // column renders without a request per row. Absent feature -> 403, ignored.
    try {
      const reviews = await api.listCallReviews();
      setCallReviews(Object.fromEntries(reviews.map((r) => [r.contact_phone, r])));
    } catch { /* feature off for this clinic */ }
  }), [once]);
  const startCallReview = useCallback((phone: string) => {
    if (!remote) return;
    // Optimistic: the button must react before the worker picks the job up.
    setCallReviews((m) => ({ ...m, [phone]: { ...(m[phone] as CallReview), contact_phone: phone, status: "queued", error: null } as CallReview }));
    api.startCallReview(phone)
      .then((r) => setCallReviews((m) => ({ ...m, [phone]: { ...m[phone], ...r } })))
      .catch((e) => {
        setCallReviews((m) => ({ ...m, [phone]: { ...(m[phone] as CallReview), contact_phone: phone, status: "failed", error: errMsg(e) } as CallReview }));
        setToast(`Could not start the review: ${errMsg(e)}`);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const ensureUsage = useCallback(() => once("usage", async () => {
    const u = await api.usage();
    setDb((d) => ({ ...d, usage: mapUsage(u) }));
  }), [once]);
  const ensureRunForConversation = useCallback((phone: string) => once(`run:${phone}`, async () => {
    const runs = await api.listRuns({ contact_phone: phone }, 200);
    setDb((d) => { const have = new Set(d.runs.map((r) => r.id)); return { ...d, runs: [...d.runs, ...runs.filter((r) => !have.has(r.id)).map(mapRun)] }; });
  }), [once]);
  /** Merge a page into the union store; rows already held keep their place. */
  const absorbConvPage = useCallback((raws: Raw[]) => {
    setDb((d) => {
      const have = new Set(d.conversations.map((c) => c.id));
      const add = raws.filter((c) => !have.has(c.id as string));
      if (!add.length) return d;
      return { ...d, conversations: [...d.conversations, ...add.map(mapConv)], crm: { ...d.crm, ...Object.fromEntries(add.map((c) => [c.id, crmFrom(c)])) } };
    });
  }, []);

  const loadMoreConversations = useCallback(async (view: ConvView = "inbox") => {
    if (!remote || loadingMore.current[view]) return;
    const { loaded, total } = convPagingRef.current[view];
    if (loaded >= total) return;
    loadingMore.current[view] = true;
    try {
      const page = await api.listConversationsPage({ limit: 50, offset: loaded, view });
      absorbConvPage(page.conversations as unknown as Raw[]);
      setConvPaging((p) => ({ ...p, [view]: { total: page.total, loaded: loaded + page.conversations.length } }));
      if (page.counts) setConvCounts(page.counts);
    } catch (e) { setToast(`Could not load more: ${errMsg(e)}`); }
    finally { loadingMore.current[view] = false; }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [absorbConvPage]);

  /** Page 1 of the template tab — on first open, and while it is being watched. */
  const refreshTemplateView = useCallback(async () => {
    if (!remote) return;
    try {
      const page = await api.listConversationsPage({ limit: 50, view: "template" });
      absorbConvPage(page.conversations as unknown as Raw[]);
      setConvPaging((p) => ({ ...p, template: { total: page.total, loaded: Math.max(p.template.loaded, page.conversations.length) } }));
      if (page.counts) setConvCounts(page.counts);
    } catch { /* the next refresh retries */ }
  }, [absorbConvPage]);

  refreshTemplateRef.current = () => { void refreshTemplateView(); };

  /** The inbox list tells the store which tab is showing, so only that one is kept fresh. */
  const setConversationView = useCallback((view: ConvView) => {
    convWatched.current = view;
    if (view === "template" && convPagingRef.current.template.loaded === 0) void refreshTemplateView();
  }, [refreshTemplateView]);

  const value = useMemo<Store>(() => {
    const runByPhone = new Map<string, WorkflowRun>();
    for (const r of db.runs) { const prev = runByPhone.get(r.contact_phone); if (!prev || r.started_at > prev.started_at) runByPhone.set(r.contact_phone, r); }
    // A thread we started (single template send, broadcast) is not a lead until
    // the person replies or a flow runs for them.
    const toLead = (c: Conversation, run: WorkflowRun | null, rowKey: string, arrivedAt: string): Lead =>
      ({ id: c.id, rowKey, arrivedAt, conversation: c, run, crm: normCrm(db.crm[c.id]), name: c.contact_name?.trim() || `+${c.contact_phone}`, phone: c.contact_phone, fields: run?.variables ?? {}, createdAt: c.created_at, lastActivityAt: c.last_message_at ?? c.created_at });
    // Per patient (latest run): what the properties drawer, lead sheet and calls popup show.
    const patientLeads: Lead[] = db.conversations.flatMap((c) => {
      const run = runByPhone.get(c.contact_phone) ?? null;
      if (!c.last_inbound_at && !run) return [];
      return [toLead(c, run, c.id, c.created_at)];
    });
    const leadById = new Map(patientLeads.map((l) => [l.id, l]));
    // The Leads page: one row per arrival from the server feed (mock mode: one per patient).
    const convById = new Map(db.conversations.map((c) => [c.id, c]));
    const runById = new Map(db.runs.map((r) => [r.id, r]));
    const leads: Lead[] = remote
      ? feed.items.flatMap((i) => { const c = convById.get(i.convId); return c ? [toLead(c, (i.runId && runById.get(i.runId)) || null, i.key, i.arrivedAt)] : []; })
      : patientLeads;
    const leadFeed: LeadFeedInfo = { total: remote ? feed.total : leads.length, loaded: leads.length, loading: feed.loading, ready: feed.ready, hasMore: remote && feed.offset < feed.total, q: feed.q, source: feed.source };
    const clearSelection = () => { setSelectedIds([]); setSelectMode(false); };
    const flow: Flow = remote ? (schemaFlow ?? { id: "remote", name: db.client.name, fields: [] }) : ACTIVE_FLOW;
    const fail = (prefix: string) => (e: unknown) => setToast(`${prefix}: ${errMsg(e)}`);

    /** Persist the CRM-owned slice (call_tried + custom) as attributes.crm. */
    const pushCrmSlice = (id: string, crm: CrmFields) => {
      if (!remote) return;
      // call_tried is server-owned (bumped by FasterQ outbound calls) — never sent.
      api.updateContact(id, { attributes: { crm: { custom: crm.custom } } }).then((r) => r?.conversation && upsertConv(r.conversation)).catch(fail("Could not save"));
    };
    const setCrmLocal = (id: string, fn: (cur: CrmFields) => CrmFields): CrmFields => {
      const next = fn(normCrm(dbRef.current.crm[id]));
      setDb((d) => ({ ...d, crm: { ...d.crm, [id]: next } }));
      return next;
    };
    const persistColumns = (next: CustomColumn[]) => {
      if (!remote || !db.client.id) return;
      api.patchClient(db.client.id, { crm_columns: next }).catch(fail("Could not save columns"));
    };

    const sendTemplate: Store["sendTemplate"] = async (phone, name, template, params, sentBy = "template", broadcastId) => {
      if (remote) {
        await api.testSend(db.account.id, template.id, { to_phone: phone, params });
        // The new chat is awaiting a template reply, so it is excluded from the
        // inbox view by definition — scanning that page would never find it and
        // the caller's navigate would silently do nothing. Pull the template
        // view (which also refreshes that tab) and fall back to what we hold.
        const clean = phone.trim().replace(/^\+/, "");
        await refreshTemplateView();
        const match = (c: Conversation) => c.contact_phone === clean || c.contact_phone === phone;
        return dbRef.current.conversations.find(match)?.id ?? "";
      }
      let convId = "";
      setDb((d) => {
        const existing = d.conversations.find((c) => c.contact_phone === phone);
        const conv = existing ?? newConversation(phone, name);
        convId = conv.id;
        let next = existing ? d : { ...d, conversations: [conv, ...d.conversations], contacts: d.contacts.some((c) => c.phone === phone) ? d.contacts : [...d.contacts, { id: uid("ct"), whatsapp_account_id: ACCOUNT_ID, phone, name, source: "import" as const, opted_out: false, marketing_opt_in: true, tags: [], last_inbound_at: null, created_at: nowIso() }] };
        const m: MessageRecord = { id: uid("msg"), whatsapp_account_id: ACCOUNT_ID, contact_phone: phone, direction: "outgoing", message_type: "template", text: renderTemplateBody(template.components, params), metadata: { sent_by: sentBy, template: { name: template.name, language: template.language, params }, ...(broadcastId ? { broadcast_id: broadcastId } : {}), meta_message_id: `wamid.${uid("t").toUpperCase()}` }, status: "created", created_at: nowIso() };
        next = appendOutgoing(next, conv, m, `📋 ${template.name}`);
        window.setTimeout(() => simulateTicks(conv.id, m.id), 0);
        return next;
      });
      return convId;
    };

    /** Bulk-send rows → backend audience. Contacts are imported first so the preview/counts match. */
    const importRows = async (rows: { phone: string; name: string }[], template: Template) => {
      const seen = new Set<string>();
      const uniq = rows.filter((r) => (seen.has(r.phone) ? false : (seen.add(r.phone), true)));
      for (let i = 0; i < uniq.length; i += 500) {
        await api.importContacts(db.account.id, uniq.slice(i, i + 500).map((r) => ({ phone: r.phone, ...(r.name ? { name: r.name } : {}), ...(template.category === "MARKETING" ? { opted_in: true } : {}) })));
      }
      return { phones: Array.from(seen), duplicates: rows.length - uniq.length };
    };
    const broadcastBody = (name: string | undefined, template: Template, phones: string[], confirm?: boolean): api.BroadcastBody => ({
      ...(name ? { name } : {}), template_name: template.name, template_language: template.language,
      variable_mapping: template.body_variable_count > 0 ? { "1": "@contact.name|there" } : {},
      audience: { type: "phones", phones }, ...(confirm ? { confirm: true } : {}),
    });

    return {
      features,
      setFeature: (key, on) => {
        const next = { ...featurePrefs, [key]: on };
        setFeaturePrefs(next);
        setFeatures(resolveFeatures(clientFeaturesRef.current, next));
        if (remote && db.client.id) api.patchClient(db.client.id, { feature_prefs: { [key]: on } }).catch(fail("Could not save preference"));
      },
      granted: grantedFeatures(clientFeaturesRef.current),
      featurePrefs,
      remote, authed, loading, apiDown,
      login: async (username, password) => { const r = await api.login(username, password); api.setToken(r.access_token); setAuthed(true); },
      logout,
      refresh: loadAll,
      flow, account: db.account, client: db.client, usage: db.usage,
      conversations: db.conversations, leads, contacts: db.contacts, templates: db.templates, broadcasts: db.broadcasts, runs: db.runs,
      messagesFor: (id) => db.messages[id] ?? [],
      notesFor: (id) => db.notes[id] ?? [],
      recipientsFor: (id) => db.recipients[id] ?? [],
      responsesFor: (id) => db.nodeResponses[id] ?? [],
      leadFor: (id) => leadById.get(id),
      conversationByPhone: (phone) => db.conversations.find((c) => c.contact_phone === phone),
      ensureMessages, loadOlderMessages, hasMoreMessages: (id) => !!msgMeta[id]?.hasMore, ensureNotes, ensureRunDetail, refreshBroadcast, refreshTemplates,
      ensureTemplates, ensureBroadcasts, ensureContacts, ensureRuns, ensureUsage, ensureRunForConversation, ensureCalls,
      leadFeed, loadLeads, loadMoreLeads, setLeadsWatched,
      callReviews, startCallReview,
      loadMoreConversations,
      hasMoreConversations: (view: ConvView = "inbox") => convPaging[view].loaded < convPaging[view].total,
      convCounts, setConversationView,
      syncTemplates: async () => {
        if (!remote) return;
        const r = await api.syncTemplates(db.account.id);
        setDb((d) => ({ ...d, templates: (r.templates ?? []).map(mapTemplate) }));
        setToast(`Synced ${r.synced ?? r.templates?.length ?? 0} templates from Meta`);
      },

      setOpenConversation: (id) => { openConvRef.current = id; },
      markViewed: (id) => {
        patchConv(id, (c) => (c.unread_count ? { ...c, unread_count: 0 } : c));
        if (remote && (dbRef.current.conversations.find((c) => c.id === id)?.unread_count ?? 0) > 0) api.markViewed(id).catch(() => { /* best effort */ });
      },
      closeConversation: (id) => {
        patchConv(id, (c) => ({ ...c, status: "resolved", resolved_at: nowIso(), resolved_by: "agent", bot_paused: false, active_workflow_run_id: null }));
        if (remote) api.closeConversation(id).catch(fail("Could not resolve"));
      },
      reopenConversation: (id) => {
        patchConv(id, (c) => ({ ...c, status: "open", resolved_at: null, resolved_by: null }));
        if (remote) api.openConversation(id).catch(fail("Could not re-open"));
      },
      deleteConversation: (id) => {
        if (remote) api.deleteConversation(id).catch(fail("Could not delete"));
        setDb((d) => { const c = d.conversations.find((x) => x.id === id); const { [id]: _m, ...messages } = d.messages; const { [id]: _n, ...notes } = d.notes; void _m; void _n; return { ...d, conversations: d.conversations.filter((x) => x.id !== id), messages, notes, runs: remote || !c ? d.runs : d.runs.filter((r) => r.contact_phone !== c.contact_phone) }; });
      },
      updateContact: (id, patch) => {
        patchConv(id, (c) => ({ ...c, ...(patch.contact_name !== undefined ? { contact_name: patch.contact_name } : {}), ...(patch.tags ? { tags: patch.tags } : {}), ...(patch.attributes ? { attributes: patch.attributes } : {}) }));
        if (remote) api.updateContact(id, { ...(patch.contact_name !== undefined ? { contact_name: patch.contact_name } : {}), ...(patch.tags ? { tags: patch.tags } : {}) }).then((r) => r?.conversation && upsertConv(r.conversation)).catch(fail("Could not update contact"));
      },
      setCrm: (id, patch) => {
        setCrmLocal(id, (cur) => ({ ...cur, ...patch }));
        if (remote && patch.disposition !== undefined) api.updateDisposition(id, { disposition: patch.disposition }).then((c) => c && upsertConv(c)).catch(fail("Could not save disposition"));
      },
      calls: db.calls ?? [],
      setCallAgents: async (names) => {
        const clean = names.map((x) => x.trim()).filter(Boolean);
        setDb((d) => ({ ...d, client: { ...d.client, call_recording: { agent_names: clean } } }));
        if (remote && db.client.id) await api.patchClient(db.client.id, { call_recording: { agent_names: clean } });
      },
      setRemark: (id, text) => {
        setCrmLocal(id, (cur) => ({ ...cur, remark: text }));
        if (remote) api.updateDisposition(id, { remark: text }).then((c) => c && upsertConv(c)).catch(fail("Could not save remark"));
      },
      setCustomValue: (id, key, value) => pushCrmSlice(id, setCrmLocal(id, (cur) => ({ ...cur, custom: { ...cur.custom, [key]: value } }))),
      customColumns,
      addCustomColumn: ({ label, type, options }) => {
        const base = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "column";
        let key = `c_${base}`; let i = 2;
        while (customColumns.some((c) => c.key === key)) key = `c_${base}_${i++}`;
        const def: CustomColumn = { key, label: label.trim(), type, ...(type === "dropdown" ? { options: (options ?? []).map((o) => o.trim()).filter(Boolean) } : {}) };
        const next = [...customColumns, def];
        setCustomColumns(next);
        setCols((v) => (v.includes(key) ? v : [...v, key]));
        persistColumns(next);
        return key;
      },
      removeCustomColumn: (key) => {
        const next = customColumns.filter((c) => c.key !== key);
        setCustomColumns(next);
        setCols((v) => v.filter((k) => k !== key));
        setDb((d) => ({ ...d, crm: Object.fromEntries(Object.entries(d.crm).map(([id, c]) => { const n = normCrm(c); const { [key]: _drop, ...rest } = n.custom; void _drop; return [id, { ...n, custom: rest }]; })) }));
        persistColumns(next);
      },
      addNote: (id, text) => {
        if (remote) { api.addNote(id, text).then((n) => upsertNote(n)).catch(fail("Could not add note")); return; }
        setDb((d) => ({ ...d, notes: { ...d.notes, [id]: [...(d.notes[id] ?? []), { id: uid("note"), conversation_id: id, text, at: nowIso() }] } }));
      },

      sendAgentMessage: async (id, text) => {
        const c = db.conversations.find((x) => x.id === id);
        if (!c) return;
        if (c.status === "resolved") throw new Error("Chat is resolved — re-open it to reply.");
        if (!isWithinWindow(c)) throw new Error(WINDOW_CLOSED_ERROR);
        if (remote) {
          const r = await api.sendText(id, text);
          const m: MessageRecord = { id: r.message_id, whatsapp_account_id: c.whatsapp_account_id, contact_phone: c.contact_phone, direction: "outgoing", message_type: "text", text, metadata: { sent_by: "agent", ...(r.send_error ? { send_error: typeof r.send_error === "string" ? r.send_error : JSON.stringify(r.send_error) } : {}) }, status: (r.status as MessageStatus) ?? "sent", created_at: nowIso() };
          setDb((d) => { const conv = d.conversations.find((x) => x.id === id); if (!conv) return d; const has = (d.messages[id] ?? []).some((x) => x.id === m.id); const next = has ? d : appendOutgoing(d, conv, m, text); return { ...next, conversations: next.conversations.map((x) => x.id === id ? { ...x, bot_paused: true, active_workflow_run_id: null } : x) }; });
          if (r.status === "failed") throw new Error(`Send failed: ${m.metadata.send_error ?? "rejected by WhatsApp"}`);
          return;
        }
        const m: MessageRecord = { id: uid("msg"), whatsapp_account_id: ACCOUNT_ID, contact_phone: c.contact_phone, direction: "outgoing", message_type: "text", text, metadata: { sent_by: "agent", meta_message_id: `wamid.${uid("a").toUpperCase()}` }, status: "created", created_at: nowIso() };
        const failSend = Math.random() < 0.06;
        setDb((d) => { const conv = d.conversations.find((x) => x.id === id)!; const next = appendOutgoing(d, conv, m, text); return { ...next, conversations: next.conversations.map((x) => x.id === id ? { ...x, bot_paused: true, active_workflow_run_id: null } : x), runs: next.runs.map((r) => r.id === conv.active_workflow_run_id ? { ...r, status: "cancelled" } : r) }; });
        simulateTicks(id, m.id, failSend);
        if (failSend) window.setTimeout(() => patchMsg(id, m.id, (x) => ({ ...x, metadata: { ...x.metadata, send_error: "Message failed to send (131049: not enough recent engagement)" } })), 950);
      },
      sendAgentAudio: async (id, blob, duration) => {
        const c = db.conversations.find((x) => x.id === id);
        if (!c || !isWithinWindow(c) || c.status === "resolved") return;
        if (remote) {
          const r = await api.sendAudio(id, blob);
          const m: MessageRecord = { id: r.message_id, whatsapp_account_id: c.whatsapp_account_id, contact_phone: c.contact_phone, direction: "outgoing", message_type: "audio", text: null, metadata: { sent_by: "agent", media: { type: "audio", mime_type: blob.type || "audio/webm", voice: true, duration, src: api.mediaUrl(r.message_id) } }, status: (r.status as MessageStatus) ?? "sent", created_at: nowIso() };
          setDb((d) => { const conv = d.conversations.find((x) => x.id === id); if (!conv) return d; const has = (d.messages[id] ?? []).some((x) => x.id === m.id); const next = has ? d : appendOutgoing(d, conv, m, "🎤 Voice message"); return { ...next, conversations: next.conversations.map((x) => x.id === id ? { ...x, bot_paused: true } : x) }; });
          return;
        }
        const m: MessageRecord = { id: uid("msg"), whatsapp_account_id: ACCOUNT_ID, contact_phone: c.contact_phone, direction: "outgoing", message_type: "audio", text: null, metadata: { sent_by: "agent", media: { type: "audio", mime_type: "audio/webm", voice: true, duration, src: URL.createObjectURL(blob) }, meta_message_id: `wamid.${uid("v").toUpperCase()}` }, status: "created", created_at: nowIso() };
        setDb((d) => { const conv = d.conversations.find((x) => x.id === id)!; const next = appendOutgoing(d, conv, m, "🎤 Voice message"); return { ...next, conversations: next.conversations.map((x) => x.id === id ? { ...x, bot_paused: true } : x) }; });
        simulateTicks(id, m.id);
      },
      sendTemplate,

      submitTemplate: async ({ name, category, language, body, footer }) => {
        const n = name.trim().toLowerCase().replace(/\s+/g, "_");
        const components = componentsFrom(body, footer);
        if (remote) {
          const t = await api.submitTemplate(db.account.id, { name: n, language: language || "en", category, components });
          setDb((d) => ({ ...d, templates: [mapTemplate(t), ...d.templates.filter((x) => x.id !== t.id)] }));
          setToast("Submitted to Meta for review");
          return;
        }
        const t: Template = { id: uid("tmpl"), whatsapp_account_id: ACCOUNT_ID, waba_id: WABA_ID, name: n, language: language || "en", category, components, body_variable_count: countBodyVariables(components), status: "PENDING", meta_template_id: null, rejected_reason: null, created_at: nowIso() };
        setDb((d) => ({ ...d, templates: [t, ...d.templates.filter((x) => !(x.name === n && x.language === t.language))] }));
        setToast("Submitted to Meta for review");
        window.setTimeout(() => { setDb((d) => ({ ...d, templates: d.templates.map((x) => x.id === t.id ? { ...x, status: "APPROVED", meta_template_id: String(Date.now()) } : x) })); setToast(`Template “${n}” approved`); }, 6000);
      },

      importContacts: async (rows) => {
        if (remote) {
          const before = new Set(dbRef.current.contacts.map((c) => c.phone));
          for (let i = 0; i < rows.length; i += 500) await api.importContacts(db.account.id, rows.slice(i, i + 500).map((r) => ({ phone: r.phone, ...(r.name ? { name: r.name } : {}), ...(r.tags?.length ? { tags: r.tags } : {}) })));
          await reloadContacts(db.account.id);
          const added = rows.filter((r) => !before.has(r.phone)).length;
          return { added, updated: rows.length - added };
        }
        let added = 0, updated = 0;
        setDb((d) => {
          const byPhone = new Map(d.contacts.map((c) => [c.phone, c]));
          for (const r of rows) {
            const ex = byPhone.get(r.phone);
            if (ex) { updated++; byPhone.set(r.phone, { ...ex, name: r.name || ex.name, tags: Array.from(new Set([...ex.tags, ...(r.tags ?? [])])) }); }
            else { added++; byPhone.set(r.phone, { id: uid("ct"), whatsapp_account_id: ACCOUNT_ID, phone: r.phone, name: r.name || null, source: "import", opted_out: false, marketing_opt_in: true, tags: r.tags ?? [], last_inbound_at: null, created_at: nowIso() }); }
          }
          return { ...d, contacts: Array.from(byPhone.values()) };
        });
        return { added, updated };
      },
      addContactTags: (id, tags) => {
        const cur = db.contacts.find((c) => c.id === id);
        const next = Array.from(new Set([...(cur?.tags ?? []), ...tags]));
        setDb((d) => ({ ...d, contacts: d.contacts.map((c) => c.id === id ? { ...c, tags: next } : c) }));
        if (remote) api.patchContact(db.account.id, id, { tags: next }).catch(fail("Could not tag"));
      },

      previewBroadcast: async (rows, template) => {
        if (remote) {
          const { phones, duplicates } = await importRows(rows, template);
          await reloadContacts(db.account.id);
          const p = await api.previewBroadcast(db.account.id, broadcastBody(undefined, template, phones));
          return { matched: p.matched, sendable: p.sendable, skipped: p.skipped, cooldown_skipped: p.cooldown_skipped ?? 0, cooldown_days: p.cooldown_days ?? 30, duplicates, unknown_phones: p.unknown_phones, opted_out: p.marketing_gated, requires_confirmation: p.requires_confirmation, over_hard_cap: p.over_hard_cap, confirm_threshold: p.confirm_threshold, hard_cap: p.hard_cap };
        }
        const category = template.category;
        const opted = new Set(db.contacts.filter((c) => c.opted_out || (category === "MARKETING" && !c.marketing_opt_in)).map((c) => c.phone));
        const seen = new Set<string>(); let duplicates = 0, optedOut = 0, unknown = 0, skipped = 0;
        for (const r of rows) {
          if (seen.has(r.phone)) { duplicates++; continue; } seen.add(r.phone);
          if (opted.has(r.phone)) { optedOut++; skipped++; continue; }
          if (r.params.some((p) => !p.trim())) { skipped++; continue; }
          if (!db.contacts.some((c) => c.phone === r.phone)) unknown++;
        }
        const matched = seen.size, sendable = matched - skipped;
        return { matched, sendable, skipped, cooldown_skipped: 0, cooldown_days: 30, duplicates, unknown_phones: unknown, opted_out: optedOut, requires_confirmation: sendable > BROADCAST_CONFIRM_THRESHOLD, over_hard_cap: sendable > BROADCAST_HARD_CAP, confirm_threshold: BROADCAST_CONFIRM_THRESHOLD, hard_cap: BROADCAST_HARD_CAP };
      },
      createBroadcast: async (name, template, rows, confirm) => {
        if (remote) {
          const { phones } = await importRows(rows, template);
          const b = mapBroadcast(await api.createBroadcast(db.account.id, broadcastBody(name, template, phones, confirm)));
          setDb((d) => ({ ...d, broadcasts: [b, ...d.broadcasts.filter((x) => x.id !== b.id)] }));
          void refreshBroadcast(b.id).catch(() => { /* polled by the page */ });
          return b.id;
        }
        const id = uid("bc");
        const opted = new Set(db.contacts.filter((c) => c.opted_out || (template.category === "MARKETING" && !c.marketing_opt_in)).map((c) => c.phone));
        const seen = new Set<string>();
        const recs: BroadcastRecipient[] = [];
        for (const r of rows) {
          if (seen.has(r.phone)) continue; seen.add(r.phone);
          const skip = opted.has(r.phone) ? "opted out" : r.params.some((p) => !p.trim()) ? "missing variable" : null;
          recs.push({ id: uid("rc"), broadcast_id: id, contact_phone: r.phone, contact_name: r.name || null, params: r.params, status: skip ? "skipped" : "pending", meta_message_id: null, error: skip, sent_at: null });
        }
        const counts = countsOf(recs);
        const b: Broadcast = { id, whatsapp_account_id: ACCOUNT_ID, name, template_name: template.name, template_language: template.language, variable_mapping: template.body_variable_count ? { "1": "@contact.name|there" } : {}, audience: { type: "phones", count: recs.length }, status: "running", counts, created_at: nowIso(), started_at: nowIso(), completed_at: null };
        setDb((d) => ({ ...d, broadcasts: [b, ...d.broadcasts], recipients: { ...d.recipients, [id]: recs }, contacts: (() => { const by = new Map(d.contacts.map((c) => [c.phone, c])); rows.forEach((r) => { if (!by.has(r.phone)) by.set(r.phone, { id: uid("ct"), whatsapp_account_id: ACCOUNT_ID, phone: r.phone, name: r.name || null, source: "import", opted_out: false, marketing_opt_in: true, tags: [], last_inbound_at: null, created_at: nowIso() }); }); return Array.from(by.values()); })() }));
        return id;
      },
      setBroadcastState: (id, action) => setDb((d) => ({ ...d, broadcasts: d.broadcasts.map((b) => b.id !== id ? b : action === "pause" ? { ...b, status: b.status === "running" ? "paused" : b.status } : action === "resume" ? { ...b, status: b.status === "paused" ? "running" : b.status } : { ...b, status: "cancelled", completed_at: nowIso() }) })),
      updateAccount: (patch) => {
        setDb((d) => ({ ...d, account: { ...d.account, ...patch } }));
        if (!remote) return;
        // Settings fields fire per keystroke — coalesce into one PATCH.
        accountPatchBuf.current = { ...accountPatchBuf.current, ...patch };
        if (accountPatchTimer.current) window.clearTimeout(accountPatchTimer.current);
        accountPatchTimer.current = window.setTimeout(() => {
          const body = accountPatchBuf.current; accountPatchBuf.current = {};
          api.patchAccount(dbRef.current.account.id, body).catch(fail("Could not save settings"));
        }, 700);
      },

      simulateIncoming: (id, text) => {
        if (remote) return;
        const c = db.conversations.find((x) => x.id === id);
        if (!c) return;
        const body = text ?? ["Hello?", "Is the clinic open tomorrow?", "Ok thanks", "Can you share the address?"][Math.floor(Math.random() * 4)];
        const m: MessageRecord = { id: uid("msg"), whatsapp_account_id: ACCOUNT_ID, contact_phone: c.contact_phone, direction: "incoming", message_type: "text", text: body, metadata: { meta_message_id: `wamid.${uid("i").toUpperCase()}` }, status: "read", created_at: nowIso() };
        setDb((d) => ({ ...d, messages: { ...d.messages, [id]: [...(d.messages[id] ?? []), m] }, conversations: d.conversations.map((x) => x.id === id ? { ...x, status: x.status === "resolved" ? "open" : x.status === "expired" ? "open" : x.status, bot_paused: x.status === "expired" ? false : x.bot_paused, last_inbound_at: m.created_at, last_message_at: m.created_at, last_message_text: body, last_message_direction: "incoming", unread_count: x.unread_count + 1 } : x) }));
        if (soundRef.current) playNotificationTone();
        notify(c.contact_name ?? c.contact_phone, body);
      },
      reset: () => {
        if (remote) { void loadAll(); setToast("Reloading…"); return; }
        localStorage.removeItem(LS.db); setDb(makeSeed()); setToast("Demo data reset");
      },

      visibleColumns: cols,
      toggleColumn: (k) => setCols((v) => (v.includes(k) ? v.filter((x) => x !== k) : [...v, k])),
      clearColumns: () => setCols(() => []),
      density, setDensity: setDensityState,
      sidebarCollapsed, toggleSidebar: () => setSidebarCollapsed((v) => !v),
      theme, toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
      sound, toggleSound: () => setSound((s) => !s),
      selectMode, setSelectMode: (b) => { setSelectMode(b); if (!b) setSelectedIds([]); },
      selectedIds, toggleSelect: (id) => setSelectedIds((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id])),
      selectMany: (ids) => setSelectedIds(ids), clearSelection,
      toast, setToast,
      templateTarget, openTemplateSend: (phones, templateId) => setTemplateTarget({ phones, templateId }), closeTemplateSend: () => setTemplateTarget(null),
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [db, view, customColumns, density, theme, sound, sidebarCollapsed, selectMode, selectedIds, toast, templateTarget, authed, loading, apiDown, schemaFlow, msgMeta, features, featurePrefs, convPaging, convCounts, feed, callReviews]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

function newConversation(phone: string, name: string | null): Conversation {
  return { id: uid("conv"), whatsapp_account_id: ACCOUNT_ID, contact_phone: phone, contact_name: name, status: "open", bot_paused: false, tags: [], attributes: {}, source: "whatsapp", source_id: null, source_url: null, ctwa_clid: null, source_type: null, headline: null, last_message_text: null, last_message_at: null, last_message_direction: null, last_inbound_at: null, awaiting_template_reply: false, unread_count: 0, resolved_at: null, resolved_by: null, created_at: nowIso(), active_workflow_run_id: null };
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside provider");
  return s;
}

export { firstName };
