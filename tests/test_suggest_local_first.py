from __future__ import annotations

from zotero_mcp import suggest_citations

def test_suggest_local_first_uses_cache(monkeypatch):
    # Seed cache by calling suggest with local-first and tiny text; then call again
    monkeypatch.setenv("ZOTERO_SUGGEST_LOCAL_FIRST", "true")
    # We can't guarantee live Zotero here; this is a smoke test that should not error
    out = suggest_citations("test title", limit=1)
    assert isinstance(out, str)
    # A second call should also succeed, using cache/local path if present
    out2 = suggest_citations("test title", limit=1)
    assert isinstance(out2, str)
