"""CMS_NEW schema presets for collection create."""

from __future__ import annotations

from typing import Any

SCHEMA_PRESETS: dict[str, dict[str, Any]] = {
    "blogs": {
        "label": "Blogs",
        "description": "Editorial posts with hero image, metadata, and body blocks.",
        "schema": {
            "slug": "",
            "title": "",
            "excerpt": "",
            "publishedAt": "",
            "readingTime": "",
            "category": "",
            "image": {"media_id": "", "src": "", "alt": ""},
            "body": [""],
        },
    },
    "products": {
        "label": "Products",
        "description": "Catalog items with gallery media, pricing, and highlights.",
        "schema": {
            "slug": "",
            "title": "",
            "sku": "",
            "shortDescription": "",
            "price": "",
            "status": "",
            "heroImage": {"media_id": "", "src": "", "alt": ""},
            "gallery": [{"media_id": "", "src": "", "alt": ""}],
            "specs": {"weight": "", "material": ""},
        },
    },
    "pages": {
        "label": "Pages",
        "description": "Static pages with titled sections.",
        "schema": {
            "slug": "",
            "title": "",
            "sections": [{"heading": "", "body": ""}],
        },
    },
    "other": {
        "label": "Other",
        "description": "General-purpose collection for custom content structures.",
        "schema": {
            "slug": "",
            "title": "",
            "status": "",
            "summary": "",
            "heroMedia": {"media_id": "", "src": "", "alt": ""},
            "fields": [
                {
                    "label": "",
                    "value": "",
                    "attachedMedia": {"media_id": "", "src": "", "alt": ""},
                }
            ],
        },
    },
}


def normalize_schema_value(value: Any) -> Any:
    """CMS_NEW: collapse sample values to empty typed shells."""
    if isinstance(value, dict):
        return {key: normalize_schema_value(item) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [normalize_schema_value(value[0])]
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 0
    if value is None:
        return ""
    return ""


def resolve_preset_schema(preset: str | None, schema: dict | None) -> dict[str, Any]:
    if schema:
        return normalize_schema_value(schema)
    key = (preset or "other").strip().lower()
    chosen = SCHEMA_PRESETS.get(key) or SCHEMA_PRESETS["other"]
    return normalize_schema_value(chosen["schema"])
