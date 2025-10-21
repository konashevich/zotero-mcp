# Plan 6 — Problem → Solution (content-based MCP)

Short, plain-English fixes for the issues reported by the AI agent. No backward compatibility; content-first APIs with clear, actionable behavior.

| Problem | Solution |
|---|---|
| 1) Bibliography content is unusable | Return actual CSL JSON items, not a wrapper. Output must be a CSL JSON array (objects with id, title, author, issued, etc.). Provide stable ordering, plus diagnostics (count, sha256). Support optional scope (collection) and item filters to limit payload size. |
| 2) Type contract rigidity and fragile DX | Accept both string and parsed JSON for bibliographyContent/cslContent; normalize internally (parse if string, stringify if object). Validate with a light schema; on error, return a friendly message explaining accepted forms and a short schema summary. Add optional bibliographyFormat: "csljson" to disambiguate. |
| 3) Content-based build blocked by server env | Install Pandoc in the Docker image (server-side) so builds work out of the box. Also detect Pandoc on start/use; if an operator opts out (custom image), return an actionable message with install hint and an optional pandocPath override. Provide a client-build mode that returns ready-to-run args/script for the client when server binaries are absent. Mock Pandoc in tests to verify command assembly. |
| 4) PDF engine on Linux (no browsers) | Use non-browser engines only. Auto-detect order: wkhtmltopdf → xelatex. Expose pdfEngine values ["wkhtmltopdf","xelatex"] and enginePath override. Log the chosen engine and version in diagnostics; fall back gracefully. |
| 5) YAML ensure/validate for non-[@] manuscripts | Make ensure_yaml_citations_content idempotent (return changed=false when nothing to update). For validation, if no [@] citations are found, return success with info: "No Pandoc citations found; keep footnotes or add [@keys] for citeproc." Do not error just because there are no citations. |
| 6) Error messaging quality | Wrap framework/Pydantic errors into task-level messages with remediation. Examples: "bibliographyContent must be CSL JSON (string or parsed object)", "Pandoc not found—install or use pandocPath/client-build". Include compact diagnostic codes (e.g., INVALID_BIBLIOGRAPHY_INPUT, PANDOC_MISSING) and a one-line fix. |
| 7) No guidance for large binary outputs | Document limits and behavior. If artifacts are small, return data URIs (guarded by EXPORTS_EMBED_DATA_URI). If large, return server-native temp paths or an object-id/URL for later retrieval; optionally support returnBase64 for clients without streaming. Consider chunking/streaming when client supports it. |

Notes
- Keep content-first contracts; remove path-based inputs from public tools (no backward compatibility).
- Normalize line endings to \n and use utf-8-sig for text inputs; rely on PyYAML only (fail fast otherwise).
- Add unit tests for: bib payload correctness and ordering, input normalization, no-citation validation UX, Pandoc/engine detection and fallbacks, and large-output handling (data URI vs path/object-id).

## Server upgrade checklist (actionable)

- Dockerfile: install Pandoc in the image (apt-get install -y --no-install-recommends pandoc). If using xelatex, also install texlive-xetex texlive-fonts-recommended; or prefer a browser-based engine and install chromium or wkhtmltopdf.
- Code: keep runtime detection and fallbacks (friendly errors + client-build kit) to support slim custom images, but default path is server-side build.
- Config toggles: EXPORTS_EMBED_DATA_URI for inlined artifacts; allow pdfEngine and enginePath overrides; optional PANDOC_PATH.
- Tests: mock Pandoc to verify CLI assembly; add tests that assert data-URI vs temp-path behavior; verify engine detection ordering on Linux.
