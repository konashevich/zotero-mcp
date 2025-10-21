from __future__ import annotations

import json
import re
from unittest.mock import patch

from zotero_mcp import build_exports_content


def _extract_json(msg: str) -> dict:
    m = re.search(r"```json\n(.*?)\n```", msg, flags=re.DOTALL)
    assert m, "Expected JSON result block"
    payload = json.loads(m.group(1))
    return payload.get("clientBuild") or payload.get("result", payload)


def test_client_build_fallback_per_format_commands() -> None:
    # Force pandoc missing
    with patch("zotero_mcp.__init__.shutil.which", return_value=None):
        msg = build_exports_content(
            "# T\n\nB",
            ["docx", "pdf"],
            bibliographyContent=[{"id": "k"}],
            cslContent="<style/>",
            useCiteproc=None,  # should default to true
            extraArgs=["--metadata", "title=Test"],
        )
        data = _extract_json(msg)
        cmds = data.get("commands")
        assert isinstance(cmds, list) and len(cmds) == 2
        # pdf command should include pdf-engine
        assert any("--pdf-engine=wkhtmltopdf" in c for c in [" ".join(x) for x in cmds])
        # docx should not have pdf-engine
        for arr in cmds:
            s = " ".join(arr)
            if s.endswith(".docx"):
                assert "--pdf-engine" not in s
        # should include citeproc, bibliography and csl
        all_s = "\n".join(" ".join(x) for x in cmds)
        assert "--citeproc" in all_s
        assert "--bibliography refs.json" in all_s
        assert "--csl style.csl" in all_s
    assert "--metadata title=Test" in all_s
    # one-line commands available
    assert isinstance(data.get("commandsOneLine"), list) and len(data["commandsOneLine"]) == 2


def test_build_exports_rejects_html_format() -> None:
    msg = build_exports_content("# H\n\nT", ["html"], useCiteproc=False)
    assert "Unsupported formats" in msg
