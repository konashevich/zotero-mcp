#!/usr/bin/env python3
"""Tiny CLI to call zotero_mcp.build_exports from VS Code tasks or shell.

Examples:
  python scripts/build_exports.py --document paper.md --formats docx,html --bibliography refs.json --csl .styles/lncs.csl
  python scripts/build_exports.py -d paper.md -f pdf --pdf-engine edge
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from zotero_mcp import build_exports


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run Pandoc builds via zotero_mcp.build_exports")
    p.add_argument("-d", "--document", required=True, help="Path to Markdown/Doc to build")
    p.add_argument(
        "-f",
        "--formats",
        required=True,
        help="Comma-separated formats: docx,html,pdf",
    )
    p.add_argument("-b", "--bibliography", default=None, help="Path to CSL JSON/BibTeX bibliography")
    p.add_argument("-c", "--csl", default=None, help="Path or id of CSL style (optional)")
    p.add_argument(
        "--pdf-engine",
        choices=["edge", "xelatex"],
        default="edge",
        help="PDF engine (edge default).",
    )
    args = p.parse_args(argv)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    out = build_exports(
        documentPath=args.document,
        formats=formats,  # type: ignore[arg-type]
        bibliographyPath=args.bibliography,
        cslPath=args.csl,
        pdfEngine=args.pdf_engine,  # type: ignore[arg-type]
        useCiteproc=True,
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
