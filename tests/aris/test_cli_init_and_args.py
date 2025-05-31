# Tests for argument parsing and initial setup in aris.cli_args

import pytest
import argparse
from unittest.mock import patch, MagicMock
from pathlib import Path

# Import the module/functions to test
from aris import cli_args
from aris import cli
from aris.logging_utils import configure_logging, log_router_activity, log_error

@pytest.fixture(autouse=True)
def reset_cli_globals(monkeypatch):
    """Resets globals in the cli_args module before each test."""
    monkeypatch.setattr(cli_args, 'INITIAL_VOICE_MODE', False)
    monkeypatch.setattr(cli_args, 'TEXT_MODE_TTS_ENABLED', False)
    monkeypatch.setattr(cli_args, 'TRIGGER_WORDS', [])
    monkeypatch.setattr(cli, '_APP_INITIALIZED', False)
    
    # Ensure PARSED_ARGS is reset or re-evaluated if necessary by tests, 
    # or mock its usage within functions if it impacts tests directly.
    # For parse_arguments_and_configure_logging, it's an output, so direct reset isn't critical here.
    yield

@pytest.fixture
def mock_sys_argv(monkeypatch):
    def _mock_argv(arg_list):
        monkeypatch.setattr("sys.argv", ["aris.py"] + arg_list)
    return _mock_argv

@patch("aris.cli_args.configure_logging")
@patch("aris.cli_args.Path.write_text") # Mock writing to log file
@patch("aris.cli_args.log_router_activity") # Mock specific log calls
@patch("aris.cli_args.log_error")
def test_parse_arguments_and_configure_logging_defaults(
    mock_log_err: MagicMock, mock_log_router: MagicMock, mock_write_text: MagicMock, mock_configure_logging: MagicMock, 
    mock_sys_argv, tmp_path: Path, monkeypatch
):
    # For default log file path to be predictable
    monkeypatch.setattr(Path, 'resolve', lambda self: tmp_path / self.name) 
    expected_log_file = tmp_path / "aris_run.log"

    mock_sys_argv([]) # No arguments
    args = cli_args.parse_arguments_and_configure_logging()

    assert args.voice is False
    assert args.speak is False
    assert args.verbose is False
    assert args.log_file == "aris_run.log" # Default name before resolve
    assert args.no_profile_mcp_server is False
    assert args.profile_mcp_port == 8094 # Default port
    assert cli_args.INITIAL_VOICE_MODE is False
    assert cli_args.TEXT_MODE_TTS_ENABLED is False
    assert cli_args.TRIGGER_WORDS == ["claude", "cloud", "clod", "clawd", "clode", "clause"]

    mock_configure_logging.assert_called_once_with(
        enable_console_logging=False,
        log_file_path=str(expected_log_file)
    )
    mock_write_text.assert_called_once_with("") # Log file cleared
    mock_log_router.assert_called_with(f"Log file '{str(expected_log_file)}' cleared/initialized.")

@patch("aris.cli_args.configure_logging")
@patch("aris.cli_args.Path.write_text")
@patch("aris.cli_args.log_router_activity")
@patch("aris.cli_args.log_error")
def test_parse_arguments_custom_values(
    mock_log_err: MagicMock, mock_log_router: MagicMock, mock_write_text: MagicMock, mock_configure_logging: MagicMock, 
    mock_sys_argv, tmp_path: Path, monkeypatch
):
    custom_log_filename = "my_chat.log"
    expected_log_file = tmp_path / custom_log_filename
    monkeypatch.setattr(Path, 'resolve', lambda self: tmp_path / self.name)

    test_args = [
        "--voice", 
        "--speak", 
        "--trigger-words", "alexa,hey,computer",
        "--verbose",
        "--log-file", custom_log_filename
    ]
    mock_sys_argv(test_args)
    args = cli_args.parse_arguments_and_configure_logging()

    assert args.voice is True
    assert args.speak is True
    assert args.verbose is True
    assert args.log_file == custom_log_filename
    assert cli_args.INITIAL_VOICE_MODE is True
    assert cli_args.TEXT_MODE_TTS_ENABLED is True
    assert cli_args.TRIGGER_WORDS == ["alexa", "hey", "computer"]

    mock_configure_logging.assert_called_once_with(
        enable_console_logging=True,
        log_file_path=str(expected_log_file)
    )
    mock_write_text.assert_called_once_with("")
    mock_log_router.assert_called_with(f"Log file '{str(expected_log_file)}' cleared/initialized.")

@patch("aris.cli_args.configure_logging")
@patch("aris.cli_args.Path.write_text", side_effect=IOError("Disk full"))
@patch("aris.cli_args.log_router_activity")
@patch("aris.cli_args.log_error")
def test_parse_arguments_log_clear_fails(
    mock_log_err: MagicMock, mock_log_router: MagicMock, mock_write_text_raiser: MagicMock, 
    mock_configure_logging: MagicMock, mock_sys_argv, tmp_path: Path, monkeypatch
):
    expected_log_file = tmp_path / "aris_run.log"
    monkeypatch.setattr(Path, 'resolve', lambda self: tmp_path / self.name)

    mock_sys_argv([])
    cli_args.parse_arguments_and_configure_logging()
    
    mock_configure_logging.assert_called_once_with(
        enable_console_logging=False,
        log_file_path=str(expected_log_file)
    )
    mock_write_text_raiser.assert_called_once_with("")
    mock_log_err.assert_called_once_with(f"Could not clear/initialize log file '{str(expected_log_file)}': Disk full")

# Test initial dotenv loading (qualitative check, actual loading depends on .env file presence)
@patch("aris.cli_args.load_dotenv")
@patch("aris.cli_args.find_dotenv")
@patch("aris.cli_args.parse_arguments_and_configure_logging")
def test_initialize_environment(mock_parse_args_log_config, mock_find_dotenv, mock_load_dotenv):
    # Test initialize_environment function
    cli_args.initialize_environment()
    
    # Verify that functions were called
    mock_load_dotenv.assert_called_once()
    mock_find_dotenv.assert_called_once()
    mock_parse_args_log_config.assert_called_once()

@pytest.mark.asyncio # Mark test as async
@patch("aris.orchestrator.initialize_router_components") 
@patch("aris.tts_handler._ensure_voice_dependencies", return_value=True) 
@patch("aris.tts_handler._init_openai_clients_for_tts", return_value=True) 
@patch("aris.cli.log_debug") 
@patch("aris.cli.log_router_activity") 
@patch("aris.cli.log_warning")
async def test_fully_initialize_app_components_speak_mode_success(
    mock_log_warning, mock_log_router, mock_log_debug, mock_init_openai, mock_ensure_voice, mock_init_router, monkeypatch
):
    # Simulate --speak flag being parsed
    monkeypatch.setattr(cli, 'PARSED_ARGS', argparse.Namespace(speak=True, voice=False, no_profile_mcp_server=False, profile_mcp_port=8092)) 
    monkeypatch.setattr(cli, 'INITIAL_VOICE_MODE', False)
    monkeypatch.setattr(cli_args, 'TEXT_MODE_TTS_ENABLED', True) 

    await cli.fully_initialize_app_components() # Await the async function

    mock_init_router.assert_called_once()
    mock_ensure_voice.assert_called_once()
    mock_init_openai.assert_called_once()
    assert cli_args.TEXT_MODE_TTS_ENABLED is True # Should remain true
    mock_log_router.assert_any_call("TTS for text mode enabled at startup via --speak flag.")
    assert cli._APP_INITIALIZED is True

@pytest.mark.asyncio # Mark test as async
@patch("aris.orchestrator.initialize_router_components") 
@patch("aris.tts_handler._ensure_voice_dependencies", return_value=False) # Voice deps fail
@patch("aris.tts_handler._init_openai_clients_for_tts", return_value=True)
@patch("aris.cli.log_warning")
async def test_fully_initialize_app_components_speak_mode_voice_deps_fail(
    mock_log_warning, mock_init_openai, mock_ensure_voice, mock_init_router, monkeypatch
):
    monkeypatch.setattr(cli, 'PARSED_ARGS', argparse.Namespace(speak=True, voice=False, no_profile_mcp_server=False, profile_mcp_port=8092))
    monkeypatch.setattr(cli, 'INITIAL_VOICE_MODE', False)
    monkeypatch.setattr(cli_args, 'TEXT_MODE_TTS_ENABLED', True) # Initially true from args

    await cli.fully_initialize_app_components() # Await

    mock_init_router.assert_called_once()
    mock_ensure_voice.assert_called_once()
    mock_init_openai.assert_not_called() # Should not be called if voice deps fail
    assert cli._APP_INITIALIZED is True
    # Check for warning message about TTS failure
    warning_calls = [str(call) for call in mock_log_warning.call_args_list]
    assert any("TTS via --speak could not be enabled" in call for call in warning_calls)

@pytest.mark.asyncio # Mark test as async
@patch("aris.orchestrator.initialize_router_components") 
@patch("aris.tts_handler._ensure_voice_dependencies", return_value=True) 
@patch("aris.tts_handler._init_openai_clients_for_tts", return_value=False) # OpenAI client init fail
@patch("aris.cli.log_warning")
async def test_fully_initialize_app_components_speak_mode_openai_fail(
    mock_log_warning, mock_init_openai, mock_ensure_voice, mock_init_router, monkeypatch
):
    monkeypatch.setattr(cli, 'PARSED_ARGS', argparse.Namespace(speak=True, voice=False, no_profile_mcp_server=False, profile_mcp_port=8092))
    monkeypatch.setattr(cli, 'INITIAL_VOICE_MODE', False)
    monkeypatch.setattr(cli_args, 'TEXT_MODE_TTS_ENABLED', True)

    await cli.fully_initialize_app_components() # Await

    mock_init_router.assert_called_once()
    mock_ensure_voice.assert_called_once()
    mock_init_openai.assert_called_once()
    assert cli._APP_INITIALIZED is True
    # Check for warning message about OpenAI client failure
    warning_calls = [str(call) for call in mock_log_warning.call_args_list]
    assert any("OpenAI client initialization failed" in call for call in warning_calls)

@pytest.mark.asyncio # Mark test as async
@patch("aris.orchestrator.initialize_router_components") 
async def test_fully_initialize_app_components_voice_mode(
    mock_init_router, monkeypatch
):
    monkeypatch.setattr(cli, 'PARSED_ARGS', argparse.Namespace(speak=False, voice=True, no_profile_mcp_server=False, profile_mcp_port=8092))
    monkeypatch.setattr(cli, 'INITIAL_VOICE_MODE', True)
    monkeypatch.setattr(cli, 'TRIGGER_WORDS', ["testtrigger"])
    monkeypatch.setattr(cli_args, 'TEXT_MODE_TTS_ENABLED', False)

    await cli.fully_initialize_app_components() # Await

    mock_init_router.assert_called_once()
    assert cli._APP_INITIALIZED is True

@pytest.mark.asyncio # Mark test as async
@patch("aris.orchestrator.initialize_router_components")
async def test_fully_initialize_app_components_called_multiple_times(
    mock_init_router, monkeypatch
):
    monkeypatch.setattr(cli, '_APP_INITIALIZED', False) # Ensure it starts as False
    monkeypatch.setattr(cli, 'PARSED_ARGS', argparse.Namespace(speak=False, voice=False, no_profile_mcp_server=False, profile_mcp_port=8092))
    monkeypatch.setattr(cli, 'INITIAL_VOICE_MODE', False)

    await cli.fully_initialize_app_components() # First call # Await
    assert mock_init_router.call_count == 1
    assert cli._APP_INITIALIZED is True

    await cli.fully_initialize_app_components() # Second call # Await
    assert mock_init_router.call_count == 1 # Should not be called again