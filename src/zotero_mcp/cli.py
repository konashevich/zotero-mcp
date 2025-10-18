import argparse

from zotero_mcp import mcp, zotero_health, logger


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

    # Run the server. Some FastMCP versions don't accept host/port kwargs.
    # We bind/publish the desired port via Docker instead.
    mcp.run(args.transport)


if __name__ == "__main__":
    main()
