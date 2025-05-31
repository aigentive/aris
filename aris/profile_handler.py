"""
Profile management for ARIS.
"""
import os
import json
import asyncio
from typing import Dict, List, Optional

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText

from .logging_utils import log_router_activity, log_warning, log_error, log_debug
from .profile_manager import profile_manager
from .session_state import SessionState, get_current_session_state, set_current_session_state

# Define a simple style for prompt_toolkit outputs
try:
    from .cli import cli_style
except ImportError:
    cli_style = None

def print_profile_list(profiles: Dict[str, Dict]):
    """
    Print a list of available profiles.
    
    Args:
        profiles: Dictionary of profiles from profile_manager.get_available_profiles()
    """
    print_formatted_text(FormattedText([("bold", "\nAvailable Profiles:")]), style=cli_style)
    
    # Group profiles by tags
    profiles_by_tag = {}
    for profile_ref, profile_info in profiles.items():
        for tag in profile_info.get('tags', ['uncategorized']):
            if tag not in profiles_by_tag:
                profiles_by_tag[tag] = []
            profiles_by_tag[tag].append((profile_ref, profile_info))
    
    # Sort tags
    sorted_tags = sorted(profiles_by_tag.keys())
    
    # Print profiles by tag
    for tag in sorted_tags:
        if tag == 'uncategorized' and len(sorted_tags) > 1:
            # Print uncategorized profiles last
            continue
        
        print_formatted_text(FormattedText([("class:profile.tag", f"\n[{tag}]")]), style=cli_style)
        
        # Sort profiles within tag by name
        sorted_profiles = sorted(profiles_by_tag[tag], key=lambda p: p[0])
        
        for profile_ref, profile_info in sorted_profiles:
            profile_name = profile_info.get('name', profile_ref)
            profile_desc = profile_info.get('description', '')
            
            print_formatted_text(FormattedText([
                ("class:profile.name", f"  {profile_ref}"),
                ("", ": "),
                ("class:profile.description", profile_desc[:100])
            ]), style=cli_style)
    
    # Print uncategorized profiles last if there are other categories
    if 'uncategorized' in profiles_by_tag and len(sorted_tags) > 1:
        print_formatted_text(FormattedText([("class:profile.tag", "\n[uncategorized]")]), style=cli_style)
        
        sorted_profiles = sorted(profiles_by_tag['uncategorized'], key=lambda p: p[0])
        
        for profile_ref, profile_info in sorted_profiles:
            profile_name = profile_info.get('name', profile_ref)
            profile_desc = profile_info.get('description', '')
            
            print_formatted_text(FormattedText([
                ("class:profile.name", f"  {profile_ref}"),
                ("", ": "),
                ("class:profile.description", profile_desc[:100])
            ]), style=cli_style)

def print_profile_details(profile: Dict):
    """
    Print detailed information about a profile with enhanced formatting.
    
    Args:
        profile: The profile data dictionary
    """
    # Header with visual separator
    print_formatted_text(FormattedText([
        ("bold", "\n" + "="*80),
        ("\n", ""),
        ("bold", "📋 PROFILE DETAILS"),
        ("\n", ""),
        ("bold", "="*80)
    ]), style=cli_style)
    
    # Basic profile information with icons
    print_formatted_text(FormattedText([
        ("bold", "\n🏷️  Name: "),
        ("class:profile.name", f"{profile.get('profile_name', 'Unknown')}"),
    ]), style=cli_style)
    
    if profile.get('description'):
        print_formatted_text(FormattedText([
            ("bold", "📝 Description: "),
            ("class:profile.description", f"{profile.get('description')}"),
        ]), style=cli_style)
    
    if profile.get('version'):
        print_formatted_text(FormattedText([
            ("bold", "🔢 Version: "),
            ("", f"{profile.get('version')}")
        ]), style=cli_style)
    
    if profile.get('author'):
        print_formatted_text(FormattedText([
            ("bold", "👤 Author: "),
            ("", f"{profile.get('author')}")
        ]), style=cli_style)
    
    # Inheritance
    if profile.get('extends'):
        extends = profile.get('extends')
        if isinstance(extends, list):
            extends_str = ", ".join(extends)
        else:
            extends_str = extends
        print_formatted_text(FormattedText([
            ("bold", "🔗 Extends: "),
            ("class:profile.description", extends_str)
        ]), style=cli_style)
    
    # System prompt - show full content with better formatting
    if profile.get('system_prompt'):
        system_prompt = profile.get('system_prompt', '')
        print_formatted_text(FormattedText([
            ("bold", "\n🧠 System Prompt:"),
            ("\n", ""),
            ("bold", "-" * 60)
        ]), style=cli_style)
        
        # Split into lines and add slight indentation for readability
        prompt_lines = system_prompt.split('\n')
        for line in prompt_lines:
            if line.strip():  # Skip empty lines for cleaner display
                print_formatted_text(f"  {line}", style=cli_style)
            else:
                print()  # Keep paragraph breaks
        
        print_formatted_text(FormattedText([
            ("bold", "-" * 60)
        ]), style=cli_style)
    
    if profile.get('system_prompt_file'):
        print_formatted_text(FormattedText([
            ("bold", "📄 System Prompt File: "),
            ("", f"{profile.get('system_prompt_file')}")
        ]), style=cli_style)
    
    # Tool preferences with better formatting
    if profile.get('tools'):
        tools = profile.get('tools')
        print_formatted_text(FormattedText([
            ("bold", "\n🛠️  Tools: "),
            ("class:profile.description", ', '.join(tools))
        ]), style=cli_style)
    
    # Context files
    if profile.get('context_files'):
        context_files = profile.get('context_files')
        print_formatted_text(FormattedText([
            ("bold", "\n📁 Context Files: "),
            ("", ', '.join(context_files))
        ]), style=cli_style)
        print_formatted_text(FormattedText([
            ("bold", "📂 Context Mode: "),
            ("", f"{profile.get('context_mode', 'auto')}")
        ]), style=cli_style)
    
    # MCP config files
    if profile.get('mcp_config_files'):
        mcp_configs = profile.get('mcp_config_files')
        print_formatted_text(FormattedText([
            ("bold", "\n⚙️  MCP Config Files: "),
            ("class:profile.description", ', '.join(mcp_configs))
        ]), style=cli_style)
        
    # Welcome message (with variables substituted if session is active)
    if profile.get('welcome_message'):
        welcome_message = profile.get("welcome_message")
        
        # Substitute variables if session is active
        session_state = get_current_session_state()
        if session_state and session_state.profile_variables:
            from .prompt_formatter import prompt_formatter_instance
            welcome_message, _ = prompt_formatter_instance.prepare_system_prompt(
                welcome_message,
                template_variables=session_state.profile_variables
            )
        
        print_formatted_text(FormattedText([
            ("bold", "\n💬 Welcome Message: "),
            ("class:profile.description", welcome_message)
        ]), style=cli_style)
    
    # Variables with enhanced formatting
    if profile.get('variables'):
        variables = profile.get('variables')
        print_formatted_text(FormattedText([
            ("bold", "\n🔧 Template Variables:")
        ]), style=cli_style)
        for var in variables:
            if isinstance(var, dict):
                var_name = var.get('name', 'Unknown')
                var_desc = var.get('description', '')
                var_required = var.get('required', True)
                var_default = var.get('default', 'None')
                
                # Get current value if available
                current_value = None
                # Get the session state to access the current variable values
                session_state = get_current_session_state()
                if session_state and session_state.profile_variables and var_name in session_state.profile_variables:
                    current_value = session_state.profile_variables.get(var_name)
                
                print_formatted_text(FormattedText([
                    ("class:variable.name", f"  • {var_name}"),
                    ("", ": "),
                    ("class:variable.description", var_desc),
                ]), style=cli_style)
                
                req_str = "Required" if var_required else "Optional"
                def_str = f", Default: {var_default}" if var_default is not None else ""
                curr_str = f", Current: {current_value}" if current_value else ""
                print_formatted_text(f"    ({req_str}{def_str}{curr_str})", style=cli_style)

    # Tags section
    if profile.get('tags'):
        tags = profile.get('tags')
        print_formatted_text(FormattedText([
            ("bold", "\n🏷️  Tags: "),
            ("class:profile.tag", ', '.join(tags))
        ]), style=cli_style)
    
    # Footer
    print_formatted_text(FormattedText([
        ("bold", "\n" + "="*80 + "\n")
    ]), style=cli_style)

def collect_template_variables(profile: Dict) -> Dict[str, str]:
    """
    Collect template variable values from the user.
    
    Args:
        profile: The profile data dictionary
        
    Returns:
        Dictionary mapping variable names to values
    """
    variables = profile_manager.get_variables_from_profile(profile)
    
    if not variables:
        return {}
    
    print_formatted_text(FormattedText([
        ("bold", f"\nProfile '{profile.get('profile_name')}' requires the following information:")
    ]), style=cli_style)
    
    values = {}
    
    for var in variables:
        var_name = var.name
        var_desc = var.description
        var_required = var.required
        var_default = var.default
        
        prompt_str = f"{var_name} "
        if var_desc:
            prompt_str += f"[{var_desc}]"
        
        if var_default is not None:
            prompt_str += f" (default: {var_default})"
        
        prompt_str += ": "
        
        # Get input with validation for required variables
        while True:
            value = input(prompt_str)
            
            if not value:
                if var_default is not None:
                    value = var_default
                    break
                elif not var_required:
                    break
                else:
                    print_formatted_text(FormattedText([
                        ("class:error", f"Error: {var_name} is required. Please enter a value.")
                    ]), style=cli_style)
                    continue
            else:
                break
        
        values[var_name] = value
    
    return values

def handle_variables_command(cmd_args: str, session_state: SessionState):
    """
    Handle the @profile variables command.
    
    Args:
        cmd_args: The arguments to the command
        session_state: The current session state
    """
    if not session_state.active_profile:
        print_formatted_text(FormattedText([
            ("class:error", "Error: No active profile.")
        ]), style=cli_style)
        return
    
    # Parse command arguments
    args = cmd_args.strip().split(maxsplit=1)
    
    if not args:
        # Show all variables
        if not session_state.profile_variables:
            print_formatted_text("No template variables are set for the active profile.", style=cli_style)
            return
        
        print_formatted_text(FormattedText([
            ("bold", "\nTemplate Variables for active profile:")
        ]), style=cli_style)
        
        for var_name, var_value in session_state.profile_variables.items():
            print_formatted_text(FormattedText([
                ("class:variable.name", f"  {var_name}"),
                ("", ": "),
                ("", var_value)
            ]), style=cli_style)
    
    elif len(args) == 1:
        # Show one variable
        var_name = args[0]
        
        if var_name not in session_state.profile_variables:
            print_formatted_text(FormattedText([
                ("class:error", f"Error: Variable '{var_name}' not found in active profile.")
            ]), style=cli_style)
            return
        
        var_value = session_state.profile_variables.get(var_name)
        print_formatted_text(FormattedText([
            ("class:variable.name", f"{var_name}"),
            ("", ": "),
            ("", var_value)
        ]), style=cli_style)
    
    elif len(args) == 2:
        # Set variable value
        var_name = args[0]
        var_value = args[1]
        
        # Check if the variable exists in the profile
        variables = profile_manager.get_variables_from_profile(session_state.active_profile)
        var_exists = any(var.name == var_name for var in variables)
        
        if not var_exists:
            print_formatted_text(FormattedText([
                ("class:warning", f"Warning: '{var_name}' is not declared in the profile, but will be set anyway.")
            ]), style=cli_style)
        
        # Set the variable
        session_state.profile_variables[var_name] = var_value
        # Update global session state reference
        set_current_session_state(session_state)
        print_formatted_text(FormattedText([
            ("", f"Variable '{var_name}' set to: "),
            ("class:variable.name", var_value)
        ]), style=cli_style)

def create_profile_interactive(profile_name: str):
    """Launch the interactive profile creation wizard."""
    result = profile_manager.create_profile_interactive(profile_name)
    
    if result:
        print_formatted_text(FormattedText([
            ("bold", f"\nProfile '{profile_name}' created successfully at {result}")
        ]), style=cli_style)
    else:
        print_formatted_text(FormattedText([
            ("class:error", f"\nFailed to create profile '{profile_name}'")
        ]), style=cli_style)

def activate_profile(profile_name: str, session_state: SessionState) -> bool:
    """
    Activate a profile.
    
    Args:
        profile_name: The name of the profile to activate
        session_state: The current session state
        
    Returns:
        True if the profile was activated successfully, False otherwise
    """
    try:
        # Get workspace variables from session state if available
        workspace_variables = {}
        if session_state.workspace_path:
            from .workspace_manager import workspace_manager
            workspace_variables = workspace_manager.get_workspace_variables(session_state.workspace_path)
        
        profile = profile_manager.get_profile(profile_name, resolve=True, workspace_variables=workspace_variables)
        if profile:
            # Get template variables
            variables = collect_template_variables(profile)
            
            # Merge workspace variables with template variables (workspace takes precedence)
            merged_variables = {**variables, **workspace_variables}
            
            # Update session state
            session_state.active_profile = profile
            session_state.profile_variables = merged_variables
            
            # First, completely reset any existing MCP configuration
            # This is essential to avoid inheriting servers from previous profiles
            log_router_activity(f"Completely resetting MCP configuration for profile: {profile_name}")
            session_state.mcp_config_file = None
            
            # Reset MCP service to remove all previous servers and tools
            try:
                from .orchestrator import mcp_service_instance
                if mcp_service_instance:
                    log_router_activity(f"Forcefully clearing all MCP servers and tools before loading new profile")
                    mcp_service_instance.mcp_servers = {}
                    mcp_service_instance.stdio_servers = {}
                    mcp_service_instance.failed_servers = set()
            except Exception as e:
                log_warning(f"Error resetting MCP service instance: {e}")
            
            # Standard handling for all profiles - only use MCP configs if they're defined in the profile
            if 'mcp_config_files' in profile and profile['mcp_config_files']:
                log_router_activity(f"Profile defines MCP config files: {profile['mcp_config_files']}")
                mcp_config_path = profile_manager.get_merged_mcp_config_path(profile)
                log_router_activity(f"Setting MCP config file in session state from profile configs: {mcp_config_path}")
                session_state.mcp_config_file = mcp_config_path
            else:
                # Profile has no MCP config files, set to None explicitly
                log_router_activity(f"Profile '{profile_name}' has no MCP config files, setting to None")
                session_state.mcp_config_file = None
            
            # Verify the file exists
            if session_state.mcp_config_file and os.path.exists(session_state.mcp_config_file):
                log_router_activity(f"MCP config file exists at: {session_state.mcp_config_file}")
                
                # Verify the content of the MCP config file
                try:
                    with open(session_state.mcp_config_file, 'r') as f:
                        mcp_config = json.load(f)
                    
                    if 'mcpServers' in mcp_config:
                        server_names = list(mcp_config['mcpServers'].keys())
                        log_router_activity(f"MCP config file contains mcpServers: {server_names}")
                    else:
                        log_warning(f"MCP config file is missing mcpServers section")
                except Exception as e:
                    log_warning(f"Error verifying MCP config file content: {e}")
            else:
                log_router_activity(f"Warning: MCP config file doesn't exist at: {session_state.mcp_config_file}")
            
            # Update global session state reference
            set_current_session_state(session_state)
            
            # Conditionally start MCP servers if the profile needs them
            try:
                from .mcp_startup_analyzer import MCPStartupAnalyzer
                from .cli import _start_profile_mcp_server, _start_workflow_mcp_server
                from .cli_args import PARSED_ARGS
                
                # Analyze what MCP servers this profile needs
                mcp_requirements = MCPStartupAnalyzer.analyze_profile_mcp_requirements(profile_name)
                
                # Determine which servers should start
                should_start_profile_mcp = MCPStartupAnalyzer.should_start_profile_mcp_server(mcp_requirements, PARSED_ARGS)
                should_start_workflow_mcp = MCPStartupAnalyzer.should_start_workflow_mcp_server(mcp_requirements, PARSED_ARGS)
                
                # Log startup decision
                MCPStartupAnalyzer.log_startup_decision(
                    mcp_requirements, 
                    should_start_profile_mcp, 
                    should_start_workflow_mcp,
                    verbose=getattr(PARSED_ARGS, 'verbose', False)
                )
                
                # Start servers if needed (asynchronously to avoid blocking)
                if should_start_profile_mcp:
                    # Check global state to see if profile server is already started
                    from .cli import is_profile_mcp_server_started
                    
                    if not is_profile_mcp_server_started():
                        log_router_activity("Starting Profile MCP Server for profile switch")
                        task = asyncio.create_task(_start_profile_mcp_server())
                        def mark_profile_server_started(t):
                            if not t.exception():
                                log_router_activity("Profile MCP Server startup completed")
                            else:
                                log_warning(f"Profile MCP Server startup failed: {t.exception()}")
                        task.add_done_callback(mark_profile_server_started)
                    else:
                        log_router_activity("Profile MCP Server already running, skipping startup")
                
                if should_start_workflow_mcp:
                    # Check global state to see if workflow server is already started
                    from .cli import is_workflow_mcp_server_started
                    
                    if not is_workflow_mcp_server_started():
                        log_router_activity("Starting Workflow MCP Server for profile switch")
                        task = asyncio.create_task(_start_workflow_mcp_server())
                        def mark_workflow_server_started(t):
                            if not t.exception():
                                log_router_activity("Workflow MCP Server startup completed")
                            else:
                                log_warning(f"Workflow MCP Server startup failed: {t.exception()}")
                        task.add_done_callback(mark_workflow_server_started)
                    else:
                        log_router_activity("Workflow MCP Server already running, skipping startup")
                
                # Give servers a moment to start before trying to connect
                if should_start_profile_mcp or should_start_workflow_mcp:
                    import time
                    time.sleep(2)  # Brief pause to allow server startup
                    
            except Exception as e:
                log_warning(f"Error in conditional MCP server startup during profile switch: {e}")
            
            # Reload MCP service with the new config
            try:
                # Avoid circular import by using a direct import from cc_so_orchestrator
                from .orchestrator import mcp_service_instance, refresh_tools_schema
                if mcp_service_instance:
                    # Log debugging info about MCP config file
                    if session_state.mcp_config_file and os.path.exists(session_state.mcp_config_file):
                        try:
                            with open(session_state.mcp_config_file, 'r') as f:
                                config_content = f.read()
                            log_router_activity(f"MCP config file content before reload: {config_content[:200]}...")
                        except Exception as e:
                            log_warning(f"Error reading MCP config file: {e}")
                    
                    # Reset the MCP service first to clear any existing tools
                    log_router_activity(f"Resetting MCP service instance before reloading config")
                    
                    # Reload the configuration and check for success
                    log_router_activity(f"Loading new MCP config from file: {session_state.mcp_config_file}")
                    success = mcp_service_instance.reload_config(session_state.mcp_config_file)
                    log_router_activity(f"MCP config reload result: {success}")
                    
                    # Verify the servers in the MCP service after reload
                    log_router_activity(f"MCP servers after reload: {list(mcp_service_instance.mcp_servers.keys())}")
                    
                    # Refresh tools schema directly after reload to ensure tools are available
                    # Create a task for refreshing the tools schema and add done callback to prevent warnings
                    task = asyncio.create_task(refresh_tools_schema())
                    
                    # Add a callback to handle any exceptions in the task
                    def handle_task_result(task):
                        try:
                            if task.cancelled():
                                log_debug("Tools schema refresh task was cancelled")
                                return
                            # Get the result to prevent unhandled exception warnings
                            task.result()
                            log_router_activity("Tools schema refresh completed successfully")
                            
                            # Log all available tools after refresh
                            from .orchestrator import TOOLS_SCHEMA
                            if TOOLS_SCHEMA:
                                server_tools = {}
                                for tool in TOOLS_SCHEMA:
                                    if isinstance(tool, dict) and tool.get("name"):
                                        server_name = tool.get("server_name", "unknown")
                                        if server_name not in server_tools:
                                            server_tools[server_name] = []
                                        server_tools[server_name].append(tool["name"])
                                
                                log_router_activity(f"Available tools after refresh by server: {server_tools}")
                        except Exception as e:
                            log_warning(f"Error in refresh_tools_schema task: {e}")
                    
                    task.add_done_callback(handle_task_result)
                else:
                    log_warning("MCP service instance is None, cannot reload config")
            except ImportError as e:
                log_warning(f"Could not import mcp_service_instance for config reload: {e}")
            except Exception as e:
                log_warning(f"Error reloading MCP config: {e}")
            
            # Mark session as new to trigger first message handling
            session_state.is_new_session = True
            
            # Show welcome message with variables substituted (only in interactive mode)
            try:
                from .cli import _SUPPRESS_INTERACTIVE_OUTPUT
                suppress_output = _SUPPRESS_INTERACTIVE_OUTPUT
            except ImportError:
                suppress_output = False
                
            if not suppress_output:
                if profile.get("welcome_message"):
                    # Use the prompt formatter to substitute variables in welcome message
                    from .prompt_formatter import prompt_formatter_instance
                    welcome_message = profile.get("welcome_message")
                    # Apply variable substitution to welcome message
                    welcome_message, _ = prompt_formatter_instance.prepare_system_prompt(
                        welcome_message,
                        template_variables=session_state.profile_variables
                    )
                    print_formatted_text(FormattedText([
                        ("bold fg:blue", welcome_message)
                    ]), style=cli_style)
                else:
                    print_formatted_text(FormattedText([
                        ("bold fg:blue", f"Profile '{profile_name}' activated.")
                    ]), style=cli_style)
                
            return True
        else:
            print_formatted_text(FormattedText([
                ("class:error", f"Profile '{profile_name}' not found. Use @profile list to see available profiles.")
            ]), style=cli_style)
            return False
    except Exception as e:
        print_formatted_text(FormattedText([
            ("class:error", f"Error loading profile: {str(e)}")
        ]), style=cli_style)
        log_error(f"Error loading profile {profile_name}: {e}")
        return False

def process_special_commands(cmd_text: str, session_state: SessionState) -> bool:
    """
    Process special @ commands.
    
    Args:
        cmd_text: The command text starting with @
        session_state: The current session state
        
    Returns:
        True if the command was processed, False otherwise
    """
    # Process profile commands
    if cmd_text.startswith("@profile"):
        parts = cmd_text.split(maxsplit=2)
        if len(parts) < 2:
            print_formatted_text(FormattedText([
                ("class:error", "Usage: @profile [list|show|current|<profile_name>|clear|refresh|create|variables]")
            ]), style=cli_style)
            return True
        
        profile_cmd = parts[1]
        
        if profile_cmd == "list":
            # List all available profiles
            profiles = profile_manager.get_available_profiles()
            print_profile_list(profiles)
        elif profile_cmd == "show" or profile_cmd == "current":
            # Show current or specified profile
            if len(parts) > 2 and profile_cmd == "show":
                profile_name = parts[2].split()[0]  # Get profile name, ignoring flags
                show_effective = "--effective" in parts[2]
                profile = profile_manager.get_profile(profile_name, resolve=show_effective)
            else:
                # Show current profile
                profile = session_state.active_profile
            
            if profile:
                print_profile_details(profile)
            else:
                print_formatted_text(FormattedText([
                    ("class:error", "No active profile" if profile_cmd == "current" else f"Profile '{parts[2]}' not found.")
                ]), style=cli_style)
        elif profile_cmd == "clear" or profile_cmd == "default":
            # Clear active profile
            session_state.clear_profile()
            # Update global session state reference
            set_current_session_state(session_state)
            print_formatted_text(FormattedText([
                ("class:warning", "Profile cleared. Using default CC-SO behavior.")
            ]), style=cli_style)
        elif profile_cmd == "refresh":
            # Refresh profile registry
            profile_manager.refresh_profiles()
            print_formatted_text(FormattedText([
                ("", "Profile registry refreshed.")
            ]), style=cli_style)
        elif profile_cmd == "create":
            # Interactive wizard to create a new profile
            if len(parts) < 3:
                print_formatted_text(FormattedText([
                    ("class:error", "Usage: @profile create <new_profile_name>")
                ]), style=cli_style)
            else:
                new_profile_name = parts[2]
                create_profile_interactive(new_profile_name)
        elif profile_cmd == "variables":
            # View or set template variables
            handle_variables_command(parts[2] if len(parts) > 2 else "", session_state)
        else:
            # Load a profile by name
            profile_name = profile_cmd
            activate_profile(profile_name, session_state)
        
        return True
    
    # Not a special command
    return False