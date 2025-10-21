#!/usr/bin/env python3
"""Tiny CLI to call zotero_mcp.build_exports_content from VS Code tasks or shell (Linux-first).

Examples:
    python scripts/build_exports.py --document paper.md --formats docx,pdf --bibliography refs.json --csl .styles/lncs.csl
    python scripts/build_exports.py -d paper.md -f pdf --pdf-engine wkhtmltopdf
"""

from __future__ import annotations

import argparse
import sys
from typing import List
from pathlib import Path

from zotero_mcp import build_exports_content
import json
import re
import base64


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run Pandoc builds via zotero_mcp.build_exports_content (content-first)")
    p.add_argument("-d", "--document", required=True, help="Path to Markdown/Doc to build")
    p.add_argument(
        "-f",
        "--formats",
        required=True,
        help="Comma-separated formats: docx,pdf",
    )
    p.add_argument("-b", "--bibliography", default=None, help="Path to CSL JSON/BibTeX bibliography")
    p.add_argument("-c", "--csl", default=None, help="Path or id of CSL style (optional)")
    p.add_argument(
        "--pdf-engine",
        choices=["wkhtmltopdf", "weasyprint", "xelatex"],
        default="wkhtmltopdf",
        help="PDF engine (non-browser; defaults to wkhtmltopdf).",
    )
    p.add_argument(
        "--output-basename",
        default=None,
        help="Override output filename stem (defaults to title/front matter heading).",
    )
    p.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write generated files (defaults to current directory)",
    )
    args = p.parse_args(argv)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    # Read content-based inputs per repo policy (no cross-OS path mapping in tools)
    doc_content = Path(args.document).read_text(encoding="utf-8")
    bib_content = None
    if args.bibliography:
        bib_path = Path(args.bibliography)
        if bib_path.exists():
            bib_content = bib_path.read_text(encoding="utf-8")
    csl_content = None
    if args.csl:
        csl_path = Path(args.csl)
        if csl_path.exists():
            csl_content = csl_path.read_text(encoding="utf-8")
    out = build_exports_content(
        doc_content,
        formats,  # type: ignore[arg-type]
        outputBasename=args.output_basename,
        bibliographyContent=bib_content,
        cslContent=csl_content,
        pdfEngine=args.pdf_engine,  # type: ignore[arg-type]
        useCiteproc=True,
    )

    print(out)

    # Attempt to save outputs locally
    m = re.search(r"```json\n(.*?)\n```", out, flags=re.DOTALL)
    if not m:
        return 0
    payload = json.loads(m.group(1))
    data = payload.get("result", payload)
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, list):
        return 0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.document).stem
    for art in artifacts:
        fmt = art.get("format")
        if not fmt:
            continue
        filename = art.get("filename") or f"{stem}.{fmt}"
        target = out_dir / filename
        content = art.get("content")
        if content is None:
            print(f"No content for {fmt}; skipped")
            continue
        try:
            data_bytes = base64.b64decode(content)
            target.write_bytes(data_bytes)
            print(f"Wrote {target}")
        except Exception as e:  # noqa: BLE001
            print(f"Failed to write {target}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
