"""
Interaction handling for ARIS.
"""
import sys
import json
import asyncio
import itertools
from typing import Tuple, Optional, List, Dict, Any, Union

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from .logging_utils import (
    log_router_activity, 
    log_error, 
    log_warning, 
    log_debug,
    log_user_command_raw_text
)
from .session_state import SessionState, get_current_session_state, set_current_session_state
from .tts_handler import tts_speak, summarize_for_voice
from .profile_handler import process_special_commands
from .interrupt_handler import get_interrupt_handler, InterruptContext

# Constants for spinner animation
SPINNER_CHARS = ['|', '/', '-', '\\']
SPINNER_DELAY = 0.15

# Define a simple style for prompt_toolkit outputs
try:
    from .cli import cli_style
except ImportError:
    from prompt_toolkit.styles import Style
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

# Define custom exception for turn cancellation
class TurnCancelledError(Exception):
    """Exception raised when a turn is cancelled."""
    pass

async def spinner_task(stop_event: asyncio.Event, thinking_message_prefix: str):
    """
    Displays a spinner animation while waiting for a response.
    
    Args:
        stop_event: Event to signal when to stop the spinner
        thinking_message_prefix: Prefix to show before the spinner character
    """
    for char in itertools.cycle(SPINNER_CHARS):
        if stop_event.is_set(): 
            break
        sys.stdout.write(f"\r{thinking_message_prefix}{char} ")
        sys.stdout.flush()
        await asyncio.sleep(SPINNER_DELAY)
    sys.stdout.write('\r' + ' ' * (len(thinking_message_prefix) + 2) + '\r')
    sys.stdout.flush()

def start_spinner(prefix: str):
    """
    Start a spinner animation.
    
    Args:
        prefix: Prefix to show before the spinner character
        
    Returns:
        Tuple of (event, task) for the spinner
    """
    ev = asyncio.Event()
    task = asyncio.create_task(spinner_task(ev, prefix))
    return ev, task

async def stop_spinner(ev: asyncio.Event, task: asyncio.Task):
    """
    Stop a spinner animation.
    
    Args:
        ev: Event to signal when to stop the spinner
        task: Task for the spinner
    """
    if not ev.is_set(): 
        ev.set()
    try: 
        await task  # Ensure task completes
    except asyncio.CancelledError: 
        pass

async def handle_route_chunks(
    user_msg: str, 
    session_state: Union[SessionState, str], 
    thinking_prefix: str
) -> Tuple[str, str, bool]:
    """
    Processes chunks from route() and prints assistant messages.
    
    Args:
        user_msg: The user's message to process
        session_state: The current session state or session ID string
        thinking_prefix: Prefix to show during "thinking" spinner
        
    Returns:
        Tuple of (session_id, combined_assistant_text, spoke_anything)
    """
    from .cli_args import TEXT_MODE_TTS_ENABLED
    
    # Set context to Claude thinking
    interrupt_handler = get_interrupt_handler()
    interrupt_handler.set_context(InterruptContext.CLAUDE_THINKING)
    
    stop_spinner_event, spinner = start_spinner(thinking_prefix)
    assistant_text_parts = []
    assistant_spoke = False

    try:
        # To store new session_id from events
        result_session_id = None
        
        # Handle both SessionState and string cases (for tests)
        if session_state is None:
            # For None session state (especially in tests)
            session_id = None
            system_prompt = None
            tool_preferences = None
            reference_file_path = None
            is_first_message = False
        elif isinstance(session_state, str):
            # For string session ID (in tests)
            session_id = session_state
            system_prompt = None
            tool_preferences = None
            reference_file_path = None
            is_first_message = False
        else:
            # Normal operation with SessionState object
            session_id = session_state.session_id
            system_prompt = session_state.get_system_prompt()
            tool_preferences = session_state.get_tool_preferences()
            reference_file_path = session_state.reference_file_path
            is_first_message = session_state.is_first_message()
        
        from .orchestrator import route
        try:
            async for chunk_str in route(
                user_msg,
                session_id,
                tool_preferences=tool_preferences,
                system_prompt=system_prompt,
                reference_file_path=reference_file_path,
                is_first_message=is_first_message
            ):
                try:
                    event_data = json.loads(chunk_str)
                    session_id_from_event = event_data.get("session_id")
                    if session_id_from_event:
                        # Always store the latest session ID from events for return value
                        result_session_id = session_id_from_event
                        if isinstance(session_state, str):
                            # For test compatibility
                            session_id = session_id_from_event
                        else:
                            # Normal operation
                            session_state.session_id = session_id_from_event
                            session_id = session_state.session_id

                    text_to_display = None
                    
                    # Handle system init message for MCP server status feedback
                    if event_data.get("type") == "system" and event_data.get("subtype") == "init":
                        mcp_servers = event_data.get("mcp_servers", [])
                        if mcp_servers:
                            failed_servers = [s for s in mcp_servers if s.get("status") == "failed"]
                            success_servers = [s for s in mcp_servers if s.get("status") not in ["failed", "error"]]
                            
                            if failed_servers or success_servers:
                                await stop_spinner(stop_spinner_event, spinner)
                                
                                if success_servers:
                                    server_names = [s.get("name", "unknown") for s in success_servers]
                                    print_formatted_text(FormattedText([
                                        ("class:prompt.assistant.prefix", "🔌 MCP > "),
                                        ("fg:green", f"Connected to {len(success_servers)} MCP server(s): {', '.join(server_names)}")
                                    ]), style=cli_style)
                                    
                                if failed_servers:
                                    server_names = [s.get("name", "unknown") for s in failed_servers]
                                    print_formatted_text(FormattedText([
                                        ("class:prompt.assistant.prefix", "🔌 MCP > "),
                                        ("fg:red", f"Failed to connect to {len(failed_servers)} MCP server(s): {', '.join(server_names)}")
                                    ]), style=cli_style)
                                    print_formatted_text(FormattedText([
                                        ("class:prompt.assistant.prefix", "💡 Tip > "),
                                        ("fg:yellow", "Check server installation and configuration. Some tools may not be available.")
                                    ]), style=cli_style)
                                
                                stop_spinner_event, spinner = start_spinner(thinking_prefix)
                    
                    elif event_data.get("type") == "assistant":
                        message_content = event_data.get("message", {}).get("content", [])
                        for content_item in message_content:
                            if content_item.get("type") == "text":
                                text_piece = content_item.get("text", "")
                                if text_piece:
                                    text_to_display = text_piece
                                    assistant_text_parts.append(text_piece)
                                    assistant_spoke = True 
                    elif event_data.get("type") == "result" and event_data.get("subtype") == "success" and not assistant_spoke:
                        result_text = event_data.get("result")
                        if isinstance(result_text, str):
                            text_to_display = result_text
                            assistant_text_parts.append(result_text)
                            assistant_spoke = True
                    
                    if text_to_display is not None:
                        await stop_spinner(stop_spinner_event, spinner) 
                        current_prefix = thinking_prefix.split("<")[0] + "< "
                        print_formatted_text(FormattedText([
                            ("class:prompt.assistant.prefix", current_prefix),
                            ("class:prompt.assistant.text", text_to_display.strip())
                        ]), style=cli_style)
                        
                        if TEXT_MODE_TTS_ENABLED:
                            log_debug(f"[TTS] Individual Piece Triggered for text mode. Text: '{text_to_display[:30]}...'")
                            summary = await summarize_for_voice(text_to_display) 
                            asyncio.create_task(tts_speak(summary))
                        
                        stop_spinner_event, spinner = start_spinner(thinking_prefix)

                    # Check if this is a reference file read confirmation message
                    if (is_first_message and reference_file_path and
                        text_to_display is not None and
                        "read" in text_to_display.lower() and 
                        "reference file" in text_to_display.lower()):
                        if not isinstance(session_state, str):
                            session_state.has_read_reference_file = True
                            log_debug(f"Detected reference file read confirmation: {text_to_display[:50]}...")

                except json.JSONDecodeError: 
                    log_warning(f"Non-JSON chunk from Claude CLI: {chunk_str.strip()}")
                    # Let other exceptions, including KeyboardInterrupt, propagate up
        except KeyboardInterrupt:
            # Handle CTRL+C during Claude CLI execution
            await stop_spinner(stop_spinner_event, spinner)
            log_router_activity("KeyboardInterrupt caught during Claude CLI execution - terminating process")
            
            # Terminate the Claude CLI process
            from .orchestrator import get_claude_cli_executor
            executor = get_claude_cli_executor()
            if executor:
                await executor.terminate_current_process()
            
            print_formatted_text(FormattedText([
                ('class:warning', "\n⚠️ Claude CLI execution cancelled by user (CTRL+C)")
            ]), style=cli_style)
            
            # Raise a custom exception to indicate cancellation without exiting
            raise TurnCancelledError("Turn cancelled by user interrupt")
        
        except Exception as route_iteration_err:
            # Handle other errors during route iteration
            await stop_spinner(stop_spinner_event, spinner)
            log_error(f"Error during route iteration: {route_iteration_err}", exception_info=str(route_iteration_err))
            raise  # Re-raise to be handled by outer exception handler

    except TurnCancelledError:
        # Handle turn cancellation (CTRL+C during Claude execution)
        log_router_activity("Turn was cancelled by user interrupt")
        # Return what we have so far
        concatenated_text = "".join(assistant_text_parts)
        if result_session_id:
            return result_session_id, concatenated_text, assistant_spoke
        elif isinstance(session_state, str):
            return session_state, concatenated_text, assistant_spoke
        else:
            return session_state.session_id if session_state else None, concatenated_text, assistant_spoke
    except Exception as route_err:  # Catch other errors from route() or chunk processing
        if not stop_spinner_event.is_set(): 
            await stop_spinner(stop_spinner_event, spinner)
        error_message = f"Error during Claude processing: {route_err}"
        print_formatted_text(FormattedText([
            ('class:error', f"🤖 ARIS < {error_message}")
        ]), style=cli_style, file=sys.stderr)
        log_error(f"Error from route() for '{user_msg}': {route_err}", exception_info=str(route_err))
    finally:
        if 'stop_spinner_event' in locals() and stop_spinner_event and not stop_spinner_event.is_set():
            await stop_spinner(stop_spinner_event, spinner)
        
        # Reset context back to idle
        interrupt_handler.set_context(InterruptContext.IDLE)
    
    concatenated_text = "".join(assistant_text_parts)
    
    # Return the session ID from the event if we received one
    if result_session_id:
        return result_session_id, concatenated_text, assistant_spoke
    
    # Fallback to the session state's ID
    if session_state is None:
        return None, concatenated_text, assistant_spoke
    elif isinstance(session_state, str):
        return session_state, concatenated_text, assistant_spoke
    else:
        return session_state.session_id, concatenated_text, assistant_spoke

async def text_mode_one_turn(prompt_session: PromptSession, session_state: SessionState) -> Tuple[str, SessionState]:
    """
    Process one turn in text mode.
    
    Args:
        prompt_session: The prompt_toolkit session for input
        session_state: The current session state
        
    Returns:
        Tuple of (action, updated_session_state)
    """
    from .cli_args import TEXT_MODE_TTS_ENABLED
    
    user_msg_input = ""
    try:
        # Make sure we have a clean line for input - use multiple newlines
        # to ensure separation from any previous output (like YouTube server messages)
        print("\n")
        with patch_stdout():
            user_msg_input = await prompt_session.prompt_async(FormattedText([('class:prompt.user', "🧑 User > ")]))
        user_msg_input = user_msg_input.strip()
    except (EOFError, KeyboardInterrupt):  # Ctrl+C at prompt means exit CLI
        return 'exit', session_state

    # Check for special commands
    if user_msg_input.startswith("@"):
        if process_special_commands(user_msg_input, session_state):
            return 'continue', session_state

    # Check for voice mode commands
    if user_msg_input.lower() == "/voice on": 
        return 'switch_to_voice', session_state
    if user_msg_input.lower() == "/voice off":
        print_formatted_text(FormattedText([
            ('class:prompt.assistant.text', "Already in text mode.")
        ]), style=cli_style)
        return 'continue', session_state
    if user_msg_input.lower() == "/speak on":
        from .tts_handler import _ensure_voice_dependencies, _init_openai_clients_for_tts
        if not _ensure_voice_dependencies() or not _init_openai_clients_for_tts():
            print_formatted_text(FormattedText([
                ('class:warning', "TTS could not be enabled (missing dependencies or API key).")
            ]), style=cli_style)
        else:
            TEXT_MODE_TTS_ENABLED = True
            print_formatted_text(FormattedText([
                ('bold fg:magenta', "🔊 Text mode TTS enabled.")
            ]), style=cli_style)
        return 'continue', session_state
    if user_msg_input.lower() == "/speak off":
        TEXT_MODE_TTS_ENABLED = False
        print_formatted_text(FormattedText([
            ('bold fg:gray', "🔇 Text mode TTS disabled.")
        ]), style=cli_style)
        return 'continue', session_state
    if user_msg_input.lower() in {"exit", "quit"}: 
        return 'exit', session_state
    if user_msg_input.lower() == "new": 
        # For test compatibility with expected None
        if isinstance(session_state, str):
            return 'new_conversation', None
        else:
            session_state = SessionState()  # Create a new session
            return 'new_conversation', session_state
    if not user_msg_input: 
        return 'continue', session_state

    log_user_command_raw_text(user_msg_input)
    
    # Process the message through the assistant
    profile_name = "default"
    if not isinstance(session_state, str) and hasattr(session_state, 'active_profile') and session_state.active_profile:
        profile_name = session_state.active_profile.get("profile_name", "default")
    
    try:
        new_session_id, assistant_text, _ = await handle_route_chunks(
            user_msg_input, 
            session_state, 
            f"🤖 ARIS [{profile_name}] < Thinking... "
        )
        
        # For test compatibility
        if isinstance(session_state, str):
            return 'continue', new_session_id
            
        # Update session ID if we got a new one from the event
        if new_session_id and not isinstance(session_state, str) and session_state is not None:
            if new_session_id != session_state.session_id:
                session_state.session_id = new_session_id
        
        return 'continue', session_state
    except TurnCancelledError:
        # Turn was cancelled by CTRL+C, return to prompt
        log_debug("Turn cancelled in text_mode_one_turn, returning to prompt")
        return 'continue', session_state

def print_welcome_message(profile_name="default"):
    """
    Print a welcome message to the user.
    
    Args:
        profile_name: The name of the active profile
    """
    print_formatted_text(FormattedText([
        ("bold", f"\nWelcome to {profile_name} Chat CLI (v0)"), 
        ("", "\nPowered by Claude Code and Aigentive MCP."),
    ]), style=cli_style)
    
    print_formatted_text("-----------------------------------------------------", style=cli_style)