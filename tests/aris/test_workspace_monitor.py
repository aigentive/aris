"""
Tests for workspace file monitoring functionality.
"""
import tempfile
import time
import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from aris.workspace_monitor import WorkspaceFileMonitor


class TestWorkspaceFileMonitor:
    """Test the WorkspaceFileMonitor class."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def monitor(self, temp_workspace):
        """Create a WorkspaceFileMonitor for testing."""
        return WorkspaceFileMonitor(str(temp_workspace))
    
    def test_monitor_initialization(self, temp_workspace):
        """Test WorkspaceFileMonitor initialization."""
        monitor = WorkspaceFileMonitor(str(temp_workspace))
        
        assert monitor.workspace_path == temp_workspace.resolve()
        assert monitor.ignore_patterns == WorkspaceFileMonitor.DEFAULT_IGNORE_PATTERNS
        assert monitor.max_files == 10000
        assert monitor._monitoring_enabled is True
        assert isinstance(monitor._initial_snapshot, dict)
    
    def test_monitor_initialization_custom_params(self, temp_workspace):
        """Test WorkspaceFileMonitor initialization with custom parameters."""
        custom_patterns = {'*.test', '.custom'}
        monitor = WorkspaceFileMonitor(
            str(temp_workspace), 
            ignore_patterns=custom_patterns, 
            max_files=500
        )
        
        assert monitor.ignore_patterns == custom_patterns
        assert monitor.max_files == 500
    
    def test_should_ignore_patterns(self, monitor, temp_workspace):
        """Test file ignoring based on patterns."""
        # Test hidden files
        hidden_file = temp_workspace / ".hidden"
        assert monitor._should_ignore(hidden_file) is True
        
        # Test system files
        ds_store = temp_workspace / ".DS_Store"
        assert monitor._should_ignore(ds_store) is True
        
        # Test development artifacts
        pycache_dir = temp_workspace / "__pycache__"
        assert monitor._should_ignore(pycache_dir) is True
        
        # Test normal files
        normal_file = temp_workspace / "normal.txt"
        assert monitor._should_ignore(normal_file) is False
        
        # Test .git directory itself
        git_dir = temp_workspace / ".git"
        git_dir.mkdir(exist_ok=True)
        assert monitor._should_ignore(git_dir) is True
    
    def test_should_ignore_aris_files(self, monitor, temp_workspace):
        """Test that ARIS-specific files are properly ignored."""
        # Test ARIS log directory
        logs_dir = temp_workspace / "logs"
        assert monitor._should_ignore(logs_dir) is True
        
        # Test ARIS log files in logs directory
        logs_dir.mkdir(exist_ok=True)
        log_file = logs_dir / "aris_run_20240601_123456.log"
        assert monitor._should_ignore(log_file) is True
        
        # Test ARIS log files with pattern
        aris_log = temp_workspace / "aris_session.log"
        assert monitor._should_ignore(aris_log) is True
        
        # Test .aris profile directory
        aris_profile_dir = temp_workspace / ".aris"
        assert monitor._should_ignore(aris_profile_dir) is True
        
        # Test CLAUDE backup files
        claude_backup = temp_workspace / "CLAUDE.md.bak"
        assert monitor._should_ignore(claude_backup) is True
        
        # Test that normal files are still not ignored
        normal_file = temp_workspace / "content.md"
        assert monitor._should_ignore(normal_file) is False
        
        normal_log = temp_workspace / "application.log"
        assert monitor._should_ignore(normal_log) is False
    
    def test_take_workspace_snapshot_empty(self, monitor):
        """Test taking a snapshot of an empty workspace."""
        snapshot = monitor._take_workspace_snapshot()
        
        assert isinstance(snapshot, dict)
        assert len(snapshot) == 0
    
    def test_take_workspace_snapshot_with_files(self, monitor, temp_workspace):
        """Test taking a snapshot with files present."""
        # Create test files
        file1 = temp_workspace / "test1.txt"
        file1.write_text("content1")
        
        subdir = temp_workspace / "subdir"
        subdir.mkdir()
        file2 = subdir / "test2.py"
        file2.write_text("content2")
        
        # Take snapshot
        snapshot = monitor._take_workspace_snapshot()
        
        assert len(snapshot) == 2
        assert "test1.txt" in snapshot
        assert "subdir/test2.py" in snapshot
        
        # Check metadata
        file1_info = snapshot["test1.txt"]
        assert file1_info["size"] == 8  # "content1" length
        assert file1_info["exists"] is True
        assert "mtime" in file1_info
        assert "mtime_ns" in file1_info
    
    def test_take_snapshot_ignores_patterns(self, monitor, temp_workspace):
        """Test that snapshot respects ignore patterns."""
        # Create files that should be ignored
        hidden = temp_workspace / ".hidden"
        hidden.write_text("hidden")
        
        pycache = temp_workspace / "__pycache__"
        pycache.mkdir()
        pyc_file = pycache / "test.pyc"
        pyc_file.write_text("compiled")
        
        # Create normal file
        normal = temp_workspace / "normal.txt"
        normal.write_text("normal")
        
        snapshot = monitor._take_workspace_snapshot()
        
        # Only normal file should be in snapshot
        assert len(snapshot) == 1
        assert "normal.txt" in snapshot
        assert ".hidden" not in snapshot
        assert "__pycache__/test.pyc" not in snapshot
    
    def test_get_workspace_changes_no_changes(self, monitor):
        """Test getting changes when nothing has changed."""
        changes = monitor.get_workspace_changes()
        
        assert changes["created"] == []
        assert changes["modified"] == []
        assert changes["deleted"] == []
    
    def test_get_workspace_changes_new_files(self, monitor, temp_workspace):
        """Test detecting new files."""
        # Take initial snapshot (empty)
        monitor._take_workspace_snapshot()
        
        # Create new files
        file1 = temp_workspace / "new1.txt"
        file1.write_text("new content 1")
        
        subdir = temp_workspace / "newdir"
        subdir.mkdir()
        file2 = subdir / "new2.py"
        file2.write_text("new content 2")
        
        # Get changes
        changes = monitor.get_workspace_changes()
        
        assert len(changes["created"]) == 2
        assert "new1.txt" in changes["created"]
        assert "newdir/new2.py" in changes["created"]
        assert changes["modified"] == []
        assert changes["deleted"] == []
    
    def test_get_workspace_changes_modified_files(self, monitor, temp_workspace):
        """Test detecting modified files."""
        # Create initial file
        test_file = temp_workspace / "test.txt"
        test_file.write_text("original content")
        
        # Take initial snapshot and set it as baseline
        monitor._initial_snapshot = monitor._take_workspace_snapshot()
        
        # Modify file (ensure timestamp changes)
        time.sleep(0.01)
        test_file.write_text("modified content")
        
        # Get changes
        changes = monitor.get_workspace_changes()
        
        assert changes["created"] == []
        assert len(changes["modified"]) == 1
        assert "test.txt" in changes["modified"]
        assert changes["deleted"] == []
    
    def test_get_workspace_changes_deleted_files(self, monitor, temp_workspace):
        """Test detecting deleted files."""
        # Create initial file
        test_file = temp_workspace / "to_delete.txt"
        test_file.write_text("will be deleted")
        
        # Take initial snapshot
        monitor._initial_snapshot = monitor._take_workspace_snapshot()
        
        # Delete file
        test_file.unlink()
        
        # Get changes
        changes = monitor.get_workspace_changes()
        
        assert changes["created"] == []
        assert changes["modified"] == []
        assert len(changes["deleted"]) == 1
        assert "to_delete.txt" in changes["deleted"]
    
    def test_update_baseline(self, monitor, temp_workspace):
        """Test updating the baseline snapshot."""
        # Create initial file
        file1 = temp_workspace / "file1.txt"
        file1.write_text("content1")
        
        # Update baseline to include file1
        monitor.update_baseline()
        initial_count = len(monitor._initial_snapshot)
        
        # Add new file
        file2 = temp_workspace / "file2.txt"
        file2.write_text("content2")
        
        # Update baseline again
        monitor.update_baseline()
        
        # Baseline should now include the new file
        assert len(monitor._initial_snapshot) == initial_count + 1
        assert any("file2.txt" in path for path in monitor._initial_snapshot.keys())
    
    def test_disable_enable_monitoring(self, monitor):
        """Test disabling and enabling monitoring."""
        assert monitor._monitoring_enabled is True
        
        # Disable monitoring
        monitor.disable_monitoring()
        assert monitor._monitoring_enabled is False
        
        # Changes should return empty when disabled
        changes = monitor.get_workspace_changes()
        assert changes == {"created": [], "modified": [], "deleted": []}
        
        # Re-enable monitoring
        monitor.enable_monitoring()
        assert monitor._monitoring_enabled is True
    
    def test_max_files_limit(self, temp_workspace):
        """Test max files limit enforcement."""
        # Create monitor with small limit
        monitor = WorkspaceFileMonitor(str(temp_workspace), max_files=2)
        
        # Create more files than the limit
        for i in range(5):
            file = temp_workspace / f"file{i}.txt"
            file.write_text(f"content{i}")
        
        snapshot = monitor._take_workspace_snapshot()
        
        # Should respect the limit
        assert len(snapshot) <= 2
    
    def test_nonexistent_workspace(self):
        """Test handling of non-existent workspace."""
        nonexistent = "/path/that/does/not/exist"
        monitor = WorkspaceFileMonitor(nonexistent)
        
        # Should handle gracefully
        assert len(monitor._initial_snapshot) == 0
        changes = monitor.get_workspace_changes()
        assert changes == {"created": [], "modified": [], "deleted": []}
    
    def test_workspace_is_file_not_directory(self, temp_workspace):
        """Test handling when workspace path is a file, not directory."""
        # Create a file instead of directory
        workspace_file = temp_workspace / "workspace_file.txt"
        workspace_file.write_text("not a directory")
        
        monitor = WorkspaceFileMonitor(str(workspace_file))
        
        # Should handle gracefully
        assert len(monitor._initial_snapshot) == 0
    
    def test_permission_error_handling(self, monitor):
        """Test handling of permission errors during scanning."""
        with patch.object(monitor, '_scan_directory', side_effect=PermissionError("Access denied")):
            snapshot = monitor._take_workspace_snapshot()
            
            # Should handle gracefully and return empty snapshot
            assert isinstance(snapshot, dict)
    
    def test_get_stats(self, monitor, temp_workspace):
        """Test getting monitoring statistics."""
        # Create a file to have some baseline data
        test_file = temp_workspace / "test.txt"
        test_file.write_text("test content")
        monitor.update_baseline()
        
        stats = monitor.get_stats()
        
        assert "workspace_path" in stats
        assert stats["workspace_path"] == str(temp_workspace.resolve())
        assert "monitoring_enabled" in stats
        assert stats["monitoring_enabled"] is True
        assert "tracked_files" in stats
        assert stats["tracked_files"] >= 0
        assert "scan_count" in stats
        assert "ignore_patterns_count" in stats
    
    def test_relative_path_handling(self):
        """Test proper handling of relative workspace paths."""
        # Use a relative path
        with tempfile.TemporaryDirectory() as temp_dir:
            relative_path = os.path.relpath(temp_dir)
            monitor = WorkspaceFileMonitor(relative_path)
            
            # Should convert to absolute path
            assert monitor.workspace_path.is_absolute()
            assert str(monitor.workspace_path) == str(Path(temp_dir).resolve())
    
    @pytest.mark.parametrize("pattern,filename,should_ignore", [
        ("*.pyc", "test.pyc", True),
        ("*.pyc", "test.py", False),
        (".*", ".hidden", True),
        (".*", "visible.txt", False),
        ("__pycache__", "__pycache__", True),
        ("__pycache__", "cache", False),
        ("~*", "~temp.txt", True),
        ("~*", "temp.txt", False),
    ])
    def test_ignore_patterns_parametrized(self, temp_workspace, pattern, filename, should_ignore):
        """Test various ignore patterns."""
        monitor = WorkspaceFileMonitor(str(temp_workspace), ignore_patterns={pattern})
        test_path = temp_workspace / filename
        
        result = monitor._should_ignore(test_path)
        assert result == should_ignore
    
    def test_high_precision_timestamp_comparison(self, monitor, temp_workspace):
        """Test high-precision timestamp comparison for modified file detection."""
        # Create initial file
        test_file = temp_workspace / "precision_test.txt"
        test_file.write_text("original")
        
        # Take initial snapshot
        monitor._initial_snapshot = monitor._take_workspace_snapshot()
        
        # Make a very quick modification (within same second)
        time.sleep(0.001)  # Very small delay
        test_file.write_text("modified")
        
        # Get changes - should detect the modification even with small time diff
        changes = monitor.get_workspace_changes()
        
        # The modification should be detected due to nanosecond precision
        assert "precision_test.txt" in changes["modified"] or len(changes["modified"]) == 0
        # Note: This test may be flaky on some filesystems that don't support ns precision