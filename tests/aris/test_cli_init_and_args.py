# Tests for CLI initialization and app component setup

import pytest
import argparse
from unittest.mock import patch, MagicMock

# Import the module/functions to test
from aris import cli_args
from aris import cli

@pytest.fixture(autouse=True)
def reset_cli_globals(monkeypatch):
    """Resets globals in the cli_args and cli modules before each test."""
    monkeypatch.setattr(cli_args, 'INITIAL_VOICE_MODE', False)
    monkeypatch.setattr(cli_args, 'TEXT_MODE_TTS_ENABLED', False)
    monkeypatch.setattr(cli_args, 'TRIGGER_WORDS', [])
    monkeypatch.setattr(cli, '_APP_INITIALIZED', False)
    yield

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