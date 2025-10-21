from __future__ import annotations

import json
from unittest.mock import MagicMock

from zotero_mcp import export_bibliography_content


def _extract_json(msg: str) -> dict:
    import json, re
    m = re.search(r"```json\n(.*?)\n```", msg, flags=re.DOTALL)
    assert m, "Expected JSON result block"
    payload = json.loads(m.group(1))
    return payload.get("result", payload)


def test_csljson_stable_ordering(mock_zotero: MagicMock) -> None:
    # Provide out-of-order items
    mock_zotero.everything.side_effect = lambda x: x
    mock_zotero.items.return_value = [
        {"id": "b", "title": "T2"},
        {"id": "a", "title": "T1"},
    ]
    msg1 = export_bibliography_content(format="csljson", scope="library", fetchAll=False)
    r1 = _extract_json(msg1)
    content1 = r1["content"]
    msg2 = export_bibliography_content(format="csljson", scope="library", fetchAll=False)
    r2 = _extract_json(msg2)
    content2 = r2["content"]
    assert content1 == content2
