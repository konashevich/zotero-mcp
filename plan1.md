# Write-capable tools plan for zotero-mcp

This plan adds Zotero write capabilities to the MCP server: create items, edit items, add notes and tags, with safe defaults (PATCH-like updates), clear error reporting, and test coverage. Attachments and collection helpers are proposed as a follow-up.

## Scope and goals

- Add MCP tools to:
  - Create item (`zotero_create_item`)
  - Update item (`zotero_update_item`)
  - Add note (`zotero_add_note`)
  - Set/append tags (`zotero_set_tags`)
- Respect Zotero API constraints: authentication, versioning, rate limiting, and local read-only mode.
 

## Constraints and assumptions

- Local API is read-only today; writing requires Web API with API key.
- Environment variables drive auth (already in project):
  - `ZOTERO_LOCAL` (true/false)
  - `ZOTERO_API_KEY`
  - `ZOTERO_LIBRARY_ID`
  - `ZOTERO_LIBRARY_TYPE` (user|group)
- Use `pyzotero` for all calls; lean on its helpers for templates, validation, updates, and attachments.

## New MCP tools (v1)

### 1) zotero_create_item
- Purpose: Create a new library item (optionally child of `parentItem`).
- Inputs:
  - `itemType: string` (e.g., `journalArticle`, `book`, `webpage`)
  - `fields: object` (editable fields per Zotero types)
  - `tags?: (string | { tag: string, type?: number })[]`
  - `collections?: string[]`
  - `parentItem?: string`
  - `writeToken?: string` (optional for idempotency)
  - `validateOnly?: boolean` (skip write; run validation)
- Behavior:
  - If `ZOTERO_LOCAL` is true: return error "Local API is read-only; use Web API".
  - Build from `zot.item_template(itemType)`, merge `fields`, normalize `tags`/`collections`/`parentItem`.
  - If `validateOnly`: call `zot.check_items()` and return validation result; otherwise `zot.create_items([item])`.
- Output:
  - On success: created key/version and a human-readable summary.
  - On failure: friendly message with HTTP code and details.

### 2) zotero_update_item
- Purpose: Update an existing item by `itemKey`.
- Inputs:
  - `itemKey: string`
  - `patch: object` (partial fields to set)
  - `strategy?: "patch" | "put"` (default `patch`)
  - `expectedVersion?: number` (optional)
- Behavior:
  - If `strategy="patch"`:
    - Get current version via `zot.item(itemKey)` unless `expectedVersion` provided.
    - Build `{ key, version, ...patch }` and `zot.update_items([payload])` (POST/PATCH semantics).
  - If `strategy="put"`:
    - Retrieve item, deep-merge editable JSON with `patch`, call `zot.update_item(full)`.
    - Warning: PUT removes unspecified properties; use sparingly.
- Output:
  - On success: new version, changed fields summary.
  - On 412: indicate version mismatch and advise refetch; include latest version if available.

### 3) zotero_add_note
- Purpose: Create a note (top-level or child) with optional tags.
- Inputs:
  - `content: string` (HTML preferred; can accept Markdown for simple cases)
  - `parentItem?: string`
  - `tags?: string[]`
- Behavior: Build `itemType="note"` template, set `note`, `parentItem`, `tags`, create via `zot.create_items([note])`.
- Output: note key and metadata.

### 4) zotero_set_tags
- Purpose: Replace or append tags on an item.
- Inputs:
  - `itemKey: string`
  - `mode: "replace" | "append"` (default `replace`)
  - `tags: string[]`
- Behavior:
  - `append`: fetch item and call `zot.add_tags(item, *tags)`.
  - `replace`: fetch item version; patch tags as full array via `zot.update_items([{ key, version, tags: [...] }])`.
- Output: item key/version and applied tags.

## Optional v1.1 tools (collections)
- `zotero_create_collection(name, parentCollection?)` via `zot.create_collections()`.
- `zotero_add_to_collections(itemKey, collections, mode:"replace"|"append")` via patch/`addto_collection()`.

## Optional v2 (attachments)
- `zotero_add_attachment(parentItem, files: [{ path, filename? }])` using `attachment_simple` or `attachment_both`.
- Handle quota and exists cases, and register uploads.

## Error handling strategy
- Map common HTTP errors to friendly messages:
  - 400 Bad Request: invalid type/field; show invalid keys; hint to `item_type_fields` docs.
  - 403 Forbidden: insufficient permissions (API key scope).
  - 409 Conflict: library locked; recommend retry/backoff.
  - 412 Precondition Failed: version mismatch (stale); advise fetching current item.
  - 413 Request Entity Too Large (attachments/quota): report clearly.
  - 429 Too Many Requests: honor `Retry-After`.
- Always include the underlying message from pyzotero error where available.

## Implementation plan

1. Guardrails
   - In each write tool, check `ZOTERO_LOCAL`; if true, return clear read-only error.
   - Validate env: require `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID` for writes.

2. Implement tools in `src/zotero_mcp/__init__.py`
   - Add four new `@mcp.tool` functions with typed parameters and normalized inputs.
   - Use `get_zotero_client()` and `pyzotero` methods:
     - Create: `item_template` → merge → (optional `check_items`) → `create_items([obj])`.
     - Update (patch): fetch version → `update_items([{ key, version, ...patch }])`.
     - Update (put): fetch → deep-merge → `update_item(full)`.
     - Note: create `note` template → `create_items`.
     - Tags: `add_tags` or `update_items` with full tags array.
   - Return markdown-formatted summaries with keys/versions and highlights of changed fields.

3. README update
   - Document new tools, inputs, and caveats (local read-only; PATCH vs PUT semantics; tag/collection replacement behavior).

## Edge cases & guidance
- Arrays (tags/collections) in PATCH act as full sets. Provide `append` modes for safer behavior.
- Creators input: accept either `name` or `firstName`/`lastName` shapes with `creatorType`; pass through to API.
- Versioning: default to fetching current item version for updates unless caller supplies `expectedVersion`.
- Rate limiting and lock: surface headers (`Retry-After`) where possible and avoid auto-retry loops.

## References
- Zotero Web API Basics: https://www.zotero.org/support/dev/web_api/v3/basics
- Write Requests: https://www.zotero.org/support/dev/web_api/v3/write_requests
- File Uploads: https://www.zotero.org/support/dev/web_api/v3/file_upload
- Pyzotero docs: https://pyzotero.readthedocs.io/en/latest/
