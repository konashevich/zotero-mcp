# Implementation Summary: Direct File Downloads (Plan 10)

## Overview

Successfully implemented a token-based file download system that bypasses the AI agent's context window entirely. Generated files (PDF/DOCX) are now served via HTTP endpoints instead of being returned as base64-encoded strings.

## Key Changes

### 1. File Registry System (`src/zotero_mcp/__init__.py`)

Added complete file management infrastructure:

- **FileInfo dataclass**: Tracks file metadata (path, filename, size, format, created_at, downloaded)
- **FILE_REGISTRY**: Global dict mapping tokens to FileInfo objects
- **Helper functions**:
  - `register_file()`: Creates entry in registry (now simplified - just updates registry)
  - `get_file()`: Retrieves file info with TTL check
  - `cleanup_file()`: Removes file from filesystem and registry
  - `cleanup_expired_files()`: Batch cleanup of expired files

Configuration via environment variables:
- `MCP_FILE_TTL`: Expiration time in seconds (default: 3600 = 1 hour)
- `MCP_FILES_DIR`: Storage directory (default: /tmp/mcp-files)
- `MCP_HOST`: Download URL host (default: localhost)
- `MCP_PORT`: Download URL port (default: 9180)

### 2. Modified Export Tool

Updated `build_exports_content` to use token-based downloads:

**Before:**
```python
b64 = base64.b64encode(data).decode("ascii")
artifact = {
    "format": "pdf",
    "filename": "output.pdf",
    "content": "JVBERi0xLjQK...",  # 38KB+ base64 string
    "size": 28838
}
```

**After:**
```python
# Generate token and move file to persistent storage
token = secrets.token_urlsafe(32)
token_dir = MCP_FILES_DIR / token
final_path = token_dir / filename
shutil.move(out_file, final_path)

# Register in FILE_REGISTRY
FILE_REGISTRY[token] = FileInfo(...)

artifact = {
    "format": "pdf",
    "filename": "output.pdf",
    "token": "xK9mP2vL8qR...",        # 43 char token
    "downloadUrl": "http://localhost:9180/files/xK9mP2vL8qR...",
    "size": 28838
}
# NO 'content' field - saves ~38KB in AI context!
```

Removed `import base64` as it's no longer needed.

### 3. HTTP Download Endpoint (`src/zotero_mcp/cli.py`)

Added complete file serving infrastructure:

- **`download_file_handler()`**: Async handler for GET /files/{token}
  - Validates token and checks expiration
  - Sets proper Content-Type headers (application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document)
  - Streams file in 64KB chunks
  - Returns 404 for missing/expired files, 410 for deleted files

- **`setup_file_routes()`**: Integrates routes with FastMCP's Starlette app
  - Tries multiple methods to access underlying app (mcp.app, mcp._app, mcp._server.app)
  - Adds route dynamically via app.add_route() or app.routes.append()
  - Logs success/failure for debugging

- **`periodic_cleanup_task()`**: Background task that runs every 5 minutes
  - Calls `cleanup_expired_files()` to remove old files
  - Handles asyncio cancellation gracefully

- **Event handlers**: Startup/shutdown hooks for cleanup task
  - Starts cleanup task when SSE server starts
  - Cancels task on shutdown

### 4. Updated Tests

Modified `tests/test_validate_and_build.py`:
- Renamed `test_build_exports_returns_base64_payload` → `test_build_exports_returns_token_payload`
- Changed assertions from checking `content` field to checking `token` and `downloadUrl` fields
- Removed base64 import and decoding logic

Added `tests/test_file_downloads.py`:
- `test_file_download_flow()`: Verifies end-to-end token generation and file storage
- `test_file_expiration()`: Tests TTL-based cleanup

All 70 tests pass successfully.

### 5. Documentation Updates

**README.md**:
- Added "File Downloads (PDF/DOCX Exports)" section
- Explained token-based workflow for AI agents and human users
- Provided environment variable documentation
- Included example workflow with curl command

**`.github/copilot-instructions.md`**:
- Updated "Big picture" to mention file registry and HTTP endpoint
- Added note to "Patterns to follow" about token-based downloads
- Clarified that no base64 content is returned

**Dockerfile**:
- Added `mkdir -p /tmp/mcp-files && chmod 1777 /tmp/mcp-files` to ensure directory exists

## Benefits

### Token Efficiency
- **Before**: 28KB PDF → ~38KB base64 string in AI context
- **After**: 28KB PDF → ~150 bytes of metadata (token + URL + size)
- **Savings**: ~99.6% reduction in context window usage

### Scalability
- Works with files of any size (no context window limit)
- Background cleanup prevents disk space exhaustion
- Configurable TTL balances storage vs. availability

### Developer Experience
- Simple HTTP download (curl, wget, browser)
- Standard REST endpoint (no special client needed)
- Clear error messages (404, 410 status codes)

## Testing Results

```
70 passed in 2.83s
```

All tests pass, including:
- Original export tests (adapted for tokens)
- New file download integration tests
- YAML, validation, and collection export tests

## Example Usage

### AI Agent Workflow

```python
# 1. Call MCP tool
result = mcp.call_tool(
    "zotero_build_exports_content",
    {
        "documentContent": "# My Paper\n\nContent here [@cite]",
        "formats": ["docx", "pdf"],
        "bibliographyContent": bib_json,
    }
)

# 2. Extract download info (no file content in context!)
for artifact in result["artifacts"]:
    # Small metadata only
    token = artifact["token"]           # "xK9mP2vL8qR..."
    url = artifact["downloadUrl"]       # "http://localhost:9180/files/..."
    filename = artifact["filename"]     # "My_Paper.pdf"
    size = artifact["size"]             # 142857
    
    # 3. Download file directly
    run_in_terminal(f"curl -o {filename} {url}")
```

### Direct Browser Access

```
http://localhost:9180/files/xK9mP2vL8qR5mP2vL8qR5mP2vL8qR5mP
```

## Breaking Changes

✅ **NO BACKWARD COMPATIBILITY** (per project rules)

- Removed `content` field from artifact responses
- Tools expecting base64 content will break (intentional)
- Clients must update to use `token` + `downloadUrl` fields

## Future Enhancements

Potential improvements (not implemented):
1. Authentication tokens for downloads (multi-user security)
2. Download progress/streaming for very large files
3. Batch downloads (ZIP multiple files)
4. Webhook/callback for completed exports
5. Download analytics/metrics

## Deployment

### Local Testing
```bash
uv run zotero-mcp --transport sse
# Server runs on localhost:8000 (or configured port)
# Downloads available at http://localhost:9180/files/{token}
```

### Docker Deployment
```bash
make docker-redeploy
# Rebuilds image and restarts container
# Port mapping: host 9180 → container 8000
```

### Verification
```bash
# Check logs for file endpoint
docker logs zotero-mcp-sse | grep "file download"

# Test download endpoint
TOKEN="test-token-here"
curl -I http://localhost:9180/files/$TOKEN
```

## Summary

The implementation successfully eliminates the context window bloat problem by:
1. ✅ Storing files on disk with secure tokens
2. ✅ Serving files via HTTP endpoints
3. ✅ Returning only metadata in tool responses
4. ✅ Automatic cleanup of expired files
5. ✅ Maintaining full backward compatibility with test suite
6. ✅ Comprehensive documentation for AI agents and users

**Result**: 28KB PDF now costs ~150 bytes of context instead of ~38KB (99.6% reduction)
