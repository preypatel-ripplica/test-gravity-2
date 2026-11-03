from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

# Shared Beacon env (backend/.env). Same file as the rest of the API.
_BACKEND = Path(__file__).resolve().parents[1]  # beacon/backend/
load_dotenv(_BACKEND / ".env")
load_dotenv()


MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "botify")


client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]


clients_collection = db["clients"]
users_collection = db["users"]
whatsapp_accounts_collection = db["whatsapp_accounts"]
workflows_collection = db["workflows"]
workflow_nodes_collection = db["workflow_nodes"]
workflow_runs_collection = db["workflow_runs"]
workflow_node_runs_collection = db["workflow_node_runs"]
messages_collection = db["messages"]
node_responses_collection = db["node_responses"]
conversations_collection = db["conversations"]
google_connections_collection = db["google_connections"]
templates_collection = db["templates"]
contacts_collection = db["contacts"]
broadcasts_collection = db["broadcasts"]
broadcast_recipients_collection = db["broadcast_recipients"]
ai_usage_monthly_collection = db["ai_usage_monthly"]
notes_collection = db["notes"]
calls_collection = db["calls"]
call_reviews_collection = db["call_reviews"]
call_transcripts_collection = db["call_transcripts"]


def init_db():
    client.admin.command("ping")

    clients_collection.create_index("id", unique=True)
    clients_collection.create_index("username", unique=True, sparse=True)
    users_collection.create_index("id", unique=True)

    whatsapp_accounts_collection.create_index("id", unique=True)
    whatsapp_accounts_collection.create_index("phone_number_id", unique=True)
    whatsapp_accounts_collection.create_index("client_id")

    workflows_collection.create_index("id", unique=True)
    workflows_collection.create_index(
        [
            ("client_id", 1),
            ("whatsapp_account_id", 1),
            ("status", 1),
            ("deleted", 1),
        ]
    )

    workflow_nodes_collection.create_index("id", unique=True)
    workflow_nodes_collection.create_index(
        [
            ("workflow_id", 1),
            ("deleted", 1),
        ]
    )

    workflow_runs_collection.create_index("id", unique=True)
    workflow_runs_collection.create_index(
        [
            ("client_id", 1),
            ("whatsapp_account_id", 1),
            ("contact_phone", 1),
            ("status", 1),
        ]
    )
    # Backs the inactivity-timeout sweep: find waiting runs per account older
    # than a cutoff without scanning the whole collection.
    workflow_runs_collection.create_index(
        [
            ("whatsapp_account_id", 1),
            ("status", 1),
            ("updated_at", 1),
        ]
    )

    workflow_node_runs_collection.create_index("id", unique=True)
    workflow_node_runs_collection.create_index("workflow_run_id")
    # CRM: disposition_sync matches relay docs to runs by the generated lead id.
    workflow_runs_collection.create_index("variables.lead_id")
    # CRM leads feed: runs per client, newest arrival first.
    workflow_runs_collection.create_index([("client_id", 1), ("started_at", -1)])
    notes_collection.create_index([("conversation_id", 1), ("created_at", 1)])

    messages_collection.create_index("id", unique=True)
    messages_collection.create_index("workflow_run_id")
    messages_collection.create_index("contact_phone")

    node_responses_collection.create_index("id", unique=True)
    node_responses_collection.create_index("workflow_run_id")

    conversations_collection.create_index("id", unique=True)
    conversations_collection.create_index(
        [
            ("whatsapp_account_id", 1),
            ("contact_phone", 1),
        ],
        unique=True,
    )
    conversations_collection.create_index(
        [
            ("client_id", 1),
            ("status", 1),
        ]
    )
    conversations_collection.create_index("last_message_at")

    google_connections_collection.create_index("id", unique=True)
    google_connections_collection.create_index("client_id")

    templates_collection.create_index("id", unique=True)
    templates_collection.create_index(
        [("whatsapp_account_id", 1), ("name", 1), ("language", 1)], unique=True
    )
    templates_collection.create_index("client_id")

    contacts_collection.create_index("id", unique=True)
    contacts_collection.create_index(
        [("whatsapp_account_id", 1), ("phone", 1)], unique=True
    )
    contacts_collection.create_index([("whatsapp_account_id", 1), ("tags", 1)])
    contacts_collection.create_index("client_id")

    broadcasts_collection.create_index("id", unique=True)
    broadcasts_collection.create_index(
        [("client_id", 1), ("whatsapp_account_id", 1), ("status", 1)]
    )

    broadcast_recipients_collection.create_index("id", unique=True)
    broadcast_recipients_collection.create_index([("broadcast_id", 1), ("status", 1)])
    # cooldown lookup: who got this template from this client recently
    broadcasts_collection.create_index([("client_id", 1), ("template_name", 1), ("created_at", -1)])
    broadcast_recipients_collection.create_index([("broadcast_id", 1), ("contact_phone", 1)])
    broadcast_recipients_collection.create_index("meta_message_id")

    # FasterQ call records: dedupe on the provider's id; list per client; join to
    # the lead by number; conversations get a client-scoped phone lookup.
    calls_collection.create_index("id", unique=True)
    calls_collection.create_index([("provider", 1), ("provider_call_id", 1)], unique=True)
    calls_collection.create_index([("client_id", 1), ("started_at", -1)])
    calls_collection.create_index([("client_id", 1), ("contact_phone", 1)])
    calls_collection.create_index("conversation_id")
    calls_collection.create_index("recording_status")

    # AI call review. One doc per patient per clinic; the unique index is what
    # makes the enqueue upsert race-safe (a Mongo upsert is not atomic against a
    # concurrent upsert without one). The status index backs the worker's drain.
    call_reviews_collection.create_index([("client_id", 1), ("contact_phone", 1)], unique=True)
    call_reviews_collection.create_index([("status", 1), ("updated_at", 1)])
    call_transcripts_collection.create_index("call_id", unique=True)
    conversations_collection.create_index([("client_id", 1), ("contact_phone", 1)])
    # Backs the inbox/template tab split and its counts. (It cannot help the
    # sort, which is on a computed rank and always runs in memory.)
    conversations_collection.create_index(
        [("client_id", 1), ("awaiting_template_reply", 1), ("last_message_at", -1)]
    )
