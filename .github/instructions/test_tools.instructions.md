When tasked with tool testing you must use your actual access to the Zotero MCP server's tools as the agent. YOU DO NOT TEST VIA COMMUNICATING WITH DOCKER SERVER DIRECTLY. YOU MUST TEST IT VIA MCP SERVER TOOLS AVAILABLE TO YOU AS THE AGENT IN THIS CHAT.


# Zotero MCP Server – End-to-end Test Methodology

This document records a reusable methodology for fully testing the Zotero MCP server against the manuscript `Debunking Blockchain Misconceptions.md`, with the MCP server running remotely on Linux and the editor on Windows/OneDrive. It focuses on the practical authoring/validation/export workflows required for a hands‑free citations pipeline.

## Scope and objectives

- Verify that the Zotero MCP server enables a complete citations workflow without relying on local file paths, using content‑based tool variants when the server is remote.
- Concentrate on behaviours needed to prepare citations and build outputs (DOCX/PDF). Problems and gaps are called out explicitly under “Observed” and “Reported”.

## Test environment

- Client: Windows (VS Code), manuscript at `Public VS Private/Debunking Blockchain Misconceptions.md`.
- Server: Linux, MCP server “zotero” accessible over home network.
- Editor pipeline baseline: Local VS Code task “Export with citations (DOCX+PDF)” known to succeed (Pandoc + citeproc). On Linux, PDF builds use wkhtmltopdf or xelatex.
- Manuscript YAML: Present and pointing to `style.csl` and `references.json`.

## Test matrix and steps

Each feature below states how it was tested (inputs and procedure), why it was tested that way (the real workflow it should support), the expected behaviour, the observed behaviour, and what was reported as an issue or gap.

### 1) CSL style retrieval

- How used
  - Path‑based: `ensure_style("springer-lecture-notes-in-computer-science")` → write to `style.csl`.
  - Content‑based: `ensure_style_content("springer-lecture-notes-in-computer-science")` → return CSL XML content and hash.
- Why (real action)
  - Authors need a correct CSL to format citations consistently (LNCS in this project).
- Expected
  - Path‑based: file saved to `style.csl`.
  - Content‑based: CSL XML string + integrity metadata (hash/etag).
- Observed
  - Path‑based: succeeded for the LNCS id; 404 on an incorrect alias (as expected for a bad id).
  - Content‑based: returned valid CSL XML with SHA256.
- Reported
  - Note to improve discoverability of valid style IDs; otherwise no blocker.

### 2) Bibliography export (CSL JSON)

- How used
  - Content‑based: `export_bibliography_content(scope="library", format="csljson")` to retrieve a CSL JSON bibliography as a string for direct use (no filesystem writes).
- Why (real action)
  - Content‑based flows must provide real CSL JSON for citeproc, validation, and builds when server and editor do not share a filesystem.
- Expected
  - A CSL JSON string (array of item objects with fields like `id`, `title`, `author`, `issued`, `container-title`, `DOI/URL`, etc.), plus `count` and `sha256` for diagnostics.
- Observed
  - Returned a placeholder string such as `["items", …]` with correct `count`/`sha256` but no actual CSL JSON entries.
- Reported
  - Blocker: bibliography “content” unusable for citeproc or any downstream tooling; must return real CSL JSON.

### 3) YAML ensure (content‑based and earlier path‑based context)

- How used
  - Earlier path‑based: `ensure_yaml_citations(documentPath=Windows path with spaces)`; expected no‑op because YAML already present.
  - New content‑based: `ensure_yaml_citations_content(documentContent, cslContent, bibliographyContent, linkCitations=true)`.
- Why (real action)
  - Client should send document content and receive updated content; idempotent edits, no reliance on server filesystem.
- Expected
  - If YAML already matches, return “no changes”. Otherwise, inject/update YAML keys and return updated document content.
- Observed
  - Path‑based (earlier): failed due to mixing Linux container prefixes with Windows paths.
  - Content‑based: rejected `bibliographyContent` when passed as parsed JSON (type rigidity) and emitted framework validation errors.
- Reported
  - Blocker: accept both raw string and parsed JSON, normalise internally; ensure idempotent updates and user‑level error messages.

### 4) Reference validation (content‑based)

- How used
  - `validate_references_content(documentContent with footnotes/no [@keys], bibliographyContent from export)`.
- Why (real action)
  - Authors want a quick pre‑export check (unresolved keys, duplicates, missing fields); also need a helpful message when still using footnotes and not [@keys].
- Expected
  - If no [@keys], return an informative “no citations found” result (not an error). If [@keys] exist, validate against CSL JSON and return an actionable report.
- Observed
  - Rejected `bibliographyContent` because it was not a string; validation failed at type level before any semantic checks.
- Reported
  - Blocker: same input normalisation issue; add a graceful path for footnote‑only manuscripts.

### 5) Library exploration (collections, search, suggestions)

- How used
  - `get_collections` to enumerate; `search_items` with realistic queries (e.g., “Bitcoin”, “Hyperledger Fabric”); `suggest_citations` with representative text.
- Why (real action)
  - Authors need to discover items and retrieve [@keys]; collections support scoped exports.
- Expected
  - Collections tree; search returns relevant items; suggestions ranked with short rationales.
- Observed
  - Collections and search behaved as expected; suggestions worked but rationales were occasionally generic.
- Reported
  - Not a blocker; suggestions could be more informative, but outside the critical path.

### 6) Server‑side builds (DOCX/PDF) via content

- How used
  - `build_exports_content(documentContent, cslContent, bibliographyContent, formats=["docx","pdf"], pdfEngine="edge")`.
- Why (real action)
  - One‑command server‑side build without client paths; ideal when server orchestrates outputs.
- Expected
  - Generate DOCX/PDF from content; if Pandoc is missing, return actionable remediation (install guide or `pandocPath` override). Provide a client‑build fallback recipe if server lacks dependencies.
- Observed
  - First failed on bibliography type validation; historically the server also failed with “Pandoc not installed or not in PATH”.
- Reported
  - Blocker: input normalisation, environment detection for Pandoc, and clear remediation/fallback.

### 7) PDF engine portability on Linux

- How used
  - Requested `pdfEngine="edge"` (mirroring Windows default).
- Why (real action)
  - Many Linux hosts won’t have Edge; tool should auto‑select Chromium/Chrome/wkhtmltopdf or accept explicit overrides.
- Expected
  - Engine detection on Linux with graceful fallback and clear logs; support `pdfEngine` and `enginePath` overrides.
- Observed
  - No automatic fallback evident; failures likely without explicit server setup.
- Reported
  - Blocker: add engine detection and fallback; expose friendly selection diagnostics.

### 8) Local sanity check with VS Code task

- How used
  - Ran “Export with citations (DOCX+PDF)” locally to verify the manuscript/YAML and baseline outputs.
- Why (real action)
  - Establish that manuscript content and YAML are valid; isolate MCP tool issues from document issues.
- Expected
  - Local export succeeds; confirms citation wiring.
- Observed
  - Succeeds as expected; one failure traced to nested shell quoting of the Markdown path with spaces (task invocation nuance, unrelated to MCP).
- Reported
  - Confirms server issues are not due to manuscript problems.

## Consolidated expectations (what “done” looks like)

- `export_bibliography_content` returns real CSL JSON (string), with `count`/`sha256`.
- All content‑based tools accept `bibliographyContent` as either a raw CSL JSON string or a parsed JSON object, normalising internally; emit user‑level, actionable errors on malformed inputs.
- `ensure_yaml_citations_content` is idempotent; returns “no changes” when YAML already matches; never hard‑fails because a document lacks [@keys].
- `validate_references_content` returns “no citations found” when appropriate; otherwise a clear report (unresolved keys, duplicates, missing fields).
- `build_exports_content` detects Pandoc; if absent, provides installation guidance or `pandocPath` override and a client‑build fallback recipe. For PDF on Linux, auto‑detect non‑browser engines (wkhtmltopdf → xelatex) with sensible defaults and overrides.
- Output delivery clarifies size limits and, when needed, supports alternative delivery (e.g., link/object id or chunking/base64) for large artefacts.

## Reporting discipline

For each tool call, capture:

- Inputs used (ids, scope, payload shapes)
- The real workflow it represents (authoring, validation, export)
- Expected outcome/behaviour
- Observed output (including error messages)
- A short, actionable remediation or change request

This methodology exercises tools exactly as an author or build system would use them, surfaces precise failure modes, and defines concrete acceptance criteria to close gaps and reach a robust, hands‑free citations pipeline.
