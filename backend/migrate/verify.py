"""Compare TG source counts vs Beacon destination after import."""

from __future__ import annotations

from typing import Any

from backend.main.db import (
    access_col,
    channels_col,
    custom_trackers_col,
    monthly_reports_col,
    plan_items_col,
    yt_metadata_col,
    projects_col,
    social_posts_col,
    social_schedules_col,
    users_col,
    videos_col,
    weekly_trackers_col,
)

from . import source as S
from .config import BEACON_SUPERUSER_EMAIL


def beacon_counts() -> dict[str, int]:
    return {
        "users": users_col().estimated_document_count(),
        "projects": projects_col().estimated_document_count(),
        "access": access_col().estimated_document_count(),
        "channels": channels_col().estimated_document_count(),
        "videos": videos_col().estimated_document_count(),
        "yt_metadata": yt_metadata_col().estimated_document_count(),
        "productions": yt_metadata_col().estimated_document_count(),
        "monthly_reports": monthly_reports_col().estimated_document_count(),
        "plan_items": plan_items_col().estimated_document_count(),
        "social_posts": social_posts_col().estimated_document_count(),
        "social_schedules": social_schedules_col().estimated_document_count(),
        "weekly_trackers": weekly_trackers_col().estimated_document_count(),
        "custom_trackers": custom_trackers_col().estimated_document_count(),
    }


def verify_import(bundle_stats: dict[str, Any]) -> dict[str, Any]:
    source_before = bundle_stats.get("source_counts") or {}
    source_after = {} if bundle_stats.get("fixture") else S.count_all()
    dest = beacon_counts()
    bundle = bundle_stats.get("bundle_counts") or {}

    mismatches = []
    # Source must be unchanged (read-only guarantee) — skip for --fixture
    if not bundle_stats.get("fixture"):
        for key, before in source_before.items():
            after = source_after.get(key, 0)
            if before != after:
                mismatches.append(f"SOURCE CHANGED {key}: {before} → {after}")

    # Dest should match what we intended to write
    checks = [
        ("projects", "projects"),
        ("channels", "channels"),
        ("videos", "videos"),
        ("yt_metadata", "productions"),
        ("productions", "productions"),
        ("monthly_reports", "monthly_reports"),
        ("plan_items", "plan_items"),
        ("social_posts", "social_posts"),
        ("social_schedules", "social_schedules"),
        ("weekly_trackers", "weekly_trackers"),
        ("custom_trackers", "custom_trackers"),
    ]
    for dest_key, bundle_key in checks:
        if dest.get(dest_key, 0) != bundle.get(bundle_key, 0):
            mismatches.append(
                f"dest {dest_key}={dest.get(dest_key)} != bundle {bundle_key}={bundle.get(bundle_key)}"
            )

    superuser = users_col().find_one(
        {"email": BEACON_SUPERUSER_EMAIL}, {"_id": 0, "id": 1, "email": 1, "type": 1}
    )
    project_ids = [p["id"] for p in projects_col().find({}, {"id": 1, "_id": 0})]
    expected_access = len(project_ids) * 2
    access_n = access_col().count_documents(
        {"user_id": (superuser or {}).get("id"), "project_id": {"$in": project_ids}}
    ) if superuser else 0
    if project_ids and access_n != expected_access:
        mismatches.append(
            f"access grants={access_n} expected={expected_access} for superuser"
        )

    sample = None
    if project_ids:
        pid = project_ids[0]
        sample = {
            "project_id": pid,
            "project": projects_col().find_one({"id": pid}, {"_id": 0, "name": 1, "topics": 1}),
            "channels": channels_col().count_documents({"project_id": pid}),
            "videos": videos_col().count_documents({"project_id": pid}),
            "social_posts": social_posts_col().count_documents({"project_id": pid}),
            "weekly_trackers": weekly_trackers_col().count_documents({"project_id": pid}),
            "custom_trackers": custom_trackers_col().count_documents({"project_id": pid}),
        }
        if sample["project"] and "topics" in sample["project"]:
            sample["topic_count"] = len(sample["project"].pop("topics") or [])

    return {
        "ok": len(mismatches) == 0,
        "mismatches": mismatches,
        "source_after": source_after,
        "destination": dest,
        "superuser": superuser,
        "sample_project": sample,
    }
