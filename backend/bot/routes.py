from __future__ import annotations

from backend.bot.models import SetClientFeaturesRequest
from backend.bot.services import admin_list_clients, admin_set_client_features
from backend.bot.services import (
    verify_fasterq_secret, ingest_fasterq_call, fetch_call_recording,
    list_calls_service, call_recording_url,
)
import traceback

from fastapi import APIRouter, Request, Query, Depends, HTTPException, UploadFile, File, BackgroundTasks, Header
from fastapi.responses import (
    PlainTextResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from backend.bot.models import (
    FullSetupRequest,
    DevGoogleConnectionRequest,
    EmbeddedSignupCompleteRequest,
    RegisterPhoneNumberRequest,
    TestWebhookRequest,
    SendWhatsAppTestRequest,
    SendWhatsAppButtonTestRequest,
    SendWhatsAppListTestRequest,
    UpdateContactRequest,
    AgentSendRequest,
    CreateClientRequest,
    UpdateClientRequest,
    CreateUserRequest,
    UpdateUserRequest,
    CreateWhatsAppAccountRequest,
    UpdateWhatsAppAccountRequest,
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowNodeInput,
    UpdateWorkflowNodeRequest,
    UpdateConnectionsRequest,
    LoginRequest,
    CreateTemplateRequest,
    TestSendTemplateRequest,
    ImportContactsRequest,
    CreateBroadcastRequest,
)
from backend.bot.auth import (
    get_current_client_id,
    resolve_client_from_token,
    require_admin,
    Pagination,
    page_response,
    assert_owned,
)
from backend.bot.services import (
    resolve_message_media,
    save_full_setup,
    create_dev_google_connection,
    complete_google_oauth,
    complete_embedded_signup,
    register_whatsapp_account,
    process_test_webhook,
    get_run_debug_data,
    route_whatsapp_webhook_payload,
    verify_whatsapp_webhook,
    get_inbox_conversations,
    get_conversation_messages,
    close_conversation,
    reopen_conversation,
    delete_conversation,
    stream_client_events,
    cancel_conversation_run,
    mark_conversation_viewed,
    update_contact,
    send_agent_message,
    send_agent_audio_message,
    get_ai_usage_summary,
    # clients / users / accounts
    create_client,
    get_client_or_404,
    list_clients_service,
    update_client,
    deactivate_client,
    create_user,
    get_user_or_404,
    list_client_users,
    update_user,
    create_whatsapp_account,
    list_client_whatsapp_accounts,
    get_whatsapp_account_detail,
    update_whatsapp_account,
    disconnect_whatsapp_account,
    verify_whatsapp_account,
    subscribe_whatsapp_account_webhook,
    # workflows / nodes
    create_workflow,
    list_client_workflows,
    get_workflow_detail,
    update_workflow,
    delete_workflow,
    validate_workflow,
    publish_workflow,
    unpublish_workflow,
    set_default_workflow,
    duplicate_workflow,
    list_workflow_nodes,
    get_workflow_node_detail,
    add_workflow_node,
    update_workflow_node,
    delete_workflow_node,
    update_workflow_connections,
    workflow_connections_view,
    # runs
    list_runs_service,
    list_leads_service,
    start_call_review,
    list_call_reviews_service,
    get_run_detail,
    cancel_workflow_run_by_id,
    assert_client_id_matches_path,
    login_client,
    get_auth_client,
    get_owned_whatsapp_account_by_phone_number_id,
    get_or_create_long_live_token,
    submit_template,
    list_templates_service,
    get_template_service,
    sync_templates_from_meta,
    delete_template_service,
    send_test_template,
    list_contacts_service,
    import_contacts_service,
    set_contact_opt_out_service,
    create_broadcast,
    preview_broadcast,
    list_broadcasts_service,
    get_broadcast_service,
    set_broadcast_state,
    list_broadcast_recipients_service,
    # CRM additions
    update_conversation_disposition,
    list_conversation_notes,
    add_conversation_note,
    delete_conversation_note,
    update_contact_service,
    get_lead_schema,
)
from backend.bot.models import (
    UpdateDispositionRequest,
    CreateNoteRequest,
    UpdateContactFieldsRequest,
    StartCallReviewRequest,
)

from backend.bot.whatsapp_service import (
    send_whatsapp_text_message,
    send_whatsapp_button_message,
    send_whatsapp_list_message,
)

router = APIRouter()


@router.get("/")
def home():
    return {
        "message": "WATI-like Workflow Bot Backend is running."
    }


# =====================================================================
# Auth APIs
# =====================================================================

@router.post("/auth/login")
def auth_login(request: LoginRequest):
    return login_client(request)


@router.get("/auth/me")
def auth_me(client_id: str = Depends(get_current_client_id)):
    return {"client": get_auth_client(client_id)}


@router.get("/usage")
def ai_usage(client_id: str = Depends(get_current_client_id)):
    """This client's ai_conversation token usage + estimated cost (own data only)."""
    return get_ai_usage_summary(client_id)


@router.get("/leads/schema")
def leads_schema(
    workflow_id: str | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    """CRM: this client's lead-field schema (labels / types / options), derived
    from its published workflow (sheet column headers, questions, AI fields)."""
    return get_lead_schema(client_id, workflow_id)


@router.get("/leads")
def leads_list(
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    """CRM: the lead feed, newest first, one row per arrival (workflow run;
    a number that comes back another day is a new lead). Conversations with
    an inbound message but no run are one row each. `q` matches name/phone,
    `source` is whatsapp|ctwa."""
    total, items = list_leads_service(client_id, q, source, pagination.limit, pagination.offset)
    return page_response(total, pagination, "leads", items)


# =====================================================================
# Client APIs
# =====================================================================

@router.post("/clients")
def clients_create(request: CreateClientRequest):
    return create_client(request)


@router.get("/clients")
def clients_list(
    status: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    client = get_auth_client(client_id)
    return page_response(1, pagination, "clients", [client])


@router.get("/clients/{client_id}")
def clients_get(
    client_id: str,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return get_auth_client(client_id)


@router.patch("/clients/{client_id}")
def clients_update(
    client_id: str,
    request: UpdateClientRequest,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return update_client(client_id, request)


@router.delete("/clients/{client_id}")
def clients_delete(
    client_id: str,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return deactivate_client(client_id)


@router.post("/clients/{client_id}/long-live-token")
def clients_long_live_token(
    client_id: str,
    _admin: None = Depends(require_admin),
):
    return get_or_create_long_live_token(client_id)


@router.get("/admin/clients")
def admin_clients(_admin: None = Depends(require_admin)):
    """Ripplica-only: every client with its CRM feature switches."""
    return {"clients": admin_list_clients()}


@router.patch("/admin/clients/{client_id}/features")
def admin_client_features(
    client_id: str,
    request: SetClientFeaturesRequest,
    _admin: None = Depends(require_admin),
):
    """Ripplica-only: merge feature switches into a client, e.g.
    {"features": {"campaigns": false}}. Not reachable with a client token."""
    return admin_set_client_features(client_id, request)


# =====================================================================
# User APIs
# =====================================================================

@router.post("/clients/{client_id}/users")
def users_create(
    client_id: str,
    request: CreateUserRequest,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return create_user(client_id, request)


@router.get("/clients/{client_id}/users")
def users_list(
    client_id: str,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return list_client_users(client_id)


@router.get("/users/{user_id}")
def users_get(
    user_id: str,
    client_id: str = Depends(get_current_client_id),
):
    user = get_user_or_404(user_id)
    assert_owned(user, client_id, "User")
    return user


@router.patch("/users/{user_id}")
def users_update(
    user_id: str,
    request: UpdateUserRequest,
    client_id: str = Depends(get_current_client_id),
):
    return update_user(user_id, request, client_id)


# =====================================================================
# WhatsApp Account APIs
# =====================================================================

@router.post("/clients/{client_id}/whatsapp-accounts")
def accounts_create(
    client_id: str,
    request: CreateWhatsAppAccountRequest,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return create_whatsapp_account(client_id, request)


@router.get("/clients/{client_id}/whatsapp-accounts")
def accounts_list(
    client_id: str,
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    return list_client_whatsapp_accounts(client_id)


@router.get("/whatsapp-accounts/{account_id}")
def accounts_get(
    account_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_whatsapp_account_detail(account_id, client_id)


@router.patch("/whatsapp-accounts/{account_id}")
def accounts_update(
    account_id: str,
    request: UpdateWhatsAppAccountRequest,
    client_id: str = Depends(get_current_client_id),
):
    return update_whatsapp_account(account_id, request, client_id)


@router.delete("/whatsapp-accounts/{account_id}")
def accounts_delete(
    account_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return disconnect_whatsapp_account(account_id, client_id)


@router.post("/whatsapp-accounts/{account_id}/verify")
def accounts_verify(
    account_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return verify_whatsapp_account(account_id, client_id)


@router.post("/whatsapp-accounts/{account_id}/subscribe-webhook")
def accounts_subscribe_webhook(
    account_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return subscribe_whatsapp_account_webhook(account_id, client_id)


# =====================================================================
# Workflow APIs (scoped to the authenticated client)
# =====================================================================

@router.post("/workflows")
def workflows_create(
    request: CreateWorkflowRequest,
    client_id: str = Depends(get_current_client_id),
):
    return create_workflow(client_id, request)


@router.get("/clients/{client_id}/workflows")
def workflows_list(
    client_id: str,
    whatsapp_account_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    current_client_id: str = Depends(get_current_client_id),
):
    assert_client_id_matches_path(client_id, current_client_id)
    total, workflows = list_client_workflows(
        client_id, whatsapp_account_id, status, pagination.limit, pagination.offset
    )
    return page_response(total, pagination, "workflows", workflows)


@router.get("/workflows/{workflow_id:path}/nodes/{node_id}")
def workflow_node_get(
    workflow_id: str,
    node_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_workflow_node_detail(workflow_id, node_id, client_id)


@router.patch("/workflows/{workflow_id:path}/nodes/{node_id}")
def workflow_node_update(
    workflow_id: str,
    node_id: str,
    request: UpdateWorkflowNodeRequest,
    expected_version: int | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    return update_workflow_node(workflow_id, node_id, client_id, request, expected_version)


@router.delete("/workflows/{workflow_id:path}/nodes/{node_id}")
def workflow_node_delete(
    workflow_id: str,
    node_id: str,
    new_first_node_id: str | None = Query(default=None),
    expected_version: int | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    return delete_workflow_node(workflow_id, node_id, client_id, new_first_node_id, expected_version)


@router.get("/workflows/{workflow_id:path}/nodes")
def workflow_nodes_list(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return list_workflow_nodes(workflow_id, client_id)


@router.post("/workflows/{workflow_id:path}/nodes")
def workflow_node_add(
    workflow_id: str,
    request: WorkflowNodeInput,
    expected_version: int | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    return add_workflow_node(workflow_id, client_id, request, expected_version)


@router.get("/workflows/{workflow_id:path}/connections")
def workflow_connections_get(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return workflow_connections_view(workflow_id, client_id)


@router.post("/workflows/{workflow_id:path}/connections")
def workflow_connections_update(
    workflow_id: str,
    request: UpdateConnectionsRequest,
    expected_version: int | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    return update_workflow_connections(workflow_id, client_id, request.changes, expected_version)


@router.post("/workflows/{workflow_id:path}/validate")
def workflow_validate(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return validate_workflow(workflow_id, client_id)


@router.post("/workflows/{workflow_id:path}/publish")
def workflow_publish(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return publish_workflow(workflow_id, client_id)


@router.post("/workflows/{workflow_id:path}/unpublish")
def workflow_unpublish(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return unpublish_workflow(workflow_id, client_id)


@router.post("/workflows/{workflow_id:path}/set-default")
def workflow_set_default(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    """Publish this workflow (if it isn't already) and make it the account's
    default, clearing any workflow currently marked default on the same
    WhatsApp account. Idempotent: re-calling on the current default is a no-op
    swap. Returns 400 if the workflow can't be published, 404 if not owned."""
    return set_default_workflow(workflow_id, client_id)


@router.post("/workflows/{workflow_id:path}/duplicate")
def workflow_duplicate(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return duplicate_workflow(workflow_id, client_id)


@router.get("/workflows/{workflow_id:path}")
def workflow_get(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_workflow_detail(workflow_id, client_id)


@router.patch("/workflows/{workflow_id:path}")
def workflow_update(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    expected_version: int | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    return update_workflow(workflow_id, client_id, request, expected_version)


@router.delete("/workflows/{workflow_id:path}")
def workflow_delete(
    workflow_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return delete_workflow(workflow_id, client_id)


# =====================================================================
# Runtime APIs
# =====================================================================

# Registered before /runs/{run_id:path} so the literal path wins the match.
@router.get("/runs/debug")
def debug_run(
    workflow_run_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_run_detail(workflow_run_id, client_id)


@router.get("/runs")
def runs_list(
    whatsapp_account_id: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    contact_phone: str | None = Query(default=None),
    status: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    total, runs = list_runs_service(
        client_id,
        whatsapp_account_id,
        workflow_id,
        contact_phone,
        status,
        pagination.limit,
        pagination.offset,
    )
    return page_response(total, pagination, "runs", runs)


@router.get("/runs/{run_id:path}")
def runs_get(
    run_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_run_detail(run_id, client_id)


@router.post("/runs/{run_id:path}/cancel")
def runs_cancel(
    run_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return cancel_workflow_run_by_id(run_id, client_id)


# =====================================================================
# Dev / setup (unscoped) + webhook
# =====================================================================

@router.post("/dev/setup")
def dev_setup(
    request: FullSetupRequest,
    client_id: str = Depends(get_current_client_id),
):
    return save_full_setup(request, client_id)


@router.post("/dev/google-connections")
def dev_create_google_connection(
    request: DevGoogleConnectionRequest,
    client_id: str = Depends(get_current_client_id),
):
    return create_dev_google_connection(request.connection, client_id)


# Google OAuth callback (browser GET, reached via Google's redirect). Protected
# by the signed `state`, not the admin header. No /start endpoint: the consent
# URL is handed to the operator in the workflow-save `pending_google_auth`.
@router.get("/google/oauth/callback", response_class=HTMLResponse)
def google_oauth_callback(code: str = Query(...), state: str = Query(...)):
    try:
        connection = complete_google_oauth(code=code, state=state)
    except Exception as error:
        return HTMLResponse(
            f"<h3>Google connection failed</h3><p>{str(error)}</p>",
            status_code=400,
        )
    return HTMLResponse(
        f"<h3>&#9989; Google account connected</h3>"
        f"<p>Connection <b>{connection.id}</b>"
        + (f" ({connection.google_email})" if connection.google_email else "")
        + "</p><p>You can close this tab and return to the admin console.</p>"
    )


# Meta Embedded Signup (admin-gated). The FB JS SDK popup runs in the admin
# console; the browser posts the code + WABA/phone ids here.
@router.post("/whatsapp/embedded-signup/complete")
def embedded_signup_complete(
    request: EmbeddedSignupCompleteRequest,
    client_id: str = Depends(get_current_client_id),
):
    return complete_embedded_signup(request, client_id)


@router.post("/whatsapp-accounts/{account_id}/register")
def whatsapp_account_register(
    account_id: str,
    request: RegisterPhoneNumberRequest,
    client_id: str = Depends(get_current_client_id),
):
    return register_whatsapp_account(account_id, request, client_id)


@router.post("/webhook/test")
def test_webhook(
    request: TestWebhookRequest,
    client_id: str = Depends(get_current_client_id),
):
    return process_test_webhook(request, client_id)


@router.get("/webhook/whatsapp")
def whatsapp_webhook_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    challenge = verify_whatsapp_webhook(
        mode=hub_mode,
        verify_token=hub_verify_token,
        challenge=hub_challenge,
    )

    return PlainTextResponse(content=challenge)


@router.post("/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request):
    payload = await request.json()

    print("WHATSAPP WEBHOOK PAYLOAD:", flush=True)
    print(payload, flush=True)

    # Always answer 200 to Meta. Any non-2xx makes Meta retry the same
    # webhook for hours, reprocessing the same message in a loop.
    try:
        result = route_whatsapp_webhook_payload(payload)
    except Exception as error:
        traceback.print_exc()
        result = {
            "error": True,
            "reason": str(error),
        }

    print("WHATSAPP WEBHOOK RESULT:", flush=True)
    print(result, flush=True)

    return {
        "status of request": "received",
        "result": result,
    }


# =====================================================================
# Inbox / conversation APIs (scoped to the authenticated client)
# =====================================================================

@router.get("/conversations")
def list_inbox_conversations(
    status: str | None = Query(default=None),
    whatsapp_account_id: str | None = Query(default=None),
    view: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    """`view` picks the CRM inbox tab: 'inbox' (All / Unread) hides chats waiting
    on a reply to a template, 'template' returns only those. Omitted = no filter.
    `counts` carries both tab totals so a badge is right before the tab is paged."""
    total, conversations, counts = get_inbox_conversations(
        client_id=client_id,
        status=status,
        whatsapp_account_id=whatsapp_account_id,
        limit=pagination.limit,
        offset=pagination.offset,
        view=view,
    )
    return {**page_response(total, pagination, "conversations", conversations), "counts": counts}


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(
    conversation_id: str,
    limit: int = Query(default=30),
    before: str | None = Query(default=None),
    client_id: str = Depends(get_current_client_id),
):
    return get_conversation_messages(conversation_id, client_id, limit, before)


@router.get("/events")
async def inbox_events(request: Request, token: str = Query(...)):
    """Real-time inbox stream (Server-Sent Events). The browser's EventSource
    can't send an Authorization header, so the client JWT arrives as ?token=
    (same as the media proxy). Pushes conversation/message changes so the inbox
    doesn't have to poll.

    async def (not sync) so Starlette does not park this on the default thread
    pool — SSE already uses a dedicated executor for Mongo watch polling.
    """
    client_id = resolve_client_from_token(token)
    return StreamingResponse(
        stream_client_events(client_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{conversation_id}/close")
def conversation_close(
    conversation_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return close_conversation(conversation_id, client_id)


@router.post("/conversations/{conversation_id}/open")
def conversation_open(
    conversation_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return reopen_conversation(conversation_id, client_id)


@router.delete("/conversations/{conversation_id}")
def conversation_delete(
    conversation_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return delete_conversation(conversation_id, client_id)


@router.post("/conversations/{conversation_id}/cancel-run")
def conversation_cancel_run(
    conversation_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return cancel_conversation_run(conversation_id, client_id)


@router.post("/conversations/{conversation_id}/mark-viewed")
def conversation_mark_viewed(
    conversation_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return mark_conversation_viewed(conversation_id, client_id)


@router.patch("/conversations/{conversation_id}/contact")
def conversation_update_contact(
    conversation_id: str,
    request: UpdateContactRequest,
    client_id: str = Depends(get_current_client_id),
):
    return update_contact(conversation_id, client_id, request)


# ---- CRM additions (the Ripply inbox never calls these) ----

@router.patch("/conversations/{conversation_id}/disposition")
def conversation_update_disposition(
    conversation_id: str,
    request: UpdateDispositionRequest,
    client_id: str = Depends(get_current_client_id),
):
    """Agent-set lead outcome (disposition + remark) on a conversation."""
    return update_conversation_disposition(conversation_id, client_id, request)


@router.get("/conversations/{conversation_id}/notes")
def conversation_notes_list(
    conversation_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return list_conversation_notes(conversation_id, client_id)


@router.post("/conversations/{conversation_id}/notes")
def conversation_notes_add(
    conversation_id: str,
    request: CreateNoteRequest,
    client_id: str = Depends(get_current_client_id),
):
    return add_conversation_note(conversation_id, client_id, request)


@router.delete("/conversations/{conversation_id}/notes/{note_id}")
def conversation_notes_delete(
    conversation_id: str,
    note_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return delete_conversation_note(conversation_id, note_id, client_id)


@router.post("/conversations/{conversation_id}/send")
def conversation_send_agent_message(
    conversation_id: str,
    request: AgentSendRequest,
    client_id: str = Depends(get_current_client_id),
):
    return send_agent_message(conversation_id, client_id, request.text)


@router.post("/conversations/{conversation_id}/send-audio")
async def conversation_send_agent_audio(
    conversation_id: str,
    file: UploadFile = File(...),
    client_id: str = Depends(get_current_client_id),
):
    """Send a voice note from the inbox: accepts the browser's recording (WebM/
    Opus, MP4, ...), transcoded server-side to OGG/Opus before it goes to Meta."""
    audio_bytes = await file.read()
    return send_agent_audio_message(conversation_id, client_id, audio_bytes)


# =====================================================================
# Dev-only manual WhatsApp senders (testing)
# =====================================================================

@router.post("/dev/whatsapp/send-text")
def dev_send_whatsapp_text(
    request: SendWhatsAppTestRequest,
    client_id: str = Depends(get_current_client_id),
):
    account = get_owned_whatsapp_account_by_phone_number_id(
        request.phone_number_id, client_id
    )
    result = send_whatsapp_text_message(
        phone_number_id=account.phone_number_id,
        to_phone=request.to_phone,
        text=request.text,
        access_token=account.access_token,
    )

    return {
        "status": "sent",
        "meta_response": result,
    }


@router.post("/dev/whatsapp/send-buttons")
def dev_send_whatsapp_buttons(
    request: SendWhatsAppButtonTestRequest,
    client_id: str = Depends(get_current_client_id),
):
    account = get_owned_whatsapp_account_by_phone_number_id(
        request.phone_number_id, client_id
    )
    result = send_whatsapp_button_message(
        phone_number_id=account.phone_number_id,
        to_phone=request.to_phone,
        body_text=request.text,
        access_token=account.access_token,
        buttons=[
            {
                "id": "track_order",
                "title": "Track Order",
            },
            {
                "id": "return_item",
                "title": "Return Item",
            },
        ],
    )

    return {
        "status": "sent",
        "meta_response": result,
    }


@router.post("/dev/whatsapp/send-list")
def dev_send_whatsapp_list(
    request: SendWhatsAppListTestRequest,
    client_id: str = Depends(get_current_client_id),
):
    account = get_owned_whatsapp_account_by_phone_number_id(
        request.phone_number_id, client_id
    )
    result = send_whatsapp_list_message(
        phone_number_id=account.phone_number_id,
        to_phone=request.to_phone,
        body_text=request.body_text,
        list_config=request.list_config,
        access_token=account.access_token,
    )

    return {
        "status": "sent",
        "meta_response": result,
    }


@router.post("/webhooks/fasterq")
async def fasterq_webhook(request: Request, background: BackgroundTasks,
                          authorization: str | None = Header(default=None)):
    """FasterQ call webhook (call ended / recording ready). Authenticated by the
    API key FasterQ sends in `Authorization`. Always 2xx once authenticated so
    FasterQ never retry-loops; the recording copy runs after the response."""
    verify_fasterq_secret(authorization)
    try:
        payload = await request.json()
    except Exception:
        return {"ok": False, "reason": "invalid json"}
    try:
        result = ingest_fasterq_call(payload if isinstance(payload, dict) else {})
    except Exception as error:
        traceback.print_exc()
        return {"ok": False, "reason": str(error)}
    if result.get("download"):
        background.add_task(fetch_call_recording, result["call_id"])
    return {"ok": True, **{k: v for k, v in result.items() if k != "download"}}


@router.get("/calls")
def calls_list(
    direction: str | None = Query(default=None),
    answered: bool | None = Query(default=None),
    phone: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    total, calls = list_calls_service(client_id, direction, answered, phone, conversation_id,
                                      pagination.limit, pagination.offset)
    return page_response(total, pagination, "calls", calls)


@router.get("/calls/reviews")
def call_reviews_list(client_id: str = Depends(get_current_client_id)):
    """Every AI call review this clinic owns, so the Calls page can show a score
    per patient without a request per row."""
    return {"reviews": list_call_reviews_service(client_id)}


@router.post("/calls/reviews", status_code=202)
def call_review_start(
    request: StartCallReviewRequest,
    client_id: str = Depends(get_current_client_id),
):
    """Queue an AI review of one patient's calls (the button on the Calls page).
    Returns straight away; the result arrives over SSE as `call_review`."""
    return start_call_review(client_id, request.phone)


@router.get("/calls/{call_id}/recording")
def call_recording(call_id: str, token: str = Query(...)):
    """Redirects the <audio> element to a short-lived signed URL of the stored
    recording (token via ?token= like /media, since <audio> cannot set headers)."""
    client_id = resolve_client_from_token(token)
    return RedirectResponse(url=call_recording_url(call_id, client_id))


@router.get("/media/{message_id:path}")
def get_message_media(message_id: str, token: str = Query(...)):
    """Inbox media proxy. Streams a stored image/PDF from private GCS (or
    redirects to a literal external link) for a client-owned message. Takes the
    JWT via ?token= (not the Authorization header) because an <img> tag cannot
    set headers. Images are served inline; documents as a download."""
    client_id = resolve_client_from_token(token)

    result = resolve_message_media(message_id, client_id)

    if result["kind"] == "redirect":
        return RedirectResponse(url=result["url"])

    filename = result.get("filename")
    if result["media_type"] in ("image", "audio"):
        disposition = "inline"
    elif filename:
        disposition = f'attachment; filename="{filename}"'
    else:
        disposition = "attachment"

    return Response(
        content=result["data"],
        media_type=result["content_type"],
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, max-age=300",
        },
    )


# =====================================================================
# Message templates
# =====================================================================

@router.post("/whatsapp-accounts/{account_id}/templates")
def templates_create(
    account_id: str,
    request: CreateTemplateRequest,
    client_id: str = Depends(get_current_client_id),
):
    return submit_template(account_id, client_id, request)


@router.get("/whatsapp-accounts/{account_id}/templates")
def templates_list(
    account_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return {"templates": list_templates_service(account_id, client_id)}


@router.post("/whatsapp-accounts/{account_id}/templates/sync")
def templates_sync(
    account_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return sync_templates_from_meta(account_id, client_id)


@router.get("/whatsapp-accounts/{account_id}/templates/{template_id}")
def templates_get(
    account_id: str,
    template_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_template_service(account_id, template_id, client_id)


@router.delete("/whatsapp-accounts/{account_id}/templates/{template_id}")
def templates_delete(
    account_id: str,
    template_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return delete_template_service(account_id, template_id, client_id)


@router.post("/whatsapp-accounts/{account_id}/templates/{template_id}/test-send")
def templates_test_send(
    account_id: str,
    template_id: str,
    request: TestSendTemplateRequest,
    client_id: str = Depends(get_current_client_id),
):
    return send_test_template(account_id, template_id, client_id, request)


# =====================================================================
# Contacts
# =====================================================================

@router.get("/whatsapp-accounts/{account_id}/contacts")
def contacts_list(
    account_id: str,
    tag: str | None = Query(default=None),
    opted_out: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    total, contacts = list_contacts_service(
        account_id, client_id, tag=tag, opted_out=opted_out, search=search,
        limit=pagination.limit, offset=pagination.offset,
    )
    return page_response(total, pagination, "contacts", contacts)


@router.post("/whatsapp-accounts/{account_id}/contacts/import")
def contacts_import(
    account_id: str,
    request: ImportContactsRequest,
    client_id: str = Depends(get_current_client_id),
):
    return import_contacts_service(account_id, client_id, request)


@router.post("/whatsapp-accounts/{account_id}/contacts/{contact_id}/opt-out")
def contacts_opt_out(
    account_id: str,
    contact_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return set_contact_opt_out_service(account_id, contact_id, client_id, True)


@router.post("/whatsapp-accounts/{account_id}/contacts/{contact_id}/opt-in")
def contacts_opt_in(
    account_id: str,
    contact_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return set_contact_opt_out_service(account_id, contact_id, client_id, False)


@router.patch("/whatsapp-accounts/{account_id}/contacts/{contact_id}")
def contacts_update(
    account_id: str,
    contact_id: str,
    request: UpdateContactFieldsRequest,
    client_id: str = Depends(get_current_client_id),
):
    """CRM: edit a contact's name / tags (tags replace the list)."""
    return update_contact_service(account_id, contact_id, client_id, request)


# =====================================================================
# Broadcasts
# =====================================================================

@router.post("/whatsapp-accounts/{account_id}/broadcasts/preview")
def broadcasts_preview(
    account_id: str,
    request: CreateBroadcastRequest,
    client_id: str = Depends(get_current_client_id),
):
    return preview_broadcast(account_id, client_id, request)


@router.post("/whatsapp-accounts/{account_id}/broadcasts")
def broadcasts_create(
    account_id: str,
    request: CreateBroadcastRequest,
    client_id: str = Depends(get_current_client_id),
):
    return create_broadcast(account_id, client_id, request)


@router.get("/whatsapp-accounts/{account_id}/broadcasts")
def broadcasts_list(
    account_id: str,
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    total, items = list_broadcasts_service(
        account_id, client_id, limit=pagination.limit, offset=pagination.offset
    )
    return page_response(total, pagination, "broadcasts", items)


@router.get("/broadcasts/{broadcast_id}")
def broadcasts_get(
    broadcast_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return get_broadcast_service(broadcast_id, client_id)


@router.post("/broadcasts/{broadcast_id}/pause")
def broadcasts_pause(
    broadcast_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return set_broadcast_state(broadcast_id, client_id, "pause")


@router.post("/broadcasts/{broadcast_id}/resume")
def broadcasts_resume(
    broadcast_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return set_broadcast_state(broadcast_id, client_id, "resume")


@router.post("/broadcasts/{broadcast_id}/cancel")
def broadcasts_cancel(
    broadcast_id: str,
    client_id: str = Depends(get_current_client_id),
):
    return set_broadcast_state(broadcast_id, client_id, "cancel")


@router.get("/broadcasts/{broadcast_id}/recipients")
def broadcasts_recipients(
    broadcast_id: str,
    pagination: Pagination = Depends(),
    client_id: str = Depends(get_current_client_id),
):
    total, items = list_broadcast_recipients_service(
        broadcast_id, client_id, limit=pagination.limit, offset=pagination.offset
    )
    return page_response(total, pagination, "recipients", items)
