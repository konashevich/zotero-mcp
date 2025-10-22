import os
import typing as _typing
import shutil
import urllib
import subprocess
from pathlib import Path
import re as _re
from typing import Any, Literal, Iterable, Mapping, TypedDict, Optional
import time
import logging
from dataclasses import dataclass
try:
    import bibtexparser
except Exception:  # noqa: BLE001
    bibtexparser = None

# Structured logger
logger = logging.getLogger("zotero_mcp")
if not logger.handlers:
    h = logging.StreamHandler()
    # Include timestamp and tool name for easier tracing
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] zotero_mcp: %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    h.setFormatter(formatter)
    logger.addHandler(h)
    # Allow LOG_LEVEL env to control verbosity; default INFO
    _lvl = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        logger.setLevel(getattr(logging, _lvl, logging.INFO))
    except Exception:  # noqa: BLE001
        logger.setLevel(logging.INFO)
    # Ensure UTC timestamps
    for handler in logger.handlers:
        try:
            handler.formatter.converter = time.gmtime  # type: ignore[attr-defined]
        except Exception:
            pass


# Path normalization helper for cross-platform compatibility
def _normalize_path(path_str: str) -> Path:
    """Normalize file paths for cross-platform use.

    Handles these cases:
    - Windows absolute paths (e.g., C:\\Users\\...) when running on POSIX/Linux
      by mapping to a mounted host drive root if available.
    - Relative paths, optionally resolved against ZOTERO_DOCS_BASE if set.
    - Tilde (~) expansion.

    Environment variables supported:
    - ZOTERO_HOST_DRIVES_ROOT: Root under which Windows drives are mounted (e.g., /host_mnt or /mnt)
      If set, a path like C:\\Users\\foo becomes {ZOTERO_HOST_DRIVES_ROOT}/c/Users/foo.
    - ZOTERO_DOCS_BASE: Base directory to resolve relative paths from.
    """
    s = (path_str or "").strip().strip('"').strip("'")

    # Detect Windows absolute path patterns like C:\\ or C:/
    win_abs = bool(_re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith("\\\\")

    # If we're on non-Windows and the input is a Windows absolute path, try to map it
    if os.name != "nt" and win_abs:
        # Drive-letter based path (ignore UNC for now unless explicitly mapped)
        if _re.match(r"^[A-Za-z]:[\\/]", s):
            drive = s[0].lower()
            rest = s[2:].lstrip("\\/")
            rest_posix = rest.replace("\\", "/")

            # Determine candidate drive roots to try
            roots: list[tuple[Path, str]] = []
            env_root = os.getenv("ZOTERO_HOST_DRIVES_ROOT") or os.getenv("HOST_DRIVES_ROOT")
            if env_root:
                roots.append((Path(env_root), "env"))
            # Common Docker Desktop and WSL mount points
            roots.extend([
                (Path("/host_mnt"), "host_mnt"),  # Docker Desktop
                (Path("/mnt"), "mnt"),            # WSL or Linux
            ])

            # Try root/drive (e.g., /host_mnt/c, /mnt/c)
            for root, _tag in roots:
                drive_root = root / drive
                if drive_root.exists():
                    cand = drive_root / rest_posix
                    return cand

            # Fallback: some setups expose /c directly
            direct = Path(f"/{drive}") / rest_posix
            if direct.parent.exists():
                return direct

            # No mapping found; return as-is Path so caller can fail with a helpful error
            return Path(s)
        else:
            # UNC path on POSIX is not directly accessible without mapping; return as Path(s)
            return Path(s)

    # Normal POSIX/Windows local behavior
    p = Path(s)

    # Expand ~ if present
    try:
        p = p.expanduser()
    except Exception:
        pass

    # If path is relative and a base is provided, resolve against it
    if not p.is_absolute():
        base = os.getenv("ZOTERO_DOCS_BASE")
        if base:
            p = Path(base) / p

    # Resolve to absolute path (handles relative paths and normalizes)
    try:
        p = p.resolve()
    except Exception:
        # If resolve fails (e.g., non-existent path), at least get absolute
        try:
            p = p.absolute()
        except Exception:
            pass
    return p

# Simple in-memory TTL cache and rate limiter
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_DEFAULT = 30.0
_RL_LAST: dict[str, float] = {}
_CACHE_MAX_ENTRIES_DEFAULT = 200


def _cache_ttl() -> float:
    try:
        v = float(os.getenv("ZOTERO_CACHE_TTL", ""))
        if v > 0:
            return v
    except Exception:
        pass
    return _CACHE_TTL_DEFAULT


def _cache_get(key: str) -> Any | None:
    ttl = _cache_ttl()
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _CACHE[key] = (time.monotonic(), value)
    # Evict oldest entries if cache grows too large
    try:
        max_entries = int(os.getenv("ZOTERO_CACHE_MAX", str(_CACHE_MAX_ENTRIES_DEFAULT)))
    except Exception:
        max_entries = _CACHE_MAX_ENTRIES_DEFAULT
    if max_entries > 0 and len(_CACHE) > max_entries:
        # drop oldest ~10% to keep simple
        n_drop = max(1, max_entries // 10)
        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:n_drop]
        for k, _ in oldest:
            _CACHE.pop(k, None)


def _rate_min_interval() -> float:
    try:
        v = float(os.getenv("ZOTERO_RATE_MIN_INTERVAL", ""))
        if v >= 0:
            return v
    except Exception:
        pass
    return 0.2


def _rate_limit(bucket: str, min_interval: float | None = None) -> None:
    if min_interval is None:
        min_interval = _rate_min_interval()
    last = _RL_LAST.get(bucket)
    now = time.monotonic()
    if last is not None:
        delta = now - last
        if delta < min_interval:
            time.sleep(min_interval - delta)
    _RL_LAST[bucket] = time.monotonic()


# Standardized output models (minimal TypedDicts)
class ResolveResultModel(TypedDict):
    resolved: dict[str, dict[str, Any]]
    unresolved: list[str]
    duplicateKeys: list[str]


class ValidationReportModel(TypedDict, total=False):
    unresolvedKeys: list[str]
    duplicateKeys: list[str]
    missingFields: list[dict[str, Any]]
    unusedEntries: list[str]
    duplicateCitations: list[str]
    suggestions: dict[str, list[dict[str, Any]]]


class ExportResultModel(TypedDict):
    path: str
    count: int
    sha256: str
    warnings: list[str]

from mcp.server.fastmcp import FastMCP

from zotero_mcp.client import get_attachment_details, get_zotero_client

# File registry for download tokens
@dataclass
class FileInfo:
    """Information about a file available for download."""
    path: Path
    filename: str
    size: int
    format: str
    created_at: float
    downloaded: bool = False


FILE_REGISTRY: dict[str, FileInfo] = {}
FILE_TTL_SECONDS = int(os.getenv("MCP_FILE_TTL", "3600"))  # 1 hour default
MCP_FILES_DIR = Path(os.getenv("MCP_FILES_DIR", "/tmp/mcp-files"))
MCP_DELETE_AFTER_DOWNLOAD = os.getenv("MCP_DELETE_AFTER_DOWNLOAD", "false").lower() == "true"


def register_file(file_path: Path, filename: str, size: int, format: str) -> str:
    """Register a file for download and return a secure token."""
    import secrets
    
    # Ensure the base directory exists
    MCP_FILES_DIR.mkdir(parents=True, exist_ok=True)
    
    token = secrets.token_urlsafe(32)
    FILE_REGISTRY[token] = FileInfo(
        path=file_path,
        filename=filename,
        size=size,
        format=format,
        created_at=time.time(),
    )
    logger.debug(f"Registered file {filename} with token {token[:8]}...")
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
            try:
                info.path.parent.rmdir()
            except OSError:
                pass  # Directory not empty or doesn't exist
            logger.debug(f"Cleaned up file {info.filename} (token {token[:8]}...)")
        except Exception as e:
            logger.warning(f"Failed to cleanup file {info.filename}: {e}")


def cleanup_expired_files() -> int:
    """Remove all files past TTL. Returns count of cleaned files."""
    now = time.time()
    expired = [
        token for token, info in FILE_REGISTRY.items()
        if now - info.created_at > FILE_TTL_SECONDS
    ]
    for token in expired:
        cleanup_file(token)
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired file(s)")
    return len(expired)


# Create an MCP server
mcp = FastMCP("Zotero")
@mcp.tool(
    name="zotero_health",
    description=(
        "Report server health: yaml import availability, Zotero client init, and key config values."
    ),
)
def zotero_health() -> str:
    """Return a compact health summary for quick diagnostics."""
    import importlib
    import os as _os
    import json as _json
    _t0 = time.perf_counter()
    info: dict[str, Any] = {}
    
    # Check PyYAML availability
    try:
        _ = importlib.import_module("yaml")
        info["pyyaml"] = "ok"
    except Exception:
        info["pyyaml"] = "missing"
    
    # Parser selection is PyYAML-only per policy
    info["yamlParser"] = "pyyaml" if info["pyyaml"] == "ok" else "missing"
    
    # Zotero client init
    try:
        _ = get_zotero_client()
        info["zoteroClient"] = "ok"
    except Exception as e:  # noqa: BLE001
        info["zoteroClient"] = f"error: {e}"
    # key configs
    info["timeout"] = _os.getenv("ZOTERO_REQUEST_TIMEOUT", "(default)")
    info["cacheTTL"] = _os.getenv("ZOTERO_CACHE_TTL", "(default)")
    info["cacheMax"] = _os.getenv("ZOTERO_CACHE_MAX", "(default)")
    info["rateMinInterval"] = _os.getenv("ZOTERO_RATE_MIN_INTERVAL", "(default)")
    info["logLevel"] = logging.getLevelName(logger.level)
    # Pandoc / PDF engine diagnostics
    try:
        explicit_pandoc = os.getenv("PANDOC_PATH")
        if explicit_pandoc:
            info["pandoc"] = explicit_pandoc if Path(explicit_pandoc).exists() else f"missing:{explicit_pandoc}"
        else:
            found = shutil.which("pandoc")
            info["pandoc"] = found or "missing"
        pandoc_path = info["pandoc"]
        if isinstance(pandoc_path, str) and not pandoc_path.startswith("missing"):
            r = subprocess.run([pandoc_path, "--version"], capture_output=True, text=True)
            info["pandocVersion"] = r.stdout.splitlines()[0] if r.returncode == 0 and r.stdout else "unknown"
    except Exception:  # noqa: BLE001
        info["pandoc"] = "error"
    # PDF engine detection (non-browser only)
    engine, engine_warnings = _detect_pdf_engine(os.getenv("PDF_ENGINE"))
    info["pdfEngine"] = engine or "missing"
    if engine:
        try:
            er = subprocess.run([engine, "--version"], capture_output=True, text=True)
            if er.returncode == 0 and er.stdout:
                info["pdfEngineVersion"] = er.stdout.splitlines()[0]
        except Exception:  # noqa: BLE001
            pass
    if engine_warnings:
        info["pdfEngineWarnings"] = engine_warnings
    # Export behavior flags
    info["artifactDelivery"] = "inline-base64"
    info["basenameStrategy"] = "title/front-matter -> heading -> document (override via outputBasename)"
    info["now"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    info["latencyMs"] = round((time.perf_counter() - _t0) * 1000, 1)
    # output compact JSON for machine-readability
    logger.debug(f"health: {info}")
    return "# Health\n" + _compact_json_block("result", info)


def format_item(item: dict[str, Any]) -> str:
    """Format a Zotero item's metadata as a readable string optimized for LLM consumption"""
    data = item["data"]
    item_key = item["key"]
    item_type = data.get("itemType", "unknown")

    # Special handling for notes
    if item_type == "note":
        # Get note content
        note_content = data.get("note", "")
        # Strip HTML tags for cleaner text (simple approach)
        note_content = (
            note_content.replace("<p>", "").replace("</p>", "\n").replace("<br>", "\n")
        )
        note_content = note_content.replace("<strong>", "**").replace("</strong>", "**")
        note_content = note_content.replace("<em>", "*").replace("</em>", "*")

        # Format note with clear sections
        formatted = [
            "## 📝 Note",
            f"Item Key: `{item_key}`",
        ]

        # Add parent item reference if available
        if parent_item := data.get("parentItem"):
            formatted.append(f"Parent Item: `{parent_item}`")

        # Add date if available
        if date := data.get("dateModified"):
            formatted.append(f"Last Modified: {date}")

        # Add tags with formatting for better visibility
        if tags := data.get("tags"):
            tag_list = [f"`{tag['tag']}`" for tag in tags]
            formatted.append(f"\n### Tags\n{', '.join(tag_list)}")

        # Add note content
        formatted.append(f"\n### Note Content\n{note_content}")

        return "\n".join(formatted)

    # Regular item handling (non-notes)

    # Basic metadata with key for easy reference
    formatted = [
        f"## {data.get('title', 'Untitled')}",
        f"Item Key: `{item_key}`",
        f"Type: {item_type}",
        f"Date: {data.get('date', 'No date')}",
    ]

    # Creators with role differentiation
    creators_by_role = {}
    for creator in data.get("creators", []):
        role = creator.get("creatorType", "contributor")
        name = ""
        if "firstName" in creator and "lastName" in creator:
            name = f"{creator['lastName']}, {creator['firstName']}"
        elif "name" in creator:
            name = creator["name"]

        if name:
            if role not in creators_by_role:
                creators_by_role[role] = []
            creators_by_role[role].append(name)

    for role, names in creators_by_role.items():
        role_display = role.capitalize() + ("s" if len(names) > 1 else "")
        formatted.append(f"{role_display}: {'; '.join(names)}")

    # Publication details
    if publication := data.get("publicationTitle"):
        formatted.append(f"Publication: {publication}")
    if volume := data.get("volume"):
        volume_info = f"Volume: {volume}"
        if issue := data.get("issue"):
            volume_info += f", Issue: {issue}"
        if pages := data.get("pages"):
            volume_info += f", Pages: {pages}"
        formatted.append(volume_info)

    # Abstract with clear section header
    if abstract := data.get("abstractNote"):
        formatted.append(f"\n### Abstract\n{abstract}")

    # Tags with formatting for better visibility
    if tags := data.get("tags"):
        tag_list = [f"`{tag['tag']}`" for tag in tags]
        formatted.append(f"\n### Tags\n{', '.join(tag_list)}")

    # URLs, DOIs, and identifiers grouped together
    identifiers = []
    if url := data.get("url"):
        identifiers.append(f"URL: {url}")
    if doi := data.get("DOI"):
        identifiers.append(f"DOI: {doi}")
    if isbn := data.get("ISBN"):
        identifiers.append(f"ISBN: {isbn}")
    if issn := data.get("ISSN"):
        identifiers.append(f"ISSN: {issn}")

    if identifiers:
        formatted.append("\n### Identifiers\n" + "\n".join(identifiers))

    # Notes and attachments
    if notes := item.get("meta", {}).get("numChildren", 0):
        formatted.append(
            f"\n### Additional Information\nNumber of notes/attachments: {notes}"
        )

    return "\n".join(formatted)


@mcp.tool(
    name="zotero_item_metadata",
    description="Get metadata information about a specific Zotero item, given the item key.",
)
def get_item_metadata(item_key: str) -> str:
    """Get metadata information about a specific Zotero item"""
    zot = get_zotero_client()

    try:
        item: Any = zot.item(item_key)
        if not item:
            return f"No item found with key: {item_key}"
        return format_item(item)
    except Exception as e:
        return f"Error retrieving item metadata: {str(e)}"


@mcp.tool(
    name="zotero_item_fulltext",
    description="Get the full text content of a Zotero item, given the item key of a parent item or specific attachment.",
)
def get_item_fulltext(item_key: str) -> str:
    """Get the full text content of a specific Zotero item"""
    zot = get_zotero_client()

    try:
        item: Any = zot.item(item_key)
        if not item:
            return f"No item found with key: {item_key}"

        # Fetch full-text content
        attachment = get_attachment_details(zot, item)

        # Prepare header with metadata
        header = format_item(item)

        # Add attachment information
        if attachment is not None:
            attachment_info = f"\n## Attachment Information\n- **Key**: `{attachment.key}`\n- **Type**: {attachment.content_type}"

            # Get the full text
            full_text_data: Any = zot.fulltext_item(attachment.key)
            if full_text_data and "content" in full_text_data:
                item_text = full_text_data["content"]
                # Calculate approximate word count
                word_count = len(item_text.split())
                attachment_info += f"\n- **Word Count**: ~{word_count}"

                # Format the content with markdown for structure
                full_text = f"\n\n## Document Content\n\n{item_text}"
            else:
                # Clear error message when text extraction isn't possible
                full_text = "\n\n## Document Content\n\n[⚠️ Attachment is available but text extraction is not possible. The document may be scanned as images or have other restrictions that prevent text extraction.]"
        else:
            attachment_info = "\n\n## Attachment Information\n[❌ No suitable attachment found for full text extraction. This item may not have any attached files or they may not be in a supported format.]"
            full_text = ""

        # Combine all sections
        return f"{header}{attachment_info}{full_text}"

    except Exception as e:
        return f"Error retrieving item full text: {str(e)}"


@mcp.tool(
    name="zotero_search_items",
    # More detail can be added if useful: https://www.zotero.org/support/dev/web_api/v3/basics#searching
    description="Search for items in your Zotero library, given a query string, query mode (titleCreatorYear or everything), and optional tag search (supports boolean searches). Returned results can be looked up with zotero_item_fulltext or zotero_item_metadata.",
)
def search_items(
    query: str,
    qmode: Literal["titleCreatorYear", "everything"] | None = "titleCreatorYear",
    tag: str | None = None,
    limit: int | None = 10,
) -> str:
    """Search for items in your Zotero library"""
    zot = get_zotero_client()
    # Cache for identical queries to reduce API churn briefly
    cache_key = f"search:{qmode}:{limit}:{tag}:{query.strip()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        results = cached
    else:
        # Search using the q parameter
        params = {"q": query, "qmode": qmode, "limit": limit}
        if tag:
            params["tag"] = tag

        _rate_limit("zot.search")
        zot.add_parameters(**params)
        # n.b. types for this return do not work, it's a parsed JSON object
        results: Any = zot.items()
        _cache_set(cache_key, results)

    if not results:
        return "No items found matching your query."

    # Header with search info
    header = [
        f"# Search Results for: '{query}'",
        f"Found {len(results)} items." + (f" Using tag filter: {tag}" if tag else ""),
        "Use item keys with zotero_item_metadata or zotero_item_fulltext for more details.\n",
    ]

    # Format results
    formatted_results = []
    for i, item in enumerate(results):
        data = item["data"]
        item_key = item.get("key", "")
        item_type = data.get("itemType", "unknown")

        # Special handling for notes
        if item_type == "note":
            # Get note content
            note_content = data.get("note", "")
            # Strip HTML tags for cleaner text (simple approach)
            note_content = (
                note_content.replace("<p>", "")
                .replace("</p>", "\n")
                .replace("<br>", "\n")
            )
            note_content = note_content.replace("<strong>", "**").replace(
                "</strong>", "**"
            )
            note_content = note_content.replace("<em>", "*").replace("</em>", "*")

            # Extract a title from the first line if possible, otherwise use first few words
            title_preview = ""
            if note_content:
                lines = note_content.strip().split("\n")
                first_line = lines[0].strip()
                if first_line:
                    # Use first line if it's reasonably short, otherwise use first few words
                    if len(first_line) <= 50:
                        title_preview = first_line
                    else:
                        words = first_line.split()
                        title_preview = " ".join(words[:5]) + "..."

            # Create a good title for the note
            note_title = title_preview if title_preview else "Note"

            # Get a preview of the note content (truncated)
            preview = note_content.strip()
            if len(preview) > 150:
                preview = preview[:147] + "..."

            # Format the note entry
            entry = [
                f"## {i + 1}. 📝 {note_title}",
                f"**Type**: Note | **Key**: `{item_key}`",
                f"\n{preview}",
            ]

            # Add parent item reference if available
            if parent_item := data.get("parentItem"):
                entry.insert(2, f"**Parent Item**: `{parent_item}`")

            # Add tags if present (limited to first 5)
            if tags := data.get("tags"):
                tag_list = [f"`{tag['tag']}`" for tag in tags[:5]]
                if len(tags) > 5:
                    tag_list.append("...")
                entry.append(f"\n**Tags**: {' '.join(tag_list)}")

            formatted_results.append("\n".join(entry))
            continue

        # Regular item processing (non-notes)
        title = data.get("title", "Untitled")
        date = data.get("date", "")

        # Format primary creators (limited to first 3)
        creators = []
        for creator in data.get("creators", [])[:3]:
            if "firstName" in creator and "lastName" in creator:
                creators.append(f"{creator['lastName']}, {creator['firstName']}")
            elif "name" in creator:
                creators.append(creator["name"])

        if len(data.get("creators", [])) > 3:
            creators.append("et al.")

        creator_str = "; ".join(creators) if creators else "No authors"

        # Get publication or source info
        source = ""
        if pub := data.get("publicationTitle"):
            source = pub
        elif book := data.get("bookTitle"):
            source = f"In: {book}"
        elif publisher := data.get("publisher"):
            source = f"{publisher}"

        # Get a brief abstract (truncated if too long)
        abstract = data.get("abstractNote", "")
        if len(abstract) > 150:
            abstract = abstract[:147] + "..."

        # Build formatted entry with markdown for better structure
        entry = [
            f"## {i + 1}. {title}",
            f"**Type**: {item_type} | **Date**: {date} | **Key**: `{item_key}`",
            f"**Authors**: {creator_str}",
        ]

        if source:
            entry.append(f"**Source**: {source}")

        if abstract:
            entry.append(f"\n{abstract}")

        # Add tags if present (limited to first 5)
        if tags := data.get("tags"):
            tag_list = [f"`{tag['tag']}`" for tag in tags[:5]]
            if len(tags) > 5:
                tag_list.append("...")
            entry.append(f"\n**Tags**: {' '.join(tag_list)}")

        formatted_results.append("\n".join(entry))

    return "\n\n".join(header + formatted_results)


# ------------------------
# Write-capable MCP tools
# ------------------------

def _is_local_mode() -> bool:
    return os.getenv("ZOTERO_LOCAL", "").lower() in ("true", "1", "yes")


def _normalize_tags(tags: Iterable[Any] | None) -> list[dict[str, Any]] | None:
    if tags is None:
        return None
    norm: list[dict[str, Any]] = []
    for t in tags:
        if isinstance(t, str):
            norm.append({"tag": t})
        elif isinstance(t, Mapping) and "tag" in t:
            norm.append(dict(t))
        else:
            # skip invalid shapes silently
            continue
    return norm


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, dict)
        ):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _write_guard() -> str | None:
    if _is_local_mode():
        return (
            "Write operations are not available in local mode. "
            "Unset ZOTERO_LOCAL and provide ZOTERO_API_KEY/ZOTERO_LIBRARY_ID to use the Web API."
        )
    if not (os.getenv("ZOTERO_LIBRARY_ID") and os.getenv("ZOTERO_API_KEY")):
        return (
            "Missing credentials for writes. Set ZOTERO_LIBRARY_ID and ZOTERO_API_KEY (Web API)."
        )
    return None


def _format_error(prefix: str, e: Exception) -> str:
    """Map common Zotero API errors to friendly messages when possible."""
    code = None
    retry_after = None
    body_json: Any = None
    last_modified_version = None
    # pyzotero exceptions often include a response with status_code
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            code = getattr(resp, "status_code", None)
            retry_after = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
            last_modified_version = resp.headers.get("Last-Modified-Version") if hasattr(resp, "headers") else None
            # try parse JSON body
            try:
                body_json = resp.json()
            except Exception:  # noqa: BLE001
                body_json = None
        except Exception:  # noqa: BLE001
            pass
    # Fallback: try to parse from string
    text = str(e)
    for c in (400, 403, 409, 412, 413, 429):
        if str(c) in text:
            code = c
            break

    helper = ""
    if code == 400:
        helper = "Invalid type/field or unparseable JSON. Check field names for the item type."
    elif code == 403:
        helper = "Insufficient permissions for this library or action. Check API key scopes."
    elif code == 409:
        helper = "Library is locked. Retry after a short delay."
    elif code == 412:
        helper = "Version mismatch: fetch the latest item and retry with its current version."
    elif code == 413:
        helper = "Request too large or storage quota exceeded (attachments)."
    elif code == 429:
        wait = f" Wait {retry_after}s." if retry_after else ""
        helper = f"Rate limited. Reduce request rate and retry later.{wait}"

    suffix = f"\nHint: {helper}" if helper else ""
    # Include server-provided details if available
    details = []
    if last_modified_version:
        details.append(f"Last-Modified-Version: {last_modified_version}")
    if body_json:
        # Keep it compact
        try:
            import json as _json

            details.append("Server: " + _json.dumps(body_json, ensure_ascii=False)[:800])
        except Exception:  # noqa: BLE001
            pass
    extra = ("\n" + "\n".join(details)) if details else ""
    if code:
        return f"{prefix}: HTTP {code}: {text}{suffix}{extra}"
    return f"{prefix}: {text}{extra}"


def _compact_json_block(label: str, obj: dict[str, Any]) -> str:
    try:
        import json as _json

        return f"\n\n### {label}\n```json\n{_json.dumps(obj, ensure_ascii=False, separators=(',', ':'))}\n```"
    except Exception:  # noqa: BLE001
        return ""


def _as_text(obj: Any) -> str:
    """Normalize various upstream response types to a UTF-8 text string.

    - bytes/bytearray → decode utf-8 with replace
    - list[str] → join with double newlines
    - other → str(obj)
    """
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
        return "\n\n".join(obj)
    try:
        return str(obj)
    except Exception:
        return ""


class _DependencyError(RuntimeError):
    """Raised when a required external dependency is unavailable."""


def _sanitize_basename(candidate: str) -> str:
    cleaned = _re.sub(r"[^A-Za-z0-9._-]+", "_", (candidate or "").strip())
    cleaned = cleaned.strip("._-") or "document"
    return cleaned[:120]


def _derive_output_basename(document: str | None, provided: str | None) -> str:
    if provided and provided.strip():
        return _sanitize_basename(provided)

    text = (document or "").lstrip("\ufeff")
    front_match = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=_re.DOTALL)
    if front_match:
        title_match = _re.search(r"^title:\s*['\"]?([^'\"\n]+)", front_match.group(1), flags=_re.MULTILINE)
        if title_match:
            return _sanitize_basename(title_match.group(1))

    heading_match = _re.search(r"^#\s+([^\n]+)", text, flags=_re.MULTILINE)
    if heading_match:
        return _sanitize_basename(heading_match.group(1))

    return "document"


def _ensure_pandoc() -> str:
    explicit = os.getenv("PANDOC_PATH")
    if explicit:
        exp_path = Path(explicit)
        if exp_path.exists():
            return str(exp_path)
        raise _DependencyError(f"PANDOC_PATH points to {explicit}, but the file does not exist.")

    found = shutil.which("pandoc")
    if found:
        return found
    raise _DependencyError(
        "Pandoc not found on server. Install pandoc or set PANDOC_PATH to its location."
    )


def _detect_pdf_engine(
    requested: Literal["wkhtmltopdf", "weasyprint", "xelatex"] | None,
) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    env_engine = os.getenv("PDF_ENGINE")
    env_path = os.getenv("PDF_ENGINE_PATH")

    def _path_supports(name: str) -> bool:
        if not env_path:
            return False
        ep = Path(env_path)
        if not ep.exists():
            warnings.append(f"PDF_ENGINE_PATH set to {env_path} but the file does not exist.")
            return False
        if env_engine:
            return env_engine == name
        return ep.name.lower().startswith(name)

    def _is_available(name: str) -> bool:
        if _path_supports(name):
            return True
        found = shutil.which(name)
        return found is not None

    candidates = ("wkhtmltopdf", "weasyprint", "xelatex")

    if env_engine in candidates and _is_available(env_engine):
        return env_engine, warnings

    if requested in candidates and _is_available(requested):
        return requested, warnings

    for candidate in candidates:
        if _is_available(candidate):
            return candidate, warnings

    warnings.append("No PDF engine found (wkhtmltopdf/weasyprint/xelatex). Pandoc may fail to produce PDF.")
    return None, warnings


@dataclass
class _ExportArtifact:
    format: Literal["docx", "pdf"]
    filename: str
    token: str
    downloadUrl: str
    size: int

    def __post_init__(self) -> None:
        if self.format not in {"docx", "pdf"}:
            raise ValueError(f"Unsupported artifact format: {self.format}")
        if not isinstance(self.filename, str) or not self.filename.strip():
            raise ValueError("filename must be a non-empty string")
        if not isinstance(self.token, str) or not self.token:
            raise ValueError("token must be a non-empty string")
        if not isinstance(self.downloadUrl, str) or not self.downloadUrl:
            raise ValueError("downloadUrl must be a non-empty string")
        if not isinstance(self.size, int) or self.size < 0:
            raise ValueError("size must be a non-negative integer")

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "filename": self.filename,
            "token": self.token,
            "downloadUrl": self.downloadUrl,
            "size": self.size,
        }




def _log_startup_summary() -> None:
    """Emit a one-time log summary covering export dependencies."""
    if os.getenv("ZOTERO_SUPPRESS_STARTUP_LOG") == "1":
        return
    try:
        try:
            pandoc_path = _ensure_pandoc()
            pandoc_msg = pandoc_path
        except _DependencyError as exc:
            pandoc_msg = f"missing ({exc})"
        engine, engine_warnings = _detect_pdf_engine(os.getenv("PDF_ENGINE"))
        delivery = "inline-base64"
        logger.info(
            "startup exports: pandoc=%s, pdf_engine=%s, delivery=%s",
            pandoc_msg,
            engine or "missing",
            delivery,
        )
        for warning in engine_warnings:
            logger.warning("startup exports warning: %s", warning)
    except Exception:  # noqa: BLE001
        logger.debug("startup exports summary failed", exc_info=True)

def _ensure_csl_json(text: str) -> tuple[Any, list[str]]:
    """Parse text as JSON and validate it looks like CSL JSON.

    Returns (parsed, warnings). Parsed is either a list of entries or a dict with items[].
    Adds warnings if the shape looks wrong or entries are missing ids.
    """
    warnings: list[str] = []
    try:
        import json as _json

        parsed: Any = _json.loads(text)
    except Exception as e:  # noqa: BLE001
        return [], [f"INVALID_CSL_EXPORT: not JSON parseable ({e})"]

    def _validate_list(lst: list[Any]) -> list[str]:
        w: list[str] = []
        # Check id presence on first few items
        for it in lst[:5]:
            if not isinstance(it, dict) or not isinstance(it.get("id"), str):
                w.append("INVALID_CSL_EXPORT: entries missing string 'id' — downstream citeproc may fail")
                break
        return w

    if isinstance(parsed, list):
        warnings.extend(_validate_list(parsed))
        return parsed, warnings
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        warnings.extend(_validate_list(parsed["items"]))
        return parsed, warnings
    return parsed, ["INVALID_CSL_EXPORT: unexpected JSON shape (expected array or object with 'items')"]


def _to_csl_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Best-effort mapping from Zotero native item to a minimal CSL entry."""
    data = item.get("data", {}) if isinstance(item, dict) else {}
    entry: dict[str, Any] = {}
    # id: prefer Better BibTeX-like id if present, else Zotero key
    entry["id"] = (
        data.get("citekey")
        or item.get("key")
        or data.get("key")
        or str(item.get("id") or "")
    )
    entry["title"] = data.get("title")
    # authors
    authors: list[dict[str, Any]] = []
    for c in data.get("creators", []) or []:
        if isinstance(c, dict):
            fam = c.get("lastName") or c.get("family")
            giv = c.get("firstName") or c.get("given")
            if fam or giv:
                a: dict[str, Any] = {}
                if fam:
                    a["family"] = fam
                if giv:
                    a["given"] = giv
                authors.append(a)
    if authors:
        entry["author"] = authors
    # issued
    yr: int | None = None
    date = data.get("date") or data.get("year")
    if isinstance(date, str):
        m = _re.search(r"(19|20)\\d{2}", date)
        if m:
            try:
                yr = int(m.group(0))
            except Exception:
                yr = None
    if yr is not None:
        entry["issued"] = {"date-parts": [[yr]]}
    # type (rough mapping)
    t = data.get("itemType")
    if t:
        # minimal, leave as-is; real mapping could be added later
        entry["type"] = "article-journal" if t == "journalArticle" else t
    # DOI/URL passthrough
    if data.get("DOI"):
        entry["DOI"] = data.get("DOI")
    if data.get("url"):
        entry["URL"] = data.get("url")
    return entry


def _normalize_json_input(value: Any, expect: str = "array") -> tuple[str, Any]:
    """Accept a JSON string or a parsed object and return (json_string, parsed).

    expect: "array" (default) or "object" guides a minimal sanity check.
    Raises ValueError on irrecoverable input.
    """
    import json as _json
    parsed: Any
    if value is None:
        parsed = [] if expect == "array" else {}
        return _json.dumps(parsed, ensure_ascii=False), parsed
    if isinstance(value, (dict, list)):
        parsed = value
        s = _json.dumps(parsed, ensure_ascii=False)
        return s, parsed
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            value = str(value)
    if isinstance(value, str):
        s = value
        try:
            parsed = _json.loads(s or ("[]" if expect == "array" else "{}"))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Invalid JSON: {e}")
        # basic shape check
        if expect == "array" and not isinstance(parsed, list) and not (
            isinstance(parsed, dict) and "items" in parsed
        ):
            # allow CSL JSON object with items
            if not isinstance(parsed, dict):
                raise ValueError("Expected a JSON array of CSL items or an object with 'items'.")
        return s, parsed
    raise ValueError("Unsupported input type. Pass a JSON string or a parsed object.")


# ------------------------
# Library navigation
# ------------------------

@mcp.tool(
    name="zotero_get_collections",
    description=(
        "List Zotero collections as a tree with key, name, parentKey, path, and itemCount. "
        "Optionally filter by a parent collection key."
    ),
)
def get_collections(parentKey: str | None = None) -> str:
    """Return collections as a tree with computed paths and item counts.

    Output is a markdown summary followed by a compact JSON block of the flattened tree
    (each node has: key, name, parentKey, path, itemCount).
    """
    zot = get_zotero_client()
    # Cache per parentKey
    cache_key = f"collections:{parentKey or 'root'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        flat = cached
        header = [
            "# Collections (cached)",
            f"Count: {len(flat)}" + (f" | Parent: `{parentKey}`" if parentKey else ""),
        ]
        lines: list[str] = header
        for n in flat[:50]:
            lines.append(f"- `{n['key']}` | {n.get('path', n['name'])} ({n.get('itemCount', 0)})")
        return "\n".join(lines) + _compact_json_block("result", {"collections": flat})
    try:
        # Fetch collections; pyzotero returns a list of objects with data/meta
        if parentKey:
            # Some pyzotero versions offer collections_sub; fall back to filtering
            try:
                collections: Any = zot.collections_sub(parentKey)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                all_colls: Any = zot.collections()
                collections = [c for c in all_colls if c.get("data", {}).get("parentCollection") == parentKey]
        else:
            _rate_limit("zot.collections")
            collections = zot.collections()

        # Build maps
        nodes: dict[str, dict[str, Any]] = {}
        children_map: dict[str | None, list[str]] = {}
        for c in collections:
            data = c.get("data", {})
            key = data.get("key")
            name = data.get("name") or data.get("collectionName") or "(unnamed)"
            parent = data.get("parentCollection") or None
            count = c.get("meta", {}).get("numItems")
            if key:
                nodes[key] = {
                    "key": key,
                    "name": name,
                    "parentKey": parent,
                    "itemCount": int(count) if isinstance(count, int) or (isinstance(count, str) and count.isdigit()) else count or 0,
                }
                children_map.setdefault(parent, []).append(key)

        # Compute paths via DFS from roots (parentKey None or absent)
        def build_paths(start_keys: list[str]) -> None:
            stack: list[tuple[str, list[str]]] = [(k, [nodes[k]["name"]]) for k in start_keys]
            while stack:
                k, path_names = stack.pop()
                nodes[k]["path"] = "/".join(path_names)
                for child in children_map.get(k, []):
                    stack.append((child, path_names + [nodes[child]["name"]]))

        roots = children_map.get(None, [])
        build_paths(roots)

        # If a parentKey was specified, we may need to also include the parent chain for path context
        if parentKey and parentKey not in nodes and isinstance(collections, list):
            # Try fetch the parent to compute its name if needed
            try:
                parent_obj: Any = zot.collection(parentKey)
                pname = parent_obj.get("data", {}).get("name") or parentKey
            except Exception:  # noqa: BLE001
                pname = parentKey
            # Prepend the parent name to child paths
            for k in list(nodes.keys()):
                nodes[k]["path"] = f"{pname}/" + nodes[k].get("path", nodes[k]["name"])  # type: ignore[index]

        flat = list(nodes.values())
        flat.sort(key=lambda n: (n.get("path", ""), n.get("name", "")))

        header = [
            "# Collections",
            f"Count: {len(flat)}" + (f" | Parent: `{parentKey}`" if parentKey else ""),
        ]
        lines: list[str] = header
        for n in flat[:50]:  # limit list in the human section; full JSON below
            lines.append(f"- `{n['key']}` | {n.get('path', n['name'])} ({n.get('itemCount', 0)})")

        _cache_set(cache_key, flat)
        return "\n".join(lines) + _compact_json_block("result", {"collections": flat})
    except Exception as e:  # noqa: BLE001
        return _format_error("Error listing collections", e)


# ------------------------
# Convenience helpers
# ------------------------

@mcp.tool(
    name="zotero_open_in_zotero",
    description=(
        "Return a zotero://select URL for an item. For user libraries uses 'library'; for group libraries uses 'groups/<id>'."
    ),
)
def open_in_zotero(
    itemKey: str,
    libraryId: str | None = None,
    libraryType: Literal["user", "group"] | None = None,
    open: bool | None = False,
) -> str:
    """Build a zotero://select URL for quickly opening an item in the Zotero app.

    If libraryType is 'group' and a libraryId (group ID) is provided, use groups/<id>.
    Otherwise, default to the user library.
    """
    try:
        lib_type = (libraryType or os.getenv("ZOTERO_LIBRARY_TYPE", "user")).lower()
        lib_id = libraryId or os.getenv("ZOTERO_LIBRARY_ID")

        if lib_type == "group" and lib_id:
            url = f"zotero://select/groups/{lib_id}/items/{itemKey}"
        else:
            url = f"zotero://select/library/items/{itemKey}"

        # Optionally attempt to open via OS (best-effort)
        if open:
            try:
                import shutil
                import subprocess
                if shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", url])  # noqa: S603,S607
                # Other platforms could be added here
            except Exception:  # noqa: BLE001
                pass

        return "# Open in Zotero\n" f"URL: {url}"
    except Exception as e:  # noqa: BLE001
        return _format_error("Error building Zotero URL", e)


# ------------------------
# Bibliography export
# ------------------------

# Removed deprecated path-based zotero_export_bibliography (no backward compatibility)


@mcp.tool(
    name="zotero_export_bibliography_content",
    description=(
        "Export the library or a collection as content (bibtex|biblatex|csljson). Returns content, count, sha256, warnings."
    ),
)
def export_bibliography_content(
    format: Literal["bibtex", "biblatex", "csljson"] | None = "csljson",
    scope: Literal["library", "collection"] | None = "library",
    collectionKey: str | None = None,
    limit: int | None = 100,
    fetchAll: bool | None = True,
) -> str:
    """Export bibliography content as a string with metadata (content-first).

    For csljson: ensure the returned string is citeproc-ready. If the upstream
    response is not CSL JSON, fall back to a minimal local mapping and warn.
    """
    import hashlib
    import json as _json

    zot = get_zotero_client()
    try:
        if format not in {"bibtex", "biblatex", "csljson"}:
            return f"Unsupported format: {format}"

        params: dict[str, Any] = {"format": format}
        if limit is not None:
            params["limit"] = max(1, min(100, limit))
        zot.add_parameters(**params)

        # Fetch data
        if scope == "collection":
            if not collectionKey:
                return "collectionKey is required when scope='collection'"
            results: Any = (
                zot.everything(zot.collection_items(collectionKey)) if fetchAll else zot.collection_items(collectionKey)
            )
        else:
            results = zot.everything(zot.items()) if fetchAll else zot.items()

        # Normalize to string content
        count = 0
        content_str = ""
        warnings: list[str] = []
        if format == "csljson":
            # There are two cases:
            # 1) Upstream already returned CSL JSON text/bytes/list
            # 2) Upstream returned Zotero native items (dicts with data/meta)
            diag_codes: list[str] = []
            if isinstance(results, list) and results and isinstance(results[0], dict) and "data" in results[0]:
                # Native Zotero items — map to minimal CSL
                mapped = []
                any_zotero_key_ids = False
                any_authors_partial = False
                for it in results:
                    entry = _to_csl_entry(it)
                    # Mark when id appears to be an 8-char Zotero key
                    if isinstance(entry.get("id"), str) and _re.fullmatch(r"[A-Z0-9]{8}", entry["id"] or ""):
                        any_zotero_key_ids = True
                    # Detect if creators existed but none mapped to family/given
                    data = it.get("data", {}) if isinstance(it, dict) else {}
                    creators = data.get("creators") or []
                    if creators and not entry.get("author"):
                        any_authors_partial = True
                    mapped.append(entry)
                # stable order by id then title
                mapped.sort(key=lambda it: (str(it.get("id", "")), str(it.get("title", ""))))
                content_str = _json.dumps(mapped, ensure_ascii=False)
                count = len(mapped)
                # Validate and warn if ids are missing
                _parsed, w = _ensure_csl_json(content_str)
                warnings.extend(w)
                if any_zotero_key_ids:
                    warnings.append("CSL ids derived from Zotero item keys; Better BibTeX citekeys not available")
                    diag_codes.append("CSL_IDS_FROM_ZOTERO_KEYS")
                if any_authors_partial:
                    warnings.append("Some authors could not be structured (family/given) and were omitted")
                    diag_codes.append("CSL_AUTHORS_PARTIAL")
            else:
                # If results is already a Python list/dict, JSON-encode it; else treat as text
                if isinstance(results, (list, dict)):
                    try:
                        content_str = _json.dumps(results, ensure_ascii=False)
                    except Exception:
                        content_str = _as_text(results)
                else:
                    content_str = _as_text(results)
                parsed, w = _ensure_csl_json(content_str)
                warnings.extend(w)
                if isinstance(parsed, list):
                    count = len(parsed)
                elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                    count = len(parsed["items"])  # type: ignore[index]
                # If parsed shape looks wrong (e.g. list of strings or missing ids), perform a fallback
                need_fallback = False
                if warnings:
                    # Any INVALID_CSL_EXPORT warning triggers fallback mapping
                    need_fallback = any("INVALID_CSL_EXPORT" in w for w in warnings)
                # Additional heuristic: results like ["items", ...] (strings only)
                if not need_fallback and isinstance(results, list) and all(isinstance(x, str) for x in results):
                    need_fallback = True
                if need_fallback:
                    try:
                        # Refetch native items without format param and map locally to CSL
                        zot_fallback = get_zotero_client()
                        # Do not set format to let API return native item JSON
                        if scope == "collection":
                            if not collectionKey:
                                return "collectionKey is required when scope='collection'"
                            native = (
                                zot_fallback.everything(zot_fallback.collection_items(collectionKey)) if fetchAll else zot_fallback.collection_items(collectionKey)
                            )
                        else:
                            native = zot_fallback.everything(zot_fallback.items()) if fetchAll else zot_fallback.items()
                        if isinstance(native, list) and native and isinstance(native[0], dict) and "data" in native[0]:
                            mapped = []
                            any_zotero_key_ids = False
                            any_authors_partial = False
                            for it in native:
                                entry = _to_csl_entry(it)
                                if isinstance(entry.get("id"), str) and _re.fullmatch(r"[A-Z0-9]{8}", entry["id"] or ""):
                                    any_zotero_key_ids = True
                                data = it.get("data", {}) if isinstance(it, dict) else {}
                                creators = data.get("creators") or []
                                if creators and not entry.get("author"):
                                    any_authors_partial = True
                                mapped.append(entry)
                            mapped.sort(key=lambda it: (str(it.get("id", "")), str(it.get("title", ""))))
                            content_str = _json.dumps(mapped, ensure_ascii=False)
                            count = len(mapped)
                            # Revalidate mapped content
                            _parsed2, w2 = _ensure_csl_json(content_str)
                            warnings.extend(w2)
                            diag_codes.append("CSL_FALLBACK_LOCAL_MAPPING")
                            if any_zotero_key_ids:
                                warnings.append("CSL ids derived from Zotero item keys; Better BibTeX citekeys not available")
                                diag_codes.append("CSL_IDS_FROM_ZOTERO_KEYS")
                            if any_authors_partial:
                                warnings.append("Some authors could not be structured (family/given) and were omitted")
                                diag_codes.append("CSL_AUTHORS_PARTIAL")
                    except Exception:
                        # Keep original content_str and warnings if fallback fails
                        pass
            # attach diag codes for csljson branch if any
            if locals().get("diag_codes"):
                # Will be included in JSON block below
                pass
        elif format == "bibtex":
            try:
                import bibtexparser  # type: ignore

                content_str = bibtexparser.dumps(results)  # type: ignore[arg-type]
                try:
                    count = len(getattr(results, "entries", []))
                except Exception:  # noqa: BLE001
                    count = 0
            except Exception:  # noqa: BLE001
                content_str = str(results)
                count = 0
        else:  # biblatex
            content_str = str(results)
            count = len(results) if isinstance(results, list) else 0
            warnings.append("biblatex formatting fallback used; verify output format.")

        sha = hashlib.sha256(content_str.encode("utf-8", errors="ignore")).hexdigest()
        header = [
            "# Bibliography export (content)",
            f"Format: {format}",
            f"Scope: {scope}" + (f" (collection {collectionKey})" if scope == "collection" else ""),
            f"Items: {count}",
            f"SHA256: {sha}",
        ]
        result_obj: dict[str, Any] = {"content": content_str, "count": count, "sha256": sha, "warnings": warnings}
        if format == "csljson":
            # include diagnostic codes when present (from mapping and from warnings)
            dc = list(locals().get("diag_codes") or [])
            for w in warnings:
                if "INVALID_CSL_EXPORT" in w and "INVALID_CSL_EXPORT" not in dc:
                    dc.append("INVALID_CSL_EXPORT")
            if dc:
                result_obj["codes"] = dc
        return "\n".join(header) + _compact_json_block("result", result_obj)
    except Exception as e:  # noqa: BLE001
        return _format_error("Error exporting bibliography", e)


# ------------------------
# Styles and workspace YAML
# ------------------------

# Removed deprecated path-based zotero_ensure_style (no backward compatibility)


@mcp.tool(
    name="zotero_ensure_style_content",
    description=("Fetch a CSL style (id or URL) and return its content with metadata (ETag if available)."),
)
def ensure_style_content(style: str) -> str:
    """Return CSL style content (content-first) without touching the filesystem."""
    import hashlib
    import urllib.parse
    import urllib.request
    import urllib.error

    def _is_url(s: str) -> bool:
        try:
            p = urllib.parse.urlparse(s)
            return p.scheme in {"http", "https"}
        except Exception:  # noqa: BLE001
            return False

    def _download(url: str) -> tuple[bytes, dict[str, str]]:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:  # nosec
            data = resp.read()
            hdrs = {k: v for k, v in getattr(resp, "headers", {}).items()} if hasattr(resp, "headers") else {}
            return data, hdrs

    try:
        if _is_url(style):
            data, hdrs = _download(style)
        else:
            safe = style if style.endswith(".csl") else f"{style}.csl"
            url = f"https://raw.githubusercontent.com/citation-style-language/styles/master/{safe}"
            data, hdrs = _download(url)
        sha = hashlib.sha256(data).hexdigest()
        etag = hdrs.get("ETag") if isinstance(hdrs, dict) else None
        text = data.decode("utf-8", errors="replace")
        header = [
            "# CSL style (content)",
            f"Bytes: {len(data)}",
            f"SHA256: {sha}",
            (f"ETag: {etag}" if etag else ""),
        ]
        return "\n".join([h for h in header if h]) + _compact_json_block(
            "result", {"content": text, "sha256": sha, "etag": etag}
        )
    except Exception as e:  # noqa: BLE001
        return _format_error("Error fetching CSL style", e)


@mcp.tool(
    name="zotero_ensure_yaml_citations_content",
    description=(
        "Ensure a Markdown string's YAML front matter contains bibliography, csl, and link-citations keys. Accepts content, returns updatedContent and diagnostics."
    ),
)
def ensure_yaml_citations_content(
    documentContent: str,
    bibliographyContent: Any | None = None,
    cslContent: Any | None = None,
    linkCitations: bool | None = True,
) -> str:
    """Insert or update YAML front matter keys for citations in provided content.

    Strict: PyYAML only. If unavailable, fail fast with a clear error.
    """
    import re as _re
    try:
        import yaml as _yaml  # type: ignore
    except Exception as e:  # noqa: BLE001
        return _format_error("Error ensuring YAML citations", Exception(f"PyYAML not available: {e}"))

    _t0 = time.perf_counter()
    try:
        # Normalize BOM and newlines
        content = (documentContent or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

        # Detect front matter
        fm_match = _re.match(r"^---\n(.*?)\n---\n(.*)$", content, flags=_re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2)
        else:
            fm_text = ""
            body = content

        changed = False
        preserved: list[str] = []
        keys_updated: list[str] = []

        try:
            fm_obj = _yaml.safe_load(fm_text) if fm_text.strip() else {}
            if not isinstance(fm_obj, dict):
                fm_obj = {}
        except Exception:
            fm_obj = {}

        # Track preserved keys
        preserved = [k for k in fm_obj.keys()]

        # Update keys
        prev = dict(fm_obj)
        # Content-first contract: when content is provided, mark YAML as inline
        if bibliographyContent is not None:
            fm_obj["bibliography"] = "__INLINE__"
        # Only set csl when provided
        if cslContent is not None:
            fm_obj["csl"] = "__INLINE__"
        if linkCitations is not None:
            fm_obj["link-citations"] = bool(linkCitations)

        for k in ("bibliography", "csl", "link-citations"):
            if prev.get(k) != fm_obj.get(k):
                keys_updated.append(k)

        # Dump YAML preserving order
        dumped = _yaml.safe_dump(fm_obj, sort_keys=False).strip()
        updated_content = f"---\n{dumped}\n---\n{body if body else ''}"
        changed = (updated_content != content)

        _ms = round((time.perf_counter() - _t0) * 1000, 1)
        logger.info(f"ensure_yaml_citations_content: updated using pyyaml in {_ms} ms; changed={changed}")
        result = {
            "updatedContent": updated_content,
            "changed": changed,
            "parser": "pyyaml",
            "diagnostics": {"keysUpdated": keys_updated, "preservedKeys": preserved},
        }
        return "YAML citations updated (parser=pyyaml)." + _compact_json_block("result", result)
    except Exception as e:  # noqa: BLE001
        logger.exception("ensure_yaml_citations_content: error")
        return _format_error("Error ensuring YAML citations", e)


# ------------------------
# Better BibTeX auto-export (best-effort)
# ------------------------

@mcp.tool(
    name="zotero_ensure_auto_export",
    description=(
        "Verify (or prepare) Better BibTeX auto-export for a file. Detects local BBT endpoint; if unavailable, returns a clear fallback."
    ),
)
def ensure_auto_export(
    path: str,
    format: Literal["bibtex", "biblatex", "csljson"] | None = "csljson",
    scope: Literal["library", "collection"] | None = "library",
    collectionKey: str | None = None,
) -> str:
    """Ensure/verify Better BibTeX auto-export.

    This function detects Better BibTeX on 127.0.0.1:23119 and returns:
    - status 'verified' if an existing auto-export appears to match (best-effort)
    - status 'available' with a spec to configure if BBT is present but not matched
    - status 'fallback' when BBT is not reachable, advising on-demand export
    """
    import json as _json
    import urllib.error
    import urllib.parse
    import urllib.request

    base = "http://127.0.0.1:23119"

    def _get(url: str) -> bytes:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=1.5) as resp:  # nosec - local endpoint by design
            return resp.read()

    # Apply sensible defaults when inputs are placeholders
    if not path or path.strip() in {".", "./", "auto"}:
        path = os.getenv("ZOTERO_DEFAULT_EXPORT_PATH", os.path.abspath("references.bib"))
    if not format:
        fmt_env = os.getenv("ZOTERO_DEFAULT_EXPORT_FORMAT", "bibtex") or "bibtex"
        if fmt_env not in {"bibtex", "biblatex", "csljson"}:
            fmt_env = "bibtex"
        format = _typing.cast(Literal["bibtex", "biblatex", "csljson"], fmt_env)
    spec = {"path": path, "format": format, "scope": scope, "collectionKey": collectionKey}

    try:
        # Detect BBT presence
        _ = _get(f"{base}/better-bibtex/version")

        # Try to list auto-exports (endpoint shape may vary across versions)
        status = "available"
        try:
            raw = _get(f"{base}/better-bibtex/autoexport?format=json")
            data = _json.loads(raw.decode("utf-8", errors="ignore"))
            # Look for a matching target
            for entry in data if isinstance(data, list) else []:
                tgt = entry.get("path") or entry.get("texpath") or entry.get("exportPath")
                fmt = entry.get("translator") or entry.get("format")
                if tgt and isinstance(tgt, str) and tgt.endswith(path):
                    status = "verified"
                    break
        except Exception:  # noqa: BLE001
            # If listing fails, we still report availability with a spec
            pass

        msg = [
            "# Better BibTeX auto-export",
            f"Status: {status}",
            "BBT detected on localhost. If not already configured, set up an auto-export in Zotero:",
            "- Choose the library or collection",
            f"- Format: {format}",
            f"- Target path: {path}",
        ]
        if scope == "collection" and collectionKey:
            msg.append(f"- Collection key: {collectionKey}")
        return "\n".join(msg) + _compact_json_block("result", {"status": status, **spec})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        # Fallback when local Zotero/BBT is not present
        fb = [
            "# Better BibTeX auto-export",
            "Status: fallback",
            "Local Better BibTeX endpoint is not reachable. Use on-demand export instead:",
            "- Call zotero_export_bibliography to write the file when needed.",
        ]
        return "\n".join(fb) + _compact_json_block("result", {"status": "fallback", **spec})
    except Exception as e:  # noqa: BLE001
        return _format_error("Error ensuring auto-export", e)


@mcp.tool(
    name="zotero_library_ensure_auto_export",
    description=(
        "Ensure (or report) a Better BibTeX auto-export for a file in one call. Internally uses detection or job ensure/verify."
    ),
)
def library_ensure_auto_export(
    path: str,
    format: Literal["bibtex", "biblatex", "csljson"] | None = "csljson",
    scope: Literal["library", "collection"] | None = "library",
    collectionKey: str | None = None,
    keepUpdated: bool | None = True,
) -> str:
    """Unified wrapper to align with the plan's single ensureAutoExport tool surface."""
    # Try the concrete job ensure first; if BBT is unavailable, fall back to detection guidance
    res = bbt_ensure_auto_export_job(path, format=format, scope=scope, collectionKey=collectionKey, keepUpdated=keepUpdated)
    if "Status: fallback" in res or '"status":"fallback"' in res:
        # Provide guidance/detect as a follow-up
        info = ensure_auto_export(path, format=format, scope=scope, collectionKey=collectionKey)
        return res + "\n\n" + info
    return res


# ------------------------
# Citation helpers
# ------------------------

@mcp.tool(
    name="zotero_resolve_citekeys",
    description=(
        "Resolve citekeys to item metadata using a CSL JSON file if provided; otherwise best-effort via Zotero."
    ),
)
def resolve_citekeys(
    citekeys: list[str],
    bibliographyContent: Any | None = None,
    tryZotero: bool | None = True,
    preferBBT: bool | None = True,
) -> str:
    """Resolve citekeys to metadata.

    Strategy:
    - If bibliographyPath points to a CSL JSON file, map by entry.id (Better BibTeX uses citekey as id).
    - Else if tryZotero, for keys that look like Zotero item keys (8-char base32), fetch item and return minimal metadata.
    Output contains: resolved (dict), unresolved (list), duplicateKeys (list).
    """
    import json as _json
    import os as _os
    import re as _re

    resolved: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    duplicates: list[str] = []

    # duplicates detection from input
    seen: set[str] = set()
    for ck in citekeys:
        low = ck.strip()
        if low in seen and low not in duplicates:
            duplicates.append(low)
        seen.add(low)

    # Optional: Prefer Better BibTeX local endpoint for fast citekey resolution
    if preferBBT and citekeys:
        try:
            import json as _json
            import urllib.parse as _uparse
            import urllib.request as _ureq
            import urllib.error as _uerr

            base = "http://127.0.0.1:23119/better-bibtex/json?citekeys="
            q = ",".join([_uparse.quote(c) for c in citekeys])
            url = base + q
            req = _ureq.Request(url)
            with _ureq.urlopen(req, timeout=1.5) as resp:  # nosec - localhost endpoint
                raw = resp.read()
            data = _json.loads(raw.decode("utf-8", errors="ignore"))
            if isinstance(data, list):
                for it in data:
                    if not isinstance(it, dict):
                        continue
                    cid = it.get("id") or it.get("citekey")
                    if isinstance(cid, str) and cid not in resolved:
                        authors = []
                        for a in it.get("author", []) or []:
                            if isinstance(a, dict):
                                fam = a.get("family") or a.get("last")
                                giv = a.get("given") or a.get("first")
                                if fam and giv:
                                    authors.append(f"{fam}, {giv}")
                                elif fam:
                                    authors.append(str(fam))
                        resolved[cid] = {
                            "id": cid,
                            "title": it.get("title"),
                            "author": authors,
                            "issued": it.get("issued"),
                            "type": it.get("type"),
                        }
        except Exception:  # noqa: BLE001
            # Ignore BBT errors and continue with other strategies
            pass

    # From CSL JSON (content-based)
    if bibliographyContent is not None:
        try:
            _s, data = _normalize_json_input(bibliographyContent, expect="array")
            items = data["items"] if isinstance(data, dict) and "items" in data else data
            csl_map: dict[str, dict[str, Any]] = {}
            if isinstance(items, list):
                for it in items:
                    cid = it.get("id") if isinstance(it, dict) else None
                    if isinstance(cid, str):
                        csl_map[cid] = it
            for ck in citekeys:
                entry = csl_map.get(ck)
                if entry:
                    authors = []
                    for a in entry.get("author", []) or []:
                        if isinstance(a, dict):
                            fam = a.get("family") or a.get("last")
                            giv = a.get("given") or a.get("first")
                            if fam and giv:
                                authors.append(f"{fam}, {giv}")
                            elif fam:
                                authors.append(str(fam))
                    if ck not in resolved:
                        resolved[ck] = {
                            "id": entry.get("id"),
                            "title": entry.get("title"),
                            "author": authors,
                            "issued": entry.get("issued"),
                            "type": entry.get("type"),
                        }
                else:
                    unresolved.append(ck)
        except Exception as e:
            return (
                "Invalid bibliographyContent. Pass CSL JSON as a string or a parsed array/object with 'items'. "
                f"Details: {e}"
            )

    # Try Zotero for unresolved keys that look like item keys
    looks_like_item_key = _re.compile(r"^[A-Z0-9]{8}$")
    # Try Zotero fallback even if a bibliography was provided, but only for unresolved keys
    if tryZotero:
        zot = get_zotero_client()
        to_try = [ck for ck in (unresolved if unresolved else citekeys) if looks_like_item_key.match(ck)]
        still_unresolved: list[str] = []
        for ck in to_try:
            try:
                item: Any = zot.item(ck)
                if item:
                    data = item.get("data", {})
                    title = data.get("title")
                    authors = []
                    for c in data.get("creators", []) or []:
                        if "lastName" in c and "firstName" in c:
                            authors.append(f"{c['lastName']}, {c['firstName']}")
                        elif "name" in c:
                            authors.append(c["name"])
                    resolved[ck] = {
                        "key": ck,
                        "title": title,
                        "author": authors,
                        "type": data.get("itemType"),
                    }
                else:
                    still_unresolved.append(ck)
            except Exception:  # noqa: BLE001
                still_unresolved.append(ck)
    unresolved = [ck for ck in citekeys if ck not in resolved]

    header = [
        "# Resolve citekeys",
        f"Total: {len(citekeys)} | Resolved: {len(resolved)} | Unresolved: {len(unresolved)}",
        (f"Duplicate keys: {', '.join(duplicates)}" if duplicates else ""),
    ]
    return "\n".join([h for h in header if h]) + _compact_json_block(
        "result", {"resolved": resolved, "unresolved": unresolved, "duplicateKeys": duplicates}
    )


@mcp.tool(
    name="zotero_insert_citation",
    description=("Format citations for pandoc or LaTeX given citekeys and optional prefix/suffix/pages."),
)
def insert_citation(
    citekeys: list[str],
    style: Literal["pandoc", "latex"] | None = "pandoc",
    prefix: str | None = None,
    suffix: str | None = None,
    pages: str | None = None,
) -> str:
    r"""Return a formatted citation string.

    pandoc: [@a; @b, p. 42]
    latex: \parencite[42]{a,b}
    """
    if not citekeys:
        return "No citekeys provided."
    keys = [k.strip() for k in citekeys if k and k.strip()]
    if not keys:
        return "No citekeys provided."

    if style == "latex":
        opt = pages.strip() if pages else None
        body = ",".join(keys)
        return f"\\parencite[{opt}]{{{body}}}" if opt else f"\\parencite{{{body}}}"

    # pandoc-style
    parts: list[str] = []
    if prefix and prefix.strip():
        parts.append(prefix.strip() + " ")
    # citation cluster: @a; @b
    cluster = "; ".join([f"@{k}" for k in keys])
    if pages and pages.strip():
        cluster += f", p. {pages.strip()}"
    if suffix and suffix.strip():
        cluster += f" {suffix.strip()}"
    parts.append(cluster)
    return "[" + "".join(parts) + "]"


@mcp.tool(
    name="zotero_bbt_resolve_citekeys",
    description=(
        "Resolve citekeys using the Better BibTeX local HTTP API (127.0.0.1:23119). Returns resolved and unresolved."
    ),
)
def bbt_resolve_citekeys(citekeys: list[str]) -> str:
    """Resolve citekeys via Better BibTeX local endpoint.

    Calls /better-bibtex/json?citekeys=ck1,ck2 and expects a JSON array of CSL-ish entries.
    """
    import json as _json
    import urllib.parse as _uparse
    import urllib.request as _ureq
    import urllib.error as _uerr

    if not citekeys:
        return "No citekeys provided."

    base = "http://127.0.0.1:23119/better-bibtex/json?citekeys="
    q = ",".join([_uparse.quote(c) for c in citekeys])
    url = base + q

    try:
        req = _ureq.Request(url)
        with _ureq.urlopen(req, timeout=1.5) as resp:  # nosec - localhost endpoint by design
            raw = resp.read()
        data = _json.loads(raw.decode("utf-8", errors="ignore"))
        resolved: dict[str, dict[str, Any]] = {}
        seen = set()
        # Accept list of dicts; map by id or citekey
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                cid = it.get("id") or it.get("citekey")
                if isinstance(cid, str) and cid not in seen:
                    seen.add(cid)
                    # Normalize authors
                    authors = []
                    for a in it.get("author", []) or []:
                        if isinstance(a, dict):
                            fam = a.get("family") or a.get("last")
                            giv = a.get("given") or a.get("first")
                            if fam and giv:
                                authors.append(f"{fam}, {giv}")
                            elif fam:
                                authors.append(str(fam))
                    resolved[cid] = {
                        "id": cid,
                        "title": it.get("title"),
                        "author": authors,
                        "type": it.get("type"),
                    }
        unresolved = [ck for ck in citekeys if ck not in resolved]
        header = [
            "# BBT resolve citekeys",
            f"Total: {len(citekeys)} | Resolved: {len(resolved)} | Unresolved: {len(unresolved)}",
        ]
        return "\n".join(header) + _compact_json_block("result", {"resolved": resolved, "unresolved": unresolved})
    except (_uerr.URLError, _uerr.HTTPError, TimeoutError):
        header = [
            "# BBT resolve citekeys",
            "Status: fallback (Better BibTeX not reachable)",
        ]
        return "\n".join(header) + _compact_json_block(
            "result", {"resolved": {}, "unresolved": list(citekeys)}
        )


@mcp.tool(
    name="zotero_bbt_ensure_auto_export_job",
    description=(
        "Create or verify a Better BibTeX auto-export job for a path. Returns created/updated/verified, or a fallback if BBT is not reachable."
    ),
)
def bbt_ensure_auto_export_job(
    path: str,
    format: Literal["bibtex", "biblatex", "csljson"] | None = "csljson",
    scope: Literal["library", "collection"] | None = "library",
    collectionKey: str | None = None,
    keepUpdated: bool | None = True,
) -> str:
    """Ensure a Better BibTeX auto-export job exists and matches the requested settings.

    Best-effort against local BBT API. If BBT isn't reachable, returns a friendly fallback.
    """
    import json as _json
    import urllib.parse as _uparse
    import urllib.request as _ureq
    import urllib.error as _uerr

    base = "http://127.0.0.1:23119"
    translator_map = {
        "bibtex": "Better BibTeX",
        "biblatex": "Better BibLaTeX",
        "csljson": "CSL JSON",
    }
    translator = translator_map.get(format or "csljson", "CSL JSON")

    def _get(url: str) -> bytes:
        req = _ureq.Request(url)
        with _ureq.urlopen(req, timeout=1.5) as resp:  # nosec - localhost endpoint by design
            return resp.read()

    def _json_req(url: str, method: str, payload: dict[str, Any]) -> Any:
        data = _json.dumps(payload).encode("utf-8")
        req = _ureq.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        with _ureq.urlopen(req, timeout=2.0) as resp:  # nosec - localhost
            raw = resp.read()
            try:
                return _json.loads(raw.decode("utf-8", errors="ignore"))
            except Exception:  # noqa: BLE001
                return None

    # Detect BBT
    try:
        _ = _get(f"{base}/better-bibtex/version")
    except (_uerr.URLError, _uerr.HTTPError, TimeoutError):
        msg = [
            "# Better BibTeX auto-export",
            "Status: fallback",
            "Local Better BibTeX endpoint is not reachable. Start Zotero with the Better BibTeX plugin.",
        ]
        return "\n".join(msg) + _compact_json_block(
            "result",
            {"status": "fallback", "path": path, "format": format, "scope": scope, "collectionKey": collectionKey},
        )

    # List jobs
    try:
        jobs_raw = _get(f"{base}/better-bibtex/autoexport?format=json")
        jobs = _json.loads(jobs_raw.decode("utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001
        jobs = []

    # Find matching by path
    match = None
    if isinstance(jobs, list):
        for j in jobs:
            try:
                jpath = j.get("path") or j.get("texpath") or j.get("exportPath")
                if isinstance(jpath, str) and (jpath == path or jpath.endswith(path)):
                    match = j
                    break
            except Exception:  # noqa: BLE001
                continue

    # Desired job payload
    body: dict[str, Any] = {
        "path": path,
        "translator": translator,
        "type": "collection" if scope == "collection" else "library",
        "keepUpdated": bool(keepUpdated),
    }
    if scope == "collection" and collectionKey:
        body["collection"] = collectionKey

    status = "created"
    job_id = None
    try:
        if match is None:
            # Create
            resp = _json_req(f"{base}/better-bibtex/autoexport", "POST", body)
            status = "created"
            job_id = (resp or {}).get("id") if isinstance(resp, dict) else None
        else:
            # Verify fields
            needs_update = False
            try:
                if str(match.get("translator")) != translator:
                    needs_update = True
                if scope == "collection" and collectionKey and match.get("collection") != collectionKey:
                    needs_update = True
                if bool(match.get("keepUpdated", True)) != bool(keepUpdated):
                    needs_update = True
            except Exception:  # noqa: BLE001
                needs_update = True

            job_id = match.get("id")
            if needs_update:
                # Update (best effort)
                upd = dict(body)
                if job_id is not None:
                    upd["id"] = job_id
                _ = _json_req(f"{base}/better-bibtex/autoexport", "POST", upd)
                status = "updated"
            else:
                status = "verified"
    except Exception as e:  # noqa: BLE001
        return _format_error("Error ensuring BBT auto-export", e)

    header = [
        "# Better BibTeX auto-export",
        f"Status: {status}",
    ]
    return "\n".join(header) + _compact_json_block(
        "result",
        {
            "status": status,
            "id": job_id,
            "path": path,
            "format": format,
            "translator": translator,
            "scope": scope,
            "collectionKey": collectionKey,
            "keepUpdated": bool(keepUpdated),
        },
    )


@mcp.tool(
    name="zotero_suggest_citations",
    description=("Suggest citations based on input text; returns ranked items with simple overlap scoring."),
)
def suggest_citations(
    text: str,
    limit: int | None = 5,
    qmode: Literal["titleCreatorYear", "everything"] | None = "titleCreatorYear",
) -> str:
    """Suggest citation items with basic token overlap scoring against titles and creators.

    Adds: small cache, retry with narrower query on timeout, and short backoff.
    """
    _t0 = time.perf_counter()
    if not text or len(text.strip()) < 3:
        return "Input text too short to suggest citations."
    zot = get_zotero_client()

    cache_key = f"suggest:{qmode}:{limit}:{text.strip().lower()[:200]}"

    # Optional local-first: scan recent cached search results and rank locally
    local_first = os.getenv("ZOTERO_SUGGEST_LOCAL_FIRST", "true").lower() in {"1", "true", "yes"}
    # threshold for score to accept local results without server call
    try:
        local_threshold = int(os.getenv("ZOTERO_SUGGEST_LOCAL_THRESHOLD", "2"))
    except Exception:
        local_threshold = 2
    local_candidates: list[dict[str, Any]] = []
    if local_first:
        try:
            for k, (_, val) in list(_CACHE.items()):  # type: ignore[misc]
                if isinstance(k, str) and k.startswith("search:") and isinstance(val, list):
                    for it in val:
                        if isinstance(it, dict):
                            local_candidates.append(it)
        except Exception:
            local_candidates = []

    results: Any = None
    used_server = False
    if local_candidates:
        # We'll rank locally; only call server if we don't meet threshold later
        results = local_candidates
    else:
        cached = _cache_get(cache_key)
        if cached is not None:
            results = cached
        else:
            # Fetch candidates with minimal retry policy
            results = []
            tries = 0
            max_retries = 2
            while tries <= max_retries:
                tries += 1
                try:
                    zot.add_parameters(q=text, qmode=qmode, limit=limit or 5)
                    _rate_limit("zot.suggest")
                    results = zot.items()
                    used_server = True
                    break
                except Exception:
                    # On first failure for broad queries, retry with titleCreatorYear
                    if tries == 1 and qmode != "titleCreatorYear":
                        logger.warning("suggest_citations: retry with titleCreatorYear after failure")
                        qmode = "titleCreatorYear"
                        continue
                    import random as _rnd
                    delay = 0.15 * tries + _rnd.random() * 0.1
                    logger.warning(f"suggest_citations: backoff {delay:.2f}s (attempt {tries})")
                    time.sleep(delay)
            _cache_set(cache_key, results)
    if not results:
        logger.info("suggest_citations: no results")
        return "No suggestions found."

    if not isinstance(results, list):
        logger.info("suggest_citations: non-list results")
        return "No suggestions found."

    # Tokenize query
    import re as _re

    qtokens = set([t.lower() for t in _re.findall(r"[\w-]+", text) if len(t) > 2])

    ranked: list[tuple[int, dict[str, Any], list[str], list[str], bool]] = []
    for it in results:
        if not isinstance(it, dict):
            continue
        data = it.get("data", {})
        title = data.get("title", "")
        creators = data.get("creators", []) or []
        tokens = set([t.lower() for t in _re.findall(r"[\w-]+", title)])
        matched_title = qtokens & tokens
        doi = data.get("DOI") or data.get("doi")
        doi_match = 1 if doi and any(part in (doi or "").lower() for part in qtokens) else 0
        for c in creators:
            if isinstance(c, dict):
                if "lastName" in c:
                    tokens.add(c["lastName"].lower())
                if "firstName" in c:
                    tokens.add(c["firstName"].lower())
                if "name" in c:
                    tokens.add(c["name"].lower())
        matched_creators = qtokens & tokens
        # score: title matches weighted higher; DOI contributes
        score = (2 * len(matched_title)) + len(matched_creators) + doi_match
        ranked.append((score, it, sorted(list(matched_title))[:3], sorted(list(matched_creators))[:3], bool(doi)))

    ranked.sort(key=lambda x: (-x[0], x[1].get("key", "")))
    top = ranked[: (limit or 5)]

    # If we only used local candidates and the best score is below threshold, try a single server fetch
    if local_first and local_candidates and top and top[0][0] < local_threshold:
        try:
            zot.add_parameters(q=text, qmode=qmode, limit=limit or 5)
            _rate_limit("zot.suggest")
            sres = zot.items()
            used_server = True
            if isinstance(sres, list) and sres:
                results = sres
                ranked = []
                for it in results:
                    if not isinstance(it, dict):
                        continue
                    data = it.get("data", {})
                    title = data.get("title", "")
                    creators = data.get("creators", []) or []
                    tokens = set([t.lower() for t in _re.findall(r"[\w-]+", title)])
                    matched_title = qtokens & tokens
                    doi = data.get("DOI") or data.get("doi")
                    doi_match = 1 if doi and any(part in (doi or "").lower() for part in qtokens) else 0
                    for c in creators:
                        if isinstance(c, dict):
                            if "lastName" in c:
                                tokens.add(c["lastName"].lower())
                            if "firstName" in c:
                                tokens.add(c["firstName"].lower())
                            if "name" in c:
                                tokens.add(c["name"].lower())
                    matched_creators = qtokens & tokens
                    score = (2 * len(matched_title)) + len(matched_creators) + doi_match
                    ranked.append((score, it, sorted(list(matched_title))[:3], sorted(list(matched_creators))[:3], bool(doi)))
                ranked.sort(key=lambda x: (-x[0], x[1].get("key", "")))
                top = ranked[: (limit or 5)]
        except Exception:
            pass

    lines = [f"# Suggestions (top {len(top)})"]
    for i, pack in enumerate(top, start=1):
        _, item, mt, mc, has_doi = pack
        data = item.get("data", {})
        item_key = item.get("key", "")
        title = data.get("title", "Untitled")
        authors = []
        for c in data.get("creators", []) or []:
            if "lastName" in c and "firstName" in c:
                authors.append(f"{c['lastName']}, {c['firstName']}")
            elif "name" in c:
                authors.append(c["name"])
        rationale = []
        if mt:
            rationale.append(f"title:{'/'.join(mt)}")
        if mc:
            rationale.append(f"creator:{'/'.join(mc)}")
        if has_doi:
            rationale.append("doi")
        lines.append(
            f"{i}. {title} — {', '.join(authors) if authors else 'No authors'} (Key `{item_key}`)"
            + (f" [match: {'; '.join(rationale)}]" if rationale else "")
        )

    _ms = round((time.perf_counter() - _t0) * 1000, 1)
    logger.info(f"suggest_citations: returned {len(top)} items in {_ms} ms; server={used_server}")
    return "\n".join(lines)


# ------------------------
# Validation and builds
# ------------------------

@mcp.tool(
    name="zotero_validate_references_content",
    description=(
        "Validate references in Markdown content against a CSL JSON bibliography string; report unresolved, duplicates, and missing fields."
    ),
)
def validate_references_content(
    documentContent: str,
    bibliographyContent: Any,
    requireDOIURL: bool | None = True,
) -> str:
    """Scan Markdown for citekeys and validate against a CSL JSON bibliography string."""
    import json as _json
    import re as _re

    content = (documentContent or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

    # Strip YAML front matter and fenced code blocks before scanning
    # Remove YAML front matter
    content_wo_yaml = _re.sub(r"^---\n.*?\n---\n", "", content, flags=_re.DOTALL)
    # Remove fenced code blocks ```...```
    content_wo_code = _re.sub(r"```.*?```", "", content_wo_yaml, flags=_re.DOTALL)
    # Ignore escaped \@ occurrences
    content_wo_code = _re.sub(r"\\@", "", content_wo_code)
    # Extract citekeys from pandoc-style and bare @key
    all_keys: list[str] = _re.findall(r"@([A-Za-z0-9:_-]+)", content_wo_code)
    keys = set(all_keys)
    # Also extract LaTeX-style \cite{a,b}, \parencite{a}, \textcite{a}, \autocite{a}
    for m in _re.findall(r"\\(?:cite|parencite|textcite|autocite)\{([^}]*)\}", content_wo_code):
        parts = [p.strip() for p in m.split(",") if p.strip()]
        for p in parts:
            all_keys.append(p)
            keys.add(p)

    try:
        # Accept string or parsed object
        _s, data = _normalize_json_input(bibliographyContent, expect="array")
        items = data["items"] if isinstance(data, dict) and "items" in data else data
        csl_map: dict[str, dict[str, Any]] = {}
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and isinstance(it.get("id"), str):
                csl_map[it["id"]] = it
    except Exception as e:  # noqa: BLE001
        return (
            "Invalid bibliographyContent. Pass CSL JSON as a string or a parsed array/object with 'items'. "
            f"Details: {e}"
        )

    unresolved = [k for k in keys if k not in csl_map]
    duplicate_keys: list[str] = []
    # duplicates within document (approx): multiple mentions are fine; real duplicates refer to citekeys repeated in bib
    # Here we check if the bibliography itself has duplicate ids (rare in JSON arrays)
    seen: set[str] = set()
    for k in csl_map.keys():
        if k in seen and k not in duplicate_keys:
            duplicate_keys.append(k)
        seen.add(k)

    missing_fields: list[dict[str, Any]] = []
    for k in keys:
        it = csl_map.get(k)
        if not it:
            continue
        need: list[str] = []
        if not it.get("title"):
            need.append("title")
        if not it.get("author"):
            need.append("author")
        # Year in CSL often under issued/date-parts
        issued = it.get("issued") or {}
        has_year = False
        if isinstance(issued, dict):
            parts = issued.get("date-parts") or issued.get("raw")
            if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                has_year = True
            elif isinstance(parts, str) and parts:
                has_year = True
        if not has_year:
            need.append("year")
        if requireDOIURL:
            if not (it.get("DOI") or it.get("doi") or it.get("URL") or it.get("url")):
                need.append("doi/url")
        # Don't require DOI/URL for the minimal validation used in tests
        if need:
            missing_fields.append({"id": k, "missing": need})

    # Duplicate citations within the document (same key used more than once)
    counts: dict[str, int] = {}
    for k in all_keys:
        counts[k] = counts.get(k, 0) + 1
    duplicate_citations = [k for k, c in counts.items() if c > 1]

    # Unused entries: present in bibliography but not cited
    unused_entries = [k for k in csl_map.keys() if k not in keys]

    # Use resolver chain to get robust resolution (prefer BBT/file/Zotero)
    try:
        # Best-effort suggestions using existing resolver (bibliographyPath not applicable here).
        # Do NOT override the unresolved list computed from the provided bibliography.
        resolved_out = resolve_citekeys(list(keys), tryZotero=True, preferBBT=True)
        # Extract JSON result block if present
        import json as _json

        m = _re.search(r"```json\n(.*?)\n```", resolved_out, flags=_re.DOTALL)
        suggestions = {}
        if m:
            parsed = _json.loads(m.group(1))
            res = parsed.get("result", parsed)
            _resolved_map = res.get("resolved", {})
            _ = _resolved_map  # reserved for future suggestion formatting
    except Exception:  # noqa: BLE001
        suggestions = {}

    header = ["# Validation report"]
    if len(keys) == 0:
        header.append("No Pandoc citations found. Keep footnotes or add [@keys] for citeproc.")
    header += [
        f"Unresolved: {len(unresolved)}",
        f"Duplicate keys: {len(duplicate_keys)}",
        f"Missing fields: {len(missing_fields)}",
        f"Duplicate citations: {len(duplicate_citations)}",
        f"Unused entries: {len(unused_entries)}",
    ]
    return "\n".join(header) + _compact_json_block(
        "result",
        {
            "unresolvedKeys": unresolved,
            "duplicateKeys": duplicate_keys,
            "duplicateCitations": duplicate_citations,
            "missingFields": missing_fields,
            "unusedEntries": unused_entries,
            "suggestions": {},
        },
    )


@mcp.tool(
    name="zotero_build_exports_content",
    description=(
        "Build DOCX/PDF from Markdown content using Pandoc with --citeproc. Returns download tokens and URLs for direct file retrieval (bypasses context window)."
    ),
)
def build_exports_content(
    documentContent: str,
    formats: list[Literal["docx", "pdf"]],
    outputBasename: str | None = None,
    bibliographyContent: Any | None = None,
    cslContent: Any | None = None,
    useCiteproc: bool | None = True,
    pdfEngine: Literal["wkhtmltopdf", "weasyprint", "xelatex"] | None = None,
    extraArgs: list[str] | None = None,
) -> str:
    import tempfile as _tempfile

    if not formats:
        return "Error: No formats specified. Provide at least one of: docx, pdf."
    supported = {"docx", "pdf"}
    bad = [f for f in formats if f not in supported]
    if bad:
        return f"Error: Unsupported formats: {', '.join(bad)}. Supported: docx, pdf."

    basename = _derive_output_basename(documentContent, outputBasename)

    try:
        _pandoc_path = _ensure_pandoc()
    except _DependencyError as exc:
        has_bib = bibliographyContent is not None
        has_csl = cslContent is not None
        use_cp = True if useCiteproc is None else bool(useCiteproc)
        cmds: list[list[str]] = []
        cmds_one_line: list[str] = []
        for fmt in formats:
            out_name = f"{basename}.{fmt}"
            base = ["pandoc", "doc.md"]
            if use_cp:
                base += ["--citeproc"]
            if has_bib:
                base += ["--bibliography", "refs.json"]
            if has_csl:
                base += ["--csl", "style.csl"]
            if fmt == "pdf":
                base += ["--pdf-engine=wkhtmltopdf"]
            if extraArgs:
                base += list(extraArgs)
            base += ["-o", out_name]
            cmds.append(base)
            cmds_one_line.append(" ".join(base))
        kit = {
            "message": str(exc),
            "steps": [
                "1) Save your Markdown to doc.md (UTF-8)",
                "2) If you have a CSL JSON bibliography, save it to refs.json",
                "3) If you have a CSL style, save it to style.csl",
                "4) Run the command(s) below for each requested format:",
            ],
            "commands": cmds,
            "commandsOneLine": cmds_one_line,
            "notes": [
                "PDF requires wkhtmltopdf, weasyprint, or xelatex installed; the commands default to wkhtmltopdf.",
                "Set PDF_ENGINE and PDF_ENGINE_PATH to choose a different engine if desired.",
                "CSL JSON must be an array of items or an object with an 'items' array. Example: [{\"id\":\"k1\",\"title\":\"T\"}].",
            ],
        }
        return f"Error: {exc}" + _compact_json_block("clientBuild", kit)

    _t0 = time.perf_counter()
    out_artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    tempdir = _tempfile.mkdtemp(prefix="zot-export-")
    try:
        doc_path = Path(tempdir) / "doc.md"
        doc_path.write_text((documentContent or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")
        bib_path = None
        if bibliographyContent is not None:
            try:
                bib_str, _ = _normalize_json_input(bibliographyContent, expect="array")
            except Exception as e:  # noqa: BLE001
                return f"Invalid bibliographyContent: {e}"
            bib_path = Path(tempdir) / "refs.json"
            bib_path.write_text(bib_str, encoding="utf-8")
        csl_path = None
        if cslContent is not None:
            csl_path = Path(tempdir) / "style.csl"
            csl_path.write_text(cslContent, encoding="utf-8")

        chosen_engine_for_log: str | None = None
        for fmt in formats:
            out_file = Path(tempdir) / f"{basename}.{fmt}"
            cmd = [
                _pandoc_path,
                str(doc_path),
                "-o",
                str(out_file),
            ]
            if useCiteproc:
                cmd.append("--citeproc")
            if fmt == "pdf":
                chosen_engine, engine_warnings = _detect_pdf_engine(pdfEngine)
                warnings.extend(engine_warnings)
                if chosen_engine:
                    cmd += [f"--pdf-engine={chosen_engine}"]
                    chosen_engine_for_log = chosen_engine
            if bib_path:
                cmd += ["--bibliography", str(bib_path)]
            if csl_path:
                cmd += ["--csl", str(csl_path)]
            if extraArgs:
                cmd += list(extraArgs)

            logger.info(f"pandoc: {' '.join(cmd)}")
            run_env = os.environ.copy()
            pdf_engine_path_env = os.getenv("PDF_ENGINE_PATH")
            if pdf_engine_path_env:
                ep = Path(pdf_engine_path_env)
                if ep.exists():
                    run_env["PATH"] = str(ep.parent) + os.pathsep + run_env.get("PATH", "")
            r = subprocess.run(cmd, capture_output=True, text=True, env=run_env)
            if r.returncode != 0:
                warnings.append(r.stderr.strip())
                continue
            
            # Check file exists and get size
            if not out_file.exists():
                warnings.append(f"artifact {fmt} missing at {out_file}")
                continue
            
            try:
                file_size = out_file.stat().st_size
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"artifact {fmt} stat failed: {exc}")
                continue
            
            # Move file to persistent location for download
            try:
                import secrets
                # Generate token for this file
                file_token = secrets.token_urlsafe(32)
                token_dir = MCP_FILES_DIR / file_token
                token_dir.mkdir(parents=True, exist_ok=True)
                final_filename = f"{basename}.{fmt}"
                final_path = token_dir / final_filename
                shutil.move(str(out_file), str(final_path))
                
                # Register file in registry
                FILE_REGISTRY[file_token] = FileInfo(
                    path=final_path,
                    filename=final_filename,
                    size=file_size,
                    format=fmt,
                    created_at=time.time(),
                )
                logger.info(f"Registered file {final_filename} with token {file_token[:8]}... (registry size: {len(FILE_REGISTRY)})")
                
                # Build download URL
                host = os.getenv("MCP_HOST", "localhost")
                port = os.getenv("MCP_PORT", "9180")
                download_url = f"http://{host}:{port}/files/{file_token}"
                
                artifact = _ExportArtifact(
                    format=fmt,
                    filename=final_filename,
                    token=file_token,
                    downloadUrl=download_url,
                    size=file_size,
                )
                out_artifacts.append(artifact.as_dict())
            except Exception as exc:  # noqa: BLE001
                logger.error(f"artifact {fmt} registration failed: {exc}", exc_info=True)
                warnings.append(f"artifact {fmt} registration failed: {exc}")
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
    _ms = round((time.perf_counter() - _t0) * 1000, 1)
    logger.info(f"build_exports_content: built {formats} in {_ms} ms")
    header = [
        "# Build exports",
        f"Formats: {', '.join(formats)}",
        f"Basename: {basename}",
        "",
        "Download files using the provided URLs or tokens.",
        "Example: `curl -o output.pdf <downloadUrl>`",
        f"Files expire after {FILE_TTL_SECONDS // 60} minutes.",
    ]
    chosen_engine_version = None
    try:
        if chosen_engine_for_log and shutil.which(chosen_engine_for_log):
            ev = subprocess.run([chosen_engine_for_log, "--version"], capture_output=True, text=True)
            if ev.returncode == 0 and ev.stdout:
                chosen_engine_version = ev.stdout.splitlines()[0]
    except Exception:
        pass
    return "\n".join(header) + _compact_json_block(
        "result",
        {
            "artifacts": out_artifacts,
            "warnings": warnings,
            "chosenEngine": chosen_engine_for_log,
            "chosenEngineVersion": chosen_engine_version,
        },
    )


@mcp.tool(
    name="zotero_insert_citation_content",
    description=(
        "Format citations for pandoc or LaTeX given citekeys and optional prefix/suffix/pages (content API)."
    ),
)
def insert_citation_content(
    citekeys: list[str],
    pages: str | None = None,
    prefix: str | None = None,
    suffix: str | None = None,
    style: Literal["pandoc", "latex"] | None = "pandoc",
) -> str:
    # Delegate to existing implementation
    return insert_citation(citekeys=citekeys, pages=pages, prefix=prefix, suffix=suffix, style=style or "pandoc")


@mcp.tool(
    name="zotero_create_item",
    description="Create a new Zotero item. Provide itemType and a fields object; optional tags, collections, and parentItem.",
)
def create_item(
    itemType: str,
    fields: dict[str, Any],
    tags: list[Any] | None = None,
    collections: list[str] | None = None,
    parentItem: str | None = None,
    validateOnly: bool | None = False,
    writeToken: str | None = None,
) -> str:
    guard = _write_guard()
    if guard:
        return guard

    zot = get_zotero_client()
    # For idempotent writes header handling
    sess: Any = None
    original_token: str | None = None
    try:
        template: Any = zot.item_template(itemType)
        # merge editable fields
        if fields:
            template.update(fields)
        if parentItem:
            template["parentItem"] = parentItem
        if collections:
            template["collections"] = list(collections)
        norm_tags = _normalize_tags(tags)
        if norm_tags is not None:
            template["tags"] = norm_tags

        if validateOnly:
            try:
                zot.check_items([template])
                return (
                    "Validation successful for new item of type '"
                    + itemType
                    + "'."
                )
            except Exception as e:  # noqa: BLE001
                # Try to enrich with allowed fields
                try:
                    fields_info: Any = zot.item_type_fields(itemType)
                    allowed_fields: list[str] = []
                    if isinstance(fields_info, Iterable):
                        for f in fields_info:
                            if isinstance(f, Mapping):
                                fname = f.get("field")
                                if isinstance(fname, str):
                                    allowed_fields.append(fname)
                    allowed = ", ".join(sorted(set(allowed_fields)))
                    extra = f"\nAllowed fields for {itemType}: {allowed}" if allowed else ""
                    return f"Validation failed: {e}{extra}"
                except Exception:  # noqa: BLE001
                    return f"Validation failed: {e}"

        # Best-effort support for write token (idempotent writes)
        try:
            sess = getattr(zot, "session", None) or getattr(zot, "_session", None)
            if writeToken and sess and hasattr(sess, "headers"):
                original_token = sess.headers.get("Zotero-Write-Token")
                sess.headers["Zotero-Write-Token"] = writeToken
        except Exception:  # noqa: BLE001
            pass

        resp: Any = zot.create_items([template])
        success = resp.get("success", {})
        failed = resp.get("failed", {})
        unchanged = resp.get("unchanged", {})
        if success:
            # index "0" corresponds to our single object
            new_key = list(success.values())[0]
            summary = (
                f"## ✅ Item created\nKey: `{new_key}`\nType: {itemType}\n"
                "Use zotero_item_metadata to view details."
            )
            return summary + _compact_json_block("result", {"key": new_key, "type": itemType})
        if unchanged:
            key = list(unchanged.values())[0]
            return f"## ⚠️ Unchanged\nItem already existed: `{key}`"
        if failed:
            err = list(failed.values())[0]
            return f"## ❌ Create failed\nCode: {err.get('code')}\nMessage: {err.get('message')}"
        return "## ❌ Create failed with unknown response"
    except Exception as e:  # noqa: BLE001
        return _format_error("Error creating item", e)
    finally:
        # Clear write token to avoid cross-request reuse
        try:
            if sess and hasattr(sess, "headers") and writeToken is not None:
                if original_token is None:
                    sess.headers.pop("Zotero-Write-Token", None)
                else:
                    sess.headers["Zotero-Write-Token"] = original_token
        except Exception:  # noqa: BLE001
            pass


@mcp.tool(
    name="zotero_update_item",
    description="Update an existing Zotero item by key. Default strategy is patch (safe).",
)
def update_item(
    itemKey: str,
    patch: dict[str, Any],
    strategy: Literal["patch", "put"] | None = "patch",
    expectedVersion: int | None = None,
) -> str:
    guard = _write_guard()
    if guard:
        return guard

    zot = get_zotero_client()
    try:
        current: Any = zot.item(itemKey)
        if not current:
            return f"No item found with key: {itemKey}"
        version = (
            expectedVersion if expectedVersion is not None else current["data"].get("version")
        )
        if strategy == "patch":
            payload: dict[str, Any] = {"key": itemKey, "version": version}
            payload.update(patch or {})
            zot.update_items([payload])
        else:
            # PUT: deep-merge patch into full editable JSON
            full = dict(current["data"])
            merged = _deep_merge(full, patch or {})
            zot.update_item(merged)

        # Try to fetch new version (best-effort)
        try:
            latest: Any = zot.item(itemKey)
            new_version = latest["data"].get("version")
        except Exception:  # noqa: BLE001
            new_version = "(unknown)"
        summary = (
            f"## ✅ Item updated\nKey: `{itemKey}`\nVersion: {new_version}\n"
            "Fields changed: " + ", ".join(sorted(patch.keys()))
        )
        return summary + _compact_json_block("result", {"key": itemKey, "version": new_version})
    except Exception as e:  # noqa: BLE001
        return _format_error("Error updating item", e)


@mcp.tool(
    name="zotero_add_note",
    description="Create a note (top-level or child). Provide content (HTML or plain text).",
)
def add_note(
    content: str,
    parentItem: str | None = None,
    tags: list[str] | None = None,
) -> str:
    guard = _write_guard()
    if guard:
        return guard

    zot = get_zotero_client()
    try:
        note: Any = zot.item_template("note")
        # Markdown-to-HTML (light): handle **bold**, *italic*, and line breaks
        note_html = content
        if "<" not in content and ">" not in content:
            # very small subset
            note_html = note_html.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            note_html = note_html.replace("*", "<em>", 1).replace("*", "</em>", 1)
            esc = note_html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            esc = esc.replace("\n\n", "</p><p>").replace("\n", "<br>")
            note_html = f"<p>{esc}</p>"
        note["note"] = note_html
        if parentItem:
            note["parentItem"] = parentItem
        norm_tags = _normalize_tags(tags)
        if norm_tags is not None:
            note["tags"] = norm_tags
        resp: Any = zot.create_items([note])
        success = resp.get("success", {})
        if success:
            new_key = list(success.values())[0]
            summary = (
                f"## ✅ Note created\nKey: `{new_key}`"
                + (f"\nParent: `{parentItem}`" if parentItem else "")
            )
            return summary + _compact_json_block("result", {"key": new_key, "parent": parentItem})
        failed = resp.get("failed", {})
        if failed:
            err = list(failed.values())[0]
            return f"## ❌ Note create failed\nCode: {err.get('code')}\nMessage: {err.get('message')}"
        return "## ❌ Note create failed with unknown response"
    except Exception as e:  # noqa: BLE001
        return f"Error creating note: {e}"


@mcp.tool(
    name="zotero_set_tags",
    description="Replace or append tags on an item. mode=replace|append (default replace).",
)
def set_tags(
    itemKey: str,
    tags: list[str],
    mode: Literal["replace", "append"] | None = "replace",
) -> str:
    guard = _write_guard()
    if guard:
        return guard

    if not tags:
        return "No tags provided."

    zot = get_zotero_client()
    try:
        item: Any = zot.item(itemKey)
        if not item:
            return f"No item found with key: {itemKey}"
        # normalize and deduplicate tags
        deduped = []
        seen = set()
        invalid = []
        for t in tags:
            if isinstance(t, str) and t.strip():
                key = t.strip()
                if key.lower() not in seen:
                    seen.add(key.lower())
                    deduped.append(key)
            else:
                invalid.append(str(t))

        if mode == "append":
            _ = zot.add_tags(item, *deduped)
            summary = f"## ✅ Tags appended\nItem: `{itemKey}`\nAdded: {', '.join(deduped)}"
            if invalid:
                summary += f"\nSkipped invalid: {', '.join(invalid)}"
            return summary + _compact_json_block("result", {"key": itemKey, "appended": deduped})
        # replace mode
        version = item["data"].get("version")
        payload = {
            "key": itemKey,
            "version": version,
            "tags": [{"tag": t} for t in deduped],
        }
        zot.update_items([payload])
        summary = f"## ✅ Tags replaced\nItem: `{itemKey}`\nTags: {', '.join(deduped)}"
        if invalid:
            summary += f"\nSkipped invalid: {', '.join(invalid)}"
        return summary + _compact_json_block("result", {"key": itemKey, "tags": deduped})
    except Exception as e:  # noqa: BLE001
        return _format_error("Error setting tags", e)


@mcp.tool(
    name="zotero_export_collection",
    description=(
        "Export items from a collection. Provide collectionKey and an export format (e.g. bibtex, ris, csv, csljson), "
        "or set format to 'bib' or 'citation' with a CSL style."
    ),
)
def export_collection(
    collectionKey: str,
    format: Literal[
        "bibtex",
        "biblatex",
        "coins",
        "csljson",
        "csv",
        "mods",
        "refer",
        "rdf_bibliontology",
        "rdf_dc",
        "rdf_zotero",
        "ris",
        "tei",
        "wikipedia",
        "bib",
        "citation",
    ] = "ris",
    style: str | None = None,
    limit: int | None = 100,
    start: int | None = 0,
    fetchAll: bool | None = False,
) -> str:
    """Export a collection in the requested format.

    For export formats (bibtex/ris/csv/etc.), the API requires an explicit limit (max 100 per page).
    For 'bib'/'citation', a CSL style is recommended.
    """
    zot = get_zotero_client()
    import json as _json

    # Configure parameters based on mode
    try:
        params: dict[str, Any] = {}
        export_formats = {
            "bibtex",
            "biblatex",
            "coins",
            "csljson",
            "csv",
            "mods",
            "refer",
            "rdf_bibliontology",
            "rdf_dc",
            "rdf_zotero",
            "ris",
            "tei",
            "wikipedia",
        }
        if format in export_formats:
            params["format"] = format
            if limit is None:
                limit = 100
        elif format in {"bib", "citation"}:
            params["format"] = "json"
            params["include"] = format
            if style:
                params["style"] = style
            if limit is None:
                limit = 100
        else:
            return f"Unsupported format: {format}"

        if limit is not None:
            params["limit"] = max(1, min(100, limit))
        if start is not None:
            params["start"] = max(0, start)

        zot.add_parameters(**params)
        # Fetch items
        if fetchAll:
            results: Any = zot.everything(zot.collection_items(collectionKey))
        else:
            results = zot.collection_items(collectionKey)

        count = 0
        content_str = ""
        warnings: list[str] = []
        # Normalize output by format
        if format == "csljson":
            # Treat upstream as text and validate CSL JSON
            extra_codes: list[str] = []
            if isinstance(results, (list, dict)):
                # JSON-encode Python objects for consistent shape
                try:
                    text = _json.dumps(results, ensure_ascii=False)
                except Exception:
                    text = _as_text(results)
            else:
                text = _as_text(results)
            parsed, w = _ensure_csl_json(text)
            warnings.extend(w)
            if isinstance(parsed, list):
                count = len(parsed)
            elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                count = len(parsed["items"])  # type: ignore[index]
            content_str = text
            # Fallback: if invalid or non-citeproc-ready, refetch native items and map locally
            need_fallback = any("INVALID_CSL_EXPORT" in ww for ww in warnings)
            if not need_fallback and isinstance(results, list) and all(isinstance(x, str) for x in results):
                need_fallback = True
            if need_fallback:
                try:
                    zot_fb = get_zotero_client()
                    native = zot_fb.everything(zot_fb.collection_items(collectionKey)) if fetchAll else zot_fb.collection_items(collectionKey)
                    if isinstance(native, list) and native and isinstance(native[0], dict) and "data" in native[0]:
                        mapped = []
                        any_zotero_key_ids = False
                        any_authors_partial = False
                        for it in native:
                            entry = _to_csl_entry(it)
                            if isinstance(entry.get("id"), str) and _re.fullmatch(r"[A-Z0-9]{8}", entry["id"] or ""):
                                any_zotero_key_ids = True
                            data = it.get("data", {}) if isinstance(it, dict) else {}
                            creators = data.get("creators") or []
                            if creators and not entry.get("author"):
                                any_authors_partial = True
                            mapped.append(entry)
                        mapped.sort(key=lambda it: (str(it.get("id", "")), str(it.get("title", ""))))
                        content_str = _json.dumps(mapped, ensure_ascii=False)
                        count = len(mapped)
                        _parsed2, w2 = _ensure_csl_json(content_str)
                        warnings.extend(w2)
                        extra_codes.append("CSL_FALLBACK_LOCAL_MAPPING")
                        if any_zotero_key_ids:
                            warnings.append("CSL ids derived from Zotero item keys; Better BibTeX citekeys not available")
                            extra_codes.append("CSL_IDS_FROM_ZOTERO_KEYS")
                        if any_authors_partial:
                            warnings.append("Some authors could not be structured (family/given) and were omitted")
                            extra_codes.append("CSL_AUTHORS_PARTIAL")
                except Exception:
                    pass
        elif format == "bibtex":
            # pyzotero returns a bibtexparser database object
            try:
                import bibtexparser  # type: ignore

                content_str = bibtexparser.dumps(results)  # type: ignore[arg-type]
                # Estimate count from entries if available
                try:
                    count = len(getattr(results, "entries", []))
                except Exception:  # noqa: BLE001
                    count = 0
            except Exception:  # noqa: BLE001
                content_str = str(results)
                count = 0
        elif format in export_formats:
            # Treat as text (RIS/CSV/etc.) — do not JSON-parse
            content_str = _as_text(results)
            # Better RIS count heuristic: count TY - lines
            if format == "ris":
                import re as _re2
                count = len(_re2.findall(r"(?m)^TY\s*-", content_str))
                # Warn that count is heuristic
                warnings.append("COUNT_HEURISTIC: RIS entry count estimated by 'TY -' lines")
            elif isinstance(results, list):
                count = len(results)
            else:
                count = 1 if content_str.strip() else 0
        else:
            # bib/citation included in JSON data per item
            if isinstance(results, list):
                count = len(results)
                # Extract included field into a text block
                key = "bib" if format == "bib" else "citation"
                parts: list[str] = []
                for it in results:
                    try:
                        data = it.get("data", {})
                        included = data.get(key, "")
                        if included:
                            parts.append(str(included))
                    except Exception:  # noqa: BLE001
                        pass
                content_str = "\n\n".join(parts)
                if count > 0 and not content_str.strip():
                    warnings.append(
                        "EMPTY_CITATION_EXPORT: Zotero did not include formatted strings; check style or API parameters"
                    )
            else:
                content_str = str(results)
                count = 0

        header = [
            f"# Collection export",
            f"Collection: `{collectionKey}`",
            f"Format: {format}" + (f" (style: {style})" if style and format in {"bib", "citation"} else ""),
            f"Items: {count}",
        ]

        # Build compact JSON summary
        # Attach diagnostic codes for known conditions
        codes: list[str] = []
        extra_codes = locals().get("extra_codes", []) or []
        for w in list(warnings):
            if "INVALID_CSL_EXPORT" in w:
                codes.append("INVALID_CSL_EXPORT")
            if "EMPTY_CITATION_EXPORT" in w:
                codes.append("EMPTY_CITATION_EXPORT")
            if "COUNT_HEURISTIC" in w:
                codes.append("COUNT_HEURISTIC")
        # Merge any additional diagnostic codes computed during processing
        try:
            for c in extra_codes:
                if c not in codes:
                    codes.append(c)
        except Exception:
            pass
        summary_block = _compact_json_block("result", {
            "collectionKey": collectionKey,
            "format": format,
            "style": style,
            "count": count,
            "limit": limit,
            "start": start,
            "all": bool(fetchAll),
            "warnings": warnings,
            "codes": codes,
        })

        # Include exported content in a fenced block (avoid JSON fence for non-JSON)
        content_block = f"\n\n### Exported content\n```\n{content_str}\n```"
        return "\n".join(header) + summary_block + content_block
    except Exception as e:  # noqa: BLE001
        return _format_error("Error exporting collection", e)

_log_startup_summary()
