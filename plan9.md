# Plan 9 — Base64 exports, no HTML, smart naming

## 1. Diagnose current behavior
- Inspect `src/zotero_mcp/__init__.py` and helpers used by `build_exports_content` to map artifact creation, naming, and returned schema.
- Review existing tests/fixtures that touch export tools so the regression surface is clear.

## 2. Return base64 artifacts (no server paths)
- Refactor `build_exports_content` to read each generated file, base64-encode it, and return objects shaped `{format, filename, content, size, warnings?}`.
- Validate outgoing payloads (pydantic/dataclasses) to guarantee predictable fields for clients.

## 3. Remove HTML as a supported format
- Drop `html` from defaults; reject it explicitly during input validation with an actionable error.
- Clean up scripts/docs/tests that assume `/tmp/.../out.html` or browser-based HTML workflows.

## 4. Smart filename selection
- Accept an `outputBasename` parameter; if absent, derive it from Markdown front-matter `title`, sanitized, with fallback to `document`.
- Apply the basename consistently to both temp files and returned filenames so diagnostics line up.

## 5. Engine and dependency detection
- Implement `ensure_pandoc()` to locate Pandoc (respect `PANDOC_PATH`) or raise a friendly install hint.
- Add `detect_pdf_engine()` that prefers `wkhtmltopdf`, then `weasyprint`, then `xelatex`, surfacing clear errors when none are available.
- Include chosen paths/engines in tool diagnostics.

## 6. Warnings and logging
- Emit structured warnings when a format is skipped, an engine is missing, or encoding fails.
- Update health checks/startup logs to report pandoc path, active PDF engine, and whether base64 delivery is enabled.

## 7. Test coverage
- Extend tests to assert base64 content is returned, filenames follow expectations, and HTML requests are rejected.
- Add cases for missing pandoc/pdf engines, title-derived basenames (unsafe characters, repeat runs), and size-field accuracy.

## 8. Documentation and client guidance
- Update `README.md` (and relevant client docs) to explain base64 responses, the no-HTML stance, and dependency detection.
- Provide example client snippets showing how to decode and save artifacts; add troubleshooting tips for missing dependencies.

## 9. Verification and rollout
- Run full test suite and export integration checks (DOCX/PDF).
- Manually exercise the MCP tool to confirm base64 payloads decode correctly and no HTML is generated.
- Summarize ready-to-commit changes and note any follow-up tasks (e.g., client updates).
