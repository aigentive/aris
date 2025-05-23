"""
Tests for the multi-level CTRL+C interrupt handler.

This test suite covers:
1. Basic interrupt handler functionality
2. Context switching and callback registration
3. Multi-level interrupt counting
4. TTS interruption scenarios
5. STT interruption scenarios
6. Claude CLI interruption scenarios
7. Application exit scenarios
"""

import asyncio
import signal
import time
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from aris.interrupt_handler import (
    InterruptHandler, 
    InterruptContext, 
    get_interrupt_handler,
    set_execution_context,
    track_async_task
)


class TestInterruptHandler:
    """Test suite for the InterruptHandler class."""
    
    def test_initialization(self):
        """Test interrupt handler initialization."""
        handler = InterruptHandler()
        
        assert handler.current_context == InterruptContext.IDLE
        assert handler.interrupt_count == 0
        assert handler.last_interrupt_time == 0
        assert handler.interrupt_reset_timeout == 2.0
        assert handler.tts_interrupt_callback is None
        assert handler.stt_interrupt_callback is None
        assert handler.claude_interrupt_callback is None
        assert handler.exit_callback is None
    
    def test_signal_handler_installation(self):
        """Test that signal handler is properly installed."""
        handler = InterruptHandler()
        
        with patch('signal.signal') as mock_signal, patch('signal.getsignal'):
            handler.initialize()
            mock_signal.assert_called_once_with(signal.SIGINT, handler._handle_interrupt)
    
    def test_signal_handler_restoration(self):
        """Test that original signal handler is restored on shutdown."""
        handler = InterruptHandler()
        original_handler = signal.getsignal(signal.SIGINT)
        
        with patch('signal.signal') as mock_signal:
            handler._original_sigint_handler = original_handler
            handler.shutdown()
            mock_signal.assert_called_once_with(signal.SIGINT, original_handler)
    
    def test_context_switching(self):
        """Test context switching functionality."""
        handler = InterruptHandler()
        
        # Test setting different contexts
        handler.set_context(InterruptContext.TTS_PLAYING)
        assert handler.current_context == InterruptContext.TTS_PLAYING
        
        handler.set_context(InterruptContext.STT_LISTENING)
        assert handler.current_context == InterruptContext.STT_LISTENING
        
        handler.set_context(InterruptContext.CLAUDE_THINKING)
        assert handler.current_context == InterruptContext.CLAUDE_THINKING
        
        handler.set_context(InterruptContext.IDLE)
        assert handler.current_context == InterruptContext.IDLE
    
    def test_callback_registration(self):
        """Test callback registration for different contexts."""
        handler = InterruptHandler()
        
        tts_callback = Mock()
        stt_callback = Mock()
        claude_callback = Mock()
        exit_callback = Mock()
        
        handler.register_tts_callback(tts_callback)
        handler.register_stt_callback(stt_callback)
        handler.register_claude_callback(claude_callback)
        handler.register_exit_callback(exit_callback)
        
        assert handler.tts_interrupt_callback == tts_callback
        assert handler.stt_interrupt_callback == stt_callback
        assert handler.claude_interrupt_callback == claude_callback
        assert handler.exit_callback == exit_callback
    
    def test_interrupt_count_reset_after_timeout(self):
        """Test that interrupt count resets after timeout."""
        handler = InterruptHandler()
        handler.interrupt_reset_timeout = 0.1  # Set short timeout for testing
        
        # First interrupt
        handler._handle_interrupt(signal.SIGINT, None)
        assert handler.interrupt_count == 1
        
        # Wait for timeout
        time.sleep(0.2)
        
        # Second interrupt after timeout should reset count
        handler._handle_interrupt(signal.SIGINT, None)
        assert handler.interrupt_count == 1  # Reset to 1, not 2
    
    def test_interrupt_count_accumulation(self):
        """Test that interrupt count accumulates within timeout."""
        handler = InterruptHandler()
        handler.interrupt_reset_timeout = 10.0  # Long timeout
        
        # Set idle context to avoid triggering actual handlers
        handler.set_context(InterruptContext.IDLE)
        
        # Mock exit callback to prevent KeyboardInterrupt
        handler.register_exit_callback(Mock())
        
        # Multiple interrupts within timeout
        handler._handle_interrupt(signal.SIGINT, None)
        assert handler.interrupt_count == 1
        
        handler._handle_interrupt(signal.SIGINT, None)
        assert handler.interrupt_count == 2  # Exit callback called but count still increments
        
        # Reset count for next test
        handler.interrupt_count = 0
    
    def test_tts_interrupt_handling(self):
        """Test TTS interruption handling."""
        handler = InterruptHandler()
        tts_callback = Mock()
        
        handler.register_tts_callback(tts_callback)
        handler.set_context(InterruptContext.TTS_PLAYING)
        
        # Simulate CTRL+C during TTS
        handler._handle_interrupt(signal.SIGINT, None)
        
        tts_callback.assert_called_once()
        assert handler.interrupt_count == 0  # Should reset after handling
    
    def test_stt_interrupt_handling(self):
        """Test STT interruption handling."""
        handler = InterruptHandler()
        stt_callback = Mock()
        
        handler.register_stt_callback(stt_callback)
        handler.set_context(InterruptContext.STT_LISTENING)
        
        # Simulate CTRL+C during STT
        handler._handle_interrupt(signal.SIGINT, None)
        
        stt_callback.assert_called_once()
        assert handler.interrupt_count == 0  # Should reset after handling
    
    def test_claude_interrupt_handling_first_ctrlc(self):
        """Test Claude interruption handling on first CTRL+C."""
        handler = InterruptHandler()
        claude_callback = Mock()
        
        handler.register_claude_callback(claude_callback)
        handler.set_context(InterruptContext.CLAUDE_THINKING)
        
        # First CTRL+C should not trigger callback
        handler._handle_interrupt(signal.SIGINT, None)
        
        claude_callback.assert_not_called()
        assert handler.interrupt_count == 1
    
    def test_claude_interrupt_handling_second_ctrlc(self):
        """Test Claude interruption handling on second CTRL+C."""
        handler = InterruptHandler()
        claude_callback = Mock()
        
        handler.register_claude_callback(claude_callback)
        handler.set_context(InterruptContext.CLAUDE_THINKING)
        
        # First CTRL+C
        handler._handle_interrupt(signal.SIGINT, None)
        assert handler.interrupt_count == 1
        
        # Second CTRL+C should raise KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            handler._handle_interrupt(signal.SIGINT, None)
    
    def test_idle_state_exit_handling(self):
        """Test application exit in idle state."""
        handler = InterruptHandler()
        exit_callback = Mock()
        
        handler.register_exit_callback(exit_callback)
        handler.set_context(InterruptContext.IDLE)
        
        # First CTRL+C in idle state
        handler._handle_interrupt(signal.SIGINT, None)
        exit_callback.assert_not_called()
        assert handler.interrupt_count == 1
        
        # Second CTRL+C should trigger exit
        handler._handle_interrupt(signal.SIGINT, None)
        exit_callback.assert_called_once()
    
    def test_idle_state_exit_fallback(self):
        """Test that KeyboardInterrupt is raised if no exit callback."""
        handler = InterruptHandler()
        handler.set_context(InterruptContext.IDLE)
        
        # Mock signal.signal to prevent actual signal handler installation
        with patch('signal.signal'):
            # First CTRL+C
            handler._handle_interrupt(signal.SIGINT, None)
            
            # Second CTRL+C should raise KeyboardInterrupt
            with pytest.raises(KeyboardInterrupt):
                handler._handle_interrupt(signal.SIGINT, None)
    
    def test_nested_interrupt_prevention(self):
        """Test that nested interrupt handling is prevented."""
        handler = InterruptHandler()
        handler._handling_interrupt = True
        
        tts_callback = Mock()
        handler.register_tts_callback(tts_callback)
        handler.set_context(InterruptContext.TTS_PLAYING)
        
        # This should not process due to _handling_interrupt flag
        handler._handle_interrupt(signal.SIGINT, None)
        
        tts_callback.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_task_tracking(self):
        """Test async task tracking functionality."""
        handler = InterruptHandler()
        
        # Create a test task
        async def dummy_task():
            await asyncio.sleep(0.1)
        
        task = asyncio.create_task(dummy_task())
        handler.track_task(task)
        
        assert task in handler._active_tasks
        
        # Wait for task to complete
        await task
        
        # Task should be removed after completion
        assert task not in handler._active_tasks
    
    @pytest.mark.asyncio
    async def test_task_cancellation_on_shutdown(self):
        """Test that tracked tasks are cancelled on shutdown."""
        handler = InterruptHandler()
        
        # Create a long-running task
        async def long_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
        
        task = asyncio.create_task(long_task())
        handler.track_task(task)
        
        # Shutdown should cancel the task
        handler.shutdown()
        
        # Give a moment for cancellation to propagate
        await asyncio.sleep(0.01)
        
        assert task.cancelled() or task.done()
    
    def test_global_handler_singleton(self):
        """Test that get_interrupt_handler returns singleton."""
        handler1 = get_interrupt_handler()
        handler2 = get_interrupt_handler()
        
        assert handler1 is handler2
    
    @pytest.mark.asyncio
    async def test_convenience_functions(self):
        """Test convenience functions."""
        handler = get_interrupt_handler()
        
        # Test set_execution_context
        set_execution_context(InterruptContext.TTS_PLAYING)
        assert handler.current_context == InterruptContext.TTS_PLAYING
        
        # Test track_async_task
        async def dummy():
            pass
        
        task = asyncio.create_task(dummy())
        track_async_task(task)
        assert task in handler._active_tasks
        
        # Wait for task to complete
        await task


class TestInterruptHandlerIntegration:
    """Integration tests for interrupt handler with other components."""
    
    @pytest.mark.asyncio
    async def test_tts_interrupt_integration(self):
        """Test TTS interruption with real async callback."""
        handler = InterruptHandler()
        tts_interrupted = asyncio.Event()
        
        def tts_callback():
            tts_interrupted.set()
        
        handler.register_tts_callback(tts_callback)
        handler.set_context(InterruptContext.TTS_PLAYING)
        
        # Simulate CTRL+C
        handler._handle_interrupt(signal.SIGINT, None)
        
        # Check that callback was triggered
        assert tts_interrupted.is_set()
    
    def test_claude_interrupt_integration(self):
        """Test Claude interruption raises KeyboardInterrupt."""
        handler = InterruptHandler()
        claude_callback = Mock()
        
        handler.register_claude_callback(claude_callback)
        handler.set_context(InterruptContext.CLAUDE_THINKING)
        
        # First CTRL+C - no effect
        handler._handle_interrupt(signal.SIGINT, None)
        assert handler.interrupt_count == 1
        
        # Second CTRL+C - should raise KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt) as exc_info:
            handler._handle_interrupt(signal.SIGINT, None)
        
        assert "Claude processing interrupted by user" in str(exc_info.value)
    
    def test_multi_context_scenario(self):
        """Test a scenario with multiple context switches."""
        handler = InterruptHandler()
        
        tts_callback = Mock()
        stt_callback = Mock()
        claude_callback = Mock()
        
        handler.register_tts_callback(tts_callback)
        handler.register_stt_callback(stt_callback)
        handler.register_claude_callback(claude_callback)
        
        # Start with TTS
        handler.set_context(InterruptContext.TTS_PLAYING)
        handler._handle_interrupt(signal.SIGINT, None)
        tts_callback.assert_called_once()
        
        # Switch to STT
        handler.set_context(InterruptContext.STT_LISTENING)
        handler._handle_interrupt(signal.SIGINT, None)
        stt_callback.assert_called_once()
        
        # Switch to Claude
        handler.set_context(InterruptContext.CLAUDE_THINKING)
        handler._handle_interrupt(signal.SIGINT, None)  # First
        with pytest.raises(KeyboardInterrupt):
            handler._handle_interrupt(signal.SIGINT, None)  # Second