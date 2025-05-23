"""Tests for the voice_handler module in aris"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from aris.voice_handler import VoiceHandler
from aris.session_state import SessionState

@pytest.fixture
def voice_handler():
    """Create a VoiceHandler instance for testing."""
    return VoiceHandler(trigger_words=["claude", "hey"])

@pytest.fixture
def mock_session_state():
    """Create a mock session state for testing."""
    session_state = SessionState(session_id="test123")
    session_state.active_profile = {"profile_name": "test_profile"}
    return session_state

@patch("aris.voice_handler._ensure_voice_dependencies")
@patch("aris.voice_handler._init_openai_clients_for_tts")
def test_initialize_success(mock_init_openai, mock_ensure_voice_deps, voice_handler):
    """Test successful initialization of VoiceHandler."""
    # Configure mocks
    mock_ensure_voice_deps.return_value = True
    mock_init_openai.return_value = True
    
    # Mock the Recorder class
    recorder_mock = MagicMock()
    recorder_instance_mock = MagicMock()
    recorder_mock.return_value = recorder_instance_mock
    
    # Set the Recorder in tts_handler module
    import aris.tts_handler as tts_module
    original_recorder = getattr(tts_module, 'Recorder', None)
    tts_module.Recorder = recorder_mock
    
    try:
        # Call initialize
        result = voice_handler.initialize()
        
        # Verify that initialization was successful
        assert result is True
        assert voice_handler.recorder_instance == recorder_instance_mock
        
        # Verify that the Recorder was instantiated with the expected arguments
        recorder_mock.assert_called_once_with(model="small.en")
    finally:
        # Restore original Recorder
        if original_recorder is not None:
            tts_module.Recorder = original_recorder
        else:
            delattr(tts_module, 'Recorder')

@patch("aris.voice_handler._ensure_voice_dependencies")
@patch("aris.voice_handler._init_openai_clients_for_tts")
def test_initialize_voice_deps_failure(mock_init_openai, mock_ensure_voice_deps, voice_handler):
    """Test VoiceHandler initialization when voice dependencies are missing."""
    # Configure mocks
    mock_ensure_voice_deps.return_value = False
    mock_init_openai.return_value = True
    
    # Call initialize
    result = voice_handler.initialize()
    
    # Verify that initialization failed
    assert result is False
    assert voice_handler.recorder_instance is None

@patch("aris.voice_handler._ensure_voice_dependencies")
@patch("aris.voice_handler._init_openai_clients_for_tts")
def test_initialize_openai_failure(mock_init_openai, mock_ensure_voice_deps, voice_handler):
    """Test VoiceHandler initialization when OpenAI client initialization fails."""
    # Configure mocks
    mock_ensure_voice_deps.return_value = True
    mock_init_openai.return_value = False
    
    # Call initialize
    result = voice_handler.initialize()
    
    # Verify that initialization failed
    assert result is False
    assert voice_handler.recorder_instance is None

def test_shutdown(voice_handler):
    """Test VoiceHandler shutdown."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    voice_handler.recorder_instance = mock_recorder
    
    # Call shutdown
    voice_handler.shutdown()
    
    # Verify that the recorder was shut down
    mock_recorder.shutdown.assert_called_once()
    assert voice_handler.recorder_instance is None

@pytest.mark.asyncio
@patch("aris.interaction_handler.handle_route_chunks")
@patch("aris.voice_handler.tts_speak")
@patch("aris.voice_handler.summarize_for_voice")
async def test_handle_one_turn_no_recorder(
    mock_summarize, mock_tts_speak, mock_handle_route, voice_handler, mock_session_state
):
    """Test handle_one_turn when recorder is not initialized."""
    # Ensure recorder is None
    voice_handler.recorder_instance = None
    
    # Call handle_one_turn
    action, session_state = await voice_handler.handle_one_turn(mock_session_state)
    
    # Verify that the function switched to text mode
    assert action == "switch_to_text"
    assert session_state is mock_session_state
    
    # Verify that no other methods were called
    mock_handle_route.assert_not_called()
    mock_tts_speak.assert_not_called()
    mock_summarize.assert_not_called()

@pytest.mark.asyncio
@patch("aris.voice_handler.log_user_command_raw_voice")
@patch("aris.interaction_handler.handle_route_chunks")
@patch("aris.voice_handler.tts_speak")
@patch("aris.voice_handler.summarize_for_voice")
async def test_handle_one_turn_with_text(
    mock_summarize, mock_tts_speak, mock_handle_route, mock_log_command, 
    voice_handler, mock_session_state
):
    """Test handle_one_turn with successful text recognition."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    mock_recorder.text.return_value = "hey claude help me with this task"
    voice_handler.recorder_instance = mock_recorder
    
    # Configure mock handle_route_chunks
    mock_handle_route.return_value = ("new123", "I'll help you with that task.", True)
    
    # Configure mock summarize_for_voice
    mock_summarize.return_value = "I'll help with that task."
    
    # Mock asyncio.get_running_loop and run_in_executor
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = "hey claude help me with this task"
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function processed the voice input correctly
        assert action == "continue"
        assert session_state.session_id == "new123"  # Updated from handle_route_chunks
        
        # Verify that the appropriate methods were called
        mock_loop.run_in_executor.assert_called_once()
        mock_log_command.assert_called_once_with("hey  help me with this task")  # Note: trigger word removal leaves extra spaces
        mock_handle_route.assert_called_once_with(
            "hey  help me with this task", 
            mock_session_state, 
            "🤖 ARIS [test_profile] < Thinking... "
        )
        mock_summarize.assert_called_once_with("I'll help you with that task.")
        assert mock_tts_speak.call_count == 1  # Called via create_task

@pytest.mark.asyncio
@patch("aris.profile_handler.process_special_commands")
async def test_handle_one_turn_with_special_command(
    mock_process_commands, voice_handler, mock_session_state
):
    """Test handle_one_turn with a special command."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    mock_recorder.text.return_value = "@profile list"
    voice_handler.recorder_instance = mock_recorder
    
    # Configure mock process_special_commands
    mock_process_commands.return_value = True  # This is a special command
    
    # Mock asyncio.get_running_loop and run_in_executor
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = "@profile list"
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function processed the special command correctly
        assert action == "continue"
        assert session_state is mock_session_state  # Same session state
        
        # Verify that process_special_commands was called
        mock_process_commands.assert_called_once_with("@profile list", mock_session_state)

@pytest.mark.asyncio
async def test_handle_one_turn_with_voice_off_command(voice_handler, mock_session_state):
    """Test handle_one_turn with the '/voice off' command."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    mock_recorder.text.return_value = "/voice off"
    voice_handler.recorder_instance = mock_recorder
    
    # Mock asyncio.get_running_loop and run_in_executor
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = "/voice off"
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function switched to text mode
        assert action == "switch_to_text"
        assert session_state is mock_session_state  # Same session state

@pytest.mark.asyncio
@patch("aris.voice_handler.tts_speak")
async def test_handle_one_turn_with_voice_on_command(
    mock_tts_speak, voice_handler, mock_session_state
):
    """Test handle_one_turn with the '/voice on' command."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    mock_recorder.text.return_value = "/voice on"
    voice_handler.recorder_instance = mock_recorder
    
    # Mock asyncio.get_running_loop and run_in_executor
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = "/voice on"
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function acknowledged voice mode is already active
        assert action == "continue"
        assert session_state is mock_session_state  # Same session state
        assert mock_tts_speak.call_count == 1  # Called via create_task

@pytest.mark.asyncio
async def test_handle_one_turn_with_exit_command(voice_handler, mock_session_state):
    """Test handle_one_turn with the 'exit' command."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    mock_recorder.text.return_value = "exit"
    voice_handler.recorder_instance = mock_recorder
    
    # Mock asyncio.get_running_loop and run_in_executor
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = "exit"
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function returned exit action
        assert action == "exit"
        assert session_state is mock_session_state  # Same session state

@pytest.mark.asyncio
async def test_handle_one_turn_with_new_command(voice_handler, mock_session_state):
    """Test handle_one_turn with the 'new' command."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    mock_recorder.text.return_value = "new"
    voice_handler.recorder_instance = mock_recorder
    
    # Mock asyncio.get_running_loop and run_in_executor
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = "new"
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function created a new conversation
        assert action == "new_conversation"
        assert session_state.session_id is None  # New session state

@pytest.mark.asyncio
async def test_handle_one_turn_with_keyboard_interrupt(
    voice_handler, mock_session_state
):
    """Test handle_one_turn with a KeyboardInterrupt."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    voice_handler.recorder_instance = mock_recorder
    
    # Mock prompt_toolkit
    mock_prompt_toolkit = MagicMock()
    mock_print_formatted_text = MagicMock()
    mock_prompt_toolkit.print_formatted_text = mock_print_formatted_text
    
    with patch.dict('sys.modules', {
        'prompt_toolkit': mock_prompt_toolkit,
        'prompt_toolkit.formatted_text': MagicMock(FormattedText=MagicMock())
    }):
        # Mock asyncio.get_running_loop and run_in_executor to raise KeyboardInterrupt
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(side_effect=KeyboardInterrupt())
            mock_get_loop.return_value = mock_loop
            
            # Call handle_one_turn
            action, session_state = await voice_handler.handle_one_turn(mock_session_state)
            
            # Verify that the function switched to text mode
            assert action == "switch_to_text"
            assert session_state is mock_session_state  # Same session state
            
            # Verify that print_formatted_text was called with a warning message
            mock_print_formatted_text.assert_called_once()

@pytest.mark.asyncio
@patch("aris.voice_handler.tts_speak")
@patch("aris.voice_handler.log_error")
async def test_handle_one_turn_with_exception(
    mock_log_error, mock_tts_speak, voice_handler, mock_session_state
):
    """Test handle_one_turn with a general exception."""
    # Set up a mock recorder instance
    mock_recorder = MagicMock()
    voice_handler.recorder_instance = mock_recorder
    
    # Mock asyncio.get_running_loop and run_in_executor to raise an exception
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(side_effect=Exception("Test error"))
        mock_get_loop.return_value = mock_loop
        
        # Call handle_one_turn
        action, session_state = await voice_handler.handle_one_turn(mock_session_state)
        
        # Verify that the function continued despite the error
        assert action == "continue"
        assert session_state is mock_session_state  # Same session state
        
        # Verify that log_error was called and tts_speak was triggered
        mock_log_error.assert_called_once()
        assert mock_tts_speak.call_count == 1  # Called via create_task