"""
Tests for CTRL+C (KeyboardInterrupt) handling in ARIS.
"""
import pytest
import asyncio
import signal
import os
from unittest.mock import Mock, patch, AsyncMock

from aris.claude_cli_executor import ClaudeCLIExecutor
from aris.interaction_handler import handle_route_chunks, TurnCancelledError
from aris.session_state import SessionState


class TestClaudeCLIExecutorSignalHandling:
    """Test Claude CLI executor signal handling functionality."""
    
    def test_executor_initialization(self):
        """Test that executor initializes with process tracking."""
        executor = ClaudeCLIExecutor("fake_claude_path")
        assert executor.claude_cli_path == "fake_claude_path"
        assert executor.current_process is None
    
    @pytest.mark.asyncio
    async def test_process_tracking_during_execution(self):
        """Test that process is tracked during execution."""
        executor = ClaudeCLIExecutor("fake_claude_path")
        
        # Mock the subprocess creation
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        mock_process.stdout = None
        mock_process.stderr = AsyncMock()
        mock_process.stderr.read.return_value = b""
        mock_process.wait = AsyncMock(return_value=0)
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            # Start execution (should complete immediately with no stdout)
            result_chunks = []
            async for chunk in executor.execute_cli("test prompt", ["--test-flag"]):
                result_chunks.append(chunk)
            
            # Process should be cleared after execution
            assert executor.current_process is None
    
    def test_terminate_current_process_no_process(self):
        """Test terminating when no process is running."""
        executor = ClaudeCLIExecutor("fake_claude_path")
        
        # Should not raise an exception
        executor.terminate_current_process()
        assert executor.current_process is None
    
    def test_terminate_current_process_with_process(self):
        """Test terminating an active process."""
        executor = ClaudeCLIExecutor("fake_claude_path")
        
        # Mock an active process
        mock_process = Mock()
        mock_process.returncode = None  # Still running
        mock_process.pid = 12345
        mock_process.terminate = Mock()
        
        executor.current_process = mock_process
        executor.terminate_current_process()
        
        # Should have called terminate
        mock_process.terminate.assert_called_once()
        # Process reference should be cleared
        assert executor.current_process is None
    
    def test_terminate_current_process_already_finished(self):
        """Test terminating a process that already finished."""
        executor = ClaudeCLIExecutor("fake_claude_path")
        
        # Mock a finished process
        mock_process = Mock()
        mock_process.returncode = 0  # Already finished
        mock_process.pid = 12345
        
        executor.current_process = mock_process
        executor.terminate_current_process()
        
        # Should not have attempted termination since process is already finished
        # Process reference should be cleared
        assert executor.current_process is None
    
    def test_terminate_process_with_exception(self):
        """Test handling exceptions during process termination."""
        executor = ClaudeCLIExecutor("fake_claude_path")
        
        # Mock a process that raises exception on terminate
        mock_process = Mock()
        mock_process.returncode = None
        mock_process.pid = 12345
        mock_process.terminate.side_effect = ProcessLookupError("Process not found")
        
        executor.current_process = mock_process
        
        # Should not raise exception
        executor.terminate_current_process()
        mock_process.terminate.assert_called_once()
        # Process reference should be cleared
        assert executor.current_process is None
    
    # Note: Force kill test removed as terminate_current_process is now synchronous
    # and doesn't include async wait/kill logic


class TestInteractionHandlerSignalHandling:
    """Test interaction handler signal handling functionality."""
    
    @pytest.mark.asyncio
    async def test_keyboard_interrupt_during_route(self):
        """Test that KeyboardInterrupt during route execution is handled properly."""
        session_state = SessionState()
        
        # Mock the route function to raise KeyboardInterrupt
        async def mock_route(*args, **kwargs):
            yield '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Starting..."}]}}'
            # Simulate CTRL+C during execution
            raise KeyboardInterrupt("User interrupted")
        
        # Mock the interrupt handler
        with patch('aris.interaction_handler.get_interrupt_handler') as mock_get_handler:
            mock_interrupt_handler = Mock()
            mock_get_handler.return_value = mock_interrupt_handler
            
            # Mock the orchestrator functions  
            with patch('aris.orchestrator.route', return_value=mock_route()):
                with patch('aris.orchestrator.get_claude_cli_executor') as mock_get_executor:
                    # Mock executor with terminate method
                    mock_executor = Mock()
                    mock_executor.terminate_current_process = AsyncMock()
                    mock_get_executor.return_value = mock_executor
                    
                    # The function should return partial results, not raise
                    session_id, text, spoke = await handle_route_chunks(
                        "test message",
                        session_state,
                        "Test thinking..."
                    )
                    
                    # Should have attempted to terminate the process
                    mock_executor.terminate_current_process.assert_called_once()
                    
                    # Should return partial results
                    assert text == "Starting..."  # The text that was yielded before interrupt
                    assert spoke is True
    
    @pytest.mark.asyncio
    async def test_keyboard_interrupt_no_executor(self):
        """Test KeyboardInterrupt handling when no executor is available."""
        session_state = SessionState()
        
        # Mock the route function to raise KeyboardInterrupt
        async def mock_route(*args, **kwargs):
            raise KeyboardInterrupt("User interrupted")
        
        # Mock the interrupt handler
        with patch('aris.interaction_handler.get_interrupt_handler') as mock_get_handler:
            mock_interrupt_handler = Mock()
            mock_get_handler.return_value = mock_interrupt_handler
            
            # Mock no executor available
            with patch('aris.orchestrator.route', return_value=mock_route()):
                with patch('aris.orchestrator.get_claude_cli_executor', return_value=None):
                    # The function should return empty results, not raise
                    session_id, text, spoke = await handle_route_chunks(
                        "test message",
                        session_state,
                        "Test thinking..."
                    )
                    
                    # Should return empty results since interrupt happened immediately
                    assert text == ""
                    assert spoke is False
    
    @pytest.mark.asyncio
    async def test_turn_cancelled_error_handling(self):
        """Test that TurnCancelledError returns partial results."""
        session_state = SessionState()
        
        # Mock the route function to yield some data then raise KeyboardInterrupt
        async def mock_route(*args, **kwargs):
            yield '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Partial response"}]}}'
            yield '{"session_id": "test_session_123"}'
            raise KeyboardInterrupt("User interrupted")
        
        with patch('aris.orchestrator.route', return_value=mock_route()):
            with patch('aris.orchestrator.get_claude_cli_executor') as mock_get_executor:
                mock_executor = Mock()
                mock_executor.terminate_current_process = AsyncMock()
                mock_get_executor.return_value = mock_executor
                
                # Should catch TurnCancelledError and return partial results
                session_id, text, spoke = await handle_route_chunks(
                    "test message",
                    session_state,
                    "Test thinking..."
                )
                
                # Should return the partial response
                assert session_id == "test_session_123"
                assert text == "Partial response"
                assert spoke is True
    
    @pytest.mark.asyncio
    async def test_text_mode_turn_cancellation(self):
        """Test turn cancellation handling in text mode."""
        from aris.interaction_handler import text_mode_one_turn
        from prompt_toolkit import PromptSession
        
        session_state = SessionState()
        mock_prompt_session = Mock(spec=PromptSession)
        
        # Mock prompt input
        with patch.object(mock_prompt_session, 'prompt_async', return_value="test input"):
            # Mock handle_route_chunks to raise TurnCancelledError
            with patch('aris.interaction_handler.handle_route_chunks', side_effect=TurnCancelledError("Cancelled")):
                action, returned_state = await text_mode_one_turn(mock_prompt_session, session_state)
                
                # Should return 'continue' to stay in CLI, not exit
                assert action == 'continue'
                assert returned_state == session_state


class TestSignalHandlingIntegration:
    """Integration tests for signal handling across components."""
    
    @pytest.mark.asyncio
    async def test_full_ctrl_c_flow(self):
        """Test the complete CTRL+C handling flow."""
        from aris.orchestrator import get_claude_cli_executor, initialize_router_components
        
        # Initialize components for testing
        await initialize_router_components()
        
        # Get the executor instance
        executor = get_claude_cli_executor()
        assert executor is not None
        
        # Mock a long-running process
        mock_process = Mock()
        mock_process.returncode = None
        mock_process.pid = 12345
        mock_process.terminate = Mock()
        mock_process.wait = AsyncMock(return_value=0)
        
        # Simulate process being set during execution
        executor.current_process = mock_process
        
        # Test termination works
        executor.terminate_current_process()
        mock_process.terminate.assert_called_once()
    
    def test_turn_cancelled_error_exception(self):
        """Test TurnCancelledError exception properties."""
        error = TurnCancelledError("Test cancellation")
        assert str(error) == "Test cancellation"
        assert isinstance(error, Exception)


if __name__ == "__main__":
    pytest.main([__file__])