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
from .session_insights import SessionInsightsCollector
from .progress_chunk_processor import ProgressChunkProcessor


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
    
    def __init__(self, interactive: bool = True, show_progress: bool = True, enable_insights: bool = True):
        self.interactive = interactive
        self.show_progress = show_progress
        self.current_state = ProgressState(ExecutionPhase.INITIALIZING)
        self.is_running = False
        self.display_thread = None
        self._lock = threading.Lock()
        
        # Track phase history for debugging
        self.phase_history: List[ProgressState] = []
        
        # Add hierarchical display components
        self.chunk_processor = ProgressChunkProcessor()
        self._active_tools: Dict[str, float] = {}  # tool_id -> start_time
        self._current_tool_batch: List[str] = []  # Track multiple tools in same message
        self._pending_results: Dict[str, str] = {}  # tool_id -> result_message
        
        # Optional session insights (workspace monitoring always available since ARIS always has workspace)
        if enable_insights:
            try:
                self.insights_collector = SessionInsightsCollector()
            except Exception as e:
                log_debug(f"Failed to initialize insights collector: {e}")
                self.insights_collector = None
        else:
            self.insights_collector = None
        self._pending_insights: List[Dict[str, Any]] = []
        
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
    
    def process_chunk_with_insights(self, chunk: str) -> Optional[str]:
        """
        Enhanced chunk processing with hierarchical display and insights
        """
        # Always process insights first to ensure data collection
        if self.insights_collector:
            try:
                insight = self.insights_collector.process_chunk(chunk)
                if insight:
                    self._pending_insights.append(insight)
                    if insight.get("show_immediately"):
                        self._display_insight(insight)
                
                # Check workspace changes and progress insights
                workspace_insight = self.insights_collector.check_workspace_changes()
                if workspace_insight:
                    self._display_insight(workspace_insight)
                
                progress_insight = self.insights_collector.get_current_progress_insight()
                if progress_insight:
                    self._display_progress_insight(progress_insight)
            except Exception as e:
                log_debug(f"Error in insights collection: {e}")
        
        try:
            data = json.loads(chunk)
            
            # Handle tool execution start
            if data.get("type") == "assistant":
                content = data.get("message", {}).get("content", [])
                
                # Find all tool_use items in this message
                tool_use_items = [item for item in content if item.get("type") == "tool_use"]
                
                if tool_use_items:
                    # This is a new tool batch - reset tracking
                    self._current_tool_batch = []
                    
                    # Track all tools in this batch and display each one
                    for item in tool_use_items:
                        tool_id = item.get("id", "")
                        if tool_id:
                            self._active_tools[tool_id] = time.time()
                            self._current_tool_batch.append(tool_id)
                            
                            # Extract and display individual tool details
                            tool_detail = self.chunk_processor.extract_single_tool_parameters(item)
                            if tool_detail and self.show_progress:
                                print(f"  ├─ {tool_detail}", flush=True)
                    
                    # Return None to suppress standard progress display
                    return None
            
            # Handle tool completion  
            elif data.get("type") == "user":
                content = data.get("message", {}).get("content", [])
                
                for item in content:
                    if item.get("type") == "tool_result":
                        tool_id = item.get("tool_use_id", "")
                        
                        # Format the result without tree prefix
                        result_detail = self._format_single_tool_result(item, tool_id)
                        if result_detail:
                            # Store the result for batch display
                            self._pending_results[tool_id] = result_detail
                            
                            # Remove from current batch
                            if tool_id in self._current_tool_batch:
                                self._current_tool_batch.remove(tool_id)
                            
                            # If this completes the batch, display all results
                            if not self._current_tool_batch and self._pending_results:
                                self._display_tool_results_batch()
                            
                            # Return None to suppress standard progress display
                            return None
            
            # For non-tool chunks, use standard progress detail
            return parse_chunk_for_progress_detail(chunk)
            
        except (json.JSONDecodeError, KeyError):
            return parse_chunk_for_progress_detail(chunk)
    
    def _display_insight(self, insight: Dict[str, Any]):
        """Display an actionable insight"""
        if not self.show_progress:
            return
            
        insight_type = insight.get("type", "")
        message = insight.get("message", "")
        
        # Choose appropriate emoji and formatting
        emoji_map = {
            "resource_insight": "🔗",
            "timing_insight": "⏱️",
            "external_operation_insight": "🔌", 
            "workspace_insight": "📁",
            "completion_summary": "✅"
        }
        
        emoji = emoji_map.get(insight_type, "ℹ️")
        print(f"{emoji} {message}", flush=True)
    
    def _display_progress_insight(self, message: str):
        """Display periodic progress insight"""
        if self.show_progress:
            print(f"📊 {message}", flush=True)
    
    def _format_single_tool_result(self, item: dict, tool_id: str) -> Optional[str]:
        """Format a single tool result without tree prefix"""
        is_error = item.get("is_error", False)
        result_content = item.get("content", "")
        
        # Calculate execution time if available
        execution_time = ""
        if tool_id in self._active_tools:
            elapsed = time.time() - self._active_tools[tool_id]
            if elapsed > 1.0:
                execution_time = f" ({elapsed:.1f}s)"
            del self._active_tools[tool_id]
        
        if is_error:
            # Show brief error
            error_preview = str(result_content)[:80]
            if len(str(result_content)) > 80:
                error_preview += "..."
            # Clean up line breaks for single line display
            error_preview = " ".join(error_preview.split())
            return f"❌ Error: {error_preview}{execution_time}"
        else:
            # Show brief success summary with intelligent content extraction
            if isinstance(result_content, str) and result_content.strip():
                # Extract meaningful content (skip line numbers, get title/first content)
                cleaned_content = self._extract_meaningful_preview(result_content)
                return f"✅ {cleaned_content}{execution_time}"
            else:
                return f"✅ Completed{execution_time}"
    
    def _extract_meaningful_preview(self, content: str) -> str:
        """Extract meaningful preview from file content, providing clean single-line summaries"""
        if not content or not content.strip():
            return "Empty file"
        
        lines = content.strip().split('\n')
        cleaned_lines = []
        
        # Clean all lines and remove line numbers
        for line in lines:
            # Remove line number prefix if present (e.g., "     1\t")
            cleaned_line = line
            if '\t' in line:
                parts = line.split('\t', 1)
                if len(parts) > 1 and parts[0].strip().isdigit():
                    cleaned_line = parts[1]
            
            cleaned_line = cleaned_line.strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        
        if not cleaned_lines:
            return "Content loaded"
        
        # Look for document titles, headers, or meaningful first content
        for line in cleaned_lines:
            # Markdown headers - extract title
            if line.startswith('#'):
                title = line.lstrip('#').strip()
                if title and len(title) > 2:
                    return self._format_preview(title, 100)
            
            # Python/shell comments with meaningful content (like script descriptions)
            if line.startswith('#') and len(line) > 10:
                comment = line.lstrip('#').strip()
                if any(keyword in comment.lower() for keyword in ['script', 'module', 'tool', 'function', 'class']):
                    return self._format_preview(comment, 100)
            
            # Class or function definitions (show the signature)
            if any(line.startswith(keyword) for keyword in ['class ', 'def ', 'function ', 'export ']):
                return self._format_preview(line, 100)
            
            # Import statements (show what's being imported)
            if line.startswith(('import ', 'from ', 'require(', 'const ', 'let ', 'var ')):
                return self._format_preview(line, 100)
            
            # JSON/YAML structure indicators
            if line.startswith(('{', '[', '---')) or ':' in line[:50]:
                # For structured data, show a summary
                if '{' in content or '[' in content:
                    return "JSON/structured data"
                elif ':' in line and not line.startswith('http'):
                    return self._format_preview(line, 100)
            
            # Skip very short lines, obvious boilerplate
            if len(line) < 5 or line in ['"""', "'''", '/*', '*/', '<!--', '-->', '<?xml']:
                continue
            
            # Found meaningful content - return it
            if len(line) > 10:
                return self._format_preview(line, 100)
        
        # Fallback: try to get meaningful content from the start
        meaningful_start = None
        for line in cleaned_lines[:5]:  # Check first 5 lines
            if len(line) > 15 and not line.startswith(('*', '//', '<!--', '#!', '<?')):
                meaningful_start = line
                break
        
        if meaningful_start:
            return self._format_preview(meaningful_start, 100)
        
        # Last resort: show file type indicator based on content patterns
        content_lower = content.lower()
        if 'class ' in content_lower or 'def ' in content_lower:
            return "Python code"
        elif 'function' in content_lower or '=>' in content:
            return "JavaScript code"
        elif '<html' in content_lower or '<div' in content_lower:
            return "HTML content"
        elif content.strip().startswith('{') or content.strip().startswith('['):
            return "JSON data"
        elif '---' in content[:50]:
            return "YAML/Markdown content"
        
        return "Text content"
    
    def _format_preview(self, text: str, max_length: int) -> str:
        """Format text for clean single-line preview"""
        # Remove extra whitespace and ensure single line
        cleaned = " ".join(text.split())
        
        # Remove common code artifacts
        cleaned = cleaned.replace('"""', '').replace("'''", '').replace('/*', '').replace('*/', '')
        
        # Truncate if needed
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length - 3] + "..."
        
        return cleaned
    
    def _display_tool_results_batch(self):
        """Display all pending tool results with proper tree formatting"""
        if not self._pending_results:
            return
        
        results = list(self._pending_results.values())
        
        # Display all results with proper tree formatting
        for i, result in enumerate(results):
            if i == len(results) - 1:  # Last result
                prefix = "  └─"
            else:  # Intermediate results
                prefix = "  ├─"
            
            if self.show_progress:
                print(f"{prefix} {result}", flush=True)
        
        # Clear pending results
        self._pending_results.clear()
    
    def get_completion_summary(self) -> Optional[Dict[str, Any]]:
        """Get final completion summary (only available if insights enabled)"""
        if not self.insights_collector:
            return None
            
        completion_insights = [i for i in self._pending_insights if i.get("type") == "completion_summary"]
        return completion_insights[-1] if completion_insights else None
    
    def has_insights(self) -> bool:
        """Check if this tracker has insights capabilities enabled"""
        return self.insights_collector is not None



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


def create_progress_tracker(interactive: bool = True, verbose: bool = False, enable_insights: bool = True) -> ProgressTracker:
    """
    Create progress tracker with optional session insights and workspace monitoring.
    
    Args:
        interactive: Whether running in interactive mode
        verbose: Whether to show progress (disabled if verbose logging is on)
        enable_insights: Whether to enable insights collection and workspace monitoring (default: True)
        
    Returns:
        ProgressTracker instance with insights enabled if requested
    """
    # If verbose logging is enabled, don't show progress to avoid interference
    show_progress = not verbose
    
    return ProgressTracker(interactive=interactive, show_progress=show_progress, enable_insights=enable_insights)