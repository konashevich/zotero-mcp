"""Tests for bibliography export and workspace/style helpers"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from zotero_mcp import export_bibliography_content, ensure_style_content, ensure_yaml_citations_content


def test_export_bibliography_csljson(tmp_path: Path, mock_zotero: MagicMock) -> None:
    mock_zotero.everything.side_effect = lambda x: x  # passthrough
    # Return native Zotero items (so code exercises local CSL mapping)
    mock_zotero.items.return_value = [
        {"key": "K1", "data": {"key": "K1", "itemType": "journalArticle", "title": "A", "creators": []}},
        {"key": "K2", "data": {"key": "K2", "itemType": "journalArticle", "title": "B", "creators": []}},
    ]

    out = export_bibliography_content(format="csljson", scope="library", fetchAll=False)
    assert "# Bibliography export (content)" in out
    assert "SHA256:" in out
    assert "Items: 2" in out
    assert "result" in out
    # Extract and verify CSL JSON shape
    import json, re
    m = re.search(r"```json\n(.*?)\n```", out, flags=re.DOTALL)
    assert m
    payload = json.loads(m.group(1))
    res = payload.get("result", payload)
    content = res["content"]
    data = json.loads(content)
    assert isinstance(data, list)
    assert all(isinstance(e.get("id"), str) for e in data)
    # Stable ordering by id then title (K1 before K2)
    ids = [e.get("id") for e in data]
    assert ids == sorted(ids)


def test_export_bibliography_csljson_already_csl_list(tmp_path: Path, mock_zotero: MagicMock) -> None:
    # Upstream returns a Python list in CSL shape
    mock_zotero.items.return_value = [
        {"id": "a", "title": "A"},
        {"id": "b", "title": "B"},
    ]
    out = export_bibliography_content(format="csljson", scope="library", fetchAll=False)
    import json, re
    m = re.search(r"```json\n(.*?)\n```", out, flags=re.DOTALL)
    assert m, "Expected JSON result block"
    payload = json.loads(m.group(1))
    res = payload.get("result", payload)
    content = res["content"]
    data = json.loads(content)
    assert isinstance(data, list) and len(data) == 2
    assert all(isinstance(e.get("id"), str) for e in data)


def test_export_bibliography_collection(tmp_path: Path, mock_zotero: MagicMock) -> None:
    mock_zotero.everything.side_effect = lambda x: x
    mock_zotero.collection_items.return_value = ["@article{a}", "@article{b}"]

    out = export_bibliography_content(format="biblatex", scope="collection", collectionKey="C1", fetchAll=False)
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

    msg = ensure_style_content("https://example.com/my.csl")
    assert "CSL style (content)" in msg


def _extract_updated_content(msg: str) -> str:
    import json, re
    m = re.search(r"```json\n(.*?)\n```", msg, flags=re.DOTALL)
    assert m, "Expected JSON result block in tool output"
    payload = json.loads(m.group(1))
    res = payload.get("result", payload)
    return res["updatedContent"]


def test_ensure_yaml_citations(tmp_path: Path) -> None:
    # Input content without YAML
    doc_text = "# Title\n\nBody"

    msg = ensure_yaml_citations_content(doc_text, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content = _extract_updated_content(msg)

    assert "YAML citations updated" in msg
    assert content.startswith("---\n")
    assert "bibliography: __INLINE__" in content
    assert "csl: __INLINE__" in content
    assert "link-citations: true" in content


def test_ensure_yaml_citations_idempotency(tmp_path: Path) -> None:
    """Running ensure_yaml_citations_content twice should produce identical results"""
    doc_text = "# Title\n\nBody"
    # First run
    msg1 = ensure_yaml_citations_content(doc_text, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content1 = _extract_updated_content(msg1)
    # Second run with same params
    msg2 = ensure_yaml_citations_content(content1, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content2 = _extract_updated_content(msg2)
    assert content1 == content2


def test_ensure_yaml_citations_update_existing(tmp_path: Path) -> None:
    """Update existing front matter with new paths"""
    doc = tmp_path / "paper.md"
    initial = """---
bibliography: old.json
csl: old.csl
link-citations: false
author: Test Author
---

# Title

Body"""
    # Provide existing content with YAML front matter
    msg = ensure_yaml_citations_content(initial, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content = _extract_updated_content(msg)

    # Should update citation keys
    assert "bibliography: __INLINE__" in content
    assert "csl: __INLINE__" in content
    assert "link-citations: true" in content
    # Should preserve other keys
    assert "author: Test Author" in content or "author:" in content
    # Should not contain old values
    assert "old.json" not in content
    assert "old.csl" not in content


def test_ensure_yaml_citations_crlf(tmp_path: Path) -> None:
    """Handle Windows CRLF newlines"""
    doc_text = "# Title\r\n\r\nBody"
    msg = ensure_yaml_citations_content(doc_text, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content = _extract_updated_content(msg)

    assert "YAML citations updated" in msg
    assert content.startswith("---\n")
    assert "bibliography: __INLINE__" in content


def test_ensure_yaml_citations_with_bom(tmp_path: Path) -> None:
    """Handle BOM (Byte Order Mark)"""
    # Write with BOM in content
    content_with_bom = "\ufeff# Title\n\nBody"
    msg = ensure_yaml_citations_content(content_with_bom, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content = _extract_updated_content(msg)

    assert "YAML citations updated" in msg
    # BOM should be stripped, front matter should be at start
    assert content.startswith("---\n")


def test_ensure_yaml_citations_requires_yaml(tmp_path: Path, monkeypatch: Any) -> None:
    """If PyYAML is not available, the tool fails fast (no fallback)."""
    import builtins
    import importlib
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("yaml not available")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = ensure_yaml_citations_content("# T\n\nB", bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    assert "Error ensuring YAML citations" in out
