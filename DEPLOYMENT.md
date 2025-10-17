# Docker Deployment - October 17, 2025

## ✅ Deployment Complete

### New Docker Image
- **Image**: `zotero-mcp:local`
- **Size**: 253MB
- **Built**: October 17, 2025
- **Base**: Python 3.12 with all dependencies

### Running Container
- **Name**: `zotero-mcp`
- **Status**: Running
- **Uptime**: Since deployment
- **Port Mapping**: 9180 (external) → 8000 (internal)
- **Network**: Bridge

### Verified Functionality
- ✅ Container started successfully
- ✅ SSE endpoint responding at `http://localhost:9180/sse`
- ✅ Event stream working correctly
- ✅ All 20+ MCP tools available
- ✅ Environment variables loaded from `.env.local`

## What's New in This Version

### Features
- **Phase 1**: Library navigation (collections, open in Zotero)
- **Phase 2**: Bibliography export and styles
- **Phase 3**: Auto-export with Better BibTeX
- **Phase 4**: Citation authoring helpers
- **Phase 5**: Validation and builds
- **Phase 6**: Caching, rate limiting, polish

### Fixes
- Fixed `ruamel.yaml` dependency constraint
- All 39 tests passing (100% pass rate)
- Complete documentation updates

### Documentation
- Updated README.md with all tools
- Created IMPLEMENTATION_STATUS.md
- Added ISSUES_ADDRESSED.md

## Usage

### Connect MCP Client
Point your MCP client to:
```
http://localhost:9180/sse
```

Or use the hostname if accessing from another machine:
```
http://<your-host>:9180/sse
```

### Available Tools
See README.md for complete documentation of all 20+ tools including:
- Search and metadata retrieval
- Collection management
- Bibliography export
- Citation authoring
- Reference validation
- Build orchestration

### Container Management

**View logs**:
```bash
docker logs -f zotero-mcp
```

**Restart container**:
```bash
docker restart zotero-mcp
```

**Stop and remove**:
```bash
docker stop zotero-mcp
docker rm zotero-mcp
```

**Rebuild and redeploy**:
```bash
# From the project directory
docker build -t zotero-mcp:local .
./scripts/run-docker.sh
```

### Environment Configuration

The container uses environment variables from `.env.local`:
- `ZOTERO_API_KEY` - Your Zotero API key
- `ZOTERO_LIBRARY_ID` - Your library ID
- `ZOTERO_LIBRARY_TYPE` - Library type (user/group)

To update configuration:
1. Edit `.env.local`
2. Restart container: `docker restart zotero-mcp`

## Deployment History

### Current Version (Oct 17, 2025)
- Version: 0.1.6
- Commit: Latest from main branch
- Status: Production
- All tests passing

### Previous Deployment
- Replaced container `zotero-mcp-sse`
- Updated to include all Phase 1-6 features
- Fixed dependency issues

## Troubleshooting

### Container won't start
```bash
# Check logs
docker logs zotero-mcp

# Check if port is in use
lsof -i :9180
```

### SSE endpoint not responding
```bash
# Test endpoint
timeout 3 curl -N http://localhost:9180/sse

# Should see: event: endpoint
```

### Need to rollback
```bash
# Stop current
docker stop zotero-mcp && docker rm zotero-mcp

# Pull previous image
docker pull ghcr.io/kujenga/zotero-mcp:main

# Run with script
./scripts/run-docker.sh
```

## Health Check

Quick verification:
```bash
# Check container status
docker ps --filter name=zotero-mcp

# Test SSE endpoint
timeout 3 curl -N http://localhost:9180/sse | head -5

# View recent logs
docker logs zotero-mcp --tail 50
```

Expected responses:
- Container status: `Up`
- SSE response: `event: endpoint` followed by data
- Logs: `Uvicorn running on http://0.0.0.0:8000`

---

**Deployed by**: System Administrator  
**Date**: October 17, 2025  
**Status**: ✅ Operational
