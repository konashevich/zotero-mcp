# Model Context Protocol server for Zotero

[![GitHub branch status](https://img.shields.io/github/check-runs/kujenga/zotero-mcp/main)](https://github.com/kujenga/zotero-mcp/actions)
[![PyPI - Version](https://img.shields.io/pypi/v/zotero-mcp)](https://pypi.org/project/zotero-mcp/)

This project is a python server that implements the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) for [Zotero](https://www.zotero.org/), giving you access to your Zotero library within AI assistants. It is intended to implement a small but maximally useful set of interactions with Zotero for use with [MCP clients](https://modelcontextprotocol.io/clients).

[![Zotero MCP server badge](https://glama.ai/mcp/servers/jknz38ntu4/badge)](https://glama.ai/mcp/servers/jknz38ntu4)

## Features

This MCP server provides the following tools. Strict policy: no backward compatibility; tools are content-first (strings in/out). YAML is PyYAML-only (fail-fast if unavailable). No cross-OS path mapping in tool inputs.

### Read Tools

- `zotero_search_items`: Search for items in your Zotero library using a text query
- `zotero_item_metadata`: Get detailed metadata information about a specific Zotero item
- `zotero_item_fulltext`: Get the full text of a specific Zotero item (i.e. PDF contents)
- `zotero_get_collections`: Retrieve collection tree with paths and item counts

### Write Tools (Web API only)

- `zotero_create_item`: Create a new item from a template, with optional tags/collections/parent
- `zotero_update_item`: Update an existing item by key (patch by default; supports put)
- `zotero_add_note`: Create a note (top-level or as a child of an item)
- `zotero_set_tags`: Replace or append tags on an item

### Export & Bibliography Tools

- `zotero_export_collection`: Export items in a collection to formats like RIS, BibTeX, CSL JSON, CSV, or styled bibliography/citations. For text formats (e.g., RIS/CSV), outputs are normalized as plain text. For CSL JSON, the tool validates shape; warnings/codes are included when upstream responses are not citeproc-ready.
- `zotero_export_bibliography_content`: Export library or collection bibliography as content with SHA-256 hash verification. For `format=csljson`, the tool ensures citeproc-ready CSL JSON. If upstream returns non-CSL JSON, it falls back to a minimal mapping (ids may be Zotero keys) and includes warnings/diagnostic codes.
- `zotero_ensure_style_content`: Retrieve CSL style content by ID or URL with metadata
- `zotero_ensure_yaml_citations_content`: Ensure Markdown YAML front matter contains citation fields; accepts document content and optional bibliography/style content; returns updated content and diagnostics

### Auto-Export Tools (Better BibTeX Integration)

- `zotero_ensure_auto_export`: Configure automatic bibliography export (generic with fallback)
- `zotero_bbt_ensure_auto_export_job`: Create/verify Better BibTeX auto-export jobs for hands-free sync
- `zotero_bbt_resolve_citekeys`: Resolve citekeys using Better BibTeX local API

### Citation & Authoring Tools

- `zotero_resolve_citekeys`: Resolve citekeys from multiple sources (Better BibTeX, CSL JSON content, or Zotero)
- `zotero_insert_citation`: Generate formatted citation strings (Pandoc or LaTeX style)
- `zotero_insert_citation_content`: Content-oriented variant (same formatting behavior)
- `zotero_suggest_citations`: Get ranked citation suggestions based on text context

### Validation & Build Tools

- `zotero_validate_references_content`: Validate Markdown citekeys against a CSL JSON bibliography string; returns unresolved, duplicates, missing fields, suggestions
- `zotero_build_exports_content`: Build DOCX/PDF from Markdown content using Pandoc. Each artifact is returned inline with `{format, filename, content(base64), size}` so clients can write files locally without touching the server filesystem.

#### Environment knobs (build/export)

- PANDOC_PATH: Absolute path to pandoc (else auto-detected with which).
- PDF_ENGINE: Preferred PDF engine name (`wkhtmltopdf`|`weasyprint`|`xelatex`). If set, the tool tries this first.
- PDF_ENGINE_PATH: Absolute path to the engine binary; when set, its directory is prepended to PATH for the pandoc call.
- OUTPUT_BASENAME (tool param): Override the output stem without relying on front matter or headings.
  
Exporter behavior notes:

- CSL JSON readiness: `export_bibliography_content` and `export_collection(format=csljson)` validate the JSON shape (array or `{items:[]}`) and ensure entries have an `id`. When upstream content is not CSL-ready, the server adds warnings and `codes` (e.g., `INVALID_CSL_EXPORT`, `CSL_IDS_FROM_ZOTERO_KEYS`).
- Text formats: `export_collection(format=ris|csv|...)` emits plain text (no JSON parsing). RIS counts are estimated by the number of `TY -` lines.
- Styled citations: `export_collection(format=citation, style=...)` concatenates strings from `data.citation`. If Zotero doesn’t include them, the tool returns `EMPTY_CITATION_EXPORT` in warnings/codes.

#### Health diagnostics

The `zotero_health` tool reports:

- YAML: pyyaml availability and selected parser
- Pandoc: detected path and version (or actionable error when missing)
- PDF: selected engine name and `pdfEngineVersion`
- Export status: whether base64 delivery is active and the detected output basename strategy

#### Client-build fallback (when pandoc is missing)

If pandoc isn’t found on the server, `zotero_build_exports_content` returns a JSON “clientBuild kit” that includes per-format commands and one-line strings. Filenames are derived from the document title or the explicit `outputBasename` so you can save outputs with meaningful names. PDF commands default to `--pdf-engine=wkhtmltopdf`, and any `extraArgs` are propagated.

#### CLI helper (local file writes)

`scripts/build_exports.py` wraps the content-first tool but saves artifacts locally on your machine:

- It decodes the base64 `content` payload the tool returns and writes files using the provided `filename`.
- Flags: `--out-dir` (defaults to `.`) and `--output-basename` (force a specific filename stem); `--pdf-engine` selects among `wkhtmltopdf`, `weasyprint`, or `xelatex`.

#### Example client decoding snippet

```python
import base64
from pathlib import Path

result = mcp.call_tool(
    "zotero_build_exports_content",
    {
        "documentContent": markdown_text,
        "formats": ["docx", "pdf"],
    },
)

for artifact in result["artifacts"]:
    data = base64.b64decode(artifact["content"])
    Path(artifact["filename"]).write_bytes(data)
```

#### Export troubleshooting

- **Pandoc missing**: Install pandoc or set `PANDOC_PATH` to the binary; the tool falls back to a client-build kit when it cannot find pandoc.
- **No PDF engine**: Install `wkhtmltopdf`, `weasyprint`, or `xelatex`, or set `PDF_ENGINE_PATH` to the binary. The startup logs and `zotero_health` output report which engine (if any) is detected.

### Convenience Tools

- `zotero_open_in_zotero`: Generate zotero:// URLs to open items in the Zotero application

### Write tools usage

- `zotero_create_item(itemType, fields, tags?, collections?, parentItem?, validateOnly?, writeToken?)`
  - Use `validateOnly=true` to check fields before writing.
  - `writeToken` enables idempotent create; repeated requests with the same token are rejected by Zotero.

- `zotero_update_item(itemKey, patch, strategy="patch"|"put", expectedVersion?)`
  - `patch` (default) changes only provided fields and preserves others.
  - `put` sends a full item: unspecified fields are removed — use with care.
  - If `expectedVersion` is omitted, the tool fetches the current item to obtain its version.

- `zotero_set_tags(itemKey, tags, mode="replace"|"append")`
  - `replace` overwrites tags with the provided list.
  - `append` keeps existing tags and adds the provided tags.

Common errors are mapped to helpful hints where possible (400 invalid fields, 403 insufficient scope, 409 locked, 412 version mismatch, 429 rate limited).

### Export and Bibliography Tools Usage

- `zotero_export_collection(collectionKey, format, style?, limit?, start?, fetchAll?)`
  - export formats: `ris`, `bibtex`, `csv`, `csljson`, `wikipedia`, and others supported by Zotero.
  - bibliography/citation: set `format` to `bib` or `citation` and optionally provide `style` (e.g., `apa`).
  - For export formats, the API requires a `limit` (max 100 per page). Use `fetchAll=true` to retrieve all items.

- `zotero_export_bibliography_content(format="csljson"|"bibtex"|"biblatex", scope="library"|"collection", collectionKey?, limit?, fetchAll?)`
  - Export bibliography as a string with SHA-256 for change detection
  - Returns `{content, count, sha256, warnings}`

- `zotero_ensure_style_content(style)`
  - Download CSL style by ID or URL and return the content with metadata
  - Returns `{content, sha256, etag}` when available

- `zotero_ensure_yaml_citations_content(documentContent, bibliographyContent?, cslContent?, linkCitations=true)`
  - Update Markdown YAML front-matter with citation settings
  - Preserves other YAML fields and normalizes newlines to `\n`
  - PyYAML-only (fail-fast if unavailable)
  - Returns `{updatedContent, changed, parser:"pyyaml", diagnostics:{keysUpdated, preservedKeys}}`

### YAML Front Matter for Citations

When working with Markdown documents that use Pandoc for citation processing, you need a YAML front matter block at the start of your document. The `zotero_ensure_yaml_citations_content` tool automatically adds or updates this block.

**Minimal YAML front matter example:**

```yaml
---
bibliography: references.json
csl: style.csl
link-citations: true
---
```

**How it works:**

- YAML parsing is PyYAML-only (fail-fast if missing). No fallbacks.
- It preserves existing YAML keys and updates only citation-related fields
- Works with documents that have BOM or Windows CRLF line endings
- Running it multiple times is idempotent (produces the same result)
- If you pass `bibliographyContent` or `cslContent`, the YAML values are set to `__INLINE__` to reflect content-managed inputs; build tools provide temp files under the hood when invoking Pandoc.

**Manual fallback:**
If you prefer to add the front matter manually, just paste the YAML block above at the very start of your Markdown file, adjusting the paths to match your bibliography and CSL style files.

## Troubleshooting

### YAML Parser Status

YAML parsing is PyYAML-only. If PyYAML is missing, citation tools fail fast with a clear error. Ensure the environment includes PyYAML (uv sync or pip install PyYAML).

### Docker Redeploy

To rebuild and redeploy the Docker container with the latest changes:

```bash
make docker-redeploy
```

This will:

1. Build a new `zotero-mcp:local` image
1. Stop and remove the old container
1. Start a new container with the updated image
1. Show recent logs to verify startup

For manual steps, see `.github/instructions/deploy.instructions.md`.

### Auto-Export Usage (Better BibTeX)

- `zotero_ensure_auto_export(path, format="csljson"|"bibtex"|"biblatex", scope="library"|"collection", collectionKey?, keepUpdated=true)`
  - Configure automatic bibliography sync (requires Better BibTeX plugin)
  - Falls back gracefully with guidance if Better BibTeX unavailable

- `zotero_bbt_ensure_auto_export_job(path, format, scope, collectionKey?, keepUpdated=true)`
  - Direct Better BibTeX auto-export job management
  - Returns created/updated/verified status

### Citation Authoring Usage

- `zotero_resolve_citekeys(citekeys, bibliographyContent?, tryZotero=true, preferBBT=true)`
  - Multi-source resolution: Better BibTeX → CSL JSON content → Zotero API
  - Returns `{resolved: {...}, unresolved: [...], duplicateKeys: [...]}`

- `zotero_insert_citation(citekeys, style="pandoc"|"latex", prefix?, suffix?, pages?)`
  - Generate formatted citations: `[@key1; @key2, p. 42]` or `\parencite[42]{key1,key2}`

- `zotero_suggest_citations(text, limit=5, qmode="titleCreatorYear"|"everything")`
  - Get ranked suggestions with match rationale (title/author/DOI overlap)

### Validation and Build Usage

- `zotero_validate_references_content(documentContent, bibliographyContent, requireDOIURL=true)`
  - Scan Markdown for citekeys and validate against CSL JSON content
  - Returns unresolved keys, duplicates, duplicate citations, missing fields `{id, missing}`, suggestions `{}` and unused entries

- `zotero_build_exports_content(documentContent, formats=["docx","pdf"], outputBasename?, bibliographyContent?, cslContent?, useCiteproc=true, pdfEngine="wkhtmltopdf"|"weasyprint"|"xelatex", extraArgs?)`
  - Build outputs with Pandoc and citation processing
  - Returns base64-encoded artifacts so the client can write files locally. Each artifact includes `format`, `filename`, `content`, and `size`.

## Examples (content-first tools)

These examples show minimal payloads and the shape of the JSON “result” block each tool emits. The human-readable text includes a fenced JSON block you can parse.

### Ensure YAML for citations

Tool: `zotero_ensure_yaml_citations_content`

Input

```json
{
  "documentContent": "# Title\n\nBody\n",
  "bibliographyContent": "[]",
  "cslContent": "<style/>",
  "linkCitations": true
}
```

Notes

- When `bibliographyContent`/`cslContent` are provided, the YAML values are set to `__INLINE__` to indicate content-managed inputs (no paths). This is intentional and idempotent.

Result (excerpt)

```json
{
  "result": {
    "updatedContent": "---\nbibliography: __INLINE__\ncsl: __INLINE__\nlink-citations: true\n---\n\n# Title\n\nBody\n",
    "changed": true,
    "parser": "pyyaml",
    "diagnostics": {"keysUpdated": ["bibliography","csl","link-citations"], "preservedKeys": []}
  }
}
```

### Validate references

Tool: `zotero_validate_references_content`

Input

```json
{
  "documentContent": "This cites @k1 and @missing.",
  "bibliographyContent": "[{\"id\":\"k1\",\"title\":\"T\",\"author\":[{\"family\":\"Doe\",\"given\":\"J\"}],\"issued\":{\"raw\":\"2020\"}}]",
  "requireDOIURL": false
}
```

Result fields

- `unresolvedKeys`: e.g., `["missing"]`
- `duplicateKeys`: usually `[]` for CSL JSON arrays
- `missingFields`: list of `{id, missing}`
- `duplicateCitations` and `unusedEntries`: provided for convenience

### Build exports (DOCX/PDF)

Tool: `zotero_build_exports_content`

Input

```json
{
  "documentContent": "# Title\n\nHello\n",
  "formats": ["docx","pdf"],
  "useCiteproc": true
}
```

Behavior

- Writes temp files internally for Pandoc, then returns base64-encoded artifacts with filenames derived from the document title or the explicit `outputBasename`.

Result (excerpt)

```json
{
  "result": {
    "artifacts": [
      {"format": "docx", "filename": "Title.docx", "content": "UEsDBBQABA...", "size": 1234},
      {"format": "pdf", "filename": "Title.pdf", "content": "JVBERi0xLjQKJ...", "size": 5678}
    ],
    "warnings": []
  }
}
```

### Export bibliography as content

Tool: `zotero_export_bibliography_content`

Input

```json
{
  "format": "csljson",
  "scope": "library",
  "fetchAll": false
}
```

Result (excerpt)

```json
{
  "result": {
    "content": "[ {\n  \"id\": \"key1\"\n} ]",
    "count": 1,
    "sha256": "...",
    "warnings": []
  }
}
```

### Ensure CSL style content

Tool: `zotero_ensure_style_content`

Input

```json
{ "style": "apa" }
```

Result (excerpt)

```json
{
  "result": {
    "content": "<?xml version=\"1.0\" encoding=\"utf-8\"?>...",
    "sha256": "...",
    "etag": "...optional..."
  }
}
```

### Convenience Tools Usage

- `zotero_get_collections(parentKey?)`
  - Retrieve collection tree with `{key, name, parentKey, path, itemCount}`

- `zotero_open_in_zotero(itemKey, libraryType?, libraryId?)`
  - Generate `zotero://select/library/items/<key>` URL

These can be discovered and accessed through any MCP client or through the [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector).

Each tool returns formatted text containing relevant information from your Zotero items, and AI assistants such as Claude can use them sequentially, searching for items then retrieving their metadata or text content.

## Installation

This server can either run against either a [local API offered by the Zotero desktop application](https://groups.google.com/g/zotero-dev/c/ElvHhIFAXrY/m/fA7SKKwsAgAJ)) or through the [Zotero Web API](https://www.zotero.org/support/dev/web_api/v3/start). The local API can be a bit more responsive, but requires that the Zotero app be running on the same computer with the API enabled. To enable the local API, do the following steps:

1. Open Zotero and open "Zotero Settings"
1. Under the "Advanced" tab, check the box that says "Allow other applications on this computer to communicate with Zotero".

> [!IMPORTANT]
> For access to the `/fulltext` endpoint on the local API which allows retrieving the full content of items in your library, you'll need to install a [Zotero Beta Build](https://www.zotero.org/support/beta_builds) (as of 2025-03-30). Once 7.1 is released this will no longer be the case. See <https://github.com/zotero/zotero/pull/5004> for more information. If you do not want to do this, use the Web API instead.

To use the Zotero Web API, you'll need to create an API key and find your Library ID (usually your User ID) in your Zotero account settings here: <https://www.zotero.org/settings/keys>

These are the available configuration options:

- `ZOTERO_LOCAL=true`: Use the local Zotero API (default: false, see note below)
- `ZOTERO_API_KEY`: Your Zotero API key (not required for the local API)
- `ZOTERO_LIBRARY_ID`: Your Zotero library ID (your user ID for user libraries, not required for the local API)
- `ZOTERO_LIBRARY_TYPE`: The type of library (user or group, default: user)
- `ZOTERO_REQUEST_TIMEOUT`: HTTP request timeout (seconds) for the Zotero client; defaults to 6.0
- `ZOTERO_CACHE_TTL`: In-memory cache TTL (seconds) for recent calls; defaults to 30
- `ZOTERO_CACHE_MAX`: Max in-memory cache entries before evicting oldest; defaults to 200
- `ZOTERO_RATE_MIN_INTERVAL`: Minimum seconds between repeated calls in the same bucket; defaults to 0.2
- `ZOTERO_DEFAULT_CSL`: Default CSL path or style id to use when none provided; defaults to `lncs.csl` (downloaded as Springer LNCS)
- `ZOTERO_DEFAULT_EXPORT_PATH`: Default auto-export path when not specified; defaults to `references.bib` at repo root
- `ZOTERO_DEFAULT_EXPORT_FORMAT`: Default auto-export format when not specified; defaults to `bibtex`
- `ZOTERO_SUGGEST_LOCAL_FIRST`: If true, suggestion tool ranks from recently cached search results first; defaults to `true`
- `LOG_LEVEL`: Python logging level for server (DEBUG, INFO, WARNING, ERROR); defaults to `INFO`

> [!NOTE]
> Write operations require the Web API. If `ZOTERO_LOCAL=true` is set, write tools will return a helpful error and no changes will be made.

### [`uvx`](https://docs.astral.sh/uv/getting-started/installation/) with Local Zotero API

To use this with Claude Desktop and a direct python install with [`uvx`](https://docs.astral.sh/uv/getting-started/installation/), add the following to the `mcpServers` configuration:

```json
{
  "mcpServers": {
    "zotero": {
      "command": "uvx",
      "args": ["--upgrade", "zotero-mcp"],
      "env": {
        "ZOTERO_LOCAL": "true",
        "ZOTERO_API_KEY": "",
        "ZOTERO_LIBRARY_ID": ""
      }
    }
  }
}
```

The `--upgrade` flag is optional and will pull the latest version when new ones are available. If you don't have `uvx` installed you can use `pipx run` instead, or clone this repository locally and use the instructions in [Development](#development) below.

### Docker with Zotero Web API

If you want to run this MCP server in a Docker container, you can use the following configuration, inserting your API key and library ID:

```json
{
  "mcpServers": {
    "zotero": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e", "ZOTERO_API_KEY=PLACEHOLDER",
        "-e", "ZOTERO_LIBRARY_ID=PLACEHOLDER",
        "ghcr.io/kujenga/zotero-mcp:main"
      ],
    }
  }
}
```

To update to a newer version, run `docker pull ghcr.io/kujenga/zotero-mcp:main`. It is also possible to use the docker-based installation to talk to the local Zotero API, but you'll need to modify the above command to ensure that there is network connectivity to the Zotero application's local API interface.

## Development

Information on making changes and contributing to the project.

1. Clone this repository
1. Install dependencies with [uv](https://docs.astral.sh/uv/) by running: `uv sync` (includes PyYAML; if using a system Python without uv, ensure `pip install PyYAML` is installed on the host)
1. Create a `.env` (or `.env.local`) file in the project root with the environment variables above. See `.env.example` for a quick start.

Start the [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) for local development:

```bash
npx @modelcontextprotocol/inspector uv run zotero-mcp
```

To test the local repository against Claude Desktop, run `echo $PWD/.venv/bin/zotero-mcp` in your shell within this directory, then set the following within your Claude Desktop configuration

```json
{
  "mcpServers": {
    "zotero": {
      "command": "/path/to/zotero-mcp/.venv/bin/zotero-mcp"
      "env": {
        // Whatever configuration is desired.
      }
    }
  }
}
```

### Running Tests

To run the test suite:

```bash
uv run pytest
```

### Docker Development

Build the container image with this command:

```sh
docker build . -t zotero-mcp:local
```

To test the container with the MCP inspector, run the following command:

```sh
npx @modelcontextprotocol/inspector \
    -e ZOTERO_API_KEY=$ZOTERO_API_KEY \
    -e ZOTERO_LIBRARY_ID=$ZOTERO_LIBRARY_ID \
    docker run --rm -i \
        --env ZOTERO_API_KEY \
        --env ZOTERO_LIBRARY_ID \
        zotero-mcp:local
```

### Run as an HTTP SSE server (Docker)

If you want to expose this server on your LAN as an SSE endpoint consumable by MCP clients, use the helper script:

1. Create a `.env.local` in the repo root with your Web API credentials:

  ```env
  ZOTERO_API_KEY=your_api_key
  ZOTERO_LIBRARY_ID=your_library_id
  # Optional (defaults to "user")
  ZOTERO_LIBRARY_TYPE=user
  ```

1. (Optional) Set bind host/port. Defaults are `0.0.0.0:9180`.

  ```bash
  export MCP_HOST=0.0.0.0
  export MCP_PORT=9180
  ```

1. Start the containerized SSE server:

  ```bash
  ./scripts/run-docker.sh
  ```

The server will listen at `http://<your-host>:<MCP_PORT>/sse` (e.g., `http://192.168.1.114:9180/sse`). Point your MCP client to that URL.

## Relevant Documentation

- <https://modelcontextprotocol.io/tutorials/building-mcp-with-llms>
- <https://github.com/modelcontextprotocol/python-sdk>
- <https://pyzotero.readthedocs.io/en/latest/>
- <https://www.zotero.org/support/dev/web_api/v3/start>
- <https://modelcontextprotocol.io/llms-full.txt> can be utilized by LLMs
