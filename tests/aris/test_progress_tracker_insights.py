"""
Tests for ProgressTracker with insights functionality.
"""
import json
import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from aris.progress_tracker import ProgressTracker, create_progress_tracker, ExecutionPhase
from aris.session_insights import SessionInsightsCollector


class TestProgressTrackerWithInsights:
    """Test ProgressTracker with insights enabled."""
    
    @pytest.fixture
    def mock_insights_collector(self):
        """Mock SessionInsightsCollector for testing."""
        collector = MagicMock(spec=SessionInsightsCollector)
        collector.process_chunk.return_value = None
        collector.check_workspace_changes.return_value = None
        collector.get_current_progress_insight.return_value = None
        return collector
    
    def test_progress_tracker_with_insights_enabled(self):
        """Test ProgressTracker creation with insights enabled."""
        with patch('aris.progress_tracker.SessionInsightsCollector') as mock_collector_class:
            tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=True)
            
            assert tracker.has_insights() is True
            assert tracker.insights_collector is not None
            assert isinstance(tracker._pending_insights, list)
            mock_collector_class.assert_called_once()
    
    def test_progress_tracker_with_insights_disabled(self):
        """Test ProgressTracker creation with insights disabled."""
        tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=False)
        
        assert tracker.has_insights() is False
        assert tracker.insights_collector is None
        assert isinstance(tracker._pending_insights, list)
        assert len(tracker._pending_insights) == 0
    
    def test_process_chunk_with_insights_enabled(self, mock_insights_collector):
        """Test chunk processing with insights enabled."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
            
            # Mock insight return
            mock_insight = {
                "type": "timing_insight",
                "message": "Test insight",
                "show_immediately": True
            }
            mock_insights_collector.process_chunk.return_value = mock_insight
            
            with patch('builtins.print') as mock_print:
                chunk = '{"type": "test", "content": "test"}'
                result = tracker.process_chunk_with_insights(chunk)
                
                # Should call insights collector
                mock_insights_collector.process_chunk.assert_called_once_with(chunk)
                mock_insights_collector.check_workspace_changes.assert_called_once()
                mock_insights_collector.get_current_progress_insight.assert_called_once()
                
                # Should store insight
                assert len(tracker._pending_insights) == 1
                assert tracker._pending_insights[0] == mock_insight
                
                # Should display immediate insight (look for the emoji and message)
                print_calls = [call[0][0] for call in mock_print.call_args_list]
                insight_prints = [call for call in print_calls if "⏱️" in call and "Test insight" in call]
                assert len(insight_prints) >= 1
    
    def test_process_chunk_with_insights_disabled(self):
        """Test chunk processing with insights disabled."""
        tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=False)
        
        chunk = '{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "test_tool"}]}}'
        
        with patch('aris.progress_tracker.parse_chunk_for_progress_detail') as mock_parse:
            mock_parse.return_value = "Using test_tool"
            
            result = tracker.process_chunk_with_insights(chunk)
            
            # Should fall back to standard parsing
            mock_parse.assert_called_once_with(chunk)
            assert result == "Using test_tool"
            assert len(tracker._pending_insights) == 0
    
    def test_process_chunk_insights_error_handling(self, mock_insights_collector):
        """Test error handling in insights processing."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=True)
            
            # Mock insights collector to raise exception
            mock_insights_collector.process_chunk.side_effect = Exception("Test error")
            
            with patch('aris.progress_tracker.log_debug') as mock_log:
                chunk = '{"type": "test"}'
                result = tracker.process_chunk_with_insights(chunk)
                
                # Should log error but not crash
                mock_log.assert_called_with("Error in insights collection: Test error")
                # Should still return standard progress detail (may be None for invalid chunks)
                assert result is None or isinstance(result, str)  # Falls back to parse_chunk_for_progress_detail
    
    def test_display_insight_with_different_types(self, mock_insights_collector):
        """Test displaying different types of insights."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
            
            test_insights = [
                {"type": "resource_insight", "message": "Connected to services"},
                {"type": "timing_insight", "message": "Operation will take 10s"},
                {"type": "external_operation_insight", "message": "External operation starting"},
                {"type": "workspace_insight", "message": "2 files created"},
                {"type": "completion_summary", "message": "Task completed"},
                {"type": "unknown_type", "message": "Unknown insight"}
            ]
            
            expected_emojis = ["🔗", "⏱️", "🔌", "📁", "✅", "ℹ️"]
            
            with patch('builtins.print') as mock_print:
                for insight, expected_emoji in zip(test_insights, expected_emojis):
                    tracker._display_insight(insight)
                    
                    # Check that correct emoji was used
                    call_args = mock_print.call_args[0][0]
                    assert call_args.startswith(expected_emoji)
                    assert insight["message"] in call_args
    
    def test_display_insight_show_progress_disabled(self, mock_insights_collector):
        """Test that insights are not displayed when show_progress is disabled."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=True)
            
            insight = {"type": "timing_insight", "message": "Test message"}
            
            with patch('builtins.print') as mock_print:
                tracker._display_insight(insight)
                
                # Should not print anything
                mock_print.assert_not_called()
    
    def test_display_progress_insight(self, mock_insights_collector):
        """Test displaying progress insights."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
            
            with patch('builtins.print') as mock_print:
                tracker._display_progress_insight("Progress message")
                
                mock_print.assert_called_once_with("📊 Progress message", flush=True)
    
    def test_get_completion_summary_with_insights(self, mock_insights_collector):
        """Test getting completion summary when insights are enabled."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=True)
            
            # Add some insights including a completion summary
            tracker._pending_insights = [
                {"type": "timing_insight", "message": "Some timing"},
                {"type": "completion_summary", "message": "Task done", "metrics": {"cost": 0.10}},
                {"type": "workspace_insight", "message": "Files changed"}
            ]
            
            summary = tracker.get_completion_summary()
            
            assert summary is not None
            assert summary["type"] == "completion_summary"
            assert summary["message"] == "Task done"
            assert summary["metrics"]["cost"] == 0.10
    
    def test_get_completion_summary_without_insights(self):
        """Test getting completion summary when insights are disabled."""
        tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=False)
        
        summary = tracker.get_completion_summary()
        
        assert summary is None
    
    def test_get_completion_summary_no_completion_insights(self, mock_insights_collector):
        """Test getting completion summary when no completion insights exist."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=False, enable_insights=True)
            
            # Add non-completion insights
            tracker._pending_insights = [
                {"type": "timing_insight", "message": "Some timing"},
                {"type": "workspace_insight", "message": "Files changed"}
            ]
            
            summary = tracker.get_completion_summary()
            
            assert summary is None
    
    def test_workspace_changes_processing(self, mock_insights_collector):
        """Test workspace changes processing during chunk analysis."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
            
            # Mock workspace insight
            workspace_insight = {
                "type": "workspace_insight",
                "message": "3 files created",
                "show_immediately": False
            }
            mock_insights_collector.check_workspace_changes.return_value = workspace_insight
            
            with patch('builtins.print') as mock_print:
                chunk = '{"type": "test"}'
                tracker.process_chunk_with_insights(chunk)
                
                # Should display workspace insight
                mock_print.assert_called_with("📁 3 files created", flush=True)
    
    def test_progress_insight_display(self, mock_insights_collector):
        """Test progress insight display during chunk processing."""
        with patch('aris.progress_tracker.SessionInsightsCollector', return_value=mock_insights_collector):
            tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
            
            # Mock progress insight
            progress_insight = "Processing: 2 external operations • 1m 30s elapsed"
            mock_insights_collector.get_current_progress_insight.return_value = progress_insight
            
            with patch('builtins.print') as mock_print:
                chunk = '{"type": "test"}'
                tracker.process_chunk_with_insights(chunk)
                
                # Should display progress insight
                mock_print.assert_called_with("📊 Processing: 2 external operations • 1m 30s elapsed", flush=True)


class TestCreateProgressTrackerWithInsights:
    """Test the enhanced create_progress_tracker factory function."""
    
    def test_create_tracker_insights_enabled_default(self):
        """Test creating tracker with insights enabled by default."""
        with patch('aris.progress_tracker.SessionInsightsCollector'):
            tracker = create_progress_tracker(interactive=False, verbose=False)
            
            assert tracker.has_insights() is True
    
    def test_create_tracker_insights_disabled(self):
        """Test creating tracker with insights disabled."""
        tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=False)
        
        assert tracker.has_insights() is False
    
    def test_create_tracker_insights_enabled_explicit(self):
        """Test creating tracker with insights explicitly enabled."""
        with patch('aris.progress_tracker.SessionInsightsCollector'):
            tracker = create_progress_tracker(interactive=False, verbose=False, enable_insights=True)
            
            assert tracker.has_insights() is True
    
    def test_create_tracker_verbose_mode_insights(self):
        """Test that verbose mode doesn't affect insights setting."""
        with patch('aris.progress_tracker.SessionInsightsCollector'):
            # Verbose mode should disable progress display but not insights
            tracker = create_progress_tracker(interactive=False, verbose=True, enable_insights=True)
            
            assert tracker.show_progress is False  # Verbose disables progress display
            assert tracker.has_insights() is True  # But insights should still be enabled
    
    def test_create_tracker_interactive_mode_insights(self):
        """Test creating interactive tracker with insights."""
        with patch('aris.progress_tracker.SessionInsightsCollector'):
            tracker = create_progress_tracker(interactive=True, verbose=False, enable_insights=True)
            
            assert tracker.interactive is True
            assert tracker.show_progress is True
            assert tracker.has_insights() is True
    
    def test_factory_function_backward_compatibility(self):
        """Test that factory function maintains backward compatibility."""
        # Test with old signature (no enable_insights parameter)
        tracker = create_progress_tracker(interactive=False, verbose=False)
        
        # Should still work and have insights enabled by default
        assert tracker.interactive is False
        assert tracker.show_progress is True
    
    @pytest.mark.parametrize("interactive,verbose,enable_insights,expected_show_progress,expected_has_insights", [
        (True, False, True, True, True),
        (True, False, False, True, False),
        (True, True, True, False, True),
        (True, True, False, False, False),
        (False, False, True, True, True),
        (False, False, False, True, False),
        (False, True, True, False, True),
        (False, True, False, False, False),
    ])
    def test_factory_function_parameter_combinations(self, interactive, verbose, enable_insights, 
                                                   expected_show_progress, expected_has_insights):
        """Test various parameter combinations for the factory function."""
        with patch('aris.progress_tracker.SessionInsightsCollector'):
            tracker = create_progress_tracker(
                interactive=interactive, 
                verbose=verbose, 
                enable_insights=enable_insights
            )
            
            assert tracker.interactive == interactive
            assert tracker.show_progress == expected_show_progress
            assert tracker.has_insights() == expected_has_insights


class TestProgressTrackerInsightsIntegration:
    """Test integration between ProgressTracker and insights components."""
    
    def test_real_json_chunk_processing(self):
        """Test processing real JSON chunks with insights."""
        with patch('aris.session_state.get_current_session_state') as mock_session:
            with patch('aris.workspace_monitor.WorkspaceFileMonitor'):
                # Set up session state mock
                session_state = MagicMock()
                session_state.workspace_path = "/tmp/test"
                mock_session.return_value = session_state
                
                tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
                
                # Test with real-like JSON chunks
                init_chunk = json.dumps({
                    "type": "system",
                    "subtype": "init", 
                    "mcp_servers": [{"name": "test-server", "status": "connected"}]
                })
                
                tool_chunk = json.dumps({
                    "type": "assistant",
                    "message": {
                        "content": [{
                            "type": "tool_use",
                            "name": "mcp__test-server__generate_content",
                            "id": "tool_123"
                        }]
                    }
                })
                
                with patch('builtins.print') as mock_print:
                    # Process chunks
                    tracker.process_chunk_with_insights(init_chunk)
                    tracker.process_chunk_with_insights(tool_chunk)
                    
                    # Should have generated insights
                    assert len(tracker._pending_insights) >= 1
                    # Should have printed some insights
                    assert mock_print.call_count >= 1
    
    def test_insights_dont_break_standard_progress(self):
        """Test that insights don't interfere with standard progress tracking."""
        with patch('aris.session_state.get_current_session_state') as mock_session:
            with patch('aris.workspace_monitor.WorkspaceFileMonitor'):
                session_state = MagicMock()
                session_state.workspace_path = "/tmp/test"
                mock_session.return_value = session_state
                
                tracker = ProgressTracker(interactive=False, show_progress=True, enable_insights=True)
                
                # Test standard progress tracking still works
                tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "Test detail")
                
                assert tracker.current_state.phase == ExecutionPhase.PROCESSING_INPUT
                assert tracker.current_state.detail == "Test detail"
                assert len(tracker.phase_history) == 1