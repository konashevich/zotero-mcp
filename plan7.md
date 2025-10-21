# Plan 7 — Linux-first, Windows client; no-nonsense plan

Goal: A robust Zotero MCP server running on Linux that serves a Windows-based client over the home network. Content-first APIs, zero cross-OS paths, server actually builds documents.

For each area: Is it stupid here? Why is it in scope? What’s the proper solution?

## 1) Bibliography content (CSL JSON)

- Stupid? Yes, if it returns anything except real CSL JSON items.
- Why in scope: Client must validate/build without touching disk.
- Proper solution: Return a stable-ordered CSL JSON array of item objects. Include diagnostics (count, sha256). Support optional scope filters. Tests assert the array shape and that citeproc accepts it.

## 2) Input type normalization (string vs parsed JSON)

- Stupid to reject parsed JSON? Yes. Real clients parse/manipulate.
- Why in scope: Smooth DX, fewer type-gotchas.
- Proper solution: Accept string or parsed objects; normalize internally. On error, show human guidance and a tiny schema summary. Optional `bibliographyFormat: "csljson"` accepted but not required.

## 3) Server builds (Pandoc)

- Stupid to error-only? Yes. The server must build.
- Why in scope: The Linux server is the build executor.
- Proper solution: Install Pandoc in the Docker image. Detect at runtime for slim custom images; if missing, provide an actionable message and a client-build kit. Tests mock Pandoc and verify CLI assembly.

## 4) PDF engine on Linux (no browsers)

- Why in scope: PDF needs a rendering engine.
- Proper solution: Use only non-browser engines. Auto-detect order: wkhtmltopdf → xelatex. Ship wkhtmltopdf in the image by default; optionally provide a “full” image variant with xelatex. Log chosen engine/version.

## 5) YAML ensure/validate behavior

- Stupid to error on no citations? Yes.
- Why in scope: Authors may use footnotes before adding [@].
- Proper solution: ensure_yaml_citations_content is idempotent; validate returns informative success when no [@] found. Tests cover no-citation path.

## 6) Errors and diagnostics

- Stupid to surface Pydantic/raw traces? Yes.
- Why in scope: Non-experts need actionable guidance.
- Proper solution: Wrap errors with task-centric messages and short fixes. Add compact diagnostic codes (e.g., INVALID_BIBLIOGRAPHY_INPUT, PANDOC_MISSING). Keep low-level traces in logs only.

## 7) Large outputs and delivery

- Stupid to ignore size? Yes.
- Why in scope: DOCX/PDF can be multi‑MB.
- Proper solution: Document size limits. If small, return data URIs when EXPORTS_EMBED_DATA_URI=true. If large, return server-native temp paths or a durable object-id/URL. Consider chunking when the client supports it.

## 8) Windows paths and cross-OS mapping

- Stupid to accept client paths? Yes.
- Why in scope: Avoid cross-OS headaches.
- Proper solution: Content-based tools only. The server writes temp files internally when needed. No path mapping in public inputs.

## 9) Docker image: what we ship

- Stupid to ship without required binaries? Yes.
- Why in scope: Users expect builds to work.
- Proper solution: Update Dockerfile to install: pandoc, wkhtmltopdf (or chromium), minimal fonts. Keep image lean (no full TeX unless required). Verify with a startup check.

## 10) Health and observability

- Stupid to be opaque? Yes.
- Why in scope: Quick triage and reproducibility.
- Proper solution: Extend `zotero_health` to report: pandoc version, chosen PDF engine/version, YAML parser, and key flags (EXPORTS_EMBED_DATA_URI). Keep it compact JSON under a markdown heading.

## 11) Tests that matter

- Bibliography returns real CSL JSON and stable order.
- Input normalization accepts string/object; helpful error on invalid.
- No-citation validation returns informative success.
- Pandoc mocked: command line is assembled as expected; build artifacts returned with data URI vs path based on env.
- Engine detection: Linux ordering honored, logging shows the selected engine.

## 12) Operator knobs (documented)

- ENV: EXPORTS_EMBED_DATA_URI, PANDOC_PATH, PDF_ENGINE, PDF_ENGINE_PATH.
- Tool params: pdfEngine/enginePath accepted but optional; defaults are auto-detected.
- Clear doc for size thresholds and delivery modes.

## 13) Breaking changes stance

- No backward compatibility with path-based tools. Old params removed.
- Content-first inputs and deterministic outputs only.

## 14) Deliverables

- Code: updated tools in `src/zotero_mcp/__init__.py`.
- Docker: updated Dockerfile (pandoc + wkhtmltopdf/chromium), startup checks.
- Docs: README updates; plan and health examples.
- Tests: added/updated in `tests/` for the above behaviors.
