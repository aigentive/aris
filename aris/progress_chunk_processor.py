"""
Enhanced chunk processor for extracting tool parameters and details from Claude CLI JSON chunks.
Builds on existing parse_chunk_for_progress_detail functionality.
"""
import json
from typing import Optional, Dict, Any


class ProgressChunkProcessor:
    """Enhanced chunk processor building on existing parse_chunk_for_progress_detail"""
    
    # Simple parameter formatters for core tools
    TOOL_FORMATTERS = {
        "Read": lambda params: f"Reading {params['file_path']}" + 
                              (f" (lines {params.get('offset', 1)}-{params.get('limit', 'end')})" if 'limit' in params else ""),
        "Write": lambda params: f"Writing to {params['file_path']} ({len(params['content'])} chars)",
        "Bash": lambda params: f"Running: {params['command'][:60]}{'...' if len(params['command']) > 60 else ''}",
        "Edit": lambda params: f"Editing {params['file_path']} ({params.get('expected_replacements', 1)} replacements)",
        "MultiEdit": lambda params: f"Editing {params['file_path']} ({len(params['edits'])} changes)",
        "WebSearch": lambda params: f"Searching: {params['query'][:40]}{'...' if len(params['query']) > 40 else ''}",
        "Glob": lambda params: f"Finding files: {params['pattern']}",
        "Grep": lambda params: f"Searching in files: {params['pattern']}",
        "LS": lambda params: f"Listing directory: {params['path']}",
        "WebFetch": lambda params: f"Fetching: {params['url'][:50]}{'...' if len(params['url']) > 50 else ''}",
        "Task": lambda params: f"Delegating task: {params['description']}"
    }
    
    def extract_tool_parameters(self, chunk_data: dict) -> Optional[str]:
        """Extract tool parameters for display using simple formatters"""
        content = chunk_data.get("message", {}).get("content", [])
        
        for item in content:
            if item.get("type") == "tool_use":
                return self.extract_single_tool_parameters(item)
        
        return None
    
    def extract_single_tool_parameters(self, tool_item: dict) -> Optional[str]:
        """Extract parameters for a single tool_use item"""
        tool_name = tool_item.get("name", "")
        parameters = tool_item.get("input", {})
        
        # Clean MCP prefixes
        clean_name = self._clean_tool_name(tool_name)
        
        # Use simple formatter if available
        if clean_name in self.TOOL_FORMATTERS:
            try:
                return self.TOOL_FORMATTERS[clean_name](parameters)
            except (KeyError, TypeError):
                # Fallback to basic display
                pass
        
        # For MCP tools, show basic info
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            server_name = parts[1] if len(parts) >= 3 else "unknown"
            return f"Using {clean_name} (via {server_name})"
        
        # Generic fallback
        return f"Using {clean_name}"
    
    def _clean_tool_name(self, tool_name: str) -> str:
        """Clean MCP prefixes from tool names"""
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            if len(parts) >= 3:
                return parts[-1]
            return tool_name.replace("mcp__", "")
        return tool_name