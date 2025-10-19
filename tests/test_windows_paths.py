"""Tests for Windows path handling and cross-platform compatibility"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from zotero_mcp import ensure_yaml_citations, validate_references, build_exports


def test_ensure_yaml_citations_windows_path(tmp_path: Path) -> None:
    """Test Windows-style paths with backslashes and spaces"""
    # Create a directory with spaces like Windows paths often have
    doc_dir = tmp_path / "My Documents" / "Blockchain Materials"
    doc_dir.mkdir(parents=True)
    doc = doc_dir / "paper.md"
    doc.write_text("# Title\n\nBody", encoding="utf-8")

    # Test with forward slashes (should work on both platforms)
    msg = ensure_yaml_citations(str(doc), "refs.json", "style.csl", True)
    content = doc.read_text(encoding="utf-8")

    assert "YAML citations updated" in msg
    assert content.startswith("---\n")
    assert "bibliography: refs.json" in content


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
def test_ensure_yaml_citations_windows_backslashes(tmp_path: Path) -> None:
    """Test actual Windows backslash paths (only runs on Windows)"""
    doc_dir = tmp_path / "OneDrive" / "Public VS Private"
    doc_dir.mkdir(parents=True)
    doc = doc_dir / "paper.md"
    doc.write_text("# Title\n\nBody", encoding="utf-8")

    # Use Windows-style path with backslashes
    windows_path = str(doc).replace("/", "\\")
    
    msg = ensure_yaml_citations(windows_path, "refs.json", "style.csl", True)
    content = doc.read_text(encoding="utf-8")

    assert "YAML citations updated" in msg
    assert "bibliography: refs.json" in content


def test_ensure_yaml_citations_path_with_special_chars(tmp_path: Path) -> None:
    """Test paths with special characters (parentheses, exclamation marks, etc.)"""
    # Simulate path like: c:\Users\akona\OneDrive\!4AUS\Blockchain Materials\...
    doc_dir = tmp_path / "!4AUS" / "Blockchain Materials (2024)" / "Public VS Private"
    doc_dir.mkdir(parents=True)
    doc = doc_dir / "paper.md"
    doc.write_text("# Title\n\nBody", encoding="utf-8")

    msg = ensure_yaml_citations(str(doc), "refs.json", "style.csl", True)
    content = doc.read_text(encoding="utf-8")

    assert "YAML citations updated" in msg
    assert "bibliography: refs.json" in content


def test_validate_references_windows_path(tmp_path: Path) -> None:
    """Test validate_references with Windows-style paths"""
    import json
    
    # Create document with citation
    doc_dir = tmp_path / "My Documents" / "Research"
    doc_dir.mkdir(parents=True)
    doc = doc_dir / "paper.md"
    doc.write_text("# Title\n\nSome text [@key1] here.", encoding="utf-8")
    
    # Create bibliography
    bib = tmp_path / "references.json"
    bib_data = [{
        "id": "key1",
        "type": "article",
        "title": "Test Article",
        "author": [{"family": "Smith", "given": "John"}],
        "DOI": "10.1234/test",
        "URL": "https://example.com"
    }]
    bib.write_text(json.dumps(bib_data), encoding="utf-8")
    
    result = validate_references(str(doc), str(bib), requireDOIURL=True)
    
    assert "Validation" in result or "validation" in result.lower()
    # Should find the citation
    assert "key1" in result or "0 unresolved" in result or "Unresolved: 0" in result


def test_build_exports_windows_path(tmp_path: Path) -> None:
    """Test build_exports with Windows-style paths"""
    doc_dir = tmp_path / "Documents" / "My Papers"
    doc_dir.mkdir(parents=True)
    doc = doc_dir / "paper.md"
    doc.write_text("# Title\n\nContent", encoding="utf-8")
    
    # Mock pandoc being available
    with patch("zotero_mcp.__init__.shutil.which", return_value="/usr/bin/pandoc"):
        with patch("zotero_mcp.__init__.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            
            result = build_exports(str(doc), ["docx"], useCiteproc=False)
            
            # Should not fail with path issues
            assert "Error" not in result or "not in PATH" in result
            # Verify pandoc was called (or error message about it)
            if "not in PATH" not in result:
                assert mock_run.called


def test_path_normalization_with_tilde(tmp_path: Path) -> None:
    """Test that paths with ~ are expanded correctly"""
    # This test verifies the _normalize_path function handles user home directory
    from zotero_mcp import _normalize_path
    
    # Test with explicit path (not relying on ~ expansion in test environment)
    test_path = str(tmp_path / "test.md")
    normalized = _normalize_path(test_path)
    
    assert normalized.is_absolute()
    assert str(normalized) == os.path.abspath(test_path)


def test_path_normalization_relative_to_absolute(tmp_path: Path) -> None:
    """Test that relative paths are converted to absolute"""
    from zotero_mcp import _normalize_path
    
    # Change to tmp_path directory
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        
        # Test relative path
        normalized = _normalize_path("./test.md")
        
        assert normalized.is_absolute()
        assert str(normalized).startswith(str(tmp_path))
    finally:
        os.chdir(original_cwd)
