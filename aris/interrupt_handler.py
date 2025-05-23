"""
Centralized interrupt handling for ARIS with multi-level CTRL+C hierarchy.

This module manages the following interrupt levels:
1. First CTRL+C: Interrupts only TTS playback (if active)
2. Second CTRL+C: Interrupts Claude CLI process (if thinking)
3. Third CTRL+C: Terminates entire CLI application

The handler tracks the current context (TTS, STT, Claude processing, idle)
and manages interrupt count to provide appropriate behavior at each level.
"""

import asyncio
import signal
import time
from enum import Enum
from typing import Optional, Callable, Set
from .logging_utils import log_router_activity, log_warning, log_debug

class InterruptContext(Enum):
    """Represents the current execution context for interrupt handling."""
    IDLE = "idle"
    TTS_PLAYING = "tts_playing"
    STT_LISTENING = "stt_listening"
    CLAUDE_THINKING = "claude_thinking"

class InterruptHandler:
    """
    Manages multi-level CTRL+C interrupts with context awareness.
    
    This handler maintains state about:
    - Current execution context (TTS, STT, Claude, idle)
    - Interrupt count and timing
    - Callbacks for different interrupt levels
    """
    
    def __init__(self):
        self.current_context = InterruptContext.IDLE
        self.interrupt_count = 0
        self.last_interrupt_time = 0
        self.interrupt_reset_timeout = 2.0  # Reset interrupt count after 2 seconds
        
        # Callbacks for different contexts
        self.tts_interrupt_callback: Optional[Callable] = None
        self.stt_interrupt_callback: Optional[Callable] = None
        self.claude_interrupt_callback: Optional[Callable] = None
        self.exit_callback: Optional[Callable] = None
        
        # Track if we're already handling an interrupt
        self._handling_interrupt = False
        
        # Original signal handler
        self._original_sigint_handler = None
        
        # Active tasks that should be cancelled on exit
        self._active_tasks: Set[asyncio.Task] = set()
    
    def initialize(self):
        """Initialize the interrupt handler and set up signal handling."""
        log_router_activity("InterruptHandler: Initializing multi-level CTRL+C handling")
        
        # Store original handler
        self._original_sigint_handler = signal.getsignal(signal.SIGINT)
        print(f"[DEBUG] Original SIGINT handler: {self._original_sigint_handler}", flush=True)
        
        # Always use regular signal handler for better compatibility
        signal.signal(signal.SIGINT, self._handle_interrupt)
        print(f"[DEBUG] InterruptHandler: Signal handler installed: {self._handle_interrupt}", flush=True)
        log_debug("InterruptHandler: Regular signal handler installed")
    
    def shutdown(self):
        """Restore original signal handler and clean up."""
        log_router_activity("InterruptHandler: Shutting down")
        
        # Cancel any active tasks
        for task in self._active_tasks:
            if not task.done():
                task.cancel()
        
        # No need to remove asyncio signal handler since we're not using it
        
        # Restore original handler
        if self._original_sigint_handler:
            signal.signal(signal.SIGINT, self._original_sigint_handler)
        
        log_debug("InterruptHandler: Original signal handler restored")
    
    def set_context(self, context: InterruptContext):
        """
        Set the current execution context.
        
        Args:
            context: The new execution context
        """
        old_context = self.current_context
        self.current_context = context
        log_debug(f"InterruptHandler: Context changed from {old_context.value} to {context.value}")
        
        # Re-ensure our signal handler is active when changing context
        current_handler = signal.getsignal(signal.SIGINT)
        if current_handler != self._handle_interrupt:
            log_debug(f"InterruptHandler: Re-installing signal handler (was {current_handler})")
            signal.signal(signal.SIGINT, self._handle_interrupt)
    
    def register_tts_callback(self, callback: Callable):
        """Register callback for TTS interruption."""
        self.tts_interrupt_callback = callback
        log_debug("InterruptHandler: TTS interrupt callback registered")
    
    def register_stt_callback(self, callback: Callable):
        """Register callback for STT interruption."""
        self.stt_interrupt_callback = callback
        log_debug("InterruptHandler: STT interrupt callback registered")
    
    def register_claude_callback(self, callback: Callable):
        """Register callback for Claude process interruption."""
        self.claude_interrupt_callback = callback
        log_debug("InterruptHandler: Claude interrupt callback registered")
    
    def register_exit_callback(self, callback: Callable):
        """Register callback for application exit."""
        self.exit_callback = callback
        log_debug("InterruptHandler: Exit callback registered")
    
    def track_task(self, task: asyncio.Task):
        """Track an active task that should be cancelled on exit."""
        self._active_tasks.add(task)
        
        # Remove task when it's done
        def remove_task(t):
            self._active_tasks.discard(t)
        
        task.add_done_callback(remove_task)
    
    def _handle_interrupt_async(self):
        """Async wrapper for interrupt handling."""
        self._handle_interrupt(signal.SIGINT, None)
    
    def _handle_interrupt(self, signum, frame):
        """
        Handle SIGINT (CTRL+C) with context-aware multi-level behavior.
        
        Args:
            signum: Signal number (SIGINT)
            frame: Current stack frame
        """
        # Debug: Ensure handler is being called
        print(f"\n[DEBUG] Interrupt handler called! Context: {self.current_context.value}, Count: {self.interrupt_count + 1}", flush=True)
        
        # Prevent nested interrupt handling
        if self._handling_interrupt:
            print("[DEBUG] Already handling interrupt, ignoring...", flush=True)
            return
        
        self._handling_interrupt = True
        
        try:
            current_time = time.time()
            
            # Reset interrupt count if timeout has passed
            if current_time - self.last_interrupt_time > self.interrupt_reset_timeout:
                self.interrupt_count = 0
            
            self.interrupt_count += 1
            self.last_interrupt_time = current_time
            
            log_router_activity(f"InterruptHandler: CTRL+C pressed (count: {self.interrupt_count}, context: {self.current_context.value})")
            
            # Handle based on context and interrupt count
            if self.current_context == InterruptContext.TTS_PLAYING:
                # First interrupt during TTS: stop only TTS
                print("\n🔇 Stopping speech...", flush=True)
                if self.tts_interrupt_callback:
                    log_router_activity("InterruptHandler: Interrupting TTS playback")
                    self.tts_interrupt_callback()
                    self.interrupt_count = 0  # Reset count after handling
                else:
                    log_warning("InterruptHandler: No TTS callback registered")
            
            elif self.current_context == InterruptContext.STT_LISTENING:
                # Interrupt during STT: stop recording
                print("\n🎵 Stopping voice recording...", flush=True)
                if self.stt_interrupt_callback:
                    log_router_activity("InterruptHandler: Interrupting STT recording")
                    self.stt_interrupt_callback()
                    self.interrupt_count = 0  # Reset count after handling
                else:
                    log_warning("InterruptHandler: No STT callback registered")
            
            elif self.current_context == InterruptContext.CLAUDE_THINKING:
                # During Claude processing
                if self.interrupt_count == 1:
                    # First interrupt: just notify user
                    log_router_activity("InterruptHandler: First CTRL+C during Claude processing (press again to interrupt)")
                    # Show user-visible feedback
                    print("\n⚠️  Press CTRL+C again to interrupt Claude processing...", flush=True)
                elif self.interrupt_count >= 2:
                    # Second interrupt: stop Claude
                    print("\n🛑 Interrupting Claude...", flush=True)
                    if self.claude_interrupt_callback:
                        log_router_activity("InterruptHandler: Interrupting Claude processing")
                        # Instead of calling the callback directly (which is async),
                        # raise KeyboardInterrupt to be caught by the interaction handler
                        raise KeyboardInterrupt("Claude processing interrupted by user")
                    else:
                        log_warning("InterruptHandler: No Claude callback registered")
                        raise KeyboardInterrupt("Claude processing interrupted by user")
            
            else:
                # IDLE context or no specific handler
                if self.interrupt_count == 1:
                    log_router_activity("InterruptHandler: First CTRL+C in idle state (press again to exit)")
                    print("\n⚠️  Press CTRL+C again to exit...", flush=True)
                elif self.interrupt_count >= 2:
                    # Exit application
                    log_router_activity("InterruptHandler: Exiting application")
                    print("\n👋 Exiting ARIS...", flush=True)
                    if self.exit_callback:
                        self.exit_callback()
                    else:
                        # Fallback: raise KeyboardInterrupt
                        raise KeyboardInterrupt()
        
        finally:
            self._handling_interrupt = False

# Global interrupt handler instance
_interrupt_handler: Optional[InterruptHandler] = None

def get_interrupt_handler() -> InterruptHandler:
    """
    Get or create the global interrupt handler instance.
    
    Returns:
        The global InterruptHandler instance
    """
    global _interrupt_handler
    
    if _interrupt_handler is None:
        _interrupt_handler = InterruptHandler()
    
    return _interrupt_handler

def set_execution_context(context: InterruptContext):
    """
    Convenience function to set the current execution context.
    
    Args:
        context: The new execution context
    """
    handler = get_interrupt_handler()
    handler.set_context(context)

def track_async_task(task: asyncio.Task):
    """
    Convenience function to track an async task for cleanup.
    
    Args:
        task: The asyncio task to track
    """
    handler = get_interrupt_handler()
    handler.track_task(task)