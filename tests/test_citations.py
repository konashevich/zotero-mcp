"""Tests for citation helper tools"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zotero_mcp import insert_citation, resolve_citekeys, suggest_citations


def test_insert_citation_pandoc() -> None:
    s = insert_citation(["a", "b"], style="pandoc", pages="42")
    assert s == "[@a; @b, p. 42]"


def test_insert_citation_latex() -> None:
    s = insert_citation(["a", "b"], style="latex", pages="42")
    assert s == "\\parencite[42]{a,b}"


def test_resolve_citekeys_from_csljson_content(tmp_path: Path) -> None:
    items = [
        {"id": "key1", "title": "Paper A", "author": [{"family": "Doe", "given": "J"}]},
        {"id": "key2", "title": "Paper B", "author": [{"family": "Roe", "given": "R"}]},
    ]
    bib_text = json.dumps(items)
    out = resolve_citekeys(["key1", "missing"], bibliographyContent=bib_text)
    assert "Resolved: 1" in out
    assert "Unresolved: 1" in out
    assert "result" in out


def test_suggest_citations_basic(mock_zotero: Any) -> None:
    mock_zotero.items.return_value = [
        {"key": "K1", "data": {"title": "Blockchain Basics", "creators": [{"lastName": "Smith", "firstName": "Alice"}]}},
        {"key": "K2", "data": {"title": "Advanced Topics", "creators": [{"name": "Bob"}]}},
    ]
    out = suggest_citations("blockchain")
    assert "Suggestions" in out
    assert "K1" in out


def test_resolve_citekeys_prefer_bbt(monkeypatch: Any, tmp_path: Path) -> None:
    # Simulate BBT JSON endpoint response
    import types
    import json as _json

    class _Resp:
        def __init__(self, payload: bytes) -> None:
            self._p = payload

        def read(self) -> bytes:
            return self._p

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=1.5):  # type: ignore[no-redef]
        data = [
            {"id": "bbtKey", "title": "BBT Title", "author": [{"family": "Doe", "given": "J"}]}
        ]
        return _Resp(_json.dumps(data).encode("utf-8"))

    import urllib.request as _ureq
    monkeypatch.setattr(_ureq, "urlopen", fake_urlopen)

    out = resolve_citekeys(["bbtKey"], bibliographyContent=None, tryZotero=False, preferBBT=True)
    assert "Resolved: 1" in out