"""Tests for Markdown validation and build orchestration"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from zotero_mcp import build_exports, validate_references


def test_validate_references(tmp_path: Path) -> None:
    doc = tmp_path / "paper.md"
    doc.write_text("""---
title: Test
---

This cites @key1 and @missing.
""", encoding="utf-8")

    bib = tmp_path / "refs.json"
    items = [{"id": "key1", "title": "A", "author": [{"family": "Doe", "given": "J"}], "issued": {"raw": "2020"}}]
    bib.write_text(json.dumps(items), encoding="utf-8")

    out = validate_references(str(doc), str(bib), requireDOIURL=False)
    assert "Unresolved: 1" in out
    assert "Missing fields: 0" in out


def test_build_exports_invokes_pandoc(tmp_path: Path) -> None:
    doc = tmp_path / "paper.md"
    doc.write_text("# Title\n\nHello", encoding="utf-8")

    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        # Mock subprocess.run to simulate success
        class _Res:
            returncode = 0
            stderr = ""

        with patch("zotero_mcp.__init__.subprocess.run", return_value=_Res()):
            out = build_exports(str(doc), ["docx", "html"], useCiteproc=True)
            assert "Outputs: 2" in out


def test_validate_references_require_doi_url(tmp_path: Path) -> None:
    doc = tmp_path / "paper.md"
    doc.write_text("""---
title: Test
---

This cites @key1.
""", encoding="utf-8")

    bib = tmp_path / "refs.json"
    items = [{"id": "key1", "title": "A", "author": [{"family": "Doe", "given": "J"}], "issued": {"raw": "2020"}}]
    bib.write_text(json.dumps(items), encoding="utf-8")

    out = validate_references(str(doc), str(bib), requireDOIURL=True)
    assert "Missing fields:" in out
    assert "doi/url" in out.lower()