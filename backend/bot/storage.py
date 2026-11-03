from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from backend.bot.utils import now_utc, short_id
from backend.bot.database import (
    clients_collection,
    users_collection,
    whatsapp_accounts_collection,
    workflows_collection,
    workflow_nodes_collection,
    workflow_runs_collection,
    workflow_node_runs_collection,
    messages_collection,
    node_responses_collection,
    conversations_collection,
    google_connections_collection,
    templates_collection,
    contacts_collection,
    broadcasts_collection,
    broadcast_recipients_collection,
    ai_usage_monthly_collection,
    notes_collection,
    calls_collection,
    call_reviews_collection,
    call_transcripts_collection,
)
from backend.bot.models import (
    Client,
    User,
    WhatsAppAccount,
    Workflow,
    WorkflowNode,
    WorkflowRun,
    WorkflowNodeRun,
    MessageRecord,
    NodeResponse,
    Conversation,
    GoogleConnection,
    Template,
    Contact,
    Broadcast,
    BroadcastRecipient,
    Note,
    CallRecord,
    CallReview,
    CallTranscript,
)


def model_to_dict(model):
    data = model.model_dump(mode="python")

    data.pop("created_at", None)
    data.pop("updated_at", None)

    return data


def parse_model(model_class, document):
    if not document:
        return None

    document = dict(document)
    document.pop("_id", None)

    return model_class(**document)


def upsert_document(collection, key_filter: dict, document: dict):
    current_time = now_utc()
    document["updated_at"] = current_time

    collection.update_one(
        key_filter,
        {
            "$set": document,
            "$setOnInsert": {
                "created_at": current_time,
            },
        },
        upsert=True,
    )


def paginated_find(
    collection,
    query: dict,
    model_class,
    sort_field: str,
    sort_direction: int,
    limit: int,
    offset: int,
):
    """Shared shape for every list endpoint: total count + one page."""
    total = collection.count_documents(query)

    documents = (
        collection.find(query)
        .sort(sort_field, sort_direction)
        .skip(offset)
        .limit(limit)
    )

    items = [parse_model(model_class, document) for document in documents]

    return total, items


def save_client(client: Client):
    upsert_document(
        clients_collection,
        {"id": client.id},
        model_to_dict(client),
    )


def get_client_by_id(client_id: str) -> Optional[Client]:
    document = clients_collection.find_one({"id": client_id})
    return parse_model(Client, document)


def get_client_by_username(username: str) -> Optional[Client]:
    document = clients_collection.find_one({"username": username})
    return parse_model(Client, document)


def list_clients(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    query = {}
    if status:
        query["status"] = status

    return paginated_find(
        clients_collection, query, Client, "created_at", -1, limit, offset
    )


def get_user_by_id(user_id: str) -> Optional[User]:
    document = users_collection.find_one({"id": user_id})
    return parse_model(User, document)


def list_users_for_client(client_id: str) -> list[User]:
    documents = users_collection.find({"client_id": client_id}).sort("created_at", 1)
    return [parse_model(User, document) for document in documents]


def list_whatsapp_accounts_for_client(client_id: str) -> list[WhatsAppAccount]:
    documents = whatsapp_accounts_collection.find(
        {"client_id": client_id}
    ).sort("created_at", 1)
    return [parse_model(WhatsAppAccount, document) for document in documents]


def save_user(user: User):
    upsert_document(
        users_collection,
        {"id": user.id},
        model_to_dict(user),
    )


def save_whatsapp_account(account: WhatsAppAccount):
    upsert_document(
        whatsapp_accounts_collection,
        {"id": account.id},
        model_to_dict(account),
    )


def get_whatsapp_account_by_phone_number_id(
    phone_number_id: str,
) -> Optional[WhatsAppAccount]:
    document = whatsapp_accounts_collection.find_one(
        {"phone_number_id": phone_number_id}
    )
    return parse_model(WhatsAppAccount, document)


def save_workflow(workflow: Workflow):
    upsert_document(
        workflows_collection,
        {"id": workflow.id},
        model_to_dict(workflow),
    )


def get_workflow_by_id(workflow_id: str) -> Optional[Workflow]:
    document = workflows_collection.find_one({"id": workflow_id})
    return parse_model(Workflow, document)


def save_google_connection(connection: GoogleConnection):
    upsert_document(
        google_connections_collection,
        {"id": connection.id},
        model_to_dict(connection),
    )


def get_google_connection_by_id(connection_id: str) -> Optional[GoogleConnection]:
    document = google_connections_collection.find_one({"id": connection_id})
    return parse_model(GoogleConnection, document)


def get_published_workflows_for_account(
    client_id: str,
    whatsapp_account_id: str,
) -> list[Workflow]:
    documents = workflows_collection.find(
        {
            "client_id": client_id,
            "whatsapp_account_id": whatsapp_account_id,
            "status": "published",
            "deleted": False,
        }
    )

    return [
        parse_model(Workflow, document)
        for document in documents
    ]


def list_workflows_for_client(
    client_id: str,
    whatsapp_account_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    query = {
        "client_id": client_id,
        "deleted": False,
    }

    if whatsapp_account_id:
        query["whatsapp_account_id"] = whatsapp_account_id

    if status:
        query["status"] = status

    return paginated_find(
        workflows_collection, query, Workflow, "created_at", -1, limit, offset
    )


def save_workflow_node(node: WorkflowNode):
    upsert_document(
        workflow_nodes_collection,
        {"id": node.id},
        model_to_dict(node),
    )


def get_workflow_node_by_id(node_id: str) -> Optional[WorkflowNode]:
    document = workflow_nodes_collection.find_one({"id": node_id})
    return parse_model(WorkflowNode, document)


def soft_delete_missing_workflow_nodes(workflow_id: str, keep_ids: list[str]):
    """Marks nodes of the workflow that are NOT in keep_ids as deleted.
    Used when a whole graph is re-saved with nodes removed."""
    workflow_nodes_collection.update_many(
        {
            "workflow_id": workflow_id,
            "id": {"$nin": keep_ids},
            "deleted": False,
        },
        {
            "$set": {
                "deleted": True,
                "updated_at": now_utc(),
            },
        },
    )



def get_workflow_nodes(workflow_id: str) -> list[WorkflowNode]:
    documents = workflow_nodes_collection.find(
        {
            "workflow_id": workflow_id,
            "deleted": False,
        }
    )

    return [
        parse_model(WorkflowNode, document)
        for document in documents
    ]


def save_workflow_run(run: WorkflowRun):
    upsert_document(
        workflow_runs_collection,
        {"id": run.id},
        model_to_dict(run),
    )


def save_run_crm_result(run_id: str, crm_pushed_at, crm_push_result: dict):
    """Persist ONLY the CRM outcome fields.

    Deliberately not save_workflow_run(): that upserts the whole model, so a
    caller holding a run loaded before some other code changed it writes the
    stale copy back over everything. That is exactly how the timeout sweep
    resurrected cancelled runs and re-sent the closing message every 15 minutes -
    it hands push_lead_to_crm a run whose in-memory status is still
    waiting_for_user. Recording a CRM result must not be able to touch status,
    variables or waiting_at_node_id."""
    workflow_runs_collection.update_one(
        {"id": run_id},
        {"$set": {
            "crm_pushed_at": crm_pushed_at,
            "crm_push_result": crm_push_result,
            "updated_at": now_utc(),
        }},
    )


def record_ai_usage(client_id: str, run_id: str, node_run_id: str, prompt: int,
                    completion: int, total: int, cost_usd: float, cached: int = 0):
    """Accumulate one AI turn's token usage into the per-client monthly counter.

    The per-run and per-node totals are NOT written here: they are accumulated on
    the in-memory models in services._ai_record_usage and persisted by the AI
    flow's own save_workflow_run / save_workflow_node_run. A dotted $inc here would
    (a) be clobbered the instant that full-document save runs, and (b) actually
    raise on the very first turn — the docs are saved with `token_usage: null`, and
    Mongo cannot $inc a field inside a null, which previously aborted this whole
    function (monthly rollup included). Monthly is its own collection with no such
    null field, so it stays a safe upsert."""
    now = now_utc()
    month = now.strftime("%Y-%m")
    ai_usage_monthly_collection.update_one(
        {"client_id": client_id, "month": month},
        {
            "$inc": {
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "total_tokens": int(total or 0),
                "cached_tokens": int(cached or 0),
                "turns": 1,
                "cost_usd": float(cost_usd or 0.0),
            },
            "$set": {"updated_at": now},
            "$setOnInsert": {"client_id": client_id, "month": month, "created_at": now},
        },
        upsert=True,
    )


def get_client_ai_usage(client_id: str, months: int = 6) -> list[dict]:
    """Recent monthly AI-usage rows for a client, newest first."""
    rows = list(
        ai_usage_monthly_collection.find({"client_id": client_id}, {"_id": 0})
        .sort("month", -1)
        .limit(months)
    )
    return rows


def get_workflow_run_by_id(run_id: str) -> Optional[WorkflowRun]:
    document = workflow_runs_collection.find_one({"id": run_id})
    return parse_model(WorkflowRun, document)


def find_run_by_lead_id(client_id: str, lead_id: str) -> Optional[WorkflowRun]:
    """The run whose generate_id node stamped this lead_id (index: variables.lead_id)."""
    document = workflow_runs_collection.find_one(
        {"client_id": client_id, "variables.lead_id": lead_id}
    )
    return parse_model(WorkflowRun, document)


def find_active_workflow_run(
    client_id: str,
    whatsapp_account_id: str,
    contact_phone: str,
) -> Optional[WorkflowRun]:
    document = workflow_runs_collection.find_one(
        {
            "client_id": client_id,
            "whatsapp_account_id": whatsapp_account_id,
            "contact_phone": contact_phone,
            "status": {
                "$in": ["active", "waiting_for_user"],
            },
        },
        sort=[("updated_at", -1)],
    )

    return parse_model(WorkflowRun, document)


def find_waiting_runs_older_than(
    whatsapp_account_id: str,
    cutoff,
) -> list[WorkflowRun]:
    """Runs stuck waiting for a customer answer whose last state change is older
    than `cutoff` - i.e. the customer has gone silent mid-flow. Backed by the
    (whatsapp_account_id, status, updated_at) index so the sweep stays cheap."""
    documents = workflow_runs_collection.find(
        {
            "whatsapp_account_id": whatsapp_account_id,
            "status": "waiting_for_user",
            "updated_at": {"$lt": cutoff},
        }
    )
    return [parse_model(WorkflowRun, document) for document in documents]


def claim_run_for_timeout(run_id: str) -> bool:
    """Atomically flip a waiting run to cancelled. Returns True only if THIS call
    won the flip - the guard that stops multiple instances (or overlapping
    sweeps) from closing the same run and double-messaging the customer."""
    document = workflow_runs_collection.find_one_and_update(
        {"id": run_id, "status": "waiting_for_user"},
        {"$set": {"status": "cancelled", "completed_at": now_utc()}},
    )
    return document is not None


def list_accounts_with_inactivity_enabled() -> list[WhatsAppAccount]:
    """Connected accounts that have the inactivity timeout turned on - the set
    the sweep iterates over."""
    # $ne False (not "== True") so accounts saved before this field existed -
    # which have no key stored - are still swept, matching the model default.
    documents = whatsapp_accounts_collection.find(
        {
            "status": "connected",
            "inactivity_timeout_enabled": {"$ne": False},
        }
    )
    return [parse_model(WhatsAppAccount, document) for document in documents]


def list_workflow_runs(
    client_id: str,
    whatsapp_account_id: str | None = None,
    workflow_id: str | None = None,
    contact_phone: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    query = {"client_id": client_id}

    if whatsapp_account_id:
        query["whatsapp_account_id"] = whatsapp_account_id

    if workflow_id:
        query["workflow_id"] = workflow_id

    if contact_phone:
        query["contact_phone"] = contact_phone

    if status:
        query["status"] = status

    return paginated_find(
        workflow_runs_collection, query, WorkflowRun, "created_at", -1, limit, offset
    )


def save_workflow_node_run(node_run: WorkflowNodeRun):
    upsert_document(
        workflow_node_runs_collection,
        {"id": node_run.id},
        model_to_dict(node_run),
    )


def get_workflow_node_run_by_id(
    node_run_id: str,
) -> Optional[WorkflowNodeRun]:
    document = workflow_node_runs_collection.find_one({"id": node_run_id})
    return parse_model(WorkflowNodeRun, document)


def save_message(message: MessageRecord):
    upsert_document(
        messages_collection,
        {"id": message.id},
        model_to_dict(message),
    )


def save_node_response(response: NodeResponse):
    upsert_document(
        node_responses_collection,
        {"id": response.id},
        model_to_dict(response),
    )


def get_message_by_id(message_id: str) -> Optional[MessageRecord]:
    document = messages_collection.find_one({"id": message_id})
    return parse_model(MessageRecord, document)


def get_run_messages(workflow_run_id: str) -> list[MessageRecord]:
    documents = messages_collection.find(
        {
            "workflow_run_id": workflow_run_id,
        }
    ).sort("created_at", 1)

    return [
        parse_model(MessageRecord, document)
        for document in documents
    ]

def get_workflow_node_runs_by_run_id(
    workflow_run_id: str,
) -> list[WorkflowNodeRun]:
    documents = workflow_node_runs_collection.find(
        {
            "workflow_run_id": workflow_run_id,
        }
    ).sort("created_at", 1)

    return [
        parse_model(WorkflowNodeRun, document)
        for document in documents
    ]


def get_run_node_responses(workflow_run_id: str) -> list[NodeResponse]:
    documents = node_responses_collection.find(
        {
            "workflow_run_id": workflow_run_id,
        }
    ).sort("created_at", 1)

    return [
        parse_model(NodeResponse, document)
        for document in documents
    ]

def update_message_after_send( 
    message_id: str,
    status: str,
    metadata: dict,
):
    """Because initially our outgoing message status is:

        created

        After Meta accepts it, we want:

        sent

        or if Meta rejects it:

        failed """
    
    messages_collection.update_one(
        {"id": message_id},
        {
            "$set": {
                "status": status,
                "metadata": metadata,
                "updated_at": now_utc(),
            },
        },
    )

def get_whatsapp_account_by_id(
    account_id: str,
) -> Optional[WhatsAppAccount]:
    document = whatsapp_accounts_collection.find_one(
        {"id": account_id}
    )

    return parse_model(WhatsAppAccount, document)

MESSAGE_STATUS_ORDER = {
    "created": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
}


def should_apply_message_status_update(
    current_status: str | None,
    incoming_status: str | None,
) -> bool:
    current = (current_status or "created").lower()
    incoming = (incoming_status or "").lower()

    # Once read, nothing should downgrade it.
    if current == "read":
        return False

    # Once delivered, sent should not downgrade it.
    if current == "delivered" and incoming == "sent":
        return False

    # Failed is special.
    # Allow failed only if message has not already reached delivered/read.
    if incoming == "failed":
        return current not in ["delivered", "read"]

    # If current is failed, do not revive it from later status webhooks.
    if current == "failed":
        return False

    incoming_rank = MESSAGE_STATUS_ORDER.get(incoming)

    # Unknown status should be recorded in history,
    # but should not become main message.status.
    if incoming_rank is None:
        return False

    current_rank = MESSAGE_STATUS_ORDER.get(current, 0)

    return incoming_rank >= current_rank


def update_message_status_by_meta_message_id(
    meta_message_id: str,
    status: str,
    status_payload: dict,
):
    current_time = now_utc()

    message_document = messages_collection.find_one(
        {
            "metadata.meta_message_id": meta_message_id,
        }
    )

    if not message_document:
        return {
            "matched_count": 0,
            "modified_count": 0,
            "applied": False,
            "previous_status": None,
            "incoming_status": status,
            "final_status": None,
            "reason": "Message not found for Meta message id.",
        }

    previous_status = message_document.get("status", "created")

    should_apply = should_apply_message_status_update(
        current_status=previous_status,
        incoming_status=status,
    )

    history_item = {
        "status": status,
        "payload": status_payload,
        "received_at": current_time,
        "applied_to_main_status": should_apply,
        "previous_status": previous_status,
    }

    update_query = {
        "$set": {
            "updated_at": current_time,
        },
        "$push": {
            "metadata.status_history": history_item,
        },
    }

    if should_apply:
        update_query["$set"]["status"] = status

    result = messages_collection.update_one(
        {
            "metadata.meta_message_id": meta_message_id,
        },
        update_query,
    )

    final_status = status if should_apply else previous_status

    return {
        "matched_count": result.matched_count,
        "modified_count": result.modified_count,
        "applied": should_apply,
        "previous_status": previous_status,
        "incoming_status": status,
        "final_status": final_status,
        "reason": None if should_apply else "Skipped because incoming status would downgrade current status.",
    }

def upsert_conversation_on_message(
    client_id: str,
    whatsapp_account_id: str,
    contact_phone: str,
    text: str | None,
    direction: str,
    contact_name: str | None = None,
    referral: dict | None = None,
    message_type: str = "text",
) -> Conversation:
    """One conversation exists per (whatsapp_account_id, contact_phone).

    An inbound message re-opens the chat; an outbound one refreshes the
    last-message preview. Incoming messages also bump unread_count. The id is
    generated once on insert ($setOnInsert), so it stays stable across upserts -
    which is why the generic upsert_document() cannot be used here.

    An outbound TEMPLATE is special twice over: it does not re-open the chat
    (only the customer's inbound opens Meta's 24h window, so claiming "open"
    would be a lie the expiry sweep immediately overwrites - that fight is what
    made the inbox flicker), and it marks the chat as awaiting a reply so the
    CRM can keep it out of the main list until the customer answers.
    """
    current_time = now_utc()

    is_template = direction == "outgoing" and message_type == "template"

    set_fields = {
        "client_id": client_id,
        "last_message_text": text,
        "last_message_at": current_time,
        "last_message_direction": direction,
        "updated_at": current_time,
    }
    # A template cannot re-open a closed window, so it must not claim "open".
    if not is_template:
        set_fields["status"] = "open"
    else:
        set_fields["awaiting_template_reply"] = True
        set_fields["last_template_at"] = current_time

    if contact_name:
        set_fields["contact_name"] = contact_name

    # CTWA attribution: Meta attaches a referral object to the message a
    # customer sends by tapping a Click-to-WhatsApp ad. It only appears on
    # that first message, so persist it whenever we see it.
    if referral:
        set_fields["source"] = "ctwa"
        set_fields["source_id"] = referral.get("source_id")
        set_fields["source_url"] = referral.get("source_url")
        set_fields["ctwa_clid"] = referral.get("ctwa_clid")
        set_fields["source_type"] = referral.get("source_type")
        set_fields["headline"] = referral.get("headline")

    set_on_insert = {
        "id": f"conv:{short_id()}",
        "whatsapp_account_id": whatsapp_account_id,
        "contact_phone": contact_phone,
        "created_at": current_time,
    }

    # A template to a brand-new contact creates the conversation, and since
    # `status` is left out of $set for templates it would otherwise have no
    # status at all - which parses back as "open", the exact lie this change
    # removes. They have never written in, so the honest starting state is
    # expired. ($set and $setOnInsert may not both touch `status`.)
    if is_template:
        set_on_insert["status"] = "expired"

    if not referral:
        set_on_insert["source"] = "whatsapp"

    update_query = {
        "$set": set_fields,
        "$setOnInsert": set_on_insert,
    }

    if direction == "incoming":
        update_query["$inc"] = {"unread_count": 1}
        # Stamp the 24-hour customer service window from the customer's inbound.
        set_fields["last_inbound_at"] = current_time
        # They answered: the chat rejoins the normal inbox.
        set_fields["awaiting_template_reply"] = False

    document = conversations_collection.find_one_and_update(
        {
            "whatsapp_account_id": whatsapp_account_id,
            "contact_phone": contact_phone,
        },
        update_query,
        upsert=True,
        return_document=True,
    )

    return parse_model(Conversation, document)


def get_conversation_by_id(conversation_id: str) -> Optional[Conversation]:
    document = conversations_collection.find_one({"id": conversation_id})
    return parse_model(Conversation, document)


def get_conversation_for_contact(
    whatsapp_account_id: str,
    contact_phone: str,
) -> Optional[Conversation]:
    document = conversations_collection.find_one(
        {
            "whatsapp_account_id": whatsapp_account_id,
            "contact_phone": contact_phone,
        }
    )
    return parse_model(Conversation, document)


def expire_stale_conversations(
    cutoff,
    client_id: str | None = None,
    conversation_id: str | None = None,
):
    """Materialize the 24h window on the conversation collection: flip
    open/resolved -> expired for conversations whose last inbound is older than
    `cutoff`, clear the agent handoff (bot_paused=False), unlink the run, and
    cancel their still-running workflows. Scope by client (inbox list) or a
    single conversation (opening a chat). `cutoff` = now - 24h, passed by the
    caller so the window length stays single-sourced in services."""
    # No inbound ever means no window was ever opened, so those count as stale
    # too. Exempting them (the old `$ne: None`) left them permanently "open"
    # server-side while the CRM rendered them expired, and the two fought.
    stale_filter = {
        "status": {"$in": ["open", "resolved"]},
        "$or": [
            {"last_inbound_at": None},
            {"last_inbound_at": {"$lt": cutoff}},
        ],
    }
    if client_id:
        stale_filter["client_id"] = client_id
    if conversation_id:
        stale_filter["id"] = conversation_id

    # Which contacts are expiring — needed to cancel their running workflows.
    stale = list(
        conversations_collection.find(
            stale_filter,
            {"whatsapp_account_id": 1, "contact_phone": 1},
        )
    )
    if not stale:
        return

    current_time = now_utc()

    conversations_collection.update_many(
        stale_filter,
        {
            "$set": {
                "status": "expired",
                "bot_paused": False,
                "active_workflow_run_id": None,
                "updated_at": current_time,
            }
        },
    )

    workflow_runs_collection.update_many(
        {
            "$or": [
                {
                    "whatsapp_account_id": doc["whatsapp_account_id"],
                    "contact_phone": doc["contact_phone"],
                }
                for doc in stale
            ],
            "status": {"$in": ["active", "waiting_for_user"]},
        },
        {"$set": {"status": "cancelled", "completed_at": current_time}},
    )


# The CRM's inbox tabs. "inbox" is All/Unread, "template" is the Template msg.
# tab. Note `$ne: True` rather than `False`: a document written before the field
# existed has no value at all, and must stay visible in All rather than falling
# out of every tab.
CONVERSATION_VIEWS = {
    "inbox": {"awaiting_template_reply": {"$ne": True}},
    "template": {"awaiting_template_reply": True},
}


def count_conversation_views(client_id: str) -> dict[str, int]:
    """How many conversations each inbox tab holds. Returned on every list call
    so a tab's badge is right the moment it is opened, instead of counting only
    the rows that happen to be loaded."""
    return {
        name: conversations_collection.count_documents({"client_id": client_id, **clause})
        for name, clause in CONVERSATION_VIEWS.items()
    }


def list_conversations(
    client_id: str | None = None,
    status: str | None = None,
    whatsapp_account_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    view: str | None = None,
):
    query = {}

    if client_id:
        query["client_id"] = client_id

    if status:
        query["status"] = status

    if whatsapp_account_id:
        query["whatsapp_account_id"] = whatsapp_account_id

    # No view = no filter, so every other consumer of this function is untouched.
    if view:
        query.update(CONVERSATION_VIEWS.get(view, {}))

    # Tiered ordering: open (0) -> resolved (1) -> expired (2), and by recency
    # (last_message_at desc) within each tier. This keeps expired/dead chats at
    # the bottom even when an outgoing agent/bot message bumped last_message_at.
    # `id` breaks ties: without it the sort is unstable between two page queries
    # for rows sharing last_message_at (every row where it is null, for one), so
    # paging could silently skip and duplicate rows.
    total = conversations_collection.count_documents(query)
    pipeline = [
        {"$match": query},
        {"$addFields": {"_rank": {"$switch": {"branches": [
            {"case": {"$eq": ["$status", "open"]}, "then": 0},
            {"case": {"$eq": ["$status", "resolved"]}, "then": 1},
        ], "default": 2}}}},
        {"$sort": {"_rank": 1, "last_message_at": -1, "id": 1}},
        {"$skip": offset},
        {"$limit": limit},
        {"$project": {"_rank": 0}},
    ]
    items = [
        parse_model(Conversation, document)
        for document in conversations_collection.aggregate(pipeline)
    ]
    return total, items


def set_conversation_status(
    conversation_id: str,
    status: str,
    resolved_by: str | None = None,
    active_workflow_run_id: str | None = None,
    bot_paused: bool | None = None,
):
    current_time = now_utc()

    set_fields = {
        "status": status,
        "active_workflow_run_id": active_workflow_run_id,
        "updated_at": current_time,
    }

    if bot_paused is not None:
        set_fields["bot_paused"] = bot_paused

    if status == "resolved":
        set_fields["resolved_at"] = current_time
        set_fields["resolved_by"] = resolved_by
    else:
        set_fields["resolved_at"] = None
        set_fields["resolved_by"] = None

    conversations_collection.update_one(
        {"id": conversation_id},
        {"$set": set_fields},
    )


def set_conversation_bot_paused(
    conversation_id: str,
    paused: bool,
):
    conversations_collection.update_one(
        {"id": conversation_id},
        {
            "$set": {
                "bot_paused": paused,
                "updated_at": now_utc(),
            },
        },
    )


def set_conversation_disposition(conversation_id: str, **fields):
    """Persist ONLY the agent-set lead outcome (disposition / remark / when).

    Targeted $set like save_run_crm_result: never a whole-model save, so a
    stale in-memory conversation can't clobber status / bot_paused / unread."""
    allowed = {"disposition", "disposition_remark", "disposition_updated_at"}
    set_fields = {key: value for key, value in fields.items() if key in allowed}
    if not set_fields:
        return
    set_fields["updated_at"] = now_utc()
    conversations_collection.update_one({"id": conversation_id}, {"$set": set_fields})


def set_conversation_active_run(
    conversation_id: str,
    workflow_run_id: str | None,
):
    conversations_collection.update_one(
        {"id": conversation_id},
        {
            "$set": {
                "active_workflow_run_id": workflow_run_id,
                "updated_at": now_utc(),
            },
        },
    )


def reset_conversation_unread(conversation_id: str):
    conversations_collection.update_one(
        {"id": conversation_id},
        {
            "$set": {
                "unread_count": 0,
                "updated_at": now_utc(),
            },
        },
    )


def get_messages_for_contact(
    whatsapp_account_id: str,
    contact_phone: str,
    limit: int | None = None,
    before=None,
) -> list[MessageRecord]:
    """Messages for a contact, oldest->newest. With `limit`, returns the most
    recent `limit` (optionally older than `before`) — used for inbox pagination.
    Without `limit`, returns the full history (unchanged legacy behavior)."""
    query = {
        "whatsapp_account_id": whatsapp_account_id,
        "contact_phone": contact_phone,
    }
    if before is not None:
        query["created_at"] = {"$lt": before}

    if limit is None:
        documents = messages_collection.find(query).sort("created_at", 1)
        return [parse_model(MessageRecord, document) for document in documents]

    # Newest `limit`, then flip to ascending for display.
    documents = list(
        messages_collection.find(query).sort("created_at", -1).limit(limit)
    )
    documents.reverse()
    return [parse_model(MessageRecord, document) for document in documents]


def merge_conversation_attributes(
    conversation_id: str,
    attributes: dict,
):
    """Merges keys into conversation.attributes without touching existing
    ones (dotted-path $set). Used to surface workflow answers as WATI-style
    contact attributes."""
    if not attributes:
        return

    set_fields = {
        f"attributes.{key}": value
        for key, value in attributes.items()
    }
    set_fields["updated_at"] = now_utc()

    conversations_collection.update_one(
        {"id": conversation_id},
        {"$set": set_fields},
    )


def update_conversation_contact_fields(
    conversation_id: str,
    contact_name: str | None = None,
    attributes: dict | None = None,
    tags: list[str] | None = None,
):
    set_fields = {"updated_at": now_utc()}

    if contact_name is not None:
        set_fields["contact_name"] = contact_name

    if attributes is not None:
        # Merge, never replace: attributes.crm.call_tried is server-owned (bumped
        # by FasterQ calls) and workflow answers live alongside — a remark or
        # custom-column edit from the CRM must not wipe them.
        for key, value in attributes.items():
            if key == "crm" and isinstance(value, dict):
                for ck, cv in value.items():
                    set_fields[f"attributes.crm.{ck}"] = cv
            else:
                set_fields[f"attributes.{key}"] = value

    if tags is not None:
        set_fields["tags"] = tags

    conversations_collection.update_one(
        {"id": conversation_id},
        {"$set": set_fields},
    )


def delete_conversation_cascade(conversation: Conversation) -> dict:
    """Hard-deletes a conversation and everything tied to its contact: all
    messages, workflow runs for the contact, and each run's node runs and node
    responses. Keyed on (whatsapp_account_id, contact_phone) — the same identity
    used to read messages/conversations — so nothing for the contact is left
    behind. Returns per-collection deleted counts."""
    account_id = conversation.whatsapp_account_id
    phone = conversation.contact_phone

    run_ids = [
        document["id"]
        for document in workflow_runs_collection.find(
            {
                "client_id": conversation.client_id,
                "whatsapp_account_id": account_id,
                "contact_phone": phone,
            },
            {"id": 1},
        )
    ]

    node_responses = 0
    node_runs = 0
    if run_ids:
        node_responses = node_responses_collection.delete_many(
            {"workflow_run_id": {"$in": run_ids}}
        ).deleted_count
        node_runs = workflow_node_runs_collection.delete_many(
            {"workflow_run_id": {"$in": run_ids}}
        ).deleted_count

    messages = messages_collection.delete_many(
        {"whatsapp_account_id": account_id, "contact_phone": phone}
    ).deleted_count
    runs = workflow_runs_collection.delete_many(
        {"id": {"$in": run_ids}}
    ).deleted_count if run_ids else 0
    conversations = conversations_collection.delete_one(
        {"id": conversation.id}
    ).deleted_count

    return {
        "conversations": conversations,
        "messages": messages,
        "workflow_runs": runs,
        "workflow_node_runs": node_runs,
        "node_responses": node_responses,
    }


# =====================================================================
# Templates
# =====================================================================

def save_template(template: Template):
    upsert_document(templates_collection, {"id": template.id}, model_to_dict(template))


def get_template_by_id(template_id: str) -> Optional[Template]:
    return parse_model(Template, templates_collection.find_one({"id": template_id}))


def get_template(whatsapp_account_id: str, name: str, language: str) -> Optional[Template]:
    return parse_model(Template, templates_collection.find_one(
        {"whatsapp_account_id": whatsapp_account_id, "name": name, "language": language}
    ))


def list_templates_for_account(whatsapp_account_id: str) -> list[Template]:
    docs = templates_collection.find(
        {"whatsapp_account_id": whatsapp_account_id}
    ).sort("created_at", -1)
    return [parse_model(Template, d) for d in docs]


def delete_template_by_id(template_id: str):
    templates_collection.delete_one({"id": template_id})


def set_template_status(
    whatsapp_account_id: str, name: str, language: str,
    status: str, rejected_reason: str | None = None,
) -> int:
    result = templates_collection.update_one(
        {"whatsapp_account_id": whatsapp_account_id, "name": name, "language": language},
        {"$set": {"status": status, "rejected_reason": rejected_reason, "updated_at": now_utc()}},
    )
    return result.matched_count


# =====================================================================
# Contacts
# =====================================================================

def upsert_contact(
    whatsapp_account_id: str, client_id: str, phone: str,
    name: str | None = None, source: str = "inbound",
    last_inbound_at=None, marketing_opt_in: bool = False,
):
    current = now_utc()
    set_fields = {"updated_at": current, "client_id": client_id}
    if name:
        set_fields["name"] = name
    if last_inbound_at is not None:
        set_fields["last_inbound_at"] = last_inbound_at
    # Only ever upgrade consent here (engagement/import-with-consent); never clear
    # it (opt-out is the only path that revokes it).
    on_insert = {
        "id": f"contact:{short_id()}",
        "whatsapp_account_id": whatsapp_account_id,
        "phone": phone,
        "source": source,
        "opted_out": False,
        "tags": [],
        "created_at": current,
    }
    if marketing_opt_in:
        set_fields["marketing_opt_in"] = True  # applies to insert + update
    else:
        on_insert["marketing_opt_in"] = False  # default only on first insert
    contacts_collection.update_one(
        {"whatsapp_account_id": whatsapp_account_id, "phone": phone},
        {"$set": set_fields, "$setOnInsert": on_insert},
        upsert=True,
    )


def get_contact_by_id(contact_id: str) -> Optional[Contact]:
    return parse_model(Contact, contacts_collection.find_one({"id": contact_id}))


def update_contact_fields(
    contact_id: str, name: str | None = None, tags: list[str] | None = None,
) -> Optional[Contact]:
    """CRM edit of a contact. Targeted $set; `tags` replaces the whole list."""
    set_fields: dict[str, Any] = {"updated_at": now_utc()}
    if name is not None:
        set_fields["name"] = name.strip() or None
    if tags is not None:
        set_fields["tags"] = sorted({t.strip() for t in tags if t and t.strip()})
    contacts_collection.update_one({"id": contact_id}, {"$set": set_fields})
    return get_contact_by_id(contact_id)


# =====================================================================
# Notes (agent-only, never sent to the customer)
# =====================================================================

def save_note(note: Note):
    upsert_document(notes_collection, {"id": note.id}, model_to_dict(note))


def list_notes(conversation_id: str) -> list[Note]:
    documents = notes_collection.find({"conversation_id": conversation_id}).sort("created_at", 1)
    return [note for note in (parse_model(Note, d) for d in documents) if note]


def get_note_by_id(note_id: str) -> Optional[Note]:
    return parse_model(Note, notes_collection.find_one({"id": note_id}))


def delete_note(note_id: str):
    notes_collection.delete_one({"id": note_id})


def list_contacts(
    whatsapp_account_id: str, tag: str | None = None, opted_out: bool | None = None,
    search: str | None = None, limit: int = 50, offset: int = 0,
):
    query: dict = {"whatsapp_account_id": whatsapp_account_id}
    if tag:
        query["tags"] = tag
    if opted_out is not None:
        query["opted_out"] = opted_out
    if search:
        query["$or"] = [
            {"phone": {"$regex": search}},
            {"name": {"$regex": search, "$options": "i"}},
        ]
    return paginated_find(contacts_collection, query, Contact, "created_at", -1, limit, offset)


def set_contact_opt_out(whatsapp_account_id: str, phone: str, opted_out: bool) -> int:
    result = contacts_collection.update_one(
        {"whatsapp_account_id": whatsapp_account_id, "phone": phone},
        {"$set": {"opted_out": opted_out, "updated_at": now_utc()}},
    )
    return result.matched_count


def get_audience_contacts(
    whatsapp_account_id: str, audience: dict, require_marketing_opt_in: bool = False,
) -> list[Contact]:
    """Contacts matching a broadcast audience, always excluding opted-out. When
    require_marketing_opt_in is set (MARKETING templates), also require consent."""
    query: dict = {"whatsapp_account_id": whatsapp_account_id, "opted_out": {"$ne": True}}
    if require_marketing_opt_in:
        query["marketing_opt_in"] = True
    atype = (audience or {}).get("type", "all")
    if atype == "tag" and audience.get("tag"):
        query["tags"] = audience["tag"]
    elif atype == "phones":
        query["phone"] = {"$in": audience.get("phones", [])}
    return [parse_model(Contact, d) for d in contacts_collection.find(query)]


def update_contact_consent(
    whatsapp_account_id: str, phone: str,
    opted_out: bool | None = None, marketing_opt_in: bool | None = None,
) -> int:
    """Set opt-out and/or marketing consent flags (only the ones provided)."""
    set_fields: dict = {"updated_at": now_utc()}
    if opted_out is not None:
        set_fields["opted_out"] = opted_out
    if marketing_opt_in is not None:
        set_fields["marketing_opt_in"] = marketing_opt_in
    result = contacts_collection.update_one(
        {"whatsapp_account_id": whatsapp_account_id, "phone": phone},
        {"$set": set_fields},
    )
    return result.matched_count


# =====================================================================
# Broadcasts + recipients
# =====================================================================

def save_broadcast(broadcast: Broadcast):
    upsert_document(broadcasts_collection, {"id": broadcast.id}, model_to_dict(broadcast))


def get_broadcast_by_id(broadcast_id: str) -> Optional[Broadcast]:
    return parse_model(Broadcast, broadcasts_collection.find_one({"id": broadcast_id}))


def list_broadcasts_for_account(whatsapp_account_id: str, limit: int = 50, offset: int = 0):
    return paginated_find(
        broadcasts_collection, {"whatsapp_account_id": whatsapp_account_id},
        Broadcast, "created_at", -1, limit, offset,
    )


def set_broadcast_status(broadcast_id: str, status: str, **extra):
    broadcasts_collection.update_one(
        {"id": broadcast_id},
        {"$set": {"status": status, "updated_at": now_utc(), **extra}},
    )


def list_running_broadcast_ids() -> list[str]:
    return [d["id"] for d in broadcasts_collection.find({"status": "running"}, {"id": 1})]


def bump_broadcast_counts(broadcast_id: str, **deltas):
    inc = {f"counts.{k}": v for k, v in deltas.items() if v}
    if not inc:
        return
    broadcasts_collection.update_one(
        {"id": broadcast_id}, {"$inc": inc, "$set": {"updated_at": now_utc()}}
    )


def recent_template_recipients(client_id: str, template_name: str, phones: list[str],
                               since: datetime) -> dict[str, datetime]:
    """Phones that this client already targeted with `template_name` in a
    broadcast created on/after `since` → the latest such time. Pending/sending
    rows count too (two uploads on the same day must not double-send);
    skipped/failed rows do not (nothing reached the person)."""
    if not phones:
        return {}
    ids = [d["id"] for d in broadcasts_collection.find(
        {"client_id": client_id, "template_name": template_name, "created_at": {"$gte": since}},
        {"id": 1},
    )]
    if not ids:
        return {}
    latest: dict[str, datetime] = {}
    cursor = broadcast_recipients_collection.find(
        {"broadcast_id": {"$in": ids}, "contact_phone": {"$in": phones},
         "status": {"$in": ["pending", "sending", "sent", "delivered", "read"]}},
        {"contact_phone": 1, "sent_at": 1, "created_at": 1},
    )
    for d in cursor:
        when = d.get("sent_at") or d.get("created_at") or since
        prev = latest.get(d["contact_phone"])
        if prev is None or when > prev:
            latest[d["contact_phone"]] = when
    return latest


def insert_broadcast_recipients(recipients: list[BroadcastRecipient]):
    if not recipients:
        return
    current = now_utc()
    docs = []
    for r in recipients:
        d = r.model_dump(mode="python")
        d["created_at"] = current
        d["updated_at"] = current
        docs.append(d)
    broadcast_recipients_collection.insert_many(docs)


def claim_pending_recipient(broadcast_id: str) -> Optional[BroadcastRecipient]:
    """Atomically take one pending recipient (pending->sending). Returns the
    pre-image (still carries id/contact_phone/params) or None if none pending."""
    doc = broadcast_recipients_collection.find_one_and_update(
        {"broadcast_id": broadcast_id, "status": "pending"},
        {"$set": {"status": "sending", "updated_at": now_utc()}},
    )
    return parse_model(BroadcastRecipient, doc)


def count_open_recipients(broadcast_id: str) -> int:
    return broadcast_recipients_collection.count_documents(
        {"broadcast_id": broadcast_id, "status": {"$in": ["pending", "sending"]}}
    )


def finalize_recipient_send(recipient_id: str, status: str,
                            meta_message_id: str | None = None, error=None):
    broadcast_recipients_collection.update_one(
        {"id": recipient_id},
        {"$set": {
            "status": status, "meta_message_id": meta_message_id, "error": error,
            "sent_at": now_utc(), "updated_at": now_utc(),
        }},
    )


def list_recipients_for_broadcast(broadcast_id: str, limit: int = 100, offset: int = 0):
    return paginated_find(
        broadcast_recipients_collection, {"broadcast_id": broadcast_id},
        BroadcastRecipient, "created_at", 1, limit, offset,
    )


def get_recipient_by_meta_message_id(meta_message_id: str) -> Optional[BroadcastRecipient]:
    return parse_model(BroadcastRecipient, broadcast_recipients_collection.find_one(
        {"meta_message_id": meta_message_id}
    ))


def set_recipient_status(recipient_id: str, status: str, error: str | None = None):
    fields: dict = {"status": status, "updated_at": now_utc()}
    if error is not None:
        fields["error"] = error
    broadcast_recipients_collection.update_one({"id": recipient_id}, {"$set": fields})


def set_template_status_by_waba(waba_id: str, name: str, language: str,
                                status: str, rejected_reason: str | None = None) -> int:
    result = templates_collection.update_one(
        {"waba_id": waba_id, "name": name, "language": language},
        {"$set": {"status": status, "rejected_reason": rejected_reason, "updated_at": now_utc()}},
    )
    return result.matched_count


def add_contact_tags(whatsapp_account_id: str, phone: str, tags: list[str]):
    if not tags:
        return
    contacts_collection.update_one(
        {"whatsapp_account_id": whatsapp_account_id, "phone": phone},
        {"$addToSet": {"tags": {"$each": tags}}, "$set": {"updated_at": now_utc()}},
    )


def reclaim_stale_sending_recipients(broadcast_id: str, cutoff) -> int:
    """Return recipients stuck in 'sending' (worker died mid-send) older than
    cutoff back to 'pending' so they get retried and the broadcast can finish."""
    result = broadcast_recipients_collection.update_many(
        {"broadcast_id": broadcast_id, "status": "sending", "updated_at": {"$lt": cutoff}},
        {"$set": {"status": "pending", "updated_at": now_utc()}},
    )
    return result.modified_count


# ---------------------------------------------------------------------------
# FasterQ call records
# ---------------------------------------------------------------------------

def save_call(call: CallRecord):
    upsert_document(calls_collection, {"id": call.id}, model_to_dict(call))


def get_call_by_id(call_id: str) -> Optional[CallRecord]:
    return parse_model(CallRecord, calls_collection.find_one({"id": call_id}))


def get_call_by_provider_id(provider: str, provider_call_id: str) -> Optional[CallRecord]:
    return parse_model(CallRecord, calls_collection.find_one(
        {"provider": provider, "provider_call_id": provider_call_id}))


def list_calls(client_id: str, direction: str | None = None, answered: bool | None = None,
               phone: str | None = None, conversation_id: str | None = None,
               limit: int = 50, offset: int = 0):
    query: dict[str, Any] = {"client_id": client_id}
    if direction:
        query["direction"] = direction
    if answered is not None:
        query["answered"] = answered
    if phone:
        query["contact_phone"] = {"$regex": re.escape(phone.strip().lstrip("+"))}
    if conversation_id:
        query["conversation_id"] = conversation_id
    return paginated_find(calls_collection, query, CallRecord, "started_at", -1, limit, offset)


def list_calls_needing_recording(limit: int = 50) -> list[CallRecord]:
    """Recordings still to be copied into our bucket (retried a few times)."""
    documents = calls_collection.find({
        "recording_url": {"$nin": [None, ""]},
        "recording_status": {"$in": ["pending", "failed"]},
        "recording_attempts": {"$lt": 5},
    }).sort("updated_at", 1).limit(limit)
    return [parse_model(CallRecord, d) for d in documents]


def list_calls_missing_links(since: datetime, limit: int = 500) -> list[CallRecord]:
    """Calls not yet tied to a client (agent name unknown at the time) or to a
    conversation (the person had not messaged yet)."""
    documents = calls_collection.find({
        "created_at": {"$gte": since},
        "$or": [{"client_id": None}, {"conversation_id": None}],
    }).sort("created_at", -1).limit(limit)
    return [parse_model(CallRecord, d) for d in documents]


def list_calls_for_agent_unassigned(agent_names_lc: list[str], limit: int = 500) -> list[CallRecord]:
    if not agent_names_lc:
        return []
    documents = calls_collection.find({"client_id": None}).sort("created_at", -1).limit(limit)
    return [c for c in (parse_model(CallRecord, d) for d in documents)
            if c and (c.agent_name or "").strip().lower() in agent_names_lc]


def find_conversation_by_client_phone(client_id: str, contact_phone: str) -> Optional[Conversation]:
    """One indexed lookup — the customer's number is unique per client account."""
    return parse_model(Conversation, conversations_collection.find_one(
        {"client_id": client_id, "contact_phone": contact_phone}, sort=[("last_message_at", -1)]))


def increment_call_tried(conversation_id: str) -> None:
    """The lead's Calls count: +1 per outbound call reported by FasterQ."""
    conversations_collection.update_one(
        {"id": conversation_id},
        {"$inc": {"attributes.crm.call_tried": 1}, "$set": {"updated_at": now_utc()}},
    )


def find_client_by_agent_name(agent_name: str) -> Optional[Client]:
    """Clients are few; compare the saved names case-insensitively in Python."""
    needle = (agent_name or "").strip().lower()
    if not needle:
        return None
    for document in clients_collection.find({"call_recording.agent_names": {"$exists": True, "$ne": []}}):
        names = [str(n).strip().lower() for n in (document.get("call_recording") or {}).get("agent_names") or []]
        if needle in names:
            return parse_model(Client, document)
    return None


# ---------------------------------------------------------------------------
# CRM leads feed: one row per arrival (a workflow run), newest first
# ---------------------------------------------------------------------------

LEADS_DAY_TZ = "Asia/Kolkata"


def _lead_phones_for_filters(client_id: str, q: str | None, source: str | None) -> list[str] | None:
    """Resolve a name/phone search + source filter to the contact phones they
    match (conversations hold the name and the source). None = no filter."""
    if not q and not source:
        return None
    query: dict[str, Any] = {"client_id": client_id}
    if source:
        query["source"] = source
    if q:
        needle = re.escape(q.strip())
        query["$or"] = [
            {"contact_name": {"$regex": needle, "$options": "i"}},
            {"contact_phone": {"$regex": needle}},
        ]
    return conversations_collection.distinct("contact_phone", query)


def list_leads(
    client_id: str,
    q: str | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """The CRM's lead feed. Every workflow run is an arrival; a conversation
    with an inbound message but no run at all is one row too. Several runs of
    the same number on the same (IST) day collapse to the latest one, so a
    patient who restarts the flow twice in a morning is one lead, but one who
    comes back on another day is a new lead. Returns
    (total, [{kind, run_id|conversation_id, contact_phone, whatsapp_account_id,
    arrived_at}]) sorted newest first."""
    phones = _lead_phones_for_filters(client_id, q, source)
    if phones is not None and not phones:
        return 0, []
    run_match: dict[str, Any] = {"client_id": client_id}
    conv_match: dict[str, Any] = {"client_id": client_id, "last_inbound_at": {"$ne": None}}
    if phones is not None:
        run_match["contact_phone"] = {"$in": phones}
        conv_match["contact_phone"] = {"$in": phones}

    pipeline = [
        {"$match": run_match},
        {"$project": {
            "_id": 0, "kind": "run", "run_id": "$id",
            "contact_phone": 1, "whatsapp_account_id": 1,
            "arrived_at": {"$ifNull": ["$started_at", "$created_at"]},
        }},
        {"$unionWith": {"coll": "conversations", "pipeline": [
            {"$match": conv_match},
            {"$lookup": {
                "from": "workflow_runs",
                "let": {"phone": "$contact_phone", "account": "$whatsapp_account_id"},
                "pipeline": [
                    {"$match": {"$expr": {"$and": [
                        {"$eq": ["$client_id", client_id]},
                        {"$eq": ["$whatsapp_account_id", "$$account"]},
                        {"$eq": ["$contact_phone", "$$phone"]},
                    ]}}},
                    {"$limit": 1},
                    {"$project": {"_id": 1}},
                ],
                "as": "runs",
            }},
            {"$match": {"runs": {"$size": 0}}},
            {"$project": {
                "_id": 0, "kind": "conversation", "conversation_id": "$id",
                "contact_phone": 1, "whatsapp_account_id": 1,
                "arrived_at": {"$ifNull": ["$created_at", "$last_inbound_at"]},
            }},
        ]}},
        {"$sort": {"arrived_at": -1}},
        {"$group": {
            "_id": {
                "phone": "$contact_phone",
                "day": {"$dateToString": {"date": "$arrived_at", "format": "%Y-%m-%d", "timezone": LEADS_DAY_TZ, "onNull": ""}},
            },
            "row": {"$first": "$$ROOT"},
        }},
        {"$replaceRoot": {"newRoot": "$row"}},
        # A run whose chat was deleted from the inbox has no patient to show:
        # drop it here so the total matches what the page can render.
        {"$lookup": {
            "from": "conversations",
            "let": {"phone": "$contact_phone", "account": "$whatsapp_account_id"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$whatsapp_account_id", "$$account"]},
                    {"$eq": ["$contact_phone", "$$phone"]},
                ]}}},
                {"$limit": 1},
                {"$project": {"_id": 1}},
            ],
            "as": "conv",
        }},
        {"$match": {"conv": {"$ne": []}}},
        {"$project": {"conv": 0}},
        {"$sort": {"arrived_at": -1, "contact_phone": 1}},
        {"$facet": {
            "total": [{"$count": "n"}],
            "page": [{"$skip": offset}, {"$limit": limit}],
        }},
    ]
    result = next(workflow_runs_collection.aggregate(pipeline, allowDiskUse=True), None) or {}
    total = (result.get("total") or [{}])[0].get("n", 0) if result.get("total") else 0
    return total, list(result.get("page") or [])


def get_workflow_runs_by_ids(run_ids: list[str]) -> list[WorkflowRun]:
    if not run_ids:
        return []
    documents = workflow_runs_collection.find({"id": {"$in": run_ids}})
    return [r for r in (parse_model(WorkflowRun, d) for d in documents) if r]


def get_conversations_by_ids(conversation_ids: list[str]) -> list[Conversation]:
    if not conversation_ids:
        return []
    documents = conversations_collection.find({"id": {"$in": conversation_ids}})
    return [c for c in (parse_model(Conversation, d) for d in documents) if c]


def get_conversations_by_phones(client_id: str, phones: list[str]) -> list[Conversation]:
    if not phones:
        return []
    documents = conversations_collection.find({"client_id": client_id, "contact_phone": {"$in": phones}})
    return [c for c in (parse_model(Conversation, d) for d in documents) if c]


# ---------------------------------------------------------------------------
# AI call review: the document is also the job queue
# ---------------------------------------------------------------------------

def get_call_review(client_id: str, contact_phone: str) -> Optional[CallReview]:
    return parse_model(CallReview, call_reviews_collection.find_one(
        {"client_id": client_id, "contact_phone": contact_phone}))


def list_call_reviews(client_id: str, limit: int = 1000) -> list[CallReview]:
    documents = call_reviews_collection.find({"client_id": client_id}).limit(limit)
    return [r for r in (parse_model(CallReview, d) for d in documents) if r]


def enqueue_call_review(
    client_id: str,
    contact_phone: str,
    conversation_id: str | None = None,
) -> tuple[CallReview, bool]:
    """Queue one patient's review. Returns (review, queued_now).

    Atomic against a second press and against another instance: the filter
    excludes the in-flight statuses, so a patient already queued or running is
    never enqueued twice. The unique (client_id, contact_phone) index is what
    makes the upsert safe - without it two concurrent upserts both insert.
    """
    now = now_utc()
    try:
        document = call_reviews_collection.find_one_and_update(
            {
                "client_id": client_id,
                "contact_phone": contact_phone,
                "status": {"$nin": ["queued", "running"]},
            },
            {
                "$set": {
                    "status": "queued",
                    "error": None,
                    "attempts": 0,
                    "conversation_id": conversation_id,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "client_id": client_id,
                    "contact_phone": contact_phone,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=True,
        )
        return parse_model(CallReview, document), True
    except DuplicateKeyError:
        # Lost the race (or it is already queued/running) - hand back what is there.
        return get_call_review(client_id, contact_phone), False


def claim_queued_call_review() -> Optional[CallReview]:
    """Atomically take one queued review (queued->running). Returns None when
    there is nothing to do. Only the caller that wins the flip does the work."""
    now = now_utc()
    document = call_reviews_collection.find_one_and_update(
        {"status": "queued"},
        {"$set": {"status": "running", "started_at": now, "updated_at": now},
         "$inc": {"attempts": 1}},
        sort=[("updated_at", 1)],
        return_document=True,
    )
    return parse_model(CallReview, document)


def reclaim_stale_call_reviews(cutoff, max_attempts: int = 3) -> int:
    """Reviews stuck in 'running' (instance died mid-job) go back to 'queued',
    or to 'failed' once they have burned through their attempts. The worker
    touches updated_at as it goes, so a genuinely long review is never stolen."""
    call_reviews_collection.update_many(
        {"status": "running", "updated_at": {"$lt": cutoff}, "attempts": {"$gte": max_attempts}},
        {"$set": {"status": "failed", "error": "Timed out", "updated_at": now_utc()}},
    )
    result = call_reviews_collection.update_many(
        {"status": "running", "updated_at": {"$lt": cutoff}, "attempts": {"$lt": max_attempts}},
        {"$set": {"status": "queued", "updated_at": now_utc()}},
    )
    return result.modified_count


def touch_call_review(client_id: str, contact_phone: str) -> None:
    """Heartbeat while a long review runs, so the stale reclaim leaves it alone."""
    call_reviews_collection.update_one(
        {"client_id": client_id, "contact_phone": contact_phone},
        {"$set": {"updated_at": now_utc()}},
    )


def finish_call_review(client_id: str, contact_phone: str, fields: dict) -> None:
    call_reviews_collection.update_one(
        {"client_id": client_id, "contact_phone": contact_phone},
        {"$set": {**fields, "updated_at": now_utc()}},
    )


def get_call_transcript(call_id: str) -> Optional[CallTranscript]:
    return parse_model(CallTranscript, call_transcripts_collection.find_one({"call_id": call_id}))


def get_call_transcripts(call_ids: list[str]) -> dict[str, CallTranscript]:
    if not call_ids:
        return {}
    documents = call_transcripts_collection.find({"call_id": {"$in": call_ids}})
    out = {}
    for document in documents:
        transcript = parse_model(CallTranscript, document)
        if transcript:
            out[transcript.call_id] = transcript
    return out


def save_call_transcript(transcript: CallTranscript) -> None:
    upsert_document(call_transcripts_collection, {"call_id": transcript.call_id},
                    model_to_dict(transcript))


def list_calls_for_patient(client_id: str, contact_phone: str, limit: int = 200) -> list[CallRecord]:
    """Every call this clinic has with one number, oldest first. Exact match -
    list_calls() takes a regex for the search box, which would also match a
    different patient whose number merely contains this one."""
    documents = (calls_collection
                 .find({"client_id": client_id, "contact_phone": contact_phone})
                 .sort("started_at", 1).limit(limit))
    return [c for c in (parse_model(CallRecord, d) for d in documents) if c]
