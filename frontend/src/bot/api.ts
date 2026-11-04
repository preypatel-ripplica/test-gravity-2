/**
 * Typed client for the botify backend. Enabled only when VITE_API_BASE_URL is
 * set at build time; otherwise the store runs in mock mode on seed data.
 * Paths/shapes mirror routes.py (page_response = {total, limit, offset, <key>}).
 */
import type {
  Conversation, MessageRecord, Note, Template, Contact, Broadcast, BroadcastRecipient, WorkflowRun,
  WhatsAppAccount, AiUsage, CallRecord, CallReview,
} from "./types";

// Prod: same split as Beacon — page on plugai.ripplica.com, API on
// plugai.api.ripplica.com (see deploy/frontend.Dockerfile VITE_API_URL).
// Local vite proxies /bot/api → :8000 when VITE_API_URL is unset.
const RAW = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
  || (
    (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, "")
      ? `${String(import.meta.env.VITE_API_URL).replace(/\/+$/, "")}/bot/api`
      : "/bot/api"
  )
);
export const BASE = RAW.replace(/\/+$/, "");
export const enabled = BASE.length > 0;

// Same key the previous inbox used, so a signed-in client stays signed in across
// the switch. "crm_token" is the key the CRM used while it lived at /crm.
const TOKEN_KEY = "botify_inbox_token";
const LEGACY_TOKEN_KEY = "crm_token";
export const getToken = (): string | null => {
  try {
    const t = localStorage.getItem(TOKEN_KEY);
    if (t) return t;
    const legacy = localStorage.getItem(LEGACY_TOKEN_KEY);
    if (legacy) { localStorage.setItem(TOKEN_KEY, legacy); localStorage.removeItem(LEGACY_TOKEN_KEY); }
    return legacy;
  } catch { return null; }
};
export const setToken = (t: string | null) => { try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(LEGACY_TOKEN_KEY); } catch { /* ignore */ } };

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}

type Opts = { method?: string; json?: unknown; form?: FormData; auth?: boolean };
async function request<T>(path: string, { method = "GET", json, form, auth = true }: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (json !== undefined) headers["Content-Type"] = "application/json";
  const tok = getToken();
  if (auth && tok) headers.Authorization = `Bearer ${tok}`;
  const res = await fetch(`${BASE}${path}`, { method, headers, body: json !== undefined ? JSON.stringify(json) : form });
  if (res.status === 401 && auth) { setToken(null); window.dispatchEvent(new Event("crm:logout")); }
  if (!res.ok) {
    let detail = res.statusText;
    try { const b = await res.json(); detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b); } catch { /* keep */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
const qs = (o: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
/** Walk a paginated endpoint (max 200/page) up to `max` items. */
async function allPages<T>(fetchPage: (limit: number, offset: number) => Promise<{ total: number; items: T[] }>, max = 1000): Promise<T[]> {
  const out: T[] = [];
  let offset = 0;
  for (;;) {
    const { total, items } = await fetchPage(200, offset);
    out.push(...items);
    offset += items.length;
    if (items.length === 0 || offset >= total || offset >= max) break;
  }
  return out;
}

// ---- URLs used directly by the browser (token in query: EventSource/<img>/<audio> can't set headers) ----
export const eventsUrl = () => `${BASE}/events?token=${encodeURIComponent(getToken() ?? "")}`;
export const mediaUrl = (messageId: string) => `${BASE}/media/${encodeURIComponent(messageId)}?token=${encodeURIComponent(getToken() ?? "")}`;
/** Inbound/outbound media has no src in the payload — point it at the proxy. */
export const withMediaSrc = (m: MessageRecord): MessageRecord =>
  m.metadata?.media && !m.metadata.media.src ? { ...m, metadata: { ...m.metadata, media: { ...m.metadata.media, src: mediaUrl(m.id) } } } : m;

// ---- auth ----
export interface AuthClient { id: string; name: string; username?: string; status?: string; crm_push?: unknown; disposition_sync?: unknown; crm_columns?: unknown[] }
export const login = (username: string, password: string) =>
  request<{ access_token: string; token_type: string; expires_at: string; client: AuthClient }>("/auth/login", { method: "POST", json: { username, password }, auth: false });
export const me = () => request<{ client: AuthClient & Record<string, unknown> }>("/auth/me");
export const patchClient = (clientId: string, body: { crm_columns?: unknown[]; feature_prefs?: Record<string, boolean>; crm_view?: { desktop?: string[]; phone?: string[] }; call_recording?: { agent_names: string[] } }) => request<Record<string, unknown>>(`/clients/${clientId}`, { method: "PATCH", json: body });
export const usage = () => request<AiUsage>("/usage");

// ---- accounts ----
export const listAccounts = (clientId: string) => request<{ accounts?: WhatsAppAccount[]; whatsapp_accounts?: WhatsAppAccount[] } | WhatsAppAccount[]>(`/clients/${clientId}/whatsapp-accounts`)
  .then((r) => Array.isArray(r) ? r : (r.accounts ?? r.whatsapp_accounts ?? []));
export const patchAccount = (accountId: string, body: Partial<WhatsAppAccount>) => request<WhatsAppAccount>(`/whatsapp-accounts/${accountId}`, { method: "PATCH", json: body });

// ---- conversations / messages ----
/** Which inbox tab a page is for: All/Unread hide chats awaiting a template reply. */
export type ConvView = "inbox" | "template";
export interface ConvCounts { inbox: number; template: number }
/** One page of conversations — what the inbox boots with; more are pulled on scroll.
 * `counts` carries both tab totals, so a badge is right before its tab is paged. */
export const listConversationsPage = (opts: { status?: string; view?: ConvView; limit?: number; offset?: number } = {}) =>
  request<{ total: number; limit: number; offset: number; conversations: Conversation[]; counts?: ConvCounts }>(`/conversations${qs({ status: opts.status, view: opts.view, limit: opts.limit ?? 50, offset: opts.offset ?? 0 })}`);
export const listConversations = (opts: { status?: string; whatsapp_account_id?: string } = {}) =>
  allPages<Conversation>((limit, offset) => request<{ total: number; conversations: Conversation[] }>(`/conversations${qs({ ...opts, limit, offset })}`).then((r) => ({ total: r.total, items: r.conversations })), 2000);
export const getMessages = (id: string, opts: { limit?: number; before?: string } = {}) =>
  request<{ conversation: Conversation; messages: MessageRecord[]; has_more: boolean }>(`/conversations/${id}/messages${qs({ limit: opts.limit ?? 30, before: opts.before })}`);
export const markViewed = (id: string) => request(`/conversations/${id}/mark-viewed`, { method: "POST" });
export const closeConversation = (id: string) => request<{ status: string }>(`/conversations/${id}/close`, { method: "POST" });
export const openConversation = (id: string) => request<{ status: string }>(`/conversations/${id}/open`, { method: "POST" });
export const deleteConversation = (id: string) => request<{ deleted: boolean }>(`/conversations/${id}`, { method: "DELETE" });
export const updateContact = (id: string, body: { contact_name?: string; tags?: string[]; attributes?: Record<string, unknown> }) =>
  request<{ conversation: Conversation }>(`/conversations/${id}/contact`, { method: "PATCH", json: body });
export const updateDisposition = (id: string, body: { disposition?: string; remark?: string }) =>
  request<Conversation>(`/conversations/${id}/disposition`, { method: "PATCH", json: body });
export const listNotes = (id: string) => request<{ notes: Note[] }>(`/conversations/${id}/notes`).then((r) => r.notes);
export const addNote = (id: string, text: string) => request<Note>(`/conversations/${id}/notes`, { method: "POST", json: { text } });
export const deleteNote = (id: string, noteId: string) => request(`/conversations/${id}/notes/${noteId}`, { method: "DELETE" });
export const sendText = (id: string, text: string) =>
  request<{ message_id: string; status: string; send_error: unknown; bot_paused?: boolean }>(`/conversations/${id}/send`, { method: "POST", json: { text } });
export const sendAudio = (id: string, blob: Blob) => {
  const form = new FormData();
  form.append("file", blob, blob.type.includes("mp4") ? "voice.mp4" : "voice.webm");
  return request<{ message_id: string; status: string; send_error: unknown; bot_paused?: boolean }>(`/conversations/${id}/send-audio`, { method: "POST", form });
};

// ---- templates ----
export const listTemplates = (accountId: string) => request<{ templates?: Template[] } | Template[]>(`/whatsapp-accounts/${accountId}/templates`).then((r) => Array.isArray(r) ? r : (r.templates ?? []));
export const submitTemplate = (accountId: string, body: { name: string; language: string; category: string; components: unknown[] }) => request<Template>(`/whatsapp-accounts/${accountId}/templates`, { method: "POST", json: body });
export const syncTemplates = (accountId: string) => request<{ synced: number; templates: Template[] }>(`/whatsapp-accounts/${accountId}/templates/sync`, { method: "POST" });
export const testSend = (accountId: string, templateId: string, body: { to_phone: string; params: string[] }) => request<{ sent: boolean }>(`/whatsapp-accounts/${accountId}/templates/${templateId}/test-send`, { method: "POST", json: body });

// ---- broadcasts ----
export interface BroadcastBody { name?: string; template_name: string; template_language: string; variable_mapping: Record<string, string>; audience: { type: "all" | "tag" | "phones"; tag?: string; phones?: string[] }; confirm?: boolean }
export interface ServerPreview { matched: number; sendable: number; skipped: number; cooldown_skipped?: number; cooldown_days?: number; marketing_gated: number; unknown_phones: number; confirm_threshold: number; hard_cap: number; requires_confirmation: boolean; over_hard_cap: boolean }
export const previewBroadcast = (accountId: string, body: BroadcastBody) => request<ServerPreview>(`/whatsapp-accounts/${accountId}/broadcasts/preview`, { method: "POST", json: body });
export const createBroadcast = (accountId: string, body: BroadcastBody) => request<Broadcast>(`/whatsapp-accounts/${accountId}/broadcasts`, { method: "POST", json: body });
export const listBroadcasts = (accountId: string) => allPages<Broadcast>((limit, offset) => request<{ total: number; broadcasts: Broadcast[] }>(`/whatsapp-accounts/${accountId}/broadcasts${qs({ limit, offset })}`).then((r) => ({ total: r.total, items: r.broadcasts })), 400);
export const getBroadcast = (id: string) => request<Broadcast>(`/broadcasts/${id}`);
export const listRecipients = (id: string) => allPages<BroadcastRecipient>((limit, offset) => request<{ total: number; recipients: BroadcastRecipient[] }>(`/broadcasts/${id}/recipients${qs({ limit, offset })}`).then((r) => ({ total: r.total, items: r.recipients })), 5000);

// ---- contacts ----
export const listContacts = (accountId: string, opts: { search?: string; tag?: string; opted_out?: boolean } = {}) =>
  allPages<Contact>((limit, offset) => request<{ total: number; contacts: Contact[] }>(`/whatsapp-accounts/${accountId}/contacts${qs({ ...opts, limit, offset })}`).then((r) => ({ total: r.total, items: r.contacts })), 5000);
export const importContacts = (accountId: string, contacts: { phone: string; name?: string; tags?: string[]; opted_in?: boolean }[]) =>
  request<Record<string, unknown>>(`/whatsapp-accounts/${accountId}/contacts/import`, { method: "POST", json: { contacts } });
export const optOut = (accountId: string, contactId: string) => request(`/whatsapp-accounts/${accountId}/contacts/${contactId}/opt-out`, { method: "POST" });
export const optIn = (accountId: string, contactId: string) => request(`/whatsapp-accounts/${accountId}/contacts/${contactId}/opt-in`, { method: "POST" });
export const patchContact = (accountId: string, contactId: string, body: { name?: string; tags?: string[] }) => request<Contact>(`/whatsapp-accounts/${accountId}/contacts/${contactId}`, { method: "PATCH", json: body });

// ---- leads ----
export const listCalls = (opts: { direction?: string; answered?: boolean; phone?: string; conversation_id?: string } = {}, max = 1000) =>
  allPages<CallRecord>((limit, offset) => request<{ total: number; calls: CallRecord[] }>(`/calls${qs({ ...opts, limit, offset })}`).then((r) => ({ total: r.total, items: r.calls })), max);
/** Where the <audio> element gets a call recording (302 to a short-lived signed URL). */
export const callRecordingUrl = (callId: string) => `${BASE}/calls/${encodeURIComponent(callId)}/recording?token=${encodeURIComponent(getToken() ?? "")}`;
/** One page of the leads feed: one row per arrival (workflow run), newest first. */
export interface LeadRow { key: string; kind: "run" | "conversation"; arrived_at: string; run: Record<string, unknown> | null; conversation: Record<string, unknown> & { id: string } }
export interface LeadsPage { total: number; limit: number; offset: number; leads: LeadRow[] }
export const listLeadsPage = (opts: { q?: string; source?: string; limit?: number; offset?: number } = {}) =>
  request<LeadsPage>(`/leads${qs({ q: opts.q, source: opts.source, limit: opts.limit ?? 100, offset: opts.offset ?? 0 })}`);
// ---- AI call review (on demand, per patient) ----
export const listCallReviews = () =>
  request<{ reviews: CallReview[] }>("/calls/reviews").then((r) => r.reviews ?? []);
/** Queues the review; the result arrives over SSE as a `call_review` event. */
export const startCallReview = (phone: string) =>
  request<CallReview>("/calls/reviews", { method: "POST", json: { phone } });

export const listRuns = (opts: { contact_phone?: string; whatsapp_account_id?: string; status?: string } = {}, max = 1000) =>
  allPages<WorkflowRun>((limit, offset) => request<{ total: number; runs: WorkflowRun[] }>(`/runs${qs({ ...opts, limit, offset })}`).then((r) => ({ total: r.total, items: r.runs })), max);
export interface RunDetail { workflow_run: WorkflowRun; workflow_node_runs: unknown[]; messages: MessageRecord[]; node_responses: { id?: string; workflow_run_id: string; variable_name: string; question: string; response: string; created_at?: string }[] }
export const getRun = (id: string) => request<RunDetail>(`/runs/${id}`);
export interface SchemaField { key: string; label: string; type: string; options: string[] }
export const leadSchema = () => request<{ workflow_id: string | null; fields: SchemaField[] }>("/leads/schema");
