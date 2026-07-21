"""Verify MelBand-RoFormer checkpoint integrity."""

from __future__ import annotations

import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "separator-env" / "models" / "audio-separator" / "mel_band_roformer_kim_ft_unwa.ckpt"
EXPECTED_SIZE = 913_100_690


def main() -> int:
    if not MODEL_PATH.exists():
        print(f"MISSING: {MODEL_PATH}")
        return 1

    size = MODEL_PATH.stat().st_size
    if size != EXPECTED_SIZE:
        print(f"BAD_SIZE: {size} (expected {EXPECTED_SIZE})")
        return 1

    try:
        torch.load(str(MODEL_PATH), map_location="cpu", weights_only=False)
    except Exception as exc:  # noqa: BLE001 - verification entrypoint
        print(f"CORRUPT: {exc}")
        return 1

    print(f"OK: {MODEL_PATH} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
