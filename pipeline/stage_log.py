"""Structured stage job logging — prefixes, param groups, path formatting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pipeline.models import ProgressEvent, StageName, rel_path

if TYPE_CHECKING:
    pass


def ms_between(iso_start: str, iso_end: str) -> int:
    """Compute milliseconds between two ISO timestamps (fallback when monotonic unavailable)."""
    try:
        start = datetime.fromisoformat(iso_start)
        end = datetime.fromisoformat(iso_end)
        return max(0, int((end - start).total_seconds() * 1000))
    except (TypeError, ValueError):
        return 0


def _format_kv_line(prefix: str, pairs: dict[str, str]) -> str:
    parts = "  ".join(f"{k}={v}" for k, v in pairs.items())
    return f"{prefix} {parts}"


def _format_param_values(group: dict[str, Any]) -> str:
    return "  ".join(f"{k}={v}" for k, v in group.items())


@dataclass
class ParamLogGroups:
    mode: dict[str, Any] = field(default_factory=dict)
    wizard: dict[str, Any] = field(default_factory=dict)
    advanced: dict[str, Any] = field(default_factory=dict)
    defaulted: dict[str, Any] = field(default_factory=dict)


def pick_inputs(
    stage: StageName | str,
    inputs: dict[str, Any],
    params: dict[str, Any],
    root: Path,
) -> dict[str, str]:
    """Select input keys per stage contract and format as repo-relative paths."""
    stage_val = stage.value if isinstance(stage, StageName) else stage

    def _rel(key: str) -> str | None:
        val = inputs.get(key) or params.get(key)
        if not val:
            return None
        p = Path(val)
        if not p.is_absolute():
            p = (root / p).resolve()
        return rel_path(p, root)

    mapping: dict[str, str] = {}
    if stage_val == StageName.SEPARATE.value:
        if v := _rel("mix_audio"):
            mapping["mix_audio"] = v
    elif stage_val == StageName.SLICE.value:
        if v := _rel("vocals"):
            mapping["vocals"] = v
        mode = params.get("mode") or inputs.get("mode", "")
        if mode == "lrc":
            if v := _rel("lrc"):
                mapping["lrc"] = v
        if v := _rel("output_dir"):
            mapping["output_dir"] = v
        if mode:
            mapping["mode"] = str(mode)
    elif stage_val == StageName.CONVERT.value:
        mode = params.get("mode") or inputs.get("mode", "slice_batch")
        if mode:
            mapping["mode"] = str(mode)
        for key in ("source_vocals", "reference", "slices_dir", "manifest", "output_dir", "overrides_path"):
            if v := _rel(key):
                mapping[key] = v
        if mode == "full_track":
            if v := _rel("output_path"):
                mapping["output_path"] = v
    elif stage_val == StageName.MERGE.value:
        for key in (
            "vocals",
            "instrumental",
            "reference",
            "original_vocals",
            "manifest",
            "slices_dir",
            "output_dir",
        ):
            if v := _rel(key):
                mapping[key] = v
        profile = params.get("profile") or params.get("merge_profile")
        if profile:
            mapping["profile"] = str(profile)
    return mapping


def build_param_groups(
    stage: StageName | str,
    params: dict[str, Any],
    inputs: dict[str, Any],
) -> ParamLogGroups:
    """Build wizard / advanced / defaulted param groups for logging."""
    from pipeline.stage_params import collect_params, default_stage_params, params_for_stage

    stage_val = stage.value if isinstance(stage, StageName) else stage
    slice_mode = (
        inputs.get("slice_mode")
        or params.get("active_slice_mode")
        or params.get("slice_mode")
        or params.get("mode")
    )
    convert_mode = params.get("mode") or inputs.get("mode")
    if stage_val == StageName.SLICE.value:
        slice_mode = params.get("mode") or inputs.get("mode") or slice_mode
    if stage_val == StageName.CONVERT.value:
        convert_mode = params.get("mode") or inputs.get("mode") or convert_mode

    defaults = default_stage_params(stage_val)
    effective = collect_params(
        stage_val,
        {**defaults, **params},
        slice_mode=str(slice_mode) if slice_mode else None,
        convert_mode=str(convert_mode) if convert_mode else None,
    )
    schema = {p.key: p for p in params_for_stage(stage_val)}

    groups = ParamLogGroups()
    mode_keys = ("mode", "active_slice_mode", "profile", "merge_profile")
    for key in mode_keys:
        val = params.get(key) or inputs.get(key)
        if val is not None and key != "merge_profile":
            groups.mode[key if key != "merge_profile" else "profile"] = val
        elif key == "merge_profile" and val is not None:
            groups.mode["profile"] = val

    for key, value in effective.items():
        param = schema.get(key)
        if param is None:
            continue
        default_val = defaults.get(key)
        if param.wizard:
            groups.wizard[key] = value
        elif value != default_val:
            groups.advanced[key] = value
        else:
            groups.defaulted[key] = value

    return groups


def format_cmd_lines(argv: list[str], *, cwd: str | None = None, python: str | None = None) -> list[str]:
    """Return [CMD] lines for python, cwd, and argv."""
    lines: list[str] = []
    if python:
        lines.append(f"[CMD] python={python}")
    if cwd:
        lines.append(f"[CMD] cwd={cwd}")
    lines.append(f"[CMD] argv: {' '.join(argv)}")
    return lines


@dataclass
class StageLogWriter:
    project_id: str
    stage: StageName
    job_id: str
    log_path: Path
    root: Path
    on_progress: Callable[[ProgressEvent], None] | None = None
    _percent: float = 0.0
    _footer_written: bool = False

    def _emit(self, log_line: str, message: str | None = None) -> None:
        short = message if message is not None else log_line
        if len(short) > 120:
            short = short[:117] + "..."
        if self.on_progress:
            self.on_progress(
                ProgressEvent(
                    project_id=self.project_id,
                    stage=self.stage,
                    job_id=self.job_id,
                    percent=self._percent,
                    message=short,
                    log_line=log_line,
                )
            )

    def _write_lines(self, lines: list[str]) -> None:
        for line in lines:
            self._emit(line)

    def job_header(self, *, queued_at: str, created_at: str) -> None:
        log_display = rel_path(self.log_path, self.root)
        lines = [
            f"[JOB] === {self.stage.value} stage job={self.job_id} ===",
            _format_kv_line(
                "[JOB]",
                {
                    "project_id": self.project_id,
                    "stage": self.stage.value,
                    "created_at": created_at,
                },
            ),
            _format_kv_line("[JOB]", {"queued_at": queued_at, "log": log_display}),
        ]
        self._write_lines(lines)

    def job_started(self, *, started_at: str, queue_wait_ms: int) -> None:
        self._emit(_format_kv_line("[JOB]", {"started_at": started_at, "queue_wait_ms": str(queue_wait_ms)}))

    def section(self, title: str, lines: dict[str, str] | list[str]) -> None:
        self._emit(f"[JOB] --- {title} ---")
        if isinstance(lines, dict):
            for key, val in lines.items():
                self._emit(f"[JOB] {key}={val}")
        else:
            for line in lines:
                self._emit(f"[JOB] {line}")

    def inputs(self, mapping: dict[str, str | None]) -> None:
        for key, val in mapping.items():
            if val:
                self._emit(f"[INPUT] {key}={val}")

    def params(self, groups: ParamLogGroups) -> None:
        if groups.mode:
            self._emit(f"[PARAM] {_format_param_values(groups.mode)}")
        if groups.wizard:
            self._emit(f"[PARAM] wizard: {_format_param_values(groups.wizard)}")
        if groups.advanced:
            self._emit(f"[PARAM] advanced: {_format_param_values(groups.advanced)}")
        if groups.defaulted:
            keys = ", ".join(sorted(groups.defaulted.keys()))
            self._emit(f"[PARAM] default: {keys}")

    def cmd(self, argv: list[str], *, cwd: str | None = None, python: str | None = None) -> None:
        self._write_lines(format_cmd_lines(argv, cwd=cwd, python=python))

    def exec_context(self, **kv: str) -> None:
        self._emit(f"[EXEC] {_format_param_values(kv)}")

    def info(self, message: str) -> None:
        self._emit(f"[PROC] {message}", message=message)

    def line(self, message: str) -> None:
        self._emit(f"[PROC] {message}", message=message)

    def outputs(self, mapping: dict[str, str | None], **extra: str | int | None) -> None:
        for key, val in mapping.items():
            if val is not None:
                self._emit(f"[OUT] {key}={val}")
        for key, val in extra.items():
            if val is not None:
                self._emit(f"[OUT] {key}={val}")

    def error(self, message: str) -> None:
        self._emit(f"[ERR] {message}")

    def job_footer(self, *, success: bool, elapsed_ms: int, error: str | None = None) -> None:
        if self._footer_written:
            return
        self._footer_written = True
        status = "true" if success else "false"
        line = f"[JOB] === done success={status} elapsed_ms={elapsed_ms} ==="
        if error and not success:
            line = f"[JOB] === done success={status} elapsed_ms={elapsed_ms} error={error} ==="
        self._emit(line)


def pick_outputs(
    stage: StageName | str,
    artifacts: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, str | None], dict[str, str | int | None]]:
    """Build output mapping and extra counts from stage execution result."""
    stage_val = stage.value if isinstance(stage, StageName) else stage
    mapping: dict[str, str | None] = {}
    extra: dict[str, str | int | None] = {}

    if stage_val == StageName.SEPARATE.value:
        mapping["vocals"] = artifacts.get("vocals")
        mapping["instrumental"] = artifacts.get("instrumental")
    elif stage_val == StageName.SLICE.value:
        mapping["slices_dir"] = artifacts.get("slices_dir")
        mapping["manifest"] = artifacts.get("manifest")
        if "slice_count" in params:
            extra["slice_count"] = params["slice_count"]
    elif stage_val == StageName.CONVERT.value:
        mode = params.get("mode", "slice_batch")
        if mode == "slice_batch":
            mapping["converted_dir"] = artifacts.get("converted_dir")
            cc = params.get("converted_count")
            tc = params.get("total_count")
            if cc is not None and tc is not None:
                extra["converted_count"] = f"{cc}/{tc}"
            elif cc is not None:
                extra["converted_count"] = cc
        if artifacts.get("full_track"):
            mapping["full_track"] = artifacts.get("full_track")
    elif stage_val == StageName.MERGE.value:
        mapping["merged_dir"] = artifacts.get("merged_dir")
        mapping["vocals"] = artifacts.get("vocals")
        mapping["mixed"] = artifacts.get("mixed")

    return mapping, extra
