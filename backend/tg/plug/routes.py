from __future__ import annotations

from datetime import timedelta, datetime, timezone
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm

from backend.tg.auth import get_password_hash, verify_password
from backend.tg.config import settings
from backend.tg.plug.auth import create_plug_token, get_current_creator
from backend.tg.database import (
    save_instagram_app_config,
    get_instagram_app_config,
    save_instagram_oauth_state,
    get_instagram_connection,
)
from backend.tg.plug.database import (
    fetch_creator,
    insert_creator,
    search_profile_error,
    insert_topic_run,
    latest_topic_run,
    replace_topic_run,
    update_creator,
    list_todos,
    insert_todo,
    update_todo,
    delete_todo,
    reorder_todos,
)
from backend.tg.plug import openai as plug_openai
from backend.tg.plug import schemas
from backend.tg.plug.instagram_analytics import (
    MAX_ANALYTICS_DAYS,
    clamp_analytics_window,
    fetch_plug_analytics,
)

router = APIRouter(prefix="/plug", tags=["plug"])


def _creator_out(doc: dict) -> schemas.PlugCreatorOut:
    return schemas.PlugCreatorOut(**{k: doc.get(k) for k in schemas.PlugCreatorOut.model_fields})


@router.get("/")
def plug_root():
    return {
        "product": "plug",
        "audience": "content creators",
        "login": "one account = one creator",
    }


@router.post("/auth.register", response_model=schemas.PlugToken, status_code=status.HTTP_201_CREATED)
def register(body: schemas.PlugRegister):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if fetch_creator(username):
        raise HTTPException(status_code=400, detail="Username already registered")
    insert_creator(
        {
            "username": username,
            "hashed_password": get_password_hash(body.password),
            "is_active": True,
        }
    )
    token = create_plug_token(
        username,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth.login", response_model=schemas.PlugToken)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    creator = fetch_creator(form_data.username, include_password=True)
    if not creator or not verify_password(
        form_data.password, creator.get("hashed_password") or ""
    ):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    if not creator.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is disabled")
    token = create_plug_token(
        creator["username"],
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth.me", response_model=schemas.PlugCreatorOut)
def me(current: dict = Depends(get_current_creator)):
    fresh = fetch_creator(current["username"]) or current
    return _creator_out(fresh)


@router.post("/profile.update", response_model=schemas.PlugCreatorOut)
def update_profile(
    body: schemas.PlugProfileUpdate,
    current: dict = Depends(get_current_creator),
):
    patch = body.model_dump(exclude_unset=True)
    if "example_topics" in patch:
        patch["example_topics"] = [
            str(t).strip() for t in (patch["example_topics"] or []) if str(t).strip()
        ]
    if "example_scripts" in patch:
        patch["example_scripts"] = [
            str(s).strip() for s in (patch["example_scripts"] or []) if str(s).strip()
        ]
    if "reference_videos" in patch:
        patch["reference_videos"] = [
            str(v).strip() for v in (patch["reference_videos"] or []) if str(v).strip()
        ]
    for key in ("name", "website", "instagram", "niche", "niche_details", "language"):
        if key in patch and patch[key] is not None:
            patch[key] = str(patch[key]).strip()
    updated = update_creator(current["username"], **patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Creator not found")
    return _creator_out(updated)


@router.post("/instagram.config.save", response_model=schemas.PlugInstagramConfigOut)
def save_instagram_config(
    body: schemas.PlugInstagramConfigSave,
    current: dict = Depends(get_current_creator),
):
    save_instagram_app_config(
        current["username"],
        app_id=body.app_id,
        app_secret=body.app_secret,
    )
    return {
        "app_id": body.app_id, 
        "app_secret": body.app_secret,
        "redirect_uri": getattr(settings, "PLUG_INSTA_REDIRECT_URI", settings.INSTAGRAM_REDIRECT_URI)
    }


@router.post("/instagram.config.get", response_model=schemas.PlugInstagramConfigOut)
def get_instagram_config(current: dict = Depends(get_current_creator)):
    config = get_instagram_app_config(current["username"]) or {}
    return {
        "app_id": config.get("app_id") or "",
        "app_secret": config.get("app_secret") or "",
        "redirect_uri": getattr(settings, "PLUG_INSTA_REDIRECT_URI", settings.INSTAGRAM_REDIRECT_URI)
    }


@router.post("/instagram.connect-url", response_model=schemas.PlugInstagramConnectUrlResponse)
def instagram_connect_url(current: dict = Depends(get_current_creator)):
    config = get_instagram_app_config(current["username"]) or {}
    if not config.get("app_id") or not config.get("app_secret"):
        raise HTTPException(status_code=400, detail="Save Instagram App ID and App Secret first.")

    state = str(uuid4())
    save_instagram_oauth_state(
        state,
        {
            "client_id": current["username"],
            "username": current["username"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_context": "plug",
        },
    )
    params = {
        "client_id": config["app_id"],
        "redirect_uri": settings.PLUG_INSTA_REDIRECT_URI,
        "state": state,
        "scope": settings.INSTAGRAM_OAUTH_SCOPES,
        "response_type": "code",
        "force_reauth": "true",
    }
    url = f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"
    return schemas.PlugInstagramConnectUrlResponse(authorization_url=url, state=state)


@router.post("/instagram.disconnect", response_model=schemas.PlugCreatorOut)
def disconnect_instagram(current: dict = Depends(get_current_creator)):
    updated = update_creator(current["username"], instagram_connected=False)
    if not updated:
        raise HTTPException(status_code=404, detail="Creator not found")
    return _creator_out(updated)


@router.post("/analytics.get")
async def analytics(
    body: dict | None = Body(default=None),
    current: dict = Depends(get_current_creator),
):
    fresh = fetch_creator(current["username"]) or current
    connected = bool(fresh.get("instagram_connected"))

    # Accept since/until as YYYY-MM-DD, or fall back to days (default 7)
    now = datetime.now(timezone.utc)
    try:
        if body and body.get("since") and body.get("until"):
            since_dt = datetime.strptime(body["since"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until_dt = datetime.strptime(body["until"], "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
            since_dt, until_dt = clamp_analytics_window(since_dt, until_dt)
        else:
            days = 7
            if body and isinstance(body.get("days"), (int, float)):
                days = max(2, min(MAX_ANALYTICS_DAYS, int(body["days"])))
            since_dt = now - timedelta(days=days)
            until_dt = now
            since_dt, until_dt = clamp_analytics_window(since_dt, until_dt)
    except (ValueError, TypeError):
        since_dt = now - timedelta(days=7)
        until_dt = now

    metrics = None
    time_series = None
    views_by_follow_type = None
    views_by_content_type = None
    interactions_by_content_type = None
    reels = []
    reel_summary = None
    if connected:
        conn = get_instagram_connection(current["username"])
        if conn and conn.get("access_token") and conn.get("instagram_user_id"):
            try:
                payload = await fetch_plug_analytics(
                    ig_id=conn["instagram_user_id"],
                    token=conn["access_token"],
                    since_dt=since_dt,
                    until_dt=until_dt,
                )
                metrics = payload.get("metrics")
                time_series = payload.get("time_series")
                views_by_follow_type = payload.get("views_by_follow_type")
                views_by_content_type = payload.get("views_by_content_type")
                interactions_by_content_type = payload.get("interactions_by_content_type")
                reels = payload.get("reels") or []
                reel_summary = payload.get("reel_summary")
            except Exception as e:
                print(f"[Analytics] Error calling Meta: {e}", flush=True)

        if not metrics:
            metrics = {
                "reach": 0, "accounts_engaged": 0, "total_interactions": 0,
                "views": 0, "saves": 0, "likes": 0, "comments": 0, "shares": 0,
                "profile_views": 0, "website_clicks": 0, "follows_and_unfollows": 0,
                "profile_links_taps": 0,
            }

    return {
        "instagram_connected": connected,
        "instagram": fresh.get("instagram") or "",
        "placeholder": not bool(metrics) and connected,
        "since": since_dt.strftime("%Y-%m-%d"),
        "until": until_dt.strftime("%Y-%m-%d"),
        "message": (
            "Instagram insights will show here after the connection is live."
            if connected
            else "Connect Instagram to unlock analytics."
        ),
        "metrics": metrics,
        "time_series": time_series,
        "views_by_follow_type": views_by_follow_type,
        "views_by_content_type": views_by_content_type,
        "interactions_by_content_type": interactions_by_content_type,
        "reels": reels,
        "reel_summary": reel_summary,
    }


def _require_profile_for_search(creator: dict) -> None:
    detail = search_profile_error(creator)
    if detail:
        raise HTTPException(status_code=400, detail=detail)


@router.post("/topics.search")
def topics_search(
    body: schemas.PlugTopicSearch,
    current: dict = Depends(get_current_creator),
):
    creator = fetch_creator(current["username"]) or current
    _require_profile_for_search(creator)
    language = (body.language or creator.get("language") or "english").strip() or "english"
    try:
        result = plug_openai.search_topics(
            creator=creator,
            language=language,
            prompt=body.prompt or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    update_creator(creator["username"], language=language)
    run = insert_topic_run(
        {
            "id": str(uuid4()),
            "username": creator["username"],
            "language": result["language"],
            "prompt": result.get("prompt") or "",
            "topics": result["topics"],
            "sources": result.get("sources") or [],
        }
    )
    return run


@router.post("/topics.list")
def topics_list(current: dict = Depends(get_current_creator)):
    run = latest_topic_run(current["username"])
    return {"run": run}


@router.post("/topics.script.redo")
def topics_script_redo(
    body: schemas.PlugScriptRedo,
    current: dict = Depends(get_current_creator),
):
    creator = fetch_creator(current["username"]) or current
    run = latest_topic_run(creator["username"])
    if not run:
        raise HTTPException(status_code=404, detail="No topics yet. Search first.")
    topics = list(run.get("topics") or [])
    idx = next((i for i, t in enumerate(topics) if t.get("id") == body.topic_id), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Topic not found")
    language = (
        (body.language or run.get("language") or creator.get("language") or "english").strip()
        or "english"
    )
    try:
        rewritten = plug_openai.redo_script(
            creator=creator,
            topic=topics[idx],
            language=language,
            prompt=body.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    topics[idx] = {
        **topics[idx],
        "script": rewritten["script"],
        "hook_used": rewritten.get("hook_used") or topics[idx].get("hook_used") or "",
        "cta_line": rewritten.get("cta_line") or topics[idx].get("cta_line") or "",
    }
    saved = replace_topic_run({**run, "topics": topics})
    return {"run": saved, "topic": topics[idx]}


@router.post("/topics.script.rate")
def topics_script_rate(
    body: schemas.PlugScriptRate,
    current: dict = Depends(get_current_creator),
):
    rating = (body.rating or "").strip().lower() or None
    if rating not in (None, "like", "dislike"):
        raise HTTPException(status_code=400, detail="rating must be like, dislike, or empty")
    run = latest_topic_run(current["username"])
    if not run:
        raise HTTPException(status_code=404, detail="No topics yet. Search first.")
    topics = list(run.get("topics") or [])
    idx = next((i for i, t in enumerate(topics) if t.get("id") == body.topic_id), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Topic not found")
    topics[idx] = {**topics[idx], "rating": rating}
    saved = replace_topic_run({**run, "topics": topics})
    return {"run": saved, "topic": topics[idx]}


@router.post("/todos.list")
def todos_list(current: dict = Depends(get_current_creator)):
    return {"todos": list_todos(current["username"])}


@router.post("/todos.create")
def todos_create(
    body: schemas.PlugTodoCreate,
    current: dict = Depends(get_current_creator),
):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    todo = insert_todo(current["username"], text)
    return {"todo": todo, "todos": list_todos(current["username"])}


@router.post("/todos.update")
def todos_update(
    body: schemas.PlugTodoUpdate,
    current: dict = Depends(get_current_creator),
):
    text = body.text.strip() if isinstance(body.text, str) else None
    if text is not None and not text:
        raise HTTPException(status_code=400, detail="Text is required")
    updated = update_todo(current["username"], body.id, text=text, done=body.done)
    if not updated:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"todo": updated, "todos": list_todos(current["username"])}


@router.post("/todos.delete")
def todos_delete(
    body: schemas.PlugTodoDelete,
    current: dict = Depends(get_current_creator),
):
    if not delete_todo(current["username"], body.id):
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"todos": list_todos(current["username"])}


@router.post("/todos.reorder")
def todos_reorder(
    body: schemas.PlugTodoReorder,
    current: dict = Depends(get_current_creator),
):
    todos = reorder_todos(current["username"], body.open_ids or [], body.done_ids or [])
    return {"todos": todos}
