"""Subprocess helpers for separator-env and seed-vc-env."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from pipeline.paths import get_root, get_seed_vc_env, get_separator_env

ProgressLineCallback = Callable[[str], None]

# Registry of "currently running subprocess per worker thread". A GpuJobQueue
# serializes work onto a single daemon worker thread, so at most one entry is
# expected to be live per thread at a time. This lets GpuJobQueue.cancel_current()
# (called from a different thread — the async event loop or a thread-pool thread)
# reach into the worker thread and terminate its subprocess without threading the
# Popen handle through every stage function signature.
_process_registry: dict[int, subprocess.Popen] = {}
_registry_lock = threading.Lock()


def _register_process(proc: subprocess.Popen) -> None:
    with _registry_lock:
        _process_registry[threading.get_ident()] = proc


def _unregister_process() -> None:
    with _registry_lock:
        _process_registry.pop(threading.get_ident(), None)


def get_process_for_thread(thread_id: int) -> subprocess.Popen | None:
    with _registry_lock:
        return _process_registry.get(thread_id)


def terminate_process_for_thread(thread_id: int, timeout: float = 5.0) -> bool:
    """Terminate the subprocess currently registered for *thread_id*, if any.

    Returns True if a live process was found and a terminate/kill signal was sent.
    """
    proc = get_process_for_thread(thread_id)
    if proc is None or proc.poll() is not None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
    return True


def separator_python() -> Path:
    exe = get_separator_env() / "Scripts" / "python.exe"
    if exe.is_file():
        return exe
    return Path(sys.executable)


def seed_vc_python() -> Path:
    exe = get_seed_vc_env() / "Scripts" / "python.exe"
    if exe.is_file():
        return exe
    return Path(sys.executable)


_SEPARATOR_CLI_BOOTSTRAP = (
    "import sys; sys.argv[0]='audio-separator'; "
    "from audio_separator.utils.cli import main; main()"
)


def separator_cli_cmd(*args: str | Path) -> list[str]:
    """Invoke audio-separator via python.exe instead of the console-script .exe shim.

    On some Windows setups the uv-generated ``audio-separator.exe`` shim is blocked
    by application control policy; calling the CLI module directly avoids that.
    """
    return [
        str(separator_python()),
        "-c",
        _SEPARATOR_CLI_BOOTSTRAP,
        *[str(a) for a in args],
    ]


def separator_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    root = get_root()
    model_dir = get_separator_env() / "models" / "audio-separator"
    env = os.environ.copy()
    # Subprocesses must not inherit broken proxy settings (common Web UI startup issue).
    env["HTTP_PROXY"] = ""
    env["HTTPS_PROXY"] = ""
    env["ALL_PROXY"] = ""
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    env.setdefault("no_proxy", "127.0.0.1,localhost")
    env.update(
        {
            "TORCH_HOME": str(get_separator_env() / "models" / "torch-hub"),
            "HF_HOME": str(get_separator_env() / "models" / "hf-cache"),
            "AUDIO_SEPARATOR_MODEL_DIR": str(model_dir),
            # phoneme_align local_cpu on Windows CPU: avoid Torch/BLAS thread crash
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "CUDA_VISIBLE_DEVICES": "",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    if extra:
        env.update(extra)
    return env


def run_subprocess(
    cmd: list[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    on_line: ProgressLineCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run command, optionally streaming merged stdout/stderr line-by-line."""
    work_dir = cwd or get_root()
    str_cmd = [str(part) for part in cmd]

    if on_line is None:
        return subprocess.run(
            str_cmd,
            cwd=work_dir,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    proc = subprocess.Popen(
        str_cmd,
        cwd=work_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    _register_process(proc)
    try:
        assert proc.stdout is not None
        lines: list[str] = []
        for line in proc.stdout:
            lines.append(line)
            on_line(line.rstrip("\n"))
        code = proc.wait()
    finally:
        _unregister_process()
    output = "".join(lines)
    return subprocess.CompletedProcess(str_cmd, code, stdout=output, stderr="")


def iter_subprocess_lines(
    cmd: list[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Iterator[str]:
    work_dir = cwd or get_root()
    str_cmd = [str(part) for part in cmd]
    proc = subprocess.Popen(
        str_cmd,
        cwd=work_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    _register_process(proc)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line.rstrip("\n")
        code = proc.wait()
    finally:
        _unregister_process()
    if code != 0:
        raise subprocess.CalledProcessError(code, str_cmd)
