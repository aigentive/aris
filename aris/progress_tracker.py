"""
Progress tracking system for ARIS execution phases.
Works in both interactive and non-interactive modes.
"""
import json
import time
import threading
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from .logging_utils import log_debug


class ExecutionPhase(Enum):
    """Execution phases that ARIS goes through"""
    INITIALIZING = "Initializing ARIS"
    LOADING_PROFILE = "Loading profile"
    STARTING_MCP = "Starting MCP servers"
    PROCESSING_INPUT = "Processing request"
    CALLING_TOOLS = "Executing tools"
    GENERATING_RESPONSE = "Generating response"
    COMPLETING = "Finishing up"
    DONE = "Complete"


@dataclass
class ProgressState:
    """Current progress state"""
    phase: ExecutionPhase
    detail: str = ""
    progress: float = 0.0  # 0.0 to 1.0 (for future use)
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ProgressTracker:
    """
    Unified progress tracking for both interactive and non-interactive modes.
    
    - Interactive mode: Shows animated progress with details
    - Non-interactive mode: Shows progress updates on new lines
    """
    
    def __init__(self, interactive: bool = True, show_progress: bool = True):
        self.interactive = interactive
        self.show_progress = show_progress
        self.current_state = ProgressState(ExecutionPhase.INITIALIZING)
        self.is_running = False
        self.display_thread = None
        self._lock = threading.Lock()
        
        # Track phase history for debugging
        self.phase_history: List[ProgressState] = []
        
    def update_phase(self, phase: ExecutionPhase, detail: str = ""):
        """Update the current execution phase"""
        with self._lock:
            self.current_state = ProgressState(phase, detail)
            self.phase_history.append(self.current_state)
            
        log_debug(f"ProgressTracker: Phase changed to {phase.value} - {detail}")
        
        # In non-interactive mode, show immediate progress updates
        if not self.interactive and self.show_progress:
            self._show_non_interactive_update()
            
    def update_detail(self, detail: str):
        """Update just the detail text for current phase"""
        with self._lock:
            self.current_state.detail = detail
            
        log_debug(f"ProgressTracker: Detail updated to '{detail}'")
        
        # In non-interactive mode, show detail updates immediately
        if not self.interactive and self.show_progress:
            self._show_non_interactive_update()
        
    def start_display(self):
        """Start the progress display (only matters for interactive mode)"""
        if not self.show_progress:
            return
            
        if self.interactive:
            self.is_running = True
            self.display_thread = threading.Thread(target=self._interactive_display_loop)
            self.display_thread.daemon = True
            self.display_thread.start()
        else:
            # Non-interactive mode shows updates immediately, no background thread needed
            self._show_non_interactive_update()
            
    def stop_display(self):
        """Stop the progress display"""
        self.is_running = False
        if self.display_thread:
            self.display_thread.join(timeout=1.0)
            
        # Clear the progress line in interactive mode
        if self.interactive and self.show_progress:
            print("\r" + " " * 80 + "\r", end="", flush=True)
            
    def _show_non_interactive_update(self):
        """Show progress update for non-interactive mode"""
        with self._lock:
            phase_text = self.current_state.phase.value
            detail_text = self.current_state.detail
            
        if detail_text:
            status_line = f"📋 {phase_text}: {detail_text}"
        else:
            status_line = f"📋 {phase_text}..."
            
        print(status_line, flush=True)
        
    def _interactive_display_loop(self):
        """
        Interactive mode progress display.
        Uses a separate line to avoid conflicts with the main spinner.
        """
        last_displayed_detail = ""
        
        while self.is_running:
            with self._lock:
                if self.current_state.phase == ExecutionPhase.DONE:
                    break
                    
                phase_text = self.current_state.phase.value
                detail_text = self.current_state.detail
                
            # Only update display when detail changes to avoid flickering
            if detail_text and detail_text != last_displayed_detail:
                # Move to next line, show update, then return cursor
                status_line = f"\n📋 {phase_text}: {detail_text}"
                
                # Truncate if too long
                if len(status_line) > 78:
                    status_line = status_line[:75] + "..."
                    
                print(status_line, flush=True)
                last_displayed_detail = detail_text
                
            time.sleep(0.2)  # Check less frequently than main spinner
            
    def mark_complete(self):
        """Mark progress as complete"""
        self.update_phase(ExecutionPhase.DONE)
        self.stop_display()
        
    def get_phase_summary(self) -> str:
        """Get a summary of all phases for debugging"""
        summary_lines = []
        for i, state in enumerate(self.phase_history):
            duration = ""
            if i > 0:
                prev_time = self.phase_history[i-1].timestamp
                duration = f" ({state.timestamp - prev_time:.2f}s)"
                
            detail_suffix = f" - {state.detail}" if state.detail else ""
            summary_lines.append(f"{state.phase.value}{detail_suffix}{duration}")
            
        return "\n".join(summary_lines)


def parse_chunk_for_progress_detail(chunk: str) -> Optional[str]:
    """
    Extract meaningful progress details from Claude CLI JSON chunks.
    This helps provide real-time feedback about what's happening.
    """
    try:
        data = json.loads(chunk)
        
        # System initialization events
        if data.get("type") == "system":
            subtype = data.get("subtype")
            if subtype == "init":
                mcp_servers = data.get("mcp_servers", [])
                if mcp_servers:
                    connected_count = len([s for s in mcp_servers if s.get("status") == "connected"])
                    return f"Connected {connected_count}/{len(mcp_servers)} MCP servers"
                return "MCP servers initialized"
                
        # Tool execution
        elif data.get("type") == "assistant":
            message = data.get("message", {})
            content = message.get("content", [])
            
            for item in content:
                if item.get("type") == "tool_use":
                    tool_name = item.get("name", "unknown")
                    # Clean up MCP prefixes for better display
                    if tool_name.startswith("mcp__"):
                        # For MCP tools like "mcp__openai-image-mcp__generate_image"
                        # Extract the actual tool name (last part after __)
                        parts = tool_name.split("__")
                        if len(parts) >= 3:
                            tool_name = parts[-1]  # Get the actual tool name
                        else:
                            # Fallback for simpler MCP patterns
                            tool_name = tool_name.replace("mcp__", "")
                    return f"Using {tool_name}"
                    
                elif item.get("type") == "text":
                    # Extract first few words of response for context
                    text = item.get("text", "").strip()
                    if text:
                        words = text.split()[:6]  # First 6 words
                        preview = " ".join(words)
                        if len(text.split()) > 6:
                            preview += "..."
                        return f"Writing: {preview}"
        
        # Tool results (user messages containing tool outputs)
        elif data.get("type") == "user":
            message = data.get("message", {})
            content = message.get("content", [])
            
            for item in content:
                if item.get("type") == "tool_result":
                    # Use the explicit is_error field to determine status
                    is_error = item.get("is_error", False)
                    result_content = item.get("content", "")
                    
                    if is_error:
                        # Show a preview of the actual error message
                        if isinstance(result_content, str) and result_content.strip():
                            # Clean up the content for single-line display
                            clean_content = " ".join(result_content.strip().split())
                            preview = clean_content[:120]
                            if len(clean_content) > 120:
                                preview += "..."
                            return f"Tool error: {preview}"
                        else:
                            return "Tool error"
                    else:
                        # Show a preview of the successful result
                        if isinstance(result_content, str) and result_content.strip():
                            # Clean up the content for single-line display
                            clean_content = " ".join(result_content.strip().split())
                            preview = clean_content[:120]
                            if len(clean_content) > 120:
                                preview += "..."
                            return f"Tool completed: {preview}"
                        else:
                            return "Tool completed"
                        
        # Error events
        elif data.get("type") == "error":
            error_msg = data.get("message", "Unknown error")
            return f"Error: {error_msg[:40]}..."
            
    except (json.JSONDecodeError, KeyError, TypeError):
        # If we can't parse it, that's fine - not all chunks will be parseable
        pass
    except Exception as e:
        # Log unexpected parsing errors for debugging
        log_debug(f"Unexpected error parsing chunk for progress: {e}")
        
    return None


def create_progress_tracker(interactive: bool = True, verbose: bool = False) -> ProgressTracker:
    """
    Factory function to create a progress tracker based on mode.
    
    Args:
        interactive: Whether running in interactive mode
        verbose: Whether to show progress (disabled if verbose logging is on)
    
    Returns:
        ProgressTracker instance configured for the mode
    """
    # If verbose logging is enabled, don't show progress to avoid interference
    show_progress = not verbose
    
    return ProgressTracker(interactive=interactive, show_progress=show_progress)