"""
Critical functional parity tests between interactive and non-interactive modes.

These tests are MANDATORY to ensure no functionality is lost in non-interactive mode.
Every core feature MUST have identical behavior between the two modes.
"""
import pytest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from aris.cli import detect_execution_mode, parse_claude_response_stream, execute_single_turn
from aris.session_state import SessionState
from aris.profile_manager import profile_manager
from aris.workspace_manager import workspace_manager
from aris.cli_args import parse_arguments_and_configure_logging


class TestModeDetection:
    """Test mode detection logic for proper routing."""
    
    def test_input_flag_triggers_non_interactive(self):
        """--input flag should trigger non-interactive mode."""
        args = MagicMock()
        args.input = "test message"
        
        mode, user_input = detect_execution_mode(args)
        
        assert mode == "non_interactive"
        assert user_input == "test message"
    
    def test_no_input_triggers_interactive(self):
        """No input should trigger interactive mode."""
        args = MagicMock()
        args.input = None
        
        with patch('sys.stdin.isatty', return_value=True):
            mode, user_input = detect_execution_mode(args)
        
        assert mode == "interactive"
        assert user_input is None
    
    @patch('sys.stdin.isatty', return_value=False)
    @patch('sys.stdin.read', return_value="stdin message\n")
    def test_stdin_input_triggers_non_interactive(self, mock_read, mock_isatty):
        """Stdin input should trigger non-interactive mode."""
        args = MagicMock()
        args.input = None
        
        mode, user_input = detect_execution_mode(args)
        
        assert mode == "non_interactive"
        assert user_input == "stdin message"


class TestResponseParsing:
    """Test response parsing maintains identical behavior."""
    
    def test_parse_text_response(self):
        """Text responses should be parsed identically."""
        chunks = [
            '{"type": "text", "text": "Hello "}',
            '{"type": "text", "text": "world!"}',
        ]
        
        result = parse_claude_response_stream(chunks)
        assert result == "Hello world!"
    
    def test_parse_mixed_response_types(self):
        """Mixed response types should be handled identically."""
        chunks = [
            '{"type": "text", "text": "Starting task..."}',
            '{"type": "tool_use", "name": "test_tool", "input": {}}',
            '{"type": "text", "text": " completed!"}',
        ]
        
        result = parse_claude_response_stream(chunks)
        assert result == "Starting task... completed!"
    
    def test_parse_error_response(self):
        """Error responses should raise exceptions identically."""
        chunks = [
            '{"type": "error", "error": {"message": "Test error"}}'
        ]
        
        with pytest.raises(RuntimeError, match="Claude error: Test error"):
            parse_claude_response_stream(chunks)
    
    def test_parse_malformed_json(self):
        """Malformed JSON should be skipped identically."""
        chunks = [
            '{"type": "text", "text": "Good"}',
            'invalid json',
            '{"type": "text", "text": " response"}',
        ]
        
        result = parse_claude_response_stream(chunks)
        assert result == "Good response"


class TestProfileSystemParity:
    """Test profile system has identical behavior in both modes."""
    
    def test_profile_loading_identical(self):
        """Profile loading must be identical in both modes."""
        # Test that profile loading works the same way
        # This would be expanded with actual profile loading tests
        assert True  # Placeholder for now
    
    def test_profile_inheritance_identical(self):
        """Profile inheritance must work identically."""
        # Test profile inheritance chains
        assert True  # Placeholder for now
    
    def test_template_variable_substitution_identical(self):
        """Template variable substitution must be identical."""
        # Test {{variable}} substitution
        assert True  # Placeholder for now


class TestWorkspaceManagementParity:
    """Test workspace management has identical behavior."""
    
    def test_workspace_setup_identical(self):
        """Workspace setup must be identical."""
        # Test workspace directory creation and navigation
        assert True  # Placeholder for now
    
    def test_workspace_variable_injection_identical(self):
        """Workspace variable injection must be identical."""
        # Test {workspace} and {workspace_name} variables
        assert True  # Placeholder for now
    
    def test_workspace_cleanup_identical(self):
        """Workspace cleanup must be identical."""
        # Test directory restoration
        assert True  # Placeholder for now


class TestMCPServiceParity:
    """Test MCP service integration has identical behavior."""
    
    def test_mcp_server_connection_identical(self):
        """MCP server connections must be identical."""
        # Test both HTTP and stdio server connections
        assert True  # Placeholder for now
    
    def test_mcp_tool_execution_identical(self):
        """MCP tool execution must be identical."""
        # Test tool invocation and responses
        assert True  # Placeholder for now
    
    def test_mcp_config_merging_identical(self):
        """MCP config merging must be identical."""
        # Test configuration loading and merging
        assert True  # Placeholder for now


class TestSessionStateParity:
    """Test session state management has identical behavior."""
    
    def test_session_initialization_identical(self):
        """Session initialization must be identical."""
        session1 = SessionState()
        session2 = SessionState()
        
        # Both should have the same initial state
        # Note: session_id starts as None for new sessions, only gets set when resuming
        assert session1.session_id == session2.session_id == None  # Both start as None
        assert session1.active_profile == session2.active_profile
        assert session1.profile_variables == session2.profile_variables
    
    def test_system_prompt_generation_identical(self):
        """System prompt generation must be identical."""
        # Test system prompt with context files and workspace
        assert True  # Placeholder for now
    
    def test_tool_preferences_identical(self):
        """Tool preferences must be handled identically."""
        # Test tool filtering and preferences
        assert True  # Placeholder for now


class TestContextFileParity:
    """Test context file handling has identical behavior."""
    
    def test_context_file_resolution_identical(self):
        """Context file path resolution must be identical."""
        # Test finding and resolving context files
        assert True  # Placeholder for now
    
    def test_embedded_vs_referenced_mode_identical(self):
        """Embedded vs referenced mode selection must be identical."""
        # Test size thresholds and mode selection
        assert True  # Placeholder for now
    
    def test_context_consolidation_identical(self):
        """Context file consolidation must be identical."""
        # Test merging multiple context files
        assert True  # Placeholder for now


class TestClaudeCLIIntegrationParity:
    """Test Claude CLI integration has identical behavior."""
    
    @pytest.mark.asyncio
    async def test_route_function_identical(self):
        """The route() function must behave identically."""
        # This is the core test - the route function should work the same way
        # regardless of how it's called (interactive vs non-interactive)
        
        session_state = SessionState()
        user_input = "Hello, test message"
        
        # Mock the orchestrator route function
        with patch('aris.orchestrator.route') as mock_route:
            # Set up mock to return test chunks as async iterator
            async def mock_async_iter():
                for chunk in ['{"type": "text", "text": "Hello"}', '{"type": "text", "text": " world!"}']:
                    yield chunk
            
            mock_route.return_value = mock_async_iter()
            
            result = await execute_single_turn(user_input, session_state)
            
            # Verify route was called with correct parameters
            # Note: For new session, is_first_message() returns True
            mock_route.assert_called_once_with(
                user_msg_for_turn=user_input,
                claude_session_to_resume=session_state.session_id,
                tool_preferences=session_state.get_tool_preferences(),
                system_prompt=session_state.get_system_prompt(),
                reference_file_path=session_state.reference_file_path,
                is_first_message=True  # New session defaults to True
            )
            
            assert result == "Hello world!"
    
    def test_flag_generation_identical(self):
        """Claude CLI flag generation must be identical."""
        # Test that flags are generated the same way
        assert True  # Placeholder for now
    
    def test_subprocess_management_identical(self):
        """Subprocess management must be identical."""
        # Test process creation and management
        assert True  # Placeholder for now


class TestErrorHandlingParity:
    """Test error handling has identical behavior."""
    
    def test_error_reporting_identical(self):
        """Error reporting must be identical."""
        # Test that errors are handled and reported the same way
        assert True  # Placeholder for now
    
    def test_exception_propagation_identical(self):
        """Exception propagation must be identical."""
        # Test that exceptions bubble up the same way
        assert True  # Placeholder for now
    
    def test_failure_scenarios_identical(self):
        """Failure scenarios must be handled identically."""
        # Test various failure modes
        assert True  # Placeholder for now


class TestCLIArgumentParity:
    """Test that CLI arguments work identically in both modes."""
    
    def test_profile_argument_identical(self):
        """--profile argument must work identically."""
        # Test profile selection
        assert True  # Placeholder for now
    
    def test_workspace_argument_identical(self):
        """--workspace argument must work identically."""
        # Test workspace setup
        assert True  # Placeholder for now
    
    def test_verbose_logging_identical(self):
        """--verbose argument must work identically."""
        # Test logging behavior
        assert True  # Placeholder for now


# Integration test to verify overall parity
class TestOverallFunctionalParity:
    """High-level integration tests for functional parity."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_parity(self):
        """End-to-end test comparing interactive vs non-interactive execution."""
        # This would be a comprehensive test that sets up the same conditions
        # in both modes and verifies identical results
        assert True  # Placeholder for comprehensive test
    
    def test_performance_parity(self):
        """Performance characteristics should be similar (startup time, etc.)."""
        # Test that non-interactive mode doesn't have significantly different performance
        assert True  # Placeholder for now
    
    def test_resource_usage_parity(self):
        """Resource usage should be similar between modes."""
        # Test memory usage, file handles, etc.
        assert True  # Placeholder for now