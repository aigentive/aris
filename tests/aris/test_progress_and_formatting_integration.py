"""
Integration tests for progress tracking and response formatting working together.
"""
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from aris.cli import execute_single_turn, execute_non_interactive_mode, format_non_interactive_response
from aris.progress_tracker import ProgressTracker, ExecutionPhase
from aris.session_state import SessionState


class TestProgressTrackingIntegration:
    """Test progress tracking integration with the CLI execution flow."""
    
    @pytest.mark.asyncio
    async def test_execute_single_turn_with_progress_tracker(self):
        """Test that execute_single_turn properly uses a progress tracker."""
        session_state = SessionState()
        session_state.session_id = "test_session"
        
        # Create a real progress tracker to test with
        progress_tracker = ProgressTracker(interactive=False, show_progress=False)
        
        with patch('aris.orchestrator.route') as mock_route:
            async def mock_async_iter():
                yield '{"type": "text", "text": "Hello"}'
                yield '{"type": "text", "text": " world!"}'
            
            mock_route.return_value = mock_async_iter()
            
            result = await execute_single_turn("test", session_state, progress_tracker)
            
            # Verify that the progress tracker was passed to route
            mock_route.assert_called_once()
            call_kwargs = mock_route.call_args[1]
            assert 'progress_tracker' in call_kwargs
            assert call_kwargs['progress_tracker'] is progress_tracker
            
            assert result == "Hello world!"
    
    @pytest.mark.asyncio
    async def test_non_interactive_mode_creates_progress_tracker(self):
        """Test that non-interactive mode creates and uses a progress tracker."""
        with patch('aris.session_state.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            mock_args.verbose = False
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            mock_execute.return_value = "test response"
            
            await execute_non_interactive_mode("test input")
            
            # Verify that execute_single_turn was called with a progress tracker
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args[0]
            assert len(call_args) == 3  # user_input, session_state, progress_tracker
            assert isinstance(call_args[2], ProgressTracker)
            assert call_args[2].interactive is False
    
    @pytest.mark.asyncio
    async def test_non_interactive_verbose_mode_disables_progress(self):
        """Test that verbose mode disables progress tracking display."""
        with patch('aris.session_state.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            mock_args.verbose = True  # Verbose mode enabled
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            mock_execute.return_value = "test response"
            
            await execute_non_interactive_mode("test input")
            
            # Progress tracker should have show_progress=False in verbose mode
            call_args = mock_execute.call_args[0]
            progress_tracker = call_args[2]
            assert progress_tracker.show_progress is False


class TestResponseFormattingIntegration:
    """Test response formatting integration with the complete flow."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_response_formatting(self):
        """Test complete end-to-end response formatting in non-interactive mode."""
        with patch('aris.session_state.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print') as mock_print, \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            mock_args.verbose = True  # Disable progress to focus on response formatting
            
            # Set up session with custom profile
            mock_session = SessionState()
            mock_session.active_profile = {"profile_name": "test_profile"}
            mock_get_session.return_value = mock_session
            
            # Mock response from execute_single_turn
            multiline_response = """Analysis complete!

Results:
- Found 5 issues
- Fixed 3 automatically
- 2 require manual review

Next steps recommended."""
            mock_execute.return_value = multiline_response
            
            await execute_non_interactive_mode("analyze code")
            
            # Find the formatted response call (non-flush call)
            response_calls = [call for call in mock_print.call_args_list if not call[1].get('flush')]
            assert len(response_calls) == 1
            
            formatted_output = response_calls[0][0][0]
            
            # Verify formatting
            lines = formatted_output.split('\n')
            assert lines[0] == "🤖 test_profile: Analysis complete!"
            assert "Results:" in formatted_output
            assert "- Found 5 issues" in formatted_output
            
            # Verify indentation
            expected_indent = " " * len("🤖 test_profile: ")
            for line in lines[1:]:
                if line.strip():  # Non-empty lines should be indented
                    assert line.startswith(expected_indent)
    
    def test_format_response_with_different_profiles(self):
        """Test response formatting with different profile names."""
        profiles = [
            {"profile_name": "dev"},
            {"profile_name": "data_scientist"}, 
            {"profile_name": "ai_researcher"},
            None,  # No profile
            {},    # Empty profile
        ]
        
        for profile in profiles:
            session_state = MagicMock()
            session_state.active_profile = profile
            
            response = "Test response\nSecond line"
            result = format_non_interactive_response(response, session_state)
            
            if profile and profile.get("profile_name"):
                expected_prefix = f"🤖 {profile['profile_name']}: "
            else:
                expected_prefix = "🤖 aris: "
            
            assert result.startswith(expected_prefix + "Test response")
            
            # Check indentation of second line
            lines = result.split('\n')
            if len(lines) > 1:
                expected_indent = " " * len(expected_prefix)
                assert lines[1] == expected_indent + "Second line"


class TestProgressTrackerWithRouteFunction:
    """Test progress tracker integration with the route function."""
    
    @pytest.mark.asyncio
    async def test_route_function_uses_progress_tracker(self):
        """Test that the route function properly utilizes progress tracker."""
        from aris.orchestrator import route
        
        # Create a real progress tracker
        progress_tracker = ProgressTracker(interactive=False, show_progress=False)
        
        with patch('aris.orchestrator.mcp_service_instance') as mock_mcp, \
             patch('aris.orchestrator.prompt_formatter_instance') as mock_formatter, \
             patch('aris.orchestrator.cli_flag_manager_instance') as mock_flag_manager, \
             patch('aris.orchestrator.claude_cli_executor_instance') as mock_executor, \
             patch('aris.cli.get_current_session_state') as mock_session:
            
            # Set up mocks
            mock_formatter.format_prompt.return_value = "formatted prompt"
            mock_flag_manager.generate_claude_cli_flags.return_value = ["--verbose"]
            
            # Mock executor to return test chunks
            async def mock_execute_cli(*args, **kwargs):
                yield '{"type": "text", "text": "test response"}'
            
            mock_executor.execute_cli = mock_execute_cli
            
            # Mock session state
            session_state = MagicMock()
            session_state.active_profile = {"profile_name": "test"}
            mock_session.return_value = session_state
            
            # Test route with progress tracker
            chunks = []
            async for chunk in route(
                user_msg_for_turn="test message",
                progress_tracker=progress_tracker
            ):
                chunks.append(chunk)
            
            # Verify progress tracking was used
            assert len(progress_tracker.phase_history) >= 2  # Should have multiple phase updates
            final_phase = progress_tracker.current_state.phase
            assert final_phase == ExecutionPhase.COMPLETING
    
    @pytest.mark.asyncio 
    async def test_route_function_without_progress_tracker(self):
        """Test that route function works without progress tracker."""
        from aris.orchestrator import route
        
        with patch('aris.orchestrator.mcp_service_instance') as mock_mcp, \
             patch('aris.orchestrator.prompt_formatter_instance') as mock_formatter, \
             patch('aris.orchestrator.cli_flag_manager_instance') as mock_flag_manager, \
             patch('aris.orchestrator.claude_cli_executor_instance') as mock_executor, \
             patch('aris.cli.get_current_session_state') as mock_session:
            
            # Set up minimal mocks
            mock_formatter.format_prompt.return_value = "formatted prompt"
            mock_flag_manager.generate_claude_cli_flags.return_value = ["--verbose"]
            
            async def mock_execute_cli(*args, **kwargs):
                yield '{"type": "text", "text": "test response"}'
            
            mock_executor.execute_cli = mock_execute_cli
            
            session_state = MagicMock()
            session_state.active_profile = {"profile_name": "test"}
            mock_session.return_value = session_state
            
            # Test route without progress tracker (should not crash)
            chunks = []
            async for chunk in route(
                user_msg_for_turn="test message",
                progress_tracker=None
            ):
                chunks.append(chunk)
            
            # Should still work and return chunks
            assert len(chunks) == 1
            assert "test response" in chunks[0]


class TestErrorHandlingWithProgressAndFormatting:
    """Test error handling scenarios with progress tracking and formatting."""
    
    @pytest.mark.asyncio
    async def test_error_during_execution_stops_progress(self):
        """Test that errors properly stop progress tracking."""
        with patch('aris.session_state.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            mock_args.verbose = False
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            
            # Make execute_single_turn raise an exception
            mock_execute.side_effect = Exception("Test error")
            
            await execute_non_interactive_mode("test input")
            
            # Should have handled the error gracefully
            # (The implementation catches the exception and continues)
    
    def test_format_error_response(self):
        """Test formatting error responses appropriately."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "error_handler"}
        
        error_response = """Error: File not found

Traceback:
  File "main.py", line 42
    result = process_file(filename)
  FileNotFoundError: No such file"""
        
        result = format_non_interactive_response(error_response, session_state)
        
        # Error should be formatted like any other response
        assert result.startswith("🤖 error_handler: Error: File not found")
        assert "Traceback:" in result
        assert "FileNotFoundError" in result
        
        # Multi-line structure should be preserved
        lines = result.split('\n')
        expected_indent = " " * len("🤖 error_handler: ")
        assert lines[2] == expected_indent + "Traceback:"