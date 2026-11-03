from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field,ConfigDict,AliasChoices

class CrmPushConfig(BaseModel):
    """Per-client outbound lead push. When a run ends, the collected variables are
    rendered through `payload_template` and POSTed to `url` - so a client whose
    CRM wants leads directly no longer needs a Google-Sheets Apps Script polling
    the sheet.

    `payload_template` is the "choose what to send" part: CRM key -> @variable
    template. Keys whose variables were never collected are dropped rather than
    sent as literal "@name" text. `static_fields` carries constants merged into
    every payload (an auth key, a source tag) and is REDACTED by the client API."""
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = False
    url: str = ""
    method: Literal["POST", "PUT"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    static_fields: dict[str, Any] = Field(default_factory=dict)
    payload_template: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("payload_template", "payloadTemplate"),
    )
    # Which run endings push a lead. Both by default: most leads never finish the
    # flow, so completion-only would silently drop the majority.
    fire_on: list[Literal["completed", "timeout"]] = Field(
        default_factory=lambda: ["completed", "timeout"],
        validation_alias=AliasChoices("fire_on", "fireOn"),
    )
    timeout_seconds: int = Field(
        default=15,
        validation_alias=AliasChoices("timeout_seconds", "timeoutSeconds"),
    )


class DispositionSyncConfig(BaseModel):
    """Pull call outcomes the CRM reported back, and write them onto the lead's
    sheet row.

    The dispositions live in the relay's OWN Mongo (it already keeps one document
    per Lead_ID, incrementing call_attempt_no, keeping the newest Disposition and
    appending Remarks). We only ever READ that collection - the sheet is the one
    thing we write, because only this backend holds the Google credentials."""
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = False
    # Read-only connection to the relay's cluster. Secret - redacted by the API.
    mongo_uri: str = Field(default="", validation_alias=AliasChoices("mongo_uri", "mongoUri"))
    db_name: str = Field(default="ssb", validation_alias=AliasChoices("db_name", "dbName"))
    collection: str = "crm_dispositions"

    # Where the lead rows live.
    google_connection_id: str = Field(
        default="", validation_alias=AliasChoices("google_connection_id", "googleConnectionId"))
    spreadsheet_id: str = Field(
        default="", validation_alias=AliasChoices("spreadsheet_id", "spreadsheetId"))
    sheet_name: str = Field(default="Sheet1", validation_alias=AliasChoices("sheet_name", "sheetName"))
    # Sheet column that holds the lead id, matched against the CRM's Lead_ID.
    key_column: str = Field(default="lead_id", validation_alias=AliasChoices("key_column", "keyColumn"))

    # sheet column -> field on the disposition document.
    columns: dict[str, str] = Field(default_factory=dict)

    # How far back each sweep re-scans, so a restart or missed tick self-heals
    # without storing any sync bookkeeping.
    lookback_hours: int = Field(
        default=6, validation_alias=AliasChoices("lookback_hours", "lookbackHours"))


# Keys the CRM understands (crm/src/features.ts). Kept in sync by hand.
CRM_FEATURE_KEYS = frozenset({
    "leads", "campaigns", "templates", "contacts",
    "notes", "voiceNotes", "disposition", "customColumns", "calls",
    "callReview",
})


class CallRecordingConfig(BaseModel):
    """Client-settable (Settings → Call recording): the agent names, exactly as
    FasterQ reports them, whose calls belong to this clinic."""
    agent_names: list[str] = Field(default_factory=list)


class Client(BaseModel):
    id: str
    name: str
    username: Optional[str] = None
    password: Optional[str] = None
    long_live_token: Optional[str] = None
    long_live_token_expires_at: Optional[datetime] = None
    status: Literal["active", "inactive"] = "active"
    # Optional outbound CRM integration. None/disabled = nothing is ever sent.
    crm_push: Optional[CrmPushConfig] = None
    # Optional inbound call-outcome sync (relay's Mongo -> this client's sheet).
    disposition_sync: Optional[DispositionSyncConfig] = None
    # CRM: user-defined Leads columns (label/type/options), owned by the CRM UI.
    crm_columns: list[dict[str, Any]] = Field(default_factory=list)
    # CRM feature entitlements, set by Ripplica only (admin routes), never by the
    # client. Absent key = the CRM's default for that feature (on). The CRM reads
    # this off GET /auth/me; the old inbox ignores it.
    features: dict[str, bool] = Field(default_factory=dict)
    # The client's own choices within what Ripplica granted (Settings → Features).
    # Absent key = the CRM's default for that feature. Set via PATCH /clients/{id}.
    feature_prefs: dict[str, bool] = Field(default_factory=dict)
    # Which Leads columns the clinic shows, shared by all its devices of a kind:
    # {"desktop": [...keys], "phone": [...keys]}. Set via PATCH /clients/{id}.
    crm_view: dict[str, list[str]] = Field(default_factory=dict)
    # FasterQ call recordings: which agent names route to this client.
    call_recording: Optional[CallRecordingConfig] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CallRecord(BaseModel):
    """One phone call reported by FasterQ (SIM or WhatsApp call), matched to a
    client by agent name and to a conversation by the customer's number. The
    recording is copied into our private GCS bucket."""
    id: str
    provider: str = "fasterq"
    provider_call_id: str
    client_id: Optional[str] = None
    conversation_id: Optional[str] = None
    contact_phone: str
    agent_name: Optional[str] = None
    agent_email: Optional[str] = None
    agent_phone: Optional[str] = None
    direction: Literal["inbound", "outbound"] = "inbound"
    started_at: Optional[datetime] = None
    duration_seconds: int = 0
    answered: bool = False
    source: Literal["sim", "whatsapp", "unknown"] = "unknown"
    recording_url: Optional[str] = None
    recording_gcs_uri: Optional[str] = None
    recording_status: Literal["none", "pending", "stored", "failed"] = "none"
    recording_error: Optional[str] = None
    recording_attempts: int = 0
    # The lead's "Calls" count is bumped once per outbound call, on first sight.
    call_tried_applied: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CallReviewEntry(BaseModel):
    """One call's own score inside a patient's review. `percent` is computed
    from `scores`, never taken from the model."""
    call_id: str
    percent: int = 0
    scores: dict[str, Any] = Field(default_factory=dict)
    review: str = ""


class CallReviewSkip(BaseModel):
    """A call left out of the review, with the reason, so a patient scored on
    4 of 9 calls explains itself instead of looking wrong."""
    call_id: str
    reason: str


class CallReview(BaseModel):
    """The AI review of ONE patient's calls for one clinic, built on demand when
    an agent presses the button on the Calls page. Keyed by (client_id,
    contact_phone) - not conversation_id, which is optional on CallRecord and
    null for every row the Calls page shows as "not in inbox".

    The document doubles as the job queue: 'queued' is written by the request,
    'running' only by the worker that wins the claim, so "never started" stays
    distinguishable from "died mid-flight"."""
    client_id: str
    contact_phone: str
    conversation_id: Optional[str] = None

    status: Literal["queued", "running", "done", "failed"] = "queued"
    percent: Optional[int] = None
    combined_review: str = ""
    # What the agent never did on ANY call (from the model).
    agent_missed: list[str] = Field(default_factory=list)
    per_call: list[CallReviewEntry] = Field(default_factory=list)
    skipped: list[CallReviewSkip] = Field(default_factory=list)
    # Which calls this result covers, so the UI can offer a re-run when newer
    # calls have arrived and a re-press can spend nothing when they have not.
    calls_covered: list[str] = Field(default_factory=list)

    attempts: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CallTranscript(BaseModel):
    """One call's speaker-labelled transcript. Deliberately its own collection,
    not a field on CallRecord: save_call upserts the whole model, so a late
    "recording ready" webhook holding a stale record would clobber it, and every
    write to `calls` is pushed to open browsers over SSE."""
    call_id: str
    client_id: Optional[str] = None
    contact_phone: str = ""
    text: str = ""
    model: str = ""
    duration_seconds: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class User(BaseModel):
    id: str
    client_id: str
    name: str
    email: str
    role: str = "admin"
    status: Literal["active", "inactive"] = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WhatsAppAccount(BaseModel):
    id: str
    client_id: str

    name: str
    phone_number_id: str
    display_phone_number: Optional[str] = None
    whatsapp_business_account_id: Optional[str] = None

    # Populated from Meta phone-number metadata (e.g. after Embedded Signup).
    verified_name: Optional[str] = None
    quality_rating: Optional[str] = None

    # Per-client Meta credentials. None falls back to the global
    # WHATSAPP_ACCESS_TOKEN env var (the original single-tenant setup).
    # For Embedded-Signup accounts this holds the client-scoped BISU token.
    # Never returned by the API - see redact_account in services.
    access_token: Optional[str] = None
    webhook_verify_token: Optional[str] = None

    status: Literal["connected", "disconnected"] = "connected"

    # Inactivity timeout: if a workflow run sits waiting for the customer's
    # answer longer than `inactivity_timeout_minutes`, the bot closes the run,
    # tells the customer (with `inactivity_timeout_message`), and the next
    # inbound message restarts the flow. Applies to every flow on this number.
    inactivity_timeout_enabled: bool = True
    inactivity_timeout_minutes: int = 15
    inactivity_timeout_message: str = (
        "Your chat was closed due to inactivity. "
        "Send us a message anytime to start again."
    )

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Workflow(BaseModel):
    id: str
    client_id: str
    whatsapp_account_id: str

    created_by_user_id: str
    updated_by_user_id: str

    name: str
    description: Optional[str] = None

    node_ids: list[str] = Field(default_factory=list)
    first_node_id: Optional[str] = None

    # Keyword routing: an incoming message that exactly matches one of
    # these (case-insensitive) starts this workflow. is_default marks the
    # fallback workflow when nothing matches; max one default published
    # per WhatsApp account.
    trigger_keywords: list[str] = Field(default_factory=list)
    is_default: bool = False

    status: Literal["draft", "published", "archived"] = "draft"
    deleted: bool = False

    # Optimistic-concurrency counter, bumped on every graph-mutating edit.
    # A mutating call may pass expected_version to get a 409 on a stale edit.
    version: int = 1

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkflowNode(BaseModel):
    id: str
    client_id: str
    workflow_id: str

    created_by_user_id: str
    updated_by_user_id: str

    name: str
    type: Literal["send_message", "ask_question", "condition", "webhook", "google_sheets", "ai_conversation", "generate_id", "set_variable"]

    next_node_id: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)

    # Canvas coordinates for a visual builder ({"x": .., "y": ..}); display
    # only, ignored by the engine.
    position: Optional[dict[str, float]] = None

    deleted: bool = False

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TokenUsage(BaseModel):
    """LLM token usage + estimated cost, accumulated across a conversation's AI
    turns (on the run and the ai_conversation node run)."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Subset of prompt_tokens served from OpenAI's prefix cache (billed at 0.1x).
    cached_tokens: int = 0
    turns: int = 0
    cost_usd: float = 0.0


class WorkflowRun(BaseModel):
    id: str

    client_id: str
    whatsapp_account_id: str
    workflow_id: str

    contact_phone: str

    status: Literal[
        "active",
        "waiting_for_user",
        "completed",
        "failed",
        "cancelled",
    ] = "active"

    current_node_id: Optional[str] = None
    waiting_at_node_id: Optional[str] = None
    waiting_node_run_id: Optional[str] = None

    variables: dict[str, Any] = Field(default_factory=dict)

    # Outbound CRM push (see CrmPushConfig). Stamped once so a run is never
    # pushed twice - a run can end via completion OR the inactivity sweep, and
    # both call the pusher.
    crm_pushed_at: Optional[datetime] = None
    crm_push_result: Optional[dict[str, Any]] = None

    # LLM token usage accumulated across this conversation's ai_conversation turns.
    token_usage: Optional[TokenUsage] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkflowNodeRun(BaseModel):
    id: str

    client_id: str
    whatsapp_account_id: str
    workflow_id: str
    workflow_run_id: str

    node_id: str
    node_type: str
    node_name: str

    status: Literal[
        "active",
        "waiting_for_user",
        "success",
        "failed",
        "cancelled",
    ] = "active"

    user_input: Optional[dict[str, Any]] = None

    next_node_id: Optional[str] = None

    error: Optional[str] = None

    # For ai_conversation nodes: LLM token usage across this node's turns.
    token_usage: Optional[TokenUsage] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageRecord(BaseModel):
    id: str

    client_id: str
    whatsapp_account_id: str
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    node_run_id: Optional[str] = None

    contact_phone: str

    direction: Literal["incoming", "outgoing"]
    message_type: str = "text"

    text: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    status: str = "created"

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Conversation(BaseModel):
    id: str

    client_id: str
    whatsapp_account_id: str
    contact_phone: str

    contact_name: Optional[str] = None

    status: Literal["open", "resolved", "expired"] = "open"

    # True while a human agent is handling the chat. Set on the first
    # manual send; cleared when the chat is closed/resolved. While True,
    # incoming messages never start or continue workflows.
    bot_paused: bool = False

    active_workflow_run_id: Optional[str] = None

    # WATI-style contact enrichment
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    # Agent-set lead outcome (CRM). Free strings: the value set is per client
    # and lives in the CRM UI. disposition_sync also writes here from the CRM
    # relay (matched on the run's lead_id). Additive - the inbox ignores them.
    disposition: Optional[str] = None
    disposition_remark: Optional[str] = None
    disposition_updated_at: Optional[datetime] = None

    # Acquisition. source is "whatsapp" for organic chats, "ctwa" when the
    # first message arrived through a Click-to-WhatsApp ad (Meta sends a
    # referral object on that message).
    source: str = "whatsapp"
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    # CTWA click id (for Conversions-API ad attribution) + which ad drove the
    # click: source_type ("ad"/"post") and the ad headline.
    ctwa_clid: Optional[str] = None
    source_type: Optional[str] = None
    headline: Optional[str] = None

    last_message_text: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_direction: Optional[Literal["incoming", "outgoing"]] = None

    # Timestamp of the customer's most recent inbound message. Meta's 24-hour
    # customer service window is measured from here: free-form sends are only
    # allowed while now - last_inbound_at < 24h.
    last_inbound_at: Optional[datetime] = None

    unread_count: int = 0

    # Set when an outbound template goes out, cleared by the customer's next
    # inbound. Drives the CRM's "Template msg." tab: a template send is not a
    # conversation until they reply, so it must not crowd the main list.
    # Deliberately NOT cleared by an agent's follow-up text.
    awaiting_template_reply: bool = False
    last_template_at: Optional[datetime] = None

    resolved_at: Optional[datetime] = None
    resolved_by: Optional[Literal["auto", "agent"]] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class NodeResponse(BaseModel):
    id: str

    client_id: str
    whatsapp_account_id: str
    workflow_id: str
    workflow_run_id: str

    node_id: str
    node_run_id: str

    variable_name: str
    question: Optional[str] = None
    response: Any

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GoogleConnection(BaseModel):
    """A stored Google account authorization. Holds the long-lived refresh token
    (V1: not encrypted) used to mint short-lived access tokens at runtime. The
    connection holds only the Google account + token - no spreadsheet id."""
    id: str
    client_id: str
    created_by_user_id: Optional[str] = None

    google_email: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)

    access_token: Optional[str] = None
    refresh_token: str
    token_expiry: Optional[datetime] = None

    status: Literal["connected", "disconnected", "failed"] = "connected"

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FullSetupRequest(BaseModel):
    client: Client
    user: User
    whatsapp_account: WhatsAppAccount
    google_connections: list[GoogleConnection] = Field(default_factory=list)
    workflow: Workflow
    nodes: list[WorkflowNode]


class DevGoogleConnectionRequest(BaseModel):
    connection: GoogleConnection


class EmbeddedSignupCompleteRequest(BaseModel):
    """Sent by the admin console after the Meta Embedded Signup popup finishes.
    Carries the exchangeable code + the WABA/phone ids the flow returned."""
    client_id: str
    code: str
    waba_id: str
    phone_number_id: str
    business_id: Optional[str] = None
    session_id: Optional[str] = None


class RegisterPhoneNumberRequest(BaseModel):
    pin: str


class TestWebhookRequest(BaseModel):
    phone_number_id: str
    from_phone: str
    text: str
    message_type: str = "text"

class SendMessageConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str

    # Optional media attachment (image / PDF document). media_url is either a
    # literal https link OR an @variable resolving to a previously-captured
    # media (a signed GCS URL is then minted at send time). caption falls back
    # to `message`; filename applies to documents.
    media_type: Optional[Literal["image", "document"]] = Field(
        default=None,
        validation_alias=AliasChoices("media_type", "mediaType"),
    )
    media_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("media_url", "mediaUrl"),
    )
    caption: Optional[str] = None
    filename: Optional[str] = None

class AskQuestionOptionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    label: str

    # Optional so an edge can be cut/unwired (null) while a draft is being
    # edited. Publish validation requires it to be set and to point at a
    # real node.
    next_node_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("next_node_id", "nextNodeId"),
    )

class AskQuestionListRowConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    label: str
    description: Optional[str] = None

    next_node_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("next_node_id", "nextNodeId"),
    )

class AskQuestionListSectionConfig(BaseModel):
    """
    Section title
    Row 1
    Row 2
    """
    model_config = ConfigDict(populate_by_name=True)

    title: str
    rows: list[AskQuestionListRowConfig] = Field(default_factory=list)

class AskQuestionListConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    button_text: str = Field(
        default="Choose option",
        validation_alias=AliasChoices("button_text", "buttonText"),
    )

    sections: list[AskQuestionListSectionConfig] = Field(default_factory=list)

class AskQuestionConfig(BaseModel):
    """AskQuestionConfig
    common:
        question
        input_type
        variable_name

    buttons only:
        options

    list only:
        list_config
            button_text
            sections
                rows
                
thus Button node config:

{
  "question": "What do you need help with?",
  "input_type": "buttons",
  "variable_name": "issue_type",
  "options": [
    {
      "id": "track_order",
      "label": "Track Order",
      "next_node_id": "client:meta_test/workflow:support_bot/node:3"
    },
    {
      "id": "return_item",
      "label": "Return Item",
      "next_node_id": "client:meta_test/workflow:support_bot/node:4"
    }
  ]
}

No list_config.


For list, do this:

{
  "question": "What do you need help with?",
  "input_type": "list",
  "variable_name": "issue_type",
  "list_config": {
    "button_text": "Choose option",
    "sections": [
      {
        "title": "Orders",
        "rows": [
          {
            "id": "track_order",
            "label": "Track Order",
            "description": "Check your order status",
            "next_node_id": "client:meta_test/workflow:support_bot/node:3"
          }
        ]
      },
      {
        "title": "Returns",
        "rows": [
          {
            "id": "return_item",
            "label": "Return Item",
            "description": "Start a return request",
            "next_node_id": "client:meta_test/workflow:support_bot/node:4"
          }
        ]
      }
    ]
  }
}

No options"""
    model_config = ConfigDict(populate_by_name=True)

    question: str

    input_type: Literal["text", "buttons", "list"] = Field(
        default="text",
        validation_alias=AliasChoices("input_type", "inputType"),
    )
    # Used only when input_type = "buttons"
    options: list[AskQuestionOptionConfig] = Field(default_factory=list)

    # Used only when input_type = "list"
    list_config: Optional[AskQuestionListConfig] = Field(
        default=None,
        validation_alias=AliasChoices("list_config", "listConfig"),
    )

    variable_name: str = Field(
        validation_alias=AliasChoices("variable_name", "variableName"),
    )

    # Default branch for buttons/list: where a free-text (non-matching) answer
    # goes. None = re-prompt and stay on this node (the automatic "circle
    # back"). Set it to another node's id to route free text there instead.
    default_next_node_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("default_next_node_id", "defaultNextNodeId"),
    )

    # Custom re-prompt text shown on a non-matching answer; falls back to a
    # generated "please choose one of the options" message.
    retry_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("retry_message", "retryMessage"),
    )

    # Per-node toggle: when True the customer's reply is expected to be an
    # uploaded file (image/PDF) and is captured into `variable_name` as a media
    # dict; a text reply re-prompts. Composes with input_type (a text question
    # can just flip this on to collect a file).
    accept_media: bool = Field(
        default=False,
        validation_alias=AliasChoices("accept_media", "acceptMedia"),
    )

    # Optional media the BOT attaches to the question prompt (sent as a leading
    # media message). Same semantics as SendMessageConfig's media fields.
    media_type: Optional[Literal["image", "document"]] = Field(
        default=None,
        validation_alias=AliasChoices("media_type", "mediaType"),
    )
    media_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("media_url", "mediaUrl"),
    )
    caption: Optional[str] = None
    filename: Optional[str] = None


class ConditionRuleConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    variable: str
    operator: Literal["equals", "not_equals"] = "equals"
    value: Any

    next_node_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("next_node_id", "nextNodeId"),
    )

class ConditionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conditions: list[ConditionRuleConfig] = Field(default_factory=list)

    default_next_node_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("default_next_node_id", "defaultNextNodeId"),
    )


class WebhookConfig(BaseModel):
    """Calls an external HTTP endpoint and stores values pulled from the JSON
    response into workflow variables (same store as question answers)."""
    model_config = ConfigDict(populate_by_name=True)

    url: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("query_params", "queryParams"),
    )
    body: Optional[dict[str, Any]] = None
    timeout_seconds: int = Field(
        default=20,
        validation_alias=AliasChoices("timeout_seconds", "timeoutSeconds"),
    )
    # variable_name -> JSON path in the response. Path "$" (or "") stores the
    # WHOLE response body; "$.data.order" is a rooted sub-path; "data.order.status"
    # is a plain path. e.g. {"order_status": "data.order.status", "full_response": "$"}
    extract: dict[str, str] = Field(default_factory=dict)
    # Optional: capture the HTTP status code into this variable so a following
    # condition node can branch on success/failure.
    store_status_in: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("store_status_in", "storeStatusIn"),
    )
    # Opt-in: an HTTP/network failure advances to next_node_id instead of
    # failing the run. Off by default so existing webhooks are unchanged. Pair
    # it with store_status_in and branch on the status in a condition node -
    # that is what makes store_status_in's "branch on success/failure" actually
    # reachable (today the run dies before the condition can run). Use it for
    # enrichment calls that must never cost a live conversation.
    continue_on_error: bool = Field(
        default=False,
        validation_alias=AliasChoices("continue_on_error", "continueOnError"),
    )


class GoogleSheetCellMapping(BaseModel):
    """One WATI-style key->value row: write `value` (resolved from run.variables
    via @variables) into the sheet column named `column`."""
    model_config = ConfigDict(populate_by_name=True)

    column: str
    value: Any


class GoogleSheetReferenceConfig(BaseModel):
    """For update_row: the column/value used to find which rows to update."""
    model_config = ConfigDict(populate_by_name=True)

    column: str
    value: Any


class GoogleSheetsConfig(BaseModel):
    """Insert or update rows in a Google Sheet. The Google token is NOT here -
    the node only references a google_connection_id; the token lives in the
    google_connections collection so many workflows can reuse one account."""
    model_config = ConfigDict(populate_by_name=True)

    google_connection_id: str = Field(
        validation_alias=AliasChoices("google_connection_id", "googleConnectionId"),
    )
    spreadsheet_id: str = Field(
        validation_alias=AliasChoices("spreadsheet_id", "spreadsheetId"),
    )
    sheet_name: str = Field(
        validation_alias=AliasChoices("sheet_name", "sheetName"),
    )

    action: Literal["insert_row", "update_row"]

    # Required only when action == update_row.
    reference: Optional[GoogleSheetReferenceConfig] = None

    mappings: list[GoogleSheetCellMapping] = Field(default_factory=list)

    value_input_option: Literal["RAW", "USER_ENTERED"] = Field(
        default="RAW",
        validation_alias=AliasChoices("value_input_option", "valueInputOption"),
    )

    # Optional: store a compact result summary into this run variable.
    save_result_in: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("save_result_in", "saveResultIn"),
    )


class SetVariableConfig(BaseModel):
    """Writes fixed or @variable-rendered values into run.variables, then advances.

    Exists because nothing else could: generate_id only mints a timestamp id and
    webhook only extracts from a response, so a branch that "knows" something
    (e.g. this lead came from a Meta ad) had no way to record it as a variable -
    only as a literal in a sheet cell, invisible to every later node."""
    model_config = ConfigDict(populate_by_name=True)

    # variable name -> value template, e.g. {"lead_source": "Meta ad"} or
    # {"greeting": "Hello @contact.name"}.
    variables: dict[str, Any] = Field(default_factory=dict)


class GenerateIdConfig(BaseModel):
    """Generates a unique id in-process and stores it into run.variables[variable_name]
    (no external call). Format: <YYYYMMDDHHMMSS>-<8 hex upper>, optionally prefixed
    (prefix "" -> no prefix, e.g. 20260820031857-F4E740A1; prefix "RIP" ->
    RIP-20260820031857-F4E740A1). Replaces the old external lead-id webhook."""
    model_config = ConfigDict(populate_by_name=True)

    variable_name: str = Field(
        default="lead_id",
        validation_alias=AliasChoices("variable_name", "variableName"),
    )
    prefix: str = ""


class AiFieldSpec(BaseModel):
    """One lead field the AI node must collect into run.variables[name].

    `type` shapes validation/normalization; `options` constrains an enum field
    to the EXACT labels the downstream sheet/condition nodes already expect
    (e.g. the JPC pain list). `format_hint` normalizes dates/times per client
    (JPC uses MM/DD/YYYY, Raheja DD/MM/YYYY). A `media` field is captured from
    the patient's uploaded file, never from LLM text."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    required: bool = True
    type: Literal["text", "enum", "date", "time", "number", "media"] = "text"

    # enum only: the exact allowed labels.
    options: list[str] = Field(default_factory=list)
    # enum only: allow the patient's own words when nothing matches (mirrors the
    # existing "type Other if none match" behaviour). False = must pick a label.
    allow_other: bool = Field(
        default=True,
        validation_alias=AliasChoices("allow_other", "allowOther"),
    )
    # date/time: e.g. "MM/DD/YYYY", "DD/MM/YYYY", "9AM-5PM".
    format_hint: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("format_hint", "formatHint"),
    )


class AiToolSpec(BaseModel):
    """One tool the AI node may call mid-conversation. `type` picks which engine
    runner backs it; `config` is that runner's own node config, used as a
    TEMPLATE - the LLM only supplies `args`, never the connection/sheet/url, so
    a hallucinated argument can never redirect a write somewhere else.

    `name` is what the LLM calls (it never sees `type`), and `description` is
    what tells it when to call - both go into the system prompt."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    # No "webhook" yet: the webhook logic lives inline in _run_webhook_node and
    # has no reusable execute_*() entry point like google_sheets does. Offering
    # a tool type that cannot run would be worse than not offering it - add it
    # once that runner is split the same way.
    type: Literal["send_message", "ask_question", "google_sheets", "generate_id"]
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class AiConversationConfig(BaseModel):
    """An LLM-driven conversational node: greets, answers FAQs from `knowledge`,
    collects `fields` into run.variables, then hands back to the existing graph
    (webhook/sheet/confirmation nodes run unchanged). ONE node type, fully
    config-driven - nothing doctor-specific lives in code, so the same node
    serves any clinic. The model is swappable per node via `model` (or the
    AI_NODE_MODEL env default) behind the llm_service adapter."""
    model_config = ConfigDict(populate_by_name=True)

    goal: str
    knowledge: str = ""
    fields: list[AiFieldSpec] = Field(default_factory=list)

    # Tools the AI may call during the conversation (sheet writes, info
    # messages, ad-hoc questions). Empty = the original collect-then-hand-back
    # behaviour, unchanged.
    tools: list[AiToolSpec] = Field(default_factory=list)

    language_hint: str = Field(
        default="Match the patient's language (Hindi/Hinglish/English).",
        validation_alias=AliasChoices("language_hint", "languageHint"),
    )
    # Hard cap on patient turns before the node gives up and hands back whatever
    # it has collected (cost + loop guard).
    max_turns: int = Field(
        default=20,
        validation_alias=AliasChoices("max_turns", "maxTurns"),
    )
    # Optional per-node model override (e.g. "gpt-5-mini", "gemini-2.5-flash").
    model: Optional[str] = None

    # Patient asks for a human -> pause the bot so an agent takes over in inbox.
    handoff_keywords: list[str] = Field(
        default_factory=lambda: ["agent", "human", "call me"],
        validation_alias=AliasChoices("handoff_keywords", "handoffKeywords"),
    )
    # Emergency phrases -> reply immediately with the clinic phone.
    emergency_keywords: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("emergency_keywords", "emergencyKeywords"),
    )
    emergency_message: str = Field(
        default="",
        validation_alias=AliasChoices("emergency_message", "emergencyMessage"),
    )
    # Sent when the LLM/API fails - a blip must NOT kill the patient chat.
    fallback_message: str = Field(
        default="Thanks for your message — our team will get back to you shortly.",
        validation_alias=AliasChoices("fallback_message", "fallbackMessage"),
    )
    # Where to hand back after collection; falls back to node.next_node_id.
    next_node_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("next_node_id", "nextNodeId"),
    )


class UpdateContactRequest(BaseModel):
    contact_name: Optional[str] = None
    attributes: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None


class UpdateDispositionRequest(BaseModel):
    """CRM: agent-set lead outcome on a conversation."""
    disposition: Optional[str] = None
    remark: Optional[str] = None


class UpdateContactFieldsRequest(BaseModel):
    """PATCH a contact's editable fields. `tags` REPLACES the list."""
    name: Optional[str] = None
    tags: Optional[list[str]] = None


class Note(BaseModel):
    """An agent's internal note on a conversation - never sent to the customer."""
    id: str
    client_id: str
    conversation_id: str
    text: str
    author: str = "agent"
    created_at: Optional[datetime] = None


class CreateNoteRequest(BaseModel):
    text: str


class LoginRequest(BaseModel):
    username: str
    password: str


### Platform CRUD request bodies

class CreateClientRequest(BaseModel):
    name: str
    username: str
    password: str


class UpdateClientRequest(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    status: Optional[Literal["active", "inactive"]] = None
    crm_push: Optional[CrmPushConfig] = None
    disposition_sync: Optional[DispositionSyncConfig] = None
    crm_columns: Optional[list[dict[str, Any]]] = None
    # Merged into Client.feature_prefs (send only the keys to change).
    feature_prefs: Optional[dict[str, bool]] = None
    # Merged into Client.crm_view (send "desktop" and/or "phone").
    crm_view: Optional[dict[str, list[str]]] = None
    # Replaces Client.call_recording (the agent-name list).
    call_recording: Optional[CallRecordingConfig] = None


class StartCallReviewRequest(BaseModel):
    """Body of POST /calls/reviews - the patient's number, which is how the
    Calls page identifies a row (conversation_id is null for "not in inbox")."""
    phone: str


class SetClientFeaturesRequest(BaseModel):
    """Admin-only: merge these keys into Client.features (true restores one)."""
    features: dict[str, bool]


class CreateUserRequest(BaseModel):
    name: str
    email: str
    role: str = "admin"


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[Literal["active", "inactive"]] = None


class CreateWhatsAppAccountRequest(BaseModel):
    name: str
    phone_number_id: str
    display_phone_number: Optional[str] = None
    whatsapp_business_account_id: Optional[str] = None
    access_token: Optional[str] = None
    webhook_verify_token: Optional[str] = None


class UpdateWhatsAppAccountRequest(BaseModel):
    name: Optional[str] = None
    phone_number_id: Optional[str] = None
    display_phone_number: Optional[str] = None
    whatsapp_business_account_id: Optional[str] = None
    access_token: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    status: Optional[Literal["connected", "disconnected"]] = None
    inactivity_timeout_enabled: Optional[bool] = None
    inactivity_timeout_minutes: Optional[int] = None
    inactivity_timeout_message: Optional[str] = None


class WorkflowNodeInput(BaseModel):
    """Node as clients send it: a short local id ("welcome", "ask_issue").
    The server namespaces it under the workflow id and rewrites every
    next_node_id reference, so callers never build full ids."""
    id: str
    name: str
    type: Literal["send_message", "ask_question", "condition", "webhook", "google_sheets", "ai_conversation", "generate_id", "set_variable"]
    next_node_id: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    position: Optional[dict[str, float]] = None


class CreateWorkflowRequest(BaseModel):
    whatsapp_account_id: str
    created_by_user_id: str
    name: str
    description: Optional[str] = None
    first_node_id: str
    trigger_keywords: list[str] = Field(default_factory=list)
    is_default: bool = False
    nodes: list[WorkflowNodeInput]


class UpdateWorkflowRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    first_node_id: Optional[str] = None
    trigger_keywords: Optional[list[str]] = None
    is_default: Optional[bool] = None


class UpdateWorkflowNodeRequest(BaseModel):
    name: Optional[str] = None
    next_node_id: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    position: Optional[dict[str, float]] = None


class ConnectionChange(BaseModel):
    source_node_id: str
    handle: str = "default"
    target_node_id: Optional[str] = None


class UpdateConnectionsRequest(BaseModel):
    changes: list[ConnectionChange]


class AgentSendRequest(BaseModel):
    text: str


### the below are just for testing purposes
class SendWhatsAppTestRequest(BaseModel):
    phone_number_id: str
    to_phone: str
    text: str


class SendWhatsAppButtonTestRequest(BaseModel):
    phone_number_id: str
    to_phone: str
    text: str

class SendWhatsAppListTestRequest(BaseModel):
    phone_number_id: str
    to_phone: str
    body_text: str
    list_config: dict


# =====================================================================
# Templates / Contacts / Broadcasts
# =====================================================================

class Template(BaseModel):
    """Local mirror of a WhatsApp message template submitted to Meta. Templates
    live at the WABA level; status is updated by Meta's approval webhook or a
    manual sync. Only APPROVED templates may be sent."""
    id: str
    client_id: str
    whatsapp_account_id: str
    waba_id: str

    name: str
    language: str
    category: Literal["MARKETING", "UTILITY", "AUTHENTICATION"]
    # Raw Meta component JSON (HEADER/BODY/FOOTER/BUTTONS), passed through as-is.
    components: list[dict[str, Any]] = Field(default_factory=list)
    # Number of {{n}} placeholders in the BODY - used to validate send params.
    body_variable_count: int = 0

    # Meta emits many statuses over time (PENDING/APPROVED/REJECTED/PAUSED/
    # DISABLED/PENDING_DELETION/FLAGGED/IN_APPEAL…). Kept as a plain string so a
    # new Meta status can never fail validation and break template reads.
    status: str = "PENDING"
    meta_template_id: Optional[str] = None
    rejected_reason: Optional[str] = None

    created_by_user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Contact(BaseModel):
    """A reachable audience member, auto-captured from inbound messages (dedup
    per account+phone) or bulk-imported. opted_out excludes them from broadcasts."""
    id: str
    client_id: str
    whatsapp_account_id: str

    phone: str
    name: Optional[str] = None
    source: Literal["inbound", "ctwa", "import"] = "inbound"

    opted_out: bool = False
    # Positive marketing consent (distinct from the hard opted_out block). Set
    # True when the contact engages (inbound/CTWA) or explicitly opts in; cold
    # imports stay False until flagged. Required for MARKETING-category sends.
    marketing_opt_in: bool = False
    tags: list[str] = Field(default_factory=list)

    last_inbound_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _empty_counts() -> dict[str, int]:
    return {"total": 0, "pending": 0, "sent": 0, "delivered": 0,
            "read": 0, "failed": 0, "skipped": 0}


class Broadcast(BaseModel):
    """A campaign: one approved template sent to an audience. Recipients are
    materialized into broadcast_recipients and drained by the background worker."""
    id: str
    client_id: str
    whatsapp_account_id: str

    name: Optional[str] = None
    template_name: str
    template_language: str
    # {"1": "@contact.name", "2": "static text"} - fills BODY {{n}} per recipient.
    variable_mapping: dict[str, Any] = Field(default_factory=dict)
    # {"type": "all"|"tag"|"phones", "tag": .., "phones": [..]}
    audience: dict[str, Any] = Field(default_factory=dict)

    status: Literal["draft", "queued", "running", "paused", "completed", "cancelled"] = "queued"
    counts: dict[str, int] = Field(default_factory=_empty_counts)

    created_by_user_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BroadcastRecipient(BaseModel):
    """One send task in a broadcast. The worker claims pending rows atomically
    (pending->sending) so instances never double-send; delivery/read come back
    via the status webhook matched on meta_message_id."""
    id: str
    broadcast_id: str
    client_id: str
    whatsapp_account_id: str

    contact_phone: str
    params: list[str] = Field(default_factory=list)

    status: Literal[
        "pending", "sending", "sent", "delivered", "read", "failed", "skipped"
    ] = "pending"
    meta_message_id: Optional[str] = None
    error: Optional[Any] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreateTemplateRequest(BaseModel):
    name: str
    language: str
    category: Literal["MARKETING", "UTILITY", "AUTHENTICATION"]
    components: list[dict[str, Any]]


class TestSendTemplateRequest(BaseModel):
    to_phone: str
    params: list[str] = Field(default_factory=list)


class ImportContactItem(BaseModel):
    phone: str
    name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    opted_in: bool = False  # assert documented marketing consent for this row


class ImportContactsRequest(BaseModel):
    contacts: list[ImportContactItem]


class BroadcastAudience(BaseModel):
    type: Literal["all", "tag", "phones"] = "all"
    tag: Optional[str] = None
    phones: list[str] = Field(default_factory=list)


class CreateBroadcastRequest(BaseModel):
    name: Optional[str] = None
    template_name: str
    template_language: str
    variable_mapping: dict[str, Any] = Field(default_factory=dict)
    audience: BroadcastAudience = Field(default_factory=BroadcastAudience)
    # Must be true to proceed when the audience exceeds the confirm threshold.
    confirm: bool = False
