from __future__ import annotations

from backend.bot.models import CRM_FEATURE_KEYS, SetClientFeaturesRequest, CallRecord, CallRecordingConfig, CallReview
import hmac
from typing import Any
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import ipaddress
import socket
import re
import requests
from pydantic import ValidationError
from fastapi import HTTPException
import os
import json
import time
import asyncio
from uuid import uuid4
import backend.bot.llm_service as llm_service
from backend.bot.database import db
from backend.bot.utils import now_utc, short_id, render_text, resolve_runtime_text
from backend.bot.models import (
    FullSetupRequest,
    Client,
    User,
    WhatsAppAccount,
    Workflow,
    WorkflowNode,
    WorkflowRun,
    WorkflowNodeRun,
    TokenUsage,
    Conversation,
    MessageRecord,
    NodeResponse,
    TestWebhookRequest,
    LoginRequest,
    SendMessageConfig,
    AskQuestionConfig,
    ConditionConfig,
    WebhookConfig,
    GoogleSheetsConfig,
    AiConversationConfig,
    GenerateIdConfig,
    SetVariableConfig,
    CrmPushConfig,
    GoogleConnection,
    EmbeddedSignupCompleteRequest,
    RegisterPhoneNumberRequest,
    AskQuestionListConfig,
    UpdateContactRequest,
    CreateClientRequest,
    UpdateClientRequest,
    CreateUserRequest,
    UpdateUserRequest,
    CreateWhatsAppAccountRequest,
    UpdateWhatsAppAccountRequest,
    WorkflowNodeInput,
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    UpdateWorkflowNodeRequest,
    Template,
    Contact,
    Broadcast,
    BroadcastRecipient,
    CreateTemplateRequest,
    TestSendTemplateRequest,
    UpdateDispositionRequest,
    UpdateContactFieldsRequest,
    Note,
    CreateNoteRequest,
    ImportContactsRequest,
    CreateBroadcastRequest,
)
from backend.bot.storage import (
    parse_model,
    save_client,
    save_user,
    save_whatsapp_account,
    save_google_connection,
    get_google_connection_by_id,
    save_workflow,
    save_workflow_node,
    get_whatsapp_account_by_phone_number_id,
    get_published_workflows_for_account,
    get_workflow_by_id,
    get_workflow_nodes,
    find_active_workflow_run,
    save_workflow_run,
    save_run_crm_result,
    record_ai_usage,
    get_client_ai_usage,
    set_conversation_disposition,
    find_run_by_lead_id,
    update_contact_fields,
    save_note,
    list_notes,
    get_note_by_id,
    delete_note,
    list_workflows_for_client,
    get_workflow_nodes,
    save_workflow_node_run,
    get_workflow_node_run_by_id,
    save_message,
    get_message_by_id,
    save_node_response,
    get_run_messages,
    get_run_node_responses,
    get_workflow_run_by_id,
    get_workflow_node_runs_by_run_id,
    update_message_after_send,
    get_whatsapp_account_by_id,
    update_message_status_by_meta_message_id,
    upsert_conversation_on_message,
    get_conversation_by_id,
    get_conversation_for_contact,
    list_conversations,
    count_conversation_views,
    CONVERSATION_VIEWS,
    expire_stale_conversations,
    set_conversation_status,
    set_conversation_active_run,
    reset_conversation_unread,
    get_messages_for_contact,
    merge_conversation_attributes,
    update_conversation_contact_fields,
    delete_conversation_cascade,
    set_conversation_bot_paused,
    get_client_by_id,
    get_client_by_username,
    list_clients,
    recent_template_recipients,
    save_call,
    get_call_by_id,
    get_call_by_provider_id,
    list_calls,
    list_calls_needing_recording,
    list_calls_missing_links,
    list_calls_for_agent_unassigned,
    find_conversation_by_client_phone,
    increment_call_tried,
    find_client_by_agent_name,
    get_user_by_id,
    list_users_for_client,
    list_whatsapp_accounts_for_client,
    list_workflows_for_client,
    get_workflow_node_by_id,
    soft_delete_missing_workflow_nodes,
    list_workflow_runs,
    list_leads,
    list_calls_for_patient,
    get_call_review,
    list_call_reviews,
    enqueue_call_review,
    get_workflow_runs_by_ids,
    get_conversations_by_ids,
    get_conversations_by_phones,
    find_waiting_runs_older_than,
    claim_run_for_timeout,
    list_accounts_with_inactivity_enabled,
    save_template,
    get_template_by_id,
    get_template,
    list_templates_for_account,
    delete_template_by_id,
    set_template_status,
    set_template_status_by_waba,
    upsert_contact,
    get_contact_by_id,
    list_contacts,
    set_contact_opt_out,
    update_contact_consent,
    add_contact_tags,
    get_audience_contacts,
    save_broadcast,
    get_broadcast_by_id,
    list_broadcasts_for_account,
    set_broadcast_status,
    list_running_broadcast_ids,
    bump_broadcast_counts,
    insert_broadcast_recipients,
    claim_pending_recipient,
    count_open_recipients,
    finalize_recipient_send,
    list_recipients_for_broadcast,
    get_recipient_by_meta_message_id,
    set_recipient_status,
    reclaim_stale_sending_recipients,
)
from backend.bot.auth import (
    assert_owned,
    create_client_token,
    ensure_aware_utc,
    long_live_token_delta,
    session_token_delta,
)
from backend.bot.whatsapp_service import (
    send_whatsapp_text_message,
    send_whatsapp_button_message,
    send_whatsapp_list_message,
    send_whatsapp_media_message,
    upload_whatsapp_media,
    send_whatsapp_template_message,
    download_whatsapp_media,
    mark_whatsapp_message_as_read,
    check_whatsapp_credentials,
    subscribe_whatsapp_business_account,
    create_message_template,
    list_message_templates,
    delete_message_template,
)
from backend.bot.google_sheets_service import execute_google_sheets_node
import backend.bot.google_oauth_service as google_oauth_service
import backend.bot.meta_onboarding_service as meta_onboarding_service
import backend.bot.gcs_service as gcs_service
import backend.bot.audio_service as audio_service
from backend.bot.utils import get_value_by_path, MISSING

def make_workflow_run_id(workflow_id: str):
    return f"{workflow_id}/run:{short_id()}"


def make_node_run_id(workflow_run_id: str):
    return f"{workflow_run_id}/node_run:{short_id()}"


def make_message_id():
    return f"msg:{short_id()}"


def make_response_id():
    return f"response:{short_id()}"


# WhatsApp caps interactive labels: 20 chars on a button, 24 on a list row
# title. There is no truncation in whatsapp_service, so an over-long label is
# rejected by Meta and the whole question fails to send. A list row can carry a
# 72-char `description`, so an over-long label is shown truncated in the title
# with the full text underneath.
BUTTON_LABEL_LIMIT = 20
LIST_LABEL_LIMIT = 24
LIST_DESCRIPTION_LIMIT = 72


def _resolve_option_label(label: str, variables: dict[str, Any]) -> str | None:
    """Render @variables in one option label. Returns None when the label
    references a variable that isn't set yet - e.g. a doctor-search webhook that
    returned 2 names leaves @doctor3/@doctor4 unset, and those rows must be
    dropped rather than shown to the patient as the literal text "@doctor3"."""
    if not isinstance(label, str) or "@" not in label:
        return label

    resolved, _, missing = resolve_runtime_text(text=label, variables=variables)
    if missing:
        return None
    return resolved


def _fit_label(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def get_button_option_metadata(options, variables: dict[str, Any] | None = None):
    """Button options for the outgoing payload, with @variables resolved.
    `full_label` keeps the untruncated text so the stored answer is the real
    value even when the displayed label had to be shortened."""
    variables = variables or {}
    resolved_options = []

    for option in options:
        data = option.model_dump(mode="python")
        label = _resolve_option_label(data.get("label"), variables)
        if label is None or not label.strip():
            continue
        data["full_label"] = label
        data["label"] = _fit_label(label, BUTTON_LABEL_LIMIT)
        resolved_options.append(data)

    return resolved_options


def get_list_config_metadata(list_config: AskQuestionListConfig | None,
                             variables: dict[str, Any] | None = None):
    if not list_config:
        return None

    variables = variables or {}
    data = list_config.model_dump(mode="python", exclude_none=True)

    sections = []
    for section in data.get("sections", []) or []:
        rows = []
        for row in section.get("rows", []) or []:
            label = _resolve_option_label(row.get("label"), variables)
            if label is None or not label.strip():
                continue

            row["full_label"] = label
            row["label"] = _fit_label(label, LIST_LABEL_LIMIT)

            description = _resolve_option_label(row.get("description") or "", variables)
            if description is None:
                description = ""
            # Show the full text under a truncated title so nothing is hidden.
            if not description and label != row["label"]:
                description = label
            if description:
                row["description"] = _fit_label(description, LIST_DESCRIPTION_LIMIT)
            else:
                row.pop("description", None)

            rows.append(row)

        if rows:
            section["rows"] = rows
            sections.append(section)

    data["sections"] = sections
    return data


def resolved_option_label(config: AskQuestionConfig, choice, variables: dict[str, Any]) -> str:
    """The label to STORE for a chosen option: @variables resolved and never
    truncated, so the sheet gets "Dr. Vidushi Kothari Bansal" rather than the
    display title or the literal "@doctor1"."""
    resolved = _resolve_option_label(choice.label, variables)
    return resolved if resolved is not None else choice.label

def get_option_display_labels(options): 
    #This returns full option objects into option labels. both for buttons or list config
    return [option.label for option in options]


def get_ask_question_choices(config: AskQuestionConfig):
    """This function will help in fetching all options(in case of buttons) or all rows of all sections(in case of list. Why all rows only? no section titles? it is becaues for matching user selected text , we only need rows because only it has label and id) , of ask question node. """
    if config.input_type == "buttons":
        return config.options

    if config.input_type == "list" and config.list_config:
        choices = []

        for section in config.list_config.sections:
            choices.extend(section.rows)

        return choices

    return []

def find_selected_option(
    config: AskQuestionConfig,
    user_text: str,
    variables: dict[str, Any] | None = None,
):
    choices = get_ask_question_choices(config)

    cleaned_user_text = user_text.strip()
    normalized_user_text = cleaned_user_text.lower()

    for choice in choices:
        # 1. Exact id match.
        # This handles real WhatsApp button/list clicks.
        if choice.id and cleaned_user_text == choice.id:
            return choice

        # 2. Case-insensitive label match.
        # This handles manual typing like "track order". Compare against the
        # RESOLVED label too, so someone typing "Dr. Akshita Bansal" matches a
        # row whose configured label is "@doctor2".
        candidates = {choice.label.strip().lower()}
        if variables:
            resolved = _resolve_option_label(choice.label, variables)
            if resolved:
                candidates.add(resolved.strip().lower())
                candidates.add(_fit_label(resolved, LIST_LABEL_LIMIT).strip().lower())

        if normalized_user_text in candidates:
            return choice

    return None


def normalize_trigger_text(text: str | None) -> str:
    return (text or "").strip().lower()


def select_workflow_for_message(
    published_workflows: list[Workflow],
    text: str | None,
) -> Workflow | None:
    """Keyword router for accounts with multiple published workflows.

    Exact (case-insensitive) keyword match wins, then the explicit default
    workflow. A single published workflow with no keywords keeps behaving
    like the original one-flow setup, so old data needs no migration.
    """
    normalized = normalize_trigger_text(text)

    default_workflow = None

    for workflow in published_workflows:
        for keyword in workflow.trigger_keywords:
            if normalize_trigger_text(keyword) == normalized:
                return workflow

        if workflow.is_default and default_workflow is None:
            default_workflow = workflow

    if default_workflow:
        return default_workflow

    if len(published_workflows) == 1 and not published_workflows[0].trigger_keywords:
        return published_workflows[0]

    return None


def validate_publish_rules(workflow: Workflow) -> list:
    """Routing rules across the account's published workflows: keywords
    must not collide, at most one default, and nothing unroutable."""
    errors = []

    others = [
        published
        for published in get_published_workflows_for_account(
            client_id=workflow.client_id,
            whatsapp_account_id=workflow.whatsapp_account_id,
        )
        if published.id != workflow.id
    ]

    my_keywords = {
        normalize_trigger_text(keyword)
        for keyword in workflow.trigger_keywords
        if normalize_trigger_text(keyword)
    }

    if others and not my_keywords and not workflow.is_default:
        errors.append(
            "Other workflows are already published on this WhatsApp account - "
            "this workflow needs trigger_keywords or is_default=true to be routable."
        )

    for other in others:
        other_keywords = {
            normalize_trigger_text(keyword)
            for keyword in other.trigger_keywords
            if normalize_trigger_text(keyword)
        }

        overlap = sorted(my_keywords & other_keywords)

        if overlap:
            errors.append(
                f"Keyword(s) {overlap} already used by published workflow "
                f"'{other.name}' ({other.id})."
            )

        if workflow.is_default and other.is_default:
            errors.append(
                f"Published workflow '{other.name}' ({other.id}) is already "
                "the default for this account."
            )

        if not other_keywords and not other.is_default:
            errors.append(
                f"Published workflow '{other.name}' ({other.id}) has no "
                "keywords and is not default; give it keywords or unpublish it first."
            )

    return errors


NODE_CONFIG_MODELS = {
    "send_message": SendMessageConfig,
    "ask_question": AskQuestionConfig,
    "condition": ConditionConfig,
    "webhook": WebhookConfig,
    "google_sheets": GoogleSheetsConfig,
    "ai_conversation": AiConversationConfig,
    "generate_id": GenerateIdConfig,
    "set_variable": SetVariableConfig,
}

def parse_node_config(node: WorkflowNode):
    config_model = NODE_CONFIG_MODELS.get(node.type)

    if not config_model:
        raise ValueError(f"Unsupported node type: {node.type}")

    return config_model.model_validate(node.config) 

'''what this line do config_model.model_validate(node.config)?
Here node.config is a normal dict, and model_validate() checks it against the selected config model(class), then returns a proper Pydantic object.raw_config = {
    "question": "What do you need help with?",
    "input_type": "buttons",
    "variable_name": "issue_type",
    "options": [
        {
            "id": "track_order",
            "label": "Track Order",
            "next_node_id": "node:3",
        }
    ],
}

This is just a dict.

Now validate it:

config = AskQuestionConfig.model_validate(raw_config)

This one line does two things:

1. Checks if raw_config is valid AskQuestionConfig data.
2. Returns an AskQuestionConfig object.'''

def validate_full_setup(setup: FullSetupRequest):
    errors = []

    client = setup.client
    user = setup.user
    account = setup.whatsapp_account
    workflow = setup.workflow
    nodes = setup.nodes

    if user.client_id != client.id:
        errors.append("user.client_id must match client.id.")

    if account.client_id != client.id:
        errors.append("whatsapp_account.client_id must match client.id.")

    if workflow.client_id != client.id:
        errors.append("workflow.client_id must match client.id.")

    if workflow.whatsapp_account_id != account.id:
        errors.append("workflow.whatsapp_account_id must match whatsapp_account.id.")

    errors.extend(validate_workflow_graph(workflow, nodes))

    if errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid setup JSON.",
                "errors": errors,
            },
        )


def _validate_media_config(node, config) -> list:
    """media_type and media_url must be set together (both or neither)."""
    errors = []
    media_type = getattr(config, "media_type", None)
    media_url = getattr(config, "media_url", None)

    if media_type and not media_url:
        errors.append(f"{node.type} node '{node.id}' has media_type but no media_url.")
    if media_url and not media_type:
        errors.append(f"{node.type} node '{node.id}' has media_url but no media_type.")

    return errors


def _validate_ask_question_node(node, config, node_id_set) -> list:
    """Structural checks for one ask_question node's parsed config."""
    errors = []

    # Default branch (free-text fallback) is optional; if set it must point at
    # a real node. None = re-prompt on this node, always valid.
    if config.default_next_node_id and config.default_next_node_id not in node_id_set:
        errors.append(
            f"ask_question node '{node.id}' has invalid default_next_node_id "
            f"'{config.default_next_node_id}'."
        )

    if config.input_type == "buttons":
        if config.list_config:
            errors.append(
                f"ask_question node '{node.id}' uses buttons but has list_config."
            )

        if not config.options:
            errors.append(
                f"ask_question node '{node.id}' uses buttons but has no options."
            )

        if len(config.options) > 3:
            errors.append(
                f"ask_question node '{node.id}' uses buttons but has more than 3 options."
            )

        option_labels = [option.label for option in config.options]
        option_ids = [option.id for option in config.options if option.id]

        if len(option_labels) != len(set(option_labels)):
            errors.append(
                f"ask_question node '{node.id}' has duplicate button labels."
            )

        if len(option_ids) != len(set(option_ids)):
            errors.append(
                f"ask_question node '{node.id}' has duplicate button ids."
            )

        for index, option in enumerate(config.options):
            if not option.id:
                errors.append(
                    f"ask_question node '{node.id}' button option {index + 1} is missing id."
                )

            if option.next_node_id not in node_id_set:
                errors.append(
                    f"ask_question node '{node.id}' button option {index + 1} has invalid next_node_id."
                )

    elif config.input_type == "list":
        if config.options:
            errors.append(
                f"ask_question node '{node.id}' uses list but has button options."
            )

        if not config.list_config:
            errors.append(
                f"ask_question node '{node.id}' uses list but has no list_config."
            )

        else:
            button_text = config.list_config.button_text

            if not button_text:
                errors.append(
                    f"ask_question node '{node.id}' list button_text is required."
                )

            if len(button_text) > 20:
                errors.append(
                    f"ask_question node '{node.id}' list button_text is longer than 20 characters."
                )

            if not config.list_config.sections:
                errors.append(
                    f"ask_question node '{node.id}' uses list but has no sections."
                )

            all_rows = []
            section_titles = []

            for section_index, section in enumerate(config.list_config.sections):
                section_titles.append(section.title)

                if not section.title:
                    errors.append(
                        f"ask_question node '{node.id}' list section {section_index + 1} has no title."
                    )

                if len(section.title) > 24:
                    errors.append(
                        f"ask_question node '{node.id}' list section {section_index + 1} title is longer than 24 characters."
                    )

                if not section.rows:
                    errors.append(
                        f"ask_question node '{node.id}' list section {section_index + 1} has no rows."
                    )

                all_rows.extend(section.rows)

            if len(section_titles) != len(set(section_titles)):
                errors.append(
                    f"ask_question node '{node.id}' has duplicate list section titles."
                )

            if len(all_rows) > 10:
                errors.append(
                    f"ask_question node '{node.id}' uses list but has more than 10 total rows."
                )

            row_labels = [row.label for row in all_rows]
            row_ids = [row.id for row in all_rows if row.id]

            if len(row_labels) != len(set(row_labels)):
                errors.append(
                    f"ask_question node '{node.id}' has duplicate list row labels."
                )

            if len(row_ids) != len(set(row_ids)):
                errors.append(
                    f"ask_question node '{node.id}' has duplicate list row ids."
                )

            for index, row in enumerate(all_rows):
                if not row.id:
                    errors.append(
                        f"ask_question node '{node.id}' list row {index + 1} is missing id."
                    )

                if row.next_node_id not in node_id_set:
                    errors.append(
                        f"ask_question node '{node.id}' list row {index + 1} has invalid next_node_id."
                    )

    else:
        if config.options:
            errors.append(
                f"text ask_question node '{node.id}' should not have options."
            )

        if config.list_config:
            errors.append(
                f"text ask_question node '{node.id}' should not have list_config."
            )

        if node.next_node_id and node.next_node_id not in node_id_set:
            errors.append(
                f"text ask_question node '{node.id}' has invalid next_node_id '{node.next_node_id}'."
            )

    return errors


def _validate_condition_node(node, config, node_id_set) -> list:
    """Structural checks for one condition node's parsed config."""
    errors = []

    if not config.conditions and not config.default_next_node_id:
        errors.append(
            f"condition node '{node.id}' needs conditions or default_next_node_id."
        )

    for index, condition in enumerate(config.conditions):
        if condition.next_node_id not in node_id_set:
            errors.append(
                f"condition node '{node.id}' rule {index + 1} has invalid next_node_id."
            )

    if config.default_next_node_id and config.default_next_node_id not in node_id_set:
        errors.append(
            f"condition node '{node.id}' has invalid default_next_node_id."
        )

    return errors


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_webhook_node(node, config, node_id_set) -> list:
    """Structural checks for one webhook node's parsed config."""
    errors = []

    if not config.url or not config.url.strip():
        errors.append(f"webhook node '{node.id}' requires a url.")

    if node.next_node_id and node.next_node_id not in node_id_set:
        errors.append(f"webhook node '{node.id}' has invalid next_node_id.")

    for variable_name, json_path in config.extract.items():
        if not _IDENTIFIER.match(variable_name):
            errors.append(
                f"webhook node '{node.id}' extract variable '{variable_name}' "
                "is not a valid identifier."
            )
        if not json_path or not json_path.strip():
            errors.append(
                f"webhook node '{node.id}' extract variable '{variable_name}' "
                "has an empty path."
            )

    if config.store_status_in and not _IDENTIFIER.match(config.store_status_in):
        errors.append(
            f"webhook node '{node.id}' store_status_in is not a valid identifier."
        )

    return errors


def _validate_google_sheets_node(node, config, node_id_set) -> list:
    """Structural checks for one google_sheets node's parsed config. Purely
    offline - it never hits Google (that happens at runtime)."""
    errors = []

    if not config.google_connection_id or not config.google_connection_id.strip():
        errors.append(f"google_sheets node '{node.id}' requires a google_connection_id.")
    if not config.spreadsheet_id or not config.spreadsheet_id.strip():
        errors.append(f"google_sheets node '{node.id}' requires a spreadsheet_id.")
    if not config.sheet_name or not config.sheet_name.strip():
        errors.append(f"google_sheets node '{node.id}' requires a sheet_name.")

    if not config.mappings:
        errors.append(f"google_sheets node '{node.id}' requires at least one mapping.")
    for mapping in config.mappings:
        if not mapping.column or not mapping.column.strip():
            errors.append(f"google_sheets node '{node.id}' has a mapping with an empty column.")

    if config.action == "update_row":
        if not config.reference:
            errors.append(
                f"google_sheets node '{node.id}' with action update_row requires a reference."
            )
        elif not config.reference.column or not config.reference.column.strip():
            errors.append(
                f"google_sheets node '{node.id}' update_row reference needs a column."
            )

    if config.save_result_in and not _IDENTIFIER.match(config.save_result_in):
        errors.append(
            f"google_sheets node '{node.id}' save_result_in is not a valid identifier."
        )

    if node.next_node_id and node.next_node_id not in node_id_set:
        errors.append(f"google_sheets node '{node.id}' has invalid next_node_id.")

    return errors


def _validate_set_variable_node(node, config, node_id_set) -> list:
    """Structural checks for one set_variable node's parsed config."""
    errors = []

    if not config.variables:
        errors.append(f"set_variable node '{node.id}' requires at least one variable.")

    for name in config.variables:
        if not name or not _IDENTIFIER.match(name):
            errors.append(
                f"set_variable node '{node.id}' variable '{name}' is not a valid identifier."
            )

    if node.next_node_id and node.next_node_id not in node_id_set:
        errors.append(f"set_variable node '{node.id}' has invalid next_node_id.")

    return errors


def _validate_generate_id_node(node, config, node_id_set) -> list:
    """Structural checks for one generate_id node's parsed config."""
    errors = []

    if not config.variable_name or not _IDENTIFIER.match(config.variable_name):
        errors.append(
            f"generate_id node '{node.id}' variable_name is not a valid identifier."
        )
    # prefix is optional: "" -> id is just "<timestamp>-<hex>".

    if node.next_node_id and node.next_node_id not in node_id_set:
        errors.append(f"generate_id node '{node.id}' has invalid next_node_id.")

    return errors


def _validate_ai_conversation_node(node, config, node_id_set) -> list:
    """Structural checks for one ai_conversation node's parsed config. Offline -
    it never calls the LLM (that happens at runtime)."""
    errors = []

    if not config.goal or not config.goal.strip():
        errors.append(f"ai_conversation node '{node.id}' requires a goal.")

    if not config.fields:
        errors.append(
            f"ai_conversation node '{node.id}' requires at least one field to collect."
        )

    seen = set()
    for field in config.fields:
        if not field.name or not field.name.strip():
            errors.append(f"ai_conversation node '{node.id}' has a field with an empty name.")
            continue
        if not _IDENTIFIER.match(field.name):
            errors.append(
                f"ai_conversation node '{node.id}' field '{field.name}' is not a valid identifier."
            )
        if field.name in seen:
            errors.append(
                f"ai_conversation node '{node.id}' has a duplicate field name '{field.name}'."
            )
        seen.add(field.name)
        if field.type == "enum" and not field.options:
            errors.append(
                f"ai_conversation node '{node.id}' enum field '{field.name}' requires options."
            )

    if config.max_turns < 1:
        errors.append(f"ai_conversation node '{node.id}' max_turns must be at least 1.")

    # Tools: catch a broken tool config at publish time, not mid-chat at 2am.
    seen_tools = set()
    for tool in config.tools:
        if not tool.name or not tool.name.strip():
            errors.append(f"ai_conversation node '{node.id}' has a tool with an empty name.")
            continue
        if tool.name in seen_tools:
            errors.append(
                f"ai_conversation node '{node.id}' has a duplicate tool name '{tool.name}'."
            )
        seen_tools.add(tool.name)

        if tool.type == "google_sheets":
            try:
                sheet_config = GoogleSheetsConfig.model_validate(
                    {**(tool.config or {}), "mappings": (tool.config or {}).get("mappings") or
                     [{"column": "placeholder", "value": ""}]}
                )
            except ValidationError as exc:
                errors.append(
                    f"ai_conversation node '{node.id}' tool '{tool.name}' has an invalid "
                    f"google_sheets config ({exc.error_count()} errors)."
                )
                continue
            if sheet_config.action == "update_row" and not sheet_config.reference:
                errors.append(
                    f"ai_conversation node '{node.id}' tool '{tool.name}' uses update_row "
                    "but has no reference (which row to update)."
                )

    # Hand-back target: config override wins, else the node's linear next.
    target = config.next_node_id or node.next_node_id
    if target and target not in node_id_set:
        errors.append(
            f"ai_conversation node '{node.id}' has an invalid next_node_id '{target}'."
        )

    return errors


def validate_workflow_graph(workflow: Workflow, nodes: list[WorkflowNode]) -> list:
    """Every structural check for one workflow graph, as an error list
    instead of an exception - shared by /dev/setup, workflow create,
    node edits, /validate and /publish. Per-node-type checks live in the
    `_validate_*_node` helpers."""
    errors = []

    node_ids = [node.id for node in nodes]
    node_id_set = set(node_ids)

    if len(node_ids) != len(node_id_set):
        errors.append("Duplicate node IDs found.")

    if not workflow.first_node_id:
        errors.append("workflow.first_node_id is required.")

    elif workflow.first_node_id not in node_id_set:
        errors.append("workflow.first_node_id must exist in nodes.")

    for node in nodes:
        if node.client_id != workflow.client_id:
            errors.append(f"node '{node.id}' has wrong client_id.")

        if node.workflow_id != workflow.id:
            errors.append(f"node '{node.id}' has wrong workflow_id.")

        if node.next_node_id and node.next_node_id not in node_id_set:
            errors.append(
                f"node '{node.id}' has invalid next_node_id '{node.next_node_id}'."
            )

        try:
            config = parse_node_config(node)

        except ValidationError as error:
            errors.append(
                {
                    "node_id": node.id,
                    "node_type": node.type,
                    "message": "Invalid node config.",
                    "errors": error.errors(),
                }
            )
            continue

        except ValueError as error:
            errors.append(
                {
                    "node_id": node.id,
                    "node_type": node.type,
                    "message": str(error),
                }
            )
            continue

        if isinstance(config, AskQuestionConfig):
            errors.extend(_validate_ask_question_node(node, config, node_id_set))
        elif isinstance(config, ConditionConfig):
            errors.extend(_validate_condition_node(node, config, node_id_set))
        elif isinstance(config, WebhookConfig):
            errors.extend(_validate_webhook_node(node, config, node_id_set))
        elif isinstance(config, GoogleSheetsConfig):
            errors.extend(_validate_google_sheets_node(node, config, node_id_set))
        elif isinstance(config, AiConversationConfig):
            errors.extend(_validate_ai_conversation_node(node, config, node_id_set))
        elif isinstance(config, GenerateIdConfig):
            errors.extend(_validate_generate_id_node(node, config, node_id_set))
        elif isinstance(config, SetVariableConfig):
            errors.extend(_validate_set_variable_node(node, config, node_id_set))

        if isinstance(config, (SendMessageConfig, AskQuestionConfig)):
            errors.extend(_validate_media_config(node, config))

    return errors


def validate_node_shapes(nodes: list[WorkflowNode]) -> list:
    """Draft-lenient check: config must be well-formed and any edge target
    that IS set must point at a real node - but null/cut edges are allowed
    (you're mid-edit). Used by the connections editor and node edits."""
    errors = []
    node_id_set = {node.id for node in nodes}

    for node in nodes:
        try:
            parse_node_config(node)
        except ValidationError as error:
            errors.append({
                "node_id": node.id,
                "message": "Invalid node config.",
                "errors": error.errors(),
            })
            continue
        except ValueError as error:
            errors.append({"node_id": node.id, "message": str(error)})
            continue

        for edge in get_node_edges(node):
            target = edge["target"]
            if target and target not in node_id_set:
                errors.append(
                    f"node '{node_local_id(node.id)}' edge '{edge['handle']}' "
                    f"points at missing node '{target}'."
                )

    return errors


def analyze_graph(workflow: Workflow, nodes: list[WorkflowNode]) -> dict:
    """Reachability report over the uniform edge view: which nodes can't be
    reached from the entry, and which edges dangle into nothing."""
    node_by_id = {node.id: node for node in nodes}

    dangling = []
    for node in nodes:
        for edge in get_node_edges(node):
            target = edge["target"]
            if target and target not in node_by_id:
                dangling.append({
                    "node_id": node.id,
                    "handle": edge["handle"],
                    "target": target,
                })

    reachable = set()
    if workflow.first_node_id and workflow.first_node_id in node_by_id:
        stack = [workflow.first_node_id]
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in get_node_edges(node_by_id[current]):
                target = edge["target"]
                if target and target in node_by_id and target not in reachable:
                    stack.append(target)

    orphans = [node.id for node in nodes if node.id not in reachable]

    warnings = []
    if orphans:
        warnings.append(f"{len(orphans)} node(s) unreachable from the entry node.")
    if dangling:
        warnings.append(f"{len(dangling)} edge(s) point at a missing node.")

    return {"orphans": orphans, "dangling": dangling, "warnings": warnings}


def validate_for_publish(workflow: Workflow, nodes: list[WorkflowNode]) -> list:
    """Strict, publish-time check: node shapes + full structural validation
    (via validate_workflow_graph, which requires every branch wired) +
    reachability (no orphans, no dangling)."""
    errors = list(validate_workflow_graph(workflow, nodes))

    report = analyze_graph(workflow, nodes)
    for item in report["dangling"]:
        errors.append(
            f"node '{node_local_id(item['node_id'])}' edge '{item['handle']}' "
            f"points at a missing node."
        )
    for orphan in report["orphans"]:
        errors.append(f"node '{node_local_id(orphan)}' is unreachable from the entry node.")

    return errors


def save_full_setup(
    setup: FullSetupRequest,
    client_id: str | None = None,
): # in routes , it will come as FullSetupRequest object , u can see routes
    if client_id is not None and setup.client.id != client_id:
        raise HTTPException(status_code=404, detail="Client not found.")

    validate_full_setup(setup)

    workflow = setup.workflow
    nodes = setup.nodes

    if workflow.status == "published":
        publish_errors = validate_publish_rules(workflow)

        if publish_errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Workflow cannot be published.",
                    "errors": publish_errors,
                },
            )

    workflow.node_ids = [node.id for node in nodes]

    # Re-POSTing a setup must not wipe credentials that were set via the
    # account APIs (setup JSONs usually carry no token).
    existing_account = get_whatsapp_account_by_id(setup.whatsapp_account.id)
    if existing_account:
        if setup.whatsapp_account.access_token is None:
            setup.whatsapp_account.access_token = existing_account.access_token
        if setup.whatsapp_account.webhook_verify_token is None:
            setup.whatsapp_account.webhook_verify_token = existing_account.webhook_verify_token

    save_client(setup.client)
    save_user(setup.user)
    save_whatsapp_account(setup.whatsapp_account)

    for google_connection in setup.google_connections:
        if google_connection.client_id != setup.client.id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Google connection '{google_connection.id}' does not belong "
                    f"to client '{setup.client.id}'."
                ),
            )
        save_google_connection(google_connection)

    save_workflow(workflow)

    for node in nodes:
        save_workflow_node(node)

    # Nodes dropped from a re-POSTed graph used to leak as live engine
    # nodes forever; soft-delete anything not in the new graph.
    soft_delete_missing_workflow_nodes(
        workflow_id=workflow.id,
        keep_ids=workflow.node_ids,
    )

    return {
        "message": "Setup saved successfully.",
        "client_id": setup.client.id,
        "whatsapp_account_id": setup.whatsapp_account.id,
        "google_connections_count": len(setup.google_connections),
        "workflow_id": workflow.id,
        "total_nodes": len(nodes),
        "pending_google_auth": google_connections_needing_auth(nodes, setup.client.id),
    }


def create_dev_google_connection(
    connection: GoogleConnection,
    client_id: str | None = None,
):
    """Dev helper: create/update one Google connection (holds the refresh
    token). Used when only the token changed, without re-running full setup.
    Never echoes the tokens back."""
    client = get_client_by_id(connection.client_id)
    if not client:
        raise HTTPException(
            status_code=404,
            detail=f"Client '{connection.client_id}' not found.",
        )
    if client_id is not None and connection.client_id != client_id:
        raise HTTPException(status_code=404, detail="Client not found.")

    save_google_connection(connection)

    return {
        "status": "ok",
        "google_connection": {
            "id": connection.id,
            "client_id": connection.client_id,
            "created_by_user_id": connection.created_by_user_id,
            "google_email": connection.google_email,
            "scopes": connection.scopes,
            "status": connection.status,
        },
    }


def google_connections_needing_auth(
    nodes: list[WorkflowNode],
    client_id: str,
) -> list[dict[str, str]]:
    """Scan a workflow's nodes for google_sheets nodes whose referenced
    connection has no usable token yet, and return a Google consent URL for each
    (deduped). The admin console opens these to complete OAuth."""
    pending: dict[str, str] = {}

    for node in nodes:
        if node.type != "google_sheets":
            continue
        try:
            config = parse_node_config(node)
        except Exception:
            continue
        connection_id = getattr(config, "google_connection_id", None)
        if not connection_id or connection_id in pending:
            continue

        connection = get_google_connection_by_id(connection_id)
        if connection is None or not connection.refresh_token:
            pending[connection_id] = google_oauth_service.build_consent_url(
                connection_id=connection_id,
                client_id=client_id,
            )

    return [
        {"connection_id": cid, "auth_url": url}
        for cid, url in pending.items()
    ]


def complete_google_oauth(code: str, state: str) -> GoogleConnection:
    """OAuth callback: verify the signed state, exchange the code for tokens,
    and upsert the google_connection with the refresh token."""
    parsed = google_oauth_service.verify_state(state)
    connection_id = parsed["connection_id"]
    client_id = parsed["client_id"]

    tokens = google_oauth_service.exchange_code_for_tokens(code)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh_token (re-consent required).",
        )

    access_token = tokens.get("access_token")
    email = (
        google_oauth_service.fetch_google_email(access_token)
        if access_token
        else None
    )

    connection = GoogleConnection(
        id=connection_id,
        client_id=client_id,
        google_email=email,
        scopes=google_oauth_service.SCOPES,
        access_token=access_token,
        refresh_token=refresh_token,
        status="connected",
    )
    save_google_connection(connection)
    return connection


def complete_embedded_signup(
    request: EmbeddedSignupCompleteRequest,
    client_id: str | None = None,
):
    """Finish Meta Embedded Signup: exchange the code for the client's business
    (BISU) token, subscribe our app to their WABA, read the phone metadata, and
    create/update the whatsapp_account with the token on it (the send engine
    reads account.access_token, so onboarded clients message immediately)."""
    if client_id is not None and request.client_id != client_id:
        raise HTTPException(status_code=404, detail="Client not found.")

    client = get_client_by_id(request.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")

    token_response = meta_onboarding_service.exchange_code_for_business_token(request.code)
    business_token = token_response["access_token"]

    subscribe_whatsapp_business_account(
        whatsapp_business_account_id=request.waba_id,
        access_token=business_token,
    )

    phone_metadata = meta_onboarding_service.get_phone_number_metadata(
        phone_number_id=request.phone_number_id,
        access_token=business_token,
    )

    account_id = f"wa:{request.client_id}:{request.phone_number_id}"
    account = WhatsAppAccount(
        id=account_id,
        client_id=request.client_id,
        name=phone_metadata.get("verified_name") or "WhatsApp Account",
        phone_number_id=request.phone_number_id,
        display_phone_number=phone_metadata.get("display_phone_number"),
        whatsapp_business_account_id=request.waba_id,
        verified_name=phone_metadata.get("verified_name"),
        quality_rating=phone_metadata.get("quality_rating"),
        access_token=business_token,
        # Reuse the platform verify token for this app's single webhook.
        webhook_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN"),
        status="connected",
    )
    save_whatsapp_account(account)

    return {
        "status": "embedded_signup_completed",
        "client_id": request.client_id,
        "whatsapp_account_id": account_id,
        "waba_id": request.waba_id,
        "phone_number_id": request.phone_number_id,
        "display_phone_number": account.display_phone_number,
        "verified_name": account.verified_name,
        "quality_rating": account.quality_rating,
        "next_step": "register_phone_number",
    }


def register_whatsapp_account(
    account_id: str,
    request: RegisterPhoneNumberRequest,
    client_id: str | None = None,
):
    """Register an onboarded number for the Cloud API (needed within 14 days of
    Embedded Signup) using its stored per-account token."""
    account = get_whatsapp_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="WhatsApp account not found.")
    if client_id is not None:
        assert_owned(account, client_id, "WhatsApp account")
    if not account.access_token:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp account has no stored access token.",
        )

    meta_response = meta_onboarding_service.register_phone_number(
        phone_number_id=account.phone_number_id,
        access_token=account.access_token,
        pin=request.pin,
    )

    account.status = "connected"
    save_whatsapp_account(account)

    return {
        "status": "registered",
        "whatsapp_account_id": account_id,
        "phone_number_id": account.phone_number_id,
        "meta_response": meta_response,
    }


def build_node_map(nodes: list[WorkflowNode]) -> dict[str, WorkflowNode]:
    return {
        node.id: node
        for node in nodes
    }


def create_outgoing_message(
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    text: str,
    message_type: str = "text",
    metadata: dict[str, Any] | None = None,
):
    message = MessageRecord(
        id=make_message_id(),
        client_id=run.client_id,
        whatsapp_account_id=run.whatsapp_account_id,
        workflow_id=run.workflow_id,
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        contact_phone=run.contact_phone,
        direction="outgoing",
        message_type=message_type,
        text=text,
        metadata=metadata or {},
        status="created",
    )

    save_message(message)

    upsert_conversation_on_message(
        client_id=run.client_id,
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
        text=text,
        direction="outgoing",
        # Workflow nodes send text/interactive today; forwarded so a future
        # template node cannot silently skip the awaiting-reply flag.
        message_type=message_type,
    )

    return message


def create_incoming_message(
    client_id: str,
    whatsapp_account_id: str,
    contact_phone: str,
    text: str,
    workflow_id: str | None = None,
    workflow_run_id: str | None = None,
    node_run_id: str | None = None,
    message_type: str = "text",
    metadata: dict[str, Any] | None = None,
):
    metadata = metadata or {}

    # If we already told Meta the message was read (blue ticks),
    # our own record reflects that instead of plain "received".
    status = "read" if metadata.get("marked_read_on_whatsapp") else "received"

    message = MessageRecord(
        id=make_message_id(),
        client_id=client_id,
        whatsapp_account_id=whatsapp_account_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        contact_phone=contact_phone,
        direction="incoming",
        message_type=message_type,
        text=text,
        metadata=metadata,
        status=status,
    )

    save_message(message)

    return message

def record_send_result(
    message: MessageRecord,
    *,
    meta_response: dict | None = None,
    error_detail: Any = None,
):
    """Applies the outcome of a WhatsApp send to a message and persists it:
    on success stores meta_response + meta_message_id and marks it 'sent';
    on failure stores send_error and marks it 'failed'. Shared by the engine
    sender and the agent sender."""
    if error_detail is not None:
        message.metadata["send_error"] = error_detail
        message.status = "failed"
    else:
        message.metadata["meta_response"] = meta_response
        meta_messages = (meta_response or {}).get("messages", [])
        if meta_messages:
            message.metadata["meta_message_id"] = meta_messages[0].get("id")
        message.status = "sent"

    update_message_after_send(
        message_id=message.id,
        status=message.status,
        metadata=message.metadata,
    )


# Meta's customer service window: free-form ("session") messages are only
# allowed within 24 hours of the customer's last inbound message. Past that,
# Meta rejects the send (error #131047) - the only escape hatch is a template.
WHATSAPP_SESSION_WINDOW = timedelta(hours=24)


def is_within_service_window(conversation: Conversation | None) -> bool:
    """True if we may still send a free-form message to this contact.

    Measured from the customer's last inbound message. No conversation or no
    inbound yet -> False: you cannot open a session the customer never started.
    """
    if conversation is None or conversation.last_inbound_at is None:
        return False
    # now_utc() is timezone-aware, but datetimes round-tripped through Mongo
    # come back naive - coerce to UTC so the subtraction doesn't raise.
    last_inbound_at = conversation.last_inbound_at
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)
    return now_utc() - last_inbound_at < WHATSAPP_SESSION_WINDOW


def send_outgoing_message_to_whatsapp(
    run: WorkflowRun,
    message: MessageRecord,
):
    if message.direction != "outgoing":
        return

    if message.message_type not in [
        "text", "interactive_buttons", "interactive_list", "image", "document"
    ]:
        return

    account = get_whatsapp_account_by_id(run.whatsapp_account_id)

    if not account:
        record_send_result(message, error_detail="WhatsApp account not found for sending.")
        return

    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )

    if not is_within_service_window(conversation):
        record_send_result(
            message,
            error_detail="Outside the 24-hour customer service window - customer must message first.",
        )
        return

    try:
        if message.message_type == "text":
            meta_response = send_whatsapp_text_message(
                phone_number_id=account.phone_number_id,
                to_phone=run.contact_phone,
                text=message.text or "",
                access_token=account.access_token,
            )

        elif message.message_type == "interactive_buttons":
            buttons = [
                {"id": option["id"], "title": option["label"]}
                for option in message.metadata.get("options", [])
            ]

            meta_response = send_whatsapp_button_message(
                phone_number_id=account.phone_number_id,
                to_phone=run.contact_phone,
                body_text=message.text or "",
                buttons=buttons,
                access_token=account.access_token,
            )
        elif message.message_type in ("image", "document"):
            media = message.metadata.get("media") or {}
            # Prefer a freshly-signed URL for our private GCS objects; fall back
            # to a literal external link.
            gcs_uri = media.get("gcs_uri")
            link = gcs_service.generate_signed_url(gcs_uri) if gcs_uri else media.get("link")

            if not link:
                record_send_result(message, error_detail="Media message has no link/gcs_uri.")
                return

            meta_response = send_whatsapp_media_message(
                phone_number_id=account.phone_number_id,
                to_phone=run.contact_phone,
                media_type=message.message_type,
                link=link,
                caption=message.text or None,
                filename=media.get("filename"),
                access_token=account.access_token,
            )

        else:  # interactive_list
            meta_response = send_whatsapp_list_message(
                phone_number_id=account.phone_number_id,
                to_phone=run.contact_phone,
                body_text=message.text or "",
                list_config=message.metadata.get("list_config") or {},
                access_token=account.access_token,
            )

        record_send_result(message, meta_response=meta_response)

    except HTTPException as error:
        record_send_result(message, error_detail=error.detail)
    except RuntimeError as error:
        # e.g. GCS not configured / signed-URL failure for a media send.
        record_send_result(message, error_detail=str(error))


def get_send_failure_reason(message: MessageRecord) -> str:
    send_error = message.metadata.get("send_error")

    if isinstance(send_error, dict):
        return (
            send_error.get("message")
            or send_error.get("detail")
            or str(send_error)
        )

    if send_error:
        return str(send_error)

    return "Outgoing WhatsApp message failed to send."


def fail_workflow_at_node(
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    error_message: str,
    responses: list[dict[str, Any]],
):
    """Terminate a run as failed at the current node. Generic sibling of
    fail_workflow_after_send_failure - any node can use it. Marks the node_run
    and run failed, unlinks the (still-open) conversation's active run, and
    returns the terminal dict the engine propagates to the webhook route."""
    node_run.status = "failed"
    node_run.error = error_message
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    run.status = "failed"
    run.current_node_id = node_run.node_id
    run.waiting_at_node_id = None
    run.waiting_node_run_id = None
    run.completed_at = now_utc()
    save_workflow_run(run)

    # Failed runs keep the conversation open (it needs attention), but the dead
    # run must no longer be linked as active.
    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )
    if conversation:
        set_conversation_active_run(conversation.id, None)

    return {
        "status": "failed",
        "workflow_run_id": run.id,
        "failed_at_node_id": node_run.node_id,
        "failed_node_run_id": node_run.id,
        "error": error_message,
        "messages": responses,
        "variables": run.variables,
    }


def fail_workflow_after_send_failure(
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    message: MessageRecord,
    responses: list[dict[str, Any]],
):
    error_message = get_send_failure_reason(message)

    node_run.status = "failed"
    node_run.error = error_message
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    run.status = "failed"
    run.current_node_id = node_run.node_id
    run.waiting_at_node_id = None
    run.waiting_node_run_id = None
    run.completed_at = now_utc()
    save_workflow_run(run)

    # Failed runs keep the conversation open (it needs attention),
    # but the dead run must no longer be linked as active.
    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )
    if conversation:
        set_conversation_active_run(conversation.id, None)

    responses.append(
        {
            "type": message.message_type,
            "text": message.text,
            "status": "failed",
            "message_id": message.id,
            "send_error": message.metadata.get("send_error"),
        }
    )

    return {
        "status": "failed",
        "workflow_run_id": run.id,
        "failed_at_node_id": node_run.node_id,
        "failed_node_run_id": node_run.id,
        "failed_message_id": message.id,
        "error": error_message,
        "messages": responses,
        "variables": run.variables,
    }

def evaluate_condition_node(
    node: WorkflowNode,
    variables: dict[str, Any],
) -> str | None:
    config = parse_node_config(node)

    if not isinstance(config, ConditionConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node.id}' is not a condition node.",
        )

    for condition in config.conditions:
        # Path-aware so a condition can branch on a nested value such as
        # "contact.source_id". A single-segment path behaves exactly like the
        # previous flat variables.get(), so existing conditions are unaffected;
        # an unset variable resolves to None as before.
        actual_value = get_value_by_path(variables, condition.variable)
        if actual_value is MISSING:
            actual_value = None

        if condition.operator == "equals" and actual_value == condition.value:
            return condition.next_node_id

        if condition.operator == "not_equals" and actual_value != condition.value:
            return condition.next_node_id

    return config.default_next_node_id


def build_outbound_media_metadata(config, variables) -> dict[str, Any] | None:
    """Resolve a node's media_url into the outgoing message's media metadata.

    - If media_url is an @variable pointing at previously-captured media (a dict
      carrying a gcs_uri), reference that private object by gcs_uri - a signed
      URL is minted just before send so Meta can fetch it.
    - Otherwise treat media_url as a literal external link (@variables inside
      the string are rendered).
    Returns None when the node has no media attachment."""
    media_type = getattr(config, "media_type", None)
    media_url = getattr(config, "media_url", None)

    if not media_type or not media_url:
        return None

    stripped = media_url.strip()
    filename = getattr(config, "filename", None)

    if stripped.startswith("@"):
        value = get_value_by_path(variables, stripped[1:])
        if value is not MISSING and isinstance(value, dict) and value.get("gcs_uri"):
            return {
                "type": media_type,
                "gcs_uri": value["gcs_uri"],
                "filename": filename or value.get("filename"),
                "mime_type": value.get("mime_type"),
            }

    return {
        "type": media_type,
        "link": render_text(media_url, variables),
        "filename": filename,
    }


def resolve_message_media(message_id: str, client_id: str) -> dict[str, Any]:
    """Back the inbox media proxy: fetch a message (ownership-checked) and
    return either the object's bytes (streamed from GCS) or a redirect to a
    literal external link. Raises 404 when the message has no media."""
    message = get_message_by_id(message_id)

    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")

    assert_owned(message, client_id, "Message")

    media = (message.metadata or {}).get("media") or {}
    gcs_uri = media.get("gcs_uri")
    link = media.get("link")
    media_type = media.get("type") or message.message_type

    if gcs_uri:
        data, content_type = gcs_service.download_bytes(gcs_uri)
        return {
            "kind": "bytes",
            "data": data,
            "content_type": content_type,
            "media_type": media_type,
            "filename": media.get("filename"),
        }

    if link:
        return {"kind": "redirect", "url": link}

    raise HTTPException(status_code=404, detail="Message has no stored media.")


def _run_set_variable_node(run, node, node_run, responses):
    """Writes fixed or @variable-rendered values into run.variables, then
    advances. Pure and network-free, so like generate_id it can never fail a run.

    Lets a branch record what it knows: the lead-source branches each set
    @lead_source, which is otherwise only a literal in a sheet cell and so
    invisible to the CRM push and to every downstream node."""
    config = parse_node_config(node)

    if not isinstance(config, SetVariableConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for set_variable node '{node.id}'.",
        )

    written = {}
    for name, template in (config.variables or {}).items():
        # Non-strings (numbers, bools) pass through untouched, same as sheet
        # mapping values; strings get @variable interpolation.
        value = render_text(template, run.variables) if isinstance(template, str) else template
        run.variables[name] = value
        written[name] = value

    node_run.status = "success"
    node_run.user_input = {"variables": written}
    node_run.next_node_id = node.next_node_id
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    responses.append({"type": "set_variable", "variables": list(written.keys())})

    run.current_node_id = node.next_node_id
    save_workflow_run(run)
    return node.next_node_id, None


def _run_generate_id_node(run, node, node_run, responses):
    """Generates a unique id in-process (no network) and stores it into
    run.variables[variable_name], then advances. Pure, so it can never fail the
    run - the reliable replacement for the old external lead-id webhook.
    Format: PREFIX-<YYYYMMDDHHMMSS>-<8 hex upper>."""
    config = parse_node_config(node)

    if not isinstance(config, GenerateIdConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for generate_id node '{node.id}'.",
        )

    stamp = f"{now_utc():%Y%m%d%H%M%S}-{uuid4().hex[:8].upper()}"
    generated = f"{config.prefix}-{stamp}" if config.prefix else stamp

    run.variables[config.variable_name] = generated

    node_run.status = "success"
    node_run.user_input = {
        "variable_name": config.variable_name,
        "value": generated,
    }
    node_run.next_node_id = node.next_node_id
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    responses.append({"type": "generate_id", "variable_name": config.variable_name})

    run.current_node_id = node.next_node_id
    save_workflow_run(run)
    return node.next_node_id, None


def _run_send_message_node(run, node, node_run, responses):
    """Sends the node's text (or a media attachment with a caption), then
    advances. Returns (next_node_id, terminal): terminal is set only when the
    send fails (the workflow ends there)."""
    config = parse_node_config(node)

    if not isinstance(config, SendMessageConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for send_message node '{node.id}'.",
        )

    node_run.status = "success"
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    media_meta = build_outbound_media_metadata(config, run.variables)

    if media_meta:
        message = create_outgoing_message(
            run=run,
            node_run=node_run,
            text=render_text(config.caption or config.message, run.variables),
            message_type=media_meta["type"],
            metadata={"media": media_meta},
        )
    else:
        message = create_outgoing_message(
            run=run,
            node_run=node_run,
            text=render_text(config.message, run.variables),
            message_type="text",
        )

    send_outgoing_message_to_whatsapp(run=run, message=message)

    if message.status == "failed":
        return None, fail_workflow_after_send_failure(
            run=run, node_run=node_run, message=message, responses=responses,
        )

    responses.append({"type": message.message_type, "text": message.text})

    run.current_node_id = node.next_node_id
    save_workflow_run(run)
    return node.next_node_id, None


def _run_ask_question_node(run, node, node_run, responses):
    """Sends the question and parks the run at this node awaiting an answer.
    Always terminal: returns (None, waiting-or-failure result)."""
    config = parse_node_config(node)

    if not isinstance(config, AskQuestionConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for ask_question node '{node.id}'.",
        )

    question = render_text(config.question, run.variables)
    input_type = config.input_type
    variable_name = config.variable_name

    # 0. Optional media attached to the question: sent as a leading media
    # message (best-effort - a media failure doesn't block the question).
    media_meta = build_outbound_media_metadata(config, run.variables)
    if media_meta:
        media_message = create_outgoing_message(
            run=run,
            node_run=node_run,
            text=render_text(config.caption or "", run.variables),
            message_type=media_meta["type"],
            metadata={"media": media_meta},
        )
        send_outgoing_message_to_whatsapp(run=run, message=media_message)

    # 1. Decide message type and metadata. Option labels are @variable-rendered
    # here (the question body above already is), and any option whose variables
    # aren't set is dropped - so a doctor search that returned 2 names shows 2
    # rows, not 2 rows plus a literal "@doctor3".
    if input_type == "buttons":
        message_type = "interactive_buttons"
        message_metadata = {
            "input_type": input_type,
            "options": get_button_option_metadata(config.options, run.variables),
            "store_answer_in": variable_name,
        }
    elif input_type == "list":
        message_type = "interactive_list"
        message_metadata = {
            "input_type": input_type,
            "list_config": get_list_config_metadata(config.list_config, run.variables),
            "store_answer_in": variable_name,
        }
    else:
        message_type = "text"
        message_metadata = {
            "input_type": input_type,
            "store_answer_in": variable_name,
        }

    # Every option was dropped (all its variables unresolved) - an interactive
    # payload with no rows/buttons is rejected by Meta and would leave the run
    # stuck with the patient never seeing the question. Degrade to plain text so
    # they can still answer.
    if message_type == "interactive_buttons" and not message_metadata.get("options"):
        message_type = "text"
        message_metadata = {"input_type": "text", "store_answer_in": variable_name}
    elif message_type == "interactive_list" and not (
        (message_metadata.get("list_config") or {}).get("sections")
    ):
        message_type = "text"
        message_metadata = {"input_type": "text", "store_answer_in": variable_name}

    # The question expects an uploaded file when accept_media is on.
    message_metadata["accept_media"] = config.accept_media

    # 2 + 3. Create the outgoing message record (it doubles as the DB record
    # and the WhatsApp payload) and send it.
    message = create_outgoing_message(
        run=run,
        node_run=node_run,
        text=question,
        message_type=message_type,
        metadata=message_metadata,
    )
    send_outgoing_message_to_whatsapp(run=run, message=message)

    if message.status == "failed":
        return None, fail_workflow_after_send_failure(
            run=run, node_run=node_run, message=message, responses=responses,
        )

    # 4. Mark node/run as waiting for the user's answer.
    node_run.status = "waiting_for_user"
    node_run.completed_at = None
    save_workflow_node_run(node_run)

    run.status = "waiting_for_user"
    run.current_node_id = node.id
    run.waiting_at_node_id = node.id
    run.waiting_node_run_id = node_run.id
    save_workflow_run(run)

    # 5. Build the API response based on input type.
    question_response = {
        "type": "question",
        "question": message.text,
        "input_type": input_type,
        "store_answer_in": variable_name,
        "accept_media": config.accept_media,
    }

    if input_type == "buttons":
        question_response["options"] = get_option_display_labels(config.options)
        question_response["option_details"] = message_metadata["options"]
    elif input_type == "list":
        question_response["options"] = get_option_display_labels(
            get_ask_question_choices(config)
        )
        question_response["list_config"] = message_metadata["list_config"]

    responses.append(question_response)

    return None, {
        "status": "waiting_for_user",
        "workflow_run_id": run.id,
        "messages": responses,
        "variables": run.variables,
    }


def _run_condition_node(run, node, node_run, responses):
    """Evaluates the branch and advances. Returns (next_node_id, None)."""
    next_node_id = evaluate_condition_node(node=node, variables=run.variables)

    node_run.status = "success"
    node_run.next_node_id = next_node_id
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    run.current_node_id = next_node_id
    save_workflow_run(run)
    return next_node_id, None


# Splits "a.b[0].c" / "a.b.0.c" into ["a", "b", "0", "c"].
_JSON_PATH_SEGMENT = re.compile(r"[^.\[\]]+")


def resolve_webhook_json_path(data: Any, path: str) -> Any:
    """Pull a value out of a parsed JSON response by dotted/indexed path.

    "$" or "" returns the whole body. A leading "$." is stripped, so
    "$.data.order" and "data.order" behave the same. Supports list indexes
    written as items[0] or items.0. Returns None if any segment is missing.
    """
    if path in ("", "$"):
        return data

    if path.startswith("$."):
        path = path[2:]

    current = data
    for segment in _JSON_PATH_SEGMENT.findall(path):
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
        elif isinstance(current, list):
            if not segment.lstrip("-").isdigit():
                return None
            index = int(segment)
            if index < -len(current) or index >= len(current):
                return None
            current = current[index]
        else:
            return None

    return current


def is_safe_webhook_url(url: str) -> tuple[bool, str]:
    """Block SSRF targets: only http/https, and no host that resolves to a
    loopback/private/link-local/reserved/multicast address (incl. cloud
    metadata 169.254.169.254). Resolve-then-check - not hardened against
    DNS-rebinding, which is out of scope here."""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False, f"Unsupported URL scheme: {parsed.scheme or '(none)'}"

    host = parsed.hostname
    if not host:
        return False, "URL has no host."

    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        return False, f"Could not resolve host: {error}"

    nat64_prefix = ipaddress.IPv6Address("64:ff9b::").packed[:12]

    for family, _type, _proto, _canon, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        # A public IPv4 reached over IPv6 (IPv4-mapped `::ffff:a.b.c.d` or the
        # NAT64 `64:ff9b::/96` well-known prefix, common in IPv6-only/serverless
        # networks) shows up as a "reserved" IPv6 - unwrap to the real IPv4 and
        # judge that, or we'd wrongly block legitimate public hosts.
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            elif ip.packed[:12] == nat64_prefix:
                ip = ipaddress.IPv4Address(ip.packed[12:])

        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"Blocked non-public address: {ip}"

    return True, ""


def _render_webhook_body(body, variables):
    """Recursively substitute @variables in a webhook JSON body. String leaves are
    rendered via render_text; dicts/lists are walked; other scalars pass through.
    Returns None unchanged (the common GET case)."""
    if body is None:
        return None
    if isinstance(body, str):
        return render_text(body, variables)
    if isinstance(body, dict):
        return {key: _render_webhook_body(value, variables) for key, value in body.items()}
    if isinstance(body, list):
        return [_render_webhook_body(item, variables) for item in body]
    return body


def _run_webhook_node(run, node, node_run, responses):
    """Calls an external endpoint and stores values from the JSON response into
    run.variables (same store as question answers). An HTTP failure - blocked
    URL, network error, or a 4xx/5xx status - FAILS the run by default: it is
    logged to the terminal and terminates the workflow. Set
    config.continue_on_error to advance instead and branch on store_status_in.
    A 200 response missing a mapped extract path is non-fatal (that variable is
    just left unset)."""
    config = parse_node_config(node)

    if not isinstance(config, WebhookConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for webhook node '{node.id}'.",
        )

    status_code = 0
    error_detail = None
    body: Any = None

    # Resolve @variables in the URL, query params, headers, and body so a node
    # can call e.g. ".../search?q=@department_input&branch=@branch". A missing
    # @variable degrades to its literal text (render_text never raises).
    resolved_url = render_text(config.url, run.variables)
    resolved_params = {
        key: render_text(value, run.variables)
        for key, value in (config.query_params or {}).items()
    }
    resolved_headers = {
        key: render_text(value, run.variables)
        for key, value in (config.headers or {}).items()
    }
    resolved_body = _render_webhook_body(config.body, run.variables)

    safe, reason = is_safe_webhook_url(resolved_url)
    if not safe:
        error_detail = f"URL blocked: {reason}"
    else:
        try:
            response = requests.request(
                config.method,
                resolved_url,
                headers=resolved_headers or None,
                params=resolved_params or None,
                json=resolved_body,
                timeout=config.timeout_seconds,
            )
            status_code = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = response.text
            if status_code >= 400:
                error_detail = f"Endpoint returned HTTP {status_code}."
        except requests.RequestException as error:
            error_detail = f"Request failed: {error}"

    node_run.next_node_id = node.next_node_id

    # Record the status code regardless - useful for debugging even on failure.
    if config.store_status_in:
        run.variables[config.store_status_in] = status_code

    # HTTP failure (blocked URL / network error / 4xx-5xx): log and fail the run,
    # unless the node opted into continue_on_error - then advance and let a
    # following condition node branch on store_status_in.
    if error_detail is not None:
        node_run.user_input = {
            "url": resolved_url,
            "method": config.method,
            "status_code": status_code,
            "error": error_detail,
        }
        print("WEBHOOK NODE FAILED:", flush=True)
        print(f"  node={node.id} {config.method} {resolved_url}", flush=True)
        print(f"  status_code={status_code} error={error_detail}", flush=True)

        if not config.continue_on_error:
            return None, fail_workflow_at_node(run, node_run, error_detail, responses)

        print("  continue_on_error=true -> advancing instead of failing the run",
              flush=True)
        node_run.status = "success"
        node_run.completed_at = now_utc()
        save_workflow_node_run(node_run)

        run.current_node_id = node.next_node_id
        save_workflow_run(run)
        return node.next_node_id, None

    # Success: pull mapped values out of the response into run.variables (same
    # store as answers). A missing path is non-fatal - just left unset.
    extracted = {}
    for variable_name, json_path in config.extract.items():
        value = resolve_webhook_json_path(body, json_path)
        if value is not None:
            run.variables[variable_name] = value
            extracted[variable_name] = value

    node_run.status = "success"
    node_run.user_input = {
        "url": config.url,
        "method": config.method,
        "status_code": status_code,
        "extracted": list(extracted.keys()),
        "error": None,
    }
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    run.current_node_id = node.next_node_id
    save_workflow_run(run)
    return node.next_node_id, None


def _run_google_sheets_node(run, node, node_run, responses):
    """Insert/update a row in a Google Sheet, resolving cell values from
    run.variables. A Google API failure (bad connection, missing column, no
    matching row, auth error) FAILS the run - logged and terminated, chat left
    open. Missing @variables in mappings are non-fatal. Thin wrapper: all API
    logic lives in google_sheets_service."""
    config = parse_node_config(node)

    if not isinstance(config, GoogleSheetsConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for google_sheets node '{node.id}'.",
        )

    result = execute_google_sheets_node(run=run, config=config)

    node_run.next_node_id = node.next_node_id

    if result.status == "failed":
        node_run.user_input = {**result.metadata, "error": result.error}
        print("GOOGLE SHEETS NODE FAILED:", flush=True)
        print(f"  node={node.id} action={config.action} "
              f"sheet={config.spreadsheet_id}/{config.sheet_name}", flush=True)
        print(f"  error={result.error}", flush=True)
        return None, fail_workflow_at_node(run, node_run, result.error, responses)

    node_run.status = "success"
    node_run.user_input = {**result.metadata, "error": None}
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    responses.append({"type": "google_sheets", "status": "success"})

    run.current_node_id = node.next_node_id
    save_workflow_run(run)
    return node.next_node_id, None


# --------------------------------------------------------------------------- #
# ai_conversation node
#
# A multi-turn LLM node. It reuses the ask_question pause/resume machinery: on
# entry it sends the AI's reply and parks the run at itself (waiting_for_user);
# each patient reply is routed by continue_existing_run() to
# continue_ai_conversation() below. When the AI signals completion (or the turn
# cap is hit), the collected fields are already in run.variables and the run
# advances to next_node_id so the existing sheet/webhook/confirmation tail runs
# unchanged. Nothing doctor-specific lives here - it all comes from config.
# --------------------------------------------------------------------------- #

def _ai_build_history(run_id: str) -> list[dict]:
    """Rebuild the chat transcript for the LLM from this run's messages
    (oldest-first). Outgoing -> assistant, incoming -> user."""
    history = []
    for message in get_run_messages(run_id):
        text = (message.text or "").strip()
        if message.direction == "outgoing":
            # The AI's own turns: plain text or an interactive prompt body.
            if message.message_type in ("text", "interactive_buttons", "interactive_list") and text:
                history.append({"role": "assistant", "content": text})
        elif message.direction == "incoming":
            # Any patient turn — typed text, a media upload, or a button/list TAP
            # (button_reply/list_reply, whose text is the chosen option label).
            history.append({"role": "user", "content": text or "[uploaded a file]"})
    return history


def _ai_text_has_keyword(text: str | None, keywords: list[str]) -> bool:
    if not text or not keywords:
        return False
    lowered = text.lower()
    return any(keyword and keyword.lower() in lowered for keyword in keywords)


def _ai_pending_media_field(config: AiConversationConfig, variables: dict):
    """First media field not yet captured into run.variables, or None."""
    for field in config.fields:
        if field.type == "media" and not variables.get(field.name):
            return field
    return None


def _ai_apply_collected(run: WorkflowRun, config: AiConversationConfig, collected: dict):
    """Merge the LLM's `collected` into run.variables, normalizing enum labels to
    the exact configured option and dropping empty/unknown/media keys."""
    field_by_name = {field.name: field for field in config.fields}
    for name, value in (collected or {}).items():
        field = field_by_name.get(name)
        if field is None or field.type == "media" or value is None:
            continue
        text_value = value if isinstance(value, str) else str(value)
        text_value = text_value.strip()
        if not text_value:
            continue
        if field.type == "enum" and field.options:
            match = next(
                (opt for opt in field.options if opt.lower() == text_value.lower()),
                None,
            )
            if match is not None:
                text_value = match
            elif not field.allow_other:
                # Value not in the allowed set and no free-text fallback -> skip
                # it so a bad label never reaches the sheet/condition tail.
                continue
        run.variables[name] = text_value


def _ai_required_remaining(config: AiConversationConfig, variables: dict) -> list[str]:
    remaining = []
    for field in config.fields:
        if not field.required:
            continue
        value = variables.get(field.name)
        if field.type == "media":
            if not value:
                remaining.append(field.name)
        elif value is None or (isinstance(value, str) and not value.strip()):
            remaining.append(field.name)
    return remaining


def _ai_send_text(run: WorkflowRun, node_run: WorkflowNodeRun, text: str):
    message = create_outgoing_message(
        run=run, node_run=node_run, text=text, message_type="text",
    )
    send_outgoing_message_to_whatsapp(run=run, message=message)
    return message


def _ai_resolve_options(config: AiConversationConfig, turn) -> tuple[list[str], str | None]:
    """Options for an interactive reply: a named field's enum options win, else the
    turn's generic options. Returns (options, section_title)."""
    if turn.ask_field:
        field = next((f for f in config.fields if f.name == turn.ask_field), None)
        if field is not None and field.type == "enum" and field.options:
            title = (field.description or field.name)[:24] or "Options"
            return list(field.options), title
    if turn.options:
        return list(turn.options), "Options"
    return [], None


def _ai_send_reply(run, node_run, config, turn):
    """Send the AI's reply as tappable buttons (1-3) / list (4-10) when the turn
    offers choices, else plain text. Option `id` == the full label so a tap
    round-trips the exact label back to the LLM. Falls back to text on any issue."""
    body = (turn.reply or "").strip()
    options, section_title = _ai_resolve_options(config, turn)

    if not options or len(options) > 10:
        return _ai_send_text(run, node_run, body or "Please continue.")

    if not body:
        body = "Please choose an option:"

    if len(options) <= 3:
        message = create_outgoing_message(
            run=run, node_run=node_run, text=body, message_type="interactive_buttons",
            metadata={"input_type": "buttons",
                      "options": [{"id": opt, "label": opt[:20]} for opt in options]},
        )
    else:
        message = create_outgoing_message(
            run=run, node_run=node_run, text=body, message_type="interactive_list",
            metadata={"input_type": "list", "list_config": {
                "button_text": "Select",
                "sections": [{"title": section_title or "Options",
                              "rows": [{"id": opt, "label": opt[:24]} for opt in options]}],
            }},
        )
    send_outgoing_message_to_whatsapp(run=run, message=message)

    # If WhatsApp rejected the interactive payload, degrade to plain text so the
    # patient still gets the question (and the run isn't left silently stuck).
    if message.status == "failed":
        _ai_send_text(run, node_run, body + "\n\n" + "\n".join(f"• {o}" for o in options))
    return message


# --------------------------------------------------------------------------- #
# AI tools
#
# The AI node can call tools mid-conversation, declared per node as
# AiToolSpec{name, type, description, config}. Each type is backed by the SAME
# implementation the equivalent graph node uses - nothing is reimplemented here.
#
# Two rules hold everywhere below:
#   1. The LLM supplies only `args`. Connection ids, spreadsheet ids, sheet
#      names, actions and row references all come from the node's stored
#      config, so no invented argument can redirect a write.
#   2. A tool failure NEVER fails the run. A graph google_sheets node calls
#      fail_workflow_at_node on error, which is right for a graph but wrong
#      mid-chat: a transient Google blip would end a live patient conversation.
#      Failures are recorded and fed back to the model on the next turn instead
#      - the same precedent as fallback_message for LLM errors.
# --------------------------------------------------------------------------- #

def _ai_log_tool_call(node_run: WorkflowNodeRun, name: str, outcome: str):
    """Record one tool outcome on the node run (visible in workflow_node_runs,
    and replayed to the model next turn so it can react to a failure)."""
    history = list((node_run.user_input or {}).get("tool_calls") or [])
    history.append({"tool": name, "outcome": outcome, "at": now_utc().isoformat()})
    patch = {"tool_calls": history[-20:]}

    # Queue failures so the next turn's prompt can tell the model what broke.
    # Consumed (and cleared) by continue_ai_conversation, so a single failure is
    # reported once rather than re-sent on every later turn.
    if outcome.startswith("failed"):
        pending = list((node_run.user_input or {}).get("pending_tool_errors") or [])
        pending.append(f"{name}: {outcome}")
        patch["pending_tool_errors"] = pending[-5:]

    node_run.user_input = {**(node_run.user_input or {}), **patch}


def _ai_drop_unresolvable(mappings: list[dict], variables: dict) -> list[dict]:
    """Drop mappings whose @variables aren't set yet.

    Missing @variables resolve to their LITERAL text (google_sheets_service.py:186),
    so saving a not-yet-collected field would write the string "@patient_name"
    into the cell. Progressive capture means writing only what we actually know."""
    kept = []
    for mapping in mappings:
        value = mapping.get("value")
        if isinstance(value, str):
            _, _, missing = resolve_runtime_text(text=value, variables=variables)
            if missing:
                continue
        kept.append(mapping)
    return kept


def _ai_tool_send_message(run, node_run, tool, args, responses) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        return "skipped: no text"
    rendered = render_text(text, run.variables)
    _ai_send_text(run, node_run, rendered)
    responses.append({"type": "text", "text": rendered})
    return "sent"


def _ai_tool_ask_question(run, node_run, config, tool, args, responses) -> str:
    """Send an ad-hoc question. Routed through _ai_send_reply so the buttons
    (1-3) / list (4-10) rule lives in exactly one place, and the answer is
    parked on `pending_variable` for continue_ai_conversation to store."""
    question = render_text(str(args.get("question") or "").strip(), run.variables)
    raw_options = args.get("options")
    options = [str(o).strip() for o in (raw_options or []) if str(o).strip()]

    if not question and not options:
        return "skipped: no question"

    _ai_send_reply(
        run, node_run, config,
        llm_service.AiTurn(reply=question, options=options),
    )
    responses.append({"type": "text", "text": question})

    variable = args.get("variable")
    if isinstance(variable, str) and variable.strip():
        node_run.user_input = {
            **(node_run.user_input or {}),
            "pending_variable": variable.strip(),
        }
    return f"asked ({len(options)} options)" if options else "asked (open)"


def _ai_tool_google_sheets(run, tool, args) -> str:
    """Write to the sheet using the node's stored connection/sheet/mappings.

    The write is driven ENTIRELY by the tool's stored template - column names +
    @variable references - resolved against run.variables. We deliberately
    ignore any `values` the LLM supplies: the model knows field names ("pain",
    "patient_name"), not the exact sheet column names ("Pain", "Name"), so
    trusting its keys made it invent non-existent columns and fail every save.
    The collected fields are already in run.variables (_ai_apply_collected runs
    before tools), so the template resolves everything the model has gathered.
    The LLM decides WHEN to save; the config decides WHAT columns exist."""
    base = dict(tool.config or {})
    mappings = [dict(m) for m in (base.get("mappings") or [])]

    mappings = _ai_drop_unresolvable(mappings, run.variables)
    if not mappings:
        return "skipped: nothing known to save yet"

    base["mappings"] = mappings
    try:
        sheet_config = GoogleSheetsConfig.model_validate(base)
    except ValidationError as exc:
        return f"failed: invalid tool config ({exc.error_count()} errors)"

    result = execute_google_sheets_node(run=run, config=sheet_config)
    if result.status == "failed":
        print(f"AI TOOL google_sheets FAILED: tool={tool.name} error={result.error}",
              flush=True)
        return f"failed: {result.error}"
    return f"saved {len(mappings)} column(s)"


def _ai_tool_generate_id(run, tool, args) -> str:
    variable = str(args.get("variable") or (tool.config or {}).get("variable_name")
                   or "lead_id").strip()
    prefix = str((tool.config or {}).get("prefix") or "")
    stamp = f"{now_utc():%Y%m%d%H%M%S}-{uuid4().hex[:8].upper()}"
    run.variables[variable] = f"{prefix}-{stamp}" if prefix else stamp
    return f"generated {variable}"


def _ai_run_tools(run, node, node_run, config, turn, responses) -> bool:
    """Run this turn's tool calls in order. Unknown names are ignored (the model
    occasionally invents one); every outcome is logged to the node run.

    Returns True if a tool asked the patient a question, so the caller knows not
    to send a second one this turn."""
    asked_question = False
    tools_by_name = {tool.name: tool for tool in (config.tools or [])}

    for call in (turn.actions or []):
        tool = tools_by_name.get(call.name)
        if tool is None:
            _ai_log_tool_call(node_run, call.name, "skipped: unknown tool")
            continue

        args = call.args or {}
        try:
            if tool.type == "send_message":
                outcome = _ai_tool_send_message(run, node_run, tool, args, responses)
            elif tool.type == "ask_question":
                outcome = _ai_tool_ask_question(
                    run, node_run, config, tool, args, responses,
                )
                asked_question = asked_question or outcome.startswith("asked")
            elif tool.type == "google_sheets":
                outcome = _ai_tool_google_sheets(run, tool, args)
            elif tool.type == "generate_id":
                outcome = _ai_tool_generate_id(run, tool, args)
            else:
                outcome = "skipped: unsupported type"
        except Exception as exc:  # noqa: BLE001 - a tool must never kill the chat
            print(f"AI TOOL CRASHED: tool={call.name} type={tool.type} "
                  f"error={type(exc).__name__}: {exc}", flush=True)
            outcome = f"failed: {type(exc).__name__}"

        _ai_log_tool_call(node_run, call.name, outcome)

    save_workflow_node_run(node_run)
    save_workflow_run(run)
    return asked_question


def _ai_pause_for_human(run: WorkflowRun):
    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )
    if conversation and not conversation.bot_paused:
        set_conversation_bot_paused(conversation.id, True)


def _ai_wait(run: WorkflowRun, node: WorkflowNode, node_run: WorkflowNodeRun):
    """Park the run at this node awaiting the next patient reply."""
    node_run.status = "waiting_for_user"
    node_run.completed_at = None
    save_workflow_node_run(node_run)

    run.status = "waiting_for_user"
    run.current_node_id = node.id
    run.waiting_at_node_id = node.id
    run.waiting_node_run_id = node_run.id
    save_workflow_run(run)


def _ai_advance(run: WorkflowRun, node: WorkflowNode, node_run: WorkflowNodeRun,
                config: AiConversationConfig) -> str | None:
    """Finish the node: clear waiting state and route to the hand-back target."""
    next_node_id = config.next_node_id or node.next_node_id

    node_run.status = "success"
    node_run.next_node_id = next_node_id
    node_run.completed_at = now_utc()
    save_workflow_node_run(node_run)

    run.status = "active"
    run.waiting_at_node_id = None
    run.waiting_node_run_id = None
    run.current_node_id = next_node_id
    save_workflow_run(run)
    return next_node_id


def _ai_waiting_result(run: WorkflowRun, responses: list) -> dict:
    return {
        "status": "waiting_for_user",
        "workflow_run_id": run.id,
        "messages": responses,
        "variables": run.variables,
    }


def _ai_apply_turn(run, node, node_run, config, turn, responses):
    """Act on one LLM turn: store collected fields, run any tools, send the
    reply, then decide whether to wait for the next reply or advance. Returns
    (action, next_node_id) with action in {"wait", "advance"}."""
    _ai_apply_collected(run, config, turn.collected)

    # Tools run before the reply so a save sees this turn's collected fields,
    # and so an ask_question tool's prompt reaches the patient in order.
    tool_asked_question = False
    if turn.actions and config.tools:
        tool_asked_question = _ai_run_tools(
            run, node, node_run, config, turn, responses,
        )

    if turn.wants_human:
        _ai_pause_for_human(run)
        if turn.reply and turn.reply.strip():
            _ai_send_text(run, node_run, turn.reply)
            responses.append({"type": "text", "text": turn.reply})
        _ai_wait(run, node, node_run)
        return "wait", None

    if (turn.reply and turn.reply.strip()) or turn.ask_field or turn.options:
        if tool_asked_question:
            # An ask_question tool already sent an interactive prompt and parked
            # `pending_variable` for it. A second one this turn would mean the
            # patient's single reply is stored against the wrong question, so
            # send any remaining text as plain context instead.
            if turn.reply and turn.reply.strip():
                _ai_send_text(run, node_run, turn.reply)
                responses.append({"type": "text", "text": turn.reply})
        else:
            _ai_send_reply(run, node_run, config, turn)
            responses.append({"type": "text", "text": turn.reply})

    turns = (node_run.user_input or {}).get("ai_turns", 0)
    if turn.done or turns >= config.max_turns:
        return "advance", _ai_advance(run, node, node_run, config)

    _ai_wait(run, node, node_run)
    return "wait", None


def _ai_render_config(config: AiConversationConfig, variables: dict) -> AiConversationConfig:
    """Resolve @variables in the parts of the prompt that are meant to be
    runtime-aware: `goal` (so it can open on the ad's @contact.headline / the
    chosen @language) and `language_hint`. `knowledge` is deliberately left raw -
    it can legitimately contain an '@' (e.g. a YouTube @handle in a URL) that must
    not be treated as a variable. A blank/missing variable renders to '', which is
    the intended behaviour for an organic (non-ad) chat."""
    return config.model_copy(update={
        "goal": render_text(config.goal, variables),
        "language_hint": render_text(config.language_hint, variables),
    })


def _bump_token_usage(existing, usage: dict, cost: float) -> TokenUsage:
    """Accumulate one turn's usage onto an in-memory TokenUsage (None -> fresh)."""
    tu = existing or TokenUsage()
    tu.prompt_tokens += int(usage.get("prompt", 0) or 0)
    tu.completion_tokens += int(usage.get("completion", 0) or 0)
    tu.total_tokens += int(usage.get("total", 0) or 0)
    tu.cached_tokens += int(usage.get("cached", 0) or 0)
    tu.turns += 1
    tu.cost_usd = round(tu.cost_usd + cost, 6)
    return tu


def _ai_record_usage(run, node_run, turn):
    """Persist one AI turn's token usage + estimated cost onto the node run, the
    run, and the client's monthly counter. Never let a metering failure break a
    live patient conversation.

    The DB-level $inc in record_ai_usage would be clobbered the instant the AI
    flow re-saves the whole run/node_run (save_workflow_run / save_workflow_node_run
    write model_to_dict, where token_usage is still None), so we ALSO accumulate
    onto the in-memory models here — that is what actually survives the save. The
    monthly rollup ($inc, its own collection) is never clobbered."""
    usage = getattr(turn, "usage", None)
    if not usage or not usage.get("total"):
        return
    try:
        cost = llm_service.usage_cost(usage)
        record_ai_usage(
            client_id=run.client_id,
            run_id=run.id,
            node_run_id=node_run.id,
            prompt=usage.get("prompt", 0),
            completion=usage.get("completion", 0),
            total=usage.get("total", 0),
            cached=usage.get("cached", 0),
            cost_usd=cost,
        )
        run.token_usage = _bump_token_usage(run.token_usage, usage, cost)
        node_run.token_usage = _bump_token_usage(node_run.token_usage, usage, cost)
    except Exception as error:  # noqa: BLE001
        print("AI USAGE RECORD FAILED:", error, flush=True)


def get_ai_usage_summary(client_id: str) -> dict:
    """Per-client AI token/cost summary: recent months + this month + totals."""
    rows = get_client_ai_usage(client_id, months=6)
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0, "turns": 0, "cost_usd": 0.0}
    for r in rows:
        for k in totals:
            totals[k] += r.get(k, 0)
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    this_month = now_utc().strftime("%Y-%m")
    return {
        "current_month": next((r for r in rows if r.get("month") == this_month), None),
        "months": rows,
        "totals": totals,
    }


def _run_ai_conversation_node(run, node, node_run, responses):
    """First entry: produce the AI's opening line from the transcript so far,
    then park (or advance if it somehow completes immediately). Always terminal
    to the execute loop unless it advances."""
    config = parse_node_config(node)
    if not isinstance(config, AiConversationConfig):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config for ai_conversation node '{node.id}'.",
        )

    node_run.user_input = {"ai_turns": 0}
    save_workflow_node_run(node_run)

    history = _ai_build_history(run.id)
    try:
        turn = llm_service.run_ai_turn(
            system_prompt=llm_service.build_system_prompt(
                _ai_render_config(config, run.variables)),
            history=history,
            model=config.model,
        )
    except llm_service.LLMError:
        if config.fallback_message.strip():
            _ai_send_text(run, node_run, config.fallback_message)
            responses.append({"type": "text", "text": config.fallback_message})
        _ai_wait(run, node, node_run)
        return None, _ai_waiting_result(run, responses)

    _ai_record_usage(run, node_run, turn)
    action, next_node_id = _ai_apply_turn(run, node, node_run, config, turn, responses)
    if action == "advance":
        return next_node_id, None
    return None, _ai_waiting_result(run, responses)


def continue_ai_conversation(
    run, workflow, nodes, waiting_node, waiting_node_run,
    user_text, message_type, incoming_metadata,
):
    """A patient reply arrived while parked at an ai_conversation node: log it,
    capture any pending media upload, run one LLM turn, then wait or advance."""
    config = parse_node_config(waiting_node)
    if not isinstance(config, AiConversationConfig):
        raise HTTPException(
            status_code=400,
            detail="Waiting node config is not valid for ai_conversation.",
        )

    incoming_media = (incoming_metadata or {}).get("media")

    incoming_message = create_incoming_message(
        client_id=run.client_id,
        whatsapp_account_id=run.whatsapp_account_id,
        workflow_id=run.workflow_id,
        workflow_run_id=run.id,
        node_run_id=waiting_node_run.id,
        contact_phone=run.contact_phone,
        text=user_text,
        message_type=message_type,
        metadata=incoming_metadata,
    )

    turns = (waiting_node_run.user_input or {}).get("ai_turns", 0) + 1
    waiting_node_run.user_input = {
        **(waiting_node_run.user_input or {}),
        "ai_turns": turns,
    }

    # An ask_question tool parked a variable name last turn: this reply is its
    # answer. Mirrors variable_name on _run_ask_question_node. A tapped option
    # arrives as its exact label (the option id == the label), so it round-trips.
    pending_variable = (waiting_node_run.user_input or {}).get("pending_variable")
    if pending_variable and (user_text or "").strip():
        run.variables[pending_variable] = user_text.strip()
        waiting_node_run.user_input = {
            key: value
            for key, value in waiting_node_run.user_input.items()
            if key != "pending_variable"
        }

    # Media upload: capture into the pending media field (reuse the accept_media
    # capture shape so downstream @report.url keeps working) and tell the LLM.
    synthetic_note = None
    if incoming_media:
        media_field = _ai_pending_media_field(config, run.variables)
        if media_field is not None:
            run.variables[media_field.name] = {
                "type": incoming_media.get("type"),
                "mime_type": incoming_media.get("mime_type"),
                "filename": incoming_media.get("filename"),
                "caption": incoming_media.get("caption"),
                "gcs_uri": incoming_media.get("gcs_uri"),
                "url": build_media_proxy_url(incoming_message.id, run.client_id),
            }
            synthetic_note = (
                f"[The patient just uploaded the requested file for '{media_field.name}'.]"
            )

    # Emergency fast-path: reply with the clinic phone immediately, still continue.
    if config.emergency_message and _ai_text_has_keyword(user_text, config.emergency_keywords):
        _ai_send_text(run, waiting_node_run, config.emergency_message)

    save_workflow_node_run(waiting_node_run)

    history = _ai_build_history(run.id)
    if synthetic_note:
        history.append({"role": "user", "content": synthetic_note})

    # Tell the model about any tool that failed last turn, once, so it can
    # retry or work around it instead of assuming the save succeeded.
    tool_errors = (waiting_node_run.user_input or {}).get("pending_tool_errors") or []
    if tool_errors:
        history.append({
            "role": "user",
            "content": "[System: these tool calls failed last turn — "
                       + "; ".join(tool_errors)
                       + ". Do not mention this to the patient.]",
        })
        waiting_node_run.user_input = {
            key: value
            for key, value in (waiting_node_run.user_input or {}).items()
            if key != "pending_tool_errors"
        }
        save_workflow_node_run(waiting_node_run)

    try:
        turn = llm_service.run_ai_turn(
            system_prompt=llm_service.build_system_prompt(
                _ai_render_config(config, run.variables)),
            history=history,
            model=config.model,
        )
    except llm_service.LLMError:
        if config.fallback_message.strip():
            _ai_send_text(run, waiting_node_run, config.fallback_message)
        _ai_wait(run, waiting_node, waiting_node_run)
        return _ai_waiting_result(run, [])

    # An explicit human-handoff keyword forces takeover regardless of the LLM.
    if _ai_text_has_keyword(user_text, config.handoff_keywords):
        turn.wants_human = True

    _ai_record_usage(run, waiting_node_run, turn)
    responses = []
    action, next_node_id = _ai_apply_turn(
        run, waiting_node, waiting_node_run, config, turn, responses,
    )
    if action == "advance":
        return execute_workflow_from_node(
            run=run, workflow=workflow, nodes=nodes, start_node_id=next_node_id,
        )
    return _ai_waiting_result(run, responses)


NODE_RUNNERS = {
    "send_message": _run_send_message_node,
    "ask_question": _run_ask_question_node,
    "condition": _run_condition_node,
    "webhook": _run_webhook_node,
    "google_sheets": _run_google_sheets_node,
    "ai_conversation": _run_ai_conversation_node,
    "generate_id": _run_generate_id_node,
    "set_variable": _run_set_variable_node,
}


def execute_workflow_from_node(
    run: WorkflowRun,
    workflow: Workflow,
    nodes: list[WorkflowNode],
    start_node_id: str | None,
):
    node_map = build_node_map(nodes)
    current_node_id = start_node_id
    responses = []
    safety_counter = 0

    while current_node_id:
        safety_counter += 1

        if safety_counter > 100:
            run.status = "failed"
            save_workflow_run(run)

            raise HTTPException(
                status_code=400,
                detail="Workflow seems to have an infinite loop.",
            )

        node = node_map.get(current_node_id)

        if not node:
            run.status = "failed"
            save_workflow_run(run)

            raise HTTPException(
                status_code=400,
                detail=f"Node not found: {current_node_id}",
            )

        node_run = WorkflowNodeRun(
            id=make_node_run_id(run.id),
            client_id=run.client_id,
            whatsapp_account_id=run.whatsapp_account_id,
            workflow_id=run.workflow_id,
            workflow_run_id=run.id,
            node_id=node.id,
            node_type=node.type,
            node_name=node.name,
            status="active",
            user_input=None,
            next_node_id=node.next_node_id,
            started_at=now_utc(),
        )

        runner = NODE_RUNNERS.get(node.type)
        if runner is None:
            # Unreachable: node.type is a constrained Literal and
            # parse_node_config rejects anything else.
            break

        current_node_id, terminal_result = runner(run, node, node_run, responses)
        if terminal_result is not None:
            return terminal_result

    run.status = "completed"
    run.current_node_id = None
    run.waiting_at_node_id = None
    run.waiting_node_run_id = None
    run.completed_at = now_utc()
    save_workflow_run(run)

    # Flow ended naturally -> the chat auto-resolves in the inbox,
    # and every collected answer becomes a WATI-style contact attribute.
    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )
    if conversation:
        set_conversation_status(
            conversation_id=conversation.id,
            status="resolved",
            resolved_by="auto",
            active_workflow_run_id=None,
        )

    # Everything the flow collected is final now - hand it to the client's CRM
    # if they have one configured. Never raises.
    push_lead_to_crm(run, reason="completed")

    return {
        "status": "completed",
        "workflow_run_id": run.id,
        "messages": responses,
        "variables": run.variables,
    }


# --------------------------------------------------------------------------- #
# Outbound CRM lead push
#
# When a run ends - completed, or closed by the inactivity sweep - a client with
# crm_push enabled has the collected variables rendered through its
# payload_template and POSTed to its CRM. This replaces polling the lead sheet
# from a Google Apps Script.
#
# Deliberately mirrors the sheet-writing rules, for the same reasons:
#   - keys whose @variables were never collected are DROPPED, never sent as the
#     literal text "@patient_name" (a CRM turns that into an agent call task);
#   - it NEVER raises - a CRM outage must not fail a patient's run or stall the
#     timeout sweep;
#   - it is stamped once per run, because both run endings call it.
# --------------------------------------------------------------------------- #

def _crm_render_payload(config: CrmPushConfig, variables: dict[str, Any]) -> tuple[dict, list[str]]:
    """Render payload_template against run variables. Returns (payload, skipped)."""
    payload: dict[str, Any] = dict(config.static_fields or {})
    skipped = []

    for key, template in (config.payload_template or {}).items():
        if not isinstance(template, str):
            payload[key] = template
            continue
        resolved, _, missing = resolve_runtime_text(text=template, variables=variables)
        if missing or not resolved.strip():
            skipped.append(key)
            continue
        payload[key] = resolved

    return payload, skipped


# HTTP statuses where retrying cannot help: the request itself is wrong (bad
# auth key, malformed body). Anything else - timeout, connection error, 5xx, or
# a 200 whose body says the CRM leg failed - is transient and stays open.
_CRM_TERMINAL_STATUSES = {400, 401, 403, 404, 422}


def _crm_local_time(value) -> str:
    """Render a timestamp in the timezone the SHEET uses.

    The sheet's =NOW() is frozen through GOOGLE_SHEETS_TIMEZONE (Asia/Kolkata),
    so sending UTC to the CRM made the same lead appear 5.5 hours earlier there
    than in the sheet. Mongo hands timestamps back naive-but-UTC, hence the
    explicit attach before converting."""
    if not value:
        return ""
    try:
        from zoneinfo import ZoneInfo

        from backend.bot.google_sheets_service import GOOGLE_SHEETS_TIMEZONE

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(ZoneInfo(GOOGLE_SHEETS_TIMEZONE))
    except Exception:  # noqa: BLE001 - a bad tz name must not lose the push
        pass
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _crm_response_outcome(response) -> tuple[bool, Any]:
    """Decide success from the response BODY, never the HTTP status.

    The relay answers 200 with {"success": false, "action": "push_failed"} when
    the CRM leg fails, and the CRM's own success shape is a single-element list.
    Trusting status < 400 recorded leads the CRM never accepted as delivered -
    the common case, given the CRM answers only some of the time."""
    try:
        parsed = response.json()
    except Exception:  # noqa: BLE001 - any unparseable body is just "not JSON"
        parsed = (getattr(response, "text", "") or "")[:400]

    result = parsed[0] if isinstance(parsed, list) and parsed else parsed
    ok = isinstance(result, dict) and result.get("success") is True
    return ok, parsed


def push_lead_to_crm(run: WorkflowRun, reason: str) -> None:
    """Fire this run's lead at the client's CRM. Silent no-op unless the client
    has crm_push enabled and `reason` is in fire_on. Never raises."""
    try:
        if run.crm_pushed_at:
            return

        client = get_client_by_id(run.client_id)
        config = getattr(client, "crm_push", None) if client else None
        if not config or not config.enabled or not config.url:
            return
        if reason not in (config.fire_on or []):
            return

        # Run-level values the flow never stored as variables: the CRM wants a
        # timestamp, which on the sheet only ever existed as =NOW().
        variables = {
            **run.variables,
            "run": {
                "id": run.id,
                # Sheet-local, not UTC - see _crm_local_time.
                "started_at": _crm_local_time(run.started_at),
                "ended_at": _crm_local_time(now_utc()),
                "reason": reason,
            },
        }
        payload, skipped = _crm_render_payload(config, variables)
        attempts = ((run.crm_push_result or {}).get("attempts") or 0) + 1

        response = requests.request(
            config.method,
            config.url,
            json=payload,
            headers=config.headers or None,
            timeout=config.timeout_seconds,
        )
        ok, parsed = _crm_response_outcome(response)
        terminal = ok or response.status_code in _CRM_TERMINAL_STATUSES

        # Only a real outcome closes the lead. A transient failure leaves
        # crm_pushed_at unset so the lead still reads as outstanding instead of
        # looking delivered - the bug that silently lost the first live lead.
        if terminal:
            run.crm_pushed_at = now_utc()
        run.crm_push_result = {
            "reason": reason,
            "status_code": response.status_code,
            "ok": ok,
            "terminal": terminal,
            "attempts": attempts,
            "skipped_fields": skipped,
            "response": parsed if isinstance(parsed, (dict, list)) else str(parsed)[:400],
            "last_attempt_at": now_utc(),
        }
        # Targeted write: the caller may hold a run loaded before something else
        # changed it (the timeout sweep does), so a whole-model save would put
        # the stale copy back. See save_run_crm_result.
        save_run_crm_result(run.id, run.crm_pushed_at, run.crm_push_result)

        if not ok:
            print(f"CRM PUSH {'REJECTED' if terminal else 'FAILED (will stay open)'}: "
                  f"run={run.id} status={response.status_code} attempt={attempts} "
                  f"{str(parsed)[:200]}", flush=True)
    except Exception as error:  # noqa: BLE001 - a CRM blip must never break a run
        print(f"CRM PUSH ERROR: run={getattr(run, 'id', '?')} "
              f"{type(error).__name__}: {error}", flush=True)
        try:
            # Network/timeout: transient by definition, so it is NOT stamped.
            run.crm_push_result = {
                "reason": reason, "ok": False, "terminal": False,
                "attempts": ((run.crm_push_result or {}).get("attempts") or 0) + 1,
                "error": f"{type(error).__name__}: {error}",
                "last_attempt_at": now_utc(),
            }
            save_run_crm_result(run.id, run.crm_pushed_at, run.crm_push_result)
        except Exception:
            pass


def build_media_proxy_url(message_id: str, client_id: str) -> str:
    """The stable, reusable path for a stored media message: the backend proxy
    GET /media/{id}. The caller appends auth (?token=<jwt>) at fetch time - the
    frontend does this via mediaUrl(); we don't bake a token into stored data
    (it would go stale). Absolute when a public base URL is set, else relative."""
    base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("FLOWR_PUBLIC_BASE_URL") or "").rstrip("/")
    path = f"/media/{message_id}"
    return f"{base}{path}" if base else path


def reprompt_waiting_question(
    run, workflow, nodes, waiting_node, waiting_node_run,
    retry_text, user_text, message_type, incoming_metadata,
):
    """Log the rejected inbound message, send a re-prompt, and re-run the
    waiting ask_question node so it re-enters waiting. The answer is never
    recorded, so run.variables stays clean."""
    create_incoming_message(
        client_id=run.client_id,
        whatsapp_account_id=run.whatsapp_account_id,
        workflow_id=run.workflow_id,
        workflow_run_id=run.id,
        node_run_id=waiting_node_run.id,
        contact_phone=run.contact_phone,
        text=user_text,
        message_type=message_type,
        metadata=incoming_metadata,
    )

    retry_message = create_outgoing_message(
        run=run,
        node_run=waiting_node_run,
        text=retry_text,
        message_type="text",
    )
    send_outgoing_message_to_whatsapp(run=run, message=retry_message)

    return execute_workflow_from_node(
        run=run,
        workflow=workflow,
        nodes=nodes,
        start_node_id=waiting_node.id,
    )


def continue_existing_run(
    run: WorkflowRun,
    user_text: str,
    message_type: str = "text",
    incoming_metadata: dict[str, Any] | None = None,
):
    if run.status != "waiting_for_user":
        raise HTTPException(
            status_code=400,
            detail="Workflow run is not waiting for user input.",
        )

    workflow = get_workflow_by_id(run.workflow_id)

    if not workflow:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found.",
        )

    nodes = get_workflow_nodes(workflow.id)
    node_map = build_node_map(nodes)

    waiting_node = node_map.get(run.waiting_at_node_id)

    if not waiting_node:
        raise HTTPException(
            status_code=400,
            detail="Waiting node not found.",
        )

    # An ai_conversation node stays parked at itself across many turns; route
    # each reply to its own multi-turn handler.
    if waiting_node.type == "ai_conversation":
        waiting_node_run = get_workflow_node_run_by_id(run.waiting_node_run_id)
        if not waiting_node_run:
            raise HTTPException(
                status_code=400,
                detail="Waiting node run not found.",
            )
        return continue_ai_conversation(
            run=run,
            workflow=workflow,
            nodes=nodes,
            waiting_node=waiting_node,
            waiting_node_run=waiting_node_run,
            user_text=user_text,
            message_type=message_type,
            incoming_metadata=incoming_metadata,
        )

    if waiting_node.type != "ask_question":
        raise HTTPException(
            status_code=400,
            detail="Waiting node is not an ask_question node.",
        )

    waiting_node_run = get_workflow_node_run_by_id(run.waiting_node_run_id)

    if not waiting_node_run:
        raise HTTPException(
            status_code=400,
            detail="Waiting node run not found.",
        )

    config = parse_node_config(waiting_node)

    if not isinstance(config, AskQuestionConfig):
        raise HTTPException(
            status_code=400,
            detail="Waiting node config is not valid for ask_question.",
        )

    # The webhook downloads inbound image/PDF to GCS and attaches a media block.
    incoming_media = (incoming_metadata or {}).get("media")

    # Media answer: when this question accepts an upload, capture the file into
    # the run variable (as a media dict) instead of text and advance. A text
    # reply to a media question re-prompts.
    if config.accept_media:
        if not incoming_media:
            retry_text = render_text(
                config.retry_message or "Please upload a photo or PDF to continue.",
                run.variables,
            )
            return reprompt_waiting_question(
                run, workflow, nodes, waiting_node, waiting_node_run,
                retry_text, user_text, message_type, incoming_metadata,
            )

        incoming_message = create_incoming_message(
            client_id=run.client_id,
            whatsapp_account_id=run.whatsapp_account_id,
            workflow_id=run.workflow_id,
            workflow_run_id=run.id,
            node_run_id=waiting_node_run.id,
            contact_phone=run.contact_phone,
            text=user_text,
            message_type=message_type,
            metadata=incoming_metadata,
        )

        captured = {
            "type": incoming_media.get("type"),
            "mime_type": incoming_media.get("mime_type"),
            "filename": incoming_media.get("filename"),
            "caption": incoming_media.get("caption"),
            "gcs_uri": incoming_media.get("gcs_uri"),
            "url": build_media_proxy_url(incoming_message.id, run.client_id),
        }
        variable_name = config.variable_name
        selected_next_node_id = waiting_node.next_node_id

        waiting_node_run.status = "success"
        waiting_node_run.user_input = {
            "variable_name": variable_name,
            "value": captured,
            "raw_text": user_text,
            "message_id": incoming_message.id,
            "received_at": now_utc(),
        }
        waiting_node_run.next_node_id = selected_next_node_id
        waiting_node_run.completed_at = now_utc()
        save_workflow_node_run(waiting_node_run)

        save_node_response(NodeResponse(
            id=make_response_id(),
            client_id=run.client_id,
            whatsapp_account_id=run.whatsapp_account_id,
            workflow_id=run.workflow_id,
            workflow_run_id=run.id,
            node_id=waiting_node.id,
            node_run_id=waiting_node_run.id,
            variable_name=variable_name,
            question=config.question,
            response=captured.get("url") or "[media]",
        ))

        run.variables[variable_name] = captured
        run.status = "active"
        run.waiting_at_node_id = None
        run.waiting_node_run_id = None
        run.current_node_id = selected_next_node_id
        save_workflow_run(run)

        return execute_workflow_from_node(
            run=run, workflow=workflow, nodes=nodes,
            start_node_id=selected_next_node_id,
        )

    # A non-media question that received media -> re-prompt for text/an option.
    if incoming_media:
        retry_text = render_text(
            config.retry_message or "Please reply with a message to continue.",
            run.variables,
        )
        return reprompt_waiting_question(
            run, workflow, nodes, waiting_node, waiting_node_run,
            retry_text, user_text, message_type, incoming_metadata,
        )

    selected_label = user_text
    selected_next_node_id = waiting_node.next_node_id

    if config.input_type in ["buttons", "list"]:
        selected_option = find_selected_option(
            config=config,
            user_text=user_text,
            variables=run.variables,
        )

        if not selected_option:
            # Free text that matches no option. If a default branch is wired to
            # another node, capture the raw text as the answer and route there;
            # otherwise re-prompt and stay on this node (the "circle back"
            # default). Never raise - a 4xx makes Meta retry-loop the webhook.
            default_target = config.default_next_node_id

            if (
                default_target
                and default_target != waiting_node.id
                and default_target in node_map
            ):
                # Fall through to the normal record-answer/advance path below,
                # storing the raw text. The incoming message is logged there.
                selected_label = user_text
                selected_next_node_id = default_target
            else:
                retry_text = render_text(
                    config.retry_message or "Please choose one of the given options.",
                    run.variables,
                )
                # Circle back: re-run this node so its buttons/list are re-sent
                # and the run re-enters waiting. The free text is only logged.
                return reprompt_waiting_question(
                    run, workflow, nodes, waiting_node, waiting_node_run,
                    retry_text, user_text, message_type, incoming_metadata,
                )
        else:
            # Store the @variable-resolved, untruncated label - the raw config
            # label may be "@doctor1", and the label we displayed may have been
            # shortened to fit WhatsApp's 24-char cap.
            selected_label = resolved_option_label(
                config, selected_option, run.variables,
            )
            selected_next_node_id = selected_option.next_node_id

    incoming_message = create_incoming_message(
        client_id=run.client_id,
        whatsapp_account_id=run.whatsapp_account_id,
        workflow_id=run.workflow_id,
        workflow_run_id=run.id,
        node_run_id=waiting_node_run.id,
        contact_phone=run.contact_phone,
        text=user_text,
        message_type=message_type,
        metadata=incoming_metadata,
    )

    variable_name = config.variable_name

    waiting_node_run.status = "success"
    waiting_node_run.user_input = {
        "variable_name": variable_name,
        "value": selected_label,
        "raw_text": user_text,
        "message_id": incoming_message.id,
        "received_at": now_utc(),
    }
    waiting_node_run.next_node_id = selected_next_node_id
    waiting_node_run.completed_at = now_utc()
    save_workflow_node_run(waiting_node_run)

    response = NodeResponse(
        id=make_response_id(),
        client_id=run.client_id,
        whatsapp_account_id=run.whatsapp_account_id,
        workflow_id=run.workflow_id,
        workflow_run_id=run.id,
        node_id=waiting_node.id,
        node_run_id=waiting_node_run.id,
        variable_name=variable_name,
        question=config.question,
        response=selected_label,
    )
    save_node_response(response)

    run.variables[variable_name] = selected_label
    run.status = "active"
    run.waiting_at_node_id = None
    run.waiting_node_run_id = None
    run.current_node_id = selected_next_node_id
    save_workflow_run(run)

    return execute_workflow_from_node(
        run=run,
        workflow=workflow,
        nodes=nodes,
        start_node_id=selected_next_node_id,
    )


def start_new_run(
    workflow: Workflow,
    contact_phone: str,
    contact_name: str | None = None,
    first_message_text: str | None = None,
    first_message_type: str = "text",
    incoming_metadata: dict[str, Any] | None = None,
):
    run = WorkflowRun(
        id=make_workflow_run_id(workflow.id),
        client_id=workflow.client_id,
        whatsapp_account_id=workflow.whatsapp_account_id,
        workflow_id=workflow.id,
        contact_phone=contact_phone,
        status="active",
        current_node_id=workflow.first_node_id,
        # Built-in contact.* variables so nodes can use @contact.phone /
        # @contact.name. Namespaced under "contact" to avoid colliding with a
        # later ask_question variable literally named "name".
        variables={
            "contact": {
                "phone": contact_phone,
                "name": contact_name or "",
                # Always present (empty for non-CTWA/organic chats) so a
                # @contact.ctwa_clid mapping renders blank, never the literal
                # @-text. Overwritten with the real click id below when present.
                "ctwa_clid": "",
                # The Meta ad id behind a Click-to-WhatsApp lead. Same empty
                # default, same reason - and it is what a campaign-lookup
                # webhook resolves to a campaign name.
                "source_id": "",
                # The ad's headline and whether it was an "ad"/"post" - so a
                # node (e.g. an ai_conversation goal) can open by confirming the
                # topic the patient clicked in on. Empty for organic chats.
                "headline": "",
                "source_type": "",
            }
        },
        started_at=now_utc(),
    )

    save_workflow_run(run)

    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )
    if conversation:
        set_conversation_active_run(conversation.id, run.id)
        # Surface the Click-to-WhatsApp click id (Meta attaches it to the first
        # ad-click message; we persist it on the conversation). Seed it as a run
        # variable so nodes can write @contact.ctwa_clid, exactly alongside the
        # built-in @contact.phone / @contact.name. Absent for organic chats.
        if (conversation.ctwa_clid or conversation.source_id
                or conversation.headline or conversation.source_type):
            if conversation.ctwa_clid:
                run.variables["contact"]["ctwa_clid"] = conversation.ctwa_clid
            if conversation.source_id:
                run.variables["contact"]["source_id"] = conversation.source_id
            if conversation.headline:
                run.variables["contact"]["headline"] = conversation.headline
            if conversation.source_type:
                run.variables["contact"]["source_type"] = conversation.source_type
            save_workflow_run(run)

    if first_message_text is not None:
        create_incoming_message(
            client_id=run.client_id,
            whatsapp_account_id=run.whatsapp_account_id,
            workflow_id=run.workflow_id,
            workflow_run_id=run.id,
            contact_phone=run.contact_phone,
            text=first_message_text,
            message_type=first_message_type,
            metadata=incoming_metadata,
        )

    nodes = get_workflow_nodes(workflow.id)

    return execute_workflow_from_node(
        run=run,
        workflow=workflow,
        nodes=nodes,
        start_node_id=workflow.first_node_id,
    )

def process_incoming_message(
    phone_number_id: str,
    from_phone: str,
    text: str,
    message_type: str = "text",
    source: str = "test_webhook",
    contact_name: str | None = None,
    incoming_metadata: dict[str, Any] | None = None,
    referral: dict[str, Any] | None = None,
):
    account = get_whatsapp_account_by_phone_number_id(
        phone_number_id
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="WhatsApp account not found for this phone_number_id.",
        )

    # Soft-deleted tenants: drop silently instead of erroring back at Meta.
    if account.status == "disconnected":
        return {
            "mode": "ignored_account_disconnected",
            "source": source,
            "from_phone": from_phone,
            "phone_number_id": phone_number_id,
            "reason": "WhatsApp account is disconnected.",
        }

    client = get_client_by_id(account.client_id)

    if client and client.status != "active":
        return {
            "mode": "ignored_client_inactive",
            "source": source,
            "from_phone": from_phone,
            "phone_number_id": phone_number_id,
            "reason": "Client is inactive.",
        }

    # If the 24h window had lapsed (from the PRE-message state), this inbound
    # starts a new session: end any stale agent handoff + workflow run so the
    # BOT handles it, not the (now-ended) agent. This is the cron-free path -
    # it fires on the message itself, even if the inbox sweep never ran.
    existing_conversation = get_conversation_for_contact(
        whatsapp_account_id=account.id,
        contact_phone=from_phone,
    )
    window_had_expired = (
        existing_conversation is not None
        and existing_conversation.last_inbound_at is not None
        and not is_within_service_window(existing_conversation)
    )
    if window_had_expired:
        cancel_active_run_for_conversation(existing_conversation)
        set_conversation_active_run(existing_conversation.id, None)
        set_conversation_bot_paused(existing_conversation.id, False)

    # Every incoming message touches the chat: (re)opens it (expired/resolved ->
    # open), refreshes the last-message preview, bumps unread, keeps the contact
    # name fresh. The preview prefers the button/list label over the raw option id.
    conversation = upsert_conversation_on_message(
        client_id=account.client_id,
        whatsapp_account_id=account.id,
        contact_phone=from_phone,
        text=(incoming_metadata or {}).get("reply_title") or text,
        direction="incoming",
        contact_name=contact_name,
        referral=referral,
    )

    # Build/refresh the broadcast audience from every inbound (dedup by
    # account+phone). STOP/UNSUBSCRIBE opts the contact out of future broadcasts.
    try:
        upsert_contact(
            whatsapp_account_id=account.id,
            client_id=account.client_id,
            phone=from_phone,
            name=contact_name,
            source="ctwa" if referral else "inbound",
            last_inbound_at=now_utc(),
            marketing_opt_in=True,  # engaging with us implies marketing consent
        )
        if (text or "").strip().lower() in ("stop", "unsubscribe"):
            update_contact_consent(account.id, from_phone, opted_out=True, marketing_opt_in=False)
    except Exception as error:  # never block message processing on contact bookkeeping
        print(f"CONTACT UPSERT FAILED: {error}", flush=True)

    # Agent takeover: while a human handles this chat, log the message but
    # never start or continue workflows. The bot resumes only after the
    # chat is closed/resolved.
    if conversation and conversation.bot_paused:
        incoming_message = create_incoming_message(
            client_id=account.client_id,
            whatsapp_account_id=account.id,
            contact_phone=from_phone,
            text=text,
            message_type=message_type,
            metadata=incoming_metadata,
        )

        return {
            "mode": "agent_handling",
            "source": source,
            "from_phone": from_phone,
            "phone_number_id": phone_number_id,
            "conversation_id": conversation.id,
            "message_id": incoming_message.id,
            "reason": "Bot is paused for this conversation; a human agent is handling it.",
        }

    active_run = find_active_workflow_run(
        client_id=account.client_id,
        whatsapp_account_id=account.id,
        contact_phone=from_phone,
    )

    if active_run:
        if active_run.status == "waiting_for_user":
            result = continue_existing_run(
                run=active_run,
                user_text=text,
                message_type=message_type,
                incoming_metadata=incoming_metadata,
            )

            return {
                "mode": "continued_existing_workflow_run",
                "source": source,
                "from_phone": from_phone,
                "phone_number_id": phone_number_id,
                **result,
            }
        else:
            # run exists, but bot is not waiting for user(i.e if user sends messages before we ask any question)
            # so do NOT continue and do NOT start a new run , instead just ignore the message
            incoming_message = create_incoming_message(
                client_id=active_run.client_id,
                whatsapp_account_id=active_run.whatsapp_account_id,
                workflow_id=active_run.workflow_id,
                workflow_run_id=active_run.id,
                node_run_id=None,
                contact_phone=active_run.contact_phone,
                text=text,
                message_type=message_type,
                metadata=incoming_metadata,
                )

            return {
                "mode": "ignored_user_message",
                "source": source,
                "from_phone": from_phone,
                "phone_number_id": phone_number_id,
                "workflow_run_id": active_run.id,
                "run_status": active_run.status,
                "message_id": incoming_message.id,
                "reason": "Workflow run is active but not waiting for user input.",
            }


    published_workflows = get_published_workflows_for_account(
        client_id=account.client_id,
        whatsapp_account_id=account.id,
    )

    # Keyword routing: exact keyword match -> default workflow -> the
    # single keywordless workflow (legacy setups). No match: log the
    # message so it shows in the inbox, but start nothing.
    workflow = select_workflow_for_message(published_workflows, text)

    if not workflow:
        incoming_message = create_incoming_message(
            client_id=account.client_id,
            whatsapp_account_id=account.id,
            contact_phone=from_phone,
            text=text,
            message_type=message_type,
            metadata=incoming_metadata,
        )

        return {
            "mode": "ignored_no_matching_workflow",
            "source": source,
            "from_phone": from_phone,
            "phone_number_id": phone_number_id,
            "message_id": incoming_message.id,
            "published_workflow_count": len(published_workflows),
            "reason": (
                "No published workflow matches this message "
                "(no keyword hit and no default workflow)."
            ),
        }

    result = start_new_run(
        workflow=workflow,
        contact_phone=from_phone,
        contact_name=contact_name,
        first_message_text=text,
        first_message_type=message_type,
        incoming_metadata=incoming_metadata,
    )

    return {
        "mode": "started_new_workflow_run",
        "source": source,
        "from_phone": from_phone,
        "phone_number_id": phone_number_id,
        **result,
    }

def process_test_webhook(request: TestWebhookRequest, client_id: str | None = None):
    if client_id is not None:
        account = get_whatsapp_account_by_phone_number_id(request.phone_number_id)
        assert_owned(account, client_id, "WhatsApp account")

    return process_incoming_message(
        phone_number_id=request.phone_number_id,
        from_phone=request.from_phone,
        text=request.text,
        message_type=request.message_type,
        source="test_webhook",
    )


def get_run_debug_data(workflow_run_id: str):
    workflow_run = get_workflow_run_by_id(workflow_run_id)

    if not workflow_run:
        raise HTTPException(
            status_code=404,
            detail="Workflow run not found.",
        )

    return {
        "workflow_run": workflow_run,
        "workflow_node_runs": get_workflow_node_runs_by_run_id(workflow_run_id),
        "messages": get_run_messages(workflow_run_id),
        "node_responses": get_run_node_responses(workflow_run_id),
    }

def verify_whatsapp_webhook(
    mode: str | None,
    verify_token: str | None,
    challenge: str | None,
):
    expected_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")

    if not expected_verify_token:
        raise HTTPException(
            status_code=500,
            detail="WHATSAPP_VERIFY_TOKEN is not configured.",
        )

    if mode == "subscribe" and verify_token == expected_verify_token and challenge:
        return challenge

    raise HTTPException(
        status_code=403,
        detail="WhatsApp webhook verification failed.",
    )


def extract_whatsapp_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        phone_number_id = value["metadata"]["phone_number_id"]

        messages = value.get("messages", [])

        if not messages:
            return None

        message = messages[0]

        from_phone = message["from"]
        message_type = message.get("type", "unknown")
        meta_message_id = message.get("id")

        contact_name = None
        contacts = value.get("contacts", [])
        if contacts:
            contact_name = contacts[0].get("profile", {}).get("name")

        # Present only when the customer arrived via a Click-to-WhatsApp ad.
        referral = message.get("referral")

        # Present when the customer replied to a specific message (button/list
        # taps always have it) — wamid of the message being replied to.
        context_wamid = (message.get("context") or {}).get("id")

        text = ""
        # Human label of the tapped button/list row. text stays the option id
        # (the engine matches by id); the label is only for display.
        reply_title = None
        # Set for supported inbound media (image/document): the raw Meta media
        # reference the router downloads to GCS.
        media_info = None

        if message_type == "text":
            text = message["text"]["body"]

        elif message_type == "button":
            button = message["button"]
            text = button.get("payload") or button.get("text") or ""
            reply_title = button.get("text")

        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                button_reply = interactive.get("button_reply", {})
                text = button_reply.get("id") or button_reply.get("title") or ""
                reply_title = button_reply.get("title")
                message_type = "button_reply"

            elif interactive_type == "list_reply":
                list_reply = interactive.get("list_reply", {})
                text = list_reply.get("id") or list_reply.get("title") or ""
                reply_title = list_reply.get("title")
                message_type = "list_reply"

            else:
                text = ""

        elif message_type in ("image", "document"):
            media = message.get(message_type, {}) or {}
            caption = media.get("caption") or ""
            text = caption
            media_info = {
                "type": message_type,
                "media_id": media.get("id"),
                "mime_type": media.get("mime_type"),
                "filename": media.get("filename"),  # documents only
                "caption": caption or None,
            }

        elif message_type == "audio":
            # WhatsApp uses type "audio" for both voice notes and audio files;
            # the `voice` flag distinguishes them (drives the mic/waveform UI).
            media = message.get("audio", {}) or {}
            text = ""
            media_info = {
                "type": "audio",
                "media_id": media.get("id"),
                "mime_type": media.get("mime_type"),
                "voice": bool(media.get("voice", False)),
            }

        else:
            text = ""

        return {
            "phone_number_id": phone_number_id,
            "from_phone": from_phone,
            "text": text,
            "message_type": message_type,
            "meta_message_id": meta_message_id,
            "contact_name": contact_name,
            "referral": referral,
            "reply_title": reply_title,
            "context_wamid": context_wamid,
            "media": media_info,
            "raw_message": message,
        }

    except (KeyError, IndexError, TypeError):
        return None

def process_status_update_webhook(payload: dict[str, Any]):
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

    except (KeyError, IndexError, TypeError):
        return {
            "ignored": True,
            "reason": "Invalid WhatsApp webhook payload structure.",
        }

    statuses = value.get("statuses", [])

    if not statuses:
        return {
            "ignored": True,
            "reason": "No statuses found in webhook payload.",
        }

    results = []

    for status_event in statuses:
        meta_message_id = status_event.get("id")
        delivery_status = status_event.get("status")

        if not meta_message_id or not delivery_status:
            results.append(
                {
                    "updated": False,
                    "reason": "Status event missing id or status.",
                    "status_event": status_event,
                }
            )
            continue

        db_result = update_message_status_by_meta_message_id(
            meta_message_id=meta_message_id,
            status=delivery_status,
            status_payload=status_event,
        )

        # If this message id belongs to a broadcast recipient, advance its
        # status and roll the delta into the broadcast's counters.
        apply_broadcast_delivery_status(
            meta_message_id, delivery_status,
            error=webhook_status_error_text(status_event),
        )

        results.append(
            {
                "updated": db_result["matched_count"] > 0,
                "applied_to_main_status": db_result.get("applied", False),
                "meta_message_id": meta_message_id,
                "incoming_status": delivery_status,
                "previous_status": db_result.get("previous_status"),
                "status": db_result.get("final_status"),
                "matched_count": db_result["matched_count"],
                "modified_count": db_result["modified_count"],
                "reason": db_result.get("reason"),
            }
        )

    return {
        "mode": "status_update",
        "processed": len(statuses),
        "results": results,
    }

def route_whatsapp_webhook_payload(payload: dict[str, Any]):
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

    except (KeyError, IndexError, TypeError):
        return {
            "ignored": True,
            "reason": "Invalid WhatsApp webhook payload structure.",
        }

    # Template approval lifecycle: Meta pushes these when a submitted template is
    # APPROVED / REJECTED / PAUSED / DISABLED. Update our local mirror.
    if change.get("field") == "message_template_status_update":
        return handle_template_status_update(payload)

    if value.get("messages"): # if the webhook contains message i.e it is the webhook which was fired because user sent a message to our bot
        extracted = extract_whatsapp_message(payload)

        if not extracted:
            return {
                "ignored": True,
                "reason": "No supported incoming message found in webhook payload.",
            }

        # Supported media (image/PDF) is allowed through even with no caption;
        # only truly unsupported/empty types are dropped.
        supported_media = extracted.get("media") is not None

        if not extracted["text"] and not supported_media:
            return {
                "ignored": True,
                "reason": f"Unsupported or empty message type: {extracted['message_type']}",
            }

        incoming_metadata = {}

        if extracted.get("reply_title"):
            incoming_metadata["reply_title"] = extracted["reply_title"]

        if extracted.get("context_wamid"):
            incoming_metadata["reply_to_wamid"] = extracted["context_wamid"]

        webhook_account = get_whatsapp_account_by_phone_number_id(
            extracted["phone_number_id"]
        )

        # Inbound media: download from Meta and store to GCS BEFORE processing,
        # so the media rides on incoming_metadata regardless of bot_paused /
        # active-run state (agents see photos too). Never 5xx back to Meta on a
        # storage failure - log it and keep the message.
        preview_text = extracted["text"]
        if supported_media:
            media = extracted["media"]
            media_block = {
                "type": media["type"],
                "mime_type": media.get("mime_type"),
                "filename": media.get("filename"),
                "caption": media.get("caption"),
                "voice": media.get("voice"),
                "gcs_uri": None,
            }
            try:
                data, mime = download_whatsapp_media(
                    media["media_id"],
                    webhook_account.access_token if webhook_account else None,
                )
                mime = mime or media.get("mime_type") or "application/octet-stream"
                # WhatsApp voice notes are OGG/Opus, which Safari cannot play in
                # an <audio> element - transcode to MP3 so the inbox plays it
                # everywhere. On failure, fall back to storing the original bytes
                # (still plays in Chrome/Android); never let it 5xx the webhook.
                if media["type"] == "audio":
                    try:
                        data = audio_service.to_mp3(data)
                        mime = "audio/mpeg"
                    except audio_service.AudioTranscodeError as error:
                        print("INBOUND AUDIO TRANSCODE FAILED:", str(error), flush=True)
                media_block["mime_type"] = mime
                media_block["gcs_uri"] = gcs_service.upload_bytes(
                    data, mime, gcs_service.extension_for_mime(mime)
                )
            except (HTTPException, RuntimeError) as error:
                media_block["error"] = "media_store_failed"
                print(
                    "INBOUND MEDIA STORE FAILED:",
                    getattr(error, "detail", str(error)),
                    flush=True,
                )

            incoming_metadata["media"] = media_block

            if not preview_text:
                if media["type"] == "document":
                    preview_text = f"📄 {media.get('filename') or 'Document'}"
                elif media["type"] == "audio":
                    preview_text = "🎤 Voice message" if media.get("voice") else "🎵 Audio"
                else:
                    preview_text = "📷 Photo"
                incoming_metadata.setdefault("reply_title", preview_text)

        if extracted.get("meta_message_id"):
            incoming_metadata["meta_message_id"] = extracted["meta_message_id"]

            # Blue ticks for the customer. A failed read receipt must never
            # block the actual message processing.
            try:
                mark_whatsapp_message_as_read(
                    phone_number_id=extracted["phone_number_id"],
                    meta_message_id=extracted["meta_message_id"],
                    access_token=webhook_account.access_token if webhook_account else None,
                )
                incoming_metadata["marked_read_on_whatsapp"] = True
            except HTTPException as error:
                incoming_metadata["marked_read_on_whatsapp"] = False
                incoming_metadata["mark_read_error"] = error.detail

        return process_incoming_message(
            phone_number_id=extracted["phone_number_id"],
            from_phone=extracted["from_phone"],
            text=extracted["text"],
            message_type=extracted["message_type"],
            source="whatsapp_webhook",
            contact_name=extracted.get("contact_name"),
            incoming_metadata=incoming_metadata,
            referral=extracted.get("referral"),
        )
    if value.get("statuses"): # if the webhook contains status i.e. it is the webhook that was fired because the message we sent to user , now it is either sent or delivered or read. thus this webhook just informs us about the updated status of our sent msg.
        return process_status_update_webhook(payload)

    return {
        "ignored": True,
        "reason": "Webhook payload did not contain messages or statuses.",
    }


def cancel_active_run_for_conversation(conversation) -> str | None:
    """Cancels the conversation's live workflow run (and its waiting node
    run), if any. Returns the cancelled run id."""
    active_run = find_active_workflow_run(
        client_id=conversation.client_id,
        whatsapp_account_id=conversation.whatsapp_account_id,
        contact_phone=conversation.contact_phone,
    )

    if not active_run:
        return None

    if active_run.waiting_node_run_id:
        waiting_node_run = get_workflow_node_run_by_id(
            active_run.waiting_node_run_id
        )
        if waiting_node_run:
            waiting_node_run.status = "cancelled"
            waiting_node_run.completed_at = now_utc()
            save_workflow_node_run(waiting_node_run)

    active_run.status = "cancelled"
    active_run.waiting_at_node_id = None
    active_run.waiting_node_run_id = None
    active_run.completed_at = now_utc()
    save_workflow_run(active_run)

    return active_run.id


def close_conversation(conversation_id: str, client_id: str):
    """Manual close from the inbox (3-dot menu). Cancels the live workflow
    run so the customer's next message starts the flow from the beginning,
    marks the chat resolved, and hands control back to the bot."""
    conversation = get_owned_conversation(conversation_id, client_id)

    cancelled_run_id = cancel_active_run_for_conversation(conversation)

    set_conversation_status(
        conversation_id=conversation.id,
        status="resolved",
        resolved_by="agent",
        active_workflow_run_id=None,
        bot_paused=False,
    )

    return {
        "conversation_id": conversation.id,
        "status": "resolved",
        "resolved_by": "agent",
        "bot_paused": False,
        "cancelled_workflow_run_id": cancelled_run_id,
    }


def reopen_conversation(conversation_id: str, client_id: str):
    """Manual re-open from the inbox. Label only: if the customer messages
    while no run is active, the workflow starts fresh as usual."""
    conversation = get_owned_conversation(conversation_id, client_id)

    set_conversation_status(
        conversation_id=conversation.id,
        status="open",
        active_workflow_run_id=conversation.active_workflow_run_id,
    )

    return {
        "conversation_id": conversation.id,
        "status": "open",
    }


def delete_conversation(conversation_id: str, client_id: str):
    """Permanently deletes a chat from the inbox: cancels any live workflow run,
    then hard-deletes the conversation and everything tied to its contact
    (messages, workflow runs, node runs, node responses). Scoped to the
    authenticated client via get_owned_conversation, so a client can only delete
    its own chats. Irreversible."""
    conversation = get_owned_conversation(conversation_id, client_id)

    cancel_active_run_for_conversation(conversation)
    deleted = delete_conversation_cascade(conversation)

    return {
        "deleted": True,
        "conversation_id": conversation.id,
        "deleted_counts": deleted,
    }


# --------------------------------------------------------------------------- #
# CRM additions (additive; the Ripply inbox never calls these)
# --------------------------------------------------------------------------- #

def update_conversation_disposition(conversation_id: str, client_id: str,
                                    request: UpdateDispositionRequest):
    """Agent-set lead outcome from the CRM. Targeted write; returns the inbox view."""
    conversation = get_owned_conversation(conversation_id, client_id)
    fields: dict[str, Any] = {}
    if request.disposition is not None:
        fields["disposition"] = request.disposition.strip() or None
    if request.remark is not None:
        fields["disposition_remark"] = request.remark.strip() or None
    if fields:
        fields["disposition_updated_at"] = now_utc()
        set_conversation_disposition(conversation.id, **fields)
    return to_inbox_conversation(get_owned_conversation(conversation_id, client_id))


def list_conversation_notes(conversation_id: str, client_id: str):
    conversation = get_owned_conversation(conversation_id, client_id)
    return {"notes": [note.model_dump(mode="json") for note in list_notes(conversation.id)]}


def add_conversation_note(conversation_id: str, client_id: str, request: CreateNoteRequest):
    conversation = get_owned_conversation(conversation_id, client_id)
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Note text is required.")
    note = Note(
        id=f"note:{short_id()}", client_id=client_id, conversation_id=conversation.id,
        text=text, created_at=now_utc(),
    )
    save_note(note)
    return note.model_dump(mode="json")


def delete_conversation_note(conversation_id: str, note_id: str, client_id: str):
    conversation = get_owned_conversation(conversation_id, client_id)
    note = get_note_by_id(note_id)
    if not note or note.conversation_id != conversation.id:
        raise HTTPException(status_code=404, detail="Note not found.")
    delete_note(note_id)
    return {"deleted": True, "note_id": note_id}


def update_contact_service(account_id: str, contact_id: str, client_id: str,
                           request: UpdateContactFieldsRequest):
    """CRM edit of a contact's name / tags (tags replace the list)."""
    _owned_account(account_id, client_id)
    contact = get_contact_by_id(contact_id)
    if not contact or contact.whatsapp_account_id != account_id:
        raise HTTPException(status_code=404, detail="Contact not found.")
    updated = update_contact_fields(contact_id, name=request.name, tags=request.tags)
    return updated.model_dump(mode="json") if updated else {}


# run.variables keys that are engine plumbing, never lead fields.
_LEAD_SCHEMA_HIDDEN = {"sheet_insert", "http_status", "contact"}


def get_lead_schema(client_id: str, workflow_id: str | None = None) -> dict[str, Any]:
    """CRM: this client's lead-field schema — {key, label, type, options} per
    collected variable — derived from its published workflow, so every client's
    different fields come out with that client's own labels:
      1. google_sheets mappings: column header -> @variable (the client's labels;
         insert-node column order first),
      2. ask_question nodes: question text + button/list options,
      3. ai_conversation fields: name / description / type / options.
    Engine plumbing (_nav vars, sheet_insert, http_status, contact) is hidden."""
    import re as _re
    var_re = _re.compile(r"^@([A-Za-z]\w*)$")

    if workflow_id:
        workflow = get_workflow_by_id(workflow_id)
        if not workflow or workflow.client_id != client_id:
            raise HTTPException(status_code=404, detail="Workflow not found.")
    else:
        result = list_workflows_for_client(client_id, status="published", limit=50)
        workflows = list(result[1] if isinstance(result, tuple) else result)
        workflow = next((w for w in workflows if getattr(w, "is_default", False)), None) \
            or (workflows[0] if workflows else None)
        if workflow is None:
            return {"workflow_id": None, "fields": []}

    nodes = get_workflow_nodes(workflow.id)
    fields: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def put(key, label=None, type_=None, options=None, prefer_label=False):
        if not key or not isinstance(key, str) or key.startswith("_") or key in _LEAD_SCHEMA_HIDDEN:
            return
        field = fields.get(key)
        if field is None:
            field = {"key": key, "label": label or key.replace("_", " ").replace("-", " ").strip().title(),
                     "type": type_ or "text", "options": []}
            fields[key] = field
            order.append(key)
        elif label and prefer_label:
            field["label"] = label
        if type_ and type_ != "text":
            field["type"] = type_
        for option in options or []:
            # "@doctor1"-style options are runtime placeholders, not real values.
            if option and not str(option).startswith("@") and option not in field["options"]:
                field["options"].append(option)
        if field["options"] and field["type"] == "text":
            field["type"] = "enum"

    # 1. Sheet column headers — the client's own labels; insert node first.
    sheet_nodes = [n for n in nodes if n.type == "google_sheets"]
    sheet_nodes.sort(key=lambda n: 0 if (n.config or {}).get("action") == "insert_row" else 1)
    for node in sheet_nodes:
        for mapping in (node.config or {}).get("mappings") or []:
            if not isinstance(mapping, dict):
                continue
            value, column = mapping.get("value"), mapping.get("column")
            if isinstance(value, str) and isinstance(column, str) and column.strip():
                match = var_re.match(value.strip())
                if match:
                    put(match.group(1), label=column.strip(), prefer_label=True)

    # 2. Questions + their tappable options.
    for node in nodes:
        if node.type != "ask_question":
            continue
        config = node.config or {}
        key = config.get("variable_name") or config.get("variableName")
        question = (config.get("question") or "").strip()
        # A short question makes a fine header ("Clinic", "Able to Visit"); a full
        # sentence or a bilingual prompt does not — those fall back to the variable name.
        first = question.splitlines()[0].strip() if question else ""
        label = first if first and len(first) <= 32 and first.isascii() else None
        options = [o.get("label") for o in (config.get("options") or [])
                   if isinstance(o, dict) and o.get("label")]
        list_config = config.get("list_config") or config.get("listConfig") or {}
        for section in list_config.get("sections") or []:
            options += [r.get("label") for r in (section.get("rows") or [])
                        if isinstance(r, dict) and r.get("label")]
        put(key, label=label, type_="enum" if options else "text", options=options)

    # 3. AI-collected fields.
    for node in nodes:
        if node.type != "ai_conversation":
            continue
        for spec in (node.config or {}).get("fields") or []:
            if not isinstance(spec, dict):
                continue
            kind = {"enum": "enum", "media": "media", "date": "date"}.get(spec.get("type") or "text", "text")
            # The description is written for the AI ("the area or type of pain the
            # patient has"), not for a column header: label from the variable name
            # (put() title-cases it) and keep the description as a hint.
            put(spec.get("name"), type_=kind, options=spec.get("options") or [])
            hint = (spec.get("description") or "").strip()
            if hint and spec.get("name") in fields and "hint" not in fields[spec["name"]]:
                fields[spec["name"]]["hint"] = hint[:160]

    put("lead_id", label="Lead ID")
    put("report", label="Report", type_="media")
    return {"workflow_id": workflow.id, "fields": [fields[k] for k in order]}


# Message-metadata keys the inbox UI actually renders. Everything else
# (status_history, meta_response, capture/debug flags, ...) is stripped from the
# message payloads sent to the browser — status_history alone is ~half the bytes
# and the UI only shows the final tick from the top-level `status` field.
_INBOX_METADATA_KEYS = {
    "media",
    "sent_by",
    "reply_title",
    "reply_to_wamid",
    "meta_message_id",
    "options",
    "list_config",
    "template",
}


def _slim_interactive_option(option: dict[str, Any]) -> dict[str, Any]:
    """An interactive button/list row as the UI needs it — label/description and
    the WhatsApp option id (used as a render key). Drops next_node_id, which
    would leak the internal workflow graph."""
    if not isinstance(option, dict):
        return option
    return {k: option[k] for k in ("id", "label", "description") if k in option}


def slim_inbox_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only the metadata the inbox renders; drop debug/audit fields and the
    internal workflow-routing ids inside interactive configs."""
    if not metadata:
        return {}
    out = {k: v for k, v in metadata.items() if k in _INBOX_METADATA_KEYS}

    if isinstance(out.get("options"), list):
        out["options"] = [_slim_interactive_option(o) for o in out["options"]]

    lc = out.get("list_config")
    if isinstance(lc, dict):
        sections = []
        for section in lc.get("sections", []) or []:
            sections.append({
                "title": section.get("title"),
                "rows": [_slim_interactive_option(r) for r in section.get("rows", []) or []],
            })
        out["list_config"] = {"button_text": lc.get("button_text"), "sections": sections}

    return out


# Top-level message fields the inbox renders (everything else — internal engine
# ids like workflow_id/workflow_run_id/node_run_id/client_id — is dropped).
_INBOX_MESSAGE_FIELDS = (
    "id",
    "whatsapp_account_id",
    "contact_phone",
    "direction",
    "message_type",
    "text",
    "status",
    "created_at",
)

# Conversation fields the inbox never uses / must not leak.
_INBOX_CONVERSATION_DROP = {
    "client_id",
    "updated_at",
    # attributes stay dropped: old documents may still carry leaked sheet ids /
    # bucket paths. tags are returned (the CRM edits them); the inbox ignores them.
    "attributes",
    "active_workflow_run_id",
}


def to_inbox_message(message: MessageRecord) -> dict[str, Any]:
    """A message trimmed to just what the inbox renders (JSON-ready)."""
    data = message.model_dump(mode="json")
    out = {field: data.get(field) for field in _INBOX_MESSAGE_FIELDS}
    out["metadata"] = slim_inbox_metadata(message.metadata)
    return out


def to_inbox_conversation(conversation: Conversation) -> dict[str, Any]:
    """A conversation trimmed for the inbox: drops internal id + the
    attributes/tags blobs (which are no longer recorded and previously leaked
    Sheet ids / bucket paths)."""
    data = conversation.model_dump(mode="json")
    out = {k: v for k, v in data.items() if k not in _INBOX_CONVERSATION_DROP}
    # CRM-owned lead fields (call_tried / remark / custom columns) live under
    # attributes.crm; expose just that slice. Additive - the inbox ignores it.
    out["crm"] = (data.get("attributes") or {}).get("crm") or {}
    return out


# Dedicated pool for Mongo change-stream polling. Sharing asyncio's default
# executor with FastAPI sync routes meant a handful of SSE clients could
# exhaust the pool and freeze /health + every other request.
_SSE_EXECUTOR = None


def _sse_executor():
    global _SSE_EXECUTOR
    if _SSE_EXECUTOR is None:
        from concurrent.futures import ThreadPoolExecutor

        _SSE_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="bot-sse")
    return _SSE_EXECUTOR


async def stream_client_events(client_id: str, request):
    """Server-Sent Events stream for one client's inbox. Watches a MongoDB
    change stream on the conversations + messages collections (scoped to this
    client) and pushes each change to the browser, so the inbox no longer polls.

    Any Cloud Run instance's webhook writes to Mongo; every instance's change
    stream sees it, so this works regardless of which instance served the
    webhook. Emits:
      event: conversation  data: <Conversation JSON>   (list upsert)
      event: message       data: <MessageRecord JSON>  (append / status update)
    plus a ': ping' heartbeat, and stops when the client disconnects."""
    pipeline = [
        {
            "$match": {
                "operationType": {"$in": ["insert", "update", "replace"]},
                "ns.coll": {"$in": ["conversations", "messages", "notes", "calls", "call_reviews"]},
                "fullDocument.client_id": client_id,
            }
        }
    ]
    loop = asyncio.get_running_loop()
    try:
        stream = await loop.run_in_executor(
            _sse_executor(),
            lambda: db.watch(
                pipeline, full_document="updateLookup", max_await_time_ms=2000
            ),
        )
    except Exception as error:  # noqa: BLE001 — tell the client, don't kill the worker
        yield f"event: error\ndata: {json.dumps({'detail': f'change stream unavailable: {error}'})}\n\n"
        return

    try:
        # Prime the connection immediately so the browser sees it open.
        yield ": connected\n\n"
        last_ping = time.monotonic()
        while True:
            if await request.is_disconnected():
                break

            try:
                # try_next can return None immediately when the cursor is dead or
                # idle; never spin the event loop / thread pool on that path.
                change = await loop.run_in_executor(_sse_executor(), stream.try_next)
            except Exception as error:  # noqa: BLE001
                print(f"SSE change stream error ({client_id}): {error}", flush=True)
                break

            if change is None:
                now = time.monotonic()
                if now - last_ping >= 20:
                    last_ping = now
                    yield ": ping\n\n"
                # Pace empty polls — without this, a dead/empty try_next busy-loops
                # and starves the API (symptom: /health hangs, 40%+ CPU).
                await asyncio.sleep(0.5)
                continue

            doc = change.get("fullDocument")
            if not doc:
                continue

            coll = change["ns"]["coll"]
            if coll == "conversations":
                data = json.dumps(to_inbox_conversation(parse_model(Conversation, doc)))
                yield f"event: conversation\ndata: {data}\n\n"
            elif coll == "messages":
                data = json.dumps(to_inbox_message(parse_model(MessageRecord, doc)))
                yield f"event: message\ndata: {data}\n\n"
            elif coll == "notes":
                # CRM agent notes. The Ripply inbox only listens for
                # "conversation"/"message" events, so it ignores this one.
                note = parse_model(Note, doc)
                if note:
                    yield f"event: note\ndata: {json.dumps(note.model_dump(mode='json'))}\n\n"
            elif coll == "calls":
                # FasterQ call landed / recording ready. CRM-only event.
                call = parse_model(CallRecord, doc)
                if call:
                    name = None
                    if call.conversation_id:
                        cid = call.conversation_id
                        conv_doc = await loop.run_in_executor(
                            _sse_executor(),
                            lambda conv_id=cid: db["conversations"].find_one(
                                {"id": conv_id}, {"contact_name": 1}
                            ),
                        )
                        name = (conv_doc or {}).get("contact_name")
                    yield f"event: call\ndata: {json.dumps(to_call_json(call, name))}\n\n"
            elif coll == "call_reviews":
                # AI call review queued / finished. CRM-only event; carries no
                # transcript (those live in their own collection, off this stream).
                review = parse_model(CallReview, doc)
                if review:
                    yield f"event: call_review\ndata: {json.dumps(review.model_dump(mode='json'))}\n\n"
    finally:
        try:
            await loop.run_in_executor(_sse_executor(), stream.close)
        except Exception:  # noqa: BLE001
            pass


def cancel_conversation_run(conversation_id: str, client_id: str):
    """Stops the chat's live workflow run without resolving the chat or
    pausing the bot. The customer's next message starts the flow fresh."""
    conversation = get_owned_conversation(conversation_id, client_id)

    cancelled_run_id = cancel_active_run_for_conversation(conversation)
    set_conversation_active_run(conversation.id, None)

    return {
        "conversation_id": conversation.id,
        "status": conversation.status,
        "bot_paused": conversation.bot_paused,
        "cancelled_workflow_run_id": cancelled_run_id,
    }


def get_inbox_conversations(
    client_id: str,
    status: str | None = None,
    whatsapp_account_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    view: str | None = None,
):
    if status and status not in ["open", "resolved", "expired"]:
        raise HTTPException(
            status_code=400,
            detail="status must be 'open', 'resolved', or 'expired'.",
        )

    if view and view not in CONVERSATION_VIEWS:
        raise HTTPException(
            status_code=400,
            detail="view must be 'inbox' or 'template'.",
        )

    # Materialize the 24h window for this client before listing, so lapsed
    # conversations show as 'expired' (and their agent handoff is cleared).
    expire_stale_conversations(
        now_utc() - WHATSAPP_SESSION_WINDOW,
        client_id=client_id,
    )

    total, conversations = list_conversations(
        client_id=client_id,
        status=status,
        whatsapp_account_id=whatsapp_account_id,
        limit=limit,
        offset=offset,
        view=view,
    )
    return total, [to_inbox_conversation(c) for c in conversations], count_conversation_views(client_id)


def get_owned_conversation(conversation_id: str, client_id: str):
    conversation = get_conversation_by_id(conversation_id)
    return assert_owned(conversation, client_id, "Conversation")


def get_conversation_messages(
    conversation_id: str,
    client_id: str,
    limit: int = 30,
    before: str | None = None,
):
    """Paginated message history for a chat, oldest->newest. Returns the most
    recent `limit` messages (or the page just older than `before`, an ISO
    timestamp cursor), plus `has_more` so the inbox can lazy-load older pages on
    scroll-up instead of pulling the whole history at once."""
    # Opening a chat directly also materializes its window state.
    expire_stale_conversations(
        now_utc() - WHATSAPP_SESSION_WINDOW,
        conversation_id=conversation_id,
    )
    conversation = get_owned_conversation(conversation_id, client_id)

    cursor = datetime.fromisoformat(before) if before else None

    # Fetch one extra to detect whether older messages remain.
    messages = get_messages_for_contact(
        whatsapp_account_id=conversation.whatsapp_account_id,
        contact_phone=conversation.contact_phone,
        limit=limit + 1,
        before=cursor,
    )
    has_more = len(messages) > limit
    if has_more:
        messages = messages[1:]  # drop the oldest extra (list is ascending)

    return {
        "conversation": to_inbox_conversation(conversation),
        "messages": [to_inbox_message(m) for m in messages],
        "has_more": has_more,
    }


def mark_conversation_viewed(conversation_id: str, client_id: str):
    conversation = get_owned_conversation(conversation_id, client_id)

    reset_conversation_unread(conversation.id)

    return {
        "conversation_id": conversation.id,
        "unread_count": 0,
    }


def update_contact(conversation_id: str, client_id: str, request: UpdateContactRequest):
    conversation = get_owned_conversation(conversation_id, client_id)

    update_conversation_contact_fields(
        conversation_id=conversation.id,
        contact_name=request.contact_name,
        attributes=request.attributes,
        tags=request.tags,
    )

    return {
        "conversation": to_inbox_conversation(get_conversation_by_id(conversation.id)),
    }


def send_agent_message(conversation_id: str, client_id: str, text: str):
    """Manual reply from the inbox composer. Sends real WhatsApp text and
    records it like any other outgoing message (with tick tracking), but
    outside any workflow run."""
    if not text or not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Message text is required.",
        )

    conversation = get_owned_conversation(conversation_id, client_id)

    account = get_whatsapp_account_by_id(conversation.whatsapp_account_id)

    if not account:
        raise HTTPException(
            status_code=404,
            detail="WhatsApp account not found for this conversation.",
        )

    if not is_within_service_window(conversation):
        raise HTTPException(
            status_code=403,
            detail="The 24-hour messaging window has closed. The customer must send a new message before you can reply.",
        )

    message = MessageRecord(
        id=make_message_id(),
        client_id=conversation.client_id,
        whatsapp_account_id=conversation.whatsapp_account_id,
        contact_phone=conversation.contact_phone,
        direction="outgoing",
        message_type="text",
        text=text,
        metadata={"sent_by": "agent"},
        status="created",
    )
    save_message(message)

    try:
        meta_response = send_whatsapp_text_message(
            phone_number_id=account.phone_number_id,
            to_phone=conversation.contact_phone,
            text=text,
            access_token=account.access_token,
        )
        record_send_result(message, meta_response=meta_response)

    except HTTPException as error:
        record_send_result(message, error_detail=error.detail)

    upsert_conversation_on_message(
        client_id=conversation.client_id,
        whatsapp_account_id=conversation.whatsapp_account_id,
        contact_phone=conversation.contact_phone,
        text=text,
        direction="outgoing",
    )

    # A human stepped in: pause the bot for this chat until it is
    # closed/resolved, and cancel any workflow run waiting for an answer.
    cancelled_run_id = None
    if not conversation.bot_paused:
        cancelled_run_id = cancel_active_run_for_conversation(conversation)
        set_conversation_bot_paused(conversation.id, True)
        set_conversation_active_run(conversation.id, None)

    return {
        "message_id": message.id,
        "status": message.status,
        "send_error": message.metadata.get("send_error"),
        "bot_paused": True,
        "cancelled_workflow_run_id": cancelled_run_id,
    }


def send_agent_audio_message(conversation_id: str, client_id: str, audio_bytes: bytes):
    """Manual voice reply from the inbox. Transcodes the browser recording to MP3, stores it in
    GCS (for the inbox player), and sends it to WhatsApp as an audio message. Mirrors
    send_agent_message - same ownership check, 24-hour window gate, tick tracking, and
    bot-pause-on-human-reply. (WhatsApp's Cloud API rejects OGG/Opus voice notes with 131053, so
    the recording is delivered as a playable MP3 audio message rather than a native voice note.)"""
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload.")

    conversation = get_owned_conversation(conversation_id, client_id)

    account = get_whatsapp_account_by_id(conversation.whatsapp_account_id)
    if not account:
        raise HTTPException(
            status_code=404,
            detail="WhatsApp account not found for this conversation.",
        )

    if not is_within_service_window(conversation):
        raise HTTPException(
            status_code=403,
            detail="The 24-hour messaging window has closed. The customer must send a new message before you can reply.",
        )

    try:
        mp3_bytes = audio_service.to_mp3(audio_bytes)
    except audio_service.AudioTranscodeError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not process the recording: {error}",
        )

    try:
        gcs_uri = gcs_service.upload_bytes(mp3_bytes, "audio/mpeg", ".mp3")
    except (HTTPException, RuntimeError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"Could not store the recording: {getattr(error, 'detail', str(error))}",
        )

    message = MessageRecord(
        id=make_message_id(),
        client_id=conversation.client_id,
        whatsapp_account_id=conversation.whatsapp_account_id,
        contact_phone=conversation.contact_phone,
        direction="outgoing",
        message_type="audio",
        text=None,
        metadata={
            "sent_by": "agent",
            "reply_title": "🎤 Voice message",
            "media": {
                "type": "audio",
                "mime_type": "audio/mpeg",
                "gcs_uri": gcs_uri,
                "voice": True,
            },
        },
        status="created",
    )
    save_message(message)

    try:
        # Upload to Meta and send by media id - sending audio by link makes Meta
        # re-fetch and re-process the file, which is unreliable.
        media_id = upload_whatsapp_media(
            phone_number_id=account.phone_number_id,
            data=mp3_bytes,
            mime_type="audio/mpeg",
            filename="voice.mp3",
            access_token=account.access_token,
        )
        meta_response = send_whatsapp_media_message(
            phone_number_id=account.phone_number_id,
            to_phone=conversation.contact_phone,
            media_type="audio",
            media_id=media_id,
            access_token=account.access_token,
        )
        record_send_result(message, meta_response=meta_response)
    except HTTPException as error:
        record_send_result(message, error_detail=error.detail)

    upsert_conversation_on_message(
        client_id=conversation.client_id,
        whatsapp_account_id=conversation.whatsapp_account_id,
        contact_phone=conversation.contact_phone,
        text="🎤 Voice message",
        direction="outgoing",
    )

    cancelled_run_id = None
    if not conversation.bot_paused:
        cancelled_run_id = cancel_active_run_for_conversation(conversation)
        set_conversation_bot_paused(conversation.id, True)
        set_conversation_active_run(conversation.id, None)

    return {
        "message_id": message.id,
        "status": message.status,
        "send_error": message.metadata.get("send_error"),
        "bot_paused": True,
        "cancelled_workflow_run_id": cancelled_run_id,
    }


def retry_failed_crm_pushes() -> None:
    """Ask each crm_push client's relay to re-push its 'service unavailable'
    failures. The relay's /retry-failed re-pushes ONLY leads that never inserted
    (503), skips read-timeouts (the CRM doesn't dedupe on Lead_ID) and
    already-pushed leads - so this is safe + idempotent. One client's error never
    stops the others, nor the heartbeat."""
    try:
        _, clients = list_clients(status="active", limit=200, offset=0)
    except Exception as error:  # noqa: BLE001
        print(f"CRM RETRY: could not list clients: {error}", flush=True)
        return
    for client in clients:
        cp = getattr(client, "crm_push", None)
        if not cp or not getattr(cp, "enabled", False) or not getattr(cp, "url", None):
            continue
        if "/crm-lead-push" not in cp.url:
            continue
        retry_url = cp.url.replace("/crm-lead-push", "/retry-failed")
        auth_key = (getattr(cp, "static_fields", None) or {}).get("AuthKey")
        try:
            response = requests.post(
                retry_url, json={"AuthKey": auth_key, "limit": 200}, timeout=90)
            print(f"CRM RETRY {client.id}: {response.status_code} {response.text[:200]}", flush=True)
        except Exception as error:  # noqa: BLE001
            print(f"CRM RETRY FAILED for {client.id}: {type(error).__name__}: {error}", flush=True)


def expire_inactive_runs():
    """Sweep for workflow runs stuck waiting for a customer answer past their
    account's inactivity timeout: close the run, tell the customer, and unlink
    the conversation so the next inbound message restarts the flow. Called on a
    ~60s loop from the app lifespan. Safe to run concurrently across instances -
    claim_run_for_timeout guarantees each run is closed (and messaged) once."""
    now = now_utc()

    for account in list_accounts_with_inactivity_enabled():
        cutoff = now - timedelta(minutes=account.inactivity_timeout_minutes)

        for run in find_waiting_runs_older_than(account.id, cutoff):
            try:
                conversation = get_conversation_for_contact(
                    whatsapp_account_id=account.id,
                    contact_phone=run.contact_phone,
                )

                # A human agent took over - the timeout is a bot feature, so
                # leave the chat to the agent and don't touch the run.
                if conversation and conversation.bot_paused:
                    continue

                # Atomic guard: only the instance that wins this flip proceeds to
                # message the customer, so no double sends across instances.
                if not claim_run_for_timeout(run.id):
                    continue

                # The claim changed the ROW; mirror it onto the object we hold so
                # nothing downstream in this loop acts on (or writes back) a
                # status that is no longer true.
                run.status = "cancelled"
                run.completed_at = now_utc()

                if conversation:
                    set_conversation_active_run(conversation.id, None)

                message = MessageRecord(
                    id=make_message_id(),
                    client_id=account.client_id,
                    whatsapp_account_id=account.id,
                    contact_phone=run.contact_phone,
                    direction="outgoing",
                    message_type="text",
                    text=account.inactivity_timeout_message,
                    metadata={"sent_by": "inactivity_timeout"},
                    status="created",
                )
                save_message(message)

                try:
                    meta_response = send_whatsapp_text_message(
                        phone_number_id=account.phone_number_id,
                        to_phone=run.contact_phone,
                        text=account.inactivity_timeout_message,
                        access_token=account.access_token,
                    )
                    record_send_result(message, meta_response=meta_response)
                except HTTPException as error:
                    record_send_result(message, error_detail=error.detail)

                upsert_conversation_on_message(
                    client_id=account.client_id,
                    whatsapp_account_id=account.id,
                    contact_phone=run.contact_phone,
                    text=account.inactivity_timeout_message,
                    direction="outgoing",
                )

                # A timed-out chat is still a lead - usually the majority of
                # them - so push whatever was collected before they went quiet.
                push_lead_to_crm(run, reason="timeout")
            except Exception as error:
                print(f"INACTIVITY TIMEOUT FAILED for run {run.id}: {error}")


# =====================================================================
# Platform CRUD: clients, users, WhatsApp accounts
# =====================================================================

def redact_token(token: str | None) -> str | None:
    if not token:
        return None
    return f"••••{token[-4:]}"


def redact_account(account: WhatsAppAccount) -> dict[str, Any]:
    """Accounts leave the API only through this - tokens never do."""
    data = account.model_dump(mode="json")
    data["access_token"] = redact_token(account.access_token)
    data["webhook_verify_token"] = redact_token(account.webhook_verify_token)
    return data


def redact_client(client: Client) -> dict[str, Any]:
    data = client.model_dump(mode="json")
    data["password"] = None
    data["long_live_token"] = redact_token(client.long_live_token)
    # static_fields carries the CRM's auth key - same class of secret as the
    # password and the long-lived token, so it never leaves through the API.
    if isinstance(data.get("crm_push"), dict):
        data["crm_push"]["static_fields"] = {
            key: "***" for key in (data["crm_push"].get("static_fields") or {})
        }
    # The disposition sync holds a full Mongo connection string, credentials
    # included - the most sensitive value on the client document.
    if isinstance(data.get("disposition_sync"), dict):
        if data["disposition_sync"].get("mongo_uri"):
            data["disposition_sync"]["mongo_uri"] = "***"
    return data


def assert_client_id_matches_path(path_client_id: str, token_client_id: str):
    if path_client_id != token_client_id:
        raise HTTPException(status_code=404, detail="Client not found.")


def login_client(request: LoginRequest):
    client = get_client_by_username(request.username)

    if not client or client.password != request.password:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if client.status != "active":
        raise HTTPException(status_code=403, detail="Client is inactive.")

    expires_at = now_utc() + session_token_delta()
    token = create_client_token(
        client_id=client.id,
        token_type="session",
        expires_at=expires_at,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "client": {
            "id": client.id,
            "name": client.name,
            "username": client.username,
            "status": client.status,
        },
    }


def get_auth_client(client_id: str):
    return redact_client(get_client_or_404(client_id))


def get_owned_whatsapp_account_by_phone_number_id(
    phone_number_id: str,
    client_id: str,
) -> WhatsAppAccount:
    account = get_whatsapp_account_by_phone_number_id(phone_number_id)
    return assert_owned(account, client_id, "WhatsApp account")


def get_or_create_long_live_token(client_id: str):
    # Rotate-on-demand: every call mints a fresh long-lived token and overwrites
    # the stored one, which immediately invalidates the previous token (auth
    # compares the presented token to client.long_live_token).
    client = get_client_or_404(client_id)

    expires_at = now_utc() + long_live_token_delta()
    token = create_client_token(
        client_id=client.id,
        token_type="long_live",
        expires_at=expires_at,
    )
    client.long_live_token = token
    client.long_live_token_expires_at = expires_at
    save_client(client)

    return {
        "client_id": client.id,
        "long_live_token": token,
        "expires_at": expires_at,
        "created": True,
    }


def create_client(request: CreateClientRequest):
    if get_client_by_username(request.username):
        raise HTTPException(
            status_code=409,
            detail="A client with this username already exists.",
        )

    client = Client(
        id=f"client:{short_id()}",
        name=request.name,
        username=request.username,
        password=request.password,
    )
    save_client(client)
    return redact_client(get_client_by_id(client.id))


def get_client_or_404(client_id: str) -> Client:
    client = get_client_by_id(client_id)

    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")

    return client


def list_clients_service(status: str | None, limit: int, offset: int):
    total, clients = list_clients(status=status, limit=limit, offset=offset)
    return total, [redact_client(client) for client in clients]


def update_client(client_id: str, request: UpdateClientRequest):
    client = get_client_or_404(client_id)

    if request.name is not None:
        client.name = request.name

    if request.username is not None and request.username != client.username:
        existing = get_client_by_username(request.username)
        if existing and existing.id != client.id:
            raise HTTPException(
                status_code=409,
                detail="A client with this username already exists.",
            )
        client.username = request.username

    if request.password is not None:
        client.password = request.password

    if request.status is not None:
        client.status = request.status

    if request.crm_columns is not None:
        client.crm_columns = request.crm_columns

    if request.feature_prefs is not None:
        unknown = sorted(set(request.feature_prefs) - CRM_FEATURE_KEYS)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown feature keys: {', '.join(unknown)}. "
                       f"Valid: {', '.join(sorted(CRM_FEATURE_KEYS))}",
            )
        client.feature_prefs = {**(client.feature_prefs or {}), **request.feature_prefs}

    if request.crm_view is not None:
        bad = sorted(set(request.crm_view) - {"desktop", "phone"})
        if bad:
            raise HTTPException(status_code=422, detail=f"Unknown crm_view keys: {', '.join(bad)}. Valid: desktop, phone")
        client.crm_view = {**(client.crm_view or {}), **{k: [str(x) for x in v] for k, v in request.crm_view.items()}}

    if request.call_recording is not None:
        names = []
        for raw in request.call_recording.agent_names:
            name = str(raw).strip()
            if name and name.lower() not in [x.lower() for x in names]:
                names.append(name)
        client.call_recording = CallRecordingConfig(agent_names=names)

    save_client(client)
    if request.call_recording is not None:
        # Calls that arrived before the clinic told us its agent names.
        try:
            reattach_unassigned_calls_for_client(client)
        except Exception as error:
            print(f"CALL REATTACH ERROR ({client.id}): {error}")
    return redact_client(get_client_by_id(client.id))


def deactivate_client(client_id: str):
    """Soft delete: conversations, runs and messages keep referencing the
    client, so the record is never removed - it just stops working."""
    client = get_client_or_404(client_id)
    client.status = "inactive"
    save_client(client)

    return {"client_id": client.id, "status": "inactive"}


def create_user(client_id: str, request: CreateUserRequest):
    get_client_or_404(client_id)

    user = User(
        id=f"user:{short_id()}",
        client_id=client_id,
        name=request.name,
        email=request.email,
        role=request.role,
    )
    save_user(user)
    return get_user_by_id(user.id)


def get_user_or_404(user_id: str) -> User:
    user = get_user_by_id(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return user


def list_client_users(client_id: str):
    get_client_or_404(client_id)
    users = list_users_for_client(client_id)
    return {"total": len(users), "users": users}


def update_user(user_id: str, request: UpdateUserRequest, client_id: str | None = None):
    user = get_user_or_404(user_id)
    if client_id is not None:
        assert_owned(user, client_id, "User")

    if request.name is not None:
        user.name = request.name

    if request.email is not None:
        user.email = request.email

    if request.role is not None:
        user.role = request.role

    if request.status is not None:
        user.status = request.status

    save_user(user)
    return get_user_by_id(user.id)


def create_whatsapp_account(client_id: str, request: CreateWhatsAppAccountRequest):
    get_client_or_404(client_id)

    # phone_number_id is the webhook routing key - it must be globally
    # unique or two clients would receive each other's messages.
    existing = get_whatsapp_account_by_phone_number_id(request.phone_number_id)

    if existing:
        raise HTTPException(
            status_code=409,
            detail="A WhatsApp account with this phone_number_id already exists.",
        )

    account = WhatsAppAccount(
        id=f"wa:{short_id()}",
        client_id=client_id,
        name=request.name,
        phone_number_id=request.phone_number_id,
        display_phone_number=request.display_phone_number,
        whatsapp_business_account_id=request.whatsapp_business_account_id,
        access_token=request.access_token,
        webhook_verify_token=request.webhook_verify_token,
    )
    save_whatsapp_account(account)
    return redact_account(get_whatsapp_account_by_id(account.id))


def get_whatsapp_account_or_404(account_id: str) -> WhatsAppAccount:
    account = get_whatsapp_account_by_id(account_id)

    if not account:
        raise HTTPException(status_code=404, detail="WhatsApp account not found.")

    return account


def list_client_whatsapp_accounts(client_id: str):
    get_client_or_404(client_id)
    accounts = list_whatsapp_accounts_for_client(client_id)
    for account in accounts:
        _fill_account_metadata(account)
    return {
        "total": len(accounts),
        "whatsapp_accounts": [redact_account(account) for account in accounts],
    }


def _fill_account_metadata(account: WhatsAppAccount) -> None:
    """Accounts created by hand (not embedded signup) have no verified name /
    display phone. Fetch them from Meta once and keep them; never fail the
    request over it."""
    if account.verified_name and account.display_phone_number:
        return
    if not account.phone_number_id or not account.access_token:
        return
    try:
        meta = meta_onboarding_service.get_phone_number_metadata(
            account.phone_number_id, account.access_token
        )
    except Exception:
        return
    changed = False
    if not account.verified_name and meta.get("verified_name"):
        account.verified_name = meta["verified_name"]; changed = True
    if not account.display_phone_number and meta.get("display_phone_number"):
        account.display_phone_number = meta["display_phone_number"]; changed = True
    if changed:
        save_whatsapp_account(account)


def get_whatsapp_account_detail(account_id: str, client_id: str | None = None):
    account = get_whatsapp_account_or_404(account_id)
    if client_id is not None:
        assert_owned(account, client_id, "WhatsApp account")
    return redact_account(account)


def update_whatsapp_account(
    account_id: str,
    request: UpdateWhatsAppAccountRequest,
    client_id: str | None = None,
):
    account = get_whatsapp_account_or_404(account_id)
    if client_id is not None:
        assert_owned(account, client_id, "WhatsApp account")

    if (
        request.phone_number_id is not None
        and request.phone_number_id != account.phone_number_id
    ):
        existing = get_whatsapp_account_by_phone_number_id(request.phone_number_id)

        if existing and existing.id != account.id:
            raise HTTPException(
                status_code=409,
                detail="A WhatsApp account with this phone_number_id already exists.",
            )

        account.phone_number_id = request.phone_number_id

    if request.name is not None:
        account.name = request.name

    if request.display_phone_number is not None:
        account.display_phone_number = request.display_phone_number

    if request.whatsapp_business_account_id is not None:
        account.whatsapp_business_account_id = request.whatsapp_business_account_id

    if request.access_token is not None:
        account.access_token = request.access_token

    if request.webhook_verify_token is not None:
        account.webhook_verify_token = request.webhook_verify_token

    if request.status is not None:
        account.status = request.status

    if request.inactivity_timeout_enabled is not None:
        account.inactivity_timeout_enabled = request.inactivity_timeout_enabled

    if request.inactivity_timeout_minutes is not None:
        account.inactivity_timeout_minutes = request.inactivity_timeout_minutes

    if request.inactivity_timeout_message is not None:
        account.inactivity_timeout_message = request.inactivity_timeout_message

    save_whatsapp_account(account)
    return redact_account(get_whatsapp_account_by_id(account.id))


def disconnect_whatsapp_account(account_id: str, client_id: str | None = None):
    """Soft delete: the webhook starts ignoring this phone_number_id, but
    all history stays."""
    account = get_whatsapp_account_or_404(account_id)
    if client_id is not None:
        assert_owned(account, client_id, "WhatsApp account")
    account.status = "disconnected"
    save_whatsapp_account(account)

    return {"whatsapp_account_id": account.id, "status": "disconnected"}


def verify_whatsapp_account(account_id: str, client_id: str | None = None):
    account = get_whatsapp_account_or_404(account_id)
    if client_id is not None:
        assert_owned(account, client_id, "WhatsApp account")

    result = check_whatsapp_credentials(
        access_token=account.access_token,
        phone_number_id=account.phone_number_id,
    )

    return {
        "whatsapp_account_id": account.id,
        "using_env_fallback_token": account.access_token is None,
        **result,
    }


def subscribe_whatsapp_account_webhook(account_id: str, client_id: str | None = None):
    account = get_whatsapp_account_or_404(account_id)
    if client_id is not None:
        assert_owned(account, client_id, "WhatsApp account")

    if not account.whatsapp_business_account_id:
        raise HTTPException(
            status_code=400,
            detail="Account has no whatsapp_business_account_id set.",
        )

    result = subscribe_whatsapp_business_account(
        whatsapp_business_account_id=account.whatsapp_business_account_id,
        access_token=account.access_token,
    )

    return {"whatsapp_account_id": account.id, "meta_response": result}


# =====================================================================
# Workflow + node CRUD
# =====================================================================

NODE_REFERENCE_KEYS = {
    "next_node_id",
    "nextNodeId",
    "default_next_node_id",
    "defaultNextNodeId",
}


def remap_node_references(value, id_map: dict[str, str]):
    """Walks a raw node config and rewrites every next-node reference
    through id_map, so clients can use short local ids everywhere."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in NODE_REFERENCE_KEYS and isinstance(item, str):
                result[key] = id_map.get(item, item)
            else:
                result[key] = remap_node_references(item, id_map)
        return result

    if isinstance(value, list):
        return [remap_node_references(item, id_map) for item in value]

    return value


def node_local_id(full_node_id: str) -> str:
    return full_node_id.split("/")[-1].removeprefix("node:")


# =====================================================================
# Edge abstraction — every outgoing connection as a uniform (handle,
# target) pair, regardless of whether it lives on node.next_node_id or
# buried inside config (button options, list rows, condition rules).
# This is the single choke point for all connection edits.
# =====================================================================

def get_node_edges(node: WorkflowNode) -> list[dict[str, Any]]:
    """Reads every outgoing connection of a node as {handle, target}.

    Handles:
      default            -> node.next_node_id, OR for a buttons/list question,
                            config.default_next_node_id (the free-text fallback)
      button:<option_id> -> that button option's next_node_id
      list:<row_id>      -> that list row's next_node_id
      condition:<index>  -> that condition rule's next_node_id
      condition:default  -> config.default_next_node_id
    """
    edges: list[dict[str, Any]] = []
    config = node.config or {}

    if node.type == "ask_question":
        input_type = config.get("input_type") or config.get("inputType")

        if input_type == "buttons":
            for option in config.get("options") or []:
                edges.append({
                    "handle": f"button:{option.get('id')}",
                    "target": option.get("next_node_id") or option.get("nextNodeId"),
                })
            # Free-text fallback. None target = re-prompt/circle back on this node.
            edges.append({
                "handle": "default",
                "target": config.get("default_next_node_id") or config.get("defaultNextNodeId"),
            })
            return edges

        if input_type == "list":
            list_config = config.get("list_config") or config.get("listConfig") or {}
            for section in list_config.get("sections") or []:
                for row in section.get("rows") or []:
                    edges.append({
                        "handle": f"list:{row.get('id')}",
                        "target": row.get("next_node_id") or row.get("nextNodeId"),
                    })
            edges.append({
                "handle": "default",
                "target": config.get("default_next_node_id") or config.get("defaultNextNodeId"),
            })
            return edges

        # text question -> single default edge
        edges.append({"handle": "default", "target": node.next_node_id})
        return edges

    if node.type == "condition":
        for index, rule in enumerate(config.get("conditions") or []):
            edges.append({
                "handle": f"condition:{index}",
                "target": rule.get("next_node_id") or rule.get("nextNodeId"),
            })
        edges.append({
            "handle": "condition:default",
            "target": config.get("default_next_node_id") or config.get("defaultNextNodeId"),
        })
        return edges

    if node.type == "ai_conversation":
        # Hand-back target: config override wins, else the linear next.
        edges.append({
            "handle": "default",
            "target": config.get("next_node_id") or config.get("nextNodeId") or node.next_node_id,
        })
        return edges

    # send_message and everything else: one linear edge
    edges.append({"handle": "default", "target": node.next_node_id})
    return edges


def set_node_edge(node: WorkflowNode, handle: str, target: str | None):
    """Writes `target` into the physical place named by `handle`
    (or clears it with None). Raises 400 for a handle that doesn't
    exist on this node."""
    config = node.config or {}

    if handle == "default":
        # For a buttons/list question the "default" handle is the free-text
        # fallback stored in config; everywhere else it's the linear next.
        input_type = config.get("input_type") or config.get("inputType")
        if node.type == "ask_question" and input_type in ("buttons", "list"):
            config["default_next_node_id"] = target
            node.config = config
        else:
            node.next_node_id = target
        return

    if handle == "condition:default":
        config["default_next_node_id"] = target
        node.config = config
        return

    kind, _, ref = handle.partition(":")

    if kind == "button":
        for option in config.get("options") or []:
            if str(option.get("id")) == ref:
                option["next_node_id"] = target
                option.pop("nextNodeId", None)
                node.config = config
                return

    elif kind == "list":
        list_config = config.get("list_config") or config.get("listConfig") or {}
        for section in list_config.get("sections") or []:
            for row in section.get("rows") or []:
                if str(row.get("id")) == ref:
                    row["next_node_id"] = target
                    row.pop("nextNodeId", None)
                    node.config = config
                    return

    elif kind == "condition":
        conditions = config.get("conditions") or []
        try:
            idx = int(ref)
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(conditions):
            conditions[idx]["next_node_id"] = target
            conditions[idx].pop("nextNodeId", None)
            node.config = config
            return

    raise HTTPException(
        status_code=400,
        detail=f"Node '{node_local_id(node.id)}' has no connection handle '{handle}'.",
    )


def find_referrers(nodes: list[WorkflowNode], target_id: str) -> list[tuple[WorkflowNode, str]]:
    """Every (node, handle) across the graph whose edge points at target_id."""
    referrers = []
    for node in nodes:
        for edge in get_node_edges(node):
            if edge["target"] == target_id:
                referrers.append((node, edge["handle"]))
    return referrers


def build_node_reference_map(nodes: list[WorkflowNode]) -> dict[str, str]:
    """Accepts references as full id, last segment ("node:1") or bare
    local ("1") - all resolve to the stored full id."""
    id_map = {}

    for node in nodes:
        last_segment = node.id.split("/")[-1]
        id_map[node.id] = node.id
        id_map[last_segment] = node.id
        id_map[last_segment.removeprefix("node:")] = node.id

    return id_map


def find_node_in_workflow(
    nodes: list[WorkflowNode],
    node_reference: str,
) -> WorkflowNode | None:
    for node in nodes:
        last_segment = node.id.split("/")[-1]

        if node_reference in (node.id, last_segment, last_segment.removeprefix("node:")):
            return node

    return None


def get_owned_workflow(workflow_id: str, client_id: str) -> Workflow:
    workflow = get_workflow_by_id(workflow_id)

    if workflow and workflow.deleted:
        workflow = None

    return assert_owned(workflow, client_id, "Workflow")


def build_nodes_from_inputs(
    client_id: str,
    workflow_id: str,
    created_by_user_id: str,
    node_inputs: list[WorkflowNodeInput],
):
    local_ids = [node_input.id for node_input in node_inputs]

    if len(local_ids) != len(set(local_ids)):
        raise HTTPException(status_code=400, detail="Duplicate node ids in request.")

    id_map = {}
    full_ids = []

    for local in local_ids:
        full = f"{workflow_id}/node:{local.removeprefix('node:')}"
        full_ids.append(full)
        id_map[local] = full
        id_map[local.removeprefix("node:")] = full

    if len(full_ids) != len(set(full_ids)):
        raise HTTPException(
            status_code=400,
            detail="Node ids collide after normalization (e.g. 'x' and 'node:x').",
        )

    nodes = []

    for node_input in node_inputs:
        nodes.append(
            WorkflowNode(
                id=id_map[node_input.id],
                client_id=client_id,
                workflow_id=workflow_id,
                created_by_user_id=created_by_user_id,
                updated_by_user_id=created_by_user_id,
                name=node_input.name,
                type=node_input.type,
                next_node_id=(
                    id_map.get(node_input.next_node_id, node_input.next_node_id)
                    if node_input.next_node_id
                    else None
                ),
                config=remap_node_references(node_input.config, id_map),
                position=node_input.position,
            )
        )

    return id_map, nodes


def raise_if_graph_errors(errors: list, message: str):
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": message, "errors": errors},
        )


def check_and_bump_version(workflow: Workflow, expected_version: int | None):
    """Optimistic concurrency: reject a stale edit, else bump the version.
    The caller still save_workflow()s to persist the bump."""
    if expected_version is not None and expected_version != workflow.version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Workflow was modified by someone else "
                f"(your version {expected_version}, current {workflow.version}). Reload and retry."
            ),
        )
    workflow.version = (workflow.version or 1) + 1


def create_workflow(client_id: str, request: CreateWorkflowRequest):
    account = get_whatsapp_account_by_id(request.whatsapp_account_id)
    assert_owned(account, client_id, "WhatsApp account")

    user = get_user_by_id(request.created_by_user_id)
    assert_owned(user, client_id, "User")

    if not request.nodes:
        raise HTTPException(status_code=400, detail="Workflow needs at least one node.")

    workflow_id = f"{client_id}/workflow:{short_id()}"

    id_map, nodes = build_nodes_from_inputs(
        client_id=client_id,
        workflow_id=workflow_id,
        created_by_user_id=user.id,
        node_inputs=request.nodes,
    )

    first_node_id = id_map.get(request.first_node_id)

    if not first_node_id:
        raise HTTPException(
            status_code=400,
            detail="first_node_id must be the id of one of the nodes.",
        )

    workflow = Workflow(
        id=workflow_id,
        client_id=client_id,
        whatsapp_account_id=account.id,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
        name=request.name,
        description=request.description,
        node_ids=[node.id for node in nodes],
        first_node_id=first_node_id,
        trigger_keywords=request.trigger_keywords,
        is_default=request.is_default,
        status="draft",
    )

    raise_if_graph_errors(
        validate_workflow_graph(workflow, nodes),
        "Invalid workflow graph.",
    )

    save_workflow(workflow)

    for node in nodes:
        save_workflow_node(node)

    return {
        "workflow": get_workflow_by_id(workflow.id),
        "nodes": get_workflow_nodes(workflow.id),
        "pending_google_auth": google_connections_needing_auth(nodes, client_id),
    }


def list_client_workflows(
    client_id: str,
    whatsapp_account_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
):
    get_client_or_404(client_id)

    return list_workflows_for_client(
        client_id=client_id,
        whatsapp_account_id=whatsapp_account_id,
        status=status,
        limit=limit,
        offset=offset,
    )


def get_workflow_detail(workflow_id: str, client_id: str):
    workflow = get_owned_workflow(workflow_id, client_id)

    return {
        "workflow": workflow,
        "nodes": get_workflow_nodes(workflow.id),
    }


def update_workflow(
    workflow_id: str,
    client_id: str,
    request: UpdateWorkflowRequest,
    expected_version: int | None = None,
):
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)
    check_and_bump_version(workflow, expected_version)

    if request.name is not None:
        workflow.name = request.name

    if request.description is not None:
        workflow.description = request.description

    if request.first_node_id is not None:
        target = find_node_in_workflow(nodes, request.first_node_id)

        if not target:
            raise HTTPException(
                status_code=400,
                detail="first_node_id does not match any node of this workflow.",
            )

        workflow.first_node_id = target.id

    if request.trigger_keywords is not None:
        workflow.trigger_keywords = request.trigger_keywords

    if request.is_default is not None:
        workflow.is_default = request.is_default

    errors = validate_workflow_graph(workflow, nodes)

    # Live routing rules only matter while the workflow is published.
    if workflow.status == "published":
        errors = errors + validate_publish_rules(workflow)

    raise_if_graph_errors(errors, "Update would leave the workflow invalid.")

    save_workflow(workflow)
    return {"workflow": get_workflow_by_id(workflow.id)}


def delete_workflow(workflow_id: str, client_id: str):
    """Soft delete: runs/messages keep their history; the engine stops
    seeing the workflow because every engine query filters deleted."""
    workflow = get_owned_workflow(workflow_id, client_id)

    workflow.deleted = True
    workflow.status = "archived"
    save_workflow(workflow)

    return {"workflow_id": workflow.id, "deleted": True, "status": "archived"}


def validate_workflow(workflow_id: str, client_id: str):
    """Dry run of everything /publish checks, as data instead of a 400."""
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)

    errors = []

    if not nodes:
        errors.append("Workflow has no nodes.")
    else:
        errors.extend(validate_for_publish(workflow, nodes))

    errors.extend(validate_publish_rules(workflow))

    return {
        "workflow_id": workflow.id,
        "valid": not errors,
        "errors": errors,
        **analyze_graph(workflow, nodes),
    }


def publish_workflow(workflow_id: str, client_id: str):
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)

    errors = []

    if not nodes:
        errors.append("Workflow has no nodes.")
    else:
        errors.extend(validate_for_publish(workflow, nodes))

    errors.extend(validate_publish_rules(workflow))

    raise_if_graph_errors(errors, "Workflow cannot be published.")

    workflow.status = "published"
    save_workflow(workflow)

    return {"workflow": get_workflow_by_id(workflow.id)}


def unpublish_workflow(workflow_id: str, client_id: str):
    workflow = get_owned_workflow(workflow_id, client_id)

    workflow.status = "draft"
    save_workflow(workflow)

    return {"workflow": get_workflow_by_id(workflow.id)}


def set_default_workflow(workflow_id: str, client_id: str):
    """Publish (if needed) and make this workflow the account's default.

    One default per WhatsApp account is the routing invariant, so this clears
    any existing default on the same account before promoting the target.
    Ordering matters: the graph is validated up front (read-only) so a bad
    workflow can never leave the account with its default cleared; the old
    default is demoted before the target is set, so the one-default rule is
    never transiently violated; keyword-collision rules are checked last.
    """
    workflow = get_owned_workflow(workflow_id, client_id)  # ownership + not-deleted

    # (a) If it needs publishing, confirm the graph itself is publishable
    #     BEFORE mutating any default flag.
    if workflow.status != "published":
        nodes = get_workflow_nodes(workflow.id)
        errors = ["Workflow has no nodes."] if not nodes else list(
            validate_for_publish(workflow, nodes)
        )
        raise_if_graph_errors(errors, "Workflow cannot be published.")

    # (b) Demote the current default(s) on this account.
    # list_workflows_for_client returns (total, items); iterate the items.
    _total, other_workflows = list_workflows_for_client(
        client_id=client_id,
        whatsapp_account_id=workflow.whatsapp_account_id,
        limit=1000,
    )
    for other in other_workflows:
        if other.id != workflow.id and other.is_default:
            other.is_default = False
            save_workflow(other)

    # (c) Promote + publish the target.
    workflow.is_default = True
    workflow.status = "published"

    # (d) Now that defaults are settled, enforce keyword-collision / routing
    #     rules (default-collision can't fire - we just cleared the others).
    raise_if_graph_errors(
        validate_publish_rules(workflow), "Workflow cannot be published."
    )

    save_workflow(workflow)
    return {"workflow": get_workflow_by_id(workflow.id)}


def duplicate_workflow(workflow_id: str, client_id: str):
    """Deep copy to a fresh draft. Keywords and default flag are NOT
    copied - they would instantly collide with the original on publish."""
    source_workflow = get_owned_workflow(workflow_id, client_id)
    source_nodes = get_workflow_nodes(source_workflow.id)

    new_workflow_id = f"{client_id}/workflow:{short_id()}"

    id_map = {
        node.id: f"{new_workflow_id}/node:{node_local_id(node.id)}"
        for node in source_nodes
    }

    new_nodes = []

    for node in source_nodes:
        new_nodes.append(
            WorkflowNode(
                id=id_map[node.id],
                client_id=client_id,
                workflow_id=new_workflow_id,
                created_by_user_id=source_workflow.created_by_user_id,
                updated_by_user_id=source_workflow.updated_by_user_id,
                name=node.name,
                type=node.type,
                next_node_id=id_map.get(node.next_node_id) if node.next_node_id else None,
                config=remap_node_references(node.config, id_map),
                position=node.position,
            )
        )

    new_workflow = Workflow(
        id=new_workflow_id,
        client_id=client_id,
        whatsapp_account_id=source_workflow.whatsapp_account_id,
        created_by_user_id=source_workflow.created_by_user_id,
        updated_by_user_id=source_workflow.updated_by_user_id,
        name=f"{source_workflow.name} (copy)",
        description=source_workflow.description,
        node_ids=[node.id for node in new_nodes],
        first_node_id=(
            id_map.get(source_workflow.first_node_id)
            if source_workflow.first_node_id
            else None
        ),
        status="draft",
    )

    save_workflow(new_workflow)

    for node in new_nodes:
        save_workflow_node(node)

    return {
        "workflow": get_workflow_by_id(new_workflow.id),
        "nodes": get_workflow_nodes(new_workflow.id),
    }


def list_workflow_nodes(workflow_id: str, client_id: str):
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)
    return {"total": len(nodes), "nodes": nodes}


def get_workflow_node_detail(workflow_id: str, node_reference: str, client_id: str):
    workflow = get_owned_workflow(workflow_id, client_id)
    node = find_node_in_workflow(get_workflow_nodes(workflow.id), node_reference)

    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    return {"node": node}


def add_workflow_node(
    workflow_id: str,
    client_id: str,
    request: WorkflowNodeInput,
    expected_version: int | None = None,
):
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)
    check_and_bump_version(workflow, expected_version)

    full_id = f"{workflow.id}/node:{request.id.removeprefix('node:')}"

    if any(node.id == full_id for node in nodes):
        raise HTTPException(
            status_code=400,
            detail=f"Node '{request.id}' already exists in this workflow.",
        )

    id_map = build_node_reference_map(nodes)
    id_map[request.id] = full_id
    id_map[request.id.removeprefix("node:")] = full_id

    node = WorkflowNode(
        id=full_id,
        client_id=client_id,
        workflow_id=workflow.id,
        created_by_user_id=workflow.created_by_user_id,
        updated_by_user_id=workflow.created_by_user_id,
        name=request.name,
        type=request.type,
        next_node_id=(
            id_map.get(request.next_node_id, request.next_node_id)
            if request.next_node_id
            else None
        ),
        config=remap_node_references(request.config, id_map),
        position=request.position,
    )

    candidate_nodes = nodes + [node]

    raise_if_graph_errors(
        validate_workflow_graph(workflow, candidate_nodes),
        "Adding this node would leave the workflow invalid.",
    )

    save_workflow_node(node)

    workflow.node_ids = [existing.id for existing in candidate_nodes]
    save_workflow(workflow)

    return {"node": get_workflow_node_by_id(node.id)}


def update_workflow_node(
    workflow_id: str,
    node_reference: str,
    client_id: str,
    request: UpdateWorkflowNodeRequest,
    expected_version: int | None = None,
):
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)
    node = find_node_in_workflow(nodes, node_reference)

    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    check_and_bump_version(workflow, expected_version)
    id_map = build_node_reference_map(nodes)

    if request.name is not None:
        node.name = request.name

    if request.next_node_id is not None:
        node.next_node_id = id_map.get(request.next_node_id, request.next_node_id)

    if request.config is not None:
        node.config = remap_node_references(request.config, id_map)

    if request.position is not None:
        node.position = request.position

    candidate_nodes = [node if existing.id == node.id else existing for existing in nodes]

    raise_if_graph_errors(
        validate_workflow_graph(workflow, candidate_nodes),
        "Update would leave the workflow invalid.",
    )

    save_workflow_node(node)
    save_workflow(workflow)  # persist the version bump
    return {"node": get_workflow_node_by_id(node.id)}


def delete_workflow_node(
    workflow_id: str,
    node_reference: str,
    client_id: str,
    new_first_node_id: str | None = None,
    expected_version: int | None = None,
):
    """Soft-deletes a node and CUTS every edge pointing at it (sets those
    referrer edges to null - nothing is auto-repointed). The entry node
    can only be deleted if the caller names its replacement."""
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)
    node = find_node_in_workflow(nodes, node_reference)

    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    check_and_bump_version(workflow, expected_version)

    if workflow.first_node_id == node.id:
        if not new_first_node_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the first node; pass new_first_node_id to reassign the entry point first.",
            )

        replacement = find_node_in_workflow(nodes, new_first_node_id)
        if not replacement or replacement.id == node.id:
            raise HTTPException(
                status_code=400,
                detail="new_first_node_id must be a different node in this workflow.",
            )

        workflow.first_node_id = replacement.id

    # Cut every incoming edge: each referrer's edge to this node -> null.
    cut = []
    for referrer, handle in find_referrers(nodes, node.id):
        if referrer.id == node.id:
            continue
        set_node_edge(referrer, handle, None)
        save_workflow_node(referrer)
        cut.append({"node_id": referrer.id, "handle": handle})

    node.deleted = True
    save_workflow_node(node)

    workflow.node_ids = [existing.id for existing in nodes if existing.id != node.id]
    save_workflow(workflow)

    return {"node_id": node.id, "deleted": True, "cut_connections": cut}


def update_workflow_connections(
    workflow_id: str,
    client_id: str,
    changes: list,
    expected_version: int | None = None,
):
    """Explicitly set/clear outgoing edges. Each change is
    {source_node_id, handle, target_node_id|None}. Nothing automatic -
    this is how you wire a new node in, rewire a branch, or cut an edge."""
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)
    check_and_bump_version(workflow, expected_version)

    applied = []

    for change in changes:
        source_ref = change.source_node_id
        handle = change.handle or "default"
        target_ref = change.target_node_id

        source = find_node_in_workflow(nodes, source_ref)
        if not source:
            raise HTTPException(
                status_code=404,
                detail=f"Source node '{source_ref}' not found in this workflow.",
            )

        target_id = None
        if target_ref:
            target = find_node_in_workflow(nodes, target_ref)
            if not target:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target node '{target_ref}' not found in this workflow.",
                )
            if target.id == source.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Node '{node_local_id(source.id)}' cannot connect to itself.",
                )
            target_id = target.id

        set_node_edge(source, handle, target_id)
        save_workflow_node(source)
        applied.append({
            "source_node_id": source.id,
            "handle": handle,
            "target_node_id": target_id,
        })

    # Draft-lenient: never store a malformed node, but allow cut/dangling
    # edges while editing (publish enforces completeness).
    raise_if_graph_errors(
        validate_node_shapes(get_workflow_nodes(workflow.id)),
        "Connection update left a node malformed.",
    )

    save_workflow(workflow)  # persist the version bump
    return {"workflow_id": workflow.id, "version": workflow.version, "applied": applied}


def workflow_connections_view(workflow_id: str, client_id: str):
    """Read the whole graph as a flat edge list plus a reachability report."""
    workflow = get_owned_workflow(workflow_id, client_id)
    nodes = get_workflow_nodes(workflow.id)

    edges = []
    for node in nodes:
        for edge in get_node_edges(node):
            edges.append({
                "source_node_id": node.id,
                "handle": edge["handle"],
                "target_node_id": edge["target"],
            })

    return {
        "workflow_id": workflow.id,
        "first_node_id": workflow.first_node_id,
        "edges": edges,
        **analyze_graph(workflow, nodes),
    }


# =====================================================================
# Runtime APIs
# =====================================================================

def list_runs_service(
    client_id: str,
    whatsapp_account_id: str | None,
    workflow_id: str | None,
    contact_phone: str | None,
    status: str | None,
    limit: int,
    offset: int,
):
    return list_workflow_runs(
        client_id=client_id,
        whatsapp_account_id=whatsapp_account_id,
        workflow_id=workflow_id,
        contact_phone=contact_phone,
        status=status,
        limit=limit,
        offset=offset,
    )


def list_leads_service(
    client_id: str,
    q: str | None,
    source: str | None,
    limit: int,
    offset: int,
):
    """CRM leads feed: one row per arrival (see storage.list_leads). Each row
    carries its run (the fields collected on that visit) and the conversation
    (name, source, disposition, CRM slice) - the CRM keys everything patient-
    level off the conversation id and visit-level off the run id."""
    total, rows = list_leads(client_id, q=q, source=source, limit=limit, offset=offset)

    runs = {r.id: r for r in get_workflow_runs_by_ids([x["run_id"] for x in rows if x.get("run_id")])}
    convs_by_id = {c.id: c for c in get_conversations_by_ids([x["conversation_id"] for x in rows if x.get("conversation_id")])}
    run_phones = sorted({x["contact_phone"] for x in rows if x.get("run_id") and x.get("contact_phone")})
    convs_by_phone: dict[tuple[str, str], Conversation] = {}
    for c in get_conversations_by_phones(client_id, run_phones):
        convs_by_phone[(c.whatsapp_account_id, c.contact_phone)] = c

    items = []
    for x in rows:
        run = runs.get(x.get("run_id") or "")
        conversation = convs_by_id.get(x.get("conversation_id") or "")
        if conversation is None and run is not None:
            conversation = convs_by_phone.get((run.whatsapp_account_id, run.contact_phone))
        if conversation is None:
            # A run whose conversation was deleted from the inbox: nothing to
            # show a patient for, skip it (the total is off by one; harmless).
            continue
        arrived = x.get("arrived_at")
        items.append({
            "key": run.id if run else conversation.id,
            "kind": "run" if run else "conversation",
            "arrived_at": arrived.isoformat() if isinstance(arrived, datetime) else arrived,
            "run": run.model_dump(mode="json") if run else None,
            "conversation": to_inbox_conversation(conversation),
        })
    return total, items


from backend.bot.call_review_service import CALL_REVIEW_MIN_SECONDS  # noqa: E402 (late: avoids a cycle)


def _require_feature(client_id: str, key: str) -> None:
    """Feature gate on the SERVER. Everywhere else a flag only hides UI (the CRM
    reads Client.features off /auth/me), which was harmless when flags hid pages.
    This one spends money on every press, so it is enforced here as well."""
    client = get_client_by_id(client_id)
    if not client or not (client.features or {}).get(key):
        raise HTTPException(status_code=403, detail="This feature is not enabled for your account.")


def start_call_review(client_id: str, phone: str):
    """Queue the AI review of one patient's calls. Ownership and existence are
    the same check: the calls are looked up inside this client's scope, and a
    number with none is a 404 - the same answer another tenant's number gives."""
    _require_feature(client_id, "callReview")
    contact_phone = (phone or "").strip().lstrip("+")
    if not contact_phone:
        raise HTTPException(status_code=400, detail="phone is required.")

    calls = list_calls_for_patient(client_id, contact_phone, limit=200)
    if not calls:
        raise HTTPException(status_code=404, detail="No calls found for this number.")

    conversation_id = next((c.conversation_id for c in calls if c.conversation_id), None)
    existing = get_call_review(client_id, contact_phone)
    if existing and existing.status in ("queued", "running"):
        return existing.model_dump(mode="json")

    # Already reviewed and nothing new since: hand back what we have, spend nothing.
    if existing and existing.status == "done":
        qualifying = {c.id for c in calls
                      if c.answered and c.recording_status == "stored"
                      and (c.duration_seconds or 0) >= CALL_REVIEW_MIN_SECONDS}
        if qualifying and set(existing.calls_covered) == qualifying:
            return existing.model_dump(mode="json")

    review, _queued = enqueue_call_review(client_id, contact_phone, conversation_id)
    return review.model_dump(mode="json") if review else {"status": "queued",
                                                          "client_id": client_id,
                                                          "contact_phone": contact_phone}


def list_call_reviews_service(client_id: str):
    """Every review this clinic owns, for the Calls page to render its column."""
    return [r.model_dump(mode="json") for r in list_call_reviews(client_id)]


def get_run_detail(run_id: str, client_id: str):
    run = get_workflow_run_by_id(run_id)
    assert_owned(run, client_id, "Workflow run")

    return get_run_debug_data(run_id)


def cancel_workflow_run_by_id(run_id: str, client_id: str):
    run = get_workflow_run_by_id(run_id)
    assert_owned(run, client_id, "Workflow run")

    if run.status not in ["active", "waiting_for_user"]:
        raise HTTPException(
            status_code=400,
            detail=f"Run is '{run.status}' and cannot be cancelled.",
        )

    if run.waiting_node_run_id:
        waiting_node_run = get_workflow_node_run_by_id(run.waiting_node_run_id)

        if waiting_node_run:
            waiting_node_run.status = "cancelled"
            waiting_node_run.completed_at = now_utc()
            save_workflow_node_run(waiting_node_run)

    run.status = "cancelled"
    run.waiting_at_node_id = None
    run.waiting_node_run_id = None
    run.completed_at = now_utc()
    save_workflow_run(run)

    conversation = get_conversation_for_contact(
        whatsapp_account_id=run.whatsapp_account_id,
        contact_phone=run.contact_phone,
    )

    if conversation and conversation.active_workflow_run_id == run.id:
        set_conversation_active_run(conversation.id, None)

    return {"workflow_run_id": run.id, "status": "cancelled"}


# =====================================================================
# Templates / Contacts / Broadcasts
# =====================================================================

BROADCAST_SENDS_PER_TICK = int(os.getenv("BROADCAST_SENDS_PER_TICK", "10"))
# Audience-size guardrails: above the threshold the caller must pass confirm=true
# (after previewing); above the hard cap the broadcast is rejected outright.
BROADCAST_CONFIRM_THRESHOLD = int(os.getenv("BROADCAST_CONFIRM_THRESHOLD", "200"))
# A bulk broadcast will not re-send the same template to a number this client
# already broadcast it to within this window. Individual sends are never gated.
BROADCAST_TEMPLATE_COOLDOWN_DAYS = int(os.getenv("BROADCAST_TEMPLATE_COOLDOWN_DAYS", "30"))
BROADCAST_MAX_AUDIENCE = int(os.getenv("BROADCAST_MAX_AUDIENCE", "5000"))
# Recipients stuck 'sending' longer than this (a worker died mid-send) are
# requeued so the broadcast can finish and nobody is silently dropped.
BROADCAST_SENDING_RECLAIM_SECONDS = int(os.getenv("BROADCAST_SENDING_RECLAIM_SECONDS", "300"))

# Meta error codes that mean "slow down" (rate/throughput limits) - retry later.
_RATE_LIMIT_CODES = {4, 80007, 130429, 131048, 131056}


def _owned_account(account_id: str, client_id: str) -> WhatsAppAccount:
    return assert_owned(get_whatsapp_account_or_404(account_id), client_id, "WhatsApp account")


def _count_body_variables(components: list[dict[str, Any]]) -> int:
    """Highest {{n}} placeholder in the BODY component (0 if none)."""
    import re as _re
    for comp in components or []:
        if str(comp.get("type", "")).upper() == "BODY":
            nums = [int(n) for n in _re.findall(r"{{\s*(\d+)\s*}}", comp.get("text", "") or "")]
            return max(nums) if nums else 0
    return 0


def render_template_body(components: list[dict[str, Any]], params: list[str] | None) -> str:
    """The template's BODY text with {{1}},{{2}}… filled from params (in order),
    so a sent template reads in the inbox as the customer actually received it.
    Unfilled placeholders are left as-is; no BODY -> empty string."""
    import re as _re
    body = ""
    for comp in components or []:
        if str(comp.get("type", "")).upper() == "BODY":
            body = comp.get("text", "") or ""
            break
    values = list(params or [])

    def _sub(match: "_re.Match[str]") -> str:
        idx = int(match.group(1)) - 1
        return str(values[idx]) if 0 <= idx < len(values) else match.group(0)

    return _re.sub(r"{{\s*(\d+)\s*}}", _sub, body)


def _coerce_category(value: str | None) -> str:
    v = (value or "UTILITY").upper()
    return v if v in ("MARKETING", "UTILITY", "AUTHENTICATION") else "UTILITY"


_KNOWN_TEMPLATE_STATUSES = {
    "PENDING", "APPROVED", "REJECTED", "PAUSED", "DISABLED",
    "PENDING_DELETION", "FLAGGED", "IN_APPEAL",
}


def _coerce_template_status(value: str | None) -> str:
    v = (value or "").upper()
    return v if v in _KNOWN_TEMPLATE_STATUSES else "PENDING"


def _unsupported_variable_components(components: list[dict[str, Any]]) -> list[str]:
    """We only fill BODY {{n}} at send time. Report HEADER/BUTTON components that
    carry variables so we can reject those templates with a clear message."""
    import re as _re
    offenders: list[str] = []
    for comp in components or []:
        ctype = str(comp.get("type", "")).upper()
        if ctype == "BODY":
            continue
        blob = json.dumps(comp)
        if _re.search(r"{{\s*\d+\s*}}", blob):
            offenders.append(ctype or "UNKNOWN")
    return offenders


# ---- Templates -------------------------------------------------------

def submit_template(account_id: str, client_id: str, request: CreateTemplateRequest) -> Template:
    account = _owned_account(account_id, client_id)
    if not account.whatsapp_business_account_id:
        raise HTTPException(status_code=400, detail="Account has no whatsapp_business_account_id.")

    name = request.name.strip().lower().replace(" ", "_")
    meta_response = create_message_template(
        account.whatsapp_business_account_id, name, request.language,
        request.category, request.components, account.access_token,
    )
    # Reuse the existing row's id so a re-submit (e.g. after a rejection) updates
    # in place instead of colliding with the unique (account, name, language) index.
    existing = get_template(account_id, name, request.language)
    template = Template(
        id=existing.id if existing else f"tmpl:{short_id()}",
        client_id=client_id,
        whatsapp_account_id=account_id,
        waba_id=account.whatsapp_business_account_id,
        name=name,
        language=request.language,
        category=request.category,
        components=request.components,
        body_variable_count=_count_body_variables(request.components),
        status=_coerce_template_status(meta_response.get("status")),
        meta_template_id=meta_response.get("id"),
    )
    save_template(template)
    return template


def list_templates_service(account_id: str, client_id: str) -> list[Template]:
    _owned_account(account_id, client_id)
    return list_templates_for_account(account_id)


def get_template_service(account_id: str, template_id: str, client_id: str) -> Template:
    _owned_account(account_id, client_id)
    template = get_template_by_id(template_id)
    if not template or template.whatsapp_account_id != account_id:
        raise HTTPException(status_code=404, detail="Template not found.")
    return template


def sync_templates_from_meta(account_id: str, client_id: str) -> dict:
    account = _owned_account(account_id, client_id)
    remote = list_message_templates(account.whatsapp_business_account_id, account.access_token)
    for t in remote:
        name, language = t.get("name"), t.get("language")
        if not name or not language:
            continue
        status = _coerce_template_status(t.get("status"))
        existing = get_template(account_id, name, language)
        if existing:
            existing.status = status
            existing.meta_template_id = t.get("id") or existing.meta_template_id
            existing.rejected_reason = t.get("rejected_reason")
            existing.category = _coerce_category(t.get("category") or existing.category)
            # Pull the current content too, so an edit made in the Meta
            # dashboard (body text, footer, buttons) shows up here.
            remote_components = t.get("components")
            if isinstance(remote_components, list) and remote_components:
                existing.components = remote_components
                existing.body_variable_count = _count_body_variables(remote_components)
            save_template(existing)
        else:
            save_template(Template(
                id=f"tmpl:{short_id()}", client_id=client_id, whatsapp_account_id=account_id,
                waba_id=account.whatsapp_business_account_id, name=name, language=language,
                category=_coerce_category(t.get("category")), components=t.get("components", []),
                body_variable_count=_count_body_variables(t.get("components", [])),
                status=status, meta_template_id=t.get("id"), rejected_reason=t.get("rejected_reason"),
            ))
    return {"synced": len(remote), "templates": list_templates_for_account(account_id)}


def delete_template_service(account_id: str, template_id: str, client_id: str) -> dict:
    account = _owned_account(account_id, client_id)
    template = get_template_by_id(template_id)
    if not template or template.whatsapp_account_id != account_id:
        raise HTTPException(status_code=404, detail="Template not found.")
    delete_message_template(template.waba_id, template.name, account.access_token)
    delete_template_by_id(template_id)
    return {"deleted": template_id}


def send_test_template(account_id: str, template_id: str, client_id: str,
                       request: TestSendTemplateRequest) -> dict:
    account = _owned_account(account_id, client_id)
    template = get_template_by_id(template_id)
    if not template or template.whatsapp_account_id != account_id:
        raise HTTPException(status_code=404, detail="Template not found.")
    if template.status != "APPROVED":
        raise HTTPException(status_code=400, detail="Only APPROVED templates can be sent.")
    _assert_template_sendable(template)
    provided = request.params[: template.body_variable_count]
    if len(provided) < template.body_variable_count or any(not str(p).strip() for p in provided):
        raise HTTPException(
            status_code=400,
            detail=f"This template needs {template.body_variable_count} non-empty body parameter(s).",
        )
    # Callers (notably a client's Google Apps Script) post "+9199..." - storing
    # that verbatim produced a second conversation per patient and a "++91" in
    # the UI, which renders the number as +{contact_phone}. Normalise once, the
    # same way import_contacts_service does, and use it everywhere below.
    to_phone = (request.to_phone or "").strip().lstrip("+")
    meta_response = send_whatsapp_template_message(
        account.phone_number_id, to_phone, template.name,
        template.language, request.params, account.access_token,
    )

    # Record the send in the contact's inbox thread so agents see the template
    # we sent (labeled as a template), not just the customer's later reply.
    # Best-effort: a recording hiccup must never fail a delivered send.
    try:
        message = MessageRecord(
            id=make_message_id(),
            client_id=client_id,
            whatsapp_account_id=account_id,
            contact_phone=to_phone,
            direction="outgoing",
            message_type="template",
            text=render_template_body(template.components, provided),
            metadata={
                "sent_by": "template",
                "template": {
                    "name": template.name,
                    "language": template.language,
                    "params": provided,
                },
            },
            status="created",
        )
        save_message(message)
        record_send_result(message, meta_response=meta_response)
        upsert_conversation_on_message(
            client_id=client_id,
            whatsapp_account_id=account_id,
            contact_phone=to_phone,
            text=f"📋 {template.name}",
            direction="outgoing",
            message_type="template",
        )
    except Exception as error:
        print(f"TEMPLATE INBOX RECORD ERROR ({template.name} -> {to_phone}): {error}")

    return {"sent": True, "meta_response": meta_response}


def handle_template_status_update(payload: dict[str, Any]) -> dict:
    try:
        entry = payload["entry"][0]
        waba_id = entry.get("id")
        value = entry["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return {"ignored": True, "reason": "Invalid template-status payload."}

    name = value.get("message_template_name")
    language = value.get("message_template_language")
    raw_event = (value.get("event") or "").upper()
    reason = value.get("reason")
    if not (name and language and raw_event):
        return {"ignored": True, "reason": "Incomplete template-status event."}

    # Ignore events we don't model (e.g. quality/category updates) so we never
    # write an unexpected status onto the template.
    if raw_event not in _KNOWN_TEMPLATE_STATUSES:
        return {"ignored": True, "reason": f"Unhandled template event: {raw_event}"}

    matched = set_template_status_by_waba(
        waba_id, name, language, raw_event, reason if raw_event == "REJECTED" else None
    )
    event = raw_event
    return {
        "mode": "template_status_update", "template": name, "language": language,
        "status": event, "matched": matched,
    }


# ---- Contacts --------------------------------------------------------

def list_contacts_service(account_id: str, client_id: str, tag: str | None = None,
                          opted_out: bool | None = None, search: str | None = None,
                          limit: int = 50, offset: int = 0):
    _owned_account(account_id, client_id)
    total, contacts = list_contacts(account_id, tag=tag, opted_out=opted_out,
                                    search=search, limit=limit, offset=offset)
    return total, [c.model_dump(mode="json") for c in contacts]


def import_contacts_service(account_id: str, client_id: str, request: ImportContactsRequest) -> dict:
    _owned_account(account_id, client_id)
    imported = 0
    for item in request.contacts:
        phone = (item.phone or "").strip().lstrip("+")
        if not phone:
            continue
        upsert_contact(account_id, client_id, phone, name=item.name, source="import",
                       marketing_opt_in=item.opted_in)
        add_contact_tags(account_id, phone, item.tags)
        imported += 1
    return {"imported": imported}


def set_contact_opt_out_service(account_id: str, contact_id: str, client_id: str,
                                opted_out: bool) -> dict:
    _owned_account(account_id, client_id)
    contact = get_contact_by_id(contact_id)
    if not contact or contact.whatsapp_account_id != account_id:
        raise HTTPException(status_code=404, detail="Contact not found.")
    # Opt-out is a hard block that also revokes marketing consent; opt-in
    # re-subscribes and grants marketing consent.
    update_contact_consent(
        account_id, contact.phone,
        opted_out=opted_out, marketing_opt_in=not opted_out,
    )
    return {"contact_id": contact_id, "opted_out": opted_out, "marketing_opt_in": not opted_out}


# ---- Broadcasts ------------------------------------------------------

def _resolve_params(mapping: dict, contact: Contact, count: int) -> tuple[list[str], bool]:
    """Fill BODY {{1}}..{{count}} for one contact. Values starting with '@' map to
    contact fields (@contact.name / @contact.phone); else literal. A fallback can
    be given as '@contact.name|there'. Returns (params, has_empty); has_empty is
    True if any required param resolved blank (Meta rejects empty params)."""
    params: list[str] = []
    has_empty = False
    for i in range(1, count + 1):
        raw = (mapping or {}).get(str(i), "")
        fallback = ""
        if isinstance(raw, str) and raw.startswith("@") and "|" in raw:
            raw, fallback = raw.split("|", 1)
        if isinstance(raw, str) and raw.startswith("@"):
            path = raw[1:]
            if path in ("contact.name", "name"):
                val = contact.name or ""
            elif path in ("contact.phone", "phone"):
                val = contact.phone
            else:
                val = ""
        else:
            val = "" if raw is None else str(raw)
        val = val.strip()
        if not val:
            val = fallback.strip()
        if not val:
            has_empty = True
        params.append(val)
    return params, has_empty


def _assert_template_sendable(template: Template):
    """We only fill BODY variables; reject templates whose HEADER/BUTTON carry
    variables (Meta would reject the send with a param mismatch)."""
    offenders = _unsupported_variable_components(template.components)
    if offenders:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Template '{template.name}' has variables in {sorted(set(offenders))} "
                "components, which aren't supported yet. Use a template whose only "
                "variables are in the BODY."
            ),
        )


def _get_sendable_template(account_id: str, name: str, language: str) -> Template:
    template = get_template(account_id, name, language)
    if not template or template.status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail="Template not found or not APPROVED for this account.",
        )
    _assert_template_sendable(template)
    return template


def _resolve_broadcast_targets(account_id: str, client_id: str, template: Template,
                               request: CreateBroadcastRequest) -> tuple[list[BroadcastRecipient], dict]:
    """Resolve the audience + per-contact params into recipient rows and a
    breakdown. Applies the MARKETING opt-in gate and the empty-param skip rule.
    Recipients carry broadcast_id='' until a broadcast id is assigned."""
    audience = request.audience.model_dump()
    require_optin = (template.category == "MARKETING")
    contacts = get_audience_contacts(
        account_id, audience, require_marketing_opt_in=require_optin
    )

    # Per-client cooldown: numbers this client already broadcast this template
    # to recently are skipped, with the date, so staff can see why.
    since = now_utc() - timedelta(days=BROADCAST_TEMPLATE_COOLDOWN_DAYS)
    recent = recent_template_recipients(
        client_id, template.name, [c.phone for c in contacts], since
    )

    recipients: list[BroadcastRecipient] = []
    pending = 0
    skipped = 0
    cooldown_skipped = 0
    for c in contacts:
        params, has_empty = _resolve_params(
            request.variable_mapping, c, template.body_variable_count
        )
        error = None
        if c.phone in recent:
            cooldown_skipped += 1
            error = (f"Already received this template on {recent[c.phone].strftime('%d %b %Y')} "
                     f"({BROADCAST_TEMPLATE_COOLDOWN_DAYS}-day cooldown).")
        elif has_empty:
            error = "Missing template variable value (no name/fallback)."
        if error:
            skipped += 1
        else:
            pending += 1
        recipients.append(BroadcastRecipient(
            id=f"brcpt:{short_id()}",
            broadcast_id="",
            client_id=client_id,
            whatsapp_account_id=account_id,
            contact_phone=c.phone,
            params=params,
            status="skipped" if error else "pending",
            error=error,
        ))

    breakdown = {
        "matched": len(contacts),
        "sendable": pending,
        "skipped": skipped,
        "cooldown_skipped": cooldown_skipped,
        "cooldown_days": BROADCAST_TEMPLATE_COOLDOWN_DAYS,
        "marketing_gated": require_optin,
    }
    return recipients, breakdown


def preview_broadcast(account_id: str, client_id: str, request: CreateBroadcastRequest) -> dict:
    """Dry-run: returns the audience breakdown + whether a confirm is required,
    WITHOUT creating a broadcast or contacts. For `phones`, reports unknown numbers."""
    _owned_account(account_id, client_id)
    template = _get_sendable_template(account_id, request.template_name, request.template_language)

    audience = request.audience.model_dump()
    unknown_phones: list[str] = []
    if audience.get("type") == "phones":
        cleaned = [(p or "").strip().lstrip("+") for p in audience.get("phones", [])]
        cleaned = [p for p in cleaned if p]
        known = {c.phone for c in get_audience_contacts(account_id, {"type": "phones", "phones": cleaned})}
        unknown_phones = [p for p in cleaned if p not in known]

    _, breakdown = _resolve_broadcast_targets(account_id, client_id, template, request)
    sendable = breakdown["sendable"]
    return {
        **breakdown,
        "unknown_phones": unknown_phones,
        "confirm_threshold": BROADCAST_CONFIRM_THRESHOLD,
        "hard_cap": BROADCAST_MAX_AUDIENCE,
        "requires_confirmation": sendable > BROADCAST_CONFIRM_THRESHOLD,
        "over_hard_cap": sendable > BROADCAST_MAX_AUDIENCE,
    }


def create_broadcast(account_id: str, client_id: str, request: CreateBroadcastRequest) -> dict:
    _owned_account(account_id, client_id)
    template = _get_sendable_template(account_id, request.template_name, request.template_language)

    audience = request.audience.model_dump()
    # For an explicit phone list, make sure each number exists as a contact so it
    # is actually targetable (cold numbers get no marketing consent, so a MARKETING
    # template will still correctly exclude them).
    if audience.get("type") == "phones":
        for phone in audience.get("phones", []):
            clean = (phone or "").strip().lstrip("+")
            if clean:
                upsert_contact(account_id, client_id, clean, source="import")

    recipients, breakdown = _resolve_broadcast_targets(account_id, client_id, template, request)
    sendable = breakdown["sendable"]

    if breakdown["matched"] == 0:
        raise HTTPException(
            status_code=400,
            detail="No eligible contacts for this audience (none match, opted out, or lack marketing consent).",
        )
    if sendable == 0:
        if breakdown["cooldown_skipped"] == breakdown["matched"]:
            detail = (f"Nothing sendable: all {breakdown['matched']} matched numbers already received "
                      f"this template in the last {BROADCAST_TEMPLATE_COOLDOWN_DAYS} days.")
        elif breakdown["cooldown_skipped"]:
            detail = (f"Nothing sendable: {breakdown['cooldown_skipped']} of {breakdown['matched']} "
                      f"already received this template in the last {BROADCAST_TEMPLATE_COOLDOWN_DAYS} days "
                      "and the rest are missing template variable values.")
        else:
            detail = (f"Nothing sendable: all {breakdown['matched']} matched contacts were skipped "
                      "(missing template variable values). Add a fallback like '@contact.name|there'.")
        raise HTTPException(status_code=400, detail=detail)
    if sendable > BROADCAST_MAX_AUDIENCE:
        raise HTTPException(
            status_code=400,
            detail=f"Audience of {sendable} exceeds the hard cap of {BROADCAST_MAX_AUDIENCE}. "
                   "Split it into smaller broadcasts.",
        )
    if sendable > BROADCAST_CONFIRM_THRESHOLD and not request.confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "requires_confirmation": True,
                "eligible": breakdown["matched"],
                "sendable": sendable,
                "skipped": breakdown["skipped"],
                "cooldown_skipped": breakdown["cooldown_skipped"],
                "message": f"This will message {sendable} contacts. Resend with confirm=true to proceed.",
            },
        )

    broadcast = Broadcast(
        id=f"bcast:{short_id()}",
        client_id=client_id,
        whatsapp_account_id=account_id,
        name=request.name,
        template_name=request.template_name,
        template_language=request.template_language,
        variable_mapping=request.variable_mapping,
        audience=audience,
        status="running",
        counts={"total": breakdown["matched"], "pending": sendable,
                "sent": 0, "delivered": 0, "read": 0, "failed": 0, "skipped": breakdown["skipped"]},
        started_at=now_utc(),
    )
    save_broadcast(broadcast)
    for r in recipients:
        r.broadcast_id = broadcast.id
    insert_broadcast_recipients(recipients)
    return get_broadcast_by_id(broadcast.id).model_dump(mode="json")


def list_broadcasts_service(account_id: str, client_id: str, limit: int = 50, offset: int = 0):
    _owned_account(account_id, client_id)
    total, items = list_broadcasts_for_account(account_id, limit=limit, offset=offset)
    return total, [b.model_dump(mode="json") for b in items]


def _owned_broadcast(broadcast_id: str, client_id: str) -> Broadcast:
    broadcast = get_broadcast_by_id(broadcast_id)
    if not broadcast or broadcast.client_id != client_id:
        raise HTTPException(status_code=404, detail="Broadcast not found.")
    return broadcast


def get_broadcast_service(broadcast_id: str, client_id: str) -> dict:
    return _owned_broadcast(broadcast_id, client_id).model_dump(mode="json")


def set_broadcast_state(broadcast_id: str, client_id: str, action: str) -> dict:
    broadcast = _owned_broadcast(broadcast_id, client_id)
    transitions = {
        "pause": ("running", "paused"),
        "resume": ("paused", "running"),
        "cancel": (None, "cancelled"),
    }
    if action not in transitions:
        raise HTTPException(status_code=400, detail="Unknown broadcast action.")
    required_from, new_status = transitions[action]
    if required_from and broadcast.status != required_from:
        raise HTTPException(
            status_code=409,
            detail=f"Can only {action} a broadcast that is '{required_from}'.",
        )
    if broadcast.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Broadcast already {broadcast.status}.")
    set_broadcast_status(broadcast_id, new_status)
    return get_broadcast_by_id(broadcast_id).model_dump(mode="json")


def list_broadcast_recipients_service(broadcast_id: str, client_id: str,
                                      limit: int = 100, offset: int = 0):
    _owned_broadcast(broadcast_id, client_id)
    total, items = list_recipients_for_broadcast(broadcast_id, limit=limit, offset=offset)
    return total, [r.model_dump(mode="json") for r in items]


# ---- Broadcast worker (drained by the lifespan loop) -----------------

def _send_one_broadcast_recipient(broadcast: Broadcast, account: WhatsAppAccount,
                                  recipient: BroadcastRecipient) -> str:
    """Returns 'sent' | 'failed' | 'rate_limited'. On rate limit the recipient is
    put back to pending for a later tick."""
    try:
        meta_response = send_whatsapp_template_message(
            phone_number_id=account.phone_number_id,
            to_phone=recipient.contact_phone,
            template_name=broadcast.template_name,
            language=broadcast.template_language,
            body_params=recipient.params,
            access_token=account.access_token,
        )
    except HTTPException as error:
        detail = error.detail
        code = None
        if isinstance(detail, dict):
            code = ((detail.get("meta_response") or {}).get("error") or {}).get("code")
        if code in _RATE_LIMIT_CODES:
            set_recipient_status(recipient.id, "pending")
            return "rate_limited"
        finalize_recipient_send(recipient.id, "failed", error=detail)
        bump_broadcast_counts(broadcast.id, pending=-1, failed=1)
        return "failed"

    meta_message_id = None
    messages = (meta_response or {}).get("messages", [])
    if messages:
        meta_message_id = messages[0].get("id")

    # Record in the inbox thread so agents see what went out, rendered as the
    # customer received it. Body-render is best-effort (template lookup may miss);
    # fall back to the bare name rather than an empty bubble.
    tmpl = get_template(account.id, broadcast.template_name, broadcast.template_language)
    body_text = (
        render_template_body(tmpl.components, recipient.params)
        if tmpl else f"📋 {broadcast.template_name}"
    )
    message = MessageRecord(
        id=make_message_id(),
        client_id=broadcast.client_id,
        whatsapp_account_id=account.id,
        contact_phone=recipient.contact_phone,
        direction="outgoing",
        message_type="template",
        text=body_text,
        metadata={
            "sent_by": "broadcast",
            "broadcast_id": broadcast.id,
            "template": {
                "name": broadcast.template_name,
                "language": broadcast.template_language,
                "params": recipient.params,
            },
            "meta_message_id": meta_message_id,
            "meta_response": meta_response,
        },
        status="sent",
    )
    save_message(message)
    upsert_conversation_on_message(
        client_id=broadcast.client_id,
        whatsapp_account_id=account.id,
        contact_phone=recipient.contact_phone,
        text=f"📋 {broadcast.template_name}",
        direction="outgoing",
        message_type="template",
    )
    finalize_recipient_send(recipient.id, "sent", meta_message_id=meta_message_id)
    bump_broadcast_counts(broadcast.id, pending=-1, sent=1)
    return "sent"


def drain_broadcasts():
    """One paced pass across all running broadcasts. Called on a loop from the
    app lifespan. Sends up to BROADCAST_SENDS_PER_TICK per broadcast per tick;
    re-checks status each send so pause/cancel take effect promptly."""
    for broadcast_id in list_running_broadcast_ids():
        try:
            broadcast = get_broadcast_by_id(broadcast_id)
            if not broadcast or broadcast.status != "running":
                continue
            # Requeue anything stuck 'sending' from a previously interrupted tick.
            reclaim_stale_sending_recipients(
                broadcast_id,
                now_utc() - timedelta(seconds=BROADCAST_SENDING_RECLAIM_SECONDS),
            )
            account = get_whatsapp_account_by_id(broadcast.whatsapp_account_id)
            if not account:
                continue

            sent = 0
            while sent < BROADCAST_SENDS_PER_TICK:
                fresh = get_broadcast_by_id(broadcast_id)
                if not fresh or fresh.status != "running":
                    break
                recipient = claim_pending_recipient(broadcast_id)
                if recipient is None:
                    if count_open_recipients(broadcast_id) == 0:
                        set_broadcast_status(broadcast_id, "completed", completed_at=now_utc())
                    break
                outcome = _send_one_broadcast_recipient(broadcast, account, recipient)
                if outcome == "rate_limited":
                    break  # back off this broadcast until the next tick
                sent += 1
        except Exception as error:
            print(f"BROADCAST DRAIN FAILED for {broadcast_id}: {error}", flush=True)


_DELIVERY_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 3}


def webhook_status_error_text(status_event: dict) -> str | None:
    """'131026: Message undeliverable' from a status webhook's `errors` list, or None."""
    errors = status_event.get("errors") if isinstance(status_event, dict) else None
    if not errors or not isinstance(errors, list) or not isinstance(errors[0], dict):
        return None
    err = errors[0]
    code = err.get("code")
    text = err.get("title") or err.get("message") or (err.get("error_data") or {}).get("details")
    if code is None and not text:
        return None
    return f"{code}: {text}" if code is not None and text else str(code if code is not None else text)


def apply_broadcast_delivery_status(meta_message_id: str, delivery_status: str,
                                    error: str | None = None):
    """Advance a broadcast recipient (and its broadcast counters) when a delivery
    status webhook arrives for a message we broadcast. `error` (from the webhook's
    `errors` list) is stored on the recipient when the status is `failed`."""
    if delivery_status not in ("delivered", "read", "failed"):
        return
    recipient = get_recipient_by_meta_message_id(meta_message_id)
    if not recipient:
        return
    if _DELIVERY_RANK.get(delivery_status, 0) <= _DELIVERY_RANK.get(recipient.status, 0):
        return
    set_recipient_status(recipient.id, delivery_status,
                         error=error if delivery_status == "failed" else None)
    if delivery_status == "failed":
        # Reclassify from a success (counted 'sent') to failed so the counters
        # stay consistent with total instead of double-counting.
        bump_broadcast_counts(recipient.broadcast_id, failed=1, sent=-1)
    else:
        bump_broadcast_counts(recipient.broadcast_id, **{delivery_status: 1})


# ---------------------------------------------------------------------------
# Ripplica-only feature control (X-Admin-Secret). Clients never see or touch
# this; the CRM reads Client.features off GET /auth/me and hides what is off.
# ---------------------------------------------------------------------------

def admin_list_clients() -> list[dict[str, Any]]:
    """Every tenant with its CRM feature entitlements, for an at-a-glance view."""
    _, clients = list_clients(status=None, limit=500, offset=0)
    return [
        {"id": c.id, "name": c.name, "status": c.status, "features": c.features}
        for c in clients
    ]


def admin_set_client_features(client_id: str, request: SetClientFeaturesRequest) -> dict[str, Any]:
    """Merge feature switches into a client: send only the keys to change,
    `true` restores one. Unknown keys are a 422 so a typo never silently
    does nothing."""
    unknown = sorted(set(request.features) - CRM_FEATURE_KEYS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown feature keys: {', '.join(unknown)}. "
                   f"Valid: {', '.join(sorted(CRM_FEATURE_KEYS))}",
        )
    client = get_client_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    client.features = {**(client.features or {}), **request.features}
    save_client(client)
    return {"id": client.id, "name": client.name, "features": client.features}


# ---------------------------------------------------------------------------
# FasterQ call recordings
# ---------------------------------------------------------------------------
# FasterQ POSTs once when a call ends and again when its recording is ready
# (same callId). Calls are matched to a client by the agent name the clinic
# saved in Settings, and to a conversation by the customer's number. Outbound
# calls bump the lead's "Calls" count once; recordings are copied to our bucket.

# .strip(): a secret created with `openssl … | gcloud secrets create --data-file=-` carries a trailing newline.
FASTERQ_WEBHOOK_SECRET = os.getenv("FASTERQ_WEBHOOK_SECRET", "").strip()
CALL_RECORDING_DOWNLOAD_TIMEOUT = int(os.getenv("CALL_RECORDING_DOWNLOAD_TIMEOUT", "30"))


def normalise_indian_phone(raw: Any) -> str:
    """FasterQ sends 10 digits; we store what WhatsApp does: country code + number."""
    digits = re.sub(r"\D", "", str(raw or ""))
    digits = digits.lstrip("0")
    if len(digits) == 10:
        return "91" + digits
    return digits


def verify_fasterq_secret(header_value: str | None) -> None:
    """The API key FasterQ is configured to send (header `Authorization`)."""
    if not FASTERQ_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="FASTERQ_WEBHOOK_SECRET is not configured on the server.")
    given = (header_value or "").strip()
    if given.lower().startswith("bearer "):
        given = given[7:].strip()
    if not given or not hmac.compare_digest(given, FASTERQ_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def to_call_json(call: CallRecord, contact_name: str | None = None) -> dict[str, Any]:
    out = call.model_dump(mode="json")
    out.pop("raw", None)
    out["contact_name"] = contact_name
    return out


def _link_call(call: CallRecord) -> None:
    """Fill in client / conversation where possible and apply the Calls bump
    for an outbound call the first time it is tied to a conversation."""
    if not call.client_id and call.agent_name:
        client = find_client_by_agent_name(call.agent_name)
        if client:
            call.client_id = client.id
    if call.client_id and not call.conversation_id and call.contact_phone:
        conversation = find_conversation_by_client_phone(call.client_id, call.contact_phone)
        if conversation:
            call.conversation_id = conversation.id
    if call.direction == "outbound" and call.conversation_id and not call.call_tried_applied:
        increment_call_tried(call.conversation_id)
        call.call_tried_applied = True


def ingest_fasterq_call(payload: dict[str, Any]) -> dict[str, Any]:
    """Store/refresh one call from a FasterQ webhook. Idempotent on callId.
    Returns what the route needs; the recording download is left to the caller
    (a background task) so FasterQ gets its 2xx well within its 10 s timeout."""
    call_id = str(payload.get("callId") or "").strip()
    if not call_id:
        return {"ignored": "no callId"}
    if call_id.startswith("test_"):
        return {"ignored": "test push", "callId": call_id}

    direction = "outbound" if str(payload.get("direction") or "").strip().lower().startswith("out") else "inbound"
    source = {0: "sim", 1: "whatsapp", "0": "sim", "1": "whatsapp"}.get(payload.get("source"), "unknown")
    phone = normalise_indian_phone(payload.get("phone"))

    call = get_call_by_provider_id("fasterq", call_id) or CallRecord(
        id=f"call:{short_id()}", provider="fasterq", provider_call_id=call_id, contact_phone=phone, direction=direction,
    )
    call.contact_phone = phone or call.contact_phone
    call.direction = direction
    call.agent_name = (str(payload.get("agentName") or "").strip() or call.agent_name)
    call.agent_email = (str(payload.get("agentEmail") or "").strip() or call.agent_email)
    call.agent_phone = (normalise_indian_phone(payload.get("agentPhone")) or call.agent_phone)
    call.started_at = _parse_iso(payload.get("startTime")) or call.started_at or now_utc()
    try:
        call.duration_seconds = int(float(payload.get("duration") or 0))
    except (TypeError, ValueError):
        pass
    call.answered = bool(payload.get("answered"))
    call.source = source
    call.raw = payload

    _link_call(call)

    url = str(payload.get("recordingUrl") or "").strip()
    need_download = False
    if url and url != call.recording_url:
        call.recording_url = url
        call.recording_status = "pending"
        call.recording_attempts = 0
        call.recording_error = None
        need_download = True
    elif url and call.recording_status in ("pending", "failed"):
        need_download = True

    save_call(call)
    return {"call_id": call.id, "client_id": call.client_id, "conversation_id": call.conversation_id,
            "call_tried_applied": call.call_tried_applied, "download": need_download}


def fetch_call_recording(call_id: str) -> None:
    """Copy the provider's recording into our private bucket. Never raises."""
    call = get_call_by_id(call_id)
    if not call or not call.recording_url or call.recording_status == "stored":
        return
    try:
        response = requests.get(call.recording_url, timeout=CALL_RECORDING_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "audio/mpeg").split(";")[0].strip()
        if not content_type.startswith("audio/"):
            content_type = "audio/mpeg"
        ext = gcs_service.extension_for_mime(content_type) or ".mp3"
        prefix = f"call-recordings/{call.client_id or 'unassigned'}"
        call.recording_gcs_uri = gcs_service.upload_bytes(response.content, content_type, ext, prefix=prefix)
        call.recording_status = "stored"
        call.recording_error = None
    except Exception as error:
        call.recording_attempts += 1
        call.recording_status = "failed"
        call.recording_error = str(error)[:300]
    save_call(call)


def reattach_unassigned_calls_for_client(client: Client) -> int:
    """After a clinic saves its agent names: adopt matching calls that arrived
    earlier without a client."""
    names = [n.strip().lower() for n in ((client.call_recording.agent_names if client.call_recording else []) or [])]
    count = 0
    for call in list_calls_for_agent_unassigned(names):
        call.client_id = client.id
        _link_call(call)
        save_call(call)
        count += 1
    return count


def sweep_call_recordings() -> None:
    """Periodic: retry recording copies; link calls whose clinic/conversation
    became known later (agent name saved, or the person messaged)."""
    for call in list_calls_needing_recording():
        fetch_call_recording(call.id)
    since = now_utc() - timedelta(days=30)
    for call in list_calls_missing_links(since):
        before = (call.client_id, call.conversation_id, call.call_tried_applied)
        _link_call(call)
        if (call.client_id, call.conversation_id, call.call_tried_applied) != before:
            save_call(call)


def list_calls_service(client_id: str, direction: str | None, answered: bool | None, phone: str | None,
                       conversation_id: str | None, limit: int, offset: int):
    if direction and direction not in ("inbound", "outbound"):
        raise HTTPException(status_code=422, detail="direction must be inbound or outbound")
    total, calls = list_calls(client_id, direction, answered, phone, conversation_id, limit, offset)
    # Name the customer from the conversation, in one query.
    ids = [c.conversation_id for c in calls if c.conversation_id]
    names: dict[str, str | None] = {}
    if ids:
        for doc in db["conversations"].find({"id": {"$in": ids}}, {"id": 1, "contact_name": 1}):
            names[doc["id"]] = doc.get("contact_name")
    return total, [to_call_json(c, names.get(c.conversation_id or "")) for c in calls]


def call_recording_url(call_id: str, client_id: str) -> str:
    """Short-lived signed URL for the browser's <audio> element."""
    call = get_call_by_id(call_id)
    if not call or call.client_id != client_id:
        raise HTTPException(status_code=404, detail="Call not found.")
    if call.recording_gcs_uri:
        return gcs_service.generate_signed_url(call.recording_gcs_uri, minutes=15)
    if call.recording_url:
        return call.recording_url
    raise HTTPException(status_code=404, detail="No recording for this call.")
