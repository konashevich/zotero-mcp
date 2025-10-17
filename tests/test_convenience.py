"""Tests for convenience helpers"""

import os
from unittest.mock import patch

from zotero_mcp import open_in_zotero


def test_open_in_zotero_user_default() -> None:
    out = open_in_zotero("K1")
    assert "zotero://select/library/items/K1" in out


def test_open_in_zotero_group_with_id() -> None:
    out = open_in_zotero("K2", libraryId="999", libraryType="group")
    assert "zotero://select/groups/999/items/K2" in out


def test_open_in_zotero_env_group() -> None:
    with patch.dict(os.environ, {"ZOTERO_LIBRARY_TYPE": "group", "ZOTERO_LIBRARY_ID": "777"}, clear=False):
        out = open_in_zotero("K3")
        assert "zotero://select/groups/777/items/K3" in out