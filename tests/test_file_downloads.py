"""Integration test for file download endpoint."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from zotero_mcp import build_exports_content, FILE_REGISTRY, get_file, cleanup_file
from zotero_mcp.cli import download_file_handler
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route


def test_file_download_flow():
    """Test that files can be generated and downloaded."""
    
    def fake_run(cmd, capture_output, text, env):
        out_idx = cmd.index('-o')
        out_path = Path(cmd[out_idx + 1])
        out_path.write_bytes(b'mock-docx-content')
        class Result:
            returncode = 0
            stderr = ''
        return Result()
    
    with patch('zotero_mcp.__init__.shutil.which', return_value='/usr/bin/pandoc'):
        with patch('zotero_mcp.__init__.subprocess.run', side_effect=fake_run):
            result = build_exports_content('# Test', ['docx'], useCiteproc=False)
            
            # Parse token from result
            import json, re
            match = re.search(r'"token":"([^"]+)"', result)
            assert match, "Token should be in result"
            token = match.group(1)
            
            # Verify file is registered
            file_info = get_file(token)
            assert file_info is not None, "File should be registered"
            assert file_info.filename == "Test.docx"
            assert file_info.size == 17  # len(b'mock-docx-content')
            assert file_info.path.exists(), "File should exist on disk"
            
            # Verify file content
            content = file_info.path.read_bytes()
            assert content == b'mock-docx-content'
            
            print(f"✓ File download flow works correctly")
            print(f"  Token: {token[:16]}...")
            print(f"  File: {file_info.filename}")
            print(f"  Size: {file_info.size} bytes")


def test_file_expiration():
    """Test that expired files are cleaned up."""
    import time
    from zotero_mcp import FILE_REGISTRY, FILE_TTL_SECONDS, cleanup_expired_files
    
    def fake_run(cmd, capture_output, text, env):
        out_idx = cmd.index('-o')
        out_path = Path(cmd[out_idx + 1])
        out_path.write_bytes(b'test')
        class Result:
            returncode = 0
            stderr = ''
        return Result()
    
    with patch('zotero_mcp.__init__.shutil.which', return_value='/usr/bin/pandoc'):
        with patch('zotero_mcp.__init__.subprocess.run', side_effect=fake_run):
            result = build_exports_content('# Old', ['docx'], useCiteproc=False)
            
            import re
            match = re.search(r'"token":"([^"]+)"', result)
            token = match.group(1)
            
            # Verify file exists
            file_info = get_file(token)
            assert file_info is not None
            
            # Simulate expiration
            file_info.created_at = time.time() - FILE_TTL_SECONDS - 1
            
            # Try to get expired file
            expired_file = get_file(token)
            assert expired_file is None, "Expired file should return None"
            assert token not in FILE_REGISTRY, "Expired file should be removed from registry"
            
            print(f"✓ File expiration works correctly")


def test_http_download_endpoint():
    """Test HTTP download endpoint with TestClient."""
    # Create a test app with the download route
    app = Starlette(routes=[
        Route("/files/{token}", download_file_handler, methods=["GET"])
    ])
    
    def fake_run(cmd, capture_output, text, env):
        out_idx = cmd.index('-o')
        out_path = Path(cmd[out_idx + 1])
        out_path.write_bytes(b'test-http-content')
        class Result:
            returncode = 0
            stderr = ''
        return Result()
    
    with patch('zotero_mcp.__init__.shutil.which', return_value='/usr/bin/pandoc'):
        with patch('zotero_mcp.__init__.subprocess.run', side_effect=fake_run):
            result = build_exports_content('# HTTP Test', ['pdf'], useCiteproc=False)
            
            import re
            match = re.search(r'"token":"([^"]+)"', result)
            assert match
            token = match.group(1)
            
            # Test successful download
            client = TestClient(app)
            response = client.get(f"/files/{token}")
            
            assert response.status_code == 200
            assert response.content == b'test-http-content'
            assert response.headers['content-type'] == 'application/pdf'
            assert 'HTTP_Test.pdf' in response.headers.get('content-disposition', '')
            
            print(f"✓ HTTP download endpoint works correctly")
            print(f"  Status: {response.status_code}")
            print(f"  Content-Type: {response.headers['content-type']}")
            print(f"  Content-Length: {len(response.content)} bytes")


def test_http_endpoint_not_found():
    """Test 404 response for invalid token."""
    app = Starlette(routes=[
        Route("/files/{token}", download_file_handler, methods=["GET"])
    ])
    
    client = TestClient(app)
    response = client.get("/files/invalid-token-does-not-exist")
    
    assert response.status_code == 404
    assert b"not found" in response.content.lower()
    print(f"✓ HTTP endpoint returns 404 for invalid token")


def test_http_endpoint_gone():
    """Test 410 response for deleted file."""
    app = Starlette(routes=[
        Route("/files/{token}", download_file_handler, methods=["GET"])
    ])
    
    def fake_run(cmd, capture_output, text, env):
        out_idx = cmd.index('-o')
        out_path = Path(cmd[out_idx + 1])
        out_path.write_bytes(b'temp')
        class Result:
            returncode = 0
            stderr = ''
        return Result()
    
    with patch('zotero_mcp.__init__.shutil.which', return_value='/usr/bin/pandoc'):
        with patch('zotero_mcp.__init__.subprocess.run', side_effect=fake_run):
            result = build_exports_content('# Gone', ['docx'], useCiteproc=False)
            
            import re
            match = re.search(r'"token":"([^"]+)"', result)
            token = match.group(1)
            
            # Delete the file manually
            file_info = get_file(token)
            file_info.path.unlink()
            
            # Try to download deleted file
            client = TestClient(app)
            response = client.get(f"/files/{token}")
            
            assert response.status_code == 410
            assert b"no longer available" in response.content.lower()
            print(f"✓ HTTP endpoint returns 410 for deleted file")


def test_http_endpoint_docx_content_type():
    """Test correct Content-Type for DOCX files."""
    app = Starlette(routes=[
        Route("/files/{token}", download_file_handler, methods=["GET"])
    ])
    
    def fake_run(cmd, capture_output, text, env):
        out_idx = cmd.index('-o')
        out_path = Path(cmd[out_idx + 1])
        out_path.write_bytes(b'docx-content')
        class Result:
            returncode = 0
            stderr = ''
        return Result()
    
    with patch('zotero_mcp.__init__.shutil.which', return_value='/usr/bin/pandoc'):
        with patch('zotero_mcp.__init__.subprocess.run', side_effect=fake_run):
            result = build_exports_content('# DOCX', ['docx'], useCiteproc=False)
            
            import re
            match = re.search(r'"token":"([^"]+)"', result)
            token = match.group(1)
            
            client = TestClient(app)
            response = client.get(f"/files/{token}")
            
            assert response.status_code == 200
            expected_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            assert response.headers['content-type'] == expected_type
            print(f"✓ HTTP endpoint returns correct Content-Type for DOCX")


def test_one_time_download_deletion():
    """Test that files can be deleted after first download when configured."""
    import time
    from zotero_mcp import MCP_DELETE_AFTER_DOWNLOAD
    
    # Only run if deletion is enabled
    if not MCP_DELETE_AFTER_DOWNLOAD:
        print(f"⊘ Skipping one-time download test (MCP_DELETE_AFTER_DOWNLOAD not enabled)")
        return
    
    app = Starlette(routes=[
        Route("/files/{token}", download_file_handler, methods=["GET"])
    ])
    
    def fake_run(cmd, capture_output, text, env):
        out_idx = cmd.index('-o')
        out_path = Path(cmd[out_idx + 1])
        out_path.write_bytes(b'one-time-use')
        class Result:
            returncode = 0
            stderr = ''
        return Result()
    
    with patch('zotero_mcp.__init__.shutil.which', return_value='/usr/bin/pandoc'):
        with patch('zotero_mcp.__init__.subprocess.run', side_effect=fake_run):
            result = build_exports_content('# OneTime', ['pdf'], useCiteproc=False)
            
            import re
            match = re.search(r'"token":"([^"]+)"', result)
            token = match.group(1)
            
            # First download should succeed
            client = TestClient(app)
            response = client.get(f"/files/{token}")
            assert response.status_code == 200
            
            # Wait for cleanup task
            time.sleep(1)
            
            # Second download should fail (file deleted)
            response2 = client.get(f"/files/{token}")
            assert response2.status_code in [404, 410]
            print(f"✓ One-time download deletion works correctly")


if __name__ == "__main__":
    test_file_download_flow()
    test_file_expiration()
    test_http_download_endpoint()
    test_http_endpoint_not_found()
    test_http_endpoint_gone()
    test_http_endpoint_docx_content_type()
    test_one_time_download_deletion()
    print("\n✓ All integration tests passed!")
