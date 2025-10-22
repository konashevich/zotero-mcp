FROM python:3.13-slim-bookworm

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

# Install system dependencies needed for builds (pandoc, wkhtmltopdf)
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
	   pandoc \
	   wkhtmltopdf \
	   fonts-dejavu \
	&& rm -rf /var/lib/apt/lists/*

# Install application
ADD README.md LICENSE pyproject.toml uv.lock src scripts /app/
WORKDIR /app
ENV UV_FROZEN=true
RUN uv sync

# Check basic functionality
RUN uv run zotero-mcp --help
RUN pandoc --version || true
RUN wkhtmltopdf --version || true
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

# Create directory for file downloads with proper permissions
RUN mkdir -p /tmp/mcp-files && chmod 1777 /tmp/mcp-files

LABEL org.opencontainers.image.title="zotero-mcp"
LABEL org.opencontainers.image.description="Model Context Protocol Server for Zotero"
LABEL org.opencontainers.image.url="https://github.com/zotero/zotero-mcp"
LABEL org.opencontainers.image.source="https://github.com/zotero/zotero-mcp"
LABEL org.opencontainers.image.license="MIT"

# Expose default ports: 9180 is the host default, container uses 8000 for SSE
EXPOSE 8000 9180

# Command to run the server
ENTRYPOINT ["uv", "run", "--quiet", "zotero-mcp"]
