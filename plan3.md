# Improvement Plan for Zotero MCP Server (Oct 2025)

This plan addresses the YAML front‑matter issue and strengthens reliability, defaults, and operability of the server.

## 0) Immediate hotfix: YAML front matter without PyYAML

- Goal: ensure_yaml_citations works even if PyYAML isn’t available on the target.

- Actions:

  - Try-import PyYAML; on ImportError, fall back to a safe, text-only YAML front matter updater:
    - Detect/update YAML fence.
    - Upsert: bibliography, csl, link-citations.
    - Preserve other keys and the document body; idempotent behavior.
  - Add tests that exercise both code paths (with and without PyYAML).

- Acceptance: Tool succeeds on machines without PyYAML and is idempotent.

## 1) Packaging and container parity

- Goal: Image always contains required deps; build fails early if not.

- Actions:

  - Keep PyYAML in pyproject (already present).
  - Add Docker build check: `python -c "import yaml"` to fail early.
  - Document host (non-Docker) install steps to guarantee PyYAML presence.

- Acceptance: Image build fails fast if yaml import would fail; README clarifies host setup.

## 2) Diagnostics and health

- Goal: Quick visibility into readiness and config.

- Actions:

  - New tool: `zotero_health` returns PASS/FAIL, notes:
    - `yaml` import ok
    - Zotero API reachability (local/web per env)
    - Cache settings, timeouts, rate-limits (current values)
  - Optional: log concise health summary at startup.

- Acceptance: Single call yields a clear health report with causes for any FAIL.

## 3) SuggestCitations “local‑first” enhancement

- Goal: Reduce latency and server calls for broad queries.

- Actions:

  - Detect DOI/title/author tokens; score against cached recent items first.
  - Only hit server if local score < threshold.
  - Gate via `ZOTERO_SUGGEST_LOCAL_FIRST=true` env.

- Acceptance: Obvious DOI/title token queries return quick suggestions locally; server call remains a fallback.

## 4) Defaults and ergonomics

- Goal: “It just works.”

- Actions:

  - Keep defaults in place:
    - Default CSL auto-fetch LNCS into `.styles/lncs.csl` when none provided.
    - Default auto-export path `references.bib` and format `bibtex` when unspecified.
  - Add `.env.example` documenting ZOTERO_* variables and sensible defaults.

- Acceptance: Fresh setup can export and build with no prompts.

## 5) Observability and rate-limits

- Goal: Predictable behavior under load and simple debugging.

- Actions:

  - Structured logs around tool calls with elapsed time and status.
  - Expose/tune via env: request timeout, cache TTL/max, min rate interval; document all.
  - Apply jittered backoff on network retries (keep delays modest).

- Acceptance: Timeouts/retries visible in logs; reduced burstiness.

## 6) Build orchestration polish

- Goal: One-click/documented builds for DOCX/HTML/PDF.

- Actions:

  - Keep `scripts/build_exports.py` and VS Code tasks.
  - Optional `Makefile` targets: `make build-docs`, `make build-pdf`.

- Acceptance: Tasks produce outputs with default CSL and bibliography without extra flags.

<!-- Removed non-local items: CI, public release/publish. Plan below focuses on local implementation only. -->

---

## Suggested sequencing (local-only)

1. Implement 0 (YAML fallback) + basic local test.
2. Add 1 (Docker build import check) and 2 (health tool).
3. Implement 3 (local-first) behind env flag.
4. Apply 4–6 (defaults/ergonomics, observability/rate-limits, build tasks/Makefile).

## Success metrics (local)

- ensure_yaml_citations works without PyYAML and is idempotent on your machine.
- SuggestCitations feels snappy for obvious queries; retries/backoff are visible in logs when needed.
- Default CSL/export produce expected outputs without extra setup.
