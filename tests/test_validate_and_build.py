"""Tests for Markdown validation and build orchestration"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from unittest.mock import patch

from zotero_mcp import build_exports_content, validate_references_content


def test_validate_references(tmp_path: Path) -> None:
    doc_text = """---
title: Test
---

This cites @key1 and @missing.
"""
    items = [{"id": "key1", "title": "A", "author": [{"family": "Doe", "given": "J"}], "issued": {"raw": "2020"}}]
    bib_text = json.dumps(items)
    out = validate_references_content(doc_text, bib_text, requireDOIURL=False)
    assert "Unresolved: 1" in out
    assert "Missing fields: 0" in out


def test_build_exports_invokes_pandoc(tmp_path: Path) -> None:
    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        # Mock subprocess.run to simulate success
        class _Res:
            returncode = 0
            stderr = ""

        with patch("zotero_mcp.__init__.subprocess.run", return_value=_Res()):
            out = build_exports_content("# Title\n\nHello", ["docx", "html"], useCiteproc=True)
            assert "Build exports" in out


def test_build_exports_embeds_data_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        class _Res:
            returncode = 0
            stderr = ""
        with patch("zotero_mcp.__init__.subprocess.run", return_value=_Res()):
            # Force embedding
            monkeypatch.setenv("EXPORTS_EMBED_DATA_URI", "true")
            out = build_exports_content("# T\n\nB", ["html"], useCiteproc=False)
            assert "dataURI" in out


def test_validate_references_require_doi_url(tmp_path: Path) -> None:
    doc_text = """---
title: Test
---

This cites @key1.
"""
    items = [{"id": "key1", "title": "A", "author": [{"family": "Doe", "given": "J"}], "issued": {"raw": "2020"}}]
    bib_text = json.dumps(items)
    out = validate_references_content(doc_text, bib_text, requireDOIURL=True)
    assert "Missing fields:" in out
    assert "doi/url" in out.lower()