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
            
            return mcp_types.CallToolResult(content=tool_results_content, isError=is_error)

        async def list_tools_request_handler_adapter(req: mcp_types.ListToolsRequest):
            # Get tool definitions from our custom store
            tools = list(self.mcp_app.tools.values())
            return mcp_types.ListToolsResult(tools=tools)

        # Configure MCP server handlers
        self.mcp_app.call_tool = call_tool_request_handler_adapter
        self.mcp_app.list_tools = list_tools_request_handler_adapter

    def _setup_starlette_app(self):
        """Set up the Starlette ASGI application with routing."""
        async def health_check(request: Request):
            return PlainTextResponse(f"Workflow MCP Server running (SDK: {self._sdk_version})")

        async def mcp_sse_endpoint(request: Request):
            """Handle SSE connections for MCP communication."""
            return EventSourceResponse(self.sse_transport.handle_sse_request(request, self.mcp_app))

        async def mcp_messages_endpoint(request: Request):
            """Handle HTTP POST messages for MCP communication."""
            return await self.sse_transport.handle_post_message(request, self.mcp_app)

        routes = [
            Route("/", health_check, methods=["GET"]),
            Route("/mcp/sse/", mcp_sse_endpoint),
            Route("/mcp/messages/", mcp_messages_endpoint, methods=["POST"])
        ]

        self.starlette_app = Starlette(routes=routes)

    def _register_workflow_tools(self):
        """Register all workflow orchestration tools."""
        
        # Register execute_workflow_phase tool
        execute_workflow_phase_tool = mcp_types.Tool(
            name="execute_workflow_phase",
            description="Execute an ARIS profile with workspace support for workflow orchestration",
            inputSchema={
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
        )
        self.mcp_app.tools["execute_workflow_phase"] = execute_workflow_phase_tool
        logger.info("Registered execute_workflow_phase tool")

    async def _handle_mcp_call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> List[mcp_types.TextContent]:
        """Handle MCP tool calls and route them to appropriate handlers."""
        try:
            log_debug(f"Workflow MCP tool call: {tool_name} with args: {arguments}")
            
            if tool_name == "execute_workflow_phase":
                return await self._handle_execute_workflow_phase(arguments)
            else:
                error_msg = f"Unknown workflow tool: {tool_name}"
                log_error(error_msg)
                return [mcp_types.TextContent(
                    type="text",
                    text=json.dumps({
                        "tool_execution_error": True,
                        "error": error_msg,
                        "available_tools": list(self.mcp_app.tools.keys())
                    }, indent=2)
                )]
                
        except Exception as e:
            error_msg = f"Error executing workflow tool {tool_name}: {str(e)}"
            log_error(error_msg)
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps({
                    "tool_execution_error": True,
                    "error": error_msg,
                    "tool_name": tool_name
                }, indent=2)
            )]

    async def _handle_execute_workflow_phase(self, arguments: Dict[str, Any]) -> List[mcp_types.TextContent]:
        """Execute an ARIS profile with workspace support for workflow orchestration."""
        try:
            profile = arguments.get("profile")
            workspace = arguments.get("workspace") 
            instruction = arguments.get("instruction")
            timeout = arguments.get("timeout", 300)
            
            # Validate required arguments
            if not profile:
                raise ValueError("profile parameter is required")
            if not workspace:
                raise ValueError("workspace parameter is required")
            if not instruction:
                raise ValueError("instruction parameter is required")
            
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
                "profile": arguments.get("profile", "unknown"),
                "workspace": arguments.get("workspace", "unknown"),
                "error": f"Execution timed out after {timeout} seconds",
                "timeout": timeout
            }
            log_error(f"Workflow phase timed out: {arguments.get('profile')}")
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(error_result, indent=2)
            )]
            
        except Exception as e:
            error_result = {
                "success": False,
                "status": "error", 
                "profile": arguments.get("profile", "unknown"),
                "workspace": arguments.get("workspace", "unknown"),
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