"""Tests for BBT auto-export ensure job tool"""

from __future__ import annotations

import json
from unittest.mock import patch

from zotero_mcp import bbt_ensure_auto_export_job


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_bbt_ensure_auto_export_job_fallback() -> None:
    with patch("zotero_mcp.__init__.urllib.request.urlopen") as uo:
        from urllib.error import URLError

        uo.side_effect = URLError("no service")
        out = bbt_ensure_auto_export_job("/tmp/refs.json", format="csljson", scope="library")
        assert "Status: fallback" in out


def test_bbt_ensure_auto_export_job_create() -> None:
    # Simulate available BBT with no jobs and a successful POST
    def _fake_urlopen(req, timeout=1.5):  # noqa: ANN001
        url = getattr(req, "full_url", "")
        method = getattr(req, "method", "GET")
        if url.endswith("/better-bibtex/version") and method == "GET":
            return _Resp(b"1.0.0")
        if url.endswith("/better-bibtex/autoexport?format=json") and method == "GET":
            return _Resp(b"[]")
        if url.endswith("/better-bibtex/autoexport") and method == "POST":
            return _Resp(json.dumps({"id": 123}).encode("utf-8"))
        return _Resp(b"")

    with patch("zotero_mcp.__init__.urllib.request.urlopen", side_effect=_fake_urlopen):
        out = bbt_ensure_auto_export_job("/tmp/refs.json", format="csljson", scope="library")
        assert "Status: created" in out


def test_bbt_ensure_auto_export_job_verify() -> None:
    # Simulate existing matching job
    job = {"id": 7, "path": "/tmp/refs.json", "translator": "CSL JSON", "keepUpdated": True, "type": "library"}

    def _fake_urlopen(req, timeout=1.5):  # noqa: ANN001
        url = getattr(req, "full_url", "")
        method = getattr(req, "method", "GET")
        if url.endswith("/better-bibtex/version") and method == "GET":
            return _Resp(b"1.0.0")
        if url.endswith("/better-bibtex/autoexport?format=json") and method == "GET":
            return _Resp(json.dumps([job]).encode("utf-8"))
        return _Resp(b"")

    with patch("zotero_mcp.__init__.urllib.request.urlopen", side_effect=_fake_urlopen):
        out = bbt_ensure_auto_export_job("/tmp/refs.json", format="csljson", scope="library")
        assert "Status: verified" in out
