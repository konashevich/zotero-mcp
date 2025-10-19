"""Validate mapping of Windows absolute paths when running on POSIX/Linux.

This simulates a containerized environment where host Windows drives are mounted
under a configurable root (e.g., /host_mnt or /mnt) and verifies that _normalize_path
maps C:\\Users\\... correctly when ZOTERO_HOST_DRIVES_ROOT is set.
"""

from __future__ import annotations

import os
from pathlib import Path

from zotero_mcp import _normalize_path


def test_windows_drive_mapping_on_posix(tmp_path: Path, monkeypatch) -> None:
    # Simulate mounted host drives at tmp_path/host_mnt
    host_root = tmp_path / "host_mnt"
    drive_c = host_root / "c"
    target_dir = drive_c / "Users" / "alice" / "Docs"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "paper.md"

    # Set env var so _normalize_path prefers this root
    monkeypatch.setenv("ZOTERO_HOST_DRIVES_ROOT", str(host_root))

    # Input Windows path
    win_path = r"C:\\Users\\alice\\Docs\\paper.md"

    normalized = _normalize_path(win_path)

    # Should map into the simulated /host_mnt/c/Users/alice/Docs/paper.md
    assert str(normalized).endswith("/c/Users/alice/Docs/paper.md")
    # It doesn't need to exist for normalization, but mapping root exists
    assert normalized.parent.exists()
