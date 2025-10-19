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
	
6. Check startup health and YAML parser availability (PyYAML-only)
	```bash
	# Recent logs (look for startup health JSON with pyyaml and yamlParser fields)
	docker logs --tail 50 zotero-mcp-sse
	```
	
	The health output should include:
	- `pyyaml: ok` - PyYAML is available
	- `yamlParser: pyyaml` - YAML tools use PyYAML exclusively (fail-fast otherwise)
	
	Optional SSE probe:
	```bash
	# Quick SSE endpoint check
	timeout 3 curl -N http://localhost:9180/sse | head -5
	```

Notes
- The Dockerfile performs a lightweight YAML library check during build; ensure PyYAML is installed via `uv sync` in the image.
- Use `LOG_LEVEL=DEBUG` in `.env.local` if you want verbose startup/timing logs.
- After redeployment, the `zotero_health` MCP tool will report diagnostics including YAML parser selection (always `pyyaml`).

## Content-based tools (no cross-OS path mapping)

Public tools accept and return content (strings) to avoid cross-OS filesystem issues. Do not pass client file paths to tools. When external binaries like Pandoc require files, the server writes temporary files internally and returns either server-native paths or inline data URIs when `EXPORTS_EMBED_DATA_URI=true`.

Implications:
- No Windows-to-POSIX path mapping is documented or supported in tool inputs.
- If you bind-mount host directories for operational reasons, treat any paths as server-native only and outside the scope of MCP tool inputs.