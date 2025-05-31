# Standard library imports
import os
import json
import logging
import asyncio
import importlib.metadata
import copy
from typing import Dict, Any, List, Optional, Union, Callable

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
from .profile_manager import ProfileManager, ProfileSchema, profile_manager
from .logging_utils import log_router_activity, log_error, log_warning, log_debug

# Setup module logger
logger = logging.getLogger(__name__)

class ProfileMCPServer:
    """
    MCP server that exposes profile management tools through the Model Context Protocol.
    Allows AI agents to programmatically manage and use profiles.
    """
    
    def __init__(self, 
                 host: str = "0.0.0.0", 
                 port: int = 8092,
                 profile_manager_instance = None):
        """
        Initialize the Profile MCP Server.
        
        Args:
            host: Host address to bind the server to
            port: Port to listen on
            profile_manager_instance: Optional instance of ProfileManager to use
        """
        self.host = host
        self.port = port
        self.profile_manager = profile_manager_instance or profile_manager
        
        # Initialize version info
        self._sdk_version = self._get_sdk_version_str()
        
        # Initialize the MCP server components
        server_name = "profile_manager"  # Use consistent name matching profile_mcp_server.json
        self.mcp_app = OfficialMCPServer(server_name)
        self.mcp_app.tools = {}  # Custom store for tool definitions
        logger.info(f"Initialized MCP server with name: {server_name}")
        
        # Set up request handlers
        self._setup_request_handlers()
        
        # Initialize SSE transport
        self.sse_transport = SseServerTransport(endpoint="/../messages/")
        
        # Setup Starlette ASGI app
        self._setup_starlette_app()
        
        # Register all profile tools
        self._register_profile_tools()
        
    def _get_sdk_version_str(self) -> str:
        """Get the version of the cc_so_chat_cli package for information purposes."""
        try:
            # Attempt to get the version from the package metadata
            import importlib.metadata
            return importlib.metadata.version('aigentive')
        except (importlib.metadata.PackageNotFoundError, ImportError):
            # Fall back to a default version if metadata can't be found
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
        async def list_tools_request_handler_adapter(req: mcp_types.ListToolsRequest): # req is unused but part of handler signature
            tool_defs = await self._handle_list_tools()
            return mcp_types.ServerResult(mcp_types.ListToolsResult(tools=tool_defs))
        self.mcp_app.request_handlers[mcp_types.ListToolsRequest] = list_tools_request_handler_adapter
    
    def _register_profile_tools(self):
        """Register all profile management tools with the MCP server."""
        # Tool for listing profiles
        self._register_tool(
            name="list_profiles",
            description="List all available profiles",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_list_profiles
        )
        
        # Tool for getting profile details
        self._register_tool(
            name="get_profile",
            description="Get details of a specific profile",
            input_schema={
                "type": "object",
                "properties": {
                    "profile_ref": {"type": "string", "description": "The profile reference (e.g., 'workflow_manager')"},
                    "resolve": {"type": "boolean", "description": "Whether to resolve inheritance (default: true)"}
                },
                "required": ["profile_ref"]
            },
            handler=self._handle_get_profile
        )
        
        # Tool for creating/updating profiles
        self._register_tool(
            name="create_profile",
            description="Create or update a profile",
            input_schema={
                "type": "object",
                "properties": {
                    "profile_data": {
                        "type": "object",
                        "description": "The profile data according to ProfileSchema"
                    },
                    "save_path": {
                        "type": "string", 
                        "description": "Where to save the profile (default: user profiles directory)"
                    }
                },
                "required": ["profile_data"]
            },
            handler=self._handle_create_profile
        )
        
        # Tool for activating profiles
        self._register_tool(
            name="activate_profile",
            description="Activate a profile and get its configuration",
            input_schema={
                "type": "object",
                "properties": {
                    "profile_ref": {"type": "string", "description": "The profile reference to activate"},
                    "variables": {
                        "type": "object", 
                        "description": "Values for template variables in the profile"
                    }
                },
                "required": ["profile_ref"]
            },
            handler=self._handle_activate_profile
        )
        
        # Tool for managing profile variables
        self._register_tool(
            name="get_profile_variables",
            description="Get variables defined in a profile",
            input_schema={
                "type": "object",
                "properties": {
                    "profile_ref": {"type": "string", "description": "The profile reference"}
                },
                "required": ["profile_ref"]
            },
            handler=self._handle_get_variables
        )
        
        # Tool for merging profiles
        self._register_tool(
            name="merge_profiles",
            description="Merge two or more profiles",
            input_schema={
                "type": "object",
                "properties": {
                    "base_profile": {"type": "string", "description": "The base profile reference"},
                    "overlay_profiles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of profile references to merge on top"
                    }
                },
                "required": ["base_profile", "overlay_profiles"]
            },
            handler=self._handle_merge_profiles
        )
        
        # Tool for refreshing the profile registry
        self._register_tool(
            name="refresh_profiles",
            description="Refresh the profile registry",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_refresh_profiles
        )
        
        # Tool for getting MCP config
        self._register_config_tool()
        
        logger.info(f"Registered {len(self.mcp_app.tools)} profile management tools")
    
    def _register_tool(self, name: str, description: str, input_schema: Dict, handler: Callable):
        """Register a tool with the MCP server."""
        if name in self.mcp_app.tools:
            logger.warning(f"Tool definition for '{name}' already exists. Overwriting.")
            
        self.mcp_app.tools[name] = {
            "handler": handler,
            "description": description,
            "input_schema": input_schema
        }
        logger.info(f"Prepared MCP tool definition: {name}")
    
    def _register_config_tool(self):
        """Register the config tool that provides server information."""
        config_tool_name = "get_profile_mcp_config"
        if config_tool_name in self.mcp_app.tools:
            logger.debug(f"MCP tool definition for '{config_tool_name}' already prepared. Skipping.")
            return
        
        config_tool_description = "Retrieves the MCP interaction configuration for this Profile MCP server."
        config_input_schema = {"type": "object", "properties": {}}  # No inputs
        
        async def handle_get_mcp_config() -> List[mcp_types.TextContent]:
            config_json = self._generate_mcp_interaction_config()
            return [mcp_types.TextContent(type="text", text=json.dumps(config_json))]
        
        self.mcp_app.tools[config_tool_name] = {
            "handler": handle_get_mcp_config,
            "description": config_tool_description,
            "input_schema": config_input_schema
        }
        logger.info(f"Prepared MCP tool definition: {config_tool_name}")
    
    def _generate_mcp_interaction_config(self) -> Dict[str, Any]:
        """Generate the MCP interaction configuration for the server."""
        http_base_url = f"http://{self.host}:{self.port}"
        capabilities = []
        
        # Log available tools for debugging
        logger.debug(f"Available tools when generating MCP config: {list(self.mcp_app.tools.keys())}")
        
        # Add all tools as capabilities
        for tool_name, tool_definition in self.mcp_app.tools.items():
            capabilities.append({
                "id": tool_name,
                "type": "tool",
                "name": tool_definition.get("description"),
                "description": tool_definition.get("description"),
                "inputSchema": tool_definition.get("input_schema"),
                "server_name": self.mcp_app.name  # Use the server name from the MCP app
            })
        
        # Generate configuration with consistent server name
        config = {
            "mcpServers": {
                self.mcp_app.name: {  # Use the server name from the MCP app
                    "type": "sse",
                    "url": f"{http_base_url}/mcp/sse/"
                }
            },
            "mcp_server_base_url": http_base_url,
            "mcp_protocol_version": "0.1.0",
            "server_name": self.mcp_app.name,  # Use the server name from the MCP app
            "sdk_version": self._sdk_version,
            "transport": {
                "type": "http_sse",
                "sse_endpoint": f"{http_base_url}/mcp/sse/",
                "post_message_endpoint": f"{http_base_url}/mcp/messages/"
            },
            "capabilities": capabilities
        }
        
        # Log the generated config for debugging
        logger.debug(f"Generated MCP config with servers: {list(config['mcpServers'].keys())}")
        logger.debug(f"Server name used for MCP config: {self.mcp_app.name}")
        
        return config
        
    def _setup_starlette_app(self):
        """Set up the Starlette ASGI application."""
        # Define the raw ASGI app for SSE connections
        async def sse_endpoint_asgi_app(scope, receive, send):
            if scope["path"] == "/mcp/sse/" or scope["path"] == "/mcp/sse":
                # Ensure config tool is registered if needed
                if not self.mcp_app.tools:
                    logger.info("SSE ASGI App: No tools registered, ensuring config tool is available.")
                    self._register_config_tool()
                
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
    
    async def _handle_list_profiles(self) -> List[mcp_types.TextContent]:
        """Handler for list_profiles tool."""
        try:
            profiles = self.profile_manager.get_available_profiles()
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(profiles)
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to list profiles: {str(e)}")]
    
    async def _handle_get_profile(self, profile_ref: str, resolve: bool = True) -> List[mcp_types.TextContent]:
        """Handler for get_profile tool."""
        try:
            profile = self.profile_manager.get_profile(profile_ref, resolve=resolve)
            if not profile:
                return [self._create_error_response(f"Profile '{profile_ref}' not found")]
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(profile)
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to get profile '{profile_ref}': {str(e)}")]
    
    async def _handle_create_profile(self, profile_data: Dict, save_path: Optional[str] = None) -> List[mcp_types.TextContent]:
        """Handler for create_profile tool."""
        try:
            # Validate profile data with ProfileSchema
            
            # This will raise ValidationError if invalid
            ProfileSchema(**profile_data)
            
            # Determine save location
            profile_name = profile_data.get("profile_name")
            if not profile_name:
                return [self._create_error_response("profile_name is required in profile_data")]
            
            if save_path:
                # Ensure directory exists
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                profile_path = save_path
            else:
                # Save to user profiles directory
                from .profile_manager import USER_PROFILES_DIR
                
                # Handle nested profile paths
                profile_path_parts = profile_name.split("/")
                if len(profile_path_parts) > 1:
                    # Create directories for nested profile
                    profile_dir = os.path.join(USER_PROFILES_DIR, *profile_path_parts[:-1])
                    os.makedirs(profile_dir, exist_ok=True)
                    file_name = profile_path_parts[-1] + ".yaml"
                    profile_path = os.path.join(profile_dir, file_name)
                else:
                    # Simple profile in root directory
                    file_name = profile_name + ".yaml"
                    profile_path = os.path.join(USER_PROFILES_DIR, file_name)
            
            # Write profile to file
            import yaml
            with open(profile_path, 'w', encoding='utf-8') as f:
                yaml.dump(profile_data, f, default_flow_style=False, sort_keys=False)
            
            # Refresh profiles to include the new one
            self.profile_manager.refresh_profiles()
            
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps({"success": True, "profile_path": profile_path})
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to create profile: {str(e)}")]
    
    async def _handle_activate_profile(self, profile_ref: str, variables: Optional[Dict] = None) -> List[mcp_types.TextContent]:
        """Handler for activate_profile tool."""
        try:
            # Get the profile
            profile = self.profile_manager.get_profile(profile_ref, resolve=True)
            if not profile:
                return [self._create_error_response(f"Profile '{profile_ref}' not found")]
            
            # Get required variables
            all_variables = self.profile_manager.get_variables_from_profile(profile)
            
            # Check if all required variables are provided
            variables = variables or {}
            missing_vars = []
            for var in all_variables:
                if var.required and var.name not in variables and not var.default:
                    missing_vars.append(var.name)
            
            if missing_vars:
                return [self._create_error_response(
                    f"Missing required variables: {', '.join(missing_vars)}"
                )]
            
            # Apply defaults for missing optional variables
            for var in all_variables:
                if var.name not in variables and var.default:
                    variables[var.name] = var.default
            
            # Get MCP configuration if specified in the profile
            mcp_config = None
            if "mcp_config_files" in profile and profile["mcp_config_files"]:
                mcp_config_path = self.profile_manager.get_merged_mcp_config_path(profile)
                if mcp_config_path:
                    with open(mcp_config_path, 'r') as f:
                        mcp_config = json.load(f)
            
            # Return the activated profile info
            result = {
                "profile": profile,
                "variables": variables,
                "mcp_config": mcp_config
            }
            
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(result)
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to activate profile '{profile_ref}': {str(e)}")]
    
    async def _handle_get_variables(self, profile_ref: str) -> List[mcp_types.TextContent]:
        """Handler for get_profile_variables tool."""
        try:
            profile = self.profile_manager.get_profile(profile_ref, resolve=True)
            if not profile:
                return [self._create_error_response(f"Profile '{profile_ref}' not found")]
            
            variables = self.profile_manager.get_variables_from_profile(profile)
            # Convert Pydantic models to dictionaries
            var_dicts = [var.model_dump() for var in variables]
            
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(var_dicts)
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to get variables for profile '{profile_ref}': {str(e)}")]
    
    async def _handle_merge_profiles(self, base_profile: str, overlay_profiles: List[str]) -> List[mcp_types.TextContent]:
        """Handler for merge_profiles tool."""
        try:
            # Get the base profile
            base = self.profile_manager.get_profile(base_profile, resolve=True)
            if not base:
                return [self._create_error_response(f"Base profile '{base_profile}' not found")]
            
            # Start with a copy of the base profile
            result = copy.deepcopy(base)
            
            # Merge each overlay profile in order
            for profile_ref in overlay_profiles:
                overlay = self.profile_manager.get_profile(profile_ref, resolve=True)
                if not overlay:
                    return [self._create_error_response(f"Overlay profile '{profile_ref}' not found")]
                
                # Use the profile manager's merge function
                result = self.profile_manager._merge_profiles(result, overlay)
            
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps(result)
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to merge profiles: {str(e)}")]
    
    async def _handle_refresh_profiles(self) -> List[mcp_types.TextContent]:
        """Handler for refresh_profiles tool."""
        try:
            profiles = self.profile_manager.refresh_profiles()
            return [mcp_types.TextContent(
                type="text", 
                text=json.dumps({"success": True, "profiles_count": len(profiles)})
            )]
        except Exception as e:
            return [self._create_error_response(f"Failed to refresh profiles: {str(e)}")]
    
    def _create_error_response(self, message: str) -> mcp_types.TextContent:
        """Create a standardized error response."""
        return mcp_types.TextContent(
            type="text",
            text=json.dumps({
                "tool_execution_error": True,
                "message": message
            })
        )
    
    def _check_for_error(self, results: List[mcp_types.TextContent]) -> bool:
        """Check if the results contain an error response."""
        if not results:
            return False
        
        try:
            content = json.loads(results[0].text)
            return isinstance(content, dict) and content.get("tool_execution_error", False)
        except:
            return False
    
    async def start_server_async(self):
        """Initialize the server asynchronously. Does not block."""
        # Ensure all tools are registered
        if not self.mcp_app.tools:
            logger.info("start_server_async: No tools registered, ensuring config tool is available.")
            self._register_config_tool()
        
        logger.info("Profile MCP Server configured. Starlette app is ready.")
        self._log_connection_info()
    
    def _log_connection_info(self):
        """Log connection details and example client configuration."""
        base_url = f"http://{self.host}:{self.port}"
        # For display, if host is 0.0.0.0, suggest localhost for easier connection
        accessible_host = "localhost" if self.host == "0.0.0.0" else self.host
        
        accessible_sse_url = f"http://{accessible_host}:{self.port}/mcp/sse/"
        accessible_post_url = f"http://{accessible_host}:{self.port}/mcp/messages/"
        
        cursor_config_example = {
            "mcpServers": {
                # User should replace this name with a desired name for their client config
                self.mcp_app.name: {
                    "url": accessible_sse_url,
                    "env": {}  # Placeholder for any environment variables if needed
                }
            }
        }
        cursor_config_str = json.dumps(cursor_config_example, indent=2)
        
        # Using print for direct console output for user instructions
        # Using logger for server status messages
        print("-"*70)
        logger.info("Profile MCP Server Ready")
        logger.info(f"Listening on: {base_url} (Accessible via http://{accessible_host}:{self.port})")
        logger.info(f"=> Primary Client SSE Endpoint URL: {accessible_sse_url}")
        logger.info(f"=> Client Message POST URL:        {accessible_post_url}")
        # Only print configuration instructions in interactive mode
        try:
            from .cli import _SUPPRESS_INTERACTIVE_OUTPUT
            suppress_output = _SUPPRESS_INTERACTIVE_OUTPUT
        except ImportError:
            suppress_output = False
            
        if not suppress_output:
            print("-"*70)
            print("Configuration Instructions for MCP Clients (like Cursor, BoltAI, etc.):")
            print("1. Ensure this server process is running.")
            print(f"2. To configure Cursor, add or update your '.cursor/mcp.json' file (typically in your user or project directory)")
            print(f"   with the following structure. You can adjust the server name key ('{self.mcp_app.name}') as needed:")
            print("\n" + cursor_config_str + "\n")
            print(f"3. For other MCP clients, refer to their documentation for adding an existing HTTP/SSE MCP server.")
            print(f"   Use the SSE Endpoint URL: {accessible_sse_url}")
            print("4. Once connected, the client can discover capabilities. For this server, this includes:")
            print(f"   - A tool named 'get_profile_mcp_config' to get full server configuration and all tool schemas.")
            for tool_name in self.mcp_app.tools:
                if tool_name != "get_profile_mcp_config":
                    print(f"   - A tool named '{tool_name}' for profile management.")
            print("-"*70)
    
    def _execute_main_blocking_logic(self):
        """The core synchronous logic to run Uvicorn."""
        try:
            import uvicorn
            current_port = self.port
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    logger.info(f"Starting Uvicorn server on {self.host}:{current_port}...")
                    uvicorn.run(self.starlette_app, host=self.host, port=current_port, log_config=None)
                    # If we get here, the server started successfully
                    break
                except OSError as port_error:
                    if "address already in use" in str(port_error).lower():
                        # Port is in use, try the next port
                        retry_count += 1
                        current_port += 1
                        logger.warning(f"Port {self.port} is already in use. Trying port {current_port}...")
                        # Update the port for future connections
                        self.port = current_port
                    else:
                        # Other OSError, not related to port binding
                        raise
            
            if retry_count >= max_retries:
                logger.error(f"Failed to start server after {max_retries} attempts")
                print(f"Failed to start Profile MCP Server after trying ports {self.port}-{current_port-1}")
                
        except ImportError:
            logger.error("Uvicorn is not installed. Please install it to run the server: pip install uvicorn")
            print("Uvicorn is not installed. Please install it: pip install uvicorn")
        except Exception as e:
            logger.error(f"Failed to start server with Uvicorn: {e}", exc_info=True)
            print(f"Failed to start server with Uvicorn: {e}")
    
    def run_server_blocking(self):
        """Run the server in a blocking manner."""
        try:
            # Perform async setup first
            asyncio.run(self.start_server_async())
            # Then run the blocking uvicorn server
            self._execute_main_blocking_logic()
            return True
        except KeyboardInterrupt:
            logger.info("Server shutdown requested (KeyboardInterrupt).")
        except Exception as e:
            logger.error(f"Error in run_server_blocking: {e}", exc_info=True)
            # Re-raise the exception to be handled by the caller
            raise
        finally:
            logger.info("Profile MCP Server has shut down.")
        return False

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
        """Handle a call to a specific tool."""
        logger.debug(f"MCP Server received call_tool request for tool: '{tool_name}' with arguments: {arguments}")
        
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
            # Special handling for config tool which takes no arguments
            if tool_name == "get_profile_mcp_config":
                return await handler()
            else:
                # Debug logging for the tool arguments
                logger.debug(f"Calling tool '{tool_name}' with arguments: {arguments}")
                # For other tools, unpack arguments into the handler
                return await handler(**arguments)
        except Exception as e:
            logger.error(f"Unexpected error executing handler for tool '{tool_name}': {e}", exc_info=True)
            return [mcp_types.TextContent(type="text", text=json.dumps({
                "tool_execution_error": True,
                "error_type": "HandlerExecutionError",
                "message": str(e)
            }))]