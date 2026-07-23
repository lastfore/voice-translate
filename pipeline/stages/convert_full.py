"""Single-file full-track voice conversion (Seed-VC subprocess entrypoint)."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_convert_slices():
    script = ROOT / "scripts" / "convert-slices.py"
    spec = importlib.util.spec_from_file_location("convert_slices_script", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["convert_slices_script"] = module
    spec.loader.exec_module(module)
    return module


def convert_full_track(
    source: Path,
    reference: Path,
    output: Path,
    *,
    diffusion_steps: int = 40,
    length_adjust: float = 1.0,
    inference_cfg_rate: float = 0.7,
    auto_f0_adjust: bool = True,
    semi_tone_shift: int = 0,
    fp16: bool = True,
) -> Path:
    source = source.resolve()
    reference = reference.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not reference.is_file():
        raise FileNotFoundError(reference)

    mod = _load_convert_slices()
    mod._ensure_seed_vc_path()
    from inference import load_models

    model_args = mod._build_args(
        diffusion_steps=diffusion_steps,
        length_adjust=length_adjust,
        inference_cfg_rate=inference_cfg_rate,
        auto_f0_adjust=auto_f0_adjust,
        semi_tone_shift=semi_tone_shift,
        fp16=fp16,
    )
    models = load_models(model_args)
    waveform, sr = mod._convert_audio(source, reference, models, model_args)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), waveform, sr, subtype="PCM_16")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a single vocal track with Seed-VC")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diffusion-steps", type=int, default=40)
    parser.add_argument("--length-adjust", type=float, default=1.0)
    parser.add_argument("--inference-cfg-rate", type=float, default=0.7)
    parser.add_argument("--auto-f0-adjust", action="store_true", default=True)
    parser.add_argument("--no-auto-f0-adjust", action="store_false", dest="auto_f0_adjust")
    parser.add_argument("--semi-tone-shift", type=int, default=0)
    parser.add_argument("--fp16", action="store_true", default=True)
    parser.add_argument("--no-fp16", action="store_false", dest="fp16")
    args = parser.parse_args()

    try:
        out = convert_full_track(
            args.source,
            args.reference,
            args.output,
            diffusion_steps=args.diffusion_steps,
            length_adjust=args.length_adjust,
            inference_cfg_rate=args.inference_cfg_rate,
            auto_f0_adjust=args.auto_f0_adjust,
            semi_tone_shift=args.semi_tone_shift,
            fp16=args.fp16,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
