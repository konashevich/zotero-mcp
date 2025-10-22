# Copilot instructions for zotero-mcp

This ZOTERO MCP server is designed to run on linux-based machine. The user (AI agent) of this sever is based in the homen network, using Windows OS. Therefore, all file uploads and downloads must be handled via server-side paths and HTTP endpoints, avoiding any cross-OS path mapping. More over, as any AI, it has limited context windows, so neither sending files nor receiving files should go directly via AI agent context window, but bypass it. 

These notes align AI coding agents quickly to this repo’s patterns, workflows, and pitfalls. STRICT RULE: No backward compatibility. Remove legacy code and fallbacks when updating tools or behaviors.

## Big picture
- This is a Python Model Context Protocol (MCP) server exposing Zotero tools over SSE.
- Entry points:
  - `src/zotero_mcp/__init__.py`: all MCP tools (read, write, exports, validation). Also logging, caching, path handling, and file registry for downloads.
  - `src/zotero_mcp/cli.py`: wires FastMCP server (SSE) for `zotero-mcp` command. Adds HTTP file download endpoint at GET /files/{token}.
- Key integrations: PyZotero client (via `zotero_mcp.client`), PyYAML/ruamel for YAML, Pandoc for exports, Better BibTeX auto‑export (local API at 127.0.0.1:23119).
- Docker image provides a runnable SSE server; Make targets automate build/redeploy.
- File downloads: Generated files (PDF/DOCX) are served via HTTP to bypass AI context window. Files stored temporarily with token-based access and TTL cleanup.

## Critical workflows
- Run locally (no Docker): `uv run zotero-mcp` (set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in env or .env.local).
- Run tests: `uv run pytest` (CI expects green). Keep tests fast and deterministic.
- Docker redeploy on this device: `make docker-redeploy` (builds image, restarts container `zotero-mcp-sse`, shows health logs).
- Inspect tools live: `npx @modelcontextprotocol/inspector uv run zotero-mcp`.

## Conventions and patterns
- Tools live in a single module (`src/zotero_mcp/__init__.py`) using `@mcp.tool` decorators.
- NO BACKWARD COMPATIBILITY: replace old tools/params outright. Delete legacy aliases and code paths.
- Prefer content-based tools (accept strings, return strings/patches). Do not accept file paths unless absolutely required by an external binary (e.g., Pandoc). If paths are required, they MUST be server-native only (no cross-OS mapping).
- YAML parsing: use PyYAML if present; else fail fast with a clear error. Do not add text/ruamel fallbacks. Preserve keys and order; ensure idempotent writes.
- Path handling (when unavoidable): use `_normalize_path()`; do not attempt cross-machine mapping. If a path is inaccessible, fail fast with a clear hint.
- Write operations guardrails: respect `_write_guard()`; require `ZOTERO_API_KEY`/`ZOTERO_LIBRARY_ID` unless in `ZOTERO_LOCAL` mode.
- Logging: use module logger `logger` with UTC timestamps; `LOG_LEVEL` controls verbosity.
- Health reporting: `zotero_health` returns compact JSON with parser availability and core config.

## External dependencies
- PyZotero for Zotero Web API; network-dependent.
- Pandoc required for `zotero_build_exports` (ensure `pandoc` is available; if missing, fail with an actionable error).
- Better BibTeX local API at 127.0.0.1:23119; optional.

## Testing focus (examples in `tests/`)
- YAML front matter: idempotency, CRLF and BOM handling. No parser fallbacks; tests must pass with the default parser.
- Content-based flows first: prefer tests that pass strings instead of file paths.
- If a tool must use files, ensure tests run on server-native paths only; do not test cross-OS mappings.
- Build exports: mock `pandoc` binaries; verify command line assembly.

## Docker and deployment
- Image built from `Dockerfile` using `uv sync`; build verifies minimal imports.
- Prefer content-based tools to avoid bind mounts. If bind mounts are needed, they must be server-native; do not document cross-OS drive mapping within tools.
- Deployment docs live in `.github/instructions/deploy.instructions.md`.

## Patterns to follow when adding tools
- Prefer content-based APIs: accept documentContent/bibliographyContent/cslContent; return updatedContent/diagnostics.
- For YAML/text I/O: normalize line endings to `\n`; encoding `utf-8-sig`.
- Return concise, markdown‑friendly strings; include compact JSON sections when useful.
- Use small, local helpers in `__init__.py` for consistency (caching, rate limiting, error formatting). Remove legacy branches when updating.
- Export tools (build_exports_content) return download tokens, not file content. AI agents download files via HTTP GET to /files/{token}. Files stored in /tmp/mcp-files/{token}/ with automatic cleanup. NO base64 content in tool responses (removed for efficiency).

## Gotchas
- No backward compatibility: delete old params/aliases when changing public tool shapes.
- Cross‑machine paths are out of scope: tools should not attempt cross‑OS mapping; fail fast.
- Pandoc availability varies; fail with actionable install hints when missing.
- Don’t sort YAML keys; only update citation‑related fields.

## Quick file map
- `src/zotero_mcp/__init__.py` — tools, helpers, path normalization.
- `src/zotero_mcp/cli.py` — CLI entry.
- `src/zotero_mcp/client.py` — Zotero client helpers.
- `scripts/run-docker.sh` — local run/deploy with optional mounts.
- `tests/` — fast, focused tests; includes Windows path and YAML scenarios.
- `README.md` — tool usage; `.github/instructions/deploy.instructions.md` — AI deploy guidance and ops.
