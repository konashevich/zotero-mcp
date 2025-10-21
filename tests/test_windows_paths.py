"""Tests oriented to ensure content-based tools avoid path handling entirely."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from zotero_mcp import ensure_yaml_citations_content, validate_references_content, build_exports_content


def _extract_updated(msg: str) -> str:
    import json, re
    m = re.search(r"```json\n(.*?)\n```", msg, flags=re.DOTALL)
    assert m, "Expected JSON result block"
    payload = json.loads(m.group(1))
    res = payload.get("result", payload)
    return res["updatedContent"]


def test_ensure_yaml_citations_content_basic() -> None:
    msg = ensure_yaml_citations_content("# Title\n\nBody", bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content = _extract_updated(msg)
    assert "YAML citations updated" in msg
    assert content.startswith("---\n")
    assert "bibliography: __INLINE__" in content


def test_validate_references_content_basic() -> None:
    doc = "Some text [@k1]."
    bib = "[{\"id\":\"k1\",\"title\":\"T\"}]"
    out = validate_references_content(doc, bib, requireDOIURL=False)
    assert "Validation report" in out


def test_build_exports_content_invokes_pandoc() -> None:
    # Mock pandoc being available
    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        with patch("zotero_mcp.__init__.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            out = build_exports_content("# Title\n\nContent", ["docx"], useCiteproc=False)
            assert "Build exports" in out
            assert mock_run.called


def test_idempotent_yaml_content() -> None:
    msg1 = ensure_yaml_citations_content("# T\n\nB", bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    c1 = _extract_updated(msg1)
    msg2 = ensure_yaml_citations_content(c1, bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    c2 = _extract_updated(msg2)
    assert c1 == c2


def test_yaml_bom_and_crlf() -> None:
    msg = ensure_yaml_citations_content("\ufeff# Title\r\n\r\nBody", bibliographyContent="[]", cslContent="<style/>", linkCitations=True)
    content = _extract_updated(msg)
    assert content.startswith("---\n")


def test_build_exports_content_pdf_engine_flag() -> None:
    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        with patch("zotero_mcp.__init__.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            out = build_exports_content("# T\n\nB", ["pdf"], useCiteproc=True, pdfEngine="xelatex")
            assert "Build exports" in out


def test_build_exports_content_env_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force env engine overrides
    monkeypatch.setenv("PDF_ENGINE", "wkhtmltopdf")
    with patch("zotero_mcp.__init__.shutil.which") as mock_which:
        def which(name: str):
            if name == "pandoc":
                return "/usr/bin/pandoc"
            if name == "wkhtmltopdf":
                return "/usr/bin/wkhtmltopdf"
            return None

        mock_which.side_effect = which
        with patch("zotero_mcp.__init__.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            out = build_exports_content("# T\n\nB", ["pdf"], useCiteproc=False)
            assert "Build exports" in out


def test_build_exports_content_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch("zotero_mcp.__init__.shutil.which") as mock_which:
        def which(name: str):
            if name == "pandoc":
                return "/usr/bin/pandoc"
            if name == "weasyprint":
                return "/usr/bin/weasyprint"
            return None

        mock_which.side_effect = which
        captured: list[list[str]] = []

        class _Res:
            returncode = 0
            stderr = ""
            stdout = "weasyprint 60.0"

        def _fake_run(cmd: list[str], capture_output: bool, text: bool, env: dict[str, str]):  # type: ignore[override]
            captured.append(cmd)
            return _Res()

        with patch("zotero_mcp.__init__.subprocess.run", side_effect=_fake_run):
            out = build_exports_content("# T\n\nB", ["pdf"], useCiteproc=False, pdfEngine="weasyprint")
            assert "Build exports" in out
        assert captured, "expected pandoc invocation"
        assert any("--pdf-engine=weasyprint" in " ".join(cmd) for cmd in captured if "/usr/bin/pandoc" in cmd[0])


def test_validate_references_content_require_doi_url() -> None:
    doc = "Cite @k1."
    bib = '[{"id":"k1","title":"T"}]'
    out = validate_references_content(doc, bib, requireDOIURL=True)
    assert "doi/url" in out.lower()
