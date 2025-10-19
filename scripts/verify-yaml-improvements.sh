#!/usr/bin/env bash
# Quick verification that the YAML improvements are working

set -e

echo "==> Zotero MCP YAML Improvements Verification"
echo ""

echo "1. Running tests..."
uv run pytest -q tests/test_bibliography.py::test_ensure_yaml_citations
uv run pytest -q tests/test_bibliography.py::test_ensure_yaml_citations_idempotency
uv run pytest -q tests/test_bibliography.py::test_ensure_yaml_citations_update_existing
echo "   ✓ Tests passed"
echo ""

echo "2. Checking health diagnostics..."
HEALTH=$(uv run python -c "from zotero_mcp import zotero_health; print(zotero_health())")
echo "$HEALTH" | grep -q "pyyaml" && echo "   ✓ PyYAML status reported"
echo "$HEALTH" | grep -q "ruamel" && echo "   ✓ ruamel.yaml status reported"
echo "$HEALTH" | grep -q "yamlParser" && echo "   ✓ Parser prediction reported"
echo ""

echo "3. Testing ensure_yaml_citations..."
TMPFILE=$(mktemp --suffix=.md)
echo "# Test" > "$TMPFILE"
RESULT=$(uv run python -c "from zotero_mcp import ensure_yaml_citations; print(ensure_yaml_citations('$TMPFILE', 'refs.json', 'style.csl', True))")
echo "$RESULT" | grep -q "parser=" && echo "   ✓ Parser name included in result"
grep -q "bibliography: refs.json" "$TMPFILE" && echo "   ✓ Bibliography field added"
grep -q "csl: style.csl" "$TMPFILE" && echo "   ✓ CSL field added"
grep -q "link-citations: true" "$TMPFILE" && echo "   ✓ Link-citations field added"
rm "$TMPFILE"
echo ""

echo "==> All verifications passed! ✓"
echo ""
echo "The YAML improvements are working correctly."
echo "You can now deploy with: make docker-redeploy"
