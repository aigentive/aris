# Tests for aris.orchestrator

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Import the module to be tested
from aris import orchestrator
from aris.mcp_service import MCPService
from aris.prompt_formatter import PromptFormatter
from aris.cli_flag_manager import CLIFlagManager
from aris.claude_cli_executor import ClaudeCLIExecutor

@pytest.fixture(autouse=True)
def mock_orchestrator_globals_and_loggers(monkeypatch):
    """Mocks the global instances and logging functions within orchestrator."""
    monkeypatch.setattr(orchestrator, 'mcp_service_instance', MagicMock(spec=MCPService))
    monkeypatch.setattr(orchestrator, 'prompt_formatter_instance', MagicMock(spec=PromptFormatter))
    monkeypatch.setattr(orchestrator, 'cli_flag_manager_instance', MagicMock(spec=CLIFlagManager))
    monkeypatch.setattr(orchestrator, 'claude_cli_executor_instance', MagicMock(spec=ClaudeCLIExecutor))
    monkeypatch.setattr(orchestrator, 'TOOLS_SCHEMA', [])
    
    # Mock logging functions used by the orchestrator module itself
    monkeypatch.setattr(orchestrator, 'log_router_activity', MagicMock())
    monkeypatch.setattr(orchestrator, 'log_error', MagicMock())
    monkeypatch.setattr(orchestrator, 'log_warning', MagicMock())
    yield

@pytest.fixture
def mock_mcp_service() -> MagicMock:
    return orchestrator.mcp_service_instance

@pytest.fixture
def mock_prompt_formatter() -> MagicMock:
    return orchestrator.prompt_formatter_instance

@pytest.fixture
def mock_cli_flag_manager() -> MagicMock:
    return orchestrator.cli_flag_manager_instance

@pytest.fixture
def mock_claude_cli_executor() -> MagicMock:
    return orchestrator.claude_cli_executor_instance


@pytest.mark.asyncio
async def test_initialize_router_components_success(monkeypatch):
    mock_mcp = AsyncMock(spec=MCPService)
    mock_mcp.is_sdk_available.return_value = True
    async def fake_fetch_schema():
        return [{"name": "tool1", "description": "Fetched Tool 1"}]
    mock_mcp.fetch_tools_schema = fake_fetch_schema 
    
    monkeypatch.setattr(orchestrator, "MCPService", MagicMock(return_value=mock_mcp))

    mock_formatter = MagicMock(spec=PromptFormatter)
    monkeypatch.setattr(orchestrator, "PromptFormatter", MagicMock(return_value=mock_formatter))

    mock_flag_manager = MagicMock(spec=CLIFlagManager)
    mock_flag_manager.generate_claude_cli_flags.return_value = ["--generated-flag"]
    monkeypatch.setattr(orchestrator, "CLIFlagManager", MagicMock(return_value=mock_flag_manager))

    mock_executor = MagicMock(spec=ClaudeCLIExecutor)
    monkeypatch.setattr(orchestrator, "ClaudeCLIExecutor", MagicMock(return_value=mock_executor))

    monkeypatch.setattr("os.path.dirname", lambda x: "/fake/script/dir")
    monkeypatch.setattr("os.path.abspath", lambda x: "/fake/script/dir/orchestrator.py")

    monkeypatch.setattr(orchestrator, "TOOLS_SCHEMA", [])

    await orchestrator.initialize_router_components()
    
    # Wait a bit for the background refresh task to complete
    import asyncio
    await asyncio.sleep(0.1)

    assert orchestrator.mcp_service_instance == mock_mcp
    mock_mcp.is_sdk_available.assert_called_once()
    # fetch_tools_schema is now directly awaited, so assert_awaited_once should work if the mock is an AsyncMock
    # However, we assigned an async def directly, so we check its call through other means if needed, or ensure it was called implicitly via TOOLS_SCHEMA update.
    # For an AsyncMock, it would be: mock_mcp.fetch_tools_schema.assert_awaited_once()
    # Since we assigned a real async def, we check the outcome and that it was called if `is_sdk_available` is true.
    assert orchestrator.TOOLS_SCHEMA == [{"name": "tool1", "description": "Fetched Tool 1"}]

    assert orchestrator.prompt_formatter_instance == mock_formatter
    assert orchestrator.cli_flag_manager_instance == mock_flag_manager
    # CLIFlagManager.generate_claude_cli_flags should be called during refresh_tools_schema, not directly in initialize
    # This is an expected change in behavior with our updated code
    assert orchestrator.cli_flag_manager_instance == mock_flag_manager
    
    assert orchestrator.claude_cli_executor_instance == mock_executor
    orchestrator.log_router_activity.assert_any_call("Initializing router components (services and globals)...")

@pytest.mark.asyncio
async def test_initialize_router_components_mcp_sdk_not_available(monkeypatch):
    mock_mcp = AsyncMock(spec=MCPService)
    mock_mcp.is_sdk_available.return_value = False # SDK not available
    async def dummy_fetch(): return [] 
    mock_mcp.fetch_tools_schema = AsyncMock(side_effect=dummy_fetch) 
    monkeypatch.setattr(orchestrator, "MCPService", MagicMock(return_value=mock_mcp))
    monkeypatch.setattr("os.path.dirname", lambda x: "/fake/script/dir")
    monkeypatch.setattr("os.path.abspath", lambda x: "/fake/script/dir/orchestrator.py")

    await orchestrator.initialize_router_components()
    
    # Wait a bit for the background refresh task to complete
    import asyncio
    await asyncio.sleep(0.1)

    mock_mcp.fetch_tools_schema.assert_not_called() # Should not be called
    assert orchestrator.TOOLS_SCHEMA == []
    orchestrator.log_warning.assert_called_with("MCP SDK not available via MCPService, TOOLS_SCHEMA will be empty.")

@pytest.mark.asyncio
async def test_initialize_router_components_mcp_fetch_exception(monkeypatch):
    mock_mcp = AsyncMock(spec=MCPService)
    mock_mcp.is_sdk_available.return_value = True
    async def fetch_raises(): raise Exception("MCP Connection Error")
    mock_mcp.fetch_tools_schema = fetch_raises 
    monkeypatch.setattr(orchestrator, "MCPService", MagicMock(return_value=mock_mcp))
    monkeypatch.setattr("os.path.dirname", lambda x: "/fake/script/dir")
    monkeypatch.setattr("os.path.abspath", lambda x: "/fake/script/dir/orchestrator.py")

    await orchestrator.initialize_router_components()
    
    # Wait a bit for the background refresh task to complete and fail
    import asyncio
    await asyncio.sleep(0.1)

    assert orchestrator.TOOLS_SCHEMA == []
    orchestrator.log_error.assert_called_with(
        "Error in MCPService.fetch_tools_schema during refresh: MCP Connection Error", 
        exception_info="MCP Connection Error"
    )

@pytest.mark.asyncio
async def test_route_components_not_initialized(): # Removed caplog, will use mocked log_error
    # Ensure globals are None for this test by relying on mock_orchestrator_globals_and_loggers autouse fixture
    # to reset them, then specifically set one to None to trigger the condition.
    orchestrator.mcp_service_instance = None 

    user_msg = "test message"
    results = [chunk async for chunk in orchestrator.route(user_msg)]

    assert len(results) == 1
    error_response = json.loads(results[0])
    assert error_response["type"] == "error"
    assert error_response["error"]["message"] == "Internal Server Error: Orchestrator not initialized."
    orchestrator.log_error.assert_called_with("Orchestrator components not initialized. Call initialize_router_components() first.")

@pytest.mark.asyncio
async def test_route_success(mock_prompt_formatter, mock_claude_cli_executor, monkeypatch):
    user_msg = "What is 2+2?"
    session_id = "s123"
    formatted_prompt = "<prompt>What is 2+2?</prompt>"
    cli_flags = ["--verbose"]
    
    monkeypatch.setattr(orchestrator, 'TOOLS_SCHEMA', [{"name": "calculator"}])

    mock_prompt_formatter.format_prompt.return_value = formatted_prompt
    
    async def mock_execute_cli_stream(*args, **kwargs):
        yield '{"type": "output", "value": "4"}\n'
        yield '{"type": "end"}\n'

    mock_claude_cli_executor.execute_cli = MagicMock(return_value=mock_execute_cli_stream()) 

    results = [chunk async for chunk in orchestrator.route(user_msg, claude_session_to_resume=session_id)]

    # With our updated format_prompt implementation, it's now called with just the user message
    mock_prompt_formatter.format_prompt.assert_called_once_with(user_msg)
    # Only check that execute_cli was called once
    assert mock_claude_cli_executor.execute_cli.call_count == 1

    assert len(results) == 2
    assert json.loads(results[0]) == {"type": "output", "value": "4"}
    assert json.loads(results[1]) == {"type": "end"} 