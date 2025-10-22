import argparse
import asyncio
from pathlib import Path

from zotero_mcp import mcp, zotero_health, logger, get_file, cleanup_expired_files


# HTTP file download handler
async def download_file_handler(request):
    """Handle GET /files/{token} requests for file downloads."""
    from starlette.responses import StreamingResponse, Response
    from zotero_mcp import cleanup_file, MCP_DELETE_AFTER_DOWNLOAD
    
    token = request.path_params.get('token', '')
    
    file_info = get_file(token)
    if not file_info:
        return Response("File not found or expired", status_code=404)
    
    if not file_info.path.exists():
        cleanup_file(token)
        return Response("File no longer available", status_code=410)
    
    # Mark as downloaded
    file_info.downloaded = True
    
    # Determine content type
    content_type = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(file_info.format, "application/octet-stream")
    
    # Stream file
    def iterfile():
        with open(file_info.path, "rb") as f:
            # Read in 64KB chunks
            while chunk := f.read(65536):
                yield chunk
    
    headers = {
        "Content-Disposition": f'attachment; filename="{file_info.filename}"',
        "Content-Length": str(file_info.size),
    }
    
    logger.info(f"Serving file {file_info.filename} (token {token[:8]}...)")
    
    response = StreamingResponse(
        iterfile(),
        media_type=content_type,
        headers=headers,
    )
    
    # Delete file after download if configured (one-time use)
    if MCP_DELETE_AFTER_DOWNLOAD:
        # Schedule cleanup after response is sent
        async def cleanup_after_download():
            # Small delay to ensure file is fully streamed
            await asyncio.sleep(0.5)
            cleanup_file(token)
            logger.info(f"Deleted file after download: {file_info.filename}")
        
        # Start cleanup task in background
        asyncio.create_task(cleanup_after_download())
    
    return response


# Background cleanup task
async def periodic_cleanup_task():
    """Remove expired files every 5 minutes."""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            cleanup_expired_files()
        except asyncio.CancelledError:
            logger.info("Cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Cleanup task error: {e}")


def setup_file_routes_and_lifespan():
    """Add file download routes and lifespan handler to the MCP server's ASGI app."""
    from contextlib import asynccontextmanager
    
    try:
        # FastMCP exposes the underlying Starlette app via sse_app() method
        app = None
        if hasattr(mcp, 'sse_app') and callable(mcp.sse_app):
            app = mcp.sse_app()
        elif hasattr(mcp, 'sse_app'):
            app = mcp.sse_app
        elif hasattr(mcp, 'app'):
            app = mcp.app
        elif hasattr(mcp, '_app'):
            app = mcp._app
        elif hasattr(mcp, '_server') and hasattr(mcp._server, 'app'):
            app = mcp._server.app
        
        if app is None:
            logger.critical("Could not access FastMCP's Starlette app for file routes")
            return False
        
        # Add the file download route
        from starlette.routing import Route
        
        # Check if routes can be added dynamically
        if hasattr(app, 'add_route'):
            app.add_route("/files/{token}", download_file_handler, methods=["GET"])
            logger.info("Added file download route: GET /files/{token}")
        elif hasattr(app, 'routes'):
            # Manually append to routes list
            file_route = Route("/files/{token}", download_file_handler, methods=["GET"])
            app.routes.append(file_route)
            logger.info("Added file download route: GET /files/{token}")
        else:
            logger.warning("Could not add file download route to app")
            return False
        
        # Setup lifespan context manager for cleanup task
        original_lifespan = getattr(app.router, 'lifespan_context', None)
        
        @asynccontextmanager
        async def lifespan_with_cleanup(app_instance):
            """Lifespan that manages background cleanup task."""
            # Start cleanup task
            cleanup_task = asyncio.create_task(periodic_cleanup_task())
            logger.info("Started file cleanup background task")
            
            try:
                # If there was an original lifespan, run it
                if original_lifespan:
                    async with original_lifespan(app_instance):
                        yield
                else:
                    yield
            finally:
                # Cancel cleanup on shutdown
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
                logger.info("Stopped file cleanup background task")
        
        # Replace lifespan
        if hasattr(app, 'router'):
            app.router.lifespan_context = lifespan_with_cleanup
            logger.info("Configured lifespan for background cleanup")
        else:
            logger.warning("Could not setup lifespan - background cleanup may not work")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to setup file routes and lifespan: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Zotero Model Context Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport to use",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind for SSE (default from library if not provided)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind for SSE (default from library if not provided)",
    )
    args = parser.parse_args()

    # Log a concise health summary at startup
    try:
        health = zotero_health()
        # Extract the compact JSON block for the log, fallback to first line
        start = health.find("```json")
        end = health.find("```", start + 1)
        if start != -1 and end != -1:
            payload = health[start + 7 : end].strip()
            logger.info(f"startup health: {payload}")
        else:
            logger.info("startup health: ready")
    except Exception:
        logger.warning("startup health: failed to produce report")

    # Setup file download routes and lifespan for SSE transport
    if args.transport == "sse":
        if setup_file_routes_and_lifespan():
            logger.info("File download endpoint enabled at /files/{token}")
        else:
            logger.error("CRITICAL: Failed to setup file download routes - downloads will not work!")
            logger.error("The server will continue but file exports will fail.")

    # Run the server. Some FastMCP versions don't accept host/port kwargs.
    # We bind/publish the desired port via Docker instead.
    mcp.run(args.transport)


if __name__ == "__main__":
    main()
