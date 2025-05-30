"""Tests for the session_state module in aris"""

import pytest
from unittest.mock import patch, MagicMock

from aris.session_state import (
    SessionState, get_current_session_state, set_current_session_state
)

@pytest.fixture
def reset_global_session_state():
    """Reset the global session state before and after each test."""
    from aris import session_state
    old_state = session_state.current_session_state
    session_state.current_session_state = None
    yield
    session_state.current_session_state = old_state

def test_session_state_initialization():
    """Test that SessionState initializes correctly."""
    session = SessionState()
    
    assert session.session_id is None
    assert session.active_profile is None
    assert session.profile_variables == {}
    assert session.mcp_config_file is None
    assert session.reference_file_path is None
    assert session.is_new_session is True
    assert session.has_read_reference_file is False
    
    # Test with session_id
    session = SessionState(session_id="test123")
    assert session.session_id == "test123"

def test_session_state_clear_profile():
    """Test the clear_profile method."""
    session = SessionState()
    
    # Set some values
    session.active_profile = {"profile_name": "test"}
    session.profile_variables = {"var1": "value1"}
    session.mcp_config_file = "/path/to/config"
    session.reference_file_path = "/path/to/reference"
    session.is_new_session = False
    session.has_read_reference_file = True
    
    # Clear profile
    session.clear_profile()
    
    # Check that profile-related values are cleared
    assert session.active_profile is None
    assert session.profile_variables == {}
    assert session.mcp_config_file is None
    assert session.reference_file_path is None
    
    # Check that session state is preserved
    assert session.is_new_session is False
    assert session.has_read_reference_file is False  # This should be reset

def test_session_state_is_first_message():
    """Test the is_first_message method."""
    session = SessionState()
    
    # First call should return True and set is_new_session to False
    assert session.is_first_message() is True
    assert session.is_new_session is False
    
    # Subsequent calls should return False
    assert session.is_first_message() is False
    assert session.is_new_session is False

@patch("aris.session_state.profile_manager")
def test_session_state_get_system_prompt(mock_profile_manager):
    """Test the get_system_prompt method."""
    session = SessionState()
    
    # No active profile
    assert session.get_system_prompt() is None
    
    # With active profile and system_prompt
    session.active_profile = {
        "profile_name": "test",
        "system_prompt": "You are a helpful assistant."
    }
    
    # Mock prompt_formatter_instance from where it's imported
    with patch("aris.prompt_formatter.prompt_formatter_instance") as mock_formatter:
        mock_formatter.prepare_system_prompt.return_value = ("Processed prompt", "/path/to/reference")
        
        system_prompt = session.get_system_prompt()
        
        # Check that prepare_system_prompt was called correctly with new workspace parameters
        mock_formatter.prepare_system_prompt.assert_called_once_with(
            "You are a helpful assistant.",
            context_files=[],
            template_variables={},
            session_id=None,
            context_mode="auto",
            workspace_path=None,
            original_cwd=None
        )
        
        # Check that reference_file_path was set
        assert session.reference_file_path == "/path/to/reference"
        
        # Check that the processed prompt was returned
        assert system_prompt == "Processed prompt"

@patch("aris.session_state.profile_manager")
def test_session_state_get_system_prompt_from_file(mock_profile_manager):
    """Test getting system prompt from a file."""
    session = SessionState()
    
    # Set active profile with system_prompt_file
    session.active_profile = {
        "profile_name": "test",
        "system_prompt_file": "/path/to/prompt.txt"
    }
    
    # Mock profile_manager.load_file_content
    mock_profile_manager.load_file_content.return_value = "System prompt from file."
    
    # Mock prompt_formatter_instance from where it's imported
    with patch("aris.prompt_formatter.prompt_formatter_instance") as mock_formatter:
        mock_formatter.prepare_system_prompt.return_value = ("Processed prompt from file", None)
        
        system_prompt = session.get_system_prompt()
        
        # Check that load_file_content was called correctly
        mock_profile_manager.load_file_content.assert_called_once_with("/path/to/prompt.txt")
        
        # Check that prepare_system_prompt was called correctly with new workspace parameters
        mock_formatter.prepare_system_prompt.assert_called_once_with(
            "System prompt from file.",
            context_files=[],
            template_variables={},
            session_id=None,
            context_mode="auto",
            workspace_path=None,
            original_cwd=None
        )
        
        # Check that the processed prompt was returned
        assert system_prompt == "Processed prompt from file"

def test_session_state_get_tool_preferences():
    """Test the get_tool_preferences method."""
    session = SessionState()
    
    # No active profile
    assert session.get_tool_preferences() is None
    
    # With active profile but no tools
    session.active_profile = {"profile_name": "test"}
    assert session.get_tool_preferences() is None
    
    # With active profile and tools
    session.active_profile = {
        "profile_name": "test",
        "tools": ["Tool1", "Tool2"]
    }
    assert session.get_tool_preferences() == ["Tool1", "Tool2"]

def test_get_current_session_state(reset_global_session_state):
    """Test the get_current_session_state function."""
    # Initially should be None
    assert get_current_session_state() is None
    
    # Set a session state
    session = SessionState(session_id="test123")
    set_current_session_state(session)
    
    # Should return the set session state
    assert get_current_session_state() is session
    assert get_current_session_state().session_id == "test123"