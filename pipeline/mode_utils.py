"""Mode helpers without Gradio dependencies."""

from __future__ import annotations


def mode_from_tab_index(index: int | float | str | None, modes: list[str], default: str) -> str:
    """Map a tab selected index to a mode string."""
    try:
        return modes[int(index)]
    except (TypeError, ValueError, IndexError):
        return default


def tab_index_for_mode(mode: str, modes: list[str], default: int = 0) -> int:
    """Map a mode string to the corresponding tab index."""
    try:
        return modes.index(mode)
    except ValueError:
        return default
