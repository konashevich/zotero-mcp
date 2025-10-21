# Plan 5 — Content-based MCP tools (No Backward Compatibility)

Strict policy: No backward compatibility. Replace path-based tools with content-based tools. Remove legacy params/aliases. Fail fast on missing dependencies. Tools accept strings (content) and return strings/patches/JSON reports.

## Goals

- Eliminate cross-OS path issues entirely.
- Make tools portable across clients and deployments.
- Reduce file-system coupling; clients handle I/O locally.
- Preserve idempotency and clear diagnostics.

## Scope (breaking changes)

- Remove path-based inputs from public tools that read/write documents/bibliographies/styles.
- Introduce content-first equivalents with new names and shapes.
- Remove cross-OS path normalization in tools (internal `_normalize_path` stays only where external binaries require files).

## New tools (content-first)

1. zotero_ensure_yaml_citations_content

   - Input:
     - documentContent: string (utf-8, accepts BOM; normalizes to \n)
     - bibliographyContent?: string (CSL JSON)
     - cslContent?: string (CSL XML)
     - linkCitations?: boolean (default true)

   - Output:
     - updatedContent: string
     - changed: boolean
     - parser: "pyyaml"
     - diagnostics: { keysUpdated: string[], preservedKeys: string[] }

2. zotero_validate_references_content

   - Input:
     - documentContent: string
     - bibliographyContent: string (CSL JSON)
     - requireDOIURL?: boolean (default true)

   - Output:
     - unresolvedKeys: string[]
     - duplicateKeys: string[]
     - missingFields: { id: string, missing: string[] }[]
     - suggestions?: Record<string, any[]>

3. zotero_insert_citation_content

   - Input:
     - citekeys: string[]
     - style?: "pandoc" | "latex" (default pandoc)
     - pages?: string
     - prefix?: string
     - suffix?: string

   - Output:
     - snippet: string (ready to paste)

4. zotero_build_exports_content (hybrid)

   - Input:
      - documentContent: string
      - formats: ("docx"|"html"|"pdf")[]
      - bibliographyContent?: string (CSL JSON)
      - cslContent?: string
      - useCiteproc?: boolean (default true)
      - pdfEngine?: "wkhtmltopdf" | "xelatex" (default wkhtmltopdf)

   - Output:
      - artifacts: { format: string, path?: string, dataURI?: string, warnings?: string[] }[]

   - Notes:
      - If filesystem is required by Pandoc, write to temp files server-side and return artifacts as data URIs or server-native paths (configurable). Paths are server-native; no cross-OS mapping.

## Tools to deprecate (remove)

- zotero_ensure_yaml_citations (path-based)
- zotero_validate_references (path-based)
- zotero_build_exports (path-based) — keep only if hybrid output is too heavy, but prefer content variant.

## Implementation steps
 
1. Add new content-based tools to `src/zotero_mcp/__init__.py`.
   - Shared helpers: BOM/CRLF normalization; compact JSON diagnostics; YAML via PyYAML only (fail fast otherwise).

2. Remove/rename path-based tools (no aliases). Update `mcp = FastMCP("Zotero")` registrations.

3. Tests
   - Add tests for happy path + idempotency for ensure_yaml_citations_content.
   - Validate_references_content with minimal CSL JSON; unresolved/missing fields cases.
   - Build_exports_content: mock pandoc; verify temp-file assembly and data URI results.

4. Docs

- README: replace usage snippets with content-based examples.
- Remove cross-OS path guidance from operational docs.
- `.github/copilot-instructions.md`: already mandates content-based preference and no backward compatibility.

1. Optional knobs
   - `EXPORTS_EMBED_DATA_URI=true` to return artifacts inline; otherwise write to a temp dir and return server-native paths.

## Acceptance criteria

- All tests pass in CI.
- New tools available; old path-based ones removed.
- Tools return deterministic, markdown-friendly outputs and compact JSON diagnostics.
- No path mapping logic in tool inputs; fail fast if external files are requested.

## Risks & mitigations

- Large documentContent/bibliographyContent payloads: consider size caps; document guidance; potential gzip at transport layer if supported by client.
- Pandoc requirement for files: use temp files transparently; document that returned paths are server-native only when not embedded.

## Follow-ups

- Add a small diff/patch format for updatedContent to minimize client write churn.
- Add streaming build logs for long-running export jobs.
