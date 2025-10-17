"""Tests for collections navigation tool"""

from typing import Any

from zotero_mcp import get_collections


def test_get_collections_basic(mock_zotero: Any) -> None:
    """Ensure collections are returned with paths and counts"""
    mock_zotero.collections.return_value = [
        {
            "data": {"key": "C1", "name": "Root", "parentCollection": None},
            "meta": {"numItems": 3},
        },
        {
            "data": {"key": "C2", "name": "Child", "parentCollection": "C1"},
            "meta": {"numItems": 1},
        },
        {
            "data": {"key": "C3", "name": "Second", "parentCollection": "C1"},
            "meta": {"numItems": 0},
        },
    ]

    out = get_collections()

    assert "# Collections" in out
    assert "`C1` | Root (3)" in out
    # child path includes parent name
    assert "`C2` | Root/Child (1)" in out
    assert "result" in out  # compact JSON block label


def test_get_collections_parent_filter(mock_zotero: Any) -> None:
    """Filtering by parent should still compute paths"""
    # Emulate lack of collections_sub by raising and using fallback filter
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise AttributeError("no collections_sub")

    mock_zotero.collections_sub.side_effect = _raise  # type: ignore[attr-defined]
    mock_zotero.collections.return_value = [
        {
            "data": {"key": "C1", "name": "Root", "parentCollection": None},
            "meta": {"numItems": 3},
        },
        {
            "data": {"key": "C2", "name": "Child", "parentCollection": "C1"},
            "meta": {"numItems": 1},
        },
    ]

    out = get_collections("C1")

    # parent shown in header
    assert "Parent: `C1`" in out
    # child still appears
    assert "`C2`" in out