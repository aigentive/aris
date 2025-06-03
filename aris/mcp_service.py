import os
import json
import asyncio
import subprocess
import time
import signal
import tempfile
import atexit
from typing import List, Dict, Any, Optional, Tuple, Set, Dict, NamedTuple

# Assuming logging_utils is in the same directory or accessible via Python path
from .logging_utils import log_error, log_warning, log_router_activity, log_debug

# MCP SDK Imports - try-except block to handle availability
try:
    from mcp import ClientSession, types as mcp_types, StdioServerParameters
    from mcp.client.sse import sse_client
    
    # Import stdio client if available
    try:
        from mcp.client.stdio import stdio_client
        STDIO_CLIENT_AVAILABLE = True
    except ImportError:
        STDIO_CLIENT_AVAILABLE = False
        log_warning("mcp.client.stdio.stdio_client not found, NPM/STDIO MCP servers will not be available")
    
    MCP_SDK_AVAILABLE = True
    DEFAULT_HTTP_CLIENT = "sse_client"
except ImportError:
    try:
        from mcp.client import streamablehttp_client
        MCP_SDK_AVAILABLE = True
        DEFAULT_HTTP_CLIENT = "streamablehttp_client"
        STDIO_CLIENT_AVAILABLE = False
        log_warning("mcp.client.sse.sse_client not found, falling back to mcp.client.streamablehttp_client")
    except ImportError as e_streamable:
        log_error(f"MCP SDK (mcp) client transports (sse_client, streamablehttp_client) not found. Details: {e_streamable}",
                  exception_info=str(e_streamable))
        MCP_SDK_AVAILABLE = False
        STDIO_CLIENT_AVAILABLE = False
        DEFAULT_HTTP_CLIENT = None

# Define StdioServerInfo class after importing ClientSession
class StdioServerInfo(NamedTuple):
    """Information about a stdio-based MCP server."""
    server_params: Any  # StdioServerParameters
    session: Optional[Any] = None
    read_stream: Optional[Any] = None
    write_stream: Optional[Any] = None

class MCPService:
    """
    Service for connecting to MCP servers, fetching tool schemas, and managing configurations.
    Supports multiple MCP servers through configuration files.
    Supports different server types: 'sse', 'streamable', and 'stdio'.
    """
    
    def __init__(self, mcp_config_file: Optional[str] = None):
        """
        Initialize the MCP service with configuration from a file.
        
        Args:
            mcp_config_file: Path to MCP configuration file (if None, will use default config without tools)
        """
        self.mcp_sdk_available = MCP_SDK_AVAILABLE
        self.stdio_client_available = STDIO_CLIENT_AVAILABLE
        self.http_client_used = DEFAULT_HTTP_CLIENT
        
        self.mcp_servers = {}  # Maps server_name -> server_config
        self.stdio_servers = {}  # Maps server_name -> StdioServerInfo
        
        # Track which servers failed to initialize or return tools
        self.failed_servers = set()
        
        # Connection locks to prevent concurrent access to same server
        self._connection_locks = {}  # Maps server_name -> asyncio.Lock
        self._active_connections = set()  # Track servers currently being connected to
        
        # Load MCP server configurations from file
        self.load_config(mcp_config_file)
        
        if not self.mcp_sdk_available:
            log_warning("MCP SDK not available. MCPService will have limited functionality.")
    
    def load_config(self, config_file: Optional[str]) -> bool:
        """
        Load MCP server configurations from a JSON file.
        
        Args:
            config_file: Path to the configuration file, or None to use empty config
            
        Returns:
            True if configuration was loaded successfully, False otherwise
        """
        if config_file is None:
            # If no config file provided, use empty configuration (no MCP servers)
            log_warning(f"MCPService: No config file provided. MCP tools will not be available.")
            self.mcp_servers = {}
            return True
            
        if not os.path.exists(config_file):
            # If file doesn't exist, warn and use empty configuration
            log_warning(f"MCPService: Config file {config_file} not found. MCP tools will not be available.")
            self.mcp_servers = {}
            return False
        
        try:
            # Load configuration from file
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Extract server configurations
            if "mcpServers" in config and isinstance(config["mcpServers"], dict):
                self.mcp_servers = config["mcpServers"]
                log_router_activity(f"MCPService: Loaded {len(self.mcp_servers)} servers from config file {config_file}")
                for server_name, server_config in self.mcp_servers.items():
                    log_debug(f"MCPService: Server '{server_name}': {server_config}")
                return True
            else:
                log_warning(f"MCPService: Invalid config format in {config_file}. Expected 'mcpServers' dictionary.")
                # Empty config instead of default fallback
                self.mcp_servers = {}
                return False
        except Exception as e:
            log_error(f"MCPService: Error loading config file {config_file}: {e}")
            # Empty config instead of default fallback
            self.mcp_servers = {}
            return False
    
    def reload_config(self, new_config_file: str) -> bool:
        """
        Reload configuration from a new file.
        
        Args:
            new_config_file: Path to the new configuration file
            
        Returns:
            True if configuration was reloaded successfully, False otherwise
        """
        log_router_activity(f"MCPService: Reloading configuration from {new_config_file}")
        
        # Close any existing stdio servers
        asyncio.create_task(self._close_stdio_servers())
        
        # Clear existing configuration and state
        self.mcp_servers = {}
        self.stdio_servers = {}
        self.failed_servers = set()
        
        # Clear connection locks to prevent conflicts between old and new configurations
        self._connection_locks = {}
        self._active_connections = set()
        
        # Log the reset
        log_router_activity(f"MCPService: Reset all servers, state, and connection locks to ensure clean configuration")
        
        # Load new configuration
        success = self.load_config(new_config_file)
        
        # Log the loaded servers for verification
        if success and self.mcp_servers:
            server_names = list(self.mcp_servers.keys())
            log_router_activity(f"MCPService: Successfully loaded {len(server_names)} servers: {server_names}")
        else:
            log_router_activity(f"MCPService: No servers loaded from config file")
        
        return success
        
    async def _get_stdio_client_session(self, server_name: str, server_config: Dict[str, Any]) -> Optional[StdioServerInfo]:
        """
        Creates and initializes a stdio client session for a stdio-based MCP server.
        Follows best practices from the MCP SDK documentation for connecting to stdio-based servers.
        
        Args:
            server_name: Name of the server
            server_config: Server configuration dictionary
            
        Returns:
            StdioServerInfo object if successful, None otherwise
        """
        if not self.stdio_client_available:
            log_warning(f"MCPService: Cannot create stdio client for '{server_name}' - stdio_client not available")
            return None
            
        if not server_config.get("command"):
            log_warning(f"MCPService: Stdio server '{server_name}' missing 'command' in configuration")
            return None
            
        command = server_config.get("command")
        args = server_config.get("args", [])
        options = server_config.get("options", {})
        env_vars = server_config.get("env", {})
        
        # Create StdioServerParameters
        try:
            # Set up environment variables - make a copy to avoid modifying the original
            env = os.environ.copy()
            if env_vars:
                for key, value in env_vars.items():
                    env[key] = str(value)
            
            # Log configuration for debugging
            log_router_activity(f"MCPService: Server '{server_name}' environment variables configured: {list(env_vars.keys()) if env_vars else 'none'}")
            
            # Set up working directory
            cwd = options.get("cwd")
            
            # Log the command and args for debugging
            log_router_activity(f"MCPService: Creating stdio client for '{server_name}' with command: {command} {' '.join(args)}")
            
            # Create StdioServerParameters - this is the official way to connect to an MCP server
            # as documented in the MCP SDK
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env,
                cwd=cwd
            )
            
            return StdioServerInfo(server_params=server_params)
        except Exception as e:
            log_error(f"MCPService: Error creating stdio client parameters for '{server_name}': {e}")
            return None
            
    async def _init_stdio_client_session(self, server_name: str, server_info: StdioServerInfo) -> bool:
        """
        Initialize a stdio client session for a stdio-based MCP server.
        This is kept for compatibility with the old flow but we now prefer the direct method.
        
        Args:
            server_name: Name of the server
            server_info: StdioServerInfo object
            
        Returns:
            True if initialization was successful, False otherwise
        """
        log_router_activity(f"MCPService: Initializing stdio client session for '{server_name}'")
        
        # Store the server info
        self.stdio_servers[server_name] = server_info
        
        # Since we now use the direct method that combines initialization and fetching,
        # we don't need to actually initialize anything here.
        # This method is kept for compatibility with any code that still calls it.
        return True
    
    async def _fetch_tools_from_stdio_server_direct(self, server_name: str, server_config: Dict[str, Any]) -> List[Dict]:
        """
        Initializes a stdio client session and fetches tools in a single operation.
        This avoids asyncio cancellation scope issues by keeping everything in one task.
        Uses connection locking to prevent concurrent access to the same server.
        
        Args:
            server_name: Name of the server
            server_config: Server configuration dictionary
            
        Returns:
            List of tool schemas from the server
        """
        if not self.stdio_client_available:
            log_warning(f"MCPService: Cannot connect to stdio server '{server_name}' - stdio_client not available")
            return []
        
        # Get or create a lock for this server to prevent concurrent connections
        if server_name not in self._connection_locks:
            self._connection_locks[server_name] = asyncio.Lock()
        
        lock = self._connection_locks[server_name]
        
        # Check if connection is already in progress
        if server_name in self._active_connections:
            log_router_activity(f"MCPService: Server '{server_name}' connection already in progress, waiting...")
        
        async with lock:
            # Double-check if server failed while we were waiting for the lock
            if server_name in self.failed_servers:
                log_router_activity(f"MCPService: Server '{server_name}' already marked as failed, skipping")
                return []
            
            # Mark connection as active
            self._active_connections.add(server_name)
            try:
                log_router_activity(f"MCPService: Connecting to stdio server '{server_name}' and fetching tools")
                return await self._do_fetch_tools_from_stdio_server(server_name, server_config)
            finally:
                # Always remove from active connections when done
                self._active_connections.discard(server_name)
    
    async def _do_fetch_tools_from_stdio_server(self, server_name: str, server_config: Dict[str, Any]) -> List[Dict]:
        """
        Internal method that does the actual stdio server connection and tool fetching.
        This is separated from the locking logic for clarity.
        """
        # Log server type and environment for debugging
        server_type = server_config.get("type", "unknown")
        env_vars = server_config.get("env", {})
        log_router_activity(f"MCPService: Connecting to {server_type} server '{server_name}' with {len(env_vars)} environment variables")
        
        # Extract server configuration
        command = server_config.get("command")
        args = server_config.get("args", [])
        options = server_config.get("options", {})
        env = os.environ.copy()
        env_vars = server_config.get("env", {})
        
        if env_vars:
            for key, value in env_vars.items():
                env[key] = str(value)
        
        # Create server parameters
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
            cwd=options.get("cwd")
        )
        
        # Initialize and fetch tools in one operation to avoid cancellation scope issues
        try:
            # Set a timeout for the entire operation (increased for slow startup)
            async with asyncio.timeout(25.0):
                # Patch asyncio subprocess creation to capture stderr
                original_create_subprocess_exec = asyncio.create_subprocess_exec
                captured_stderr = []
                
                async def patched_create_subprocess_exec(*args, **kwargs):
                    # Force stderr to be captured
                    kwargs['stderr'] = asyncio.subprocess.PIPE
                    kwargs['stdout'] = asyncio.subprocess.PIPE
                    
                    try:
                        proc = await original_create_subprocess_exec(*args, **kwargs)
                        # Read stderr in background and capture it
                        if proc.stderr:
                            stderr_data = await proc.stderr.read()
                            if stderr_data:
                                captured_stderr.append(stderr_data.decode())
                        return proc
                    except Exception as e:
                        # If subprocess creation fails, capture that too
                        captured_stderr.append(str(e))
                        raise
                
                # Apply the patch
                asyncio.create_subprocess_exec = patched_create_subprocess_exec
                
                try:
                    # Use stdio_client in a single context manager
                    async with stdio_client(server_params) as (read_stream, write_stream):
                            # Initialize session and fetch tools without breaking the context
                            async with ClientSession(read_stream, write_stream) as session:
                                # Wait for initialization
                                await session.initialize()
                                
                                # Fetch tools immediately
                                log_router_activity(f"MCPService: Fetching tools from stdio server '{server_name}'")
                                list_tools_result = await session.list_tools()
                                
                                # Process tools
                                fetched_tools = []
                                if list_tools_result and hasattr(list_tools_result, 'tools') and list_tools_result.tools:
                                    for tool_obj in list_tools_result.tools:
                                        if isinstance(tool_obj, mcp_types.Tool):
                                            tool_dict = tool_obj.model_dump(exclude_none=True, by_alias=True)
                                            # Add server_name to each tool schema
                                            tool_dict["server_name"] = server_name
                                            fetched_tools.append(tool_dict)
                                        else:
                                            log_warning(f"MCPService: Encountered non-Tool object from server '{server_name}': {type(tool_obj)}")
                                
                                log_router_activity(f"MCPService: Successfully fetched {len(fetched_tools)} tools from stdio server '{server_name}'")
                                
                                # Display a message when tools are successfully fetched
                                if fetched_tools:
                                    from .logging_utils import log_info
                                    # Import prompt_toolkit formatting only if needed
                                    try:
                                        from prompt_toolkit import print_formatted_text
                                        from prompt_toolkit.formatted_text import FormattedText
                                        # Import cli_style if available
                                        try:
                                            from .cli import cli_style
                                            style = cli_style
                                        except ImportError:
                                            style = None
                                            
                                        # Use a style consistent with the CLI
                                        # Make sure we end with multiple newlines to ensure clean prompt separation
                                        print_formatted_text(FormattedText([("bold fg:green", f"\nMCP server '{server_name}' has started and is ready with {len(fetched_tools)} tools.")]), style=style)
                                        # Add extra blank lines to ensure clean separation from prompt
                                        print("\n")
                                    except ImportError:
                                        # Fall back to standard print if prompt_toolkit is not available
                                        log_info(f"MCP server '{server_name}' has started and is ready with {len(fetched_tools)} tools.\n\n")
                                        
                                return fetched_tools
                finally:
                    # Restore original function
                    asyncio.create_subprocess_exec = original_create_subprocess_exec
        except asyncio.TimeoutError:
            log_warning(f"MCPService: Timeout (25s) connecting to stdio server '{server_name}' - continuing without it")
            self.failed_servers.add(server_name)
            return []
        except Exception as e:
            log_error(f"MCPService: Error connecting to stdio server '{server_name}': {e}")
            import traceback
            log_error(f"MCPService: Traceback: {traceback.format_exc()}")
            
            # Use captured stderr for better error details
            error_details = str(e)
            if 'captured_stderr' in locals() and captured_stderr:
                stderr_text = ''.join(captured_stderr).strip()
                if stderr_text and len(stderr_text) > len(error_details):
                    error_details = stderr_text
                    log_error(f"MCPService: Captured stderr from '{server_name}': {stderr_text}")
            
            # Show user-friendly error message
            try:
                from prompt_toolkit import print_formatted_text
                from prompt_toolkit.formatted_text import FormattedText
                from .cli import cli_style
                
                # Parse common error types for better user feedback
                error_str = error_details.lower()
                if "modulenotfounderror" in error_str or "no module named" in error_str:
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "🔌 MCP > "),
                        ("fg:red", f"Failed to start '{server_name}': Module not found")
                    ]), style=cli_style)
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "💡 Tip > "),
                        ("fg:yellow", "Check server installation and Python module path")
                    ]), style=cli_style)
                elif "permission denied" in error_str:
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "🔌 MCP > "),
                        ("fg:red", f"Failed to start '{server_name}': Permission denied")
                    ]), style=cli_style)
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "💡 Tip > "),
                        ("fg:yellow", "Check file permissions and executable status")
                    ]), style=cli_style)
                elif "timeout" in error_str:
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "🔌 MCP > "),
                        ("fg:red", f"Failed to start '{server_name}': Connection timeout")
                    ]), style=cli_style)
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "💡 Tip > "),
                        ("fg:yellow", "Server may be slow to start or have startup issues")
                    ]), style=cli_style)
                else:
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "🔌 MCP > "),
                        ("fg:red", f"Failed to start '{server_name}': {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}")
                    ]), style=cli_style)
                    print_formatted_text(FormattedText([
                        ("class:prompt.assistant.prefix", "💡 Tip > "),
                        ("fg:yellow", "Check server configuration and logs for details")
                    ]), style=cli_style)
                
                print()  # Add spacing
                
            except ImportError:
                # Fallback if prompt_toolkit not available
                print(f"❌ MCP server '{server_name}' failed to start: {e}")
            
            return []
    
    async def _close_stdio_servers(self) -> None:
        """
        Close all stdio client sessions.
        """
        for server_name, server_info in list(self.stdio_servers.items()):
            await self._close_stdio_server(server_name, server_info)
        
        # Clear the dictionary
        self.stdio_servers.clear()
    
    async def _close_stdio_server(self, server_name: str, server_info: StdioServerInfo) -> None:
        """
        Close a stdio client session.
        
        Args:
            server_name: Name of the server
            server_info: StdioServerInfo object
        """
        log_router_activity(f"MCPService: Closing stdio client session for '{server_name}'")
        
        # With the current implementation using async context managers in _init_stdio_client_session,
        # we don't need to explicitly close the sessions, but we keep this method for completeness
        # and future extension
        try:
            # Nothing to do explicitly, as the context managers handle cleanup
            pass
        except Exception as e:
            log_error(f"MCPService: Error closing stdio client session for '{server_name}': {e}")
    
    async def close(self) -> None:
        """
        Clean up resources when the service is no longer needed.
        """
        await self._close_stdio_servers()
    
    async def fetch_tools_schema(self) -> List[Dict]:
        """
        Fetch tool schemas from all configured MCP servers.
        Uses a direct tool fetching approach for NPM servers to avoid asyncio context issues.
        
        Returns:
            Combined list of tool schemas from all servers
        """
        if not self.mcp_sdk_available:
            log_error(f"MCP SDK is not available. MCPService cannot fetch tools schema.")
            return []
        
        # No servers configured
        if not self.mcp_servers:
            log_warning("MCPService: No MCP servers configured.")
            return []
        
        log_router_activity(f"MCPService: Fetching tools from {len(self.mcp_servers)} configured servers")
        
        # Create tasks to fetch tools from HTTP-based servers concurrently
        http_tasks = []
        http_server_names = []
        
        # Collect HTTP server tasks for concurrent execution
        for server_name, server_config in self.mcp_servers.items():
            server_type = server_config.get("type")
            
            if server_type in ["sse", "streamable"]:
                # Standard SSE/HTTP server
                url = server_config.get("url")
                if url:
                    http_server_names.append(server_name)
                    http_tasks.append(self._fetch_tools_from_http_server(server_name, url))
        
        # Process HTTP tasks with a timeout
        all_tools = []
        
        if http_tasks:
            try:
                async with asyncio.timeout(10.0):  # 10 second timeout for HTTP servers
                    results = await asyncio.gather(*http_tasks, return_exceptions=True)
                    
                    # Process HTTP results
                    for server_name, result in zip(http_server_names, results):
                        if isinstance(result, Exception):
                            log_error(f"MCPService: Error fetching tools from HTTP server '{server_name}': {result}")
                            continue
                        
                        # Add server_name to each tool schema and add to all_tools
                        for tool in result:
                            tool["server_name"] = server_name
                            all_tools.append(tool)
            except asyncio.TimeoutError:
                log_warning("MCPService: Timeout fetching tools from HTTP servers, continuing with available tools")
        
        # Identify stdio-based servers
        stdio_servers = {
            name: config for name, config in self.mcp_servers.items() 
            if config.get("type") == "stdio"
        }
        
        # Process stdio servers sequentially to avoid context issues
        for server_name, server_config in stdio_servers.items():
            # Skip if stdio client is not available
            if not self.stdio_client_available:
                log_warning(f"MCPService: Cannot connect to stdio server '{server_name}' - stdio_client not available")
                continue
            
            # For backward compatibility, ensure the server is registered in stdio_servers
            # This is needed because some code might expect the server to be in this dictionary
            if server_name not in self.stdio_servers:
                server_info = await self._get_stdio_client_session(server_name, server_config)
                if server_info:
                    self.stdio_servers[server_name] = server_info
                    log_router_activity(f"MCPService: Registered stdio server '{server_name}' in current session")
            
            # Fetch tools with extended timeout for stdio servers (especially NPX)
            try:
                log_router_activity(f"MCPService: Attempting to connect to stdio server '{server_name}' with 30s timeout")
                stdio_tools = await asyncio.wait_for(
                    self._fetch_tools_from_stdio_server_direct(server_name, server_config),
                    timeout=30.0  # 30 second timeout for stdio connections
                )
                
                # Add tools to the result
                if stdio_tools:
                    all_tools.extend(stdio_tools)
                    log_router_activity(f"MCPService: Added {len(stdio_tools)} tools from stdio server '{server_name}'")
                else:
                    log_warning(f"MCPService: No tools fetched from stdio server '{server_name}'")
                    
            except asyncio.TimeoutError:
                log_warning(f"MCPService: Timeout (30s) connecting to stdio server '{server_name}' - skipping")
                self.failed_servers.add(server_name)
            except Exception as e:
                log_warning(f"MCPService: Error connecting to stdio server '{server_name}': {e}")
                self.failed_servers.add(server_name)
        
        log_router_activity(f"MCPService: Successfully fetched {len(all_tools)} tools from all servers")
        return all_tools
    
    async def _fetch_tools_from_stdio_server(self, server_name: str, server_info: StdioServerInfo) -> List[Dict]:
        """
        Fetch tool schemas from a stdio-based MCP server.
        
        Args:
            server_name: Name of the server
            server_info: StdioServerInfo object
            
        Returns:
            List of tool schemas from the server
            
        Raises:
            Exception: If there is an error fetching tools
        """
        log_router_activity(f"MCPService: Fetching tools from stdio server '{server_name}'")
        
        # Add a small delay after initialization to allow the server to fully start
        await asyncio.sleep(0.5)
        
        try:
            if not server_info.session:
                raise ValueError(f"No active session for stdio server '{server_name}'")
                
            # List the tools using the session
            try:
                list_tools_result = await server_info.session.list_tools()
            except Exception as e:
                # Capture detailed error information
                import traceback
                tb_str = traceback.format_exc()
                log_error(f"MCPService: Error calling list_tools on '{server_name}': {e}\nTraceback: {tb_str}")
                raise
            
            fetched_tools = []
            if list_tools_result and hasattr(list_tools_result, 'tools') and list_tools_result.tools:
                for tool_obj in list_tools_result.tools:
                    if isinstance(tool_obj, mcp_types.Tool):
                        tool_dict = tool_obj.model_dump(exclude_none=True, by_alias=True)
                        fetched_tools.append(tool_dict)
                    else:
                        log_warning(f"MCPService: Encountered non-Tool object from server '{server_name}': {type(tool_obj)}")
            else:
                log_warning(f"MCPService: No tools returned from '{server_name}' or invalid response: {list_tools_result}")
            
            log_router_activity(f"MCPService: Successfully fetched {len(fetched_tools)} tools from stdio server '{server_name}'")
            return fetched_tools
        except Exception as e:
            # Enhanced error logging
            import traceback
            log_error(f"MCPService: Error fetching tools from stdio server '{server_name}': {e}")
            log_error(f"MCPService: Traceback: {traceback.format_exc()}")
            raise
    
    async def _fetch_tools_from_http_server(self, server_name: str, server_url: str) -> List[Dict]:
        """
        Fetch tool schemas from a specific HTTP-based MCP server (SSE or Streamable).
        
        Args:
            server_name: Name of the server (for logging)
            server_url: URL of the MCP server
            
        Returns:
            List of tool schemas from the server
            
        Raises:
            Exception: If there is an error fetching tools
        """
        log_router_activity(f"MCPService: Fetching tools from HTTP server '{server_name}' at {server_url}")
        
        try:
            client_context_manager: Any = None
            if self.http_client_used == "sse_client" and 'sse_client' in globals():
                client_context_manager = sse_client(server_url)
            elif self.http_client_used == "streamablehttp_client" and 'streamablehttp_client' in globals():
                client_context_manager = streamablehttp_client(server_url)
            else:
                log_error(f"MCPService: No valid MCP HTTP client identified ({self.http_client_used}).", None)
                return []

            async with client_context_manager as (read_stream, write_stream, *_):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    log_router_activity(f"MCPService: Session initialized for HTTP server '{server_name}'. Listing tools...")
                    list_tools_result: mcp_types.ListToolsResult = await session.list_tools()
                    fetched_tools = []
                    if list_tools_result and list_tools_result.tools:
                        for tool_obj in list_tools_result.tools:
                            if isinstance(tool_obj, mcp_types.Tool):
                                tool_dict = tool_obj.model_dump(exclude_none=True, by_alias=True)
                                fetched_tools.append(tool_dict)
                            else:
                                log_warning(f"MCPService: Encountered non-Tool object from HTTP server '{server_name}': {type(tool_obj)}")
                    log_router_activity(f"MCPService: Successfully fetched {len(fetched_tools)} tools from HTTP server '{server_name}'.")
                    return fetched_tools
        except ConnectionRefusedError as e:
            log_error(f"MCPService: Connection refused when trying to connect to HTTP server '{server_name}' at {server_url}. Is the server running? Details: {e}", exception_info=str(e))
            raise
        except Exception as e:
            detailed_error_info = str(e)
            if hasattr(e, 'exceptions') and isinstance(getattr(e, 'exceptions'), (list, tuple)) and getattr(e, 'exceptions'): 
                log_error(f"MCPService: Error during communication with HTTP server '{server_name}' at {server_url}: {type(e).__name__} - {detailed_error_info}", exception_info=detailed_error_info)
            else:
                log_error(f"MCPService: Error during communication with HTTP server '{server_name}' at {server_url}: {type(e).__name__} - {e}", exception_info=str(e))
            raise
    
    def is_sdk_available(self) -> bool:
        """Checks if the MCP SDK is available."""
        return self.mcp_sdk_available
    
    def get_server_configs(self) -> Dict[str, Dict]:
        """
        Get the current server configurations.
        
        Returns:
            Dictionary mapping server names to configurations
        """
        return self.mcp_servers

# Example Usage (for testing mcp_service.py directly)
async def main_test_mcp_service():
    print("Testing MCPService...")
    
    # Create a sample config file with both SSE and stdio-based server types
    sample_config = {
        "mcpServers": {
            "aigentive": {
                "type": "sse",
                "url": os.getenv("MCP_SSE_URL", "http://localhost:8090/mcp/sse/")
            },
            "test_server": {
                "type": "sse",
                "url": "http://localhost:8091/mcp/sse/"  # Non-existent server for testing
            },
            "youtube": {
                "type": "stdio",  # Using "stdio" type for stdio-based servers
                "command": "npx",
                "args": ["-y", "youtube-data-mcp-server"],
                "options": {
                    "cwd": "/tmp"
                },
                "env": {
                    "NODE_OPTIONS": "--no-warnings",
                    "YOUTUBE_API_KEY": os.getenv("YOUTUBE_API_KEY", "xyz"),
                    "YOUTUBE_TRANSCRIPT_LANG": "en"
                }
            }
        }
    }
    
    # Write sample config to file
    with open("test_mcp_config.json", "w") as f:
        json.dump(sample_config, f, indent=2)
    
    # Create service with the sample config
    service = MCPService(mcp_config_file="test_mcp_config.json")
    
    if service.is_sdk_available():
        print(f"MCP SDK is available. Using HTTP client: {service.http_client_used}")
        print(f"Stdio client available: {service.stdio_client_available}")
        print(f"Configured servers: {list(service.get_server_configs().keys())}")
        
        # Wait a bit for stdio servers to initialize
        await asyncio.sleep(1)
        
        # Check if stdio servers were initialized
        if "youtube" in service.stdio_servers:
            print(f"Stdio server 'youtube' initialized")
        else:
            print("Stdio server 'youtube' failed to initialize")
        
        # Fetch tools from all servers
        tools = await service.fetch_tools_schema()
        if tools:
            print(f"Successfully fetched {len(tools)} tools:")
            # Group tools by server
            tools_by_server = {}
            for tool in tools:
                server = tool.get('server_name', 'unknown')
                if server not in tools_by_server:
                    tools_by_server[server] = []
                tools_by_server[server].append(tool.get('name', 'unnamed_tool'))
            
            # Print tools by server
            for server, server_tools in tools_by_server.items():
                print(f"  Server '{server}': {len(server_tools)} tools")
                for tool_name in server_tools[:5]:  # Show first 5 tools
                    print(f"    - {tool_name}")
                if len(server_tools) > 5:
                    print(f"    - ... and {len(server_tools) - 5} more")
        else:
            print("Failed to fetch tools or no tools found.")
            
        # Test config reload
        print("\nTesting config reload with no config...")
        service.reload_config(None)
        print(f"Configured servers after reload: {list(service.get_server_configs().keys())}")
        
        # Test reload with stdio servers again
        print("\nTesting config reload with stdio servers...")
        service.reload_config("test_mcp_config.json")
        print(f"Configured servers after reload: {list(service.get_server_configs().keys())}")
        
        # Wait a bit for stdio servers to initialize
        await asyncio.sleep(1)
        
        # Check if stdio servers were initialized after reload
        if "youtube" in service.stdio_servers:
            print(f"Stdio server 'youtube' initialized after reload")
        else:
            print("Stdio server 'youtube' failed to initialize after reload")
            
        # Fetch tools again
        tools = await service.fetch_tools_schema()
        print(f"Tools count after reload: {len(tools)}")
        
        # Cleanup
        await service.close()
    else:
        print("MCP SDK is not available. Cannot fetch tools.")
    
    # Clean up test config file
    try:
        os.remove("test_mcp_config.json")
    except:
        pass

if __name__ == '__main__':
    # To run this test: 
    # 1. Ensure your MCP server is running and accessible at MCP_SSE_URL.
    # 2. Set the environment variable: export PYTHONPATH=$PYTHONPATH:$(pwd)/backend/aigentive/samples/cc_so_chat_cli
    # 3. Run from the root of your project: python -m backend.aigentive.samples.cc_so_chat_cli.mcp_service
    print("Running MCPService test...")
    asyncio.run(main_test_mcp_service())