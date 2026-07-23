"""Core data models for the pipeline orchestration kernel."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_JOB_HISTORY = 20


class StageName(str, Enum):
    SEPARATE = "separate"
    SLICE = "slice"
    CONVERT = "convert"
    MERGE = "merge"


class StageStatus(str, Enum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConvertMode(str, Enum):
    FULL_TRACK = "full_track"
    SLICE_BATCH = "slice_batch"


class SliceMode(str, Enum):
    VAD = "vad"
    LRC = "lrc"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(path: Path | str, root: Path) -> str:
    """Return a forward-slash path relative to root."""
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(root)
        except ValueError:
            return str(p).replace("\\", "/")
    return str(p).replace("\\", "/")


@dataclass
class StageRecord:
    status: StageStatus = StageStatus.NOT_RUN
    started_at: str | None = None
    finished_at: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "params": self.params,
            "inputs": self.inputs,
            "artifacts": self.artifacts,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StageRecord:
        if not data:
            return cls()
        return cls(
            status=StageStatus(data.get("status", StageStatus.NOT_RUN.value)),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            params=dict(data.get("params") or {}),
            inputs=dict(data.get("inputs") or {}),
            artifacts=dict(data.get("artifacts") or {}),
            error=data.get("error"),
        )


@dataclass
class Job:
    job_id: str
    type: str
    stage: StageName | None
    status: JobStatus
    created_at: str
    log_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "stage": self.stage.value if self.stage else None,
            "status": self.status.value,
            "created_at": self.created_at,
            "log_path": self.log_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        stage_raw = data.get("stage")
        return cls(
            job_id=data["job_id"],
            type=data.get("type", "stage"),
            stage=StageName(stage_raw) if stage_raw else None,
            status=JobStatus(data.get("status", JobStatus.QUEUED.value)),
            created_at=data["created_at"],
            log_path=data.get("log_path"),
        )


@dataclass
class Project:
    id: str
    display_name: str
    created_at: str
    updated_at: str
    input_audio: str | None = None
    input_lrc: str | None = None
    stages: dict[StageName, StageRecord] = field(default_factory=dict)
    jobs: list[Job] = field(default_factory=list)

    def __post_init__(self) -> None:
        for stage in StageName:
            self.stages.setdefault(stage, StageRecord())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input": {
                "audio": self.input_audio,
                "lrc": self.input_lrc,
            },
            "stages": {name.value: rec.to_dict() for name, rec in self.stages.items()},
            "jobs": [job.to_dict() for job in self.jobs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        input_block = data.get("input") or {}
        stages_raw = data.get("stages") or {}
        stages: dict[StageName, StageRecord] = {}
        for name in StageName:
            stages[name] = StageRecord.from_dict(stages_raw.get(name.value))
        return cls(
            id=data["id"],
            display_name=data.get("display_name", data["id"]),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            input_audio=input_block.get("audio"),
            input_lrc=input_block.get("lrc"),
            stages=stages,
            jobs=[Job.from_dict(j) for j in data.get("jobs") or []],
        )

    def to_summary(self) -> dict[str, Any]:
        """Lightweight dict for Gradio sidebar."""
        stage_icons = {
            name.value: self.stages[name].status.value for name in StageName
        }
        return {
            "id": self.id,
            "display_name": self.display_name,
            "updated_at": self.updated_at,
            "stages": stage_icons,
            "input_audio": self.input_audio,
            "input_lrc": self.input_lrc,
        }

    def save(self, path: Path, root: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


@dataclass
class ProgressEvent:
    project_id: str
    stage: StageName
    job_id: str
    percent: float
    message: str
    log_line: str | None = None

    def to_ui_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "stage": self.stage.value,
            "job_id": self.job_id,
            "percent": self.percent,
            "message": self.message,
            "log_line": self.log_line,
        }


@dataclass
class StageResult:
    project_id: str
    stage: StageName
    success: bool
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class PipelineResult:
    project_id: str
    success: bool
    stage_results: list[StageResult] = field(default_factory=list)
    error: str | None = None
