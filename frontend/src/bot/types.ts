/**
 * Data contracts for the CRM.
 *
 * Everything under "Backend contracts" mirrors the real API shapes in the
 * backend (models.py / the inbox payload in frontend/src/types.ts) so that
 * wiring the API later is a data-source swap, not a rewrite. "CRM-only" types
 * are fields the backend does not have yet — see BACKEND_GAPS.md.
 */

// --------------------------------------------------------------------------- //
// Flow / lead-field schema (per client) — kept from the mockup
// --------------------------------------------------------------------------- //

export type FieldType = "text" | "enum" | "date" | "phone" | "tags" | "media";
export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];
}

/** A client's configured flow = the lead fields it collects. */
export interface Flow {
  id: string;
  name: string;
  fields: FieldDef[];
}

// --------------------------------------------------------------------------- //
// Backend contracts
// --------------------------------------------------------------------------- //

export type ConversationStatus = "open" | "resolved" | "expired";
export type ConversationSource = "whatsapp" | "ctwa";

/** Mirrors the inbox `Conversation` payload (to_inbox_conversation). */
export interface Conversation {
  id: string;
  whatsapp_account_id: string;
  contact_phone: string;
  contact_name: string | null;
  status: ConversationStatus;
  bot_paused: boolean;
  tags: string[];
  attributes: Record<string, string>;
  source: ConversationSource;
  source_id: string | null;
  source_url: string | null;
  ctwa_clid: string | null;
  source_type: string | null;
  headline: string | null;
  last_message_text: string | null;
  last_message_at: string | null;
  last_message_direction: "incoming" | "outgoing" | null;
  /** Drives the 24-hour customer-service window. null = never wrote in. */
  last_inbound_at: string | null;
  /** True from an outbound template until the customer replies. Drives the
   * "Template msg." tab; an agent's follow-up text does NOT clear it. */
  awaiting_template_reply: boolean;
  last_template_at?: string | null;
  unread_count: number;
  resolved_at: string | null;
  resolved_by: "auto" | "agent" | null;
  created_at: string;
  active_workflow_run_id: string | null;
  /** Backend (Phase A): agent-set lead outcome. */
  disposition?: string | null;
  disposition_remark?: string | null;
  /** Backend: the CRM-owned slice of attributes (call_tried / remark / custom). */
  crm?: { call_tried?: number; remark?: string; custom?: Record<string, string | number | boolean> };
}

export type MessageType =
  | "text"
  | "template"
  | "interactive_buttons"
  | "interactive_list"
  | "image"
  | "document"
  | "audio";
export type MessageStatus = "created" | "sent" | "delivered" | "read" | "failed";
/** Who produced an outgoing message; absent = the bot/workflow engine. */
export type SentBy = "agent" | "template" | "broadcast" | "inactivity_timeout";

export interface ListOption {
  id?: string;
  label: string;
  description?: string;
}
export interface ListSection {
  title: string;
  rows: ListOption[];
}
export interface MediaMeta {
  type: "image" | "document" | "audio";
  mime_type?: string;
  filename?: string;
  caption?: string;
  voice?: boolean;
  duration?: number;
  error?: string;
  /** Mock-only: local blob/data URL. The backend serves /media/{id} instead. */
  src?: string;
}
export interface StatusHistoryEntry {
  status: MessageStatus;
  received_at: string;
  previous_status?: MessageStatus | null;
}
export interface MessageMetadata {
  sent_by?: SentBy;
  template?: { name: string; language: string; params: string[] };
  broadcast_id?: string;
  options?: ListOption[];
  list_config?: { button_text?: string; sections: ListSection[] };
  media?: MediaMeta;
  /** Human label of a button/list reply the customer tapped. */
  reply_title?: string;
  reply_to_wamid?: string;
  meta_message_id?: string;
  send_error?: string;
  status_history?: StatusHistoryEntry[];
}

/** Mirrors the inbox `MessageRecord` payload (to_inbox_message). */
export interface MessageRecord {
  id: string;
  whatsapp_account_id: string;
  contact_phone: string;
  direction: "incoming" | "outgoing";
  message_type: MessageType;
  text: string | null;
  metadata: MessageMetadata;
  status: MessageStatus;
  created_at: string;
}

// ---- Templates (models.Template; components in Meta's format) ----

export type TemplateCategory = "MARKETING" | "UTILITY" | "AUTHENTICATION";
export const TEMPLATE_CATEGORIES: TemplateCategory[] = ["MARKETING", "UTILITY", "AUTHENTICATION"];
export type TemplateStatus = "APPROVED" | "PENDING" | "REJECTED";

export interface TemplateComponent {
  type: "HEADER" | "BODY" | "FOOTER" | "BUTTONS";
  format?: "TEXT" | "IMAGE" | "DOCUMENT";
  text?: string;
  example?: { body_text?: string[][]; header_text?: string[] };
  buttons?: { type: string; text: string; url?: string }[];
}

export interface Template {
  id: string;
  whatsapp_account_id: string;
  waba_id: string;
  name: string;
  language: string;
  category: TemplateCategory;
  components: TemplateComponent[];
  body_variable_count: number;
  status: TemplateStatus;
  meta_template_id: string | null;
  rejected_reason: string | null;
  created_at: string;
}

// ---- Contacts (models.Contact) ----

export type ContactSource = "inbound" | "ctwa" | "import";
export interface Contact {
  id: string;
  whatsapp_account_id: string;
  phone: string;
  name: string | null;
  source: ContactSource;
  opted_out: boolean;
  marketing_opt_in: boolean;
  tags: string[];
  last_inbound_at: string | null;
  created_at: string;
}

// ---- Broadcasts (models.Broadcast / BroadcastRecipient) ----

export type BroadcastStatus = "draft" | "queued" | "running" | "paused" | "completed" | "cancelled";
export type RecipientStatus = "pending" | "sending" | "sent" | "delivered" | "read" | "failed" | "skipped";
export interface BroadcastCounts {
  total: number;
  pending: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  skipped: number;
}
export interface BroadcastRecipient {
  id: string;
  broadcast_id: string;
  contact_phone: string;
  contact_name: string | null;
  params: string[];
  status: RecipientStatus;
  meta_message_id: string | null;
  error: string | null;
  sent_at: string | null;
}
export interface Broadcast {
  id: string;
  whatsapp_account_id: string;
  name: string;
  template_name: string;
  template_language: string;
  /** e.g. {"1": "@contact.name|there"} */
  variable_mapping: Record<string, string>;
  audience: { type: "all" | "tag" | "phones"; tag?: string; count?: number };
  status: BroadcastStatus;
  counts: BroadcastCounts;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
/** Mirrors POST /broadcasts/preview. */
export interface BroadcastPreview {
  matched: number;
  sendable: number;
  skipped: number;
  /** of `skipped`: numbers this client already broadcast the template to recently */
  cooldown_skipped: number;
  cooldown_days: number;
  duplicates: number;
  unknown_phones: number;
  opted_out: number;
  requires_confirmation: boolean;
  over_hard_cap: boolean;
  confirm_threshold: number;
  hard_cap: number;
}

// ---- Workflow runs = the lead record (models.WorkflowRun / NodeResponse) ----

export type RunStatus = "active" | "waiting_for_user" | "completed" | "failed" | "cancelled";
export interface CrmPushResult {
  reason: "completed" | "timeout";
  status_code?: number;
  ok: boolean;
  terminal: boolean;
  attempts: number;
  skipped_fields?: string[];
  error?: string;
  last_attempt_at: string;
}
export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  turns: number;
  cost_usd: number;
}
export interface WorkflowRun {
  id: string;
  whatsapp_account_id: string;
  workflow_id: string;
  contact_phone: string;
  status: RunStatus;
  /** The collected lead fields, keyed by FieldDef.key. */
  variables: Record<string, string>;
  crm_pushed_at: string | null;
  crm_push_result: CrmPushResult | null;
  token_usage: TokenUsage | null;
  started_at: string;
  completed_at: string | null;
}
export interface NodeResponse {
  id: string;
  workflow_run_id: string;
  variable_name: string;
  question: string;
  response: string;
  at: string;
}

// ---- Settings (models.WhatsAppAccount / Client / GET /usage) ----

export interface WhatsAppAccount {
  id: string;
  name: string;
  phone_number_id: string;
  display_phone_number: string;
  whatsapp_business_account_id: string;
  verified_name: string | null;
  quality_rating: "GREEN" | "YELLOW" | "RED" | "UNKNOWN";
  status: "connected" | "disconnected";
  inactivity_timeout_enabled: boolean;
  inactivity_timeout_minutes: number;
  inactivity_timeout_message: string;
}
export interface ClientSettings {
  id: string;
  name: string;
  username: string;
  crm_push: { enabled: boolean; url: string; method: "POST" | "PUT"; fire_on: string[] } | null;
  disposition_sync: { enabled: boolean; sheet_name: string; lookback_hours: number } | null;
  users: { id: string; name: string; email: string; role: string }[];
  crm_columns?: CustomColumn[];
  /** the clinic's own Settings → Features choices (server-stored) */
  feature_prefs?: Record<string, boolean>;
  /** visible Leads columns, one set per device kind, shared by the clinic */
  crm_view?: { desktop?: string[]; phone?: string[] };
  /** FasterQ agent names whose calls belong to this clinic */
  call_recording?: { agent_names: string[] };
}

/** One phone call reported by FasterQ, as GET /calls returns it. */
export interface CallRecord {
  id: string;
  provider: string;
  provider_call_id: string;
  client_id: string | null;
  conversation_id: string | null;
  contact_phone: string;
  contact_name?: string | null;
  agent_name: string | null;
  agent_email: string | null;
  agent_phone: string | null;
  direction: "inbound" | "outbound";
  started_at: string | null;
  duration_seconds: number;
  answered: boolean;
  source: "sim" | "whatsapp" | "unknown";
  recording_url: string | null;
  recording_gcs_uri: string | null;
  recording_status: "none" | "pending" | "stored" | "failed";
  recording_error: string | null;
  created_at?: string;
}
/** One call's own score inside a patient's review. `percent` is computed from
 * `scores` on the server, never invented by the model. */
export interface CallReviewEntry {
  call_id: string;
  percent: number;
  scores: Record<string, number | null>;
  review: string;
}
export interface CallReviewSkip { call_id: string; reason: string }
/** The AI review of one patient's calls, as GET /calls/reviews returns it. */
export interface CallReview {
  client_id: string;
  contact_phone: string;
  conversation_id: string | null;
  status: "queued" | "running" | "done" | "failed";
  percent: number | null;
  combined_review: string;
  /** What the agent never did on any call. */
  agent_missed: string[];
  per_call: CallReviewEntry[];
  /** Calls left out, with the reason (too short, no recording, not answered). */
  skipped: CallReviewSkip[];
  calls_covered: string[];
  attempts: number;
  error: string | null;
  updated_at?: string | null;
}

export interface AiUsageMonth {
  month: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  turns: number;
  cost_usd: number;
}
export interface AiUsage {
  current_month: AiUsageMonth | null;
  months: AiUsageMonth[];
  totals: Omit<AiUsageMonth, "month">;
}

// --------------------------------------------------------------------------- //
// CRM-only (not in the backend yet — see BACKEND_GAPS.md)
// --------------------------------------------------------------------------- //

export type Disposition =
  | "DID_NOT_CONNECT"
  | "FOLLOW_UP_REQUIRED"
  | "INTERESTED"
  | "APPOINTMENT_REQUESTED"
  | "NOT_INTERESTED"
  | "Repeated";
export const DISPOSITIONS: Disposition[] = [
  "DID_NOT_CONNECT",
  "FOLLOW_UP_REQUIRED",
  "INTERESTED",
  "APPOINTMENT_REQUESTED",
  "NOT_INTERESTED",
  "Repeated",
];

export type CustomColumnType = "text" | "number" | "date" | "checkbox" | "dropdown";
/** A user-defined Leads column (the Google-Sheets column types). Definitions are per client. */
export interface CustomColumn {
  key: string;
  label: string;
  type: CustomColumnType;
  options?: string[];
}
export type CustomValue = string | number | boolean;

/** Agent-only lead fields, keyed by conversation id.
 *  Backend: disposition -> Conversation.disposition; call_tried/remark/custom -> Conversation.attributes. */
export interface CrmFields {
  disposition: Disposition | "";
  call_tried: number;
  remark: string;
  custom: Record<string, CustomValue>;
}

/** Internal agent note — local-only, the backend has no notes feature. */
export interface Note {
  id: string;
  conversation_id: string;
  text: string;
  at: string;
}

// --------------------------------------------------------------------------- //
// Derived view used by the Leads table / Pipeline
// --------------------------------------------------------------------------- //

/** Conversation ⨝ its latest run ⨝ CRM fields — what the grid and kanban render. */
export interface Lead {
  id: string; // = conversation id (disposition / remark / calls are per patient)
  /** One row per arrival: the run id (or the conversation id when no flow ran). React key + grouping. */
  rowKey: string;
  /** When this visit started (run started_at, else conversation created_at). */
  arrivedAt: string;
  conversation: Conversation;
  run: WorkflowRun | null;
  crm: CrmFields;
  name: string;
  phone: string;
  /** Lead fields = run.variables (keyed by FieldDef.key). */
  fields: Record<string, string>;
  createdAt: string;
  lastActivityAt: string;
}

export type Density = "compact" | "cozy" | "comfortable";
