from __future__ import annotations

from unittest.mock import patch

from zotero_mcp import zotero_health


def _extract_json(msg: str) -> dict:
    import json, re
    m = re.search(r"```json\n(.*?)\n```", msg, flags=re.DOTALL)
    assert m, "Expected JSON result block"
    payload = json.loads(m.group(1))
    return payload.get("result", payload)


def test_health_reports_pandoc_and_engine() -> None:
    with patch("zotero_mcp.__init__.shutil.which") as mock_which:
        def which(name: str):
            if name == "pandoc":
                return "/usr/bin/pandoc"
            if name == "wkhtmltopdf":
                return "/usr/bin/wkhtmltopdf"
            return None

        mock_which.side_effect = which

        class _Res:
            returncode = 0
            stdout = "pandoc 3.1\n"

        with patch("zotero_mcp.__init__.subprocess.run", return_value=_Res()):
            msg = zotero_health()
            data = _extract_json(msg)
            assert data.get("pandoc") == "/usr/bin/pandoc"
            assert data.get("pandocVersion", "").startswith("pandoc ")
            assert data.get("pdfEngine") in ("wkhtmltopdf", "xelatex")
            assert "pdfEngineVersion" in data
