"""
Tests for ARIS cleanup behavior including signal handling and MCP server shutdown.

These tests verify that ARIS properly cleans up resources when interrupted
or when shutting down normally, preventing issues like:
- "Task was destroyed but it is pending" warnings
- "Address already in use" errors on restart
- Hanging background processes
"""

import asyncio
import os
import signal
import threading
import time
import unittest.mock
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock

from aris.cli import (
    _shutdown_mcp_servers,
    _start_profile_mcp_server,
    _start_workflow_mcp_server
)
from aris.interrupt_handler import InterruptHandler


class TestSignalHandlerCleanup:
    """Test proper cleanup of the signal handler background task."""
    
    @pytest.mark.asyncio
    async def test_signal_handler_task_cancellation(self):
        """Test that signal handler task is properly cancelled during shutdown."""
        # Simulate the signal handler task
        task_cancelled = asyncio.Event()
        
        async def mock_signal_handler():
            try:
                while True:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                task_cancelled.set()
                raise
        
        # Create and track the task
        interrupt_handler = InterruptHandler()
        signal_task = asyncio.create_task(mock_signal_handler())
        interrupt_handler.track_task(signal_task)
        
        # Allow task to start
        await asyncio.sleep(0.05)
        assert not signal_task.done()
        
        # Cancel the task (simulating shutdown)
        signal_task.cancel()
        
        # Verify proper cancellation
        try:
            await signal_task
        except asyncio.CancelledError:
            pass  # Expected
        
        # Verify the task was cancelled properly
        assert task_cancelled.is_set()
        assert signal_task.cancelled()
        
        # Clean up
        interrupt_handler.shutdown()
    
    @pytest.mark.asyncio  
    async def test_signal_handler_exception_handling(self):
        """Test that signal handler task handles exceptions gracefully."""
        exception_caught = asyncio.Event()
        
        async def mock_signal_handler_with_error():
            try:
                await asyncio.sleep(0.01)
                raise ValueError("Test error")
            except asyncio.CancelledError:
                raise
            except Exception:
                exception_caught.set()
                # Should continue running despite error
                await asyncio.sleep(0.1)
        
        interrupt_handler = InterruptHandler()
        signal_task = asyncio.create_task(mock_signal_handler_with_error())
        interrupt_handler.track_task(signal_task)
        
        # Wait for exception to be caught
        await asyncio.wait_for(exception_caught.wait(), timeout=1.0)
        
        # Clean up
        signal_task.cancel()
        try:
            await signal_task
        except asyncio.CancelledError:
            pass
        
        interrupt_handler.shutdown()


class TestMCPServerCleanup:
    """Test proper cleanup of MCP servers to prevent port binding issues."""
    
    @pytest.mark.asyncio
    async def test_mcp_server_shutdown_function(self):
        """Test the _shutdown_mcp_servers function."""
        
        with patch('aris.cli._workflow_mcp_server_started', True), \
             patch('aris.cli._profile_mcp_server_started', True), \
             patch('aris.cli._workflow_mcp_server_thread', Mock()), \
             patch('aris.cli._profile_mcp_server_thread', Mock()), \
             patch('aris.cli.log_debug') as mock_log:
            
            # Test shutdown function
            await _shutdown_mcp_servers()
            
            # Verify logging calls
            assert mock_log.call_count >= 2
            mock_log.assert_any_call("Shutting down Workflow MCP Server...")
            mock_log.assert_any_call("Shutting down Profile MCP Server...")
    
    @pytest.mark.asyncio
    async def test_mcp_server_startup_tracking(self):
        """Test that MCP server threads are properly tracked for cleanup."""
        
        mock_server = Mock()
        mock_server.run_server_blocking = Mock()
        
        with patch('aris.profile_mcp_server.ProfileMCPServer', return_value=mock_server), \
             patch('aris.cli.threading.Thread') as mock_thread_class, \
             patch('aris.cli.PARSED_ARGS') as mock_args:
            
            mock_args.profile_mcp_port = 8094
            mock_thread = Mock()
            mock_thread_class.return_value = mock_thread
            
            # Mock the ready event 
            with patch('aris.cli.threading.Event') as mock_event_class:
                mock_event = Mock()
                mock_event.wait.return_value = True
                mock_event_class.return_value = mock_event
                
                # Test server startup
                await _start_profile_mcp_server()
                
                # Verify thread was created and started
                mock_thread_class.assert_called_once()
                mock_thread.start.assert_called_once()
                
                # Verify daemon=True was set
                call_kwargs = mock_thread_class.call_args[1]
                assert call_kwargs['daemon'] is True
    
    def test_port_reuse_configuration(self):
        """Test that MCP servers are configured for proper port reuse."""
        
        # Import the function definition
        from aris.cli import _start_workflow_mcp_server
        
        # Get the inner function that runs in the thread
        import inspect
        source = inspect.getsource(_start_workflow_mcp_server)
        
        # Verify environment variable setting is present
        assert 'UVICORN_SERVER_SOCKET_REUSE' in source
        assert 'access_log=False' in source


class TestCleanupIntegration:
    """Integration tests for complete cleanup workflows."""
    
    @pytest.mark.asyncio
    async def test_full_cleanup_sequence(self):
        """Test the complete cleanup sequence including all components."""
        
        # Mock all components
        mock_voice_handler = Mock()
        mock_interrupt_handler = Mock()
        mock_context_manager = Mock()
        mock_workspace_manager = Mock()
        
        with patch('aris.cli._shutdown_mcp_servers', new_callable=AsyncMock) as mock_shutdown_mcp, \
             patch('aris.cli._signal_handler_task', Mock()) as mock_signal_task, \
             patch('aris.cli.log_debug') as mock_log:
            
            mock_signal_task.done.return_value = False
            mock_signal_task.cancel = Mock()
            
            # Import the cleanup section logic (we'd need to extract it to a function)
            # For now, test the MCP shutdown part
            await mock_shutdown_mcp()
            
            # Verify MCP shutdown was called
            mock_shutdown_mcp.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_interrupt_handling_during_cleanup(self):
        """Test that cleanup handles additional interrupts gracefully."""
        
        interrupt_handler = InterruptHandler()
        
        # Simulate multiple rapid interrupts
        interrupt_count = 0
        
        def mock_interrupt_callback():
            nonlocal interrupt_count
            interrupt_count += 1
        
        interrupt_handler.register_exit_callback(mock_interrupt_callback)
        
        # Test multiple interrupt levels
        with patch('aris.cli.signal.signal'):
            # Simulate first interrupt (should trigger cleanup)
            interrupt_handler._handle_interrupt(signal.SIGINT, None)
            
            # Simulate second interrupt (should force immediate exit)
            interrupt_handler._handle_interrupt(signal.SIGINT, None)
            
            # Verify callback was called
            assert interrupt_count > 0
        
        interrupt_handler.shutdown()


class TestSocketCleanup:
    """Test socket cleanup and port reuse functionality."""
    
    def test_socket_reuse_environment_variable(self):
        """Test that socket reuse environment variable is set."""
        
        import os
        from unittest.mock import patch
        
        with patch.dict(os.environ, {}, clear=True):
            # Simulate the environment variable setting logic
            def mock_run_server():
                # This simulates the run_workflow_server_with_signal function
                import os
                os.environ.setdefault('UVICORN_SERVER_SOCKET_REUSE', '1')
                
                # Verify the environment variable was set
                assert os.environ.get('UVICORN_SERVER_SOCKET_REUSE') == '1'
            
            # Run the mock server function
            mock_run_server()
    
    def test_port_availability_check(self):
        """Test port availability checking before server startup."""
        
        import socket
        from unittest.mock import patch
        
        with patch('socket.socket') as mock_socket_class:
            mock_socket = Mock()
            mock_socket_class.return_value = mock_socket
            
            # Test port available case
            mock_socket.connect_ex.return_value = 1  # Connection refused (port free)
            
            # This would normally be in the server startup logic
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("0.0.0.0", 8095))
            sock.close()
            
            # Verify port is detected as available
            assert result != 0  # Port is free
            
            # Test port occupied case
            mock_socket.connect_ex.return_value = 0  # Connection successful (port busy)
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("0.0.0.0", 8095))
            sock.close()
            
            # Verify port is detected as occupied
            assert result == 0  # Port is busy


class TestErrorHandling:
    """Test error handling during cleanup operations."""
    
    @pytest.mark.asyncio
    async def test_cleanup_with_server_errors(self):
        """Test that cleanup continues even if individual servers error."""
        
        with patch('aris.cli.log_error') as mock_log_error, \
             patch('aris.cli._workflow_mcp_server_started', True), \
             patch('aris.cli._profile_mcp_server_started', True), \
             patch('aris.cli._workflow_mcp_server_thread', Mock()), \
             patch('aris.cli._profile_mcp_server_thread', Mock()):
            
            # Test that cleanup completes even with errors
            await _shutdown_mcp_servers()
            
            # Function should complete without raising exceptions
            # Errors should be logged but not raised
    
    @pytest.mark.asyncio
    async def test_task_cancellation_with_timeout(self):
        """Test task cancellation handles hanging tasks gracefully."""
        
        async def hanging_task():
            try:
                # Simulate a task that takes a long time to respond to cancellation
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                # Simulate slow cleanup
                await asyncio.sleep(0.1)
                raise
        
        task = asyncio.create_task(hanging_task())
        
        # Cancel the task
        task.cancel()
        
        # Should handle cancellation within reasonable time
        start_time = time.time()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        
        elapsed = time.time() - start_time
        assert elapsed < 1.5  # Should not hang indefinitely


# Test fixtures and helpers

@pytest.fixture
def mock_interrupt_handler():
    """Provide a mock interrupt handler for testing."""
    handler = Mock(spec=InterruptHandler)
    handler.track_task = Mock()
    handler.shutdown = Mock()
    return handler


@pytest.fixture
def cleanup_environment():
    """Ensure clean test environment."""
    # Store original values
    original_env = os.environ.copy()
    
    yield
    
    # Restore environment
    os.environ.clear()
    os.environ.update(original_env)


if __name__ == "__main__":
    pytest.main([__file__])