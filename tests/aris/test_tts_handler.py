"""Tests for the tts_handler module in aris"""

import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock

from aris.tts_handler import (
    _ensure_voice_dependencies,
    _init_openai_clients_for_tts,
    tts_speak,
    summarize_for_voice
)

@pytest.fixture
def mock_openai_imports():
    """Set up mocks for OpenAI imports."""
    mock_recorder = MagicMock()
    mock_sf = MagicMock()
    mock_openai = MagicMock()
    mock_async_openai = MagicMock()
    mock_local_audio_player = MagicMock()
    
    return {
        "Recorder": mock_recorder,
        "sf": mock_sf,
        "OpenAI": mock_openai,
        "AsyncOpenAI": mock_async_openai,
        "LocalAudioPlayer": mock_local_audio_player
    }

@patch("aris.tts_handler._voice_dependencies_loaded", False)
@patch("aris.tts_handler.log_error")
def test_ensure_voice_dependencies_success(mock_log_error):
    """Test _ensure_voice_dependencies when imports succeed."""
    # We need to mock the imports inside the try block
    # Create mock modules
    mock_recorder = MagicMock()
    mock_sf = MagicMock()
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = MagicMock()
    mock_openai_module.AsyncOpenAI = MagicMock()
    mock_openai_module.helpers.LocalAudioPlayer = MagicMock()
    
    # Mock the actual imports
    with patch.dict('sys.modules', {
        'RealtimeSTT': MagicMock(AudioToTextRecorder=mock_recorder),
        'soundfile': mock_sf,
        'openai': mock_openai_module,
        'openai.helpers': mock_openai_module.helpers
    }):
        # Call the function
        result = _ensure_voice_dependencies()
        
        # Verify that the function returned True
        assert result is True
        
        # Verify that log_error was not called
        mock_log_error.assert_not_called()
        
        # Verify that global variables were set
        from aris.tts_handler import _voice_dependencies_loaded
        assert _voice_dependencies_loaded is True

@patch("aris.tts_handler._voice_dependencies_loaded", False)
@patch("aris.tts_handler.log_error")
def test_ensure_voice_dependencies_failure(mock_log_error):
    """Test _ensure_voice_dependencies when imports fail."""
    # Mock prompt_toolkit to fail the import
    mock_prompt_toolkit = MagicMock()
    mock_print_formatted_text = MagicMock()
    mock_prompt_toolkit.print_formatted_text = mock_print_formatted_text
    
    # Mock the imports to fail
    with patch.dict('sys.modules', {
        'prompt_toolkit': mock_prompt_toolkit,
        'prompt_toolkit.formatted_text': MagicMock(FormattedText=MagicMock())
    }):
        # Simulate ImportError for RealtimeSTT
        with patch.dict('sys.modules', {'RealtimeSTT': None}):
            # Call the function
            result = _ensure_voice_dependencies()
            
            # Verify that the function returned False
            assert result is False
            
            # Verify that log_error was called
            mock_log_error.assert_called_once()
            
            # Verify that print_formatted_text was called with an error message
            mock_print_formatted_text.assert_called_once()

@patch("aris.tts_handler.OpenAI", MagicMock())
@patch("aris.tts_handler.AsyncOpenAI", MagicMock())
@patch("aris.tts_handler.log_debug")
@patch("aris.tts_handler.log_warning")
def test_init_openai_clients_with_api_key(mock_log_warning, mock_log_debug, monkeypatch):
    """Test _init_openai_clients_for_tts with a valid API key."""
    # Set up environment variables
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    
    # Set up mock AsyncOpenAI
    mock_async_client = MagicMock()
    with patch("aris.tts_handler.AsyncOpenAI", return_value=mock_async_client):
        # Call the function
        result = _init_openai_clients_for_tts()
        
        # Verify that the function returned True
        assert result is True
        
        # Verify that AsyncOpenAI was called with the API key
        from aris.tts_handler import AsyncOpenAI
        AsyncOpenAI.assert_called_once_with(api_key="test_key")
        
        # Verify that log_warning was not called
        mock_log_warning.assert_not_called()
        
        # Verify that log_debug was called
        assert mock_log_debug.call_count > 0

@patch("aris.tts_handler.OpenAI", MagicMock())
@patch("aris.tts_handler.AsyncOpenAI", MagicMock())
@patch("aris.tts_handler.log_warning")
def test_init_openai_clients_without_api_key(mock_log_warning, monkeypatch):
    """Test _init_openai_clients_for_tts without an API key."""
    # Mock prompt_toolkit
    mock_prompt_toolkit = MagicMock()
    mock_print_formatted_text = MagicMock()
    mock_prompt_toolkit.print_formatted_text = mock_print_formatted_text
    
    with patch.dict('sys.modules', {
        'prompt_toolkit': mock_prompt_toolkit,
        'prompt_toolkit.formatted_text': MagicMock(FormattedText=MagicMock())
    }):
        # Ensure OPENAI_API_KEY is not set
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        
        # Call the function
        result = _init_openai_clients_for_tts()
        
        # Verify that the function returned False
        assert result is False
        
        # Verify that log_warning was called
        mock_log_warning.assert_called_once()
        
        # Verify that print_formatted_text was called with an error message
        mock_print_formatted_text.assert_called_once()

@patch("aris.tts_handler._async_openai_client_for_tts", None)
@patch("aris.tts_handler.OpenAI", MagicMock())
@patch("aris.tts_handler.AsyncOpenAI")
@patch("aris.tts_handler.log_error")
def test_init_openai_clients_with_exception(mock_log_error, mock_async_openai, monkeypatch):
    """Test _init_openai_clients_for_tts when AsyncOpenAI raises an exception."""
    # Mock prompt_toolkit
    mock_prompt_toolkit = MagicMock()
    mock_print_formatted_text = MagicMock()
    mock_prompt_toolkit.print_formatted_text = mock_print_formatted_text
    
    with patch.dict('sys.modules', {
        'prompt_toolkit': mock_prompt_toolkit,
        'prompt_toolkit.formatted_text': MagicMock(FormattedText=MagicMock())
    }):
        # Set up environment variables
        monkeypatch.setenv("OPENAI_API_KEY", "test_key")
        
        # Configure mock AsyncOpenAI to raise an exception
        mock_async_openai.side_effect = Exception("Test error")
        
        # Call the function
        result = _init_openai_clients_for_tts()
        
        # Verify that the function returned False
        assert result is False
        
        # Verify that log_error was called
        mock_log_error.assert_called_once()
        
        # Verify that print_formatted_text was called with an error message
        mock_print_formatted_text.assert_called_once()

@pytest.mark.asyncio
@patch("aris.tts_handler._async_openai_client_for_tts", None)
@patch("aris.tts_handler._ensure_voice_dependencies")
@patch("aris.tts_handler._init_openai_clients_for_tts")
@patch("aris.tts_handler.log_warning")
async def test_tts_speak_missing_dependencies(mock_log_warning, mock_init_openai, mock_ensure_voice_deps):
    """Test tts_speak when dependencies are missing."""
    # Configure mocks
    mock_ensure_voice_deps.return_value = False
    mock_init_openai.return_value = False
    
    # Call the function
    await tts_speak("Hello, world!")
    
    # Verify that log_warning was called
    mock_log_warning.assert_called_once()
    
    # Verify that _ensure_voice_dependencies was called but _init_openai_clients_for_tts was not
    # because _ensure_voice_dependencies returned False
    mock_ensure_voice_deps.assert_called_once()
    mock_init_openai.assert_not_called()

@pytest.mark.asyncio
@patch("aris.tts_handler._tts_playback_lock")
@patch("aris.tts_handler._async_openai_client_for_tts")
@patch("aris.tts_handler.LocalAudioPlayer")
@patch("aris.tts_handler.log_debug")
async def test_tts_speak_success(mock_log_debug, mock_local_audio_player, mock_async_client, mock_lock):
    """Test successful tts_speak execution."""
    # Set up mock lock
    mock_lock.__aenter__ = AsyncMock()
    mock_lock.__aexit__ = AsyncMock()
    
    # Set up mock response
    mock_response = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()
    mock_response.status_code = 200
    
    # Set up mock audio player
    mock_player_instance = MagicMock()
    mock_player_instance.play = AsyncMock()
    mock_local_audio_player.return_value = mock_player_instance
    
    # Set up mock client
    mock_async_client.audio.speech.with_streaming_response.create = MagicMock(return_value=mock_response)
    
    # Call the function
    await tts_speak("Hello, world!")
    
    # Verify that the lock was acquired and released
    mock_lock.__aenter__.assert_called_once()
    mock_lock.__aexit__.assert_called_once()
    
    # Verify that the API was called
    mock_async_client.audio.speech.with_streaming_response.create.assert_called_once_with(
        model="gpt-4o-mini-tts", voice="nova", input="Hello, world!", response_format="pcm"
    )
    
    # Verify that the audio player was called
    mock_player_instance.play.assert_called_once_with(mock_response)
    
    # Verify that log_debug was called multiple times
    assert mock_log_debug.call_count > 0

@pytest.mark.asyncio
@patch("aris.tts_handler._tts_playback_lock")
@patch("aris.tts_handler._async_openai_client_for_tts")
@patch("aris.tts_handler.log_error")
async def test_tts_speak_api_error(mock_log_error, mock_async_client, mock_lock):
    """Test tts_speak when the API call fails."""
    # Set up mock lock
    mock_lock.__aenter__ = AsyncMock()
    mock_lock.__aexit__ = AsyncMock()
    
    # Set up mock client to raise an exception
    mock_async_client.audio.speech.with_streaming_response.create.side_effect = Exception("API error")
    
    # Call the function
    await tts_speak("Hello, world!")
    
    # Verify that the lock was acquired and released
    mock_lock.__aenter__.assert_called_once()
    mock_lock.__aexit__.assert_called_once()
    
    # Verify that the API was called
    mock_async_client.audio.speech.with_streaming_response.create.assert_called_once()
    
    # Verify that log_error was called
    mock_log_error.assert_called_once()

@pytest.mark.asyncio
@patch("aris.tts_handler._async_openai_client_for_tts", None)
@patch("aris.tts_handler._ensure_voice_dependencies")
@patch("aris.tts_handler._init_openai_clients_for_tts")
@patch("aris.tts_handler.log_warning")
async def test_summarize_for_voice_missing_dependencies(
    mock_log_warning, mock_init_openai, mock_ensure_voice_deps
):
    """Test summarize_for_voice when dependencies are missing."""
    # Configure mocks
    mock_ensure_voice_deps.return_value = False
    mock_init_openai.return_value = False
    
    # Call the function
    result = await summarize_for_voice("This is a long text that needs to be summarized for voice output.")
    
    # Verify that log_warning was called
    mock_log_warning.assert_called_once()
    
    # Verify that _ensure_voice_dependencies was called but _init_openai_clients_for_tts was not
    # because _ensure_voice_dependencies returned False
    mock_ensure_voice_deps.assert_called_once()
    mock_init_openai.assert_not_called()
    
    # Verify that a fallback summary was returned
    # The test text is short (66 chars), so it should be returned as-is
    assert result == "This is a long text that needs to be summarized for voice output."

@pytest.mark.asyncio
@patch("aris.tts_handler._async_openai_client_for_tts")
@patch("aris.tts_handler.log_debug")
async def test_summarize_for_voice_success(mock_log_debug, mock_async_client):
    """Test successful summarize_for_voice execution."""
    # Set up mock response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Summarized text"
    
    # Set up mock client
    mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    # Call the function
    result = await summarize_for_voice("This is a long text that needs to be summarized for voice output.")
    
    # Verify that the API was called
    mock_async_client.chat.completions.create.assert_called_once()
    
    # Verify that log_debug was called multiple times
    assert mock_log_debug.call_count > 0
    
    # Verify that the summary was returned
    assert result == "Summarized text"

@pytest.mark.asyncio
@patch("aris.tts_handler._async_openai_client_for_tts")
@patch("aris.tts_handler.log_error")
async def test_summarize_for_voice_api_error(mock_log_error, mock_async_client):
    """Test summarize_for_voice when the API call fails."""
    # Set up mock client to raise an exception
    mock_async_client.chat.completions.create.side_effect = Exception("API error")
    
    # Call the function with a long text
    text = "This is a very long text that exceeds the maximum length for voice output. " * 10
    result = await summarize_for_voice(text)
    
    # Verify that the API was called
    mock_async_client.chat.completions.create.assert_called_once()
    
    # Verify that log_error was called
    mock_log_error.assert_called_once()
    
    # Verify that a fallback summary was returned
    assert result.endswith("...")
    assert len(result) <= 220  # Default max_len