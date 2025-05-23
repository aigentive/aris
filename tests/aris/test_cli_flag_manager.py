# Tests for aris.cli_flag_manager

import pytest
import os
from pathlib import Path
from aris.cli_flag_manager import CLIFlagManager
from unittest.mock import patch, MagicMock

@pytest.fixture
def flag_manager(tmp_path: Path) -> CLIFlagManager:
    # Using tmp_path as the script_dir for consistent .mcp.json lookup during tests
    return CLIFlagManager(script_dir_path=str(tmp_path))

@pytest.fixture
def create_mcp_json(tmp_path: Path):
    """Helper fixture to create a dummy .mcp.json file in the temp script_dir."""
    mcp_json_path = tmp_path / ".mcp.json"
    mcp_json_path.write_text('{"some_config": "value"}')
    return mcp_json_path

def test_generate_claude_cli_flags_basic_flags(flag_manager: CLIFlagManager, create_mcp_json):
    flags = flag_manager.generate_claude_cli_flags([])
    
    assert flag_manager.OUTPUT_FORMAT_FLAG in flags
    assert flag_manager.OUTPUT_FORMAT_VALUE in flags
    assert flag_manager.VERBOSE_FLAG in flags
    assert flag_manager.MAX_TURNS_FLAG in flags
    assert flag_manager.MAX_TURNS_VALUE in flags
    
    # MCP_CONFIG_FLAG is no longer included by default when _get_mcp_config_path returns None
    assert flag_manager.MCP_CONFIG_FLAG not in flags
    
    # Test with explicit MCP config path
    flags_with_config = flag_manager.generate_claude_cli_flags([], mcp_config_path=str(create_mcp_json))
    assert flag_manager.MCP_CONFIG_FLAG in flags_with_config
    mcp_config_flag_index = flags_with_config.index(flag_manager.MCP_CONFIG_FLAG)
    assert flags_with_config[mcp_config_flag_index + 1] == str(create_mcp_json)

def test_generate_allowed_tools_mcp_only(flag_manager: CLIFlagManager, create_mcp_json):
    mcp_schema = [
        {"name": "mcp_tool_one"},
        {"name": "mcp_tool_two"}
    ]
    # Override USER_DESIRED_NON_MCP_TOOLS for this specific test case
    original_user_tools = CLIFlagManager.USER_DESIRED_NON_MCP_TOOLS
    CLIFlagManager.USER_DESIRED_NON_MCP_TOOLS = []

    flags = flag_manager.generate_claude_cli_flags(mcp_schema)
    
    CLIFlagManager.USER_DESIRED_NON_MCP_TOOLS = original_user_tools # Restore

    assert flag_manager.ALLOWED_TOOLS_FLAG in flags
    allowed_tools_index = flags.index(flag_manager.ALLOWED_TOOLS_FLAG)
    tools_string = flags[allowed_tools_index + 1]
    
    # Use the new format string with default server name
    mcp_prefix = flag_manager.MCP_SERVER_PREFIX_FORMAT.format(server_name="aigentive")
    expected_tools = sorted([
        f"{mcp_prefix}mcp_tool_one",
        f"{mcp_prefix}mcp_tool_two"
    ])
    assert tools_string == ",".join(expected_tools)

def test_generate_allowed_tools_user_desired_only(flag_manager: CLIFlagManager, monkeypatch, create_mcp_json):
    # Use monkeypatch to temporarily modify class variable for this test
    monkeypatch.setattr(CLIFlagManager, 'USER_DESIRED_NON_MCP_TOOLS', ["UserTool1", "UserTool2"])
    
    flags = flag_manager.generate_claude_cli_flags([]) # No MCP tools
        
    assert flag_manager.ALLOWED_TOOLS_FLAG in flags
    allowed_tools_index = flags.index(flag_manager.ALLOWED_TOOLS_FLAG)
    tools_string = flags[allowed_tools_index + 1]
    
    expected_tools = sorted(["UserTool1", "UserTool2"])
    assert tools_string == ",".join(expected_tools)

def test_generate_allowed_tools_mixed_mcp_and_user(flag_manager: CLIFlagManager, monkeypatch, create_mcp_json):
    mcp_schema = [
        {"name": "mcp_main"}
    ]
    monkeypatch.setattr(CLIFlagManager, 'USER_DESIRED_NON_MCP_TOOLS', ["UserHelper", "WebSearch"])
    
    flags = flag_manager.generate_claude_cli_flags(mcp_schema)
    
    assert flag_manager.ALLOWED_TOOLS_FLAG in flags
    allowed_tools_index = flags.index(flag_manager.ALLOWED_TOOLS_FLAG)
    tools_string = flags[allowed_tools_index + 1]
    
    # Use the new format string with default server name
    mcp_prefix = flag_manager.MCP_SERVER_PREFIX_FORMAT.format(server_name="aigentive")
    expected_tools = sorted([
        f"{mcp_prefix}mcp_main",
        "UserHelper",
        "WebSearch"
    ])
    assert tools_string == ",".join(expected_tools)

def test_generate_allowed_tools_no_mcp_no_user(flag_manager: CLIFlagManager, monkeypatch, create_mcp_json):
    monkeypatch.setattr(CLIFlagManager, 'USER_DESIRED_NON_MCP_TOOLS', [])
    flags = flag_manager.generate_claude_cli_flags([])
    
    # --allowedTools flag should not be present if no tools are found
    assert flag_manager.ALLOWED_TOOLS_FLAG not in flags

def test_generate_allowed_tools_duplicates_handled(flag_manager: CLIFlagManager, monkeypatch, create_mcp_json):
    # Case where a user tool might coincidentally have the same name (after prefixing) as an MCP tool
    # The MCP tool (prefixed) should take precedence / be the one listed.
    # And also general non-MCP tools.
    mcp_schema = [
        {"name": "user_tool"} # This will become "mcp__aigentive__user_tool"
    ]
    monkeypatch.setattr(CLIFlagManager, 'USER_DESIRED_NON_MCP_TOOLS', ["user_tool", "another_tool"])
    
    flags = flag_manager.generate_claude_cli_flags(mcp_schema)
    
    assert flag_manager.ALLOWED_TOOLS_FLAG in flags
    allowed_tools_index = flags.index(flag_manager.ALLOWED_TOOLS_FLAG)
    tools_string = flags[allowed_tools_index + 1]
    
    # Expected: MCP prefixed version, and the other distinct user tool.
    # The unprefixed "user_tool" from USER_DESIRED_NON_MCP_TOOLS should not be added again if its prefixed mcp version exists.
    # But if it does not conflict with an MCP name, it should be added.
    # Logic: MCP tools are added. Then, iterate user tools: if mcp_prefix + user_tool is NOT in the set, add user_tool.
    # So, `mcp__aigentive__user_tool` is added from MCP. 
    # Then, `user_tool`: `mcp__aigentive__user_tool` IS in the set, so `user_tool` (unprefixed) is NOT added.
    # Then, `another_tool`: `mcp__aigentive__another_tool` is NOT in the set, so `another_tool` (unprefixed) IS added.
    # Use the new format string with default server name
    mcp_prefix = flag_manager.MCP_SERVER_PREFIX_FORMAT.format(server_name="aigentive")
    expected_tools = sorted([
        f"{mcp_prefix}user_tool", 
        "another_tool"
    ])
    assert tools_string == ",".join(expected_tools)

@patch("aris.cli_flag_manager.log_router_activity") # Mock log_router_activity
def test_mcp_config_path_resolution_no_file(mock_log_router_activity: MagicMock, flag_manager: CLIFlagManager, tmp_path: Path):
    # flag_manager is initialized with tmp_path
    flags = flag_manager.generate_claude_cli_flags([])
    
    # MCP_CONFIG_FLAG should not be in flags when _get_mcp_config_path returns None
    assert flag_manager.MCP_CONFIG_FLAG not in flags
    
    # Verify log message
    mock_log_router_activity.assert_any_call(f"CLIFlagManager: No MCP config path provided, skipping {flag_manager.MCP_CONFIG_FLAG}")

def test_init_with_no_script_dir_path(monkeypatch):
    """Test that if no script_dir_path is given, it defaults to this file's dir."""
    fake_module_file_path = "/fake/module/path/cli_flag_manager.py"
    expected_script_dir = "/fake/module/path"

    # Mock os.path.abspath to return our fake path when __file__ (from within CLIFlagManager) is passed.
    # We need to capture the actual __file__ value that os.path.abspath would receive.
    # Patching abspath and dirname more broadly for this specific instantiation.
    
    original_abspath = os.path.abspath
    original_dirname = os.path.dirname

    def mock_abspath(path):
        # This mock assumes that when CLIFlagManager calls abspath(__file__),
        # __file__ points to the aris package cli_flag_manager.py
        # or the direct name 'cli_flag_manager.py' if it's in the path.
        # The goal is to make it return our fake_module_file_path for that specific call.
        # For simplicity in this mock, we'll make it always return the fake path
        # if called from within the CLIFlagManager instantiation context.
        # A more robust mock would inspect `path` if needed.
        return fake_module_file_path

    def mock_dirname(path):
        if path == fake_module_file_path:
            return expected_script_dir
        return original_dirname(path) # Fallback for other dirname calls

    monkeypatch.setattr(os.path, "abspath", mock_abspath)
    monkeypatch.setattr(os.path, "dirname", mock_dirname)

    manager = CLIFlagManager() # Initialize without script_dir_path
    
    # Restore original functions to avoid affecting other tests or fixtures
    monkeypatch.setattr(os.path, "abspath", original_abspath)
    monkeypatch.setattr(os.path, "dirname", original_dirname)

    assert manager.script_dir == expected_script_dir 