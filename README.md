# Model Context Protocol server for Zotero

[![GitHub branch status](https://img.shields.io/github/check-runs/kujenga/zotero-mcp/main)](https://github.com/kujenga/zotero-mcp/actions)
[![PyPI - Version](https://img.shields.io/pypi/v/zotero-mcp)](https://pypi.org/project/zotero-mcp/)

This project is a python server that implements the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) for [Zotero](https://www.zotero.org/), giving you access to your Zotero library within AI assistants. It is intended to implement a small but maximally useful set of interactions with Zotero for use with [MCP clients](https://modelcontextprotocol.io/clients).

<a href="https://glama.ai/mcp/servers/jknz38ntu4">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/jknz38ntu4/badge" alt="Zotero Server MCP server" />
</a>

## Features

This MCP server provides the following tools:

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

- `zotero_export_collection`: Export items in a collection to formats like RIS, BibTeX, CSL JSON, CSV, or styled bibliography/citations
- `zotero_export_bibliography`: Export library or collection bibliography to a file with SHA-256 hash verification
- `zotero_ensure_style`: Download and cache CSL style files for citation formatting
- `zotero_ensure_yaml_citations`: Update Markdown YAML front-matter with bibliography and CSL settings

### Auto-Export Tools (Better BibTeX Integration)

- `zotero_ensure_auto_export`: Configure automatic bibliography export (generic with fallback)
- `zotero_bbt_ensure_auto_export_job`: Create/verify Better BibTeX auto-export jobs for hands-free sync
- `zotero_bbt_resolve_citekeys`: Resolve citekeys using Better BibTeX local API

### Citation & Authoring Tools

- `zotero_resolve_citekeys`: Resolve citekeys from multiple sources (Better BibTeX, CSL JSON, or Zotero)
- `zotero_insert_citation`: Generate formatted citation strings (Pandoc or LaTeX style)
- `zotero_suggest_citations`: Get ranked citation suggestions based on text context

### Validation & Build Tools

- `zotero_validate_references`: Validate Markdown citekeys against bibliography, report issues
- `zotero_build_exports`: Build DOCX/HTML/PDF outputs using Pandoc with citation processing

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

- `zotero_export_bibliography(targetPath, format="csljson"|"bibtex"|"biblatex", scope="library"|"collection", collectionKey?)`
  - Export to a file on disk with SHA-256 hash for change detection
  - Returns `{path, count, sha256, warnings}`

- `zotero_ensure_style(style, targetPath)`
  - Download CSL style by ID or URL to specified path
  - Idempotent: skips download if file exists

- `zotero_ensure_yaml_citations(documentPath, bibliography?, csl?, linkCitations?)`
  - Update Markdown YAML front-matter with citation settings
  - Preserves other YAML fields
  - Works with PyYAML, ruamel.yaml, or a text-based fallback
  - Returns which parser was used: `(parser=pyyaml|ruamel|text)`

### YAML Front Matter for Citations

When working with Markdown documents that use Pandoc for citation processing, you need a YAML front matter block at the start of your document. The `zotero_ensure_yaml_citations` tool automatically adds or updates this block.

**Minimal YAML front matter example:**

```yaml
---
bibliography: references.json
csl: style.csl
link-citations: true
---
```

**How it works:**

- The tool tries to use PyYAML first, then ruamel.yaml, then falls back to text-based parsing
- It preserves existing YAML keys and updates only citation-related fields
- Works with documents that have BOM or Windows CRLF line endings
- Running it multiple times is idempotent (produces the same result)

**Manual fallback:**
If you prefer to add the front matter manually, just paste the YAML block above at the very start of your Markdown file, adjusting the paths to match your bibliography and CSL style files.

## Troubleshooting

### YAML Parser Status

You can check which YAML parser will be used by calling the `zotero_health` tool. It will report:

- `pyyaml: ok|missing` - PyYAML availability
- `ruamel: ok|missing` - ruamel.yaml availability  
- `yamlParser: pyyaml|ruamel|text` - Which parser `ensure_yaml_citations` will use

**If you see `yamlParser: text`:**
The tool will still work using a text-based fallback, but for best results:
- For Docker deployments: rebuild and redeploy using `make docker-redeploy` (see deployment instructions below)
- For local installations: ensure PyYAML is installed (`pip install PyYAML` or `uv sync`)

### Docker Redeploy

To rebuild and redeploy the Docker container with the latest changes:

```bash
make docker-redeploy
```

This will:
1. Build a new `zotero-mcp:local` image
2. Stop and remove the old container
3. Start a new container with the updated image
4. Show recent logs to verify startup

For manual steps, see `.github/instructions/deploy.instructions.md`.

### Auto-Export Usage (Better BibTeX)

- `zotero_ensure_auto_export(path, format="csljson"|"bibtex"|"biblatex", scope="library"|"collection", collectionKey?, keepUpdated=true)`
  - Configure automatic bibliography sync (requires Better BibTeX plugin)
  - Falls back gracefully with guidance if Better BibTeX unavailable

- `zotero_bbt_ensure_auto_export_job(path, format, scope, collectionKey?, keepUpdated=true)`
  - Direct Better BibTeX auto-export job management
  - Returns created/updated/verified status

### Citation Authoring Usage

- `zotero_resolve_citekeys(citekeys, bibliographyPath?, tryZotero=true, preferBBT=true)`
  - Multi-source resolution: Better BibTeX → file → Zotero API
  - Returns `{resolved: {...}, unresolved: [...], duplicateKeys: [...]}`

- `zotero_insert_citation(citekeys, style="pandoc"|"latex", prefix?, suffix?, pages?)`
  - Generate formatted citations: `[@key1; @key2, p. 42]` or `\parencite[42]{key1,key2}`

- `zotero_suggest_citations(text, limit=5, qmode="titleCreatorYear"|"everything")`
  - Get ranked suggestions with match rationale (title/author/DOI overlap)

### Validation and Build Usage

- `zotero_validate_references(documentPath, bibliographyPath, requireDOIURL=true)`
  - Scan Markdown for citekeys and validate against bibliography
  - Reports: unresolved keys, duplicates, missing fields, unused entries

- `zotero_build_exports(documentPath, formats=["docx","html","pdf"], bibliographyPath?, cslPath?, useCiteproc=true, pdfEngine="edge"|"xelatex", extraArgs?)`
  - Build outputs with Pandoc and citation processing
  - Returns output paths and warnings

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
> For access to the `/fulltext` endpoint on the local API which allows retrieving the full content of items in your library, you'll need to install a [Zotero Beta Build](https://www.zotero.org/support/beta_builds) (as of 2025-03-30). Once 7.1 is released this will no longer be the case. See https://github.com/zotero/zotero/pull/5004 for more information. If you do not want to do this, use the Web API instead.

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

2. (Optional) Set bind host/port. Defaults are `0.0.0.0:9180`.

  ```bash
  export MCP_HOST=0.0.0.0
  export MCP_PORT=9180
  ```

3. Start the containerized SSE server:

  ```bash
  ./scripts/run-docker.sh
  ```

The server will listen at `http://<your-host>:<MCP_PORT>/sse` (e.g., `http://192.168.1.114:9180/sse`). Point your MCP client to that URL.

## Relevant Documentation

- https://modelcontextprotocol.io/tutorials/building-mcp-with-llms
- https://github.com/modelcontextprotocol/python-sdk
- https://pyzotero.readthedocs.io/en/latest/
- https://www.zotero.org/support/dev/web_api/v3/start
- https://modelcontextprotocol.io/llms-full.txt can be utilized by LLMs
