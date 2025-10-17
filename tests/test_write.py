"""Tests for write-capable tools with mocked pyzotero client"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from zotero_mcp import create_item, update_item, add_note, set_tags


@pytest.fixture
def mock_zotero(monkeypatch) -> MagicMock:
    mock = MagicMock()

    def mock_get_zotero_client():
        return mock

    monkeypatch.setattr("zotero_mcp.get_zotero_client", mock_get_zotero_client)
    return mock


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    # Ensure write mode (not local) and credentials present
    monkeypatch.setenv("ZOTERO_LOCAL", "")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "14105076")
    monkeypatch.setenv("ZOTERO_API_KEY", "testkey")


def test_create_item_success(mock_zotero: Any, monkeypatch: Any):
    mock_zotero.item_template.return_value = {"itemType": "book", "title": ""}
    mock_zotero.create_items.return_value = {"success": {"0": "NEWKEY"}, "failed": {}, "unchanged": {}}

    out = create_item(
        itemType="book",
        fields={"title": "My Book"},
        tags=["tag1", {"tag": "tag2"}],
        collections=["COLL1"],
        parentItem=None,
        validateOnly=False,
    )

    assert "Item created" in out and "NEWKEY" in out
    mock_zotero.item_template.assert_called_once_with("book")
    mock_zotero.create_items.assert_called_once()


def test_create_item_validate_only_success(mock_zotero: Any):
    mock_zotero.item_template.return_value = {"itemType": "book"}
    # check_items does not raise
    out = create_item("book", fields={}, validateOnly=True)
    assert "Validation successful" in out


def test_update_item_patch_success(mock_zotero: Any):
    mock_zotero.item.return_value = {"data": {"key": "K1", "version": 5}}

    out = update_item("K1", patch={"title": "New"}, strategy="patch")

    assert "Item updated" in out and "K1" in out
    mock_zotero.update_items.assert_called_once()


def test_add_note_success(mock_zotero: Any):
    mock_zotero.item_template.return_value = {"itemType": "note"}
    mock_zotero.create_items.return_value = {"success": {"0": "NOTEKEY"}, "failed": {}, "unchanged": {}}

    out = add_note("<p>Hello</p>", parentItem="PARENT")

    assert "Note created" in out and "NOTEKEY" in out and "PARENT" in out


def test_set_tags_replace(mock_zotero: Any):
    mock_zotero.item.return_value = {"data": {"key": "K1", "version": 5}}

    out = set_tags("K1", tags=["a", "b"], mode="replace")

    assert "Tags replaced" in out and "K1" in out
    mock_zotero.update_items.assert_called_once()


def test_write_guard_local(monkeypatch: Any):
    monkeypatch.setenv("ZOTERO_LOCAL", "true")
    out = create_item("book", fields={})
    assert "not available in local mode" in out
