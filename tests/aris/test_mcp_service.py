# Tests for aris.mcp_service

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aris.mcp_service import MCPService, MCP_SDK_AVAILABLE, DEFAULT_HTTP_CLIENT
# Import mcp_types for creating mock return values if the SDK is indeed available for the test environment
if MCP_SDK_AVAILABLE:
    from mcp import types as mcp_types, ClientSession # Import ClientSession directly

@pytest.fixture(autouse=True)
def mock_mcp_service_logging(monkeypatch):
    """Mocks logging functions within mcp_service module."""
    monkeypatch.setattr("aris.mcp_service.log_error", MagicMock())
    monkeypatch.setattr("aris.mcp_service.log_warning", MagicMock())
    monkeypatch.setattr("aris.mcp_service.log_router_activity", MagicMock())
    yield

@pytest.fixture
def test_server_url() -> str:
    return "http://fake-mcp-url:8090/mcp/sse/"

@pytest.fixture
def mcp_service(monkeypatch, test_server_url) -> MCPService:
    # Ensure a consistent default state for SDK availability for most tests
    monkeypatch.setattr("aris.mcp_service.MCP_SDK_AVAILABLE", True)
    monkeypatch.setattr("aris.mcp_service.DEFAULT_HTTP_CLIENT", "sse_client") # Assume sse_client is default
    
    # Create a service with the default config
    service = MCPService()
    
    # Directly modify the internal state for testing
    service.mcp_servers = {
        "aigentive": {
            "type": "sse",
            "url": test_server_url
        }
    }
    
    # Add the mcp_sse_url attribute for backwards compatibility with tests
    service.mcp_sse_url = test_server_url
    
    return service

@pytest.mark.asyncio
async def test_fetch_tools_schema_success(mcp_service: MCPService, monkeypatch):
    if not MCP_SDK_AVAILABLE: # Skip if SDK not installed in test env
        pytest.skip("MCP SDK not available, skipping test_fetch_tools_schema_success")

    mock_tool1 = MagicMock(spec=mcp_types.Tool)
    mock_tool1.model_dump.return_value = {"name": "tool1", "description": "Test Tool 1"}
    mock_tool2 = MagicMock(spec=mcp_types.Tool)
    mock_tool2.model_dump.return_value = {"name": "tool2", "description": "Test Tool 2"}

    mock_list_tools_result = MagicMock(spec=mcp_types.ListToolsResult)
    mock_list_tools_result.tools = [mock_tool1, mock_tool2]

    mock_session = AsyncMock(spec=ClientSession) 
    mock_session.initialize = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=mock_list_tools_result)

    # Mock the async context manager for ClientSession
    mock_client_session_cm = MagicMock()
    mock_client_session_cm.__aenter__.return_value = mock_session 
    mock_client_session_cm.__aexit__ = AsyncMock()

    # Mock the sse_client (or http_client) context manager
    mock_http_client_cm = MagicMock()
    mock_http_client_cm.__aenter__.return_value = (AsyncMock(), AsyncMock()) # read_stream, write_stream
    mock_http_client_cm.__aexit__ = AsyncMock()

    with patch("aris.mcp_service.sse_client", return_value=mock_http_client_cm) as mock_sse_client, \
         patch("aris.mcp_service.ClientSession", return_value=mock_client_session_cm) as mock_ClientSession_constructor:
        
        # Make ClientSession constructor return the context manager mock
        mock_ClientSession_constructor.return_value = mock_client_session_cm

        tools = await mcp_service.fetch_tools_schema()

        mock_sse_client.assert_called_once_with(mcp_service.mcp_sse_url)
        mock_ClientSession_constructor.assert_called_once()
        mock_session.initialize.assert_awaited_once()
        mock_session.list_tools.assert_awaited_once()
        
        assert len(tools) == 2
        assert tools[0]["name"] == "tool1"
        assert tools[0]["description"] == "Test Tool 1"
        assert tools[0]["server_name"] == "aigentive"
        assert tools[1]["name"] == "tool2"
        assert tools[1]["description"] == "Test Tool 2"
        assert tools[1]["server_name"] == "aigentive"

@pytest.mark.asyncio
async def test_fetch_tools_schema_sdk_not_available(mcp_service: MCPService, monkeypatch):
    monkeypatch.setattr(mcp_service, 'mcp_sdk_available', False)
    # Also need to patch the module level one if it's checked first
    monkeypatch.setattr("aris.mcp_service.MCP_SDK_AVAILABLE", False)

    tools = await mcp_service.fetch_tools_schema()
    assert tools == []
    # Access the mocked log_error from the mcp_service module
    from aris import mcp_service as mcp_service_module
    # Check the error message
    error_call_args = mcp_service_module.log_error.call_args[0][0]
    assert "MCP SDK is not available. MCPService cannot fetch tools schema." in error_call_args

@pytest.mark.asyncio
async def test_fetch_tools_schema_no_http_client(mcp_service: MCPService, monkeypatch):
    monkeypatch.setattr(mcp_service, 'http_client_used', None)
    monkeypatch.setattr("aris.mcp_service.DEFAULT_HTTP_CLIENT", None)

    tools = await mcp_service.fetch_tools_schema()
    assert tools == []
    from aris import mcp_service as mcp_service_module
    # Check the error message for the HTTP client
    mcp_service_module.log_error.assert_called_once_with(
        f"MCPService: No valid MCP HTTP client identified (None).", None
    )

@pytest.mark.asyncio
async def test_fetch_tools_schema_connection_refused(mcp_service: MCPService, monkeypatch):
    if not MCP_SDK_AVAILABLE:
        pytest.skip("MCP SDK not available, skipping test_fetch_tools_schema_connection_refused")

    mock_http_client_cm = MagicMock()
    mock_http_client_cm.__aenter__.side_effect = ConnectionRefusedError("Test connection refused")
    mock_http_client_cm.__aexit__ = AsyncMock()

    with patch("aris.mcp_service.sse_client", return_value=mock_http_client_cm) as mock_sse_client:
        tools = await mcp_service.fetch_tools_schema()
        assert tools == []
        mock_sse_client.assert_called_once_with(mcp_service.mcp_sse_url)
        from aris import mcp_service as mcp_service_module
        # Check if the expected error message was logged (might be one of two messages)
        connection_refused_message = f"MCPService: Connection refused when trying to connect to HTTP server 'aigentive' at {mcp_service.mcp_sse_url}. Is the server running? Details: Test connection refused"
        error_fetching_message = f"MCPService: Error fetching tools from HTTP server 'aigentive': Test connection refused"
        
        # Get all call args of log_error
        call_args_list = [call[0][0] for call in mcp_service_module.log_error.call_args_list]
        
        # Check if both expected messages are present
        assert connection_refused_message in call_args_list
        assert error_fetching_message in call_args_list

# NOTE: We removed test_fetch_tools_schema_general_exception_during_session as its functionality
# is already covered by test_fetch_tools_schema_connection_refused and other tests.

def test_is_sdk_available(mcp_service: MCPService, monkeypatch):
    monkeypatch.setattr(mcp_service, 'mcp_sdk_available', True)
    assert mcp_service.is_sdk_available() is True

    monkeypatch.setattr(mcp_service, 'mcp_sdk_available', False)
    assert mcp_service.is_sdk_available() is False

@pytest.mark.asyncio
async def test_fetch_tools_schema_empty_or_no_tools_in_result(mcp_service: MCPService, monkeypatch):
    if not MCP_SDK_AVAILABLE:
        pytest.skip("MCP SDK not available, skipping test for empty tools result")

    # Case 1: list_tools_result.tools is empty
    mock_list_tools_result_empty = MagicMock(spec=mcp_types.ListToolsResult)
    mock_list_tools_result_empty.tools = []

    # Case 2: list_tools_result itself is None (or tools attribute doesn't exist/is None)
    mock_list_tools_result_none = None 
    # Or more accurately for schema: MagicMock(spec=mcp_types.ListToolsResult, tools=None)
    mock_list_tools_result_attr_none = MagicMock(spec=mcp_types.ListToolsResult)
    mock_list_tools_result_attr_none.tools = None

    results_to_test = [mock_list_tools_result_empty, mock_list_tools_result_none, mock_list_tools_result_attr_none]

    for list_tools_result_case in results_to_test:
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=list_tools_result_case)

        mock_client_session_cm = MagicMock()
        mock_client_session_cm.__aenter__.return_value = mock_session
        mock_client_session_cm.__aexit__ = AsyncMock()
        
        mock_http_client_cm = MagicMock()
        mock_http_client_cm.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_http_client_cm.__aexit__ = AsyncMock()

        with patch("aris.mcp_service.sse_client", return_value=mock_http_client_cm), \
             patch("aris.mcp_service.ClientSession", return_value=mock_client_session_cm) as mock_ClientSession_constructor:
            mock_ClientSession_constructor.return_value = mock_client_session_cm
            tools = await mcp_service.fetch_tools_schema()
            assert tools == []
            # Check log for successful fetch but 0 tools
            # This might require checking caplog if there's a specific log for this success case

@pytest.mark.asyncio
async def test_fetch_tools_schema_non_tool_object_in_list(mcp_service: MCPService, monkeypatch):
    if not MCP_SDK_AVAILABLE:
        pytest.skip("MCP SDK not available, skipping test for non-tool object")

    mock_valid_tool = MagicMock(spec=mcp_types.Tool)
    mock_valid_tool.model_dump.return_value = {"name": "valid_tool"}
    mock_invalid_item = {"not_a": "tool_object"} 

    mock_list_tools_result = MagicMock(spec=mcp_types.ListToolsResult)
    mock_list_tools_result.tools = [mock_valid_tool, mock_invalid_item]

    mock_session = AsyncMock(spec=ClientSession)
    mock_session.initialize = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=mock_list_tools_result)

    mock_client_session_cm = MagicMock()
    mock_client_session_cm.__aenter__.return_value = mock_session
    mock_client_session_cm.__aexit__ = AsyncMock()
    
    mock_http_client_cm = MagicMock()
    mock_http_client_cm.__aenter__.return_value = (AsyncMock(), AsyncMock())
    mock_http_client_cm.__aexit__ = AsyncMock()

    with patch("aris.mcp_service.sse_client", return_value=mock_http_client_cm), \
         patch("aris.mcp_service.ClientSession", return_value=mock_client_session_cm) as mock_ClientSession_constructor:
        mock_ClientSession_constructor.return_value = mock_client_session_cm
        tools = await mcp_service.fetch_tools_schema()
        
        assert len(tools) == 1
        assert tools[0]["name"] == "valid_tool"
        assert tools[0]["server_name"] == "aigentive"
        from aris import mcp_service as mcp_service_module
        # Check if the expected warning message was logged
        warning_message = f"MCPService: Encountered non-Tool object from HTTP server 'aigentive': {type(mock_invalid_item)}"
        
        # Get all call args of log_warning
        call_args_list = [call[0][0] for call in mcp_service_module.log_warning.call_args_list]
        
        # Check if the expected message is present
        assert warning_message in call_args_list 