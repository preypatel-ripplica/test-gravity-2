"""Assemble a full Beacon write bundle from TG source (read-only)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import source as S
from . import transform as T


def _index_by_client(rows: list[dict[str, Any]], key: str = "client_id") -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for row in rows:
        cid = str(row.get(key) or "")
        if cid:
            out[cid].append(row)
    return out


def _index_one(rows: list[dict[str, Any]], key: str = "id") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        # schedules / doctor / credentials often keyed by client id as document id
        rid = str(row.get(key) or row.get("client_id") or "")
        if rid:
            out[rid] = row
    return out


def build_bundle() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Read all TG collections and return (bundle, stats)."""
    clients = list(S.iter_collection(S.COL_CLIENTS))
    topics = list(S.iter_collection(S.COL_TOPICS))
    channels = list(S.iter_collection(S.COL_CHANNELS))
    videos = list(S.iter_collection(S.COL_VIDEOS))
    plans = list(S.iter_collection(S.COL_CONTENT_PLANS))
    content_videos = list(S.iter_collection(S.COL_CONTENT_VIDEOS))
    social_posts = list(S.iter_collection(S.COL_SOCIAL_POSTS))
    social_schedules = list(S.iter_collection(S.COL_SOCIAL_SCHEDULES))
    weekly = list(S.iter_collection(S.COL_WEEKLY_TRACKERS))
    custom = list(S.iter_collection(S.COL_CUSTOM_TRACKERS))
    reports = list(S.iter_collection(S.COL_MONTHLY_REPORTS))
    doctor_refs = list(S.iter_collection(S.COL_DOCTOR_REFERENCES))
    credentials = list(S.iter_collection(S.COL_CLIENT_CREDENTIALS))
    ig_apps = list(S.iter_collection(S.COL_IG_APP))
    ig_conns = list(S.iter_collection(S.COL_IG_CONN))
    fb_apps = list(S.iter_collection(S.COL_FB_APP))
    fb_conns = list(S.iter_collection(S.COL_FB_CONN))

    topics_by = _index_by_client(topics)
    channels_by = _index_by_client(channels)
    videos_by = _index_by_client(videos)
    plans_by_id = {}
    for p in plans:
        # TG content_plans._id == client_id
        cid = str(p.get("id") or p.get("client_id") or "")
        if cid:
            plans_by_id[cid] = p
    cv_by = _index_by_client(content_videos)
    posts_by = _index_by_client(social_posts)
    # schedules: _id was client_id
    schedules_by = {}
    for s in social_schedules:
        cid = str(s.get("client_id") or s.get("id") or "")
        if cid:
            schedules_by[cid] = s
    weekly_by = _index_by_client(weekly)
    custom_by = _index_by_client(custom)
    reports_by = _index_by_client(reports)
    doctor_by = {}
    for d in doctor_refs:
        cid = str(d.get("client_id") or d.get("id") or "")
        if cid:
            doctor_by[cid] = d
    creds_by = {}
    for c in credentials:
        cid = str(c.get("client_id") or c.get("id") or "")
        if cid:
            creds_by[cid] = c
    ig_app_by = {str(d.get("client_id") or d.get("id")): d for d in ig_apps}
    ig_conn_by = {str(d.get("client_id") or d.get("id")): d for d in ig_conns}
    fb_app_by = {str(d.get("client_id") or d.get("id")): d for d in fb_apps}
    fb_conn_by = {str(d.get("client_id") or d.get("id")): d for d in fb_conns}

    bundle: dict[str, list[dict[str, Any]]] = {
        "projects": [],
        "project_secrets": [],
        "plan_items": [],
        "weekly_trackers": [],
        "custom_trackers": [],
        "channels": [],
        "videos": [],
        "productions": [],
        "monthly_reports": [],
        "social_posts": [],
        "social_schedules": [],
    }

    errors: list[str] = []
    for client in clients:
        project_id = str(client.get("id") or "")
        if not project_id:
            errors.append("skip client without id")
            continue
        try:
            plan_doc = plans_by_id.get(project_id)
            project = T.transform_project(
                client,
                topics_by.get(project_id, []),
                doctor_by.get(project_id),
                content_plan=T.extract_content_plan(plan_doc),
            )
            bundle["projects"].append(project)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"project {project_id}: {exc}")
            continue

        # secrets
        if project_id in creds_by:
            bundle["project_secrets"].extend(
                T.transform_manual_credentials(creds_by[project_id], project_id=project_id)
            )
        for provider, store in (
            ("instagram", ig_app_by),
            ("facebook", fb_app_by),
        ):
            secret = T.transform_app_config(
                store.get(project_id) or {}, project_id=project_id, provider=provider
            )
            if secret:
                bundle["project_secrets"].append(secret)
        ig_secret = T.transform_ig_connection(
            ig_conn_by.get(project_id) or {}, project_id=project_id
        )
        if ig_secret:
            bundle["project_secrets"].append(ig_secret)
        fb_secret = T.transform_fb_connection(
            fb_conn_by.get(project_id) or {}, project_id=project_id
        )
        if fb_secret:
            bundle["project_secrets"].append(fb_secret)

        for ch in channels_by.get(project_id, []):
            yt_secret = T.transform_youtube_secret(ch, project_id=project_id)
            secret_id = None
            if yt_secret:
                bundle["project_secrets"].append(yt_secret)
                secret_id = yt_secret["id"]
            bundle["channels"].append(
                T.transform_channel(ch, project_id=project_id, secret_id=secret_id)
            )

        for v in videos_by.get(project_id, []):
            bundle["videos"].append(T.transform_video(v, project_id=project_id))

        if project_id in plans_by_id:
            bundle["plan_items"].extend(
                T.transform_plan_items(plans_by_id[project_id], project_id=project_id)
            )

        for cv in cv_by.get(project_id, []):
            bundle["productions"].append(
                T.transform_production(cv, project_id=project_id)
            )

        for r in reports_by.get(project_id, []):
            if not r.get("report_month"):
                continue
            bundle["monthly_reports"].append(
                T.transform_report(r, project_id=project_id)
            )

        for p in posts_by.get(project_id, []):
            bundle["social_posts"].append(
                T.transform_social_post(p, project_id=project_id)
            )

        if project_id in schedules_by:
            bundle["social_schedules"].append(
                T.transform_social_schedule(
                    schedules_by[project_id], project_id=project_id
                )
            )

        for w in weekly_by.get(project_id, []):
            bundle["weekly_trackers"].append(
                T.transform_weekly_tracker(w, project_id=project_id)
            )
        # Prefer modern custom:{client} doc; skip legacy week-scoped custom docs
        custom_docs = custom_by.get(project_id, [])
        modern = [
            d
            for d in custom_docs
            if str(d.get("id") or "") == f"custom:{project_id}"
            or (
                str(d.get("id") or "").startswith("custom:")
                and str(d.get("id") or "").count(":") == 1
            )
        ]
        if not modern:
            modern = [d for d in custom_docs if isinstance(d.get("tasks"), list)]
        if modern:
            bundle["custom_trackers"].append(
                T.transform_custom_tracker(modern[0], project_id=project_id)
            )

    stats = {
        "source_clients": len(clients),
        "source_counts": S.count_all(),
        "bundle_counts": {k: len(v) for k, v in bundle.items()},
        "errors": errors,
        "topic_embedded": sum(len(p.get("topics") or []) for p in bundle["projects"]),
    }
    return bundle, stats
