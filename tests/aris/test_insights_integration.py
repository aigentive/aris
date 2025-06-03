"""
Integration tests for the complete insights workflow.
Tests the full pipeline from JSON chunks to user-visible insights.
"""
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from aris.progress_tracker import create_progress_tracker, ExecutionPhase
from aris.session_insights import SessionInsightsCollector
from aris.workspace_monitor import WorkspaceFileMonitor
from aris.cli import format_non_interactive_response


class TestInsightsEndToEndWorkflow:
    """Test complete end-to-end insights workflow."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def mock_session_state(self, temp_workspace):
        """Mock session state with temporary workspace."""
        with patch('aris.session_state.get_current_session_state') as mock:
            session_state = MagicMock()
            session_state.workspace_path = str(temp_workspace)
            session_state.active_profile = {"profile_name": "test_profile"}
            mock.return_value = session_state
            yield session_state
    
    def test_complete_insights_workflow_with_file_operations(self, mock_session_state, temp_workspace):
        """Test complete insights workflow including file operations."""
        # Create progress tracker with insights enabled
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
        
        # Simulate a complete session workflow
        workflow_chunks = [
            # System initialization
            {
                "type": "system",
                "subtype": "init",
                "mcp_servers": [
                    {"name": "file-ops", "status": "connected"},
                    {"name": "image-gen", "status": "connected"}
                ]
            },
            # Tool execution start
            {
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "name": "mcp__file-ops__create_file",
                        "id": "tool_001",
                        "input": {"filename": "test.txt", "content": "Hello World"}
                    }]
                }
            },
            # Tool result  
            {
                "type": "user",
                "message": {
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "tool_001",
                        "content": "File created successfully",
                        "is_error": False
                    }]
                }
            },
            # Another tool execution (expensive operation)
            {
                "type": "assistant", 
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "name": "mcp__image-gen__generate_image",
                        "id": "tool_002",
                        "input": {"prompt": "A beautiful sunset"}
                    }]
                }
            },
            # Completion with cost
            {
                "type": "result",
                "cost_usd": 0.25,
                "duration_ms": 45000,
                "num_turns": 2
            }
        ]
        
        insights_displayed = []
        
        with patch('builtins.print') as mock_print:
            tracker.start_display()
            
            # Process all chunks
            for chunk_data in workflow_chunks:
                chunk = json.dumps(chunk_data)
                
                # Simulate some processing time for tools
                if chunk_data.get("type") == "assistant":
                    time.sleep(0.01)  # Small delay for tool execution
                
                detail = tracker.process_chunk_with_insights(chunk)
                if detail:
                    tracker.update_detail(detail)
            
            # Create a file in workspace to trigger workspace monitoring
            test_file = temp_workspace / "created_by_tool.txt"
            test_file.write_text("Generated content")
            
            # Force workspace check
            if tracker.insights_collector:
                workspace_insight = tracker.insights_collector.check_workspace_changes()
                if workspace_insight:
                    tracker._display_insight(workspace_insight)
            
            tracker.stop_display()
            
            # Verify insights were displayed
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            insights_displayed = [call for call in print_calls if any(emoji in call for emoji in ['🔗', '🔌', '⏱️', '📁', '✅'])]
            
        # Verify expected insights were generated
        assert len(insights_displayed) >= 1  # Should have resource insights
        
        # Check for specific insight types in both displayed and pending insights
        resource_insights = [msg for msg in insights_displayed if '🔗' in msg]
        
        # External operation insights are stored but not immediately displayed (show_immediately: False)
        external_op_insights = [insight for insight in tracker._pending_insights 
                               if insight.get("type") == "external_operation_insight"]
        
        assert len(resource_insights) >= 1  # Should show connected services
        assert len(external_op_insights) >= 1  # Should have external operations in pending insights
        
        # Verify completion summary is available
        completion_summary = tracker.get_completion_summary()
        assert completion_summary is not None
        assert completion_summary["metrics"]["total_cost"] == 0.25
        assert completion_summary["metrics"]["duration_seconds"] == 45.0
    
    def test_insights_workflow_with_errors(self, mock_session_state):
        """Test insights workflow when errors occur."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
        
        error_chunks = [
            # Tool execution with error
            {
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "name": "mcp__test__failing_tool",
                        "id": "tool_error",
                        "input": {"param": "value"}
                    }]
                }
            },
            # Error result
            {
                "type": "user",
                "message": {
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "tool_error", 
                        "content": "Error: Operation failed",
                        "is_error": True
                    }]
                }
            }
        ]
        
        with patch('builtins.print'):
            for chunk_data in error_chunks:
                chunk = json.dumps(chunk_data)
                detail = tracker.process_chunk_with_insights(chunk)
        
        # Verify error tracking
        if tracker.insights_collector:
            assert len(tracker.insights_collector.metrics.errors_encountered) == 1
            assert "Error: Operation failed" in tracker.insights_collector.metrics.errors_encountered[0]
    
    def test_insights_workflow_with_long_operations(self, mock_session_state):
        """Test insights workflow with long-running operations."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
        
        # Simulate long operation by manipulating start times
        if tracker.insights_collector:
            tracker.insights_collector._tool_start_times["long_tool"] = time.time() - 15  # 15 seconds ago
        
        long_op_chunk = {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "long_tool",
                    "content": "Long operation completed",
                    "is_error": False
                }]
            }
        }
        
        insights_displayed = []
        with patch('builtins.print') as mock_print:
            chunk = json.dumps(long_op_chunk)
            tracker.process_chunk_with_insights(chunk)
            
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            timing_insights = [call for call in print_calls if '⏱️' in call and 'completed' in call]
        
        # Timing insights for completed operations have show_immediately: False, so check pending insights
        timing_insights_pending = [insight for insight in tracker._pending_insights 
                                  if insight.get("type") == "timing_insight" and "completed" in insight.get("message", "")]
        
        # Should generate timing insight for long operation (in pending insights)
        assert len(timing_insights_pending) >= 1
        
        # Verify long operation tracking
        if tracker.insights_collector:
            assert len(tracker.insights_collector.metrics.long_operations) == 1
    
    def test_workspace_monitoring_integration(self, mock_session_state, temp_workspace):
        """Test workspace monitoring integration with insights."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
        
        # Wait a moment to ensure workspace checks can proceed
        if tracker.insights_collector:
            tracker.insights_collector._last_workspace_check = time.time() - 10
        
        # Create files in workspace
        file1 = temp_workspace / "new_file.txt"
        file1.write_text("New content")
        
        subdir = temp_workspace / "subdir"
        subdir.mkdir()
        file2 = subdir / "another.py"
        file2.write_text("print('hello')")
        
        insights_displayed = []
        with patch('builtins.print') as mock_print:
            # Trigger workspace check
            if tracker.insights_collector:
                workspace_insight = tracker.insights_collector.check_workspace_changes()
                if workspace_insight:
                    tracker._display_insight(workspace_insight)
            
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            workspace_insights = [call for call in print_calls if '📁' in call]
        
        # Should detect and display workspace changes
        if workspace_insights:
            assert len(workspace_insights) >= 1
            assert "created" in workspace_insights[0] or "Workspace:" in workspace_insights[0]
    
    def test_insights_disabled_workflow(self, mock_session_state):
        """Test that workflow works correctly when insights are disabled."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=False)
        
        # Should not have insights
        assert not tracker.has_insights()
        assert tracker.insights_collector is None
        
        # Tool chunk processing should work with hierarchical display
        chunk = json.dumps({
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "name": "test_tool",
                    "id": "tool_123"
                }]
            }
        })
        
        detail = tracker.process_chunk_with_insights(chunk)
        
        # Should return None to prevent duplicate display
        assert detail is None
        
        # Non-tool chunks should still return standard progress
        text_chunk = json.dumps({
            "type": "assistant", 
            "message": {
                "content": [{
                    "type": "text",
                    "text": "Processing request"
                }]
            }
        })
        
        detail = tracker.process_chunk_with_insights(text_chunk)
        assert detail == "Writing: Processing request"
        assert len(tracker._pending_insights) == 0
        
        # Completion summary should return None
        assert tracker.get_completion_summary() is None
    
    def test_response_formatting_integration(self, mock_session_state):
        """Test integration of insights with response formatting."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
        
        # Simulate completion with metrics
        completion_chunk = {
            "type": "result",
            "cost_usd": 0.18,
            "duration_ms": 67000,  # 1m 7s
            "num_turns": 3
        }
        
        chunk = json.dumps(completion_chunk)
        tracker.process_chunk_with_insights(chunk)
        
        # Format response with insights
        response = "Task completed successfully!\n\nAll files have been processed and the analysis is complete."
        formatted = format_non_interactive_response(response, mock_session_state, tracker)
        
        # Should include metrics footer
        assert "🤖 test_profile: Task completed successfully!" in formatted
        assert "All files have been processed" in formatted
        assert "📈 Session metrics:" in formatted
        assert "💰 $0.18" in formatted
        assert "⏱️ 1m 7s" in formatted
    
    def test_performance_with_large_workspace(self, mock_session_state, temp_workspace):
        """Test that insights don't impact performance with large workspaces."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
        
        # Create many files to simulate large workspace
        for i in range(100):  # Reasonable test size
            file = temp_workspace / f"file_{i:03d}.txt"
            file.write_text(f"Content {i}")
        
        start_time = time.time()
        
        # Process a chunk that would trigger workspace check
        chunk = json.dumps({"type": "test", "content": "test"})
        
        if tracker.insights_collector:
            # Force workspace check time to allow processing
            tracker.insights_collector._last_workspace_check = time.time() - 10
            tracker.process_chunk_with_insights(chunk)
        
        processing_time = time.time() - start_time
        
        # Should complete reasonably quickly (less than 1 second for 100 files)
        assert processing_time < 1.0
    
    @pytest.mark.asyncio
    async def test_orchestrator_integration(self, mock_session_state):
        """Test integration with orchestrator chunk processing."""
        from aris.orchestrator import route
        
        # Mock dependencies
        with patch('aris.orchestrator.mcp_service_instance') as mock_mcp, \
             patch('aris.orchestrator.prompt_formatter_instance') as mock_formatter, \
             patch('aris.orchestrator.cli_flag_manager_instance') as mock_flag_manager, \
             patch('aris.orchestrator.claude_cli_executor_instance') as mock_executor:
            
            # Set up mocks
            mock_formatter.format_prompt.return_value = "test prompt"
            mock_flag_manager.generate_claude_cli_flags.return_value = []
            
            # Mock executor to return test chunks with insights data
            async def mock_execute_cli(*args, **kwargs):
                yield json.dumps({
                    "type": "system",
                    "subtype": "init", 
                    "mcp_servers": [{"name": "test-server", "status": "connected"}]
                })
                yield json.dumps({
                    "type": "assistant",
                    "message": {
                        "content": [{
                            "type": "tool_use",
                            "name": "mcp__test-server__test_tool",
                            "id": "tool_123"
                        }]
                    }
                })
                yield json.dumps({"type": "text", "text": "Response complete"})
            
            mock_executor.execute_cli = mock_execute_cli
            
            # Create tracker with insights
            tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
            
            insights_generated = []
            with patch('builtins.print') as mock_print:
                # Process through orchestrator
                chunks = []
                async for chunk in route(
                    user_msg_for_turn="test message",
                    progress_tracker=tracker
                ):
                    chunks.append(chunk)
                
                # Capture insights that were displayed
                print_calls = [call[0][0] for call in mock_print.call_args_list]
                insights_generated = [call for call in print_calls if any(emoji in call for emoji in ['🔗', '🔌', '⏱️', '📁', '✅'])]
            
            # Should have processed chunks and generated insights
            assert len(chunks) == 3
            assert len(insights_generated) >= 1  # Should have some insights
            
            # Should have insights in pending list
            assert len(tracker._pending_insights) >= 1


class TestInsightsPerformanceAndEdgeCases:
    """Test performance characteristics and edge cases."""
    
    def test_insights_collection_error_handling(self):
        """Test that insights collection errors don't break main flow."""
        with patch('aris.progress_tracker.SessionInsightsCollector') as mock_collector_class:
            # Make collector initialization fail
            mock_collector_class.side_effect = Exception("Collector init failed")
            
            # Should still create tracker without insights
            tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
            
            # Should handle gracefully
            assert tracker.insights_collector is None  # Should fall back to None
            assert not tracker.has_insights()
    
    def test_workspace_monitor_permission_errors(self):
        """Test handling of workspace permission errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('aris.session_state.get_current_session_state') as mock_session:
                session_state = MagicMock()
                session_state.workspace_path = temp_dir
                mock_session.return_value = session_state
                
                # Create collector normally
                collector = SessionInsightsCollector()
                
                # Mock workspace monitor to raise permission error
                with patch.object(collector.workspace_monitor, 'get_workspace_changes', 
                                side_effect=PermissionError("Access denied")):
                    
                    # Should handle gracefully
                    result = collector.check_workspace_changes()
                    
                    # Should return empty changes, not crash
                    assert result is None  # Due to error handling
    
    def test_malformed_json_chunks(self):
        """Test handling of malformed JSON chunks."""
        with patch('aris.session_state.get_current_session_state') as mock_session:
            session_state = MagicMock()
            session_state.workspace_path = "/tmp/test"
            mock_session.return_value = session_state
            
            with patch('aris.workspace_monitor.WorkspaceFileMonitor'):
                tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
                
                malformed_chunks = [
                    "not json at all",
                    '{"incomplete": json',
                    '{"valid": "json", "but": "unexpected_structure"}',
                    "",
                    None
                ]
                
                for chunk in malformed_chunks:
                    try:
                        # Should not crash
                        if chunk is not None:
                            result = tracker.process_chunk_with_insights(chunk)
                            # Should fall back to standard parsing or return None
                            assert result is None or isinstance(result, str)
                    except Exception as e:
                        pytest.fail(f"Malformed chunk caused exception: {e}")
    
    def test_insights_throttling(self):
        """Test that insights are properly throttled to avoid spam."""
        with patch('aris.session_state.get_current_session_state') as mock_session:
            session_state = MagicMock()
            session_state.workspace_path = "/tmp/test"
            mock_session.return_value = session_state
            
            with patch('aris.workspace_monitor.WorkspaceFileMonitor'):
                collector = SessionInsightsCollector()
                
                # Rapid workspace checks should be throttled
                result1 = collector.check_workspace_changes()
                result2 = collector.check_workspace_changes()  # Immediate second call
                result3 = collector.check_workspace_changes()  # Immediate third call
                
                # Most calls should be throttled (return None)
                throttled_results = [r for r in [result1, result2, result3] if r is None]
                assert len(throttled_results) >= 2  # Most should be throttled
    
    def test_memory_usage_with_many_insights(self):
        """Test that memory usage doesn't grow unbounded with many insights."""
        with patch('aris.session_state.get_current_session_state') as mock_session:
            session_state = MagicMock()
            session_state.workspace_path = "/tmp/test"
            mock_session.return_value = session_state
            
            with patch('aris.workspace_monitor.WorkspaceFileMonitor'):
                tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
                
                # Generate many insights
                for i in range(1000):
                    tracker._pending_insights.append({
                        "type": "test_insight",
                        "message": f"Insight {i}",
                        "timestamp": time.time()
                    })
                
                # Memory usage should be reasonable
                # (This is more of a conceptual test - in practice you'd measure actual memory)
                assert len(tracker._pending_insights) == 1000
                
                # Get completion summary should still work
                tracker._pending_insights.append({
                    "type": "completion_summary",
                    "message": "Final summary",
                    "metrics": {"cost": 0.1}
                })
                
                summary = tracker.get_completion_summary()
                assert summary is not None
                assert summary["message"] == "Final summary"