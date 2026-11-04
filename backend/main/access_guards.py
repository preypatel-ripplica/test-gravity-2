"""Project / domain access and client vs internal visibility."""

from __future__ import annotations

from fastapi import HTTPException

from .db import access_col, projects_col
from .models import Domain, UserType


def require_internal(auth: dict) -> None:
    if auth.get("type") != UserType.INTERNAL.value:
        raise HTTPException(403, "Internal users only")


def is_editor(auth: dict) -> bool:
    return auth.get("type") == UserType.EDITOR.value


def is_internal(auth: dict) -> bool:
    return auth.get("type") == UserType.INTERNAL.value


def require_internal_or_editor(auth: dict) -> None:
    if not (is_internal(auth) or is_editor(auth)):
        raise HTTPException(403, "Internal or editor users only")


def editor_id_from_auth(auth: dict) -> str:
    """Roster id for an editor user; empty for non-editors."""
    if not is_editor(auth):
        return ""
    return str(auth.get("editor_id") or "").strip()


def require_editor_roster(auth: dict) -> str:
    """Editors must have a valid roster editor_id; returns it."""
    require_internal_or_editor(auth)
    if is_internal(auth):
        return ""
    editor_id = editor_id_from_auth(auth)
    if not editor_id:
        raise HTTPException(403, "Editor account is missing editor_id")
    from backend.trackers.editors import editor_by_id

    if not editor_by_id(editor_id):
        raise HTTPException(403, "Editor account is linked to an unknown roster id")
    return editor_id


def require_project_access(user_id: str, project_id: str) -> dict:
    """Any domain grant on this project (owner counts). Returns the project doc."""
    project = projects_col().find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "Project not found")
    if project.get("owner_user_id") == user_id:
        return project
    grant = access_col().find_one({"user_id": user_id, "project_id": project_id})
    if not grant:
        raise HTTPException(403, "No access to this project")
    return project


def require_domain_access(user_id: str, project_id: str, domain: Domain | str) -> dict:
    """Specific domain grant. Returns the project doc."""
    domain_value = domain.value if isinstance(domain, Domain) else domain
    project = projects_col().find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "Project not found")
    # Owner always has every domain
    if project.get("owner_user_id") == user_id:
        return project
    grant = access_col().find_one(
        {"user_id": user_id, "project_id": project_id, "domain": domain_value}
    )
    if not grant:
        raise HTTPException(403, f"No access to domain '{domain_value}' on this project")
    return project


def require_project_owner(auth: dict, project_id: str) -> dict:
    """Only the project owner may manage members / access UI."""
    project = projects_col().find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "Project not found")
    owner_id = project.get("owner_user_id")
    if not owner_id or owner_id != auth.get("user_id"):
        raise HTTPException(403, "Only the project owner can manage access")
    return project


def is_project_owner(user_id: str, project: dict) -> bool:
    return bool(project.get("owner_user_id") and project.get("owner_user_id") == user_id)


def is_client(auth: dict) -> bool:
    return auth.get("type") == UserType.CLIENT.value


def public_secret(doc: dict, *, viewer_is_client: bool) -> dict:
    """Never leak tokens/passwords to clients; redact for internals in list views."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    sensitive = (
        "secret_encrypted",
        "refresh_token_encrypted",
        "access_token_encrypted",
    )
    if viewer_is_client:
        for key in sensitive:
            out.pop(key, None)
        out.pop("username", None)
        return out
    for key in sensitive:
        if out.get(key):
            out[key] = "***"
    return out


def filter_yt_metadata_for_viewer(doc: dict, auth: dict) -> dict | None:
    """Clients do not see WIP yt_metadata packages."""
    if is_client(auth):
        return None
    return doc


# Legacy alias
filter_production_for_viewer = filter_yt_metadata_for_viewer


def filter_report_for_viewer(doc: dict, auth: dict) -> dict:
    out = {**doc}
    out.pop("_id", None)
    if is_client(auth):
        out.pop("refine_history", None)
    return out
