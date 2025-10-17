import argparse

from zotero_mcp import mcp


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

    # Run the server. Some FastMCP versions don't accept host/port kwargs.
    # We bind/publish the desired port via Docker instead.
    mcp.run(args.transport)


if __name__ == "__main__":
    main()
