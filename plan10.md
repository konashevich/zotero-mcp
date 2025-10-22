# Plan 10 — Direct file download bypass (no context window bloat)

## Problem Statement

Current architecture forces generated files (PDF, DOCX) through the AI agent's context window as base64-encoded strings. A 28KB PDF becomes ~38KB of base64 text in the tool response, consuming tokens unnecessarily. For large documents, this is prohibitive. The AI agent should **orchestrate** file transfer but not handle file content.

## Goal

Implement a direct HTTP file download mechanism where:
1. MCP server generates files (Pandoc → PDF/DOCX)
2. Server stores files temporarily and returns a download token + metadata
3. AI agent receives only token/filename/size (no file content)
4. AI agent uses a simple HTTP request to download file directly to local workspace
5. File bytes bypass AI context window entirely

## Architecture Overview

```
┌─────────────┐                    ┌─────────────┐
│  AI Agent   │                    │ MCP Server  │
│  (VS Code)  │                    │ (port 9180) │
└──────┬──────┘                    └──────┬──────┘
       │                                  │
       │ 1. Call build_exports_content    │
       ├─────────────────────────────────>│
       │                                  │
       │                           2. Generate PDF/DOCX
       │                           3. Save to /tmp/mcp-files/{token}/
       │                           4. Create token mapping
       │                                  │
       │ 5. Return {token, filename, url} │
       │<─────────────────────────────────┤
       │    (NO file content)             │
       │                                  │
       │ 6. curl http://localhost:9180/files/{token}
       ├─────────────────────────────────>│
       │                                  │
       │ 7. File bytes (direct transfer)  │
       │<─────────────────────────────────┤
       │                                  │
       │ 8. Save to local workspace       │
       │    (file never in AI context)    │
       └──────────────────────────────────┘
```

## Implementation Plan

### 1. Add HTTP file serving endpoint to MCP server

**File:** `src/zotero_mcp/cli.py`

- FastMCP uses Starlette under the hood; we need to access the underlying ASGI app
- Add a new HTTP route `GET /files/{token}` that:
  - Validates the token exists in the file registry
  - Checks file hasn't expired (TTL mechanism)
  - Returns file as streaming response with proper Content-Type and Content-Disposition headers
  - Optionally deletes file after download (one-time use) or marks as downloaded
- Add a cleanup background task that removes expired files every N minutes

**Key points:**
- Use `mcp._server.app` or similar to access Starlette app (check FastMCP internals)
- If FastMCP doesn't expose app, may need to wrap/extend the server setup
- Token format: secure random string (e.g., `secrets.token_urlsafe(32)`)
- File registry: in-memory dict `{token: FileInfo(path, created_at, filename, size)}`

### 2. Create file registry and cleanup mechanism

**File:** `src/zotero_mcp/__init__.py` (or new `src/zotero_mcp/file_registry.py`)

```python
@dataclass
class FileInfo:
    path: Path
    filename: str
    size: int
    format: str
    created_at: float
    downloaded: bool = False

FILE_REGISTRY: dict[str, FileInfo] = {}
FILE_TTL_SECONDS = int(os.getenv("MCP_FILE_TTL", "3600"))  # 1 hour default

def register_file(file_path: Path, filename: str, size: int, format: str) -> str:
    """Register a file for download and return a token."""
    import secrets
    token = secrets.token_urlsafe(32)
    FILE_REGISTRY[token] = FileInfo(
        path=file_path,
        filename=filename,
        size=size,
        format=format,
        created_at=time.time(),
    )
    return token

def get_file(token: str) -> FileInfo | None:
    """Retrieve file info by token if not expired."""
    info = FILE_REGISTRY.get(token)
    if not info:
        return None
    if time.time() - info.created_at > FILE_TTL_SECONDS:
        cleanup_file(token)
        return None
    return info

def cleanup_file(token: str) -> None:
    """Remove file from registry and filesystem."""
    if token in FILE_REGISTRY:
        info = FILE_REGISTRY.pop(token)
        try:
            info.path.unlink(missing_ok=True)
            # Try to remove parent directory if empty
            info.path.parent.rmdir()
        except Exception:
            pass
```

### 3. Modify `build_exports_content` to return tokens instead of base64

**File:** `src/zotero_mcp/__init__.py`

**Current behavior:**
```python
# Encodes file to base64
b64 = _base64.b64encode(data).decode("ascii")
artifact = {
    "format": fmt,
    "filename": f"{basename}.{fmt}",
    "content": b64,  # ← PROBLEM: large string in context
    "size": len(data),
}
```

**New behavior:**
```python
# Move file to persistent temp location
import secrets
token = secrets.token_urlsafe(32)
token_dir = Path("/tmp/mcp-files") / token
token_dir.mkdir(parents=True, exist_ok=True)
final_path = token_dir / f"{basename}.{fmt}"
shutil.move(str(out_file), str(final_path))

# Register file
register_file(final_path, f"{basename}.{fmt}", len(data), fmt)

# Determine download URL
host = os.getenv("MCP_HOST", "localhost")
port = os.getenv("MCP_PORT", "9180")
download_url = f"http://{host}:{port}/files/{token}"

artifact = {
    "format": fmt,
    "filename": f"{basename}.{fmt}",
    "token": token,  # ← NEW: token for download
    "downloadUrl": download_url,  # ← NEW: direct URL
    "size": len(data),
    # NO "content" field with base64
}
```

**Breaking change:**
- Remove `content` field entirely (NO backward compatibility per project rules)
- Tools consuming this must be updated to use `token` + `downloadUrl`

### 4. Add Starlette route handler

**File:** `src/zotero_mcp/cli.py`

```python
from starlette.responses import StreamingResponse, Response
from starlette.routing import Route

async def download_file(request):
    token = request.path_params['token']
    
    file_info = get_file(token)
    if not file_info:
        return Response("File not found or expired", status_code=404)
    
    if not file_info.path.exists():
        cleanup_file(token)
        return Response("File no longer available", status_code=410)
    
    # Mark as downloaded (optional: delete after first download)
    file_info.downloaded = True
    
    # Determine content type
    content_type = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(file_info.format, "application/octet-stream")
    
    # Stream file
    def iterfile():
        with open(file_info.path, "rb") as f:
            yield from f
    
    headers = {
        "Content-Disposition": f'attachment; filename="{file_info.filename}"',
    }
    
    return StreamingResponse(
        iterfile(),
        media_type=content_type,
        headers=headers,
    )

# Add route to FastMCP's underlying Starlette app
def setup_file_routes(app):
    """Add file download routes to the ASGI app."""
    # Need to access mcp's internal Starlette app
    # This depends on FastMCP internals - may need investigation
    app.add_route("/files/{token}", download_file, methods=["GET"])
```

**Integration point:**
- After `mcp = FastMCP("Zotero")` in `__init__.py`, need to access underlying app
- Check FastMCP source to determine how to access/modify routes
- Alternative: Create custom ASGI middleware wrapper

### 5. Add background cleanup task

**File:** `src/zotero_mcp/cli.py`

```python
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # Start cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    yield
    # Cancel cleanup on shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

async def periodic_cleanup():
    """Remove expired files every 5 minutes."""
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            cleanup_expired_files()
        except Exception as e:
            logger.error(f"Cleanup task error: {e}")

def cleanup_expired_files():
    """Remove all files past TTL."""
    now = time.time()
    expired = [
        token for token, info in FILE_REGISTRY.items()
        if now - info.created_at > FILE_TTL_SECONDS
    ]
    for token in expired:
        cleanup_file(token)
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired files")
```

### 6. Update tool response format

**Old response:**
```json
{
  "artifacts": [
    {
      "format": "pdf",
      "filename": "output.pdf",
      "content": "JVBERi0xLjQK...38KB of base64...",
      "size": 28838
    }
  ]
}
```

**New response:**
```json
{
  "artifacts": [
    {
      "format": "pdf",
      "filename": "output.pdf",
      "token": "xK9mP2vL8qR...",
      "downloadUrl": "http://localhost:9180/files/xK9mP2vL8qR...",
      "size": 28838
    }
  ],
  "instructions": "Download files using curl or wget: curl -O http://localhost:9180/files/{token}"
}
```

### 7. Update documentation and AI agent guidance

**File:** `README.md`

Add section:
```markdown
## File Downloads (PDF/DOCX exports)

Export tools return download tokens instead of file content to avoid context window bloat.

### For AI Agents:
After calling `build_exports_content`, you'll receive:
- `token`: unique download identifier
- `downloadUrl`: direct HTTP endpoint
- `filename`: suggested filename
- `size`: file size in bytes

Download the file directly:
```bash
curl -o output.pdf http://localhost:9180/files/{token}
```

Files expire after 1 hour (configurable via MCP_FILE_TTL environment variable).

### For Human Users:
If running outside Docker, files are accessible at http://localhost:9180/files/{token}
```

**File:** `.github/copilot-instructions.md`

Add to patterns section:
```markdown
- Export tools (build_exports_content) return download tokens, not file content
- AI agents must download files via HTTP GET to /files/{token}
- Files stored in /tmp/mcp-files/{token}/ with automatic cleanup
- NO base64 content in tool responses (removed for efficiency)
```

### 8. Environment variables

Add to `.env.local` documentation:

```bash
# File download settings
MCP_FILE_TTL=3600          # File expiration in seconds (default: 1 hour)
MCP_HOST=localhost         # Host for download URLs
MCP_PORT=9180              # Port for download URLs (matches Docker mapping)
MCP_FILES_DIR=/tmp/mcp-files  # Directory for temporary files
```

### 9. Docker considerations

**File:** `Dockerfile`

Ensure temp directory permissions:
```dockerfile
RUN mkdir -p /tmp/mcp-files && chmod 1777 /tmp/mcp-files
```

**File:** `scripts/run-docker.sh`

No bind mounts needed (files served over HTTP), but ensure port 9180 mapping exists:
```bash
-p 9180:8000
```

### 10. Testing strategy

**New test file:** `tests/test_file_downloads.py`

```python
def test_build_exports_returns_token_not_content(mock_pandoc):
    """Verify exports return download tokens instead of base64."""
    result = build_exports_content(
        documentContent="# Test",
        formats=["pdf"],
    )
    
    artifacts = parse_response_json(result)["artifacts"]
    assert len(artifacts) == 1
    
    artifact = artifacts[0]
    assert "token" in artifact
    assert "downloadUrl" in artifact
    assert "content" not in artifact  # NO base64
    assert artifact["size"] > 0

def test_file_download_endpoint(client, mock_file):
    """Test HTTP file download."""
    token = register_test_file(mock_file)
    
    response = client.get(f"/files/{token}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert len(response.content) == mock_file.stat().st_size

def test_expired_file_returns_404():
    """Verify expired files are cleaned up."""
    token = register_test_file(mock_file)
    
    # Simulate expiration
    FILE_REGISTRY[token].created_at -= FILE_TTL_SECONDS + 1
    
    response = client.get(f"/files/{token}")
    assert response.status_code == 404
    assert token not in FILE_REGISTRY
```

**Update existing tests:**
- Modify tests expecting `content` field to expect `token` + `downloadUrl`
- Add integration tests that actually download files via HTTP

### 11. Fallback mechanism (optional, but consider for gradual rollout)

**SKIP THIS** - Project rules specify NO backward compatibility. Remove old base64 behavior entirely.

### 12. Migration checklist

- [ ] Add file registry module with token management
- [ ] Modify `build_exports_content` to register files and return tokens
- [ ] Add Starlette route handler for `/files/{token}`
- [ ] Implement periodic cleanup task
- [ ] Update response format (remove `content`, add `token`/`downloadUrl`)
- [ ] Add environment variables for configuration
- [ ] Update Docker setup for temp file storage
- [ ] Write comprehensive tests for download mechanism
- [ ] Update documentation (README, copilot-instructions)
- [ ] Test end-to-end: MCP tool → token → curl download → local file
- [ ] Verify no base64 content appears in AI agent context
- [ ] Measure token savings (before/after comparison)

## Success Criteria

1. **No file content in AI context**: Tool responses contain only metadata (token, URL, size)
2. **Direct HTTP download works**: `curl http://localhost:9180/files/{token} -o file.pdf` succeeds
3. **Automatic cleanup**: Files expire after TTL, registry and filesystem cleaned
4. **Tests pass**: All existing tests updated, new download tests green
5. **Documentation clear**: AI agents understand download workflow
6. **Token efficiency**: 28KB PDF → ~100 bytes of metadata (vs. 38KB base64)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| FastMCP doesn't expose Starlette app | Investigate FastMCP source; may need to fork or use lower-level MCP SDK |
| File security (unauthenticated downloads) | Tokens are cryptographically random (32 bytes); short TTL limits exposure |
| Disk space exhaustion | Periodic cleanup + TTL; optionally limit total files or size |
| Cross-container networking issues | Use localhost:9180 mapping; ensure AI agent can reach server |
| Breaking change for existing clients | Acceptable per project rules (NO backward compatibility) |

## Follow-up Tasks

After this plan:
1. Consider adding authentication tokens for downloads (if multi-user environment)
2. Add download progress/streaming for very large files
3. Support batch downloads (multiple files in ZIP)
4. Add metrics/logging for download analytics
5. Consider webhook/callback mechanism for completed exports

## Notes

- This approach aligns with content-based tool philosophy: server manages files, clients orchestrate
- Tokens are single-use or time-limited; no persistent file storage
- HTTP endpoint is simple REST, no special client libraries needed
- Works in Docker, local, and any environment where AI agent can reach server via HTTP
- File transfer bypasses AI context window completely → massive token savings for large documents
