"""
Integration tests for workspace functionality across ARIS components.
"""
import os
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock

from aris.workspace_manager import workspace_manager
from aris.session_state import SessionState
from aris.profile_manager import profile_manager
from aris.prompt_formatter import PromptFormatter


class TestWorkspaceIntegration:
    """Test workspace integration across ARIS components."""
    
    def setup_method(self):
        """Setup test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        
        # Create a test workspace
        self.workspace_path = os.path.join(self.test_dir, "test_workspace")
        os.makedirs(self.workspace_path)
        
        # Reset workspace manager state
        workspace_manager.original_cwd = None
        workspace_manager.current_workspace = None
    
    def teardown_method(self):
        """Clean up test environment."""
        # Restore original directory
        os.chdir(self.original_cwd)
        workspace_manager.restore_original_directory()
        
        # Clean up test directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_workspace_variable_injection(self):
        """Test that workspace variables are properly injected into profiles."""
        # Create test profile data
        profile_data = {
            'profile_name': 'test_profile',
            'system_prompt': 'You are in workspace: {{workspace}}',
            'variables': {'existing_var': 'existing_value'}
        }
        
        # Create workspace variables
        workspace_variables = {
            'workspace': '/test/workspace',
            'workspace_name': 'workspace'
        }
        
        # Test variable injection
        result = profile_manager._inject_workspace_variables(profile_data, workspace_variables)
        
        # Check that workspace variables were added
        assert 'workspace' in result['variables']
        assert 'workspace_name' in result['variables']
        assert result['variables']['workspace'] == '/test/workspace'
        assert result['variables']['workspace_name'] == 'workspace'
        
        # Check that existing variables are preserved
        assert result['variables']['existing_var'] == 'existing_value'
    
    def test_session_state_workspace_tracking(self):
        """Test that session state properly tracks workspace information."""
        session_state = SessionState()
        
        # Initially no workspace
        assert session_state.workspace_path is None
        assert session_state.original_cwd is None
        
        # Set workspace information
        session_state.workspace_path = self.workspace_path
        session_state.original_cwd = self.original_cwd
        
        assert session_state.workspace_path == self.workspace_path
        assert session_state.original_cwd == self.original_cwd
    
    def test_prompt_formatter_workspace_enhancement(self):
        """Test that prompt formatter adds workspace context."""
        formatter = PromptFormatter()
        
        base_prompt = "You are a helpful assistant."
        workspace_path = "/test/workspace"
        original_cwd = "/different/path"
        
        # Test with workspace context
        result, _ = formatter.prepare_system_prompt(
            base_prompt,
            workspace_path=workspace_path,
            original_cwd=original_cwd
        )
        
        # Should contain workspace information
        assert "## Workspace Information" in result
        assert workspace_path in result
        assert "Use this workspace for reading previous work" in result
    
    def test_prompt_formatter_no_workspace_enhancement(self):
        """Test that prompt formatter doesn't add workspace context when not needed."""
        formatter = PromptFormatter()
        
        base_prompt = "You are a helpful assistant."
        
        # Test without workspace (should not add context)
        result, _ = formatter.prepare_system_prompt(base_prompt)
        
        # Should not contain workspace information
        assert "## Workspace Information" not in result
    
    def test_workspace_variable_substitution_in_prompt(self):
        """Test that workspace variables are properly substituted in system prompts."""
        formatter = PromptFormatter()
        
        base_prompt = "You are working in {{workspace}} with project {{workspace_name}}."
        workspace_path = "/test/my-project"
        
        template_variables = {
            'workspace': workspace_path,
            'workspace_name': 'my-project'
        }
        
        result, _ = formatter.prepare_system_prompt(
            base_prompt,
            template_variables=template_variables,
            workspace_path=workspace_path
        )
        
        # Check variable substitution
        assert "You are working in /test/my-project with project my-project." in result
        assert "{{workspace}}" not in result
        assert "{{workspace_name}}" not in result
    
    def test_end_to_end_workspace_flow(self):
        """Test complete workspace flow from setup to cleanup."""
        # 1. Setup workspace
        workspace_arg = "test_workspace"
        resolved_path = workspace_manager.resolve_workspace_path(workspace_arg)
        original_cwd = workspace_manager.setup_workspace(resolved_path)
        
        assert os.getcwd() == resolved_path
        assert os.path.exists(resolved_path)
        
        # 2. Create session state with workspace
        session_state = SessionState()
        session_state.workspace_path = resolved_path
        session_state.original_cwd = original_cwd
        
        # 3. Generate workspace variables
        workspace_variables = workspace_manager.get_workspace_variables(resolved_path)
        expected_variables = {
            'workspace': resolved_path,
            'workspace_name': 'test_workspace'
        }
        assert workspace_variables == expected_variables
        
        # 4. Test profile with workspace variables
        profile_data = {
            'profile_name': 'test_profile',
            'system_prompt': 'Working in {{workspace}}',
            'variables': {}
        }
        
        enhanced_profile = profile_manager._inject_workspace_variables(
            profile_data, workspace_variables
        )
        
        assert enhanced_profile['variables']['workspace'] == resolved_path
        assert enhanced_profile['variables']['workspace_name'] == 'test_workspace'
        
        # 5. Test system prompt processing
        formatter = PromptFormatter()
        result, _ = formatter.prepare_system_prompt(
            enhanced_profile['system_prompt'],
            template_variables=enhanced_profile['variables'],
            workspace_path=resolved_path,
            original_cwd=self.original_cwd
        )
        
        assert f"Working in {resolved_path}" in result
        # Now workspace context should be added since workspace_path != original_cwd
        assert "## Workspace Information" in result
        
        # 6. Cleanup
        workspace_manager.restore_original_directory()
        assert os.getcwd() == self.original_cwd
    
    @patch('aris.workspace_manager.log_error')
    def test_workspace_setup_error_handling(self, mock_log_error):
        """Test error handling in workspace setup."""
        # Test with invalid workspace path
        invalid_path = "/invalid/\x00/path"
        
        with pytest.raises(OSError):
            workspace_manager.setup_workspace(invalid_path)
        
        # Ensure error was logged
        mock_log_error.assert_called()
    
    def test_workspace_variables_override_existing(self):
        """Test that workspace variables override existing profile variables."""
        profile_data = {
            'profile_name': 'test_profile',
            'variables': {
                'workspace': 'old_workspace',
                'other_var': 'keep_this'
            }
        }
        
        workspace_variables = {
            'workspace': 'new_workspace',
            'workspace_name': 'new_name'
        }
        
        result = profile_manager._inject_workspace_variables(profile_data, workspace_variables)
        
        # Workspace variables should override
        assert result['variables']['workspace'] == 'new_workspace'
        assert result['variables']['workspace_name'] == 'new_name'
        
        # Other variables should be preserved
        assert result['variables']['other_var'] == 'keep_this'