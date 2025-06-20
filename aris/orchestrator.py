import json
import os
import asyncio

from typing import Optional, List, AsyncIterator, Dict, Any

from .logging_utils import log_router_activity, log_error, log_warning, log_debug
from .mcp_service import MCPService
from .prompt_formatter import PromptFormatter
from .cli_flag_manager import CLIFlagManager
from .claude_cli_executor import ClaudeCLIExecutor
from .progress_tracker import ProgressTracker, ExecutionPhase, parse_chunk_for_progress_detail

# Default configuration
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")

# Globals populated by initialize_router_components
TOOLS_SCHEMA: List[dict] = []  # Populated by MCPService

# Service/Component Instances
mcp_service_instance: Optional[MCPService] = None
prompt_formatter_instance: Optional[PromptFormatter] = None
cli_flag_manager_instance: Optional[CLIFlagManager] = None
claude_cli_executor_instance: Optional[ClaudeCLIExecutor] = None

async def initialize_router_components_minimal():
    """Initialize core router components without MCP (for faster CLI startup)."""
    global mcp_service_instance, prompt_formatter_instance, cli_flag_manager_instance, claude_cli_executor_instance
    
    log_router_activity("Initializing core router components (services and globals)...")
    
    # Initialize core services without MCP connection
    router_script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_service_instance = MCPService()  # No config file = no MCP servers
    prompt_formatter_instance = PromptFormatter()
    cli_flag_manager_instance = CLIFlagManager(script_dir_path=router_script_dir)
    claude_cli_executor_instance = ClaudeCLIExecutor(claude_cli_path=CLAUDE_CLI_PATH)
    
    log_router_activity("Core components initialized - MCP tools will be loaded when profile requires them")

async def initialize_router_components(mcp_config_file: Optional[str] = None):
    """
    Initialize all router components needed for ARIS.
    
    Args:
        mcp_config_file: Optional path to MCP configuration file
    """
    global TOOLS_SCHEMA, mcp_service_instance, prompt_formatter_instance, cli_flag_manager_instance, claude_cli_executor_instance
    
    # Ensure this is called only after logging is configured from cli.py
    log_router_activity("Initializing router components (services and globals)...")
    
    # Clean up any existing instances to allow re-initialization
    if mcp_service_instance and hasattr(mcp_service_instance, 'close') and callable(getattr(mcp_service_instance, 'close')):
        await mcp_service_instance.close()
    
    # Instantiate Services/Components
    router_script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Log the MCP config file for debugging
    if mcp_config_file:
        log_router_activity(f"Initializing with MCP config file: {mcp_config_file}")
        if os.path.exists(mcp_config_file):
            log_router_activity(f"MCP config file exists at: {mcp_config_file}")
            
            # Log the content of the MCP config file for debugging
            try:
                with open(mcp_config_file, 'r') as f:
                    config = json.load(f)
                
                if "mcpServers" in config:
                    server_types = {}
                    for server_name, server_config in config["mcpServers"].items():
                        server_type = server_config.get("type", "unknown")
                        if server_type not in server_types:
                            server_types[server_type] = []
                        server_types[server_type].append(server_name)
                    
                    log_router_activity(f"MCP server types found: {server_types}")
                    
                    # Check for stdio servers
                    if "stdio" in server_types:
                        log_router_activity(f"stdio-based MCP servers found: {server_types['stdio']}")
            except Exception as e:
                log_warning(f"Error analyzing MCP config file: {e}")
        else:
            log_warning(f"MCP config file doesn't exist at: {mcp_config_file}")
    else:
        log_router_activity("Initializing without MCP config file")
    
    # Initialize or reinitialize components
    mcp_service_instance = MCPService(mcp_config_file)  # Use provided config file or None for no MCP tools
    prompt_formatter_instance = PromptFormatter()
    cli_flag_manager_instance = CLIFlagManager(script_dir_path=router_script_dir)
    claude_cli_executor_instance = ClaudeCLIExecutor(claude_cli_path=CLAUDE_CLI_PATH)
    
    # Start tools schema refresh in background - don't block initialization
    log_router_activity("Starting tools schema refresh in background")
    refresh_task = asyncio.create_task(refresh_tools_schema())
    
    # Add a callback to handle completion without blocking
    def handle_initial_refresh_result(task):
        try:
            task.result()  # Get result to prevent unhandled exception warnings
            log_router_activity("Background tools schema refresh completed successfully")
        except asyncio.TimeoutError:
            log_warning("Background tools schema refresh timed out")
        except asyncio.CancelledError:
            log_warning("Background tools schema refresh was cancelled")
        except Exception as e:
            log_warning(f"Background tools schema refresh failed: {e}")
            # Make sure we continue even if MCP fails
            global TOOLS_SCHEMA
            TOOLS_SCHEMA = []
    
    refresh_task.add_done_callback(handle_initial_refresh_result)

async def refresh_tools_schema():
    """Refresh the tools schema from MCP servers."""
    global TOOLS_SCHEMA, mcp_service_instance
    
    if not mcp_service_instance:
        log_error("Cannot refresh tools schema: MCP service not initialized")
        return
    
    # Clear existing tools schema first to ensure clean state
    TOOLS_SCHEMA = []
    log_router_activity("Cleared existing tools schema before refresh")
    
    # Fetch MCP Tools Schema using MCPService
    if mcp_service_instance.is_sdk_available():
        try:
            # Set a timeout for the entire refresh operation - increased for slow MCP servers
            async with asyncio.timeout(60.0):  # 60 second timeout for MCP server startup
                log_router_activity("MCPService: Fetching tools from configured servers")
                fetched_schema = await mcp_service_instance.fetch_tools_schema()
                TOOLS_SCHEMA = fetched_schema if fetched_schema is not None else []
                log_debug(f"Refreshed tools schema with {len(TOOLS_SCHEMA)} tools")
                
                # Log each server's tools for debugging
                if TOOLS_SCHEMA:
                    server_tools = {}
                    for tool in TOOLS_SCHEMA:
                        if isinstance(tool, dict) and tool.get("name"):
                            server_name = tool.get("server_name", "unknown")
                            if server_name not in server_tools:
                                server_tools[server_name] = []
                            server_tools[server_name].append(tool["name"])
                    
                    log_router_activity(f"Available tools after refresh by server: {server_tools}")
                else:
                    log_router_activity("No tools available after refresh")
        except asyncio.TimeoutError:
            log_warning("Timeout while refreshing tools schema after 60s, continuing with empty schema")
            TOOLS_SCHEMA = []  # Ensure we have an empty list
        except asyncio.CancelledError:
            log_warning("Tools schema refresh was cancelled")
            TOOLS_SCHEMA = []  # Ensure we have an empty list
            # Re-raise to propagate the cancellation
            raise
        except Exception as e:
            log_error(f"Error in MCPService.fetch_tools_schema during refresh: {e}", exception_info=str(e))
            # Keep the empty tools schema in case of error
    else:
        log_warning("MCP SDK not available via MCPService, TOOLS_SCHEMA will be empty.")
        TOOLS_SCHEMA = []

def get_claude_cli_executor() -> Optional[ClaudeCLIExecutor]:
    """
    Get the current Claude CLI executor instance for signal handling.
    
    Returns:
        The ClaudeCLIExecutor instance or None if not initialized
    """
    return claude_cli_executor_instance

async def route(
    user_msg_for_turn: str,
    claude_session_to_resume: Optional[str] = None,
    tool_preferences: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    reference_file_path: Optional[str] = None,
    is_first_message: bool = False,
    progress_tracker: Optional[ProgressTracker] = None
) -> AsyncIterator[str]:
    """
    Routes user messages to Claude CLI with appropriate system prompt and tool configuration.
    
    Args:
        user_msg_for_turn: The user's message for the current turn
        claude_session_to_resume: Optional Claude session ID to resume
        tool_preferences: Optional list of tool names to make available
        system_prompt: Optional system prompt from an active profile
        reference_file_path: Optional path to referenced context file
        is_first_message: Whether this is the first message in a new session
        
    Yields:
        Streamed output from Claude
    """
    # Add a check to ensure components are initialized
    if not mcp_service_instance or not prompt_formatter_instance or not cli_flag_manager_instance or not claude_cli_executor_instance: 
        log_error("Orchestrator components not initialized. Call initialize_router_components() first.")
        yield json.dumps({"type": "error", "error": {"message": "Internal Server Error: Orchestrator not initialized."}}) + "\n"
        return
    
    log_router_activity(f"Orchestrator: Routing message - '{user_msg_for_turn[:100]}...', session: {claude_session_to_resume}")
    
    # Update progress tracking
    if progress_tracker:
        progress_tracker.update_phase(ExecutionPhase.PROCESSING_INPUT, "Preparing request")
    
    # Check if tools schema is available (non-blocking)
    if not TOOLS_SCHEMA:
        log_debug("Tools schema not yet available, will use empty schema for this request")
    
    # If this is the first message and there's a reference file, modify the message to instruct Claude to read it
    modified_user_msg = user_msg_for_turn
    if is_first_message and reference_file_path:
        modified_user_msg = prompt_formatter_instance.modify_first_message(user_msg_for_turn, reference_file_path)
        log_debug(f"Modified first message to include reference file instruction for {reference_file_path}")
    
    # Format the user's message for the current turn (no need to pass tools_schema)
    prompt_string = prompt_formatter_instance.format_prompt(modified_user_msg)
    
    # Get the current session state to access the MCP config file path
    from .cli import get_current_session_state, profile_manager
    session_state = get_current_session_state()
    mcp_config_path = None
    
    # More detailed logging about session state
    if session_state:
        log_router_activity(f"Session state exists: {type(session_state).__name__}")
        # Log all attributes of the session state for debugging
        for attr_name in dir(session_state):
            if not attr_name.startswith('_') and not callable(getattr(session_state, attr_name)):
                log_router_activity(f"Session state attribute: {attr_name} = {getattr(session_state, attr_name)}")
        
        # Always try to generate a fresh merged MCP config from the active profile first
        if hasattr(session_state, 'active_profile') and session_state.active_profile:
            active_profile = session_state.active_profile
            profile_name = active_profile.get("profile_name", "unknown")
            log_router_activity(f"Active profile name: {profile_name}")
            
            # Check if the profile has MCP config files
            if 'mcp_config_files' in active_profile and active_profile['mcp_config_files']:
                log_router_activity(f"Profile has MCP config files: {active_profile['mcp_config_files']}")
                
                # Generate a merged MCP config with the profile as-is
                log_router_activity(f"Generating merged MCP config from profile config files")
                mcp_config_path = profile_manager.get_merged_mcp_config_path(active_profile)
                
                log_router_activity(f"Generated merged MCP config at: {mcp_config_path}")
                
                # Update session state with the new merged config
                if mcp_config_path and os.path.exists(mcp_config_path):
                    session_state.mcp_config_file = mcp_config_path
                    log_router_activity(f"Updated session state with merged MCP config: {mcp_config_path}")
                    
                    # Verify the merged config contains all servers
                    try:
                        with open(mcp_config_path, 'r') as f:
                            merged_config = json.load(f)
                        if 'mcpServers' in merged_config:
                            servers = list(merged_config['mcpServers'].keys())
                            log_router_activity(f"Merged MCP config contains servers: {servers}")
                    except Exception as e:
                        log_warning(f"Error reading merged MCP config: {e}")
                
            # If there are no MCP config files specified in the profile, don't use any MCP config
            else:
                log_router_activity(f"Profile '{profile_name}' has no MCP config files specified")
                mcp_config_path = None
                session_state.mcp_config_file = None
        
        # If we still don't have a config path, try the existing one in session
        if (not mcp_config_path or not os.path.exists(mcp_config_path)) and hasattr(session_state, 'mcp_config_file') and session_state.mcp_config_file:
            mcp_config_path = session_state.mcp_config_file
            # Verify the file exists
            if os.path.exists(mcp_config_path):
                log_router_activity(f"Using existing MCP config from session: {mcp_config_path} (file exists)")
            else:
                log_router_activity(f"MCP config file from session doesn't exist: {mcp_config_path}")
                mcp_config_path = None
                
                # Verify the config path and update session state
                if mcp_config_path:
                    # Make sure we have an absolute path
                    mcp_config_abs_path = os.path.abspath(mcp_config_path)
                    
                    if os.path.exists(mcp_config_abs_path):
                        log_router_activity(f"Generated/found MCP config: {mcp_config_abs_path} (file exists)")
                        session_state.mcp_config_file = mcp_config_abs_path
                        
                        # Log the content of the MCP config file for debugging
                        try:
                            with open(mcp_config_abs_path, 'r') as f:
                                config_content = f.read()
                            log_router_activity(f"MCP config content: {config_content[:200]}...")
                        except Exception as e:
                            log_warning(f"Error reading MCP config file: {e}")
                        
                        # Reload MCP service with the new config in background
                        try:
                            if mcp_service_instance:
                                log_router_activity(f"Starting MCP service reload in background: {mcp_config_abs_path}")
                                
                                # Create a background task for the entire MCP reload + tools refresh
                                async def reload_mcp_and_refresh_tools():
                                    try:
                                        log_router_activity(f"Reloading MCP service with new config: {mcp_config_abs_path}")
                                        success = mcp_service_instance.reload_config(mcp_config_abs_path)
                                        log_router_activity(f"MCP config reload result: {success}")
                                        
                                        if success:
                                            log_router_activity("Refreshing tools schema after MCP config reload")
                                            await refresh_tools_schema()
                                            log_router_activity("Tools schema refresh completed successfully")
                                    except asyncio.TimeoutError:
                                        log_warning("Timeout in MCP reload and tools schema refresh")
                                    except Exception as e:
                                        log_warning(f"Error in MCP reload and tools refresh: {e}")
                                        import traceback
                                        log_error(f"Traceback: {traceback.format_exc()}")
                                
                                # Start the background task without blocking
                                reload_task = asyncio.create_task(reload_mcp_and_refresh_tools())
                                
                                # Add callback to handle completion without blocking
                                def handle_reload_completion(task):
                                    try:
                                        task.result()  # Get result to prevent unhandled exception warnings
                                    except Exception as e:
                                        log_warning(f"MCP reload background task failed: {e}")
                                
                                reload_task.add_done_callback(handle_reload_completion)
                            else:
                                log_warning("MCP service instance is None, cannot reload config")
                        except Exception as e:
                            log_warning(f"Error reloading MCP config: {e}")
                    else:
                        log_warning(f"MCP config file doesn't exist at: {mcp_config_abs_path}")
                        
                        # Log that config file doesn't exist and continue without it
                        log_router_activity(f"MCP config file doesn't exist and will not be used")
                else:
                    log_router_activity("Failed to generate/find MCP config from active profile")
    else:
        log_router_activity("No session state available")
    
    # Generate Claude CLI flags, including the system prompt if provided
    # Log details about the MCP config path for debugging
    log_router_activity(f"About to generate CLI flags with MCP config path: {mcp_config_path}")
    
    # Ensure the MCP config path is absolute and exists
    mcp_config_data = None
    if mcp_config_path:
        # Make sure we have an absolute path
        mcp_config_abs_path = os.path.abspath(mcp_config_path)
        log_router_activity(f"Using absolute MCP config path: {mcp_config_abs_path}")
        
        # Verify the file exists
        if os.path.exists(mcp_config_abs_path):
            log_router_activity(f"MCP config file exists: True")
            try:
                with open(mcp_config_abs_path, 'r') as f:
                    config_content = f.read()
                    mcp_config_data = json.loads(config_content)
                log_router_activity(f"MCP config content: {config_content[:200]}...")
                log_router_activity(f"Parsed MCP config servers: {list(mcp_config_data.get('mcpServers', {}).keys())}")
                
                # Use the absolute path to ensure Claude can find it
                mcp_config_path = mcp_config_abs_path
            except Exception as e:
                log_warning(f"Error reading/parsing MCP config file: {e}")
                mcp_config_data = None
        else:
            log_warning(f"MCP config file doesn't exist at: {mcp_config_abs_path}")
            
            # Log that config file doesn't exist and continue without it
            log_router_activity(f"MCP config file doesn't exist and will not be used")
            mcp_config_path = None
    else:
        log_router_activity("No MCP config path provided")
        
        # No MCP config path provided, continue without it
        log_router_activity(f"No MCP config path provided, will continue without it")
        mcp_config_path = None
            
    # Log warning for failed MCP servers but continue execution
    failed_servers = set()
    if mcp_service_instance and hasattr(mcp_service_instance, 'failed_servers'):
        failed_servers = mcp_service_instance.failed_servers
        if failed_servers and len(failed_servers) > 0:
            # Get profile name for better warning message
            profile_name = "unknown"
            if session_state and hasattr(session_state, 'active_profile') and session_state.active_profile:
                profile_name = session_state.active_profile.get('profile_name', 'unknown')
            
            log_warning(f"Some MCP servers failed to connect for profile '{profile_name}': {failed_servers}")
            log_warning("Continuing execution - MCP tools from failed servers will not be available")
    
    cli_flags = cli_flag_manager_instance.generate_claude_cli_flags(
        mcp_tools_schema=TOOLS_SCHEMA,
        system_prompt=system_prompt,
        tool_preferences=tool_preferences,
        mcp_config_path=mcp_config_path,
        mcp_config_data=mcp_config_data
    )
    
    # Execute Claude CLI with the formatted prompt and flags
    log_router_activity(f"Orchestrator: Handing off to ClaudeCLIExecutor.")
    
    # Update progress tracking
    if progress_tracker:
        if mcp_config_data and 'mcpServers' in mcp_config_data:
            server_count = len(mcp_config_data['mcpServers'])
            progress_tracker.update_phase(ExecutionPhase.GENERATING_RESPONSE, f"Starting Claude CLI with {server_count} MCP server(s)")
        else:
            progress_tracker.update_phase(ExecutionPhase.GENERATING_RESPONSE, "Starting Claude CLI")
    
    async for chunk in claude_cli_executor_instance.execute_cli(
        prompt_string=prompt_string,
        shared_flags=cli_flags,
        session_to_resume=claude_session_to_resume
    ):
        # Enhanced progress tracking with optional insights
        if progress_tracker and hasattr(progress_tracker, 'process_chunk_with_insights'):
            try:
                detail = progress_tracker.process_chunk_with_insights(chunk)
                if detail:
                    progress_tracker.update_detail(detail)
            except Exception as e:
                log_debug(f"Error processing chunk insights: {e}")
        elif progress_tracker:
            # Existing behavior preserved
            try:
                detail = parse_chunk_for_progress_detail(chunk)
                if detail:
                    progress_tracker.update_detail(detail)
            except Exception as e:
                log_debug(f"Error updating progress tracker: {e}")
        
        yield chunk
    
    # Mark progress as complete
    if progress_tracker:
        progress_tracker.update_phase(ExecutionPhase.COMPLETING, "Finalizing response")
    
    log_router_activity(f"Orchestrator: Finished processing request for message: '{user_msg_for_turn[:100]}...'")