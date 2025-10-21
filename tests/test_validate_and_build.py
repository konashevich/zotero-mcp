"""Tests for Markdown validation and build orchestration"""

from __future__ import annotations

import json
import base64
import re
from pathlib import Path
import pytest
from unittest.mock import patch

from zotero_mcp import build_exports_content, validate_references_content


def _extract_artifacts(message: str) -> list[dict[str, object]]:
    match = re.search(r"```json\n(.*?)\n```", message, flags=re.DOTALL)
    assert match, "Expected JSON payload"
    payload = json.loads(match.group(1))
    data = payload.get("result", payload)
    artifacts = data.get("artifacts", [])
    assert isinstance(artifacts, list), "artifacts should be a list"
    return artifacts


def test_validate_references(tmp_path: Path) -> None:
    doc_text = """---
title: Test
---

This cites @key1 and @missing.
"""
    items = [{"id": "key1", "title": "A", "author": [{"family": "Doe", "given": "J"}], "issued": {"raw": "2020"}}]
    bib_text = json.dumps(items)
    out = validate_references_content(doc_text, bib_text, requireDOIURL=False)
    assert "Unresolved: 1" in out
    assert "Missing fields: 0" in out


def test_build_exports_invokes_pandoc(tmp_path: Path) -> None:
    with patch("zotero_mcp.__init__.shutil.which") as mock_which:
        def which(name: str):
            if name == "pandoc":
                return "/usr/bin/pandoc"
            if name == "wkhtmltopdf":
                return "/usr/bin/wkhtmltopdf"
            return None

        mock_which.side_effect = which
        # Mock subprocess.run to simulate success
        class _Res:
            returncode = 0
            stderr = ""

        with patch("zotero_mcp.__init__.subprocess.run", return_value=_Res()):
            out = build_exports_content("# Title\n\nHello", ["docx"], useCiteproc=True)
            assert "Build exports" in out


def test_build_exports_returns_base64_payload() -> None:
    def _fake_run(cmd: list[str], capture_output: bool, text: bool, env: dict[str, str]):  # type: ignore[override]
        out_index = cmd.index("-o")
        out_path = Path(cmd[out_index + 1])
        out_path.write_bytes(b"fake-bytes")
        class _Res:
            returncode = 0
            stderr = ""
        return _Res()

    with patch("zotero_mcp.__init__.shutil.which") as mock_which:
        def _which(name: str):
            if name == "pandoc":
                return "/usr/bin/pandoc"
            if name == "wkhtmltopdf":
                return "/usr/bin/wkhtmltopdf"
            if name == "xelatex":
                return "/usr/bin/xelatex"
            return None

        mock_which.side_effect = _which
        with patch("zotero_mcp.__init__.subprocess.run", side_effect=_fake_run):
            out = build_exports_content("# T\n\nB", ["docx"], useCiteproc=False)

    artifacts = _extract_artifacts(out)
    assert artifacts and artifacts[0]["format"] == "docx"
    blob = artifacts[0]["content"]
    decoded = base64.b64decode(blob)
    assert decoded == b"fake-bytes"
    assert artifacts[0]["size"] == len(decoded)


def test_build_exports_uses_title_for_filename() -> None:
    def _fake_run(cmd: list[str], capture_output: bool, text: bool, env: dict[str, str]):  # type: ignore[override]
        out_index = cmd.index("-o")
        out_path = Path(cmd[out_index + 1])
        out_path.write_bytes(b"title-bytes")
        class _Res:
            returncode = 0
            stderr = ""
        return _Res()

    markdown = """---
title: Fancy Report
---

Body
"""
    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        with patch("zotero_mcp.__init__.subprocess.run", side_effect=_fake_run):
            out = build_exports_content(markdown, ["docx"], useCiteproc=False)

    artifacts = _extract_artifacts(out)
    assert artifacts[0]["filename"] == "Fancy_Report.docx"


def test_build_exports_respects_output_basename() -> None:
    def _fake_run(cmd: list[str], capture_output: bool, text: bool, env: dict[str, str]):  # type: ignore[override]
        out_index = cmd.index("-o")
        out_path = Path(cmd[out_index + 1])
        out_path.write_bytes(b"custom")
        class _Res:
            returncode = 0
            stderr = ""
        return _Res()

    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        with patch("zotero_mcp.__init__.subprocess.run", side_effect=_fake_run):
            out = build_exports_content("# H\n\nB", ["pdf"], outputBasename="whitepaper", useCiteproc=False)

    artifacts = _extract_artifacts(out)
    assert artifacts[0]["filename"] == "whitepaper.pdf"




def test_validate_references_require_doi_url(tmp_path: Path) -> None:
    doc_text = """---
title: Test
---

This cites @key1.
"""
    items = [{"id": "key1", "title": "A", "author": [{"family": "Doe", "given": "J"}], "issued": {"raw": "2020"}}]
    bib_text = json.dumps(items)
    out = validate_references_content(doc_text, bib_text, requireDOIURL=True)
    assert "Missing fields:" in out
    assert "doi/url" in out.lower()


def test_validate_references_accepts_parsed_json() -> None:
    doc_text = "Nothing cites here."
    bib = [{"id": "x", "title": "T"}]
    out = validate_references_content(doc_text, bib, requireDOIURL=False)
    assert "No Pandoc citations found" in out
