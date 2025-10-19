# Improvement plan: YAML front matter tool and end-to-end citation exports

Date: 2025-10-19

## Summary of the feedback

- Ensure CSL style: PASS (APA saved to `style.csl`).
- Export bibliography (library → CSL JSON): PASS (wrote `references.json`).
- Ensure YAML citations in Debunking Blockchain Misconceptions.md: FAIL with `No module named 'yaml'`.
- Interpretation given: MCP tool needs PyYAML or a bundled parser. DOCX/PDF exports still work when passing `--citeproc --bibliography --csl` explicitly.

## Current repo state (observed)

- `ensure_yaml_citations` exists in `src/zotero_mcp/__init__.py` and already has a no-dependency text-based fallback if `import yaml` fails. Tests pass locally, including `test_ensure_yaml_citations`.
- `pyproject.toml` declares both `PyYAML>=6.0.1` and `ruamel.yaml>=0.15.0` as dependencies.
- Dockerfile installs dependencies with `uv sync` and performs a build-time import check for `yaml` (PyYAML) and `ruamel.yaml`.
- `zotero_health` reports whether `yaml` is importable; if not, it currently just says "missing".

Conclusion: The reported failure likely came from running a different or older build of the server (without the fallback) or outside the Docker/uv-managed env where PyYAML wasn’t installed. We can harden behavior, observability, and docs to eliminate confusion.

## Goals

1. Make YAML front matter insertion robust across environments (with or without PyYAML).
2. Improve diagnostics so users know fallback will still work even if `yaml` is not importable.
3. Ensure packaging/deploy paths consistently ship a working server (Docker + uv + local execution).
4. Expand tests to cover more YAML edge cases and explicitly simulate missing YAML libs.
5. Document a manual fallback snippet and a quick verification flow.

## Changes to implement

### 1) Harden ensure_yaml_citations and its UX

- Keep the current zero-dep safe path and explicitly log which parser was used: `pyyaml`, `ruamel.yaml`, or `text`. Return message could include `parser=text` when falling back.
- Try import order: PyYAML → ruamel.yaml → text. Today we try `yaml` (PyYAML) only. Add a tiny adapter for ruamel.yaml to load/dump if present.
- Make regex more resilient to optional BOM and Windows newlines, but still anchored to file start. Acceptance: handles files with/without existing front matter and idempotently upserts the three keys.
- Idempotency: Running the tool multiple times should not duplicate keys or reorder unrelated keys unnecessarily (current text fallback keeps order; we’ll preserve that).

### 2) Health reporting and logs

- `zotero_health`: change `yaml` field to a richer status, e.g., `yaml="ok"|"missing"`, `ruamel="ok"|"missing"`, and `ensureYamlParser="pyyaml"|"ruamel"|"text" (predicted)`.
- At server startup, include that richer JSON in the log so it’s visible in `docker logs`.

### 3) Packaging, deployment, and reproducibility

- Keep `PyYAML` and `ruamel.yaml` as dependencies for best default behavior; they’re already present.
- Add an explicit note in README that the server works without these at runtime via a text fallback, but recommended images/bundles install them.
- Add a Makefile shortcut for the documented Docker redeploy sequence to minimize user error (wrapper around `scripts/run-docker.sh -d`).
- Ensure `uv.lock` is committed and up to date to keep Docker builds consistent (already included in image context; ensure it’s maintained).

### 4) Tests (expand coverage)

- Add tests that simulate environments:
  - Missing `yaml` (PyYAML) → ensure fallback path works.
  - Present `ruamel.yaml` only → ensure it’s used.
  - Existing front matter is updated in place (replace values, preserve unrelated keys, maintain order).
  - Idempotency: running twice yields unchanged content and no duplicates.
  - Handles CRLF newlines and BOM (write fixture with those characteristics).

### 5) Documentation and quick fallback

- README additions:
  - “YAML front matter” section with exact minimal snippet:
    ```yaml
    ---
    bibliography: references.json
    csl: style.csl
    link-citations: true
    ---
    ```
  - Troubleshooting: If `zotero_health` shows `yaml: missing`, it’s fine—`ensure_yaml_citations` will fall back to `parser=text`. Redeploy with Docker if you prefer full YAML support.
  - Cross-reference Local Docker redeploy steps from `.github/instructions/deploy.instructions.md` and include the one-liner Makefile target.
  - Mention the existing VS Code task “Export with citations (DOCX+PDF)” and how it works even without YAML front matter (because flags are passed explicitly). Clarify when front matter is helpful (portability across tools).

## Acceptance criteria
- Running `pytest` passes with the new, extended tests.
- `ensure_yaml_citations` reports success in all three parser modes on representative docs.
- `zotero_health` shows richer fields and the startup log includes them.
- Docker build succeeds and prints `yaml import ok` (or `ruamel.yaml import ok`) at build time.
- Manual build via the VS Code task still produces DOCX/PDF with resolved citations.

## Rollout/verification steps
1. Implement changes and run tests locally: `pytest -q`.
2. Build the Docker image and redeploy locally (see `.github/instructions/deploy.instructions.md`).
3. Tail logs and verify startup health JSON includes YAML/ruamel status and predicted parser.
4. Run the YAML tool against a few docs:
   - No front matter → inserted.
   - Front matter present but mismatched paths → updated.
   - Mixed newlines/BOM → still updated.
5. Run the export task to generate DOCX/PDF and confirm citations resolve.

## Optional niceties (future)
- Add a tiny CLI wrapper: `scripts/ensure_yaml.py -d <doc> -b <bib> -c <csl> [-l true|false]` calling the same function; useful outside MCP use.
- Provide a setting to force text-only mode if users want to avoid any parser influence.
- Add a workspace command (or VS Code task) to call the YAML tool directly.

## Why this plan
- Addresses both the immediate confusion (dependency message) and structural robustness (fallback + logs + tests).
- Maintains portability: works with or without YAML libs, yet continues to prefer full parsers when available.
- Clear troubleshooting and redeploy path reduce friction for users in different environments.
