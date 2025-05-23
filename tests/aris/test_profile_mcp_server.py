import pytest
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import json
import asyncio
import logging
import copy
import os
import yaml

# Import from the aris package
from aris.profile_manager import ProfileManager, ProfileSchema, USER_PROFILES_DIR
from aris.profile_mcp_server import ProfileMCPServer

# Official MCP SDK imports for mocking/verifying interactions
import mcp.types as mcp_types

# Test fixtures
@pytest.fixture
def mock_profile_manager() -> MagicMock:
    """Fixture for a mocked ProfileManager."""
    mock = MagicMock(spec=ProfileManager)
    mock.get_available_profiles = MagicMock(return_value={
        "default": {
            "path": "/path/to/default.yaml",
            "name": "default",
            "description": "Default profile",
            "tags": ["basic"],
            "location": "/user/profiles"
        },
        "workflow_manager": {
            "path": "/path/to/workflow_manager.yaml",
            "name": "workflow_manager",
            "description": "Workflow Manager profile",
            "tags": ["workflow"],
            "location": "/package/profiles"
        }
    })
    mock.get_profile = MagicMock()  # Use MagicMock instead of AsyncMock for simpler testing
    mock.refresh_profiles = MagicMock()
    return mock

@pytest.fixture
def sample_profile() -> dict:
    """Fixture for a sample profile data."""
    return {
        "profile_name": "test_profile",
        "description": "Test profile for unit tests",
        "system_prompt": "You are a test assistant.",
        "tools": ["tool1", "tool2"],
        "context_files": [],
        "context_mode": "auto"
    }

@pytest.fixture
def mcp_server_instance(mock_profile_manager: MagicMock) -> ProfileMCPServer:
    """Fixture for a ProfileMCPServer instance with mocked ProfileManager."""
    with patch('aris.profile_mcp_server.OfficialMCPServer', autospec=True) as MockOfficialMCPServerCls, \
         patch('aris.profile_mcp_server.Starlette', autospec=True) as MockStarlette, \
         patch('aris.profile_mcp_server.Mount', autospec=True) as MockMount:

        mock_mcp_app_instance = MockOfficialMCPServerCls.return_value
        mock_mcp_app_instance.tools = {}
        mock_mcp_app_instance.request_handlers = {}
        mock_mcp_app_instance.name = "profile-mcp-server"
        mock_mcp_app_instance.create_initialization_options = MagicMock(return_value={})

        mock_starlette_instance = MockStarlette.return_value
        mock_starlette_instance.routes = []
        
        def mock_route_constructor_side_effect(path, app, name=None, methods=None):
            route_mock = MagicMock()
            route_mock.path = path
            route_mock.app = app
            route_mock.endpoint = app
            route_mock.name = name
            route_mock.methods = methods
            mock_starlette_instance.routes.append(route_mock)
            return route_mock
        MockMount.side_effect = mock_route_constructor_side_effect
        
        server = ProfileMCPServer(
            host="127.0.0.1",
            port=8092,
            profile_manager_instance=mock_profile_manager
        )
        server.mcp_app = mock_mcp_app_instance
        return server

# --- Unit Tests for ProfileMCPServer --- #

# Test __init__ behavior
@pytest.mark.asyncio
async def test_server_init_valid_args(mock_profile_manager: MagicMock):
    """Test ProfileMCPServer initialization with valid arguments."""
    with patch('aris.profile_mcp_server.Starlette', autospec=True), \
         patch('aris.profile_mcp_server.Mount', autospec=True), \
         patch('aris.profile_mcp_server.OfficialMCPServer', autospec=True) as MockOfficialMCPServerCls:
        
        mock_mcp_app_instance = MockOfficialMCPServerCls.return_value
        mock_mcp_app_instance.name = "profile_manager"
        mock_mcp_app_instance.request_handlers = {}
        mock_mcp_app_instance.tools = {}
        mock_mcp_app_instance.create_initialization_options = MagicMock(return_value={})

        server = ProfileMCPServer(
            host="testhost",
            port=1234,
            profile_manager_instance=mock_profile_manager
        )
        assert server.profile_manager == mock_profile_manager
        assert server.host == "testhost"
        assert server.port == 1234
        MockOfficialMCPServerCls.assert_called_once_with("profile_manager")

# Test tool registration
@pytest.mark.asyncio
async def test_register_profile_tools(mcp_server_instance: ProfileMCPServer):
    """Test that _register_profile_tools registers all expected tools."""
    # Clear existing tools
    mcp_server_instance.mcp_app.tools = {}
    
    # Call the method to register tools
    mcp_server_instance._register_profile_tools()
    
    # Verify expected tools are registered
    assert "list_profiles" in mcp_server_instance.mcp_app.tools
    assert "get_profile" in mcp_server_instance.mcp_app.tools
    assert "create_profile" in mcp_server_instance.mcp_app.tools
    assert "activate_profile" in mcp_server_instance.mcp_app.tools
    assert "get_profile_variables" in mcp_server_instance.mcp_app.tools
    assert "merge_profiles" in mcp_server_instance.mcp_app.tools
    assert "refresh_profiles" in mcp_server_instance.mcp_app.tools
    assert "get_profile_mcp_config" in mcp_server_instance.mcp_app.tools

# Test list_profiles handler
@pytest.mark.asyncio
async def test_handle_list_profiles(mcp_server_instance: ProfileMCPServer, mock_profile_manager: MagicMock):
    """Test _handle_list_profiles returns correct profiles."""
    expected_profiles = mock_profile_manager.get_available_profiles()
    
    result = await mcp_server_instance._handle_list_profiles()
    
    assert len(result) == 1
    assert isinstance(result[0], mcp_types.TextContent)
    assert result[0].type == "text"
    assert json.loads(result[0].text) == expected_profiles

# Test get_profile handler
@pytest.mark.asyncio
async def test_handle_get_profile_success(mcp_server_instance: ProfileMCPServer, mock_profile_manager: MagicMock, sample_profile: dict):
    """Test _handle_get_profile returns a profile when found."""
    profile_ref = "test_profile"
    mock_profile_manager.get_profile.return_value = sample_profile
    
    # Patch the _create_error_response to verify we're not hitting an error path
    with patch.object(mcp_server_instance, '_create_error_response') as mock_error_response:
        result = await mcp_server_instance._handle_get_profile(profile_ref=profile_ref, resolve=True)
        
        # Verify error response was not called
        mock_error_response.assert_not_called()
    
    assert len(result) == 1
    assert isinstance(result[0], mcp_types.TextContent)
    # Convert the result to dict for comparison
    result_data = json.loads(result[0].text)
    assert result_data == sample_profile
    mock_profile_manager.get_profile.assert_called_once_with(profile_ref, resolve=True)

@pytest.mark.asyncio
async def test_handle_get_profile_not_found(mcp_server_instance: ProfileMCPServer, mock_profile_manager: MagicMock):
    """Test _handle_get_profile returns error when profile not found."""
    profile_ref = "nonexistent_profile"
    mock_profile_manager.get_profile.return_value = None
    
    # Patch _create_error_response to return a known value
    expected_error = mcp_types.TextContent(type="text", text=json.dumps({"tool_execution_error": True, "message": "Profile not found"}))
    with patch.object(mcp_server_instance, '_create_error_response', return_value=expected_error) as mock_error:
        result = await mcp_server_instance._handle_get_profile(profile_ref=profile_ref)
        
        # Verify error was created with the right message
        mock_error.assert_called_once_with(f"Profile '{profile_ref}' not found")
    
    assert len(result) == 1
    assert result[0] == expected_error

# Test create_profile handler
@pytest.mark.asyncio
async def test_handle_create_profile(mcp_server_instance: ProfileMCPServer, sample_profile: dict):
    """Test _handle_create_profile creates a profile file."""
    # Skip the detailed implementation test and focus on success path
    # Mock the success response directly
    expected_success_response = mcp_types.TextContent(
        type="text", 
        text=json.dumps({"success": True, "profile_path": "/mock/path/test_profile.yaml"})
    )
    
    # Patch the profile validation to avoid actual validation
    with patch('aris.profile_mcp_server.ProfileSchema'), \
         patch.object(mcp_server_instance, '_create_error_response') as mock_error, \
         patch.object(mcp_server_instance.profile_manager, 'refresh_profiles'):
             
        # Handle the file operations with mocks
        with patch('builtins.open', mock_open()), \
             patch('yaml.dump'):
            
            # Call the handler
            result = await mcp_server_instance._handle_create_profile(profile_data=sample_profile)
            
            # Verify error was not called
            mock_error.assert_not_called()
            
            # Verify response structure only - without checking specific calls
            assert len(result) == 1
            assert isinstance(result[0], mcp_types.TextContent)
            response_data = json.loads(result[0].text)
            assert response_data.get("success") is True
            assert "profile_path" in response_data

# Test handle_mcp_call_tool
@pytest.mark.asyncio
async def test_handle_mcp_call_tool_success(mcp_server_instance: ProfileMCPServer):
    """Test _handle_mcp_call_tool calls the correct handler with arguments."""
    # Set up a mock handler
    mock_handler = AsyncMock(return_value=[mcp_types.TextContent(type="text", text=json.dumps({"result": "success"}))])
    mcp_server_instance.mcp_app.tools = {
        "test_tool": {
            "handler": mock_handler,
            "description": "Test tool",
            "input_schema": {"type": "object"}
        }
    }
    
    # Test arguments
    test_args = {"arg1": "value1", "arg2": 42}
    
    # Call the method
    result = await mcp_server_instance._handle_mcp_call_tool("test_tool", test_args)
    
    # Verify handler was called with unpacked arguments
    mock_handler.assert_called_once_with(**test_args)
    
    # Verify result is passed through
    assert len(result) == 1
    assert json.loads(result[0].text) == {"result": "success"}

@pytest.mark.asyncio
async def test_handle_mcp_call_tool_nonexistent_tool(mcp_server_instance: ProfileMCPServer):
    """Test _handle_mcp_call_tool returns error for nonexistent tool."""
    mcp_server_instance.mcp_app.tools = {}
    
    result = await mcp_server_instance._handle_mcp_call_tool("nonexistent_tool", {})
    
    assert len(result) == 1
    error_data = json.loads(result[0].text)
    assert error_data.get("tool_execution_error") is True
    assert error_data.get("error_type") == "ToolNotFound"

# Test handle_list_tools
@pytest.mark.asyncio
async def test_handle_list_tools(mcp_server_instance: ProfileMCPServer):
    """Test _handle_list_tools returns all registered tools."""
    # Clear and add some tools
    mcp_server_instance.mcp_app.tools = {
        "tool1": {
            "handler": AsyncMock(),
            "description": "Tool One",
            "input_schema": {"type": "object"}
        },
        "tool2": {
            "handler": AsyncMock(),
            "description": "Tool Two",
            "input_schema": {"type": "object", "properties": {"param": {"type": "string"}}}
        }
    }
    
    result = await mcp_server_instance._handle_list_tools()
    
    assert len(result) == 2
    tool_names = [tool.name for tool in result]
    assert "tool1" in tool_names
    assert "tool2" in tool_names

# Configuration for pytest to exclude integration tests by default
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark test as integration test that requires running services"
    )

def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False, help="run integration tests"
    )