"""Stage execution orchestration."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.models import (
    ConvertMode,
    Job,
    JobStatus,
    PipelineResult,
    ProgressEvent,
    SliceMode,
    StageName,
    StageResult,
    StageStatus,
    rel_path,
    utc_now_iso,
)
from pipeline.queue import GpuJobQueue, JobResult
from pipeline.stage_log import (
    StageLogWriter,
    build_param_groups,
    pick_inputs,
    pick_outputs,
)
from pipeline.stage_params import params_for_stage
from pipeline.stages.convert import run_convert
from pipeline.stages.merge import run_merge
from pipeline.stages.separate import run_separate
from pipeline.stages.slice import run_slice
from pipeline.store import ProjectStore

# Resolved path/mode fields must not be overwritten by stale UI form params.
_RESOLVED_INPUT_KEYS = frozenset({
    "mix_audio",
    "vocals",
    "lrc",
    "slices_dir",
    "manifest",
    "output_dir",
    "output_path",
    "reference",
    "source_vocals",
    "instrumental",
    "original_vocals",
    "slice_mode",
    "active_slice_mode",
})


class StageRunner:
    """Execute single stages or full pipelines via the GPU queue."""

    def __init__(self, store: ProjectStore, gpu_queue: GpuJobQueue | None = None) -> None:
        self.store = store
        self.queue = gpu_queue or GpuJobQueue()
        self._progress_subscribers: dict[str, queue.Queue[ProgressEvent]] = {}

    def run_stage(
        self,
        project_id: str,
        stage: StageName,
        params: dict | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        on_job_id: Callable[[str], None] | None = None,
    ) -> StageResult:
        """Run *stage* synchronously (blocks until the GPU queue completes it).

        ``on_job_id`` (optional) is invoked with the generated job id as soon as
        it is known — before the run is enqueued — so callers that need to
        cancel a still-running job (e.g. an HTTP layer detecting client
        disconnect) have something to pass to :meth:`cancel`.
        """
        params = dict(params or {})
        inputs = self.store.resolve_stage_inputs(project_id, stage, params)
        ok, errors = self.store.validate_stage_inputs(stage, inputs)
        if not ok:
            return StageResult(project_id, stage, False, error="; ".join(errors))

        self.store.save_stage_inputs(project_id, stage, inputs)
        job_id = self.queue.new_job_id(stage.value)
        if on_job_id is not None:
            on_job_id(job_id)
        log_path = paths.project_logs_dir(project_id) / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        created_at = queued_at = utc_now_iso()
        t_queued = time.monotonic()

        self.store.update_stage(project_id, stage, status=StageStatus.RUNNING, error=None)
        self.store.add_job(
            project_id,
            Job(
                job_id=job_id,
                type="stage",
                stage=stage,
                status=JobStatus.QUEUED,
                created_at=created_at,
                log_path=rel_path(log_path, self.store.root),
            ),
        )

        def _log(event: ProgressEvent) -> None:
            if event.log_line:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(event.log_line + "\n")
            if on_progress:
                on_progress(event)
            self._publish_progress(job_id, event)

        stage_log = StageLogWriter(
            project_id=project_id,
            stage=stage,
            job_id=job_id,
            log_path=log_path,
            root=self.store.root,
            on_progress=_log,
        )
        stage_log.job_header(queued_at=queued_at, created_at=created_at)
        stage_log.inputs(pick_inputs(stage, inputs, params, self.store.root))
        stage_log.params(build_param_groups(stage, params, inputs))

        def _work() -> dict[str, Any]:
            started_at = utc_now_iso()
            queue_wait_ms = int((time.monotonic() - t_queued) * 1000)
            stage_log.job_started(started_at=started_at, queue_wait_ms=queue_wait_ms)
            t_start = time.monotonic()
            try:
                payload = self._execute_stage(project_id, stage, inputs, params, _log, stage_log)
                out_map, out_extra = pick_outputs(stage, payload.get("artifacts", {}), payload.get("params", {}))
                stage_log.outputs(out_map, **out_extra)
                elapsed_ms = int((time.monotonic() - t_start) * 1000)
                stage_log.job_footer(success=True, elapsed_ms=elapsed_ms)
                return payload
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - t_start) * 1000)
                stage_log.error(str(exc))
                stage_log.job_footer(success=False, elapsed_ms=elapsed_ms, error=str(exc))
                raise

        self.queue.enqueue(
            Job(job_id=job_id, type="stage", stage=stage, status=JobStatus.QUEUED, created_at=created_at),
            _work,
        )
        job_result = self.queue.wait(job_id)
        if job_result.status == JobStatus.CANCELLED and not stage_log._footer_written:
            stage_log.error(job_result.error or "cancelled by user")
            stage_log.job_footer(success=False, elapsed_ms=0, error=job_result.error or "cancelled")
        return self._finalize_stage(project_id, stage, job_result, inputs, params)

    def run_stage_async(
        self,
        project_id: str,
        stage: str | StageName,
        params: dict | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        stage_enum = stage if isinstance(stage, StageName) else StageName(stage)
        events: queue.Queue[ProgressEvent | None] = queue.Queue()
        holder: list[StageResult] = []

        def _on_progress(event: ProgressEvent) -> None:
            events.put(event)

        def _worker() -> None:
            try:
                holder.append(self.run_stage(project_id, stage_enum, params, on_progress=_on_progress))
            finally:
                events.put(None)

        threading.Thread(target=_worker, daemon=True).start()
        while True:
            item = events.get()
            if item is None:
                break
            yield item.to_ui_dict()
        if holder:
            result = holder[0]
            yield {
                "done": True,
                "success": result.success,
                "error": result.error,
                "artifacts": result.artifacts,
            }

    def run_pipeline(
        self,
        project_id: str,
        *,
        stages: list[StageName] | None = None,
        convert_mode: ConvertMode = ConvertMode.SLICE_BATCH,
        slice_mode: SliceMode | None = None,
        stop_on_error: bool = True,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        **params: Any,
    ) -> PipelineResult:
        chain = stages or list(StageName)
        resolved_slice_mode = SliceMode(
            self.store.resolve_pipeline_slice_mode(project_id, slice_mode)
        )
        ok, plan_or_errors = self.store.validate_pipeline_chain(
            project_id,
            chain,
            convert_mode=convert_mode,
            slice_mode=resolved_slice_mode,
            **params,
        )
        if not ok:
            errors = plan_or_errors if isinstance(plan_or_errors, list) else []
            return PipelineResult(project_id, False, error="; ".join(errors))

        results: list[StageResult] = []
        pipeline_params = dict(params)
        pipeline_params.setdefault("mode", convert_mode.value)

        for stage in chain:
            stage_params = dict(pipeline_params)
            sm = resolved_slice_mode.value
            if stage == StageName.SLICE:
                stage_params.setdefault("mode", sm)
            if stage == StageName.CONVERT:
                stage_params.setdefault("mode", convert_mode.value)
                if convert_mode != ConvertMode.FULL_TRACK:
                    stage_params.setdefault("slice_mode", sm)
                    stage_params.setdefault("active_slice_mode", sm)
            if stage == StageName.MERGE:
                stage_params.setdefault("slice_mode", sm)
                stage_params.setdefault("active_slice_mode", sm)

            result = self.run_stage(project_id, stage, stage_params, on_progress=on_progress)
            results.append(result)
            if not result.success:
                if stop_on_error:
                    return PipelineResult(project_id, False, stage_results=results, error=result.error)
        return PipelineResult(project_id, True, stage_results=results)

    def cancel(self, job_id: str) -> bool:
        """Cancel a running stage job.

        Returns True if *job_id* was RUNNING and cancellation was requested
        (the underlying subprocess, if any, is sent ``terminate()``/``kill()``).
        Returns False if the job is unknown, already finished, or still QUEUED
        (queued-but-not-started jobs should use :meth:`GpuJobQueue.cancel`
        instead, which simply drops them before they start).
        """
        if self.queue.get_status(job_id) != JobStatus.RUNNING:
            return False
        return self.queue.cancel_current()

    def _publish_progress(self, job_id: str, event: ProgressEvent) -> None:
        q = self._progress_subscribers.get(job_id)
        if q is not None:
            q.put(event)

    def _execute_stage(
        self,
        project_id: str,
        stage: StageName,
        inputs: dict[str, Any],
        params: dict[str, Any],
        on_progress: Callable[[ProgressEvent], None],
        stage_log: StageLogWriter | None = None,
    ) -> dict[str, Any]:
        root = self.store.root

        def _abs(key: str) -> Path | None:
            val = inputs.get(key) or params.get(key)
            if not val:
                return None
            p = Path(val)
            return (root / p).resolve() if not p.is_absolute() else p.resolve()

        if stage == StageName.SEPARATE:
            mix = _abs("mix_audio")
            assert mix is not None
            result = run_separate(
                project_id,
                mix,
                model=params.get("model", "mel_band_roformer_kim_ft_unwa.ckpt"),
                on_progress=on_progress,
                stage_log=stage_log,
            )
            return {
                "artifacts": {
                    "vocals": rel_path(result.vocals, root),
                    "instrumental": rel_path(result.instrumental, root),
                },
                "params": {"model": params.get("model", "mel_band_roformer_kim_ft_unwa.ckpt")},
            }

        if stage == StageName.SLICE:
            vocals = _abs("vocals")
            mode = params.get("mode") or inputs.get("mode", SliceMode.VAD.value)
            slice_mode = paths.normalize_slice_mode(mode)
            out_dir = _abs("output_dir") or paths.slices_mode_dir(project_id, slice_mode)
            if out_dir:
                out_mode = paths.infer_slice_mode_from_slices_dir(out_dir, project_id)
                if out_mode and out_mode != slice_mode:
                    out_dir = paths.slices_mode_dir(project_id, slice_mode)
            else:
                out_dir = paths.slices_mode_dir(project_id, slice_mode)
            assert vocals is not None
            result = run_slice(
                project_id,
                vocals,
                out_dir,
                mode=mode,
                lrc_path=_abs("lrc"),
                vad_threshold=float(params.get("vad_threshold", 0.45)),
                min_speech_ms=int(params.get("min_speech_ms", 250)),
                min_silence_ms=int(params.get("min_silence_ms", 500)),
                speech_pad_ms=int(params.get("speech_pad_ms", 80)),
                boundary_mode=str(params.get("boundary_mode", "onset_aligned")),
                search_margin_ms=int(params.get("search_margin_ms", 400)),
                onset_min_lead_silence_ms=int(params.get("onset_min_lead_silence_ms", 80)),
                min_slice_ms=int(params.get("min_slice_ms", 500)),
                onset_energy_threshold_db=float(params.get("onset_energy_threshold_db", -40.0)),
                safety_margin_ms=int(params.get("safety_margin_ms", 80)),
                g2p_preroll_ms=int(params.get("g2p_preroll_ms", 0)),
                boundary_zcr_weight=float(params.get("boundary_zcr_weight", 0.0)),
                phoneme_align_mode=str(params.get("phoneme_align_mode", "off")),
                phoneme_align_fallback_only=bool(params.get("phoneme_align_fallback_only", True)),
                phoneme_align_remote_url=str(params.get("phoneme_align_remote_url", "")),
                phoneme_align_remote_timeout_s=int(
                    params.get("phoneme_align_remote_timeout_s", 30)
                ),
                on_progress=on_progress,
                stage_log=stage_log,
            )
            mode_art = {
                "slices_dir": rel_path(result.slices_dir, root),
                "manifest": rel_path(result.manifest, root),
            }
            return {
                "artifacts": {
                    slice_mode: mode_art,
                    "slices_dir": rel_path(result.slices_dir, root),
                    "manifest": rel_path(result.manifest, root),
                },
                "params": {
                    "mode": mode,
                    "active_slice_mode": slice_mode,
                    "slice_count": result.slice_count,
                    **{
                        k: params[k]
                        for k in (
                            "vad_threshold",
                            "min_speech_ms",
                            "min_silence_ms",
                            "speech_pad_ms",
                            "boundary_mode",
                            "search_margin_ms",
                            "onset_min_lead_silence_ms",
                            "min_slice_ms",
                            "onset_energy_threshold_db",
                            "safety_margin_ms",
                            "g2p_preroll_ms",
                            "boundary_zcr_weight",
                            "phoneme_align_mode",
                            "phoneme_align_fallback_only",
                            "phoneme_align_remote_url",
                            "phoneme_align_remote_timeout_s",
                        )
                        if k in params
                    },
                },
            }

        if stage == StageName.CONVERT:
            mode = params.get("mode") or inputs.get("mode", ConvertMode.SLICE_BATCH.value)
            slice_mode = paths.normalize_slice_mode(
                inputs.get("slice_mode") or params.get("active_slice_mode") or params.get("slice_mode")
            )
            slice_ids = params.get("slice_ids")
            if isinstance(slice_ids, str):
                slice_ids = [part.strip() for part in slice_ids.split(",") if part.strip()]
            reference = _abs("reference")
            assert reference is not None
            result = run_convert(
                project_id,
                mode=mode,
                source_vocals=_abs("source_vocals"),
                reference=reference,
                slices_dir=_abs("slices_dir"),
                manifest=_abs("manifest"),
                output_dir=_abs("output_dir"),
                output_path=_abs("output_path"),
                slice_mode=slice_mode,
                diffusion_steps=int(params.get("diffusion_steps", 40)),
                length_adjust=float(params.get("length_adjust", 1.0)),
                inference_cfg_rate=float(params.get("inference_cfg_rate", 0.7)),
                auto_f0_adjust=bool(params.get("auto_f0_adjust", True)),
                semi_tone_shift=int(params.get("semi_tone_shift", 0)),
                fp16=bool(params.get("fp16", True)),
                skip_existing=bool(params.get("skip_existing", True)),
                limit=int(params.get("limit", 0)),
                slice_ids=slice_ids,
                overrides_path=_abs("overrides_path"),
                on_progress=on_progress,
                stage_log=stage_log,
            )
            artifacts: dict[str, Any] = {}
            if mode == ConvertMode.SLICE_BATCH.value:
                mode_art = {"converted_dir": rel_path(result.converted_dir, root)}
                artifacts[slice_mode] = mode_art
                artifacts["converted_dir"] = rel_path(result.converted_dir, root)
            if result.full_track:
                artifacts["full_track"] = rel_path(result.full_track, root)
            convert_param_keys = [p.key for p in params_for_stage(StageName.CONVERT.value)]
            return {
                "artifacts": artifacts,
                "params": {
                    "mode": mode,
                    "active_slice_mode": slice_mode,
                    "converted_count": result.converted_count,
                    "total_count": result.total_count,
                    **{k: params[k] for k in convert_param_keys if k in params},
                    **({k: params[k] for k in ("reference",) if k in params}),
                },
            }

        if stage == StageName.MERGE:
            vocals = _abs("vocals")
            instrumental = _abs("instrumental")
            assert vocals is not None and instrumental is not None
            profile = params.get("profile") or params.get("merge_profile", "full")
            merge_mode = (
                params.get("merge_mode") or inputs.get("merge_mode") or paths.MERGE_WHOLE_TRACK
            )
            slice_mode = paths.normalize_slice_mode(
                inputs.get("slice_mode") or params.get("active_slice_mode") or params.get("slice_mode")
            )
            archive_key = paths.resolve_merged_archive_key(merge_mode, slice_mode)
            manifest = _abs("manifest")
            slices_dir = _abs("slices_dir")
            if vocals.is_file():
                manifest = None
                slices_dir = None
            merge_out = _abs("output_dir") or paths.resolve_merged_output_dir(
                project_id, merge_mode, slice_mode
            )
            result = run_merge(
                project_id,
                vocals,
                instrumental,
                merge_out,
                profile=profile,
                reference=_abs("reference"),
                original_vocals=_abs("original_vocals"),
                manifest=manifest,
                slices_dir=slices_dir,
                clean_instrumental=bool(params.get("clean_instrumental", False)),
                vocals_gain_db=float(params.get("vocals_gain_db", params.get("vocals_gain", 0.0))),
                instrumental_gain_db=float(
                    params.get("instrumental_gain_db", params.get("instrumental_gain", 0.0))
                ),
                skip_mastering=bool(params.get("skip_mastering", False)),
                boundary_crossfade_ms=int(params.get("boundary_crossfade_ms", 0)),
                boundary_crossfade_curve=str(
                    params.get("boundary_crossfade_curve", "equal_power")
                ),
                boundary_zero_crossing=bool(params.get("boundary_zero_crossing", True)),
                boundary_lufs_match_ms=int(params.get("boundary_lufs_match_ms", 0)),
                splice_wsola_search_ms=int(params.get("splice_wsola_search_ms", 0)),
                on_progress=on_progress,
                stage_log=stage_log,
            )
            mode_art = {
                "merged_dir": rel_path(result.merged_dir, root),
                "vocals": rel_path(result.vocals, root),
                "mixed": rel_path(result.mixed, root),
            }
            return {
                "artifacts": {
                    archive_key: mode_art,
                    "merged_dir": rel_path(result.merged_dir, root),
                    "vocals": rel_path(result.vocals, root),
                    "mixed": rel_path(result.mixed, root),
                },
                "params": {
                    "profile": profile,
                    "merge_mode": merge_mode,
                    "active_slice_mode": slice_mode,
                    **{
                        k: params[k]
                        for k in (
                            "vocals_gain_db",
                            "instrumental_gain_db",
                            "clean_instrumental",
                            "skip_mastering",
                            "boundary_crossfade_ms",
                            "boundary_crossfade_curve",
                            "boundary_zero_crossing",
                            "boundary_lufs_match_ms",
                            "splice_wsola_search_ms",
                        )
                        if k in params
                    },
                },
            }

        raise ValueError(f"unknown stage: {stage}")

    def _finalize_stage(
        self,
        project_id: str,
        stage: StageName,
        job_result: JobResult,
        inputs: dict[str, Any],
        params: dict[str, Any],
    ) -> StageResult:
        if job_result.status != JobStatus.COMPLETED:
            error = job_result.error or "stage failed"
            self.store.update_stage(project_id, stage, status=StageStatus.FAILED, error=error)
            return StageResult(project_id, stage, False, error=error)

        payload = job_result.result
        if not isinstance(payload, dict):
            error = "stage returned invalid result"
            self.store.update_stage(project_id, stage, status=StageStatus.FAILED, error=error)
            return StageResult(project_id, stage, False, error=error)

        artifacts = payload.get("artifacts", {})
        stage_params = {**params, **payload.get("params", {})}
        for key in _RESOLVED_INPUT_KEYS:
            if key in inputs:
                stage_params[key] = inputs[key]
        self.store.update_stage(
            project_id,
            stage,
            status=StageStatus.DONE,
            params=stage_params,
            artifacts=artifacts,
            error=None,
        )
        return StageResult(project_id, stage, True, artifacts=artifacts)
