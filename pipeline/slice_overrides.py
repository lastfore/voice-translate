"""Per-slice convert override persistence (6-A sidecar)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.models import SliceMode

CONVERT_OVERRIDE_KEYS = (
    "diffusion_steps",
    "length_adjust",
    "inference_cfg_rate",
    "auto_f0_adjust",
    "semi_tone_shift",
    "fp16",
    "reference",
)

LRC_TOLERANCE_MS = 150.0
VAD_TOLERANCE_MS = 200.0


@dataclass
class SliceOverrides:
    version: int = 1
    global_defaults: dict[str, Any] = field(default_factory=dict)
    slices: dict[str, dict[str, Any]] = field(default_factory=dict)
    orphans: list[dict[str, Any]] = field(default_factory=list)


def default_convert_globals() -> dict[str, Any]:
    from pipeline.stage_params import default_stage_params

    defaults = default_stage_params("convert")
    return {k: defaults[k] for k in CONVERT_OVERRIDE_KEYS if k in defaults and k != "reference"}


def load(path: Path) -> SliceOverrides:
    if not path.is_file():
        return SliceOverrides(global_defaults=default_convert_globals())
    data = json.loads(path.read_text(encoding="utf-8"))
    return SliceOverrides(
        version=int(data.get("version", 1)),
        global_defaults=dict(data.get("global_defaults") or default_convert_globals()),
        slices={str(k): dict(v) for k, v in (data.get("slices") or {}).items()},
        orphans=list(data.get("orphans") or []),
    )


def save(path: Path, data: SliceOverrides) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": data.version,
        "global_defaults": data.global_defaults,
        "slices": data.slices,
        "orphans": data.orphans,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def effective_params(
    slice_id: str,
    overrides: SliceOverrides,
    stage_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(overrides.global_defaults)
    if stage_defaults:
        for key in CONVERT_OVERRIDE_KEYS:
            if key in stage_defaults and stage_defaults[key] is not None:
                merged[key] = stage_defaults[key]
    merged.update(
        {
            k: v
            for k, v in overrides.slices.get(slice_id, {}).items()
            if v is not None and k in CONVERT_OVERRIDE_KEYS
        }
    )
    return merged


def _lrc_match_start(item: dict[str, Any]) -> float:
    return float(item.get("lrc_start_ms", item.get("start_ms", 0)))


def _slice_identity(item: dict[str, Any]) -> tuple[float, str]:
    return _lrc_match_start(item), str(item.get("text") or "")


def _match_slice(
    orphan_entry: dict[str, Any],
    new_slices: list[dict[str, Any]],
    *,
    mode: str,
    tolerance_ms: float,
) -> str | None:
    old_start = float(orphan_entry.get("start_ms", 0))
    old_text = str(orphan_entry.get("text") or "")
    old_id = str(orphan_entry.get("slice_id") or orphan_entry.get("id") or "")

    for item in new_slices:
        new_id = str(item.get("id", ""))
        if old_id and new_id == old_id:
            return new_id

    match_start = _lrc_match_start
    if mode == SliceMode.LRC.value and old_text:
        for item in new_slices:
            if str(item.get("text") or "") != old_text:
                continue
            if abs(match_start(item) - old_start) <= tolerance_ms:
                return str(item.get("id", ""))

    best_id: str | None = None
    best_delta = tolerance_ms + 1.0
    for item in new_slices:
        delta = abs(match_start(item) - old_start)
        if delta <= tolerance_ms and delta < best_delta:
            best_delta = delta
            best_id = str(item.get("id", ""))
    return best_id


def merge_after_reslice(
    old: SliceOverrides,
    new_manifest: dict[str, Any],
    *,
    mode: str,
    old_manifest: dict[str, Any] | None = None,
    tolerance_ms: float | None = None,
) -> SliceOverrides:
    """Re-map per-slice overrides onto a freshly generated manifest."""
    if tolerance_ms is None:
        tolerance_ms = LRC_TOLERANCE_MS if mode == SliceMode.LRC.value else VAD_TOLERANCE_MS

    new_slices = list(new_manifest.get("slices") or [])
    old_slices = list((old_manifest or {}).get("slices") or [])
    old_by_id = {str(item.get("id", "")): item for item in old_slices}
    new_ids = {str(item.get("id", "")) for item in new_slices}
    migrated: dict[str, dict[str, Any]] = {}
    orphans: list[dict[str, Any]] = list(old.orphans)

    for old_id, params in old.slices.items():
        if old_id in new_ids:
            migrated[old_id] = params
            continue
        old_item = old_by_id.get(old_id)
        entry: dict[str, Any] = {"slice_id": old_id, "params": params}
        if old_item:
            entry["start_ms"] = _lrc_match_start(old_item)
            entry["text"] = old_item.get("text")
        matched = _match_slice(entry, new_slices, mode=mode, tolerance_ms=tolerance_ms)
        if matched:
            migrated[matched] = params
        else:
            orphans.append(
                {
                    "slice_id": old_id,
                    "start_ms": entry.get("start_ms"),
                    "text": entry.get("text"),
                    "params": params,
                    "reason": "no_match_after_reslice",
                }
            )

    return SliceOverrides(
        version=old.version,
        global_defaults=old.global_defaults,
        slices=migrated,
        orphans=orphans,
    )


def apply_slice_override(
    overrides: SliceOverrides,
    slice_ids: list[str],
    params: dict[str, Any],
) -> SliceOverrides:
    updated = SliceOverrides(
        version=overrides.version,
        global_defaults=dict(overrides.global_defaults),
        slices={k: dict(v) for k, v in overrides.slices.items()},
        orphans=list(overrides.orphans),
    )
    clean = {k: v for k, v in params.items() if k in CONVERT_OVERRIDE_KEYS and v is not None}
    for slice_id in slice_ids:
        entry = dict(updated.slices.get(slice_id, {}))
        entry.update(clean)
        updated.slices[slice_id] = entry
    return updated


def clear_slice_overrides(overrides: SliceOverrides, slice_ids: list[str]) -> SliceOverrides:
    updated = SliceOverrides(
        version=overrides.version,
        global_defaults=dict(overrides.global_defaults),
        slices={k: dict(v) for k, v in overrides.slices.items()},
        orphans=list(overrides.orphans),
    )
    for slice_id in slice_ids:
        updated.slices.pop(slice_id, None)
    return updated


def clear_orphans(overrides: SliceOverrides) -> SliceOverrides:
    return SliceOverrides(
        version=overrides.version,
        global_defaults=dict(overrides.global_defaults),
        slices=dict(overrides.slices),
        orphans=[],
    )
