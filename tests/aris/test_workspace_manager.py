"""
Tests for workspace management functionality.
"""
import os
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock

from aris.workspace_manager import WorkspaceManager


class TestWorkspaceManager:
    """Test cases for WorkspaceManager class."""
    
    def setup_method(self):
        """Setup test environment."""
        self.workspace_manager = WorkspaceManager()
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
    
    def teardown_method(self):
        """Clean up test environment."""
        # Restore original directory
        os.chdir(self.original_cwd)
        
        # Clean up test directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_resolve_workspace_path_none(self):
        """Test workspace path resolution with None argument."""
        result = self.workspace_manager.resolve_workspace_path(None)
        assert result == os.getcwd()
    
    def test_resolve_workspace_path_absolute(self):
        """Test workspace path resolution with absolute path."""
        absolute_path = "/tmp/test_workspace"
        result = self.workspace_manager.resolve_workspace_path(absolute_path)
        assert result == absolute_path
    
    def test_resolve_workspace_path_relative(self):
        """Test workspace path resolution with relative path."""
        relative_path = "test_workspace"
        expected = os.path.join(os.getcwd(), relative_path)
        result = self.workspace_manager.resolve_workspace_path(relative_path)
        assert result == expected
    
    def test_setup_workspace_new_directory(self):
        """Test workspace setup with a new directory."""
        workspace_path = os.path.join(self.test_dir, "new_workspace")
        
        original_cwd = self.workspace_manager.setup_workspace(workspace_path)
        
        # Check that directory was created
        assert os.path.exists(workspace_path)
        assert os.path.isdir(workspace_path)
        
        # Check that we changed to the workspace (resolve symlinks for comparison)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_path)
        
        # Check that original directory is returned
        assert original_cwd == self.original_cwd
        
        # Check internal state
        assert self.workspace_manager.original_cwd == self.original_cwd
        assert self.workspace_manager.current_workspace == workspace_path
    
    def test_setup_workspace_existing_directory(self):
        """Test workspace setup with an existing directory."""
        workspace_path = self.test_dir
        
        original_cwd = self.workspace_manager.setup_workspace(workspace_path)
        
        # Check that we changed to the workspace (resolve symlinks for comparison)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_path)
        
        # Check that original directory is returned
        assert original_cwd == self.original_cwd
    
    def test_setup_workspace_permission_error(self):
        """Test workspace setup with permission error."""
        # Try to create workspace in a read-only directory
        with patch('os.makedirs', side_effect=OSError("Permission denied")):
            with pytest.raises(OSError):
                self.workspace_manager.setup_workspace("/root/test_workspace")
    
    def test_restore_original_directory(self):
        """Test restoring original directory."""
        workspace_path = os.path.join(self.test_dir, "test_workspace")
        
        # Setup workspace
        self.workspace_manager.setup_workspace(workspace_path)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_path)
        
        # Restore original directory
        self.workspace_manager.restore_original_directory()
        assert os.getcwd() == self.original_cwd
        assert self.workspace_manager.current_workspace is None
    
    def test_restore_original_directory_no_original(self):
        """Test restoring when no original directory is set."""
        # Should not raise an error
        self.workspace_manager.restore_original_directory()
    
    def test_restore_original_directory_nonexistent(self):
        """Test restoring when original directory no longer exists."""
        self.workspace_manager.original_cwd = "/nonexistent/directory"
        
        # Should not raise an error
        self.workspace_manager.restore_original_directory()
    
    def test_get_workspace_variables(self):
        """Test generating workspace variables."""
        workspace_path = "/home/user/my-project"
        
        variables = self.workspace_manager.get_workspace_variables(workspace_path)
        
        expected = {
            'workspace': workspace_path,
            'workspace_name': 'my-project'
        }
        assert variables == expected
    
    def test_enhance_system_prompt_with_workspace_same_directory(self):
        """Test system prompt enhancement when workspace is same as original."""
        system_prompt = "You are a helpful assistant."
        workspace_path = self.original_cwd
        
        # Set original_cwd to the same path
        self.workspace_manager.original_cwd = self.original_cwd
        
        result = self.workspace_manager.enhance_system_prompt_with_workspace(
            system_prompt, workspace_path
        )
        
        # Should not add workspace context
        assert result == system_prompt
    
    def test_enhance_system_prompt_with_workspace_different_directory(self):
        """Test system prompt enhancement when workspace is different."""
        system_prompt = "You are a helpful assistant."
        workspace_path = "/different/path"
        
        # Set original_cwd to something different
        self.workspace_manager.original_cwd = self.original_cwd
        
        result = self.workspace_manager.enhance_system_prompt_with_workspace(
            system_prompt, workspace_path
        )
        
        # Should add workspace context
        assert "## Workspace Information" in result
        assert workspace_path in result
        assert "Use this workspace for reading previous work" in result
    
    def test_get_current_workspace_info(self):
        """Test getting current workspace information."""
        workspace_path = os.path.join(self.test_dir, "test_workspace")
        
        # Initially should be None
        current, original = self.workspace_manager.get_current_workspace_info()
        assert current is None
        assert original is None
        
        # After setup
        self.workspace_manager.setup_workspace(workspace_path)
        current, original = self.workspace_manager.get_current_workspace_info()
        assert current == workspace_path
        assert original == self.original_cwd