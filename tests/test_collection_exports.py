"""Tests for collection export normalization across formats"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from zotero_mcp import export_collection


def _extract_result_payload(msg: str) -> dict[str, Any]:
    m = re.search(r"```json\n(.*?)\n```", msg, flags=re.DOTALL)
    assert m, "Expected JSON result block"
    payload = json.loads(m.group(1))
    return payload.get("result", payload)


def test_collection_export_csljson_text(mock_zotero: MagicMock) -> None:
    # Simulate Zotero csljson export returning a text blob (string)
    mock_zotero.collection_items.return_value = '[{"id":"k1","title":"T"}]'
    out = export_collection(collectionKey="C1", format="csljson", fetchAll=False)
    res = _extract_result_payload(out)
    assert res["count"] == 1
    assert "warnings" in res
    # Content block should contain JSON list
    assert "[" in out and "]" in out
    # Parse exported content and assert id presence
    m = re.search(r"### Exported content\n```\n(.*?)\n```", out, flags=re.DOTALL)
    assert m, "Expected exported content block"
    data = json.loads(m.group(1))
    assert isinstance(data, list)
    assert data and isinstance(data[0].get("id"), str)


def test_collection_export_ris_text(mock_zotero: MagicMock) -> None:
    ris = "TY  - JOUR\nTI  - Title\nER  -\n"
    # Upstream returns a list of lines (pyzotero sometimes does)
    mock_zotero.collection_items.return_value = ris.splitlines()
    out = export_collection(collectionKey="C1", format="ris", fetchAll=False)
    res = _extract_result_payload(out)
    assert res["count"] >= 1
    assert "TY  -" in out and "ER  -" in out
    # Heuristic count warning/code present
    assert any("COUNT_HEURISTIC" in w for w in res.get("warnings", []))
    assert "COUNT_HEURISTIC" in (res.get("codes") or [])


def test_collection_export_citation_included(mock_zotero: MagicMock) -> None:
    # When include=citation, pyzotero returns item dicts where data.citation is present
    mock_zotero.collection_items.return_value = [
        {"data": {"citation": "[1] A. Author, 2020."}},
        {"data": {"citation": "[2] B. Author, 2021."}},
    ]
    out = export_collection(collectionKey="C1", format="citation", style="ieee", fetchAll=False)
    res = _extract_result_payload(out)
    assert res["count"] == 2
    # Exported content should include concatenated citation strings
    assert "A. Author" in out and "B. Author" in out


def test_collection_export_citation_missing_strings_warns(mock_zotero: MagicMock) -> None:
    # Include=citation path but upstream does not populate data.citation
    mock_zotero.collection_items.return_value = [{"data": {}}, {"data": {}}]
    out = export_collection(collectionKey="C1", format="citation", style="ieee", fetchAll=False)
    res = _extract_result_payload(out)
    assert res["count"] == 2
    assert "warnings" in res and any("EMPTY_CITATION_EXPORT" in w for w in res["warnings"])  # type: ignore[index]
