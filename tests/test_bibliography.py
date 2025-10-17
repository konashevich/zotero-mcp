"""Tests for bibliography export and workspace/style helpers"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from zotero_mcp import export_bibliography, ensure_style, ensure_yaml_citations


def test_export_bibliography_csljson(tmp_path: Path, mock_zotero: MagicMock) -> None:
    mock_zotero.everything.side_effect = lambda x: x  # passthrough
    mock_zotero.items.return_value = [{"id": 1}, {"id": 2}]

    out_path = tmp_path / "refs.json"
    out = export_bibliography(str(out_path), format="csljson", scope="library", fetchAll=False)

    assert out_path.exists()
    assert "SHA256:" in out
    assert "Items: 2" in out
    assert "result" in out


def test_export_bibliography_collection(tmp_path: Path, mock_zotero: MagicMock) -> None:
    mock_zotero.everything.side_effect = lambda x: x
    mock_zotero.collection_items.return_value = ["@article{a}", "@article{b}"]

    out_path = tmp_path / "refs.bib"
    out = export_bibliography(str(out_path), format="biblatex", scope="collection", collectionKey="C1", fetchAll=False)

    assert out_path.exists()
    assert "collection C1" in out


@patch("zotero_mcp.__init__.urllib.request.urlopen")
def test_ensure_style_download(mock_urlopen: Any, tmp_path: Path) -> None:
    # Prepare fake content
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"<style>fake</style>"

    mock_urlopen.return_value = _Resp()

    target = tmp_path / "style.csl"
    msg = ensure_style("https://example.com/my.csl", str(target))
    assert target.exists()
    assert "Style" in msg


def test_ensure_yaml_citations(tmp_path: Path) -> None:
    doc = tmp_path / "paper.md"
    doc.write_text("# Title\n\nBody", encoding="utf-8")

    msg = ensure_yaml_citations(str(doc), "refs.json", "style.csl", True)
    content = doc.read_text(encoding="utf-8")

    assert "YAML citations updated" in msg
    assert content.startswith("---\n")
    assert "bibliography: refs.json" in content
    assert "csl: style.csl" in content
    assert "link-citations: true" in content