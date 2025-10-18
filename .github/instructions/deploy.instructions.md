---
applyTo: '**'
---
Provide project context and coding guidelines that AI should follow when generating code, answering questions, or reviewing changes.

## Local Docker redeploy (this device)

When asked to rebuild the Docker image and replace the running Zotero MCP server locally, follow these steps exactly:

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

5. Verify it’s running the new image
	```bash
	docker ps --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Ports}}' | grep 9180
	```
	Optional:
	```bash
	# Recent logs (look for a startup health line)
	docker logs --tail 50 zotero-mcp-sse

	# Quick SSE probe
	timeout 3 curl -N http://localhost:9180/sse | head -5
	```

Notes
- The Dockerfile performs a lightweight YAML library check during build; failures should be addressed by ensuring dependencies are installed via `uv sync` in the image.
- Use `LOG_LEVEL=DEBUG` in `.env.local` if you want verbose startup/timing logs.