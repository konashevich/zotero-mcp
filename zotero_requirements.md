# Zotero MCP Server: Vision, Capability Map, and Improvement Plan

This document defines how a full‑featured Zotero MCP server should work in this VS Code workspace, assesses the current implementation, and lists concrete improvements to reach hands‑free citation management and exports for the paper `Debunking Blockchain Misconceptions.md`.

## Vision

Enable the agent to use Zotero as a first‑class source of truth for citations and bibliographies, so it can:

- Insert citations as you write, using your Zotero library
- Keep the on‑disk bibliography (BibTeX/CSL JSON) continuously in sync via Better BibTeX auto‑export
- Validate references in the manuscript (missing items, duplicate keys, missing DOIs)
- Ensure the correct CSL style is present
- Produce DOCX/HTML/PDF on demand with resolved citations
- Work offline against the local Zotero app; fall back to Zotero Web API when local is unavailable

## High‑level architecture

- MCP server “zotero” with two adaptors:
  - Local adaptor: communicates with Zotero local HTTP endpoints (127.0.0.1:23119) and Better BibTeX (CAYW, auto‑export)
  - Cloud adaptor: communicates with Zotero Web API using an API key
- Export pipeline:
  - Pandoc + citeproc for DOCX/HTML
  - HTML → PDF via headless Edge on Windows (default, stable)
  - Optional: LaTeX (xelatex) path when a TeX toolchain is confirmed stable
- Workspace glue:
  - Bibliography file in repo (e.g., `references.bib` or `references.json`)
  - CSL style in repo (e.g., `style.csl`)
  - YAML front matter in the manuscript referencing the above

## Capabilities (tools the MCP should expose)

All tools return structured JSON with `success`, `data`, and `diagnostics`.

### Library and items

- library.searchItems
  - Input: free‑text query; optional filters (creator, year range, itemType, tags, collection)
  - Output: [{ key, citekey, title, creators, year, containerTitle, DOI/URL, tags, collections }]
- library.getItem
  - Input: item key or citekey
  - Output: full metadata (incl. attachments, notes, collections)
- library.getCollections
  - Input: optional parent collection
  - Output: tree of collections [{ key, name, parentKey, path, itemCount }]
- library.exportBibliography
  - Input: scope (collection key|library), format (biblatex|bibtex|csljson|ris), csl style (optional), path
  - Output: { path, count, hash, warnings }
- library.ensureAutoExport (Better BibTeX)
  - Input: path, format (bibtex|biblatex|csljson), translator (BBT), scope (collection|library)
  - Output: status (created|updated|verified), spec, lastExport

### Citations and writing

- library.resolveCitekeys
  - Input: array of citekeys
  - Output: map citekey → item metadata; unresolved/duplicate warnings
- writing.insertCitation
  - Input: citekeys, style ("pandoc" → returns `[@a; @b]`, "latex" → `\parencite{a,b}`), optional prefix/suffix/pages
  - Output: ready‑to‑insert text
- writing.suggestCitations
  - Input: selected text context
  - Output: ranked suggestions with brief explanations (title/author/DOI match)
- writing.validateReferences
  - Input: document path(s)
  - Output: report with unresolved citekeys, duplicate keys, unused entries, missing fields (author/title/year/DOI)

### Styles and workspace

- styles.findCslStyle
  - Input: style name fragment or URL
  - Output: matched CSL styles (id, title, field, link)
- styles.ensureStyle
  - Input: style id/URL, target path (e.g., `style.csl`)
  - Output: downloaded/verified path
- workspace.ensureYamlCitations
  - Input: document path, bibliography path, csl path, link‑citations (bool)
  - Output: updated YAML/verification status

### Exports

- exports.build
  - Input: document path; formats (docx|html|pdf); useCiteproc (bool); pdfEngine ("edge"|"xelatex"); extra args
  - Output: output file paths, logs, warnings

## Data contracts (summaries)

- Item: { key, citekey, title, creators[{family,given|literal}], date/year, containerTitle, publisher, DOI/URL, tags[], collections[], attachments[] }
- ExportResult: { path, count, hash, warnings[] }
- ValidationReport: { unresolvedKeys[], duplicateKeys[], unusedEntries[], missingFields[{key,fields[]}], suggestions[] }

## Core workflows

### 1. Cite‑as‑you‑write

- Suggest items from Zotero; insert `[@key, p. 42]`
- Ensure YAML has bibliography/style; ensure Better BibTeX auto‑export is active

### 2. Keep bibliography in sync

- On save/commit, verify `references.bib` (or `references.json`) is up to date (hash comparison)

### 3. Validate before export

- Detect unresolved citekeys, duplicates, missing DOIs; propose fixes

### 4. Build outputs

- DOCX/HTML via Pandoc + `--citeproc`
- PDF via Edge (default) or xelatex (optional)

### 5. Open items

- Open item in Zotero (`zotero://select/...`) for quick edits

## Security and permissions

- Store Zotero Web API key in secret storage; never write to repo
- Allow‑list local endpoints; validate origins
- Rate‑limit cloud calls; cache library snapshots
- Do not exfiltrate attachments unless explicitly requested

---

## Assessment of current implementation

Observed available tools (MCP):

- Search and retrieval
  - `zotero_search_items` (works)
  - `zotero_item_metadata` (works)
  - `zotero_item_fulltext` (works)
- Write operations
  - `zotero_create_item`
  - `zotero_add_note`
  - `zotero_update_item`
  - `zotero_set_tags`
- Export
  - `zotero_export_collection`

Strengths

- Core library access is present and responsive
- Ability to enrich items (notes/tags) exists
- Collection export endpoint exists (good basis for bibliography builds)

Gaps (relative to the target capability set)

### Gap 1: Library navigation

- Missing: `library.getCollections` to discover collections and keys programmatically

### Gap 2: Continuous bibliography sync (Better BibTeX)

- Missing: `library.ensureAutoExport` to set/verify "Keep updated" exports (BibTeX/CSL JSON) to repo paths

### Gap 3: Citation authoring helpers

- Missing: `library.resolveCitekeys` for validating [@keys]
- Missing: `writing.insertCitation`, `writing.suggestCitations`, `writing.validateReferences`

### Gap 4: Style and YAML management

- Missing: `styles.findCslStyle`, `styles.ensureStyle`
- Missing: `workspace.ensureYamlCitations`

### Gap 5: Build orchestration

- Missing: `exports.build` to run Pandoc (DOCX/HTML) and Edge‑based PDF in one step

### Gap 6: Convenience

- Missing: `files.openInZotero` (zotero://select) for quick access from VS Code

---

## Improvement plan

Phase 1 — Navigation and exports (foundations)

- Implement `library.getCollections` (list tree with keys)
- Implement `library.exportBibliography` by collection/library scope into repo root (`references.bib` or `references.json`)
- Implement `styles.ensureStyle` (download CSL into repo as `style.csl`)

Phase 2 — Auto‑export (hands‑free sync)

- Implement `library.ensureAutoExport` using Better BibTeX local endpoints to create/verify a “Keep updated” export to `references.bib`
- Fallback: on‑demand export via Zotero Web API when local not available

Phase 3 — Authoring helpers (productivity)

- Implement `library.resolveCitekeys` to map keys → items with warnings
- Implement `writing.insertCitation` to produce Pandoc `[@...]` or LaTeX `\parencite{}` strings
- Implement `writing.suggestCitations` using library search + rank (title/author/DOI match)
- Implement `workspace.ensureYamlCitations` to wire YAML front matter (bibliography/style/link‑citations)

Phase 4 — Validation and builds

- Implement `writing.validateReferences` (scan Markdown; report unresolved/duplicates/missing fields)
- Implement `exports.build` (DOCX/HTML via Pandoc + citeproc; PDF via Edge by default; xelatex optional)

Phase 5 — Conveniences and polish

- Implement `files.openInZotero` (launch `zotero://select/library/items/<key>`)
- Add caching for search results and library snapshots; add rate limiting

---

## Acceptance criteria (high level)

- Insert citation: From a text selection, I can ask for suggestions and the server inserts a formatted `[@key, p. 42]` segment.
- Keep updated bibliography: `references.bib` auto‑exports via BBT and remains in sync without manual steps.
- Validate references: Running validation yields a clear report (unresolved keys, duplicates, missing DOIs) and actionable suggestions.
- Export: One command builds DOCX/HTML/PDF with resolved citations and the declared CSL style; output files are placed beside the manuscript.

## Example data shapes (indicative)

Item (abridged)

- key: "ABCD1234"
- citekey: "nakamoto2008bitcoin"
- title: "Bitcoin: A Peer‑to‑Peer Electronic Cash System"
- creators: [{ family: "Nakamoto", given: "S." }]
- year: 2008
- containerTitle: "Self‑published"
- DOI: null
- URL: <https://bitcoin.org/bitcoin.pdf>
- tags: ["bitcoin", "blockchain"]
- collections: ["COLL1"]

ValidationReport (abridged)

- unresolvedKeys: ["smith2021missing"]
- duplicateKeys: ["doe2020dup"]
- unusedEntries: ["legacy2017notused"]
- missingFields: [{ key: "nakamoto2008bitcoin", fields: ["DOI"] }]
- suggestions: ["Brace capitalised words in BibTeX title for proper case preservation"]

---

## Notes on Windows specifics

- Default PDF engine should be Edge headless (reliable, no LaTeX required)
- If LaTeX is enabled, prefer explicit xelatex path configuration or verified PATH injection
- Be robust to OneDrive sync by avoiding long‑running file locks and using atomic writes for exported files

---

If you want, I can start implementing Phase 1 immediately and wire the MCP commands to the existing export scripts (`.vscode/export-with-citations.ps1` and `.vscode/export-pdf.ps1`).
