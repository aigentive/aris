"""
Tests for session insights collection and analysis.
"""
import json
import time
import tempfile
import os
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from aris.session_insights import SessionInsightsCollector, SessionMetrics
from aris.workspace_monitor import WorkspaceFileMonitor


class TestSessionMetrics:
    """Test the SessionMetrics dataclass."""
    
    def test_session_metrics_creation(self):
        """Test basic SessionMetrics creation."""
        start_time = time.time()
        metrics = SessionMetrics(start_time=start_time)
        
        assert metrics.start_time == start_time
        assert metrics.current_cost_usd == 0.0
        assert metrics.api_calls_made == 0
        assert isinstance(metrics.tools_executed, dict)
        assert len(metrics.tools_executed) == 0
        assert isinstance(metrics.mcp_servers_connected, list)
        assert len(metrics.mcp_servers_connected) == 0
    
    def test_elapsed_time_property(self):
        """Test elapsed time calculation."""
        start_time = time.time() - 10  # 10 seconds ago
        metrics = SessionMetrics(start_time=start_time)
        
        elapsed = metrics.elapsed_time
        assert 9.0 <= elapsed <= 11.0  # Allow some margin for test execution time
    
    def test_elapsed_time_formatted(self):
        """Test formatted elapsed time."""
        # Test seconds only
        start_time = time.time() - 30
        metrics = SessionMetrics(start_time=start_time)
        formatted = metrics.elapsed_time_formatted
        assert "30s" in formatted or "29s" in formatted or "31s" in formatted
        
        # Test minutes and seconds
        start_time = time.time() - 150  # 2.5 minutes
        metrics = SessionMetrics(start_time=start_time)
        formatted = metrics.elapsed_time_formatted
        assert "2m" in formatted and "30s" in formatted
    
    def test_workspace_tracking_lists(self):
        """Test workspace tracking list initialization."""
        metrics = SessionMetrics(start_time=time.time())
        
        assert isinstance(metrics.workspace_files_created, list)
        assert isinstance(metrics.workspace_files_modified, list)
        assert isinstance(metrics.workspace_files_deleted, list)
        assert len(metrics.workspace_files_created) == 0
        assert len(metrics.workspace_files_modified) == 0
        assert len(metrics.workspace_files_deleted) == 0


class TestSessionInsightsCollector:
    """Test the SessionInsightsCollector class."""
    
    @pytest.fixture
    def mock_session_state(self):
        """Mock session state for testing."""
        with patch('aris.session_state.get_current_session_state') as mock:
            session_state = MagicMock()
            session_state.workspace_path = "/tmp/test_workspace"
            mock.return_value = session_state
            yield session_state
    
    @pytest.fixture
    def collector(self, mock_session_state):
        """Create a SessionInsightsCollector for testing."""
        with patch.object(WorkspaceFileMonitor, '__init__', return_value=None):
            with patch.object(WorkspaceFileMonitor, 'get_workspace_changes', return_value={"created": [], "modified": [], "deleted": []}):
                collector = SessionInsightsCollector()
                # Mock the workspace monitor to avoid actual file system operations
                collector.workspace_monitor = MagicMock()
                collector.workspace_monitor._initial_snapshot = {}
                collector.workspace_monitor.get_workspace_changes.return_value = {"created": [], "modified": [], "deleted": []}
                yield collector
    
    def test_collector_initialization(self, collector):
        """Test SessionInsightsCollector initialization."""
        assert isinstance(collector.metrics, SessionMetrics)
        assert isinstance(collector._tool_start_times, dict)
        assert collector._last_insight_time > 0
        assert collector._last_workspace_check > 0
    
    def test_process_chunk_invalid_json(self, collector):
        """Test processing invalid JSON chunks."""
        result = collector.process_chunk("invalid json")
        assert result is None
        
        result = collector.process_chunk("")
        assert result is None
    
    def test_process_init_event(self, collector):
        """Test processing system initialization events."""
        init_chunk = json.dumps({
            "type": "system",
            "subtype": "init",
            "mcp_servers": [
                {"name": "test-server", "status": "connected"},
                {"name": "other-server", "status": "disconnected"}
            ]
        })
        
        result = collector.process_chunk(init_chunk)
        
        assert result is not None
        assert result["type"] == "resource_insight"
        assert "Connected to 1 external service(s): test-server" in result["message"]
        assert result["show_immediately"] is True
        assert "test-server" in collector.metrics.mcp_servers_connected
        assert "other-server" not in collector.metrics.mcp_servers_connected
    
    def test_process_tool_start_mcp_tool(self, collector):
        """Test processing MCP tool execution start."""
        tool_chunk = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "mcp__openai-image-mcp__generate_image",
                        "id": "tool_123",
                        "input": {"prompt": "test"}
                    }
                ]
            }
        })
        
        result = collector.process_chunk(tool_chunk)
        
        assert result is not None
        assert result["type"] == "external_operation_insight"
        assert "generate_image via openai-image-mcp service" in result["message"]
        assert result["show_immediately"] is False
        assert "generate_image" in collector.metrics.tools_executed
        assert collector.metrics.tools_executed["generate_image"] == 1
        assert "tool_123" in collector._tool_start_times
    
    def test_process_tool_start_core_tool(self, collector):
        """Test processing core ARIS tool execution start."""
        tool_chunk = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "WebSearch",
                        "id": "tool_456",
                        "input": {"query": "test"}
                    }
                ]
            }
        })
        
        result = collector.process_chunk(tool_chunk)
        
        assert result is not None
        assert result["type"] == "timing_insight"
        assert "web search operation" in result["message"]
        assert "5-15s" in result["message"]
        assert result["show_immediately"] is True
        assert "WebSearch" in collector.metrics.tools_executed
    
    def test_process_tool_result_success(self, collector):
        """Test processing successful tool results."""
        # First set up a tool start time
        collector._tool_start_times["tool_123"] = time.time() - 15  # 15 seconds ago
        
        result_chunk = json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": "Operation completed successfully",
                        "is_error": False
                    }
                ]
            }
        })
        
        result = collector.process_chunk(result_chunk)
        
        assert result is not None
        assert result["type"] == "timing_insight"
        assert "Operation completed" in result["message"]
        assert "15." in result["message"]  # Should show execution time
        assert "tool_123" not in collector._tool_start_times  # Should be removed
        assert len(collector.metrics.long_operations) == 1
    
    def test_process_tool_result_error(self, collector):
        """Test processing tool result errors."""
        collector._tool_start_times["tool_123"] = time.time()
        
        error_chunk = json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": "Error: Something went wrong",
                        "is_error": True
                    }
                ]
            }
        })
        
        result = collector.process_chunk(error_chunk)
        
        assert result is None  # Errors don't generate insights
        assert len(collector.metrics.errors_encountered) == 1
        assert "Error: Something went wrong" in collector.metrics.errors_encountered[0]
    
    def test_process_completion_event(self, collector):
        """Test processing completion events with cost data."""
        completion_chunk = json.dumps({
            "type": "result",
            "cost_usd": 0.25,
            "duration_ms": 45000,  # 45 seconds
            "num_turns": 3
        })
        
        result = collector.process_chunk(completion_chunk)
        
        assert result is not None
        assert result["type"] == "completion_summary"
        assert "Task completed in 45s" in result["message"]
        assert "$0.25 total cost" in result["message"]
        assert result["show_immediately"] is True
        assert collector.metrics.current_cost_usd == 0.25
        
        metrics = result["metrics"]
        assert metrics["total_cost"] == 0.25
        assert metrics["duration_seconds"] == 45.0
        assert metrics["num_turns"] == 3
    
    def test_clean_tool_name(self, collector):
        """Test MCP tool name cleaning."""
        # Test MCP tool name cleaning
        assert collector._clean_tool_name("mcp__server__tool") == "tool"
        assert collector._clean_tool_name("mcp__complex-server__nested__tool") == "tool"
        assert collector._clean_tool_name("regular_tool") == "regular_tool"
        assert collector._clean_tool_name("mcp__simple") == "simple"
    
    def test_should_show_progress_insight_timing(self, collector):
        """Test progress insight timing logic."""
        # Should not show immediately after creation
        assert collector.should_show_progress_insight() is False
        
        # Simulate time passing
        collector._last_insight_time = time.time() - 20  # 20 seconds ago
        assert collector.should_show_progress_insight() is True
    
    def test_get_current_progress_insight(self, collector):
        """Test progress insight generation."""
        # Set up some long operations
        collector.metrics.long_operations = [
            {"tool_id": "1", "execution_time": 15, "timestamp": time.time()},
            {"tool_id": "2", "execution_time": 25, "timestamp": time.time()}
        ]
        collector._last_insight_time = time.time() - 20  # Force insight generation
        
        insight = collector.get_current_progress_insight()
        
        assert insight is not None
        assert "Progress: 2 time-intensive operations" in insight
        assert "elapsed" in insight
    
    def test_check_workspace_changes_throttling(self, collector):
        """Test workspace change checking throttling."""
        # Should return None when called too frequently
        result1 = collector.check_workspace_changes()
        result2 = collector.check_workspace_changes()  # Immediate second call
        
        assert result2 is None  # Should be throttled
    
    def test_check_workspace_changes_with_changes(self, collector):
        """Test workspace change detection and reporting."""
        # Set up last check time to allow processing
        collector._last_workspace_check = time.time() - 10
        
        # Mock workspace changes
        collector.workspace_monitor.get_workspace_changes.return_value = {
            "created": ["new_file.txt", "another.py"],
            "modified": ["existing.md"],
            "deleted": []
        }
        
        result = collector.check_workspace_changes()
        
        assert result is not None
        assert result["type"] == "workspace_insight"
        assert "Workspace: 2 created, 1 updated" in result["message"]
        assert result["show_immediately"] is False
        
        # Check that metrics were updated
        assert len(collector.metrics.workspace_files_created) == 2
        assert len(collector.metrics.workspace_files_modified) == 1
        assert "new_file.txt" in collector.metrics.workspace_files_created
        assert "existing.md" in collector.metrics.workspace_files_modified
    
    def test_generate_completion_summary(self, collector):
        """Test completion summary generation."""
        # Set up some workspace changes
        collector.metrics.workspace_files_created = ["file1.txt", "file2.py"]
        collector.metrics.workspace_files_modified = ["file3.md"]
        
        summary = collector._generate_completion_summary(0.15, 90000, 2)  # 1.5 minutes
        
        assert "Task completed in 1m 30s" in summary
        assert "$0.15 total cost" in summary
        assert "2 files created" in summary
        assert "1 files updated" in summary
    
    def test_large_directory_monitoring_disable(self, collector):
        """Test automatic monitoring disable for large directories."""
        # Set up last check time to allow processing
        collector._last_workspace_check = time.time() - 10
        
        # Mock large directory
        collector.workspace_monitor._initial_snapshot = {f"file_{i}": {} for i in range(6000)}
        
        result = collector.check_workspace_changes()
        
        assert result is not None
        assert result["type"] == "workspace_insight"
        assert "Workspace monitoring disabled (large directory)" in result["message"]