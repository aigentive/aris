"""
Main entry point for ARIS.
"""
import os
import sys
import asyncio
import threading
import signal
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

# Import local modules
from .logging_utils import log_router_activity, log_warning, log_error, log_debug
from .cli_args import initialize_environment, PARSED_ARGS, INITIAL_VOICE_MODE, TEXT_MODE_TTS_ENABLED, TRIGGER_WORDS
from .session_state import SessionState, get_current_session_state, set_current_session_state
from .interaction_handler import print_welcome_message, text_mode_one_turn
from .voice_handler import VoiceHandler
from .profile_manager import profile_manager
from .profile_handler import activate_profile
from .interrupt_handler import InterruptHandler
from .workspace_manager import workspace_manager

# Global variable to indicate if full initialization is done
_APP_INITIALIZED = False

# Global interrupt handler instance
interrupt_handler = InterruptHandler()

# Global flag to suppress interactive output in non-interactive mode
_SUPPRESS_INTERACTIVE_OUTPUT = False


def detect_execution_mode(args) -> Tuple[str, Optional[str]]:
    """
    Determine execution mode based on input sources.
    
    Priority:
    1. --input flag (explicit non-interactive)
    2. stdin input available (automatic non-interactive)  
    3. default (interactive mode)
    
    Returns:
        Tuple of (mode, input_text) where mode is 'interactive' or 'non_interactive'
    """
    # Check for explicit --input flag (including empty strings)
    if hasattr(args, 'input') and args.input is not None:
        return "non_interactive", args.input
    
    # Check if stdin has input available
    if not sys.stdin.isatty():
        try:
            stdin_input = sys.stdin.read().strip()
            if stdin_input:
                return "non_interactive", stdin_input
        except Exception as e:
            log_error(f"Failed to read from stdin: {e}")
    
    return "interactive", None


def parse_claude_response_stream(response_chunks: List[str]) -> str:
    """
    Parse Claude CLI JSON stream IDENTICALLY to how interactive mode handles it.
    
    This preserves the EXACT SAME response processing logic.
    """
    response_content = []
    final_result = None
    
    for chunk in response_chunks:
        if not chunk.strip():
            continue
            
        try:
            # Parse each JSON chunk exactly like interactive mode
            data = json.loads(chunk)
            
            # Handle all the same event types as interactive mode
            if data.get('type') == 'text':
                # Main response content
                response_content.append(data.get('text', ''))
            elif data.get('type') == 'assistant':
                # Assistant message with content
                message = data.get('message', {})
                content = message.get('content', [])
                for item in content:
                    if item.get('type') == 'text':
                        response_content.append(item.get('text', ''))
            elif data.get('type') == 'result':
                # Final result from Claude CLI - use this as the authoritative response
                result_text = data.get('result', '')
                if result_text:
                    final_result = result_text
            elif data.get('type') == 'tool_use':
                # Tool usage events (preserve all tool functionality)
                # In non-interactive, we don't show tool usage but tools still execute
                pass
            elif data.get('type') == 'error':
                # Error handling (preserve all error reporting)
                error_msg = data.get('error', {}).get('message', 'Unknown error')
                raise RuntimeError(f"Claude error: {error_msg}")
            # Add handling for other event types as needed
            
        except json.JSONDecodeError:
            # Handle malformed JSON (same as interactive)
            continue
        except Exception as e:
            # Preserve all error handling from interactive mode
            raise
    
    # Return the final result if available (most authoritative), otherwise assembled content
    if final_result:
        return final_result.strip()
    else:
        return "".join(response_content).strip()


async def execute_single_turn(user_input: str, session_state) -> str:
    """
    Execute single request/response turn using IDENTICAL logic to interactive mode.
    
    This uses the EXACT SAME route() function that interactive mode uses.
    """
    from .orchestrator import route
    
    # Use IDENTICAL route call as in text_mode_one_turn
    response_chunks = []
    
    async for chunk in route(
        user_msg_for_turn=user_input,
        claude_session_to_resume=session_state.session_id,  # Support session resumption
        tool_preferences=session_state.get_tool_preferences(),
        system_prompt=session_state.get_system_prompt(),
        reference_file_path=session_state.reference_file_path,
        is_first_message=session_state.is_first_message()
    ):
        response_chunks.append(chunk)
    
    # Parse the IDENTICAL JSON stream that interactive mode receives
    return parse_claude_response_stream(response_chunks)


async def execute_non_interactive_mode(user_input: str):
    """
    Execute non-interactive mode with FULL functionality parity.
    
    This must preserve ALL core functionality from interactive mode.
    """
    exit_code = 0
    
    try:
        # Get current session state (should be set up by fully_initialize_app_components)
        from .session_state import get_current_session_state
        session_state = get_current_session_state()
        
        if not session_state:
            log_error("Session state not initialized for non-interactive mode")
            print("Error: Session state not initialized", file=sys.stderr)
            exit_code = 1
            return
        
        # Execute single turn using SAME route function as interactive
        response = await execute_single_turn(user_input, session_state)
        
        # Output response to stdout
        print(response)
        
    except Exception as e:
        # Log error and exit with error code
        log_error(f"Non-interactive execution failed: {e}")
        print(f"Error: {e}", file=sys.stderr)
        exit_code = 1
    finally:
        # IDENTICAL cleanup to interactive mode
        workspace_manager.restore_original_directory()
    
    # Exit with appropriate code
    log_debug(f"About to exit non-interactive mode with code: {exit_code}")
    sys.exit(exit_code)

# Define a simple style for prompt_toolkit outputs
cli_style = Style.from_dict({
    'prompt.user': 'bold fg:green',
    'prompt.assistant.prefix': 'bold fg:cyan',
    'prompt.assistant.text': 'fg:cyan',
    'prompt.thinking': 'italic fg:gray',
    'error': 'fg:ansired bold',
    'warning': 'fg:ansiyellow',
    'profile.name': 'bold fg:blue',
    'profile.description': 'fg:blue',
    'profile.tag': 'italic fg:gray',
    'variable.name': 'bold fg:magenta',
    'variable.description': 'fg:magenta'
})

async def fully_initialize_app_components():
    """Initialize all components needed for the CLI."""
    global _APP_INITIALIZED
    if _APP_INITIALIZED:
        return
    
    # Check if PARSED_ARGS is initialized, if not, initialize it
    global PARSED_ARGS, INITIAL_VOICE_MODE
    if PARSED_ARGS is None:
        log_error("PARSED_ARGS is None - calling initialize_environment() automatically")
        initialize_environment()
        # Re-import the updated globals
        from .cli_args import PARSED_ARGS, INITIAL_VOICE_MODE
    
    # Initialize without MCP config - it will be loaded when a profile is activated
    from .orchestrator import initialize_router_components
    await initialize_router_components()
    
    # TTS enablement logic that depends on other modules/args
    if PARSED_ARGS.speak and not INITIAL_VOICE_MODE: 
        log_debug(f"Attempting to enable TTS for text mode. PARSED_ARGS.speak: {PARSED_ARGS.speak}, INITIAL_VOICE_MODE: {INITIAL_VOICE_MODE}")
        
        from .tts_handler import _ensure_voice_dependencies, _init_openai_clients_for_tts
        
        dependencies_ok = _ensure_voice_dependencies()
        log_debug(f"_ensure_voice_dependencies() returned: {dependencies_ok}")
        
        clients_ok = False  # Assume false until proven true
        if dependencies_ok:  # Only try to init clients if dependencies are there
            clients_ok = _init_openai_clients_for_tts()
            log_debug(f"_init_openai_clients_for_tts() returned: {clients_ok}")
        else:
            log_warning("Skipped OpenAI client init for TTS because voice dependencies are missing.")

        if not dependencies_ok or not clients_ok:
            current_reason = []
            if not dependencies_ok: 
                current_reason.append("missing voice dependencies")
            if not clients_ok: 
                current_reason.append("OpenAI client initialization failed (check API key or connection)")
            reason_str = " and ".join(current_reason)
            log_warning(f"TTS via --speak could not be enabled at startup ({reason_str}). TTS for text mode remains disabled.")
            # Ensure it's off if setup failed
        else:
            log_router_activity("TTS for text mode enabled at startup via --speak flag.")
            # If it wasn't, there's a logic error there. For now, let's re-affirm if --speak is true.
            if PARSED_ARGS.speak:  # Re-check here to be absolutely sure if all checks passed.
                from .cli_args import TEXT_MODE_TTS_ENABLED
                log_router_activity("Setting TEXT_MODE_TTS_ENABLED to True based on --speak flag")
            else:  # Should not happen if PARSED_ARGS.speak was the entry condition for this block.
                log_warning("Logic error: TTS enablement block entered without --speak flag being true initially.")
                
    # Conditional MCP Server Startup - analyze profile requirements first
    try:
        from .mcp_startup_analyzer import MCPStartupAnalyzer
        
        # Analyze what MCP servers the target profile actually needs
        target_profile = MCPStartupAnalyzer.get_target_profile_name(PARSED_ARGS)
        mcp_requirements = MCPStartupAnalyzer.analyze_profile_mcp_requirements(target_profile)
        
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
        
        # Conditionally start Profile MCP Server
        if should_start_profile_mcp:
            await _start_profile_mcp_server()
        
        # Conditionally start Workflow MCP Server
        if should_start_workflow_mcp:
            await _start_workflow_mcp_server()
            
    except Exception as e:
        log_error(f"Failed to analyze MCP requirements, falling back to unconditional startup: {e}")
        if getattr(PARSED_ARGS, 'verbose', False):
            print(f"Warning: MCP analysis failed, starting all servers: {e}")
        
        # Fallback to unconditional startup if analysis fails
        # Check session state to avoid double startup
        from .session_state import get_current_session_state
        session_state = get_current_session_state()
        
        if not PARSED_ARGS.no_profile_mcp_server and (not session_state or not session_state.profile_mcp_server_started):
            await _start_profile_mcp_server()
        if not getattr(PARSED_ARGS, 'no_workflow_mcp_server', False) and (not session_state or not session_state.workflow_mcp_server_started):
            await _start_workflow_mcp_server()
    
    if INITIAL_VOICE_MODE and TRIGGER_WORDS:
        log_router_activity(f"Voice mode starting with trigger words: {TRIGGER_WORDS}")
    elif INITIAL_VOICE_MODE:
        log_router_activity("Voice mode starting with no specific trigger words (will process all speech).")

    # Setup workspace if specified
    workspace_path = None
    if hasattr(PARSED_ARGS, 'workspace') and PARSED_ARGS.workspace:
        try:
            # Resolve and setup workspace
            workspace_path = workspace_manager.resolve_workspace_path(PARSED_ARGS.workspace)
            original_cwd = workspace_manager.setup_workspace(workspace_path)
            log_router_activity(f"Workspace setup completed: {workspace_path}")
        except Exception as e:
            log_error(f"Failed to setup workspace '{PARSED_ARGS.workspace}': {e}")
            print(f"Warning: Failed to setup workspace '{PARSED_ARGS.workspace}': {e}")
            workspace_path = None
    
    # Initialize session state for initial profile
    profile_name = PARSED_ARGS.profile if hasattr(PARSED_ARGS, 'profile') and PARSED_ARGS.profile else "default"
    log_router_activity(f"Using initial profile: {profile_name}")
    
    # Initialize session state
    initial_session = SessionState()
    
    # Set workspace information in session state
    if workspace_path:
        initial_session.workspace_path = workspace_path
        initial_session.original_cwd = workspace_manager.original_cwd
    
    set_current_session_state(initial_session)  # Update the global reference
    
    # If a profile was specified, activate it
    if profile_name:
        profile = profile_manager.get_profile(profile_name, resolve=True)
        if profile:
            log_router_activity(f"Loading profile '{profile_name}' at startup")
            activate_profile(profile_name, initial_session)

    _APP_INITIALIZED = True
    log_router_activity("All application components initialized.")

async def run_cli_orchestrator():
    """
    Main CLI orchestrator loop.
    
    This handles the application's main loop, switching between text and voice modes,
    and processing user input through the assistant.
    """
    
    # Initialize the global interrupt handler
    global interrupt_handler
    interrupt_handler.initialize()
    
    # Register exit callback
    def exit_application():
        """Callback for application exit on third CTRL+C."""
        raise KeyboardInterrupt()
    
    interrupt_handler.register_exit_callback(exit_application)
    
    # Force re-installation of our signal handler in case asyncio overrode it
    # This is a workaround for asyncio's signal handling behavior
    signal.signal(signal.SIGINT, interrupt_handler._handle_interrupt)
    
    # Start a background task to periodically check and restore our signal handler
    async def ensure_signal_handler():
        """Periodically check and restore our signal handler if needed."""
        while True:
            try:
                await asyncio.sleep(0.5)
                current = signal.getsignal(signal.SIGINT)
                if current != interrupt_handler._handle_interrupt:
                    log_debug(f"Signal handler was changed to {current}, restoring...")
                    signal.signal(signal.SIGINT, interrupt_handler._handle_interrupt)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_debug(f"Error in ensure_signal_handler: {e}")
    
    # Start the signal handler checker
    asyncio.create_task(ensure_signal_handler())
    
    # Determine the profile name for welcome message
    profile_name = "default"
    if hasattr(PARSED_ARGS, 'profile') and PARSED_ARGS.profile:
        profile_name = PARSED_ARGS.profile
    
    print_welcome_message(profile_name)
    log_router_activity(f"Chat session started: {datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    
    # Initialize history file
    history_path = os.path.expanduser('~/.aris_history')
    try: 
        history = FileHistory(history_path)
    except Exception as e: 
        log_warning(f"Could not load history file at {history_path}: {e}. Using in-memory history.")
        history = None 
        
    prompt_session = PromptSession(
        history=history, 
        auto_suggest=AutoSuggestFromHistory() if history else None, 
        style=cli_style
    )
    
    # Initialize voice handler
    voice_handler = VoiceHandler(trigger_words=TRIGGER_WORDS)
    
    # Get the current session state
    session_state = get_current_session_state()
    if not session_state:
        session_state = SessionState()
        set_current_session_state(session_state)
    
    # Determine initial mode
    active_mode = 'voice' if INITIAL_VOICE_MODE else 'text'

    if active_mode == 'voice':
        if voice_handler.initialize():
            profile_name = "default"
            if hasattr(session_state, 'active_profile') and session_state.active_profile:
                profile_name = session_state.active_profile.get("profile_name", "default")
                
            print_formatted_text(FormattedText([
                ("bold fg:magenta", f"🎙️ Voice mode enabled with profile '{profile_name}'."), 
                ("", " Say '/voice off' to switch to text. Ctrl+C to exit.")
            ]), style=cli_style)
        else: 
            log_error("[Orchestrator] Failed to initialize voice components for voice mode. Switching to text mode.")
            active_mode = 'text'
    
    if active_mode == 'text':
        profile_name = "default"
        if hasattr(session_state, 'active_profile') and session_state.active_profile:
            profile_name = session_state.active_profile.get("profile_name", "default")
            
        print_formatted_text(FormattedText([
            ("bold fg:green", f"⌨️ Text mode enabled with profile '{profile_name}'."), 
            ("", " Type '/voice on' to switch or '/speak on' for TTS output. 'exit' or Ctrl+C to leave.")
        ]), style=cli_style)

    while True:
        action: str = 'continue'
        try:
            if active_mode == 'text':
                action, session_state = await text_mode_one_turn(
                    prompt_session, session_state
                )
                # Update the global reference after session state changes
                if session_state is not None and not isinstance(session_state, str):
                    set_current_session_state(session_state)
            elif active_mode == 'voice':
                # Disable TTS in text mode when in voice mode
                from .cli_args import TEXT_MODE_TTS_ENABLED
                TEXT_MODE_TTS_ENABLED = False 
                
                if not voice_handler.recorder_instance:
                    print_formatted_text(FormattedText([
                        ('class:error', "Error: Voice recorder not active! Switching to text mode.")
                    ]), style=cli_style)
                    active_mode = 'text'
                    action = 'switch_to_text' 
                else:
                    action, session_state = await voice_handler.handle_one_turn(session_state)
                    # Update the global reference after session state changes
                    if session_state is not None and not isinstance(session_state, str):
                        set_current_session_state(session_state)
        
        except asyncio.CancelledError: 
            log_warning("[Orchestrator] Turn was CANCELLED (asyncio.CancelledError).")
            # Potentially add cleanup for STT recorder if active_mode was voice
            if active_mode == 'voice':
                voice_handler.shutdown()
                active_mode = 'text'  # Fallback to text mode
            action = 'continue'  # Attempt to continue, might loop into text mode prompt
        except KeyboardInterrupt: 
            log_debug("[Orchestrator] CAUGHT KeyboardInterrupt during turn.")
            print_formatted_text(FormattedText([
                ('class:warning', "\n⚠️ Operation cancelled by user.")
            ]), style=cli_style)
            
            if active_mode == 'voice':
                log_router_activity("[Orchestrator] KeyboardInterrupt in voice mode, attempting to switch to text mode immediately.")
                voice_handler.shutdown()
                active_mode = 'text'  # Force mode change
                from .cli_args import TEXT_MODE_TTS_ENABLED
                TEXT_MODE_TTS_ENABLED = False  # Disable TTS when falling back
                action = 'show_text_prompt_after_interrupt'  # New distinct action
            else:
                log_router_activity("[Orchestrator] KeyboardInterrupt in text mode, returning to prompt.")
                action = 'continue'  # Continue in text mode (effectively new prompt)
        except Exception as e_orchestrator_loop:
            log_error(f"[Orchestrator] Unexpected error in main loop: {e_orchestrator_loop}", exception_info=str(e_orchestrator_loop))
            print_formatted_text(FormattedText([
                ('class:error', f"\nUnexpected error in main loop: {e_orchestrator_loop}. Returning to prompt.")
            ]), style=cli_style)
            
            if active_mode == 'voice':  # Attempt cleanup if error happened in voice mode
                voice_handler.shutdown()
                active_mode = 'text'  # Fallback to text mode
            action = 'continue'

        # --- Handle actions from turn handlers (or from KI override) ---
        if action == 'exit':
            print_formatted_text(FormattedText([("bold", "\nExiting ARIS...")]), style=cli_style)
            log_router_activity("Chat session ended by user command.")
            break
        elif action == 'new_conversation':
            print_formatted_text(FormattedText([("bold", "✨ Starting a new conversation.")]), style=cli_style)
            log_router_activity("User started a new conversation session.")
            # Update the global reference for the new session
            if session_state is not None and not isinstance(session_state, str):
                set_current_session_state(session_state)
        elif action == 'switch_to_voice':
            if active_mode == 'text':
                if voice_handler.initialize():
                    active_mode = 'voice'
                    from .cli_args import TEXT_MODE_TTS_ENABLED
                    TEXT_MODE_TTS_ENABLED = False 
                    log_router_activity("User switched to voice mode.")
                    
                    profile_name = "default"
                    if hasattr(session_state, 'active_profile') and session_state.active_profile:
                        profile_name = session_state.active_profile.get("profile_name", "default")
                        
                    print_formatted_text(FormattedText([
                        ("bold fg:magenta", f"🎙️ Voice mode enabled with profile '{profile_name}'."), 
                        ("", " Say '/voice off' to switch. Ctrl+C to exit.")
                    ]), style=cli_style)
                else:
                    print_formatted_text(FormattedText([
                        ('class:error', f"Error initializing voice mode. Staying in text mode.")
                    ]), style=cli_style)
                    log_error(f"Error initializing voice mode. Staying in text mode.")
            else:
                 print_formatted_text(FormattedText([
                     ('class:error', "Cannot switch to voice mode due to missing dependencies or API key. Staying in text mode.")
                 ]), style=cli_style)
        elif action == 'switch_to_text':
            if active_mode == 'voice':
                voice_handler.shutdown()
                active_mode = 'text'
                log_router_activity("User switched to text mode.")
                
                status_msg = "⌨️ Text mode enabled." 
                if TEXT_MODE_TTS_ENABLED:
                    status_msg += " TTS is ON ('/speak off' to disable)."
                else:
                    status_msg += " Type '/voice on' to switch or '/speak on' for TTS output."
                status_msg += " 'exit' or Ctrl+C to leave."
                
                print_formatted_text(FormattedText([
                    ("bold fg:green", status_msg)
                ]), style=cli_style)
        elif action == 'show_text_prompt_after_interrupt':
            # This state is specifically after a KI in voice mode.
            # Ensure text mode UI is clearly re-established.
            active_mode = 'text'  # Re-affirm, though should already be set
            # Ensure any active spinner is stopped from the interrupted turn
            print_formatted_text(FormattedText([
                ("bold fg:green", "\n⌨️ Switched to text mode. Type 'exit' or Ctrl+C to leave.")
            ]), style=cli_style)
            # Loop will continue and text_mode_one_turn will be called to show prompt

    # --- Cleanup ---
    voice_handler.shutdown()
    
    # Clean up interrupt handler
    interrupt_handler.shutdown()
    
    # Clean up context file manager
    from .context_file_manager import context_file_manager
    context_file_manager.cleanup_old_files()
    
    # Restore original directory if workspace was used
    workspace_manager.restore_original_directory()
    
    print_formatted_text("-----------------------------------------------------", style=cli_style)


async def _start_profile_mcp_server():
    """Start the Profile MCP Server."""
    try:
        from .profile_mcp_server import ProfileMCPServer
        
        # Create an event to signal when the server is ready
        server_ready_event = threading.Event()
        server_error_msg = [None]  # Use a list to store error message by reference
        
        # Define a function to run the server and set the event when ready
        def run_server_with_signal(server, ready_event, error_msg):
            try:
                # Run the server - this method should handle port collision and other errors
                server.run_server_blocking()
            except Exception as e:
                error_msg[0] = str(e)
            finally:
                # Signal that we're done trying to start the server
                ready_event.set()
        
        # Start the MCP server in a separate thread
        mcp_server = ProfileMCPServer(port=PARSED_ARGS.profile_mcp_port)
        server_thread = threading.Thread(
            target=run_server_with_signal, 
            args=(mcp_server, server_ready_event, server_error_msg),
            daemon=True
        )
        server_thread.start()
        
        # Wait for up to 5 seconds for the server to start
        server_ready = server_ready_event.wait(5.0)
        
        if server_error_msg[0]:
            # Server encountered an error
            log_error(f"Failed to start Profile MCP Server: {server_error_msg[0]}")
            if getattr(PARSED_ARGS, 'verbose', False):
                print(f"Warning: Failed to start Profile MCP Server: {server_error_msg[0]}")
        else:
            # Server started successfully
            log_router_activity(f"Started Profile MCP Server on port {mcp_server.port}")
            
            # Mark server as started in session state
            from .session_state import get_current_session_state
            session_state = get_current_session_state()
            if session_state:
                session_state.profile_mcp_server_started = True
            
            # Only print info to console if verbose mode is enabled
            if getattr(PARSED_ARGS, 'verbose', False):
                print(f"Profile MCP Server started on http://localhost:{mcp_server.port}")
    except Exception as e:
        log_error(f"Failed to start Profile MCP Server: {e}")
        if getattr(PARSED_ARGS, 'verbose', False):
            print(f"Warning: Failed to start Profile MCP Server: {e}")


async def _start_workflow_mcp_server():
    """Start the Workflow MCP Server."""
    try:
        from .workflow_mcp_server import WorkflowMCPServer
        
        # Create an event to signal when the server is ready
        workflow_server_ready_event = threading.Event()
        workflow_server_error_msg = [None]  # Use a list to store error message by reference
        
        # Define a function to run the server and set the event when ready
        def run_workflow_server_with_signal(server, ready_event, error_msg):
            try:
                import uvicorn
                uvicorn.run(
                    server.starlette_app,
                    host=server.host,
                    port=server.port,
                    log_level="warning"
                )
            except Exception as e:
                error_msg[0] = str(e)
            finally:
                # Signal that we're done trying to start the server
                ready_event.set()
        
        # Start the Workflow MCP server in a separate thread
        workflow_mcp_server = WorkflowMCPServer(port=8095)
        workflow_server_thread = threading.Thread(
            target=run_workflow_server_with_signal, 
            args=(workflow_mcp_server, workflow_server_ready_event, workflow_server_error_msg),
            daemon=True
        )
        workflow_server_thread.start()
        
        # Wait for up to 3 seconds for the server to start
        workflow_server_ready = workflow_server_ready_event.wait(3.0)
        
        if workflow_server_error_msg[0]:
            # Server encountered an error
            log_error(f"Failed to start Workflow MCP Server: {workflow_server_error_msg[0]}")
            if getattr(PARSED_ARGS, 'verbose', False):
                print(f"Warning: Failed to start Workflow MCP Server: {workflow_server_error_msg[0]}")
        else:
            # Server started successfully
            log_router_activity(f"Started Workflow MCP Server on port {workflow_mcp_server.port}")
            
            # Mark server as started in session state
            from .session_state import get_current_session_state
            session_state = get_current_session_state()
            if session_state:
                session_state.workflow_mcp_server_started = True
            
            # Only print info to console if verbose mode is enabled
            if getattr(PARSED_ARGS, 'verbose', False):
                print(f"Workflow MCP Server started on http://localhost:{workflow_mcp_server.port}")
    except Exception as e:
        log_error(f"Failed to start Workflow MCP Server: {e}")
        if getattr(PARSED_ARGS, 'verbose', False):
            print(f"Warning: Failed to start Workflow MCP Server: {e}")


# The main execution block
if __name__ == "__main__":
    # Parse arguments and configure logging
    initialize_environment()
    
    # Now, perform full application component initialization
    asyncio.run(fully_initialize_app_components())
    
    try:
        asyncio.run(run_cli_orchestrator())
    except KeyboardInterrupt:
        print_formatted_text(FormattedText([
            ("bold", "\nExiting ARIS via Ctrl+C...")
        ]), style=cli_style)
        log_router_activity("Chat session ended by KeyboardInterrupt.")
    finally:
        pass