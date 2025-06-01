"""
Tests for the progress tracking system and response formatting improvements.
"""
import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from aris.progress_tracker import (
    ProgressTracker, ExecutionPhase, ProgressState, 
    parse_chunk_for_progress_detail, create_progress_tracker
)


class TestProgressState:
    """Test the ProgressState dataclass."""
    
    def test_progress_state_creation(self):
        """Test basic ProgressState creation."""
        state = ProgressState(ExecutionPhase.INITIALIZING, "test detail", 0.5)
        
        assert state.phase == ExecutionPhase.INITIALIZING
        assert state.detail == "test detail"
        assert state.progress == 0.5
        assert state.timestamp > 0
    
    def test_progress_state_auto_timestamp(self):
        """Test that timestamp is set automatically."""
        before = time.time()
        state = ProgressState(ExecutionPhase.PROCESSING_INPUT)
        after = time.time()
        
        assert before <= state.timestamp <= after


class TestExecutionPhase:
    """Test the ExecutionPhase enum."""
    
    def test_execution_phases_exist(self):
        """Test that all expected phases exist."""
        expected_phases = [
            "INITIALIZING", "LOADING_PROFILE", "STARTING_MCP", 
            "PROCESSING_INPUT", "CALLING_TOOLS", "GENERATING_RESPONSE",
            "COMPLETING", "DONE"
        ]
        
        for phase_name in expected_phases:
            assert hasattr(ExecutionPhase, phase_name)
    
    def test_phase_values_are_descriptive(self):
        """Test that phase values are human-readable."""
        assert ExecutionPhase.INITIALIZING.value == "Initializing ARIS"
        assert ExecutionPhase.PROCESSING_INPUT.value == "Processing request"
        assert ExecutionPhase.GENERATING_RESPONSE.value == "Generating response"


class TestParseChunkForProgressDetail:
    """Test the chunk parsing function for progress details."""
    
    def test_parse_system_init_chunk(self):
        """Test parsing system initialization chunks."""
        chunk = '{"type": "system", "subtype": "init", "mcp_servers": [{"name": "test", "status": "connected"}]}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Connected 1/1 MCP servers"
    
    def test_parse_tool_use_chunk(self):
        """Test parsing tool use chunks."""
        chunk = '{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__server__read_file"}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Using read_file"
    
    def test_parse_text_response_chunk(self):
        """Test parsing text response chunks."""
        chunk = '{"type": "assistant", "message": {"content": [{"type": "text", "text": "I will help you create a comprehensive report"}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Writing: I will help you create a..."
    
    def test_parse_error_chunk(self):
        """Test parsing error chunks."""
        chunk = '{"type": "error", "message": "Connection failed"}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Error: Connection failed..."
    
    def test_parse_invalid_json(self):
        """Test handling invalid JSON gracefully."""
        chunk = "invalid json"
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail is None
    
    def test_parse_empty_chunk(self):
        """Test handling empty chunks."""
        chunk = ""
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail is None
    
    def test_parse_tool_result_chunk(self):
        """Test parsing successful tool result chunks."""
        chunk = '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": "File read successfully"}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Tool completed: File read successfully"
    
    def test_parse_tool_result_chunk_explicit_success(self):
        """Test parsing tool result chunks with explicit is_error=false."""
        chunk = '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": "File read successfully", "is_error": false}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Tool completed: File read successfully"
    
    def test_parse_tool_result_long_content(self):
        """Test parsing tool result with long content that gets truncated."""
        long_content = "This is a very long file content that should be truncated after 120 characters for display purposes in the progress tracker because users want to see more context about what tools are doing and what results they return"
        chunk = f'{{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "toolu_123", "content": "{long_content}"}}]}}}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        expected = "Tool completed: This is a very long file content that should be truncated after 120 characters for display purposes in the progress trac..."
        assert detail == expected
    
    def test_parse_tool_result_empty_content(self):
        """Test parsing tool result with empty content."""
        chunk = '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": ""}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Tool completed"
    
    def test_parse_permission_error_chunk(self):
        """Test parsing permission error chunks."""
        chunk = '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": "Claude requested permissions to use Bash, but you haven\'t granted it yet.", "is_error": true}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Tool error: Claude requested permissions to use Bash, but you haven't granted it yet."
    
    def test_parse_tool_error_chunk(self):
        """Test parsing tool error chunks."""
        chunk = '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": "Error: File not found", "is_error": true}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        assert detail == "Tool error: Error: File not found"
    
    def test_parse_chunk_exception_handling(self):
        """Test that parsing exceptions are handled gracefully."""
        # This should not raise an exception
        chunk = '{"type": "user", "message": {"content": [{"type": "tool_result", "content": null}]}}'
        
        detail = parse_chunk_for_progress_detail(chunk)
        
        # Should handle the null content gracefully
        assert detail == "Tool completed"


class TestProgressTracker:
    """Test the ProgressTracker class."""
    
    def test_progress_tracker_creation(self):
        """Test basic ProgressTracker creation."""
        tracker = ProgressTracker(interactive=True, show_progress=True)
        
        assert tracker.interactive is True
        assert tracker.show_progress is True
        assert tracker.current_state.phase == ExecutionPhase.INITIALIZING
        assert tracker.is_running is False
    
    def test_update_phase(self):
        """Test updating the execution phase."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        
        tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "test detail")
        
        assert tracker.current_state.phase == ExecutionPhase.PROCESSING_INPUT
        assert tracker.current_state.detail == "test detail"
    
    def test_update_detail(self):
        """Test updating just the detail."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        
        tracker.update_detail("new detail")
        
        assert tracker.current_state.detail == "new detail"
        assert tracker.current_state.phase == ExecutionPhase.INITIALIZING  # Should remain unchanged
    
    def test_phase_history_tracking(self):
        """Test that phase history is tracked."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        
        tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "processing")
        tracker.update_phase(ExecutionPhase.GENERATING_RESPONSE, "generating")
        
        assert len(tracker.phase_history) == 2  # 2 explicit updates
        assert tracker.phase_history[0].phase == ExecutionPhase.PROCESSING_INPUT
        assert tracker.phase_history[1].phase == ExecutionPhase.GENERATING_RESPONSE
    
    def test_mark_complete(self):
        """Test marking progress as complete."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        
        tracker.mark_complete()
        
        assert tracker.current_state.phase == ExecutionPhase.DONE
    
    def test_get_phase_summary(self):
        """Test getting a phase summary."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        
        tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "test")
        tracker.update_phase(ExecutionPhase.DONE)
        
        summary = tracker.get_phase_summary()
        
        assert "Processing request - test" in summary
        assert "Complete" in summary
    
    def test_non_interactive_display_disabled_when_verbose(self):
        """Test that non-interactive display is disabled in verbose mode."""
        with patch('builtins.print') as mock_print:
            tracker = ProgressTracker(interactive=False, show_progress=False)  # Verbose mode
            tracker.start_display()
            tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "test")
            
            # Should not print anything when show_progress=False
            mock_print.assert_not_called()
    
    def test_non_interactive_display_shows_updates(self):
        """Test that non-interactive display shows updates when enabled."""
        with patch('builtins.print') as mock_print:
            tracker = ProgressTracker(interactive=False, show_progress=True)
            tracker.start_display()
            tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "test detail")
            
            # Should print the progress update
            mock_print.assert_called_with("📋 Processing request: test detail", flush=True)
    
    @patch('threading.Thread')
    def test_interactive_display_thread(self, mock_thread):
        """Test that interactive display starts a background thread."""
        tracker = ProgressTracker(interactive=True, show_progress=True)
        
        tracker.start_display()
        
        # Should create and start a daemon thread
        mock_thread.assert_called_once()
        thread_instance = mock_thread.return_value
        assert thread_instance.daemon is True
        thread_instance.start.assert_called_once()
    
    def test_stop_display(self):
        """Test stopping the display."""
        tracker = ProgressTracker(interactive=False, show_progress=True)
        tracker.start_display()
        
        tracker.stop_display()
        
        assert tracker.is_running is False


class TestCreateProgressTracker:
    """Test the progress tracker factory function."""
    
    def test_create_interactive_tracker(self):
        """Test creating an interactive tracker."""
        tracker = create_progress_tracker(interactive=True, verbose=False)
        
        assert tracker.interactive is True
        assert tracker.show_progress is True  # Should be True when verbose=False
    
    def test_create_non_interactive_tracker(self):
        """Test creating a non-interactive tracker."""
        tracker = create_progress_tracker(interactive=False, verbose=False)
        
        assert tracker.interactive is False
        assert tracker.show_progress is True
    
    def test_create_tracker_verbose_disables_progress(self):
        """Test that verbose mode disables progress display."""
        tracker = create_progress_tracker(interactive=True, verbose=True)
        
        assert tracker.show_progress is False  # Should be False when verbose=True
    
    def test_create_tracker_defaults(self):
        """Test default values for the factory function."""
        tracker = create_progress_tracker()
        
        assert tracker.interactive is True  # Default
        assert tracker.show_progress is True  # Default verbose=False


class TestProgressTrackerIntegration:
    """Test progress tracker integration scenarios."""
    
    def test_progress_through_all_phases(self):
        """Test progressing through all execution phases."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        
        phases = [
            (ExecutionPhase.LOADING_PROFILE, "Loading profile data"),
            (ExecutionPhase.STARTING_MCP, "Starting MCP servers"),
            (ExecutionPhase.PROCESSING_INPUT, "Processing user request"),
            (ExecutionPhase.CALLING_TOOLS, "Executing tools"),
            (ExecutionPhase.GENERATING_RESPONSE, "Generating response"),
            (ExecutionPhase.COMPLETING, "Finalizing"),
            (ExecutionPhase.DONE, "")
        ]
        
        for phase, detail in phases:
            tracker.update_phase(phase, detail)
        
        # Should have tracked all phases
        assert len(tracker.phase_history) == len(phases)  # All explicit phase updates
        assert tracker.current_state.phase == ExecutionPhase.DONE
    
    def test_concurrent_access_thread_safety(self):
        """Test that the tracker is thread-safe for concurrent access."""
        tracker = ProgressTracker(interactive=False, show_progress=False)
        results = []
        
        def update_phase_worker(phase_num):
            tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, f"Worker {phase_num}")
            results.append(phase_num)
        
        # Create multiple threads updating simultaneously
        threads = []
        for i in range(5):
            thread = threading.Thread(target=update_phase_worker, args=(i,))
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all to complete
        for thread in threads:
            thread.join()
        
        # Should have processed all updates
        assert len(results) == 5
        assert len(tracker.phase_history) >= 5  # At least 5 updates + initial state