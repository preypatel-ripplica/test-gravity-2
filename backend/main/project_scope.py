"""Accept TG-era client_id as an alias for project_id on request bodies."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_validator


class WithProjectId(BaseModel):
    project_id: Optional[str] = None
    client_id: Optional[str] = None

    @model_validator(mode="after")
    def resolve_project_id(self):
        pid = (self.project_id or self.client_id or "").strip()
        if not pid:
            raise ValueError("project_id is required")
        object.__setattr__(self, "project_id", pid)
        return self
