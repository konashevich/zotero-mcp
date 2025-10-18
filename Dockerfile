FROM python:3.13-slim-bookworm

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

# Install application
ADD README.md LICENSE pyproject.toml uv.lock src scripts /app/
WORKDIR /app
ENV UV_FROZEN=true
RUN uv sync

# Check basic functionality
RUN uv run zotero-mcp --help
RUN uv run python - <<'PY'
import sys
try:
	import yaml  # noqa: F401
	print('yaml import ok')
except Exception:
	try:
		import ruamel.yaml  # noqa: F401
		print('ruamel.yaml import ok')
	except Exception as e:
		print('Warning: no YAML lib found in build env:', e, file=sys.stderr)
PY

LABEL org.opencontainers.image.title="zotero-mcp"
LABEL org.opencontainers.image.description="Model Context Protocol Server for Zotero"
LABEL org.opencontainers.image.url="https://github.com/zotero/zotero-mcp"
LABEL org.opencontainers.image.source="https://github.com/zotero/zotero-mcp"
LABEL org.opencontainers.image.license="MIT"

# Expose default ports: 9180 is the host default, container uses 8000 for SSE
EXPOSE 8000 9180

# Command to run the server
ENTRYPOINT ["uv", "run", "--quiet", "zotero-mcp"]
