"""Tests for Better BibTeX auto-export helper"""

from __future__ import annotations

from unittest.mock import patch

from zotero_mcp import ensure_auto_export


def test_ensure_auto_export_fallback() -> None:
    # Simulate missing local endpoint by raising URLError
    with patch("zotero_mcp.__init__.urllib.request.urlopen") as uo:
        from urllib.error import URLError

        uo.side_effect = URLError("no service")
        out = ensure_auto_export("/tmp/refs.json", format="csljson", scope="library")
        assert "Status: fallback" in out


def test_ensure_auto_export_available() -> None:
    # Simulate presence with version endpoint and an empty autoexport list
    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._body

    def _fake_urlopen(req, timeout=1.5):  # noqa: ANN001
        url = req.full_url
        if url.endswith("/better-bibtex/version"):
            return _Resp(b"1.0.0")
        if url.endswith("/better-bibtex/autoexport?format=json"):
            return _Resp(b"[]")
        return _Resp(b"")

    with patch("zotero_mcp.__init__.urllib.request.urlopen", side_effect=_fake_urlopen):
        out = ensure_auto_export("/tmp/refs.json", format="csljson", scope="library")
        assert "Status: available" in out or "Status: verified" in out