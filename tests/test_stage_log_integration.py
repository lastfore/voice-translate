"""Integration tests for stage logging — Phases 2–5."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import paths
from pipeline.models import JobStatus, StageName, StageStatus
from pipeline.queue import GpuJobQueue
from pipeline.runner import StageRunner
from pipeline.stages.convert import ConvertResult
from pipeline.stages.merge import MergeResult
from pipeline.stages.separate import SeparateResult
from pipeline.stages.slice import SliceResult
from pipeline.store import ProjectStore


@pytest.fixture
def runner_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjectStore, StageRunner, str, Path]:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    root = tmp_path
    (root / "input").mkdir()
    (root / "output" / "separated").mkdir(parents=True)
    mix = root / "input" / "song.flac"
    mix.write_bytes(b"audio")
    store = ProjectStore(root)
    store.create_project("song", mix)
    runner = StageRunner(store, GpuJobQueue())
    return store, runner, "song", root


def _latest_log(root: Path, project_id: str) -> Path:
    log_dir = paths.project_logs_dir(project_id)
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
    assert logs, f"no log files in {log_dir}"
    return logs[-1]


def test_job_header_written_before_stage_runs(runner_workspace) -> None:
    """P2-TC-001: [JOB]/[INPUT]/[PARAM] exist before worker completes."""
    _, runner, pid, root = runner_workspace
    mix = root / "input" / "song.flac"
    gate = threading.Event()

    def _slow_separate(*args, **kwargs):
        gate.wait(timeout=5)
        vocals = root / "output" / "separated" / "v.flac"
        inst = root / "output" / "separated" / "i.flac"
        vocals.write_bytes(b"v")
        inst.write_bytes(b"i")
        return SeparateResult(vocals=vocals, instrumental=inst)

    def _run():
        with patch("pipeline.runner.run_separate", side_effect=_slow_separate):
            runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": str(mix)})

    th = threading.Thread(target=_run)
    th.start()

    deadline = time.time() + 3
    found = False
    while time.time() < deadline:
        log_dir = paths.project_logs_dir(pid)
        for log_file in log_dir.glob("*.log"):
            text = log_file.read_text(encoding="utf-8")
            if "[JOB]" in text and "[INPUT]" in text and "[PARAM]" in text:
                found = True
                break
        if found:
            break
        time.sleep(0.05)

    assert found, "header not written before stage execution"
    gate.set()
    th.join(timeout=10)


def test_queue_wait_ms_in_log(runner_workspace) -> None:
    """P2-TC-002: started_at and queue_wait_ms appear in log."""
    _, runner, pid, root = runner_workspace
    mix = root / "input" / "song.flac"
    time.sleep(0.05)

    def _fake(*a, **k):
        vocals = root / "output" / "separated" / "v.flac"
        inst = root / "output" / "separated" / "i.flac"
        vocals.write_bytes(b"v")
        inst.write_bytes(b"i")
        return SeparateResult(vocals=vocals, instrumental=inst)

    with patch("pipeline.runner.run_separate", side_effect=_fake):
        result = runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": str(mix)})

    assert result.success
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "started_at=" in text
    assert "queue_wait_ms=" in text


def test_failure_writes_err_and_footer(runner_workspace) -> None:
    """P2-TC-003: stage exception produces [ERR] and success=false footer."""
    _, runner, pid, root = runner_workspace
    mix = root / "input" / "song.flac"

    with patch("pipeline.runner.run_separate", side_effect=RuntimeError("boom")):
        result = runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": str(mix)})

    assert not result.success
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[ERR]" in text
    assert "success=false" in text


def test_cancel_writes_footer(runner_workspace) -> None:
    """P2-TC-004: cancellation still writes job footer."""
    import sys

    from pipeline import venv_runner

    _, runner, pid, root = runner_workspace
    mix = root / "input" / "song.flac"
    job_ids: list[str] = []
    sleep_cmd = [sys.executable, "-c", "import time; time.sleep(30)"]

    def _blocking_separate(*a, **k):
        for _ in venv_runner.iter_subprocess_lines(sleep_cmd):
            pass
        return SeparateResult(vocals=Path("v"), instrumental=Path("i"))

    def _run():
        with patch("pipeline.runner.run_separate", side_effect=_blocking_separate):
            runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": str(mix)}, on_job_id=job_ids.append)

    th = threading.Thread(target=_run)
    th.start()
    deadline = time.time() + 5
    while time.time() < deadline and not job_ids:
        time.sleep(0.02)
    assert job_ids
    time.sleep(0.1)
    runner.cancel(job_ids[0])
    th.join(timeout=10)

    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "success=false" in text


def test_separate_log_has_cmd_proc_out(runner_workspace) -> None:
    """P3-TC-001: separate logs [CMD], [PROC], [OUT]."""
    _, runner, pid, root = runner_workspace
    mix = root / "input" / "song.flac"
    captured_log = {}

    def _fake_separate(project_id, mix_audio, *, model, on_progress=None, stage_log=None, **kw):
        if stage_log:
            stage_log.cmd(["python", "sep"], cwd=str(root), python="python")
            stage_log.line("Processing 50%")
        vocals = root / "output" / "separated" / "v.flac"
        inst = root / "output" / "separated" / "i.flac"
        vocals.write_bytes(b"v")
        inst.write_bytes(b"i")
        captured_log["stage_log"] = stage_log
        return SeparateResult(vocals=vocals, instrumental=inst)

    with patch("pipeline.runner.run_separate", side_effect=_fake_separate):
        result = runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": str(mix)})

    assert result.success
    assert captured_log["stage_log"] is not None
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert text.count("[CMD]") >= 3
    assert "[PROC]" in text
    assert "[OUT] vocals=" in text
    assert "[OUT] instrumental=" in text


def test_convert_slice_batch_log_context(runner_workspace) -> None:
    """P3-TC-002: convert slice_batch logs inputs, params, cmd, outputs."""
    store, runner, pid, root = runner_workspace
    ref = root / "input" / pid / "reference.wav"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"r")
    slices_dir = root / "output" / "slices" / pid / "lrc"
    slices_dir.mkdir(parents=True)
    (slices_dir / "manifest.json").write_text("{}", encoding="utf-8")
    out_dir = root / "output" / "converted" / pid / "lrc"
    out_dir.mkdir(parents=True)

    def _fake_convert(*args, **kwargs):
        sl = kwargs.get("stage_log")
        if sl:
            sl.cmd(["py", "convert-slices.py"], cwd=str(root), python="py")
        return ConvertResult(mode="slice_batch", converted_dir=out_dir, converted_count=2, total_count=2)

    params = {
        "mode": "slice_batch",
        "reference": str(ref),
        "slices_dir": str(slices_dir),
        "manifest": str(slices_dir / "manifest.json"),
        "output_dir": str(out_dir),
        "length_adjust": 1.05,
    }
    with patch("pipeline.runner.run_convert", side_effect=_fake_convert):
        result = runner.run_stage(pid, StageName.CONVERT, params)

    assert result.success
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[INPUT] reference=" in text
    assert "[INPUT] slices_dir=" in text
    assert "[PARAM]" in text
    assert "[CMD]" in text
    assert "converted_count=2/2" in text


def test_convert_full_track_output_path(runner_workspace) -> None:
    """P3-TC-003: full_track mode logs output_path and full_track out."""
    _, runner, pid, root = runner_workspace
    ref = root / "input" / pid / "reference.wav"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"r")
    vocals = root / "output" / "separated" / "v.flac"
    vocals.write_bytes(b"v")
    out_path = root / "output" / "converted" / pid / "full.flac"
    out_path.parent.mkdir(parents=True)

    def _fake(*args, **kwargs):
        sl = kwargs.get("stage_log")
        if sl:
            sl.cmd(["py", "convert_full"], python="py")
        return ConvertResult(
            mode="full_track",
            converted_dir=out_path.parent,
            full_track=out_path,
            converted_count=1,
            total_count=1,
        )

    with patch("pipeline.runner.run_convert", side_effect=_fake):
        result = runner.run_stage(
            pid,
            StageName.CONVERT,
            {
                "mode": "full_track",
                "reference": str(ref),
                "source_vocals": str(vocals),
                "output_path": str(out_path),
            },
        )

    assert result.success
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[INPUT] output_path=" in text
    assert "[OUT] full_track=" in text


def test_stage_log_none_backward_compatible() -> None:
    """P3-TC-004: run_separate/run_convert work without stage_log."""
    from pipeline.stages.convert import run_convert
    from pipeline.stages.separate import run_separate

    assert "stage_log" in run_separate.__code__.co_varnames
    assert "stage_log" in run_convert.__code__.co_varnames


def test_slice_lrc_exec_context(runner_workspace) -> None:
    """P4-TC-001: slice LRC writes [EXEC] handler context."""
    _, runner, pid, root = runner_workspace
    vocals = root / "output" / "separated" / "v.flac"
    vocals.write_bytes(b"v")
    lrc = root / "input" / "song.lrc"
    lrc.write_text("[00:00.00]line", encoding="utf-8")
    slices_dir = root / "output" / "slices" / pid / "lrc"
    manifest = slices_dir / "manifest.json"

    exec_lines: list[str] = []

    def _fake_slice(*args, **kwargs):
        sl = kwargs.get("stage_log")
        if sl:
            sl.exec_context(handler="scripts/slice-vocals-lrc.py", mode="lrc")
            exec_lines.append("exec")
        slices_dir.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}", encoding="utf-8")
        return SliceResult(slices_dir=slices_dir, manifest=manifest, slice_count=1)

    with patch("pipeline.runner.run_slice", side_effect=_fake_slice):
        result = runner.run_stage(
            pid,
            StageName.SLICE,
            {
                "vocals": str(vocals),
                "mode": "lrc",
                "lrc": str(lrc),
                "search_margin_ms": 350,
                "onset_min_lead_silence_ms": 90,
            },
        )

    assert result.success
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[EXEC]" in text
    assert "slice-vocals-lrc.py" in text
    assert text.count("[INPUT]") >= 1
    assert "[PARAM] lrc:" in text
    assert "boundary_mode=onset_aligned" in text
    assert "search_margin_ms=350" in text
    assert "onset_min_lead_silence_ms=90" in text
    assert "min_slice_ms=500" in text
    assert "onset_energy_threshold_db=-40" in text


def test_slice_lrc_logs_per_boundary_diagnostics(runner_workspace) -> None:
    """Each LRC boundary emits aligned/fallback, method, and reason in the job log."""
    import shutil
    import wave

    import numpy as np

    from tests.test_slice_vocals_lrc import ROOT as REPO_ROOT

    _, runner, pid, root = runner_workspace
    scripts_dst = root / "scripts"
    if not scripts_dst.is_dir():
        shutil.copytree(REPO_ROOT / "scripts", scripts_dst)

    vocals = root / "output" / "separated" / "v.flac"
    vocals.parent.mkdir(parents=True, exist_ok=True)
    lrc = root / "input" / "song.lrc"
    lrc.write_text(
        "[00:10.00]line one\n[00:15.00]line two\n[00:20.00]line three\n",
        encoding="utf-8",
    )

    sr = 44100
    audio = np.full(int(sr * 25), 0.001, dtype=np.float32)
    for onset_ms in (14700.0, 19700.0):
        audio[int(sr * onset_ms / 1000) :] = 0.5
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(vocals), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())

    result = runner.run_stage(
        pid,
        StageName.SLICE,
        {"vocals": str(vocals), "mode": "lrc", "lrc": str(lrc)},
    )
    assert result.success

    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[PROC] [BOUNDARY]" in text
    assert "aligned method=silence_onset reason=aligned_silence" in text
    assert text.count("[PROC] [BOUNDARY]") == 2


def test_slice_vad_exec_shows_vad_params(runner_workspace) -> None:
    """P4-TC-002: VAD slice [EXEC] includes vad_threshold etc."""
    _, runner, pid, root = runner_workspace
    vocals = root / "output" / "separated" / "v.flac"
    vocals.write_bytes(b"v")
    slices_dir = root / "output" / "slices" / pid / "vad"
    manifest = slices_dir / "manifest.json"

    def _fake_slice(*args, **kwargs):
        sl = kwargs.get("stage_log")
        if sl:
            sl.exec_context(
                handler="scripts/slice-vocals.py",
                mode="vad",
                vad_threshold="0.45",
                min_speech_ms="250",
            )
        slices_dir.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}", encoding="utf-8")
        return SliceResult(slices_dir=slices_dir, manifest=manifest, slice_count=1)

    with patch("pipeline.runner.run_slice", side_effect=_fake_slice):
        runner.run_stage(pid, StageName.SLICE, {"vocals": str(vocals), "mode": "vad"})

    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[PARAM] vad:" in text
    assert "vad_threshold=0.45" in text
    assert "min_speech_ms=250" in text
    assert "lrc_path" not in text


def test_merge_exec_and_proc(runner_workspace) -> None:
    """P4-TC-003: merge logs [EXEC] profile and [PROC] script lines."""
    _, runner, pid, root = runner_workspace
    vocals = root / "output" / "converted" / pid / "v.flac"
    vocals.parent.mkdir(parents=True)
    vocals.write_bytes(b"v")
    inst = root / "output" / "separated" / "i.flac"
    inst.write_bytes(b"i")
    merged = root / "output" / "merged" / pid / "full"

    def _fake_merge(*args, **kwargs):
        sl = kwargs.get("stage_log")
        if sl:
            sl.exec_context(handler="scripts/merge-audio.py", profile="full")
            sl.line("mixing track")
        merged.mkdir(parents=True, exist_ok=True)
        v_out = merged / "vocals.flac"
        m_out = merged / "mixed.flac"
        v_out.write_bytes(b"x")
        m_out.write_bytes(b"x")
        return MergeResult(vocals=v_out, mixed=m_out, merged_dir=merged)

    with patch("pipeline.runner.run_merge", side_effect=_fake_merge):
        result = runner.run_stage(
            pid,
            StageName.MERGE,
            {"vocals": str(vocals), "instrumental": str(inst), "profile": "full"},
        )

    assert result.success
    text = _latest_log(root, pid).read_text(encoding="utf-8")
    assert "[EXEC]" in text and "profile=full" in text
    assert "[PROC] mixing track" in text
    assert "[OUT] merged_dir=" in text


def test_runner_only_writes_input_param_once(runner_workspace) -> None:
    """P4-TC-004: stage execution does not call StageLogWriter.inputs/params."""
    from pipeline.stage_log import StageLogWriter

    _, runner, pid, root = runner_workspace
    vocals = root / "output" / "separated" / "v.flac"
    vocals.write_bytes(b"v")
    slices_dir = root / "output" / "slices" / pid / "vad"
    manifest = slices_dir / "manifest.json"

    input_calls = 0
    param_calls = 0
    orig_inputs = StageLogWriter.inputs
    orig_params = StageLogWriter.params

    def _count_inputs(self, mapping):
        nonlocal input_calls
        input_calls += 1
        return orig_inputs(self, mapping)

    def _count_params(self, groups):
        nonlocal param_calls
        param_calls += 1
        return orig_params(self, groups)

    def _fake_slice(*args, **kwargs):
        slices_dir.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}", encoding="utf-8")
        return SliceResult(slices_dir=slices_dir, manifest=manifest, slice_count=1)

    with patch.object(StageLogWriter, "inputs", _count_inputs):
        with patch.object(StageLogWriter, "params", _count_params):
            with patch("pipeline.runner.run_slice", side_effect=_fake_slice):
                runner.run_stage(pid, StageName.SLICE, {"vocals": str(vocals), "mode": "vad"})

    assert input_calls == 1
    assert param_calls == 1


def test_four_stage_pipeline_logs_all_have_footers(runner_workspace) -> None:
    """ALL-TC-001: each stage job log has header and footer."""
    _, runner, pid, root = runner_workspace

    vocals = root / "output" / "separated" / "song_(Vocals)_m.flac"
    inst = root / "output" / "separated" / "song_(Instrumental)_m.flac"
    vocals.parent.mkdir(parents=True, exist_ok=True)
    vocals.write_bytes(b"v")
    inst.write_bytes(b"i")
    slices = root / "output" / "slices" / pid / "lrc"
    slices.mkdir(parents=True, exist_ok=True)
    (slices / "manifest.json").write_text('{"slices":[]}', encoding="utf-8")
    converted = root / "output" / "converted" / pid / "lrc"
    converted.mkdir(parents=True, exist_ok=True)
    (converted / "vocals.flac").write_bytes(b"c")
    merged = root / "output" / "merged" / pid
    merged.mkdir(parents=True, exist_ok=True)
    ref = root / "input" / pid / "reference.wav"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"r")
    lrc = root / "input" / "song.lrc"
    lrc.write_text("[00:00.00]x", encoding="utf-8")

    patches = [
        patch(
            "pipeline.runner.run_separate",
            return_value=SeparateResult(vocals=vocals, instrumental=inst),
        ),
        patch(
            "pipeline.runner.run_slice",
            return_value=SliceResult(slices_dir=slices, manifest=slices / "manifest.json", slice_count=1),
        ),
        patch(
            "pipeline.runner.run_convert",
            return_value=ConvertResult(
                mode="slice_batch", converted_dir=converted, converted_count=1, total_count=1
            ),
        ),
        patch(
            "pipeline.runner.run_merge",
            return_value=MergeResult(
                vocals=merged / "v.flac",
                mixed=merged / "m.flac",
                merged_dir=merged,
            ),
        ),
    ]

    with patches[0], patches[1], patches[2], patches[3]:
        result = runner.run_pipeline(
            pid,
            slice_mode="lrc",
            reference=str(ref),
            lrc=str(lrc),
        )

    assert result.success, result.error

    log_dir = paths.project_logs_dir(pid)
    logs = list(log_dir.glob("*.log"))
    assert len(logs) == 4
    for log_file in logs:
        text = log_file.read_text(encoding="utf-8")
        assert "[JOB] ===" in text
        assert "success=true" in text
        assert "[OUT]" in text
