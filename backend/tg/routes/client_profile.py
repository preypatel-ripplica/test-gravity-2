from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from backend.tg import schemas
from backend.tg.auth import get_current_user
from backend.tg.database import (
    fetch_client_bundle,
    fetch_client_credentials,
    fetch_doctor_reference,
    save_client_credentials,
    save_doctor_reference,
)

router = APIRouter(tags=["client-profile"])

DEFAULT_SECTIONS = (
    (
        "Video Editing / Generation",
        (
            "HeyGen look used",
            "HeyGen tips",
            "Hand movement preference",
            "ElevenLabs tips",
            "Topic preference",
            "Video editing style / notes",
            "Script notes",
            "Length of video",
            "Voice / audio speed",
            "Posting YouTube videos on FB / Insta",
            "Like / subscribe CTA preference",
            "Colour preference",
        ),
    ),
    (
        "Meeting / Communication",
        (
            "Meeting time",
            "Average response time",
            "Team communication notes",
        ),
    ),
    (
        "Assets & Learnings",
        (
            "Procedure video repository",
            "Reference channel",
            "Doctor-specific focus",
            "Posting approach",
        ),
    ),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "id") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _require_client(username: str, client_id: str) -> dict:
    client = fetch_client_bundle(client_id, username, with_videos=False)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


def seed_doctor_sections() -> list[dict]:
    return [
        {
            "id": _new_id("sec"),
            "title": title,
            "is_default": True,
            "fields": [
                {"id": _new_id("fld"), "label": label, "value": ""}
                for label in labels
            ],
        }
        for title, labels in DEFAULT_SECTIONS
    ]


def _sanitize_sections(sections: list[schemas.DoctorReferenceSection]) -> list[dict]:
    cleaned = []
    for section in sections:
        title = (section.title or "").strip()
        if not title:
            continue
        fields = []
        for field in section.fields or []:
            label = (field.label or "").strip()
            if not label:
                continue
            fields.append({
                "id": field.id or _new_id("fld"),
                "label": label,
                "value": field.value or "",
            })
        cleaned.append({
            "id": section.id or _new_id("sec"),
            "title": title,
            "is_default": bool(section.is_default),
            "fields": fields,
        })
    return cleaned


def _sanitize_credentials(items: list[schemas.ClientCredentialItem]) -> list[dict]:
    cleaned = []
    for item in items:
        service = (item.service or "").strip()
        if not service:
            continue
        cleaned.append({
            "id": item.id or _new_id("cred"),
            "service": service,
            "username": (item.username or "").strip(),
            "password": item.password or "",
            "notes": (item.notes or "").strip(),
        })
    return cleaned


def _reference_payload(doc: dict) -> schemas.DoctorReferenceDoc:
    return schemas.DoctorReferenceDoc(
        id=doc.get("id") or doc.get("client_id"),
        client_id=doc["client_id"],
        sections=doc.get("sections") or [],
        updated_at=doc.get("updated_at"),
        updated_by=doc.get("updated_by"),
    )


def _credentials_payload(doc: dict) -> schemas.ClientCredentialsDoc:
    return schemas.ClientCredentialsDoc(
        id=doc.get("id") or doc.get("client_id"),
        client_id=doc["client_id"],
        credentials=doc.get("credentials") or [],
        updated_at=doc.get("updated_at"),
        updated_by=doc.get("updated_by"),
    )


@router.post("/client.doctor-reference.get", response_model=schemas.DoctorReferenceResponse)
def get_doctor_reference(
    body: schemas.DoctorReferenceGetRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    _require_client(username, body.client_id)
    existing = fetch_doctor_reference(body.client_id)
    if existing:
        return schemas.DoctorReferenceResponse(reference=_reference_payload(existing))

    now = _now_iso()
    saved = save_doctor_reference({
        "client_id": body.client_id,
        "sections": seed_doctor_sections(),
        "updated_at": now,
        "updated_by": username,
    })
    return schemas.DoctorReferenceResponse(reference=_reference_payload(saved))


@router.post("/client.doctor-reference.save", response_model=schemas.DoctorReferenceResponse)
def save_doctor_reference_route(
    body: schemas.DoctorReferenceSaveRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    _require_client(username, body.client_id)
    now = _now_iso()
    saved = save_doctor_reference({
        "client_id": body.client_id,
        "sections": _sanitize_sections(body.sections),
        "updated_at": now,
        "updated_by": username,
    })
    return schemas.DoctorReferenceResponse(reference=_reference_payload(saved))


@router.post("/client.credentials.get", response_model=schemas.ClientCredentialsResponse)
def get_client_credentials_route(
    body: schemas.ClientCredentialsGetRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    _require_client(username, body.client_id)
    existing = fetch_client_credentials(body.client_id)
    if existing:
        return schemas.ClientCredentialsResponse(credentials=_credentials_payload(existing))

    now = _now_iso()
    saved = save_client_credentials({
        "client_id": body.client_id,
        "credentials": [],
        "updated_at": now,
        "updated_by": username,
    })
    return schemas.ClientCredentialsResponse(credentials=_credentials_payload(saved))


@router.post("/client.credentials.save", response_model=schemas.ClientCredentialsResponse)
def save_client_credentials_route(
    body: schemas.ClientCredentialsSaveRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    _require_client(username, body.client_id)
    now = _now_iso()
    saved = save_client_credentials({
        "client_id": body.client_id,
        "credentials": _sanitize_credentials(body.credentials),
        "updated_at": now,
        "updated_by": username,
    })
    return schemas.ClientCredentialsResponse(credentials=_credentials_payload(saved))
