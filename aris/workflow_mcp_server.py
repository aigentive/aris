# Standard library imports
import os
import json
import logging
import asyncio
import subprocess
import importlib.metadata
from typing import Dict, Any, List, Optional, Union
from pathlib import Path

# Official MCP SDK imports
from mcp.server import Server as OfficialMCPServer
from mcp.server.sse import SseServerTransport
import mcp.types as mcp_types

# ASGI framework for hosting
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import PlainTextResponse
from starlette.requests import Request

# Import SSE Response class
from sse_starlette.sse import EventSourceResponse

# Local imports from ARIS
from .logging_utils import log_router_activity, log_error, log_warning, log_debug

# Setup module logger
logger = logging.getLogger(__name__)


class WorkflowMCPServer:
    """
    MCP server that provides workflow orchestration tools for coordinating
    multiple ARIS profiles in complex multi-agent workflows.
    """
    
    def __init__(self, 
                 host: str = "0.0.0.0", 
                 port: int = 8093):
        """
        Initialize the Workflow MCP Server.
        
        Args:
            host: Host address to bind the server to
            port: Port to listen on
        """
        self.host = host
        self.port = port
        
        # Initialize version info
        self._sdk_version = self._get_sdk_version_str()
        
        # Initialize the MCP server components
        server_name = "workflow_orchestrator"
        self.mcp_app = OfficialMCPServer(server_name)
        self.mcp_app.tools = {}  # Custom store for tool definitions
        logger.info(f"Initialized workflow MCP server with name: {server_name}")
        
        # Set up request handlers
        self._setup_request_handlers()
        
        # Initialize SSE transport
        self.sse_transport = SseServerTransport(endpoint="/../messages/")
        
        # Setup Starlette ASGI app
        self._setup_starlette_app()
        
        # Register workflow orchestration tools
        self._register_workflow_tools()
        
    def _get_sdk_version_str(self) -> str:
        """Get the version of the ARIS package for information purposes."""
        try:
            return importlib.metadata.version('aris')
        except (importlib.metadata.PackageNotFoundError, ImportError):
            return "unknown"
    
    def _setup_request_handlers(self):
        """Configure request handlers for MCP protocol interactions."""
        # Adapter for CallToolRequest
        async def call_tool_request_handler_adapter(req: mcp_types.CallToolRequest):
            # Pass already extracted name and arguments to our dispatcher
            tool_results_content = await self._handle_mcp_call_tool(req.params.name, (req.params.arguments or {}))
            
            # Determine if an error occurred based on our convention
            is_error = False
            if tool_results_content and isinstance(tool_results_content[0], mcp_types.TextContent):
                try:
                    error_check_data = json.loads(tool_results_content[0].text)
                    if isinstance(error_check_data, dict) and error_check_data.get("tool_execution_error"):
                        is_error = True
                except json.JSONDecodeError:
                    pass  # Not a JSON error structure, assume not an error
            
            return mcp_types.ServerResult(
                mcp_types.CallToolResult(content=list(tool_results_content), isError=is_error) 
            )
        self.mcp_app.request_handlers[mcp_types.CallToolRequest] = call_tool_request_handler_adapter
        
        # Adapter for ListToolsRequest
        async def list_tools_request_handler_adapter(req: mcp_types.ListToolsRequest):
            tool_defs = await self._handle_list_tools()
            return mcp_types.ServerResult(mcp_types.ListToolsResult(tools=tool_defs))
        self.mcp_app.request_handlers[mcp_types.ListToolsRequest] = list_tools_request_handler_adapter

    def _setup_starlette_app(self):
        """Set up the Starlette ASGI application with routing."""
        # Define the raw ASGI app for SSE connections
        async def sse_endpoint_asgi_app(scope, receive, send):
            if scope["path"] == "/mcp/sse/" or scope["path"] == "/mcp/sse":
                # Ensure tools are registered if needed
                if not self.mcp_app.tools:
                    logger.info("SSE ASGI App: No tools registered, registering workflow tools.")
                    self._register_workflow_tools()
                
                init_options = self.mcp_app.create_initialization_options()
                try:
                    async with self.sse_transport.connect_sse(scope, receive, send) as streams:
                        await self.mcp_app.run(streams[0], streams[1], init_options)
                except Exception as e:
                    logger.error(f"Error during SSE handling or mcp_app.run: {e}", exc_info=True)
                    pass
            else:
                logger.warning(f"sse_endpoint_asgi_app (mounted at /mcp/sse/) received unexpected internal scope path: {scope['path']}. Expected '/mcp/sse/' or '/mcp/sse'")
                response = PlainTextResponse("Not Found in SSE handler (bad internal path)", status_code=404)
                await response(scope, receive, send)
        
        mcp_routes = [
            Mount("/sse/", app=sse_endpoint_asgi_app),
            Mount("/messages/", app=self.sse_transport.handle_post_message)
        ]
        mcp_sub_app = Starlette(routes=mcp_routes)
        
        # The main app mounts the sub_app at /mcp
        self.starlette_app = Starlette(
            routes=[
                Mount("/mcp", app=mcp_sub_app),
            ]
        )
        logger.info("Starlette app configured with a sub-app for /mcp, containing /sse and /messages endpoints.")

    def _register_workflow_tools(self):
        """Register all workflow orchestration tools."""
        
        # Register execute_workflow_phase tool using same pattern as profile MCP server
        if "execute_workflow_phase" in self.mcp_app.tools:
            logger.warning("Tool definition for 'execute_workflow_phase' already exists. Overwriting.")
            
        self.mcp_app.tools["execute_workflow_phase"] = {
            "handler": self._handle_execute_workflow_phase,
            "description": "Execute an ARIS profile with workspace support for workflow orchestration",
            "input_schema": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Name of the ARIS profile to execute"
                    },
                    "workspace": {
                        "type": "string", 
                        "description": "Workspace directory name or path for the execution"
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Task instruction to send to the profile"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default: 300)",
                        "default": 300
                    }
                },
                "required": ["profile", "workspace", "instruction"]
            }
        }
        logger.info("Registered execute_workflow_phase tool")

    async def _handle_list_tools(self) -> list[mcp_types.Tool]:
        """Handle the ListTools request and return all available tools."""
        tools_list = []
        logger.debug(f"Preparing tool list. Found {len(self.mcp_app.tools)} tools in internal dict.")
        for tool_name, tool_def_dict in self.mcp_app.tools.items():
            logger.debug(f"Processing tool '{tool_name}' for ListTools response.")
            if "input_schema" not in tool_def_dict:
                logger.error(f"CRITICAL: 'input_schema' key MISSING from tool_def_dict for tool '{tool_name}'!")
                # Skip this tool if schema is missing to avoid validation error
                continue
            try:
                # Use the correct key expected by mcp.types.Tool (camelCase)
                tool_instance = mcp_types.Tool(
                    name=tool_name,
                    description=tool_def_dict.get("description", ""),
                    inputSchema=tool_def_dict.get("input_schema", {}) # Correct key: inputSchema
                )
                tools_list.append(tool_instance)
            except Exception as e:
                logger.error(f"Pydantic validation failed for tool '{tool_name}'. Error: {e}", exc_info=True)
                # Skip adding invalid tool
                continue
                
        return tools_list

    async def _handle_mcp_call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> List[mcp_types.TextContent]:
        """Handle MCP tool calls and route them to appropriate handlers."""
        logger.debug(f"Workflow MCP Server received call_tool request for tool: '{tool_name}' with arguments: {arguments}")
        
        # Log available tool keys for debugging
        available_tool_keys = list(self.mcp_app.tools.keys())
        logger.debug(f"Available tool keys at time of call: {available_tool_keys}")
        
        tool_definition = self.mcp_app.tools.get(tool_name)
        
        if not tool_definition:
            logger.error(f"Tool '{tool_name}' not found in available keys: {available_tool_keys}")
            return [mcp_types.TextContent(type="text", text=json.dumps({
                "tool_execution_error": True,
                "error_type": "ToolNotFound",
                "message": f"Tool '{tool_name}' not found."
            }))]
        
        handler = tool_definition.get("handler")
        if not handler or not callable(handler):
            logger.error(f"Handler for tool '{tool_name}' is missing or not callable.")
            return [mcp_types.TextContent(type="text", text=json.dumps({
                "tool_execution_error": True,
                "error_type": "InvalidHandler",
                "message": f"Handler for tool '{tool_name}' is invalid."
            }))]
        
        try:
            # Debug logging for the tool arguments
            logger.debug(f"Calling tool '{tool_name}' with arguments: {arguments}")
            # Unpack arguments into the handler
            return await handler(**arguments)
        except Exception as e:
            logger.error(f"Unexpected error executing handler for tool '{tool_name}': {e}", exc_info=True)
            return [mcp_types.TextContent(type="text", text=json.dumps({
                "tool_execution_error": True,
                "error_type": "HandlerExecutionError",
                "message": str(e)
            }))]

    async def _handle_execute_workflow_phase(self, profile: str, workspace: str, instruction: str, timeout: int = 300) -> List[mcp_types.TextContent]:
        """Execute an ARIS profile with workspace support for workflow orchestration."""
        try:
            
            log_debug(f"Executing workflow phase: profile={profile}, workspace={workspace}")
            
            # Build ARIS command with workspace support
            cmd = [
                "poetry", "run", "python", "-m", "aris",
                "--profile", profile,
                "--workspace", workspace,
                "--input", instruction
            ]
            
            # Execute ARIS profile in non-interactive mode
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.getcwd()  # Use current working directory as base
            )
            
            # Prepare execution result
            execution_result = {
                "success": result.returncode == 0,
                "profile": profile,
                "workspace": workspace,
                "instruction": instruction[:100] + "..." if len(instruction) > 100 else instruction,
                "exit_code": result.returncode,
                "response": result.stdout.strip() if result.stdout else "",
                "error": result.stderr.strip() if result.stderr else ""
            }
            
            if result.returncode == 0:
                log_debug(f"Workflow phase completed successfully: {profile}")
                execution_result["status"] = "completed"
            else:
                log_warning(f"Workflow phase failed: {profile}, exit code: {result.returncode}")
                execution_result["status"] = "failed"
            
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps(execution_result, indent=2)
            )]
            
        except subprocess.TimeoutExpired:
            error_result = {
                "success": False,
                "status": "timeout",
                "profile": profile,
                "workspace": workspace,
                "error": f"Execution timed out after {timeout} seconds",
                "timeout": timeout
            }
            log_error(f"Workflow phase timed out: {profile}")
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(error_result, indent=2)
            )]
            
        except Exception as e:
            error_result = {
                "success": False,
                "status": "error", 
                "profile": profile,
                "workspace": workspace,
                "error": str(e)
            }
            log_error(f"Error executing workflow phase: {e}")
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps(error_result, indent=2)
            )]

    async def start_async(self):
        """Start the workflow MCP server asynchronously."""
        import uvicorn
        
        try:
            # Check if port is available
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((self.host, self.port))
            sock.close()
            
            if result == 0:
                log_warning(f"Port {self.port} already in use for workflow MCP server")
                return False
            
            # Start server
            config = uvicorn.Config(
                app=self.starlette_app,
                host=self.host,
                port=self.port,
                log_level="warning"  # Reduce uvicorn noise
            )
            server = uvicorn.Server(config)
            
            log_debug(f"Starting workflow MCP server on {self.host}:{self.port}")
            
            # Start server in background task
            server_task = asyncio.create_task(server.serve())
            
            # Give server time to start
            await asyncio.sleep(0.5)
            
            log_debug(f"Workflow MCP server started successfully on port {self.port}")
            return True
            
        except Exception as e:
            log_error(f"Failed to start workflow MCP server: {e}")
            return False

    def start_server_background(self):
        """Start the workflow MCP server in a background thread."""
        import threading
        
        def run_server():
            try:
                import uvicorn
                uvicorn.run(
                    self.starlette_app,
                    host=self.host,
                    port=self.port,
                    log_level="warning"
                )
            except Exception as e:
                log_error(f"Workflow MCP server error: {e}")
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        log_debug(f"Workflow MCP server started in background on port {self.port}")
        
        return server_thread


# Global instance for easy access
workflow_mcp_server = WorkflowMCPServer()