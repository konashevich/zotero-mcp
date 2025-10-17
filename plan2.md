# Zotero MCP Server — Improvement Plan (AI feedback follow‑up)

This plan turns the feedback in `zotero_requirements.md` into a concrete, prioritized roadmap grounded in the current code/tests. It focuses on hands‑free bibliography sync, citation authoring, and one‑shot exports, while keeping local vs web API modes safe.

## Current state snapshot

Implemented MCP tools (see `src/zotero_mcp/__init__.py` and tests under `tests/`):

- Read/search: `zotero_search_items`, `zotero_item_metadata`, `zotero_item_fulltext`
- Write: `zotero_create_item`, `zotero_update_item`, `zotero_add_note`, `zotero_set_tags`
- Export (partial): `zotero_export_collection`

Gaps vs target capabilities (from `zotero_requirements.md`):

- Library navigation: collections tree
- Continuous bibliography sync (Better BibTeX auto‑export)
- Citation authoring helpers: resolve citekeys, insert citations, suggestions
- Style + YAML management
- Build orchestration (docx/html/pdf)
- Convenience: open in Zotero

## Roadmap and priorities

The phases are sequenced to unlock workflows incrementally. Each item lists acceptance criteria and test ideas.

### Phase 1 — Library navigation + convenience (Foundations)

1. Tool: library.getCollections
   - Behavior: Return tree of collections with `{ key, name, parentKey, path, itemCount }`.
   - Impl: `pyzotero` → `collections()` + `collections_sub()` or `everything(...)`; build parent graph and compute `path` strings.
   - Acceptance: A call returns the full tree; a known child shows correct `path` and `itemCount`.
   - Tests: Mock `collections()` responses; assert flatten+tree shape.

1. Tool: files.openInZotero
   - Behavior: Returns a `zotero://select/library/items/<key>` URL; optionally attempts to open via OS if allowed.
   - Acceptance: Given an item key, returns the correct select URL.
   - Tests: Pure function test for URL formatting.

### Phase 2 — Bibliography export and style wiring

1. Tool: library.exportBibliography
   - Behavior: Export library or collection to a repo‑relative path in `bibtex|biblatex|csljson`. Compute SHA‑256 and return `{ path, count, hash, warnings }`.
   - Impl: Build on current `zotero_export_collection`; add library‑scope export; persist to disk; compute hash.
   - Acceptance: File written; hash stable across identical content; count matches entries.
   - Tests: Use tmpdir, mock export results, assert file contents+hash.

1. Tool: styles.ensureStyle
   - Behavior: Download CSL by id/URL to a given path (e.g., `style.csl`); verify checksum if available.
   - Impl: HTTP GET; follow redirects; basic cache (skip if same ETag/hash).
   - Acceptance: File exists; repeated calls are idempotent; malformed URL yields clear error.
   - Tests: Mock requests; verify write/idempotency.

1. Tool: workspace.ensureYamlCitations
   - Behavior: Ensure a Markdown file’s YAML has `bibliography`, `csl`, `link-citations` keys set to provided paths/values; preserve unrelated YAML.
   - Impl: Parse front‑matter (delimited by `---`); use a safe YAML parser; update/insert; write back atomically.
   - Acceptance: Missing keys are added; existing keys updated; content beyond YAML unchanged.
   - Tests: Round‑trip fixtures with/without existing YAML.

### Phase 3 — Auto‑export (hands‑free sync)

1. Tool: library.ensureAutoExport (Better BibTeX)
   - Behavior: Create/verify a “Keep updated” Better BibTeX export to a repo path (e.g., `references.bib/json`) for a given scope (collection|library).
   - Impl: Prefer local Zotero endpoints on 127.0.0.1:23119 (Better BibTeX). Detect if available; else return actionable fallback message pointing to on‑demand `library.exportBibliography`.
   - Acceptance: When local Zotero+BBT is available, calling ensures a persistent auto‑export; otherwise returns a clear fallback.
   - Tests: Mock local HTTP responses for create/verify; simulate unavailable service.

Notes:

- Keep local mode read‑only for Zotero data writes; this feature only configures BBT via its local API.
- Do not store secrets.

### Phase 4 — Authoring helpers (productivity)

1. Tool: library.resolveCitekeys
   - Behavior: Input array of citekeys; output map citekey → item metadata, plus unresolved/duplicate warnings.
   - Impl: Prefer BBT citekey source (local endpoint) when available; fallback strategies:
     - Parse the exported `references.bib`/`references.json` (if present) to build citekey→item map.
     - As last resort, allow exact Zotero item `key` passthrough.
   - Acceptance: Known citekeys resolve; unresolved keys are reported with suggestions (closest titles/authors if possible).
   - Tests: Mock both BBT and file‑based sources; mixed resolved/unresolved cases.

1. Tool: writing.insertCitation
   - Behavior: Return formatted citation string for a set of citekeys and options: style=`pandoc` → `[@a; @b, p. 42]`, style=`latex` → `\\parencite[42]{a,b}`.
   - Acceptance: Correct formatting across combinations of prefix/suffix/pages; input validation errors are clear.
   - Tests: Pure function tests for format variants.

1. Tool: writing.suggestCitations
   - Behavior: Given selected text context, return ranked suggestions with short rationale (title/author/DOI match signals).
   - Impl: Use `zotero_search_items`/`items(qmode=...)`; add a simple scoring function (n‑gram overlap, DOI presence).
   - Acceptance: Stable deterministic top‑k for known prompts; empty/short input yields guardrails.
   - Tests: Deterministic mocks; verify ordering/rationales.

### Phase 5 — Validation and one‑shot builds

1. Tool: writing.validateReferences
    - Behavior: Scan Markdown for citekey patterns (`[@key]`, `@key`, LaTeX `\\(text|paren)cite{}`); report unresolved keys, duplicates, unused entries (vs exported bib), missing fields (author/title/year/DOI).
    - Impl: Regex extraction; use `library.resolveCitekeys` + exported file parsing; optional suggestions.
    - Acceptance: Report structure matches `ValidationReport` in `zotero_requirements.md`.
    - Tests: Markdown fixtures with edge cases (code blocks, escaped @, YAML blocks).

1. Tool: exports.build
    - Behavior: Produce DOCX/HTML/PDF with resolved citations using Pandoc `--citeproc`; default PDF via headless Edge; optional xelatex when configured.
    - Impl: Subprocess to `pandoc`; environment flags for paths; collect logs; return output paths and warnings.
    - Acceptance: Given a minimal Markdown + references/style, returns valid outputs; graceful errors when Pandoc or engines are missing.
    - Tests: Mark as integration/optional; smoke test if Pandoc present; unit test command construction otherwise.

### Phase 6 — Caching, limits, polish

1. Cross‑cutting
    - Add in‑memory cache for search/library snapshots with short TTL.
    - Rate‑limit Web API calls; surface `Retry‑After` in errors (already partially implemented).
    - Improve error shaping for write tools (already present via `_format_error`).
    - Logging: compact structured logs around exports and validation.

## Design notes and contracts

- Data contracts: Reuse the shapes specified in `zotero_requirements.md` (Item, ExportResult, ValidationReport) for tool output payloads where applicable.
- Local vs Web API:
  - Keep current guardrails: local mode is read‑only for Zotero data writes.
  - Prefer local Better BibTeX for citekeys/auto‑export; provide clear fallbacks when unavailable.
- Atomic file writes: Write temp file and atomically replace to avoid partial reads by other tools (especially on Windows/OneDrive).
- Hashing: use SHA‑256 of file contents for export verification and change detection.

## Mapping to code and tests

- New tools live in: `src/zotero_mcp/__init__.py` (consistent with existing tools)
- Client helpers (HTTP, YAML, hashing) can go in `src/zotero_mcp/client.py` or a new small `utils.py` if they don’t depend on Zotero client.
- Extend tests in place:
  - `tests/test_search.py`: add suggest ranking tests.
  - `tests/test_item_operations.py`: add collection navigation tests if formatting helpers added.
  - `tests/test_write.py`: keep write guardrails; add style/YAML idempotency tests.
  - New: `tests/test_collections.py`, `tests/test_bibliography.py`, `tests/test_validate.py` as needed.

## Acceptance checklist (high level)

- [ ] From a selection, I can request suggestions and insert a `[@key, p. 42]` snippet.
- [ ] `references.bib/json` is kept in sync via Better BibTeX auto‑export when local Zotero is available; otherwise on‑demand export works.
- [ ] Validation highlights unresolved/duplicate keys and missing fields with actionable hints.
- [ ] One command builds DOCX/HTML/PDF with the repo’s CSL style; outputs land next to the manuscript.
- [ ] Opening `zotero://select/...` for an item key works.

## Risks and mitigations

- Better BibTeX endpoint variability: Detect capability and fail with guidance; keep on‑demand export as fallback.
- Citekey source of truth: Prefer BBT; otherwise parse exported bib/CSL JSON; document precedence.
- Platform PDF engine differences: Default to Edge headless; make LaTeX optional and explicitly configured.
- Rate limits and library locks: Respect `Retry‑After`; surface friendly messages (existing `_format_error`).

## Next steps (immediate)

1) Implement `library.getCollections` and `files.openInZotero` with unit tests.
2) Implement `library.exportBibliography` and `styles.ensureStyle` + `workspace.ensureYamlCitations` (file IO + idempotent writes).
3) Iterate with `library.ensureAutoExport` (local BBT); add graceful fallback.

This sequence unlocks navigation, stable bibliography files in‑repo, and prepares for authoring helpers and builds.
