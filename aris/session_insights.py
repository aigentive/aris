"""
Session insights collection and analysis for ARIS progress tracking.
Provides actionable insights about external service usage, timing, and resource consumption.
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from .logging_utils import log_debug
from .workspace_monitor import WorkspaceFileMonitor


@dataclass
class SessionMetrics:
    """Real-time session metrics collected from JSON chunks"""
    start_time: float
    current_cost_usd: float = 0.0
    api_calls_made: int = 0
    tools_executed: Dict[str, int] = field(default_factory=dict)
    mcp_servers_connected: List[str] = field(default_factory=list)
    external_operations: List[Dict[str, Any]] = field(default_factory=list)  # MCP operations
    long_operations: List[Dict[str, Any]] = field(default_factory=list)  # Operations >10s
    errors_encountered: List[str] = field(default_factory=list)
    
    # Workspace tracking (set by workspace monitor)
    workspace_files_created: List[str] = field(default_factory=list)
    workspace_files_modified: List[str] = field(default_factory=list)
    workspace_files_deleted: List[str] = field(default_factory=list)
    
    @property
    def elapsed_time(self) -> float:
        return time.time() - self.start_time
    
    @property
    def elapsed_time_formatted(self) -> str:
        minutes, seconds = divmod(int(self.elapsed_time), 60)
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


class SessionInsightsCollector:
    """Collects and analyzes session data from JSON chunks"""
    
    def __init__(self):
        self.metrics = SessionMetrics(start_time=time.time())
        self._tool_start_times: Dict[str, float] = {}
        self._last_insight_time = time.time()
        self._last_workspace_check = time.time()
        
        # Get workspace from session state (always available in ARIS)
        from .session_state import get_current_session_state
        session_state = get_current_session_state()
        workspace_path = session_state.workspace_path if session_state else os.getcwd()
        
        self.workspace_monitor = WorkspaceFileMonitor(workspace_path)
        
    def process_chunk(self, chunk: str) -> Optional[Dict[str, Any]]:
        """Process JSON chunk and return insight if warranted"""
        try:
            data = json.loads(chunk)
            insight = None
            
            # Track system initialization
            if data.get("type") == "system" and data.get("subtype") == "init":
                insight = self._process_init_event(data)
            
            # Track tool usage
            elif data.get("type") == "assistant":
                insight = self._process_tool_start(data)
                
            # Track tool results and costs
            elif data.get("type") == "user":
                insight = self._process_tool_result(data)
                
            # Track final results with cost information
            elif data.get("type") == "result":
                insight = self._process_completion(data)
                
            return insight
            
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
    
    def _process_init_event(self, data: Dict) -> Optional[Dict[str, Any]]:
        """Process system initialization event"""
        mcp_servers = data.get("mcp_servers", [])
        connected_servers = [s["name"] for s in mcp_servers if s.get("status") == "connected"]
        self.metrics.mcp_servers_connected = connected_servers
        
        if len(connected_servers) > 0:
            return {
                "type": "resource_insight",
                "message": f"Connected to {len(connected_servers)} external service(s): {', '.join(connected_servers)}",
                "show_immediately": True
            }
        return None
    
    def _process_tool_start(self, data: Dict) -> Optional[Dict[str, Any]]:
        """Process tool execution start"""
        content = data.get("message", {}).get("content", [])
        
        for item in content:
            if item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                tool_id = item.get("id", "")
                
                # Track tool usage
                clean_tool_name = self._clean_tool_name(tool_name)
                self.metrics.tools_executed[clean_tool_name] = self.metrics.tools_executed.get(clean_tool_name, 0) + 1
                self._tool_start_times[tool_id] = time.time()
                
                # Check for potentially expensive operations
                insight = self._check_potential_cost_operation(tool_name, item.get("input", {}))
                if insight:
                    return insight
                    
        return None
    
    def _process_tool_result(self, data: Dict) -> Optional[Dict[str, Any]]:
        """Process tool execution result"""
        content = data.get("message", {}).get("content", [])
        
        for item in content:
            if item.get("type") == "tool_result":
                tool_id = item.get("tool_use_id", "")
                result_content = item.get("content", "")
                is_error = item.get("is_error", False)
                
                # Track execution time
                if tool_id in self._tool_start_times:
                    execution_time = time.time() - self._tool_start_times[tool_id]
                    del self._tool_start_times[tool_id]
                else:
                    execution_time = 0
                
                if is_error:
                    self.metrics.errors_encountered.append(str(result_content)[:100])
                    return None
                
                # Track long operations
                if execution_time > 10.0:
                    self.metrics.long_operations.append({
                        "tool_id": tool_id,
                        "execution_time": execution_time,
                        "timestamp": time.time()
                    })
                
                # Check for timing insights
                return self._analyze_tool_result(result_content, execution_time)
                
        return None
    
    def _process_completion(self, data: Dict) -> Optional[Dict[str, Any]]:
        """Process final completion event with cost data"""
        total_cost = data.get("cost_usd", 0.0)
        duration_ms = data.get("duration_ms", 0)
        num_turns = data.get("num_turns", 0)
        
        self.metrics.current_cost_usd = total_cost
        
        # Generate completion summary
        return {
            "type": "completion_summary",
            "message": self._generate_completion_summary(total_cost, duration_ms, num_turns),
            "show_immediately": True,
            "metrics": {
                "total_cost": total_cost,
                "duration_seconds": duration_ms / 1000,
                "num_turns": num_turns,
                "tools_used": dict(self.metrics.tools_executed),
                "files_created": len(self.metrics.workspace_files_created),
                "files_modified": len(self.metrics.workspace_files_modified)
            }
        }
    
    def _check_potential_cost_operation(self, tool_name: str, tool_input: Dict) -> Optional[Dict[str, Any]]:
        """Identify potentially costly operations based on ARIS core patterns"""
        # Only predict costs for ARIS built-in expensive operations
        core_expensive_operations = {
            # Only WebSearch from core ARIS tools has measurable cost/time
            "WebSearch": {
                "reason": "external API calls",
                "time_estimate": "5-15s",
                "description": "web search operation"
            }
        }
        
        clean_name = self._clean_tool_name(tool_name)
        
        # For MCP tools, we can only identify them as external operations
        if tool_name.startswith("mcp__"):
            # Extract server name for context
            parts = tool_name.split("__")
            server_name = parts[1] if len(parts) >= 3 else "unknown"
            
            # Only flag if this is the first time seeing this tool
            if self.metrics.tools_executed.get(clean_name, 0) == 1:  # First time seeing this tool
                return {
                    "type": "external_operation_insight",
                    "message": f"External operation: {clean_name} via {server_name} service",
                    "show_immediately": False,  # Don't interrupt flow
                    "details": {
                        "server": server_name,
                        "tool": clean_name,
                        "note": "External service - timing and costs depend on provider"
                    }
                }
        
        # Check core ARIS expensive operations
        elif clean_name in core_expensive_operations:
            operation = core_expensive_operations[clean_name]
            
            return {
                "type": "timing_insight", 
                "message": f"Starting {operation['description']} - {operation['reason']} ({operation['time_estimate']})",
                "show_immediately": True,
                "details": {
                    "time_estimate": operation["time_estimate"],
                    "reason": operation["reason"]
                }
            }
        
        return None
    
    def _analyze_tool_result(self, result_content: str, execution_time: float) -> Optional[Dict[str, Any]]:
        """Analyze tool results using workspace monitoring, not pattern matching"""
        # Don't try to parse unknown result formats
        # Instead, rely on workspace monitoring for file tracking
        
        # Only provide timing insight for operations that took significant time
        if execution_time > 10.0:  # Operations over 10 seconds
            return {
                "type": "timing_insight",
                "message": f"Operation completed ({execution_time:.1f}s)",
                "show_immediately": False,
                "details": {
                    "execution_time": execution_time
                }
            }
        
        return None
    
    def check_workspace_changes(self) -> Optional[Dict[str, Any]]:
        """Check for workspace file changes and update metrics"""
            
        # Only check every 5 seconds to avoid overhead
        if time.time() - self._last_workspace_check < 5.0:
            return None
            
        # Safety check: disable monitoring in very large directories
        if self.workspace_monitor and len(self.workspace_monitor._initial_snapshot) > 5000:
            self.workspace_monitor.disable_monitoring()
            return {
                "type": "workspace_insight", 
                "message": "Workspace monitoring disabled (large directory)",
                "show_immediately": False
            }
            
        self._last_workspace_check = time.time()
        
        changes = self.workspace_monitor.get_workspace_changes()
        
        # Update metrics with new changes
        new_files = len(changes["created"])
        modified_files = len(changes["modified"])
        deleted_files = len(changes["deleted"])
        
        if new_files > 0 or modified_files > 0 or deleted_files > 0:
            # Update metrics
            self.metrics.workspace_files_created.extend(changes["created"])
            self.metrics.workspace_files_modified.extend(changes["modified"]) 
            self.metrics.workspace_files_deleted.extend(changes["deleted"])
            
            # Update baseline for next check
            self.workspace_monitor.update_baseline()
            
            # Generate insight message
            change_parts = []
            if new_files > 0:
                change_parts.append(f"{new_files} created")
            if modified_files > 0:
                change_parts.append(f"{modified_files} updated")
            if deleted_files > 0:
                change_parts.append(f"{deleted_files} deleted")
            
            return {
                "type": "workspace_insight",
                "message": f"Workspace: {', '.join(change_parts)}",
                "show_immediately": False,  # Don't interrupt flow
                "details": {
                    "created": changes["created"],
                    "modified": changes["modified"],
                    "deleted": changes["deleted"]
                }
            }
        
        return None

    def _generate_completion_summary(self, total_cost: float, duration_ms: int, num_turns: int) -> str:
        """Generate final completion summary"""
        duration_formatted = f"{duration_ms // 60000}m {(duration_ms % 60000) // 1000}s" if duration_ms >= 60000 else f"{duration_ms // 1000}s"
        
        summary_parts = [f"Task completed in {duration_formatted}"]
        
        if total_cost > 0:
            summary_parts.append(f"${total_cost:.2f} total cost")
        
        if self.metrics.workspace_files_created:
            summary_parts.append(f"{len(self.metrics.workspace_files_created)} files created")
            
        if self.metrics.workspace_files_modified:
            summary_parts.append(f"{len(self.metrics.workspace_files_modified)} files updated")
        
        return " • ".join(summary_parts)
    
    def _clean_tool_name(self, tool_name: str) -> str:
        """Clean MCP prefixes from tool names"""
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            if len(parts) >= 3:
                return parts[-1]
            return tool_name.replace("mcp__", "")
        return tool_name
    

    def should_show_progress_insight(self) -> bool:
        """Determine if enough time has passed to show a progress insight"""
        return (time.time() - self._last_insight_time) > 15.0  # Show insights every 15 seconds max
    
    def get_current_progress_insight(self) -> Optional[str]:
        """Get current progress insight if warranted"""
        if not self.should_show_progress_insight():
            return None
            
        self._last_insight_time = time.time()
        
        # Generate progress insight based on current metrics
        if len(self.metrics.external_operations) > 0:
            return f"Processing: {len(self.metrics.external_operations)} external operations • {self.metrics.elapsed_time_formatted} elapsed"
        elif len(self.metrics.long_operations) > 0:
            return f"Progress: {len(self.metrics.long_operations)} time-intensive operations • {self.metrics.elapsed_time_formatted} elapsed"
        
        return None