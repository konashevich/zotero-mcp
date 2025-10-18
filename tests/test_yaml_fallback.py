from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from zotero_mcp import ensure_yaml_citations, zotero_health


def test_ensure_yaml_citations_with_yaml(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Body", encoding="utf-8")
    out = ensure_yaml_citations(str(doc), "refs.json", "style.csl", True)
    text = doc.read_text(encoding="utf-8")
    assert "bibliography: refs.json" in text
    assert "csl: style.csl" in text
    assert "link-citations: true" in text
    assert "YAML citations updated" in out


def test_ensure_yaml_citations_without_yaml(tmp_path: Path, monkeypatch: Any) -> None:
    # Simulate absence of PyYAML by making import fail inside the function
    doc = tmp_path / "doc.md"
    doc.write_text("---\nfoo: bar\n---\nBody", encoding="utf-8")

    # Patch import inside module to simulate missing yaml
    import zotero_mcp.__init__ as zm

    class _NoYAML:
        pass

    monkeypatch.setattr(zm, "yaml", None, raising=False)
    out = ensure_yaml_citations(str(doc), "refs.json", "style.csl", True)
    text = doc.read_text(encoding="utf-8")
    assert "bibliography: refs.json" in text
    assert "csl: style.csl" in text
    assert "link-citations: true" in text
    assert "YAML citations updated" in out


def test_zotero_health_smoke() -> None:
    out = zotero_health()
    assert "# Health" in out
    assert "result" in out
