# Plan 8 — Export correctness and content‑first polish

Purpose: Close the remaining gaps identified after Plan 7 by fixing export content quality (especially CSL JSON), hardening format‑specific exporters, and strengthening tests so CI enforces citeproc‑ready outputs.

## 0) What’s actually wrong (plain English)

- The content‑first bibliography tool should return real CSL JSON (array of items with id, title, author, issued, …). Right now, it can end up returning Zotero’s native item JSON or an empty/placeholder response depending on how the upstream export/pyzotero behaves.
- The collection exporter behaves inconsistently across formats:
  - csljson can look like a placeholder (e.g., `["items"]`).
  - citation (include=citation) sometimes returns an empty block.
  - ris parsing/handling can fail if the upstream call is treated as JSON.
- Tests don’t assert “citeproc‑ready” structure. They only check for any payload + count, so CI passes even when the content isn’t usable downstream.

This plan fixes exporters and adds tests that catch these issues.

## 1) Goals (acceptance criteria)

- `export_bibliography_content(format="csljson")`
  - Returns a valid CSL JSON array string (or an object with `items[]`) that parses and each entry has a string `id`.
  - Stable order (e.g., by `id` then `title`). Includes `count` and `sha256`.
  - Helpful warning if upstream returns no entries; never a placeholder like `["items"]`.
- `export_collection`
  - csljson returns valid CSL JSON text (parseable; entries have `id`). If upstream gives bytes/str, we treat it as text; if it’s JSON we validate shape; on mismatch, include a warning.
  - ris returns plain RIS text (bytes/str) with non‑zero length; never routed through JSON parsing.
  - citation(style=...) returns non‑empty formatted strings concatenated with separators; if Zotero didn’t include them, return a clear warning mentioning the requested style and parameters.
- Tests enforce the above (fail if content is not citeproc‑ready or export blocks are empty when `count > 0`).
- Diagnostics and errors are human‑readable (no raw stack traces). When upstream returns unexpected shape, include the mode/params we used and a short fix hint.

## 2) Implementation details

### A) export_bibliography_content (`src/zotero_mcp/__init__.py`)

- For format=csljson:
  - Prefer Zotero’s export translator route if available (set `format=csljson` on the request). Treat the response as text (bytes→utf‑8) and validate it’s a JSON array or an object with `items[]`. If it’s a dict of Zotero native items, fall back to a local mapping.
  - Fallback mapping (if export translator not honored): build minimal CSL JSON entries from Zotero items list: `id` (from `item["data"]["key"]` or `item["key"]`), `title` (from `data.title`), `author` (map creators → CSL `family`/`given` when present), `issued` (best effort from `data.date`). Document that ids may be Zotero keys when BBT citekeys are unavailable.
  - Sort by (`id`, `title`). Compute `sha256` on the final string.
  - Add warnings when the array is empty but items were expected.

### B) export_collection (`src/zotero_mcp/__init__.py`)

- For export formats (ris/csv/mods/…): ensure we treat response as text. If pyzotero returns a list of strings, join; if it returns bytes/str, decode and pass through. Do not attempt JSON parsing for these.
- For csljson: same validation as `export_bibliography_content` — treat as text; ensure parseable CSL JSON; warn on mismatch.
- For citation/bib (`include=citation|bib` in JSON mode): extract `data.citation`/`data.bib` when present; if missing while `count > 0`, return a warning including (format, style, limit, start) and suggest trying a known style id.

### C) Small helpers

- Add internal helpers:
  - `
as_text(obj)` → `str`: normalize bytes/str/list→joined text.
  - `_ensure_csl_json(text)` → `tuple[list|dict, warnings]`: parse JSON and validate array or `{items:[]}`; return warnings on shape mismatches.
  - `_to_csl_entry(item)` → `dict`: minimal mapper from Zotero item → CSL entry.

### D) Tests

- Strengthen tests and add new ones:
  - `tests/test_bibliography.py`
    - Assert that `export_bibliography_content(csljson)` returns content that `json.loads` parses to a list or object with `items`, and that the first entry has an `id`.
  - `tests/test_collection_exports.py` (new)
    - csljson: mocked response returns proper array; assert non‑empty and `id` present.
    - ris: mocked response returns RIS text; assert contains typical RIS tags (e.g., `TY  -`, `ER  -`).
    - citation(ieee): mocked JSON `include=citation` present; assert concatenated, non‑empty output.
    - Negative path: mocked missing `include=citation` even when `count>0` → assert a warning substring.

### E) Error messages and health

- Keep errors short and task‑centric. Examples:
  - `INVALID_CSL_EXPORT`: Upstream returned non‑CSL JSON; falling back to local mapping.
  - `EMPTY_CITATION_EXPORT`: Zotero did not include citation strings for the requested style; try a different style.
- Health remains unchanged (already reports pandoc/pdf engine and YAML parser).

### F) Docs

- README updates:
  - Clarify that content‑first tools (`export_bibliography_content`) return citeproc‑ready CSL JSON.
  - Document exporter behavior for RIS/citation and how to select styles.
  - Note environment flags for large outputs (`EXPORTS_EMBED_DATA_URI`, `EXPORTS_MAX_EMBED_BYTES`).

## 3) Task breakdown

- Code (`src/zotero_mcp/__init__.py`)
  - Implement `_as_text`, `_ensure_csl_json`, `_to_csl_entry`.
  - Update `export_bibliography_content` (csljson path, fallback mapping, stable sort, warnings).
  - Update `export_collection` (text handling for ris/csljson/citation, clearer warnings).
- Tests
  - Update `tests/test_bibliography.py` assertions for CSL JSON shape.
  - Add `tests/test_collection_exports.py` with the cases above.
- Docs
  - README: exporter behavior, style guidance, large outputs.

## 4) Acceptance tests (green criteria)

- pytest: all existing tests remain green; new tests pass.
- Manual probe (optional):
  - `export_bibliography_content(csljson)` returns a parseable CSL array with `ids`.
  - `export_collection(csljson|ris|citation)` returns non‑empty content; warnings are present only in the defined negative path.

## 5) Rollout and safety

- No backward‑compat behavior to preserve (content‑first, no legacy aliases).
- Changes localized to exporter paths and test suite; build/validate/YAML tools untouched.
- If upstream API behavior varies, we still return usable content by falling back to local mapping and attach a warning.

## 6) Timeline (target: 1–2 short PRs)

- PR1 (exporters + tests): 1 day — implement helpers, fix exporters, add tests; CI green.
- PR2 (docs): 0.5 day — README updates and small examples.

## 7) Risks and mitigations

- Upstream variability (Zotero/pyzotero differences): mitigate by validating shape and falling back to local CSL mapping.
- Performance for large libraries: keep `fetchAll` optional and enforce server‑side limits; document scope filters.
