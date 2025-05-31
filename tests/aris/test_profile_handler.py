"""Tests for the profile_handler module in aris"""

import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock, mock_open

from aris.profile_handler import (
    print_profile_list,
    print_profile_details,
    collect_template_variables,
    handle_variables_command,
    create_profile_interactive,
    activate_profile,
    process_special_commands
)
from aris.session_state import SessionState

@pytest.fixture
def mock_session_state():
    """Create a mock session state for testing."""
    session_state = SessionState(session_id="test123")
    session_state.active_profile = {"profile_name": "test_profile"}
    return session_state

@pytest.fixture
def mock_profiles():
    """Create mock profiles for testing."""
    return {
        "default": {
            "name": "Default Profile",
            "description": "Default profile for ARIS",
            "tags": ["general"]
        },
        "youtube": {
            "name": "YouTube Profile",
            "description": "Profile for YouTube content generation",
            "tags": ["content", "media"]
        },
        "github": {
            "name": "GitHub Profile",
            "description": "Profile for GitHub integration",
            "tags": ["development"]
        },
        "notags": {
            "name": "No Tags Profile",
            "description": "Profile without tags field"
            # Note: no 'tags' field at all - this will be categorized as 'uncategorized'
        }
    }

@patch("aris.profile_handler.print_formatted_text")
def test_print_profile_list(mock_print, mock_profiles):
    """Test print_profile_list function."""
    # Call the function
    print_profile_list(mock_profiles)
    
    # Verify that print_formatted_text was called multiple times
    assert mock_print.call_count > 0
    
    # Check that the function handled tags correctly
    # Should print headers for each tag category that has profiles
    # The uncategorized profile has empty tags, so it should show up as [uncategorized]
    expected_categories = ["[general]", "[content]", "[media]", "[development]"]
    
    # Check if there's an uncategorized section (only if there are profiles without tags field)
    has_uncategorized_profile = any(
        'tags' not in profile
        for profile in mock_profiles.values()
    )
    
    
    if has_uncategorized_profile and len(expected_categories) > 0:
        expected_categories.append("[uncategorized]")
    
    for category in expected_categories:
        found = False
        for call in mock_print.call_args_list:
            if category in str(call):
                found = True
                break
        assert found, f"Category {category} not found in output"

@patch("aris.profile_handler.print_formatted_text")
def test_print_profile_details_basic(mock_print):
    """Test print_profile_details function with basic profile."""
    # Create a basic profile
    profile = {
        "profile_name": "test_profile",
        "description": "Test profile description",
        "version": "1.0.0",
        "author": "Test Author"
    }
    
    # Call the function
    print_profile_details(profile)
    
    # Verify that print_formatted_text was called multiple times
    assert mock_print.call_count > 0
    
    # Check that basic profile information was printed
    profile_info = ["test_profile", "Test profile description", "1.0.0", "Test Author"]
    for info in profile_info:
        found = False
        for call in mock_print.call_args_list:
            if info in str(call):
                found = True
                break
        assert found, f"Profile info '{info}' not found in output"

@patch("aris.profile_handler.print_formatted_text")
def test_print_profile_details_complete(mock_print):
    """Test print_profile_details function with a complete profile."""
    # Create a complete profile with all possible fields
    profile = {
        "profile_name": "complete_profile",
        "description": "Complete profile with all fields",
        "version": "1.0.0",
        "author": "Test Author",
        "extends": ["base_profile"],
        "system_prompt": "You are a helpful assistant.",
        "tools": ["Tool1", "Tool2"],
        "context_files": ["file1.txt", "file2.txt"],
        "context_mode": "auto",
        "mcp_config_files": ["config1.json", "config2.json"],
        "welcome_message": "Welcome to the complete profile!",
        "variables": [
            {
                "name": "var1",
                "description": "Variable 1",
                "required": True,
                "default": "default1"
            },
            {
                "name": "var2",
                "description": "Variable 2",
                "required": False
            }
        ]
    }
    
    # Call the function
    print_profile_details(profile)
    
    # Verify that print_formatted_text was called multiple times
    assert mock_print.call_count > 0
    
    # Check that all sections were printed
    sections = [
        "PROFILE DETAILS", "Complete profile with all fields", "1.0.0", "Test Author",
        "base_profile", "System Prompt", "Tool1, Tool2",
        "Context Files", "MCP Config Files", "Welcome Message", "Template Variables"
    ]
    
    for section in sections:
        found = False
        for call in mock_print.call_args_list:
            if section in str(call):
                found = True
                break
        assert found, f"Section '{section}' not found in output"

@patch("aris.profile_handler.input")
@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_formatted_text")
def test_collect_template_variables(mock_print, mock_profile_manager, mock_input):
    """Test collect_template_variables function."""
    # Create a profile with variables
    profile = {
        "profile_name": "test_profile",
        "variables": [
            {
                "name": "var1",
                "description": "Variable 1",
                "required": True,
                "default": "default1"
            },
            {
                "name": "var2",
                "description": "Variable 2",
                "required": False,
                "default": None
            }
        ]
    }
    
    # Create variable objects
    var1 = MagicMock()
    var1.name = "var1"
    var1.description = "Variable 1"
    var1.required = True
    var1.default = "default1"
    
    var2 = MagicMock()
    var2.name = "var2"
    var2.description = "Variable 2"
    var2.required = False
    var2.default = None
    
    # Configure mock profile_manager
    mock_profile_manager.get_variables_from_profile.return_value = [var1, var2]
    
    # Configure mock input
    mock_input.side_effect = ["value1", "value2"]
    
    # Call the function
    result = collect_template_variables(profile)
    
    # Verify that print_formatted_text was called
    mock_print.assert_called_once()
    
    # Verify that input was called twice
    assert mock_input.call_count == 2
    
    # Verify that the correct values were returned
    assert result == {"var1": "value1", "var2": "value2"}

@patch("aris.profile_handler.input")
@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_formatted_text")
def test_collect_template_variables_with_defaults(mock_print, mock_profile_manager, mock_input):
    """Test collect_template_variables function with default values."""
    # Create a profile with variables
    profile = {
        "profile_name": "test_profile",
        "variables": [
            {
                "name": "var1",
                "description": "Variable 1",
                "required": True,
                "default": "default1"
            },
            {
                "name": "var2",
                "description": "Variable 2",
                "required": False,
                "default": "default2"
            }
        ]
    }
    
    # Create variable objects
    var1 = MagicMock()
    var1.name = "var1"
    var1.description = "Variable 1"
    var1.required = True
    var1.default = "default1"
    
    var2 = MagicMock()
    var2.name = "var2"
    var2.description = "Variable 2"
    var2.required = False
    var2.default = "default2"
    
    # Configure mock profile_manager
    mock_profile_manager.get_variables_from_profile.return_value = [var1, var2]
    
    # Configure mock input to return empty strings (use defaults)
    mock_input.side_effect = ["", ""]
    
    # Call the function
    result = collect_template_variables(profile)
    
    # Verify that input was called twice
    assert mock_input.call_count == 2
    
    # Verify that the correct values were returned (defaults)
    assert result == {"var1": "default1", "var2": "default2"}

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.get_current_session_state")
def test_handle_variables_command_no_active_profile(mock_get_current_session_state, mock_print, mock_session_state):
    """Test handle_variables_command with no active profile."""
    # Configure mock session state with no active profile
    mock_session_state.active_profile = None
    
    # Call the function
    handle_variables_command("", mock_session_state)
    
    # Verify that print_formatted_text was called with an error message
    mock_print.assert_called_once()
    error_message = "Error: No active profile."
    assert error_message in str(mock_print.call_args[0])

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.get_current_session_state")
def test_handle_variables_command_show_all(mock_get_current_session_state, mock_print, mock_session_state):
    """Test handle_variables_command to show all variables."""
    # Configure mock session state
    mock_session_state.profile_variables = {"var1": "value1", "var2": "value2"}
    
    # Call the function
    handle_variables_command("", mock_session_state)
    
    # Verify that print_formatted_text was called multiple times
    assert mock_print.call_count > 0
    
    # Check that variable names were included in the output
    found_var1 = False
    found_var2 = False
    for call in mock_print.call_args_list:
        if "var1" in str(call):
            found_var1 = True
        if "var2" in str(call):
            found_var2 = True
    
    assert found_var1, "Variable 'var1' not found in output"
    assert found_var2, "Variable 'var2' not found in output"

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.get_current_session_state")
def test_handle_variables_command_show_one(mock_get_current_session_state, mock_print, mock_session_state):
    """Test handle_variables_command to show one variable."""
    # Configure mock session state
    mock_session_state.profile_variables = {"var1": "value1", "var2": "value2"}
    
    # Call the function to show var1
    handle_variables_command("var1", mock_session_state)
    
    # Verify that print_formatted_text was called
    mock_print.assert_called_once()
    
    # Check that var1 was included in the output
    assert "var1" in str(mock_print.call_args[0])
    assert "value1" in str(mock_print.call_args[0])

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.set_current_session_state")
@patch("aris.profile_handler.get_current_session_state")
def test_handle_variables_command_set_variable(
    mock_get_current_session_state, mock_set_current_session_state, 
    mock_profile_manager, mock_print, mock_session_state
):
    """Test handle_variables_command to set a variable."""
    # Configure mock profile_manager
    var = MagicMock()
    var.name = "var1"
    mock_profile_manager.get_variables_from_profile.return_value = [var]
    
    # Call the function to set var1
    handle_variables_command("var1 new_value", mock_session_state)
    
    # Verify that the variable was set
    assert mock_session_state.profile_variables["var1"] == "new_value"
    
    # Verify that set_current_session_state was called
    mock_set_current_session_state.assert_called_once_with(mock_session_state)
    
    # Verify that print_formatted_text was called
    mock_print.assert_called_once()

@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_formatted_text")
def test_create_profile_interactive_success(mock_print, mock_profile_manager):
    """Test create_profile_interactive function with successful creation."""
    # Configure mock profile_manager
    mock_profile_manager.create_profile_interactive.return_value = "/path/to/profile.yaml"
    
    # Call the function
    create_profile_interactive("new_profile")
    
    # Verify that profile_manager.create_profile_interactive was called
    mock_profile_manager.create_profile_interactive.assert_called_once_with("new_profile")
    
    # Verify that print_formatted_text was called with a success message
    mock_print.assert_called_once()
    success_message = "Profile 'new_profile' created successfully"
    assert success_message in str(mock_print.call_args[0])

@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_formatted_text")
def test_create_profile_interactive_failure(mock_print, mock_profile_manager):
    """Test create_profile_interactive function with failed creation."""
    # Configure mock profile_manager
    mock_profile_manager.create_profile_interactive.return_value = None
    
    # Call the function
    create_profile_interactive("new_profile")
    
    # Verify that profile_manager.create_profile_interactive was called
    mock_profile_manager.create_profile_interactive.assert_called_once_with("new_profile")
    
    # Verify that print_formatted_text was called with an error message
    mock_print.assert_called_once()
    error_message = "Failed to create profile"
    assert error_message in str(mock_print.call_args[0])

@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.collect_template_variables")
@patch("aris.profile_handler.set_current_session_state")
@patch("aris.profile_handler.print_formatted_text")
def test_activate_profile_success(
    mock_print, mock_set_current_session_state, 
    mock_collect_variables, mock_profile_manager, mock_session_state
):
    """Test activate_profile function with successful activation."""
    # Configure mock profile_manager
    profile = {
        "profile_name": "test_profile",
        "welcome_message": "Welcome to test_profile!",
        "mcp_config_files": ["config1.json"]  # Add this to trigger MCP config handling
    }
    mock_profile_manager.get_profile.return_value = profile
    mock_profile_manager.get_merged_mcp_config_path.return_value = "/path/to/config.json"
    
    # Configure mock collect_template_variables
    mock_collect_variables.return_value = {"var1": "value1"}
    
    # Call the function
    result = activate_profile("test_profile", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that profile_manager.get_profile was called with workspace_variables
    mock_profile_manager.get_profile.assert_called_once_with("test_profile", resolve=True, workspace_variables={})
    
    # Verify that collect_template_variables was called
    mock_collect_variables.assert_called_once_with(profile)
    
    # Verify that the session state was updated
    assert mock_session_state.active_profile is profile
    assert mock_session_state.profile_variables == {"var1": "value1"}
    assert mock_session_state.mcp_config_file == "/path/to/config.json"
    assert mock_session_state.is_new_session is True
    
    # Verify that set_current_session_state was called
    mock_set_current_session_state.assert_called_once_with(mock_session_state)
    
    # Verify that print_formatted_text was called
    assert mock_print.call_count >= 1  # At least one call for the activation message

@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_formatted_text")
def test_activate_profile_not_found(mock_print, mock_profile_manager, mock_session_state):
    """Test activate_profile function when profile is not found."""
    # Configure mock profile_manager
    mock_profile_manager.get_profile.return_value = None
    
    # Call the function
    result = activate_profile("nonexistent_profile", mock_session_state)
    
    # Verify that the function returned False
    assert result is False
    
    # Verify that profile_manager.get_profile was called with workspace_variables
    mock_profile_manager.get_profile.assert_called_once_with("nonexistent_profile", resolve=True, workspace_variables={})
    
    # Verify that print_formatted_text was called with an error message
    mock_print.assert_called_once()
    error_message = "Profile 'nonexistent_profile' not found"
    assert error_message in str(mock_print.call_args[0])

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.profile_manager")
def test_process_special_commands_profile_list(mock_profile_manager, mock_print, mock_session_state, mock_profiles):
    """Test process_special_commands with @profile list."""
    # Configure mock profile_manager
    mock_profile_manager.get_available_profiles.return_value = mock_profiles
    
    # Call the function
    result = process_special_commands("@profile list", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that profile_manager.get_available_profiles was called
    mock_profile_manager.get_available_profiles.assert_called_once()
    
    # Verify that print_formatted_text was called multiple times
    assert mock_print.call_count > 0

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.print_profile_details")
def test_process_special_commands_profile_current(mock_print_details, mock_print, mock_session_state):
    """Test process_special_commands with @profile current."""
    # Call the function
    result = process_special_commands("@profile current", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that print_profile_details was called with the active profile
    mock_print_details.assert_called_once_with(mock_session_state.active_profile)

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_profile_details")
def test_process_special_commands_profile_show(mock_print_details, mock_profile_manager, mock_print, mock_session_state):
    """Test process_special_commands with @profile show."""
    # Configure mock profile_manager
    profile = {"profile_name": "test_profile"}
    mock_profile_manager.get_profile.return_value = profile
    
    # Call the function
    result = process_special_commands("@profile show test_profile", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that profile_manager.get_profile was called
    mock_profile_manager.get_profile.assert_called_once_with("test_profile", resolve=False)
    
    # Verify that print_profile_details was called with the profile
    mock_print_details.assert_called_once_with(profile)

@patch("aris.profile_handler.print_formatted_text")
@patch("aris.profile_handler.set_current_session_state")
def test_process_special_commands_profile_clear(mock_set_current_session_state, mock_print, mock_session_state):
    """Test process_special_commands with @profile clear."""
    # Call the function
    result = process_special_commands("@profile clear", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that session_state.clear_profile was called
    assert mock_session_state.active_profile is None
    assert mock_session_state.profile_variables == {}
    assert mock_session_state.mcp_config_file is None
    assert mock_session_state.reference_file_path is None
    
    # Verify that set_current_session_state was called
    mock_set_current_session_state.assert_called_once_with(mock_session_state)
    
    # Verify that print_formatted_text was called
    mock_print.assert_called_once()
    assert "Profile cleared" in str(mock_print.call_args[0])

@patch("aris.profile_handler.profile_manager")
@patch("aris.profile_handler.print_formatted_text")
def test_process_special_commands_profile_refresh(mock_print, mock_profile_manager, mock_session_state):
    """Test process_special_commands with @profile refresh."""
    # Call the function
    result = process_special_commands("@profile refresh", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that profile_manager.refresh_profiles was called
    mock_profile_manager.refresh_profiles.assert_called_once()
    
    # Verify that print_formatted_text was called
    mock_print.assert_called_once()
    assert "Profile registry refreshed" in str(mock_print.call_args[0])

@patch("aris.profile_handler.create_profile_interactive")
def test_process_special_commands_profile_create(mock_create_profile, mock_session_state):
    """Test process_special_commands with @profile create."""
    # Call the function
    result = process_special_commands("@profile create new_profile", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that create_profile_interactive was called
    mock_create_profile.assert_called_once_with("new_profile")

@patch("aris.profile_handler.handle_variables_command")
def test_process_special_commands_profile_variables(mock_handle_variables, mock_session_state):
    """Test process_special_commands with @profile variables."""
    # Call the function
    result = process_special_commands("@profile variables var1 value1", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that handle_variables_command was called
    mock_handle_variables.assert_called_once_with("var1 value1", mock_session_state)

@patch("aris.profile_handler.activate_profile")
def test_process_special_commands_profile_activate(mock_activate_profile, mock_session_state):
    """Test process_special_commands with @profile <profile_name>."""
    # Call the function
    result = process_special_commands("@profile test_profile", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that activate_profile was called
    mock_activate_profile.assert_called_once_with("test_profile", mock_session_state)

def test_process_special_commands_not_special(mock_session_state):
    """Test process_special_commands with a non-special command."""
    # Call the function with a regular message
    result = process_special_commands("Hello, world!", mock_session_state)
    
    # Verify that the function returned False
    assert result is False

@patch("aris.profile_handler.print_formatted_text")
def test_process_special_commands_invalid_profile_command(mock_print, mock_session_state):
    """Test process_special_commands with an invalid @profile command."""
    # Call the function with just @profile
    result = process_special_commands("@profile", mock_session_state)
    
    # Verify that the function returned True
    assert result is True
    
    # Verify that print_formatted_text was called with a usage message
    mock_print.assert_called_once()
    assert "Usage:" in str(mock_print.call_args[0])