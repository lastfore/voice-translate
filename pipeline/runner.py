"""Stage execution orchestration."""

from __future__ import annotations

import queue
import threading
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
from pipeline.stages.convert import run_convert
from pipeline.stages.merge import run_merge
from pipeline.stages.separate import run_separate
from pipeline.stages.slice import run_slice
from pipeline.store import ProjectStore


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
    ) -> StageResult:
        params = dict(params or {})
        inputs = self.store.resolve_stage_inputs(project_id, stage, params)
        ok, errors = self.store.validate_stage_inputs(stage, inputs)
        if not ok:
            return StageResult(project_id, stage, False, error="; ".join(errors))

        self.store.save_stage_inputs(project_id, stage, inputs)
        job_id = self.queue.new_job_id(stage.value)
        log_path = paths.project_logs_dir(project_id) / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        self.store.update_stage(project_id, stage, status=StageStatus.RUNNING, error=None)
        self.store.add_job(
            project_id,
            Job(
                job_id=job_id,
                type="stage",
                stage=stage,
                status=JobStatus.QUEUED,
                created_at=utc_now_iso(),
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

        def _work() -> dict[str, Any]:
            return self._execute_stage(project_id, stage, inputs, params, _log)

        self.queue.enqueue(
            Job(job_id=job_id, type="stage", stage=stage, status=JobStatus.QUEUED, created_at=utc_now_iso()),
            _work,
        )
        job_result = self.queue.wait(job_id)
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
        slice_mode: SliceMode = SliceMode.LRC,
        stop_on_error: bool = True,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        **params: Any,
    ) -> PipelineResult:
        chain = stages or list(StageName)
        ok, plan_or_errors = self.store.validate_pipeline_chain(
            project_id,
            chain,
            convert_mode=convert_mode,
            slice_mode=slice_mode,
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
            if stage == StageName.SLICE:
                stage_params.setdefault("mode", slice_mode.value)
            if stage == StageName.CONVERT:
                stage_params.setdefault("mode", convert_mode.value)

            result = self.run_stage(project_id, stage, stage_params, on_progress=on_progress)
            results.append(result)
            if not result.success:
                if stop_on_error:
                    return PipelineResult(project_id, False, stage_results=results, error=result.error)
        return PipelineResult(project_id, True, stage_results=results)

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
            out_dir = _abs("output_dir") or paths.slices_dir(project_id)
            assert vocals is not None
            mode = inputs.get("mode") or params.get("mode", SliceMode.VAD.value)
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
                on_progress=on_progress,
            )
            return {
                "artifacts": {
                    "slices_dir": rel_path(result.slices_dir, root),
                    "manifest": rel_path(result.manifest, root),
                },
                "params": {
                    "mode": mode,
                    "slice_count": result.slice_count,
                    **{
                        k: params[k]
                        for k in (
                            "vad_threshold",
                            "min_speech_ms",
                            "min_silence_ms",
                            "speech_pad_ms",
                        )
                        if k in params
                    },
                },
            }

        if stage == StageName.CONVERT:
            mode = inputs.get("mode") or params.get("mode", ConvertMode.SLICE_BATCH.value)
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
                diffusion_steps=int(params.get("diffusion_steps", 40)),
                length_adjust=float(params.get("length_adjust", 1.0)),
                inference_cfg_rate=float(params.get("inference_cfg_rate", 0.7)),
                auto_f0_adjust=bool(params.get("auto_f0_adjust", True)),
                semi_tone_shift=int(params.get("semi_tone_shift", 0)),
                fp16=bool(params.get("fp16", True)),
                skip_existing=bool(params.get("skip_existing", True)),
                limit=int(params.get("limit", 0)),
                on_progress=on_progress,
            )
            artifacts: dict[str, Any] = {
                "converted_dir": rel_path(result.converted_dir, root),
            }
            if result.full_track:
                artifacts["full_track"] = rel_path(result.full_track, root)
            return {
                "artifacts": artifacts,
                "params": {
                    "mode": mode,
                    "converted_count": result.converted_count,
                    "total_count": result.total_count,
                    **{k: params[k] for k in ("diffusion_steps", "reference") if k in params},
                },
            }

        if stage == StageName.MERGE:
            vocals = _abs("vocals")
            instrumental = _abs("instrumental")
            assert vocals is not None and instrumental is not None
            profile = params.get("profile") or params.get("merge_profile", "full")
            manifest = _abs("manifest")
            slices_dir = _abs("slices_dir")
            if vocals.is_file():
                manifest = None
                slices_dir = None
            result = run_merge(
                project_id,
                vocals,
                instrumental,
                _abs("output_dir") or paths.merged_dir(project_id),
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
                on_progress=on_progress,
            )
            return {
                "artifacts": {
                    "merged_dir": rel_path(result.merged_dir, root),
                    "vocals": rel_path(result.vocals, root),
                    "mixed": rel_path(result.mixed, root),
                },
                "params": {
                    "profile": profile,
                    **{
                        k: params[k]
                        for k in (
                            "vocals_gain_db",
                            "instrumental_gain_db",
                            "clean_instrumental",
                            "skip_mastering",
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
        stage_params = {**inputs, **payload.get("params", {}), **params}
        self.store.update_stage(
            project_id,
            stage,
            status=StageStatus.DONE,
            params=stage_params,
            artifacts=artifacts,
            error=None,
        )
        return StageResult(project_id, stage, True, artifacts=artifacts)
