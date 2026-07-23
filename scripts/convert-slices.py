"""Batch voice conversion for vocal slices using Seed-VC V1 (f0-conditioned)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parent.parent
SEED_VC_DIR = ROOT / "seed-vc"
DEFAULT_REFERENCE = SEED_VC_DIR / "examples" / "reference" / "dingzhen_0.wav"


def _ensure_seed_vc_path() -> None:
    seed_vc = str(SEED_VC_DIR)
    if seed_vc not in sys.path:
        sys.path.insert(0, seed_vc)
    os.chdir(seed_vc)
    os.environ.setdefault("HF_HUB_CACHE", "./checkpoints/hf_cache")


def _build_args(
    diffusion_steps: int,
    length_adjust: float,
    inference_cfg_rate: float,
    auto_f0_adjust: bool,
    semi_tone_shift: int,
    fp16: bool,
):
    from argparse import Namespace

    return Namespace(
        f0_condition=True,
        checkpoint=None,
        config=None,
        diffusion_steps=diffusion_steps,
        length_adjust=length_adjust,
        inference_cfg_rate=inference_cfg_rate,
        auto_f0_adjust=auto_f0_adjust,
        semi_tone_shift=semi_tone_shift,
        fp16=fp16,
    )


@torch.no_grad()
def _convert_audio(
    source_path: Path,
    reference_path: Path,
    models,
    args,
) -> tuple[np.ndarray, int]:
    import librosa
    import torch
    import torchaudio

    from inference import adjust_f0_semitones, crossfade

    model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = models
    device = next(model["cfm"].estimator.parameters()).device
    fp16 = args.fp16  # noqa: F841 - used in autocast below
    sr = mel_fn_args["sampling_rate"]
    hop_length = 512
    max_context_window = sr // hop_length * 30
    overlap_frame_len = 16
    overlap_wave_len = overlap_frame_len * hop_length

    source_audio = librosa.load(str(source_path), sr=sr)[0]
    ref_audio = librosa.load(str(reference_path), sr=sr)[0]

    source_audio = torch.tensor(source_audio).unsqueeze(0).float().to(device)
    ref_audio = torch.tensor(ref_audio[: sr * 25]).unsqueeze(0).float().to(device)

    converted_waves_16k = torchaudio.functional.resample(source_audio, sr, 16000)
    if converted_waves_16k.size(-1) <= 16000 * 30:
        s_alt = semantic_fn(converted_waves_16k)
    else:
        overlapping_time = 5
        s_alt_list = []
        buffer = None
        traversed_time = 0
        while traversed_time < converted_waves_16k.size(-1):
            if buffer is None:
                chunk = converted_waves_16k[:, traversed_time : traversed_time + 16000 * 30]
            else:
                chunk = torch.cat(
                    [
                        buffer,
                        converted_waves_16k[
                            :, traversed_time : traversed_time + 16000 * (30 - overlapping_time)
                        ],
                    ],
                    dim=-1,
                )
            chunk_s_alt = semantic_fn(chunk)
            if traversed_time == 0:
                s_alt_list.append(chunk_s_alt)
            else:
                s_alt_list.append(chunk_s_alt[:, 50 * overlapping_time :])
            buffer = chunk[:, -16000 * overlapping_time :]
            traversed_time += (
                30 * 16000 if traversed_time == 0 else chunk.size(-1) - 16000 * overlapping_time
            )
        s_alt = torch.cat(s_alt_list, dim=1)

    ori_waves_16k = torchaudio.functional.resample(ref_audio, sr, 16000)
    s_ori = semantic_fn(ori_waves_16k)

    mel = mel_fn(source_audio.to(device).float())
    mel2 = mel_fn(ref_audio.to(device).float())

    target_lengths = torch.LongTensor([int(mel.size(2) * args.length_adjust)]).to(mel.device)
    target2_lengths = torch.LongTensor([mel2.size(2)]).to(mel2.device)

    feat2 = torchaudio.compliance.kaldi.fbank(
        ori_waves_16k,
        num_mel_bins=80,
        dither=0,
        sample_frequency=16000,
    )
    feat2 = feat2 - feat2.mean(dim=0, keepdim=True)
    style2 = campplus_model(feat2.unsqueeze(0))

    f0_ori = f0_fn(ori_waves_16k[0], thred=0.03)
    f0_alt = f0_fn(converted_waves_16k[0], thred=0.03)

    f0_ori = torch.from_numpy(f0_ori).to(device)[None]
    f0_alt = torch.from_numpy(f0_alt).to(device)[None]

    voiced_f0_ori = f0_ori[f0_ori > 1]
    voiced_f0_alt = f0_alt[f0_alt > 1]

    log_f0_alt = torch.log(f0_alt + 1e-5)
    voiced_log_f0_ori = torch.log(voiced_f0_ori + 1e-5)
    voiced_log_f0_alt = torch.log(voiced_f0_alt + 1e-5)
    median_log_f0_ori = torch.median(voiced_log_f0_ori)
    median_log_f0_alt = torch.median(voiced_log_f0_alt)

    shifted_log_f0_alt = log_f0_alt.clone()
    if args.auto_f0_adjust:
        shifted_log_f0_alt[f0_alt > 1] = (
            log_f0_alt[f0_alt > 1] - median_log_f0_alt + median_log_f0_ori
        )
    shifted_f0_alt = torch.exp(shifted_log_f0_alt)
    if args.semi_tone_shift != 0:
        shifted_f0_alt[f0_alt > 1] = adjust_f0_semitones(
            shifted_f0_alt[f0_alt > 1], args.semi_tone_shift
        )

    cond, _, _, _, _ = model.length_regulator(
        s_alt, ylens=target_lengths, n_quantizers=3, f0=shifted_f0_alt
    )
    prompt_condition, _, _, _, _ = model.length_regulator(
        s_ori, ylens=target2_lengths, n_quantizers=3, f0=f0_ori
    )

    max_source_window = max_context_window - mel2.size(2)
    processed_frames = 0
    generated_wave_chunks = []
    previous_chunk = None

    while processed_frames < cond.size(1):
        chunk_cond = cond[:, processed_frames : processed_frames + max_source_window]
        is_last_chunk = processed_frames + max_source_window >= cond.size(1)
        cat_condition = torch.cat([prompt_condition, chunk_cond], dim=1)
        with torch.autocast(
            device_type=device.type, dtype=torch.float16 if fp16 else torch.float32
        ):
            vc_target = model.cfm.inference(
                cat_condition,
                torch.LongTensor([cat_condition.size(1)]).to(mel2.device),
                mel2,
                style2,
                None,
                args.diffusion_steps,
                inference_cfg_rate=args.inference_cfg_rate,
            )
            vc_target = vc_target[:, :, mel2.size(-1) :]
        vc_wave = vocoder_fn(vc_target.float()).squeeze()
        vc_wave = vc_wave[None, :]

        if processed_frames == 0:
            if is_last_chunk:
                generated_wave_chunks.append(vc_wave[0].cpu().numpy())
                break
            generated_wave_chunks.append(vc_wave[0, :-overlap_wave_len].cpu().numpy())
            previous_chunk = vc_wave[0, -overlap_wave_len:]
            processed_frames += vc_target.size(2) - overlap_frame_len
        elif is_last_chunk:
            generated_wave_chunks.append(
                crossfade(previous_chunk.cpu().numpy(), vc_wave[0].cpu().numpy(), overlap_wave_len)
            )
            break
        else:
            generated_wave_chunks.append(
                crossfade(
                    previous_chunk.cpu().numpy(),
                    vc_wave[0, :-overlap_wave_len].cpu().numpy(),
                    overlap_wave_len,
                )
            )
            previous_chunk = vc_wave[0, -overlap_wave_len:]
            processed_frames += vc_target.size(2) - overlap_frame_len

    waveform = np.concatenate(generated_wave_chunks).astype(np.float32)
    return waveform, sr


def _collect_slice_files(slices_dir: Path, manifest: Path | None) -> list[Path]:
    if manifest and manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return [slices_dir / item["file"] for item in data["slices"]]
    return sorted(
        list(slices_dir.glob("*.flac"))
        + list(slices_dir.glob("*.wav"))
        + list(slices_dir.glob("*.mp3"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch convert vocal slices with Seed-VC")
    parser.add_argument("slices_dir", type=Path, help="Directory containing source vocal slices")
    parser.add_argument(
        "--reference",
        type=Path,
        default=DEFAULT_REFERENCE,
        help="Reference voice audio (default: dingzhen_0.wav)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: output/converted/<slices_dir.name>/)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="manifest.json path (default: <slices_dir>/manifest.json if present)",
    )
    parser.add_argument("--diffusion-steps", type=int, default=40)
    parser.add_argument("--length-adjust", type=float, default=1.0)
    parser.add_argument("--inference-cfg-rate", type=float, default=0.7)
    parser.add_argument("--auto-f0-adjust", action="store_true", default=True)
    parser.add_argument("--no-auto-f0-adjust", action="store_false", dest="auto_f0_adjust")
    parser.add_argument("--semi-tone-shift", type=int, default=0)
    parser.add_argument("--fp16", action="store_true", default=True)
    parser.add_argument("--no-fp16", action="store_false", dest="fp16")
    parser.add_argument("--limit", type=int, default=0, help="Only convert first N slices (0 = all)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip slices with output present")
    args = parser.parse_args()

    slices_dir = args.slices_dir.resolve()
    if not slices_dir.is_dir():
        print(f"Error: slices directory not found: {slices_dir}", file=sys.stderr)
        return 1

    reference = args.reference.resolve()
    if not reference.is_file():
        print(f"Error: reference audio not found: {reference}", file=sys.stderr)
        return 1

    manifest = args.manifest.resolve() if args.manifest else slices_dir / "manifest.json"
    if not manifest.exists():
        manifest = None

    output_dir = args.output.resolve() if args.output else ROOT / "output" / "converted" / slices_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    slice_files = _collect_slice_files(slices_dir, manifest)
    if args.limit > 0:
        slice_files = slice_files[: args.limit]
    if not slice_files:
        print(f"Error: no slice files found in {slices_dir}", file=sys.stderr)
        return 1

    print(f"Slices dir : {slices_dir}")
    print(f"Reference  : {reference}")
    print(f"Output dir : {output_dir}")
    print(f"Total slices: {len(slice_files)}")

    _ensure_seed_vc_path()
    from inference import load_models

    model_args = _build_args(
        diffusion_steps=args.diffusion_steps,
        length_adjust=args.length_adjust,
        inference_cfg_rate=args.inference_cfg_rate,
        auto_f0_adjust=args.auto_f0_adjust,
        semi_tone_shift=args.semi_tone_shift,
        fp16=args.fp16,
    )

    print("Loading Seed-VC models...")
    t0 = time.time()
    models = load_models(model_args)
    print(f"Models loaded in {time.time() - t0:.1f}s")

    ok = 0
    for idx, source_path in enumerate(slice_files, start=1):
        out_path = output_dir / source_path.name
        if args.skip_existing and out_path.exists():
            print(f"[{idx}/{len(slice_files)}] skip existing: {out_path.name}")
            ok += 1
            continue

        print(f"[{idx}/{len(slice_files)}] converting {source_path.name} ...", flush=True)
        start = time.time()
        try:
            waveform, sr = _convert_audio(source_path, reference, models, model_args)
            sf.write(str(out_path), waveform, sr, subtype="PCM_16")
            elapsed = time.time() - start
            rtf = elapsed / (len(waveform) / sr) if len(waveform) else 0.0
            print(f"  -> saved {out_path.name} ({elapsed:.1f}s, RTF={rtf:.2f})")
            ok += 1
        except Exception as exc:
            print(f"  !! failed {source_path.name}: {exc}", file=sys.stderr)

    print(f"Done: {ok}/{len(slice_files)} slices converted -> {output_dir}")
    return 0 if ok == len(slice_files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
