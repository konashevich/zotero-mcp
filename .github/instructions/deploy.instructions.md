---
applyTo: '**'
---
Provide project context and coding guidelines that AI should follow when generating code, answering questions, or reviewing changes.

## Local Docker redeploy (this device)

When asked to rebuild the Docker image and replace the running Zotero MCP server locally, you can use the automated command or follow the manual steps below.

### Quick Method (Recommended)

```bash
make docker-redeploy
```

This automates all steps below: builds the image, stops the old container, starts the new one, and shows verification output.

### Manual Steps

If you need to troubleshoot or prefer manual control, follow these steps exactly:

1. Ensure environment file exists
	- Create or update a `.env.local` in the repo root with:
	  - `ZOTERO_API_KEY`
	  - `ZOTERO_LIBRARY_ID`
	  - `ZOTERO_LIBRARY_TYPE` (optional, defaults to `user`)

2. Build the image from the current workspace
	```bash
	docker build -t zotero-mcp:local .
	```

3. Stop/remove any container bound to host port 9180
	- By script name (default):
	  ```bash
	  docker rm -f zotero-mcp-sse
	  ```
	- Or by detecting whichever container holds 9180:
	  ```bash
	  docker rm -f $(docker ps -a --format '{{.ID}} {{.Ports}}' | awk '/0.0.0.0:9180->8000/ {print $1}')
	  ```

4. Launch the updated container (detached)
	```bash
	bash scripts/run-docker.sh -d
	```
	- This starts the container as `zotero-mcp-sse` and maps host 9180 to container 8000.

5. Verify it's running the new image
	```bash
	docker ps --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Ports}}' | grep 9180
	```
	
6. Check startup health and YAML parser availability
	```bash
	# Recent logs (look for startup health JSON with pyyaml/ruamel/yamlParser fields)
	docker logs --tail 50 zotero-mcp-sse
	```
	
	The health output should include:
	- `pyyaml: ok` - PyYAML is available
	- `ruamel: ok` - ruamel.yaml is available  
	- `yamlParser: pyyaml` - Indicates which parser ensure_yaml_citations will use
	
	Optional SSE probe:
	```bash
	# Quick SSE endpoint check
	timeout 3 curl -N http://localhost:9180/sse | head -5
	```

Notes
- The Dockerfile performs a lightweight YAML library check during build; failures should be addressed by ensuring dependencies are installed via `uv sync` in the image.
- Use `LOG_LEVEL=DEBUG` in `.env.local` if you want verbose startup/timing logs.
- After redeployment, the `zotero_health` MCP tool will report enhanced diagnostics including YAML parser availability and selection.

## Windows paths from clients (important)

When the server runs in Linux/Docker but clients pass absolute Windows paths (e.g., `C:\\Users\\...`), the server now maps those paths on POSIX if a corresponding host drive is mounted. Configure one of the following to enable mapping:

- ZOTERO_HOST_DRIVES_ROOT: Root under which host Windows drives are mounted. Common values:
	- Docker Desktop: `/host_mnt`
	- WSL: `/mnt`
	Example mapping: `C:\\Users\\alice\\Docs\\paper.md` → `/host_mnt/c/Users/alice/Docs/paper.md`

- Optional: Mount a specific host documents directory and set the base for relative paths:
	- HOST_DOCS_DIR: Absolute path on host to mount (e.g., `C:\\Users\\alice\\Documents\\Manuscripts`)
	- CONTAINER_DOCS_DIR: Where to mount inside container (default `/workspace`)
	- ZOTERO_DOCS_BASE: Base dir inside container to resolve relative paths

The `scripts/run-docker.sh` supports these variables. Example `.env.local` additions on Windows with Docker Desktop:

```
# Existing required values
ZOTERO_API_KEY=...
ZOTERO_LIBRARY_ID=...

# Path mapping config
HOST_DRIVES_ROOT=/host_mnt
HOST_DOCS_DIR=C:\\Users\\alice\\Documents\\Manuscripts
CONTAINER_DOCS_DIR=/workspace
# Optional: if you only use relatives, set base without a mount
# ZOTERO_DOCS_BASE=/workspace
```

Then redeploy:

```bash
make docker-redeploy
```

After redeploy, absolute Windows paths and relative paths under `ZOTERO_DOCS_BASE` will resolve correctly. If mapping fails, the tools will include a hint to set `ZOTERO_HOST_DRIVES_ROOT`.