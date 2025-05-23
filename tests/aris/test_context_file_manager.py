# Tests for aris.context_file_manager

import pytest
import os
import tempfile
from pathlib import Path

from aris.context_file_manager import ContextFileManager

@pytest.fixture
def temp_context_files():
    """Create temporary context files for testing."""
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    
    # Create test context files
    context1_path = os.path.join(temp_dir, "context1.md")
    with open(context1_path, 'w') as f:
        f.write("# Context File 1\n\nThis is test content for context file 1.")
    
    context2_path = os.path.join(temp_dir, "context2.md")
    with open(context2_path, 'w') as f:
        f.write("# Context File 2\n\nThis is test content for context file 2.")
    
    yield temp_dir, [context1_path, context2_path]
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)

@pytest.fixture
def context_manager():
    """Create a context file manager with a custom temp directory."""
    temp_dir = tempfile.mkdtemp()
    manager = ContextFileManager(base_temp_dir=temp_dir)
    
    yield manager
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)

def test_prepare_embedded_context(context_manager, temp_context_files):
    """Test preparing context for embedding directly in the system prompt."""
    temp_dir, context_files = temp_context_files
    
    # Prepare embedded context
    embedded_content = context_manager.prepare_embedded_context(context_files)
    
    # Check that the content contains information from both files
    assert "<context_context1>" in embedded_content
    assert "<context_context2>" in embedded_content
    assert "This is test content for context file 1" in embedded_content
    assert "This is test content for context file 2" in embedded_content

def test_generate_context_file(context_manager, temp_context_files):
    """Test generating a consolidated context file."""
    temp_dir, context_files = temp_context_files
    
    # Generate context file
    session_id = "test-session"
    consolidated_path = context_manager.generate_context_file(context_files, session_id)
    
    # Check that the file was created
    assert os.path.exists(consolidated_path)
    
    # Check file contents
    with open(consolidated_path, 'r') as f:
        content = f.read()
    
    assert "# ARIS Context Reference" in content
    assert "Context File 1" in content
    assert "Context File 2" in content
    assert "This is test content for context file 1" in content
    assert "This is test content for context file 2" in content

def test_estimate_context_size(context_manager, temp_context_files):
    """Test estimating the total size of context files."""
    temp_dir, context_files = temp_context_files
    
    # Get the size of the individual files
    expected_size = sum(os.path.getsize(file) for file in context_files)
    
    # Estimate context size
    estimated_size = context_manager.estimate_context_size(context_files)
    
    # Check that the estimated size matches the expected size
    assert estimated_size == expected_size

def test_context_file_caching(context_manager, temp_context_files):
    """Test that context files are cached correctly."""
    temp_dir, context_files = temp_context_files
    
    # Generate context file twice with the same inputs
    session_id = "test-session"
    path1 = context_manager.generate_context_file(context_files, session_id)
    path2 = context_manager.generate_context_file(context_files, session_id)
    
    # Check that the same file is returned (caching works)
    assert path1 == path2
    
    # Modify one of the context files
    with open(context_files[0], 'a') as f:
        f.write("\n\nAdditional content.")
    
    # Generate context file again
    path3 = context_manager.generate_context_file(context_files, session_id)
    
    # The path should be different since the file content changed
    assert path3 != path1

def test_cleanup_old_files(context_manager, monkeypatch):
    """Test cleaning up old temporary files."""
    import time
    
    # Create files matching the exact prefix used in the implementation
    recent_file = os.path.join(context_manager.base_temp_dir, "context_recent_12345678.md")
    with open(recent_file, 'w') as f:
        f.write("Recent file content")
    
    old_file = os.path.join(context_manager.base_temp_dir, "context_old_87654321.md")
    with open(old_file, 'w') as f:
        f.write("Old file content")
    
    # Mock os.path.getctime to return different creation times
    # This ensures we don't rely on actual file system timestamps
    def mock_getctime(path):
        if "recent" in path:
            return time.time() - 1 * 3600  # 1 hour ago
        else:
            return time.time() - 25 * 3600  # 25 hours ago
    
    # Apply the mock
    monkeypatch.setattr(os.path, "getctime", mock_getctime)
    
    # Register the old file in the manager's temp_files mapping for better coverage
    # This simulates the file being created by generate_context_file
    context_manager.temp_files["test_hash"] = old_file
    
    # Run cleanup with 24 hour threshold
    context_manager.cleanup_old_files(max_age_hours=24)
    
    # Check that the recent file still exists
    assert os.path.exists(recent_file)
    
    # Check that the old file was deleted and removed from cache
    assert not os.path.exists(old_file)
    assert "test_hash" not in context_manager.temp_files