"""Tests for the interaction_handler module in aris"""

import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock

from prompt_toolkit.history import FileHistory

from aris.interaction_handler import (
    TurnCancelledError,
    spinner_task,
    start_spinner,
    stop_spinner,
    handle_route_chunks,
    text_mode_one_turn,
    print_welcome_message
)
from aris.session_state import SessionState

@pytest.fixture
def mock_stop_event():
    """Create a mock stop event for testing spinner functions."""
    return asyncio.Event()

@pytest.fixture
def mock_prompt_session():
    """Create a mock prompt session for testing text mode functions."""
    prompt_session = MagicMock()
    prompt_session.prompt_async = AsyncMock()
    return prompt_session

@pytest.mark.asyncio
async def test_spinner_task(mock_stop_event, monkeypatch):
    """Test the spinner_task function."""
    # Mock sys.stdout.write and sys.stdout.flush
    mock_write = MagicMock()
    mock_flush = MagicMock()
    monkeypatch.setattr("sys.stdout.write", mock_write)
    monkeypatch.setattr("sys.stdout.flush", mock_flush)
    
    # Start the spinner task with a short timeout
    task = asyncio.create_task(spinner_task(mock_stop_event, "Thinking..."))
    
    # Let it run for a short time
    await asyncio.sleep(0.2)
    
    # Set the stop event to stop the spinner
    mock_stop_event.set()
    
    # Wait for the task to complete
    await task
    
    # Verify that stdout.write was called with the expected messages
    assert mock_write.called
    assert mock_flush.called
    
    # The last call should be to clear the spinner line
    mock_write.assert_called_with('\r' + ' ' * (len("Thinking...") + 2) + '\r')

@pytest.mark.asyncio
async def test_start_and_stop_spinner():
    """Test the start_spinner and stop_spinner functions."""
    ev, task = start_spinner("Thinking...")
    
    # Verify that the event is not set and the task is running
    assert not ev.is_set()
    assert not task.done()
    
    # Stop the spinner
    await stop_spinner(ev, task)
    
    # Verify that the event is set and the task is done
    assert ev.is_set()
    assert task.done()

@pytest.mark.asyncio
@patch("aris.cli_args.TEXT_MODE_TTS_ENABLED", False)
@patch("aris.tts_handler.tts_speak")
@patch("aris.tts_handler.summarize_for_voice")
@patch("aris.interaction_handler.start_spinner")
@patch("aris.interaction_handler.stop_spinner")
@patch("aris.interaction_handler.print_formatted_text")
@patch("aris.orchestrator.route")
async def test_handle_route_chunks_with_session_state(
    mock_route, mock_print, mock_stop_spinner, mock_start_spinner,
    mock_summarize, mock_tts_speak
):
    """Test handle_route_chunks with a SessionState object."""
    # Set up mock spinner
    mock_ev = MagicMock()
    mock_ev.is_set.return_value = False  # Ensure stop_spinner is called in finally
    mock_task = MagicMock()
    mock_start_spinner.return_value = (mock_ev, mock_task)
    
    # Set up mock route response - async generator of JSON chunks
    async def mock_route_gen(*args, **kwargs):
        # Yield assistant message
        yield json.dumps({
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Hello response"}]
            }
        })
    
    mock_route.return_value = mock_route_gen()
    
    # Create a session state
    session_state = SessionState(session_id="test123")
    
    # Call handle_route_chunks
    session_id, text, spoke = await handle_route_chunks("Hello", session_state, "Thinking...")
    
    # Verify that the function used the session state correctly
    assert session_id == "test123"
    assert text == "Hello response"
    assert spoke is True
    
    # Verify that start_spinner, stop_spinner, and print_formatted_text were called
    assert mock_start_spinner.call_count == 2  # Initial call and restart after displaying text
    assert mock_stop_spinner.call_count == 2  # Once when displaying text, once in finally
    mock_print.assert_called_once()  # For displaying the assistant message

@pytest.mark.asyncio
@patch("aris.cli_args.TEXT_MODE_TTS_ENABLED", False)
@patch("aris.interaction_handler.start_spinner")
@patch("aris.interaction_handler.stop_spinner")
@patch("aris.interaction_handler.print_formatted_text")
@patch("aris.orchestrator.route")
async def test_handle_route_chunks_with_session_id_string(
    mock_route, mock_print, mock_stop_spinner, mock_start_spinner
):
    """Test handle_route_chunks with a session ID string."""
    # Set up mock spinner
    mock_ev = MagicMock()
    mock_ev.is_set.return_value = False  # Ensure stop_spinner is called in finally
    mock_task = MagicMock()
    mock_start_spinner.return_value = (mock_ev, mock_task)
    
    # Set up mock route response - async generator of JSON chunks
    async def mock_route_gen(*args, **kwargs):
        # Empty async generator for this test
        if False:  # This condition will never be true
            yield
    
    mock_route.return_value = mock_route_gen()
    
    # Call handle_route_chunks with a session ID string
    session_id, text, spoke = await handle_route_chunks("Hello", "test123", "Thinking...")
    
    # Verify that the function used the session ID correctly
    assert session_id == "test123"
    assert text == ""
    assert spoke is False
    
    # Verify that start_spinner was called but stop_spinner only in finally
    mock_start_spinner.assert_called_once_with("Thinking...")
    mock_stop_spinner.assert_called_once_with(mock_ev, mock_task)  # Only called in finally block

@pytest.mark.asyncio
@patch("aris.cli_args.TEXT_MODE_TTS_ENABLED", False)
@patch("aris.interaction_handler.start_spinner")
@patch("aris.interaction_handler.stop_spinner")
@patch("aris.interaction_handler.print_formatted_text")
@patch("aris.orchestrator.route")
async def test_handle_route_chunks_with_assistant_message(
    mock_route, mock_print, mock_stop_spinner, mock_start_spinner
):
    """Test handle_route_chunks with an assistant message."""
    # Set up mock spinner
    mock_ev = MagicMock()
    mock_ev.is_set.return_value = False  # Ensure stop_spinner is called in finally
    mock_task = MagicMock()
    mock_start_spinner.return_value = (mock_ev, mock_task)
    
    # Set up mock route response
    async def mock_route_gen(*args, **kwargs):
        yield '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello, world!"}]}, "session_id": "new123"}'
    
    mock_route.return_value = mock_route_gen()
    
    # Call handle_route_chunks
    session_id, text, spoke = await handle_route_chunks("Hello", "test123", "Thinking...")
    
    # Verify that the function processed the assistant message correctly
    assert session_id == "new123"  # Updated from the event
    assert text == "Hello, world!"
    assert spoke is True
    
    # Verify that start_spinner, stop_spinner, and print_formatted_text were called
    assert mock_start_spinner.call_count == 2  # Initial call and restart after displaying text
    assert mock_stop_spinner.call_count == 2  # Once when displaying text, once in finally
    mock_print.assert_called_once()  # For displaying the assistant message

@pytest.mark.asyncio
@patch("aris.interaction_handler.handle_route_chunks")
async def test_text_mode_one_turn_normal_input(
    mock_handle_route_chunks, mock_prompt_session
):
    """Test text_mode_one_turn with normal input."""
    # Configure mock prompt session
    mock_prompt_session.prompt_async.return_value = "Hello, Claude"
    
    # Configure mock handle_route_chunks
    mock_handle_route_chunks.return_value = ("new123", "Hello, I'm Claude!", True)
    
    # Create a session state
    session_state = SessionState(session_id="test123")
    
    # Call text_mode_one_turn
    action, updated_session_state = await text_mode_one_turn(mock_prompt_session, session_state)
    
    # Verify that the function processed the input correctly
    assert action == "continue"
    assert updated_session_state.session_id == "new123"  # Updated from handle_route_chunks
    
    # Verify that prompt_session.prompt_async and handle_route_chunks were called
    mock_prompt_session.prompt_async.assert_called_once()
    mock_handle_route_chunks.assert_called_once_with("Hello, Claude", session_state, "🤖 ARIS [default] < Thinking... ")

@pytest.mark.asyncio
@patch("aris.interaction_handler.process_special_commands")
@patch("aris.interaction_handler.handle_route_chunks")
async def test_text_mode_one_turn_special_command(
    mock_handle_route_chunks, mock_process_special_commands, mock_prompt_session
):
    """Test text_mode_one_turn with a special command."""
    # Configure mock prompt session
    mock_prompt_session.prompt_async.return_value = "@profile list"
    
    # Configure mock process_special_commands
    mock_process_special_commands.return_value = True  # This is a special command
    
    # Create a session state
    session_state = SessionState(session_id="test123")
    
    # Call text_mode_one_turn
    action, updated_session_state = await text_mode_one_turn(mock_prompt_session, session_state)
    
    # Verify that the function processed the special command correctly
    assert action == "continue"
    assert updated_session_state is session_state  # Same session state
    
    # Verify that prompt_session.prompt_async and process_special_commands were called
    mock_prompt_session.prompt_async.assert_called_once()
    mock_process_special_commands.assert_called_once_with("@profile list", session_state)
    
    # Verify that handle_route_chunks was not called
    mock_handle_route_chunks.assert_not_called()

@pytest.mark.asyncio
@patch("aris.interaction_handler.print_formatted_text")
async def test_text_mode_one_turn_exit_command(mock_print_formatted_text, mock_prompt_session):
    """Test text_mode_one_turn with the 'exit' command."""
    # Configure mock prompt session
    mock_prompt_session.prompt_async.return_value = "exit"
    
    # Create a session state
    session_state = SessionState(session_id="test123")
    
    # Call text_mode_one_turn
    action, updated_session_state = await text_mode_one_turn(mock_prompt_session, session_state)
    
    # Verify that the function processed the exit command correctly
    assert action == "exit"
    assert updated_session_state is session_state  # Same session state

@pytest.mark.asyncio
@patch("aris.interaction_handler.print_formatted_text")
async def test_text_mode_one_turn_new_command(mock_print_formatted_text, mock_prompt_session):
    """Test text_mode_one_turn with the 'new' command."""
    # Configure mock prompt session
    mock_prompt_session.prompt_async.return_value = "new"
    
    # Create a session state
    session_state = SessionState(session_id="test123")
    
    # Call text_mode_one_turn
    action, updated_session_state = await text_mode_one_turn(mock_prompt_session, session_state)
    
    # Verify that the function processed the new command correctly
    assert action == "new_conversation"
    assert updated_session_state.session_id is None  # New session state

@pytest.mark.asyncio
@patch("aris.interaction_handler.print_formatted_text")
async def test_text_mode_one_turn_keyboard_interrupt(mock_print_formatted_text, mock_prompt_session):
    """Test text_mode_one_turn with a KeyboardInterrupt."""
    # Configure mock prompt session to raise KeyboardInterrupt
    mock_prompt_session.prompt_async.side_effect = KeyboardInterrupt()
    
    # Create a session state
    session_state = SessionState(session_id="test123")
    
    # Call text_mode_one_turn
    action, updated_session_state = await text_mode_one_turn(mock_prompt_session, session_state)
    
    # Verify that the function processed the KeyboardInterrupt correctly
    assert action == "exit"
    assert updated_session_state is session_state  # Same session state

@patch("aris.interaction_handler.print_formatted_text")
def test_print_welcome_message(mock_print_formatted_text):
    """Test print_welcome_message."""
    # Call print_welcome_message with default profile name
    print_welcome_message()
    
    # Verify that print_formatted_text was called twice
    assert mock_print_formatted_text.call_count == 2
    
    # Call print_welcome_message with custom profile name
    print_welcome_message("test_profile")
    
    # Verify that print_formatted_text was called twice more
    assert mock_print_formatted_text.call_count == 4