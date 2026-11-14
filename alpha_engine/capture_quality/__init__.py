"""Phase 11 capture-quality helpers (INACTIVE: pure functions, no I/O, not wired into any workflow).

Research only. Nothing here fetches data, writes archives, places orders or changes a pinned release.
"""
from .availability import classify_availability_capture, is_placeholder_availability_row
from .history import build_status_history, diff_status_snapshots
from .status import classify_lineup_status

__all__ = [
    "classify_availability_capture",
    "is_placeholder_availability_row",
    "build_status_history",
    "diff_status_snapshots",
    "classify_lineup_status",
]
