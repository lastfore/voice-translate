"""Request/response models for stage-run endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StageRunRequest(BaseModel):
    """Body for ``POST /api/projects/{id}/stages/{stage}/run``.

    SSE endpoints take POST + JSON body (not GET query params) per migration
    doc §4.1.2/§7 — avoids URL length limits and query-encoding issues with
    e.g. Chinese LRC paths.
    """

    params: dict[str, Any] = Field(default_factory=dict)


class StageRunResultPayload(BaseModel):
    success: bool
    error: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
