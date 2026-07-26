"""Tests for mode tab wiring helpers."""

from __future__ import annotations

from pipeline.mode_utils import mode_from_tab_index, tab_index_for_mode


def test_mode_from_tab_index_maps_valid_indices() -> None:
    modes = ["vad", "lrc"]
    assert mode_from_tab_index(0, modes, "vad") == "vad"
    assert mode_from_tab_index(1, modes, "vad") == "lrc"
    assert mode_from_tab_index("0", modes, "vad") == "vad"


def test_mode_from_tab_index_falls_back_on_invalid() -> None:
    modes = ["vad", "lrc"]
    assert mode_from_tab_index(None, modes, "vad") == "vad"
    assert mode_from_tab_index(99, modes, "vad") == "vad"


def test_tab_index_for_mode() -> None:
    modes = ["vad", "lrc"]
    assert tab_index_for_mode("vad", modes) == 0
    assert tab_index_for_mode("lrc", modes) == 1
    assert tab_index_for_mode("unknown", modes, default=1) == 1
