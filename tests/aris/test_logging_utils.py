# Tests for aris.logging_utils

import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any

import pytest
from freezegun import freeze_time

# Assuming logging_utils is a sibling module or correctly in PYTHONPATH for direct import
# For testing, it's often easier to add the parent directory of the module to sys.path
# or ensure your test runner handles it.
# For this example, we'll assume it can be imported if tests are run from the correct root
# with `backend` in PYTHONPATH or using `python -m pytest ...` from project root.
from aris import logging_utils

# Helper to strip ANSI escape codes
ANSI_ESCAPE_PATTERN = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_PATTERN.sub('', text)

@pytest.fixture(autouse=True)
def reset_logging_globals(monkeypatch):
    """Resets logging_utils globals before each test to ensure isolation."""
    monkeypatch.setattr(logging_utils, '_CONSOLE_LOGGING_ENABLED', False)
    monkeypatch.setattr(logging_utils, '_LOG_FILE_PATH', "test_temp_aris_run.log")
    # Clean up the log file if it exists from a previous run before tests
    if Path(logging_utils._LOG_FILE_PATH).exists():
        Path(logging_utils._LOG_FILE_PATH).unlink()
    yield
    # Clean up the log file after tests
    if Path(logging_utils._LOG_FILE_PATH).exists():
        Path(logging_utils._LOG_FILE_PATH).unlink()

@pytest.fixture
def temp_log_file(tmp_path: Path) -> Path:
    log_file = tmp_path / "test_aris_run.log"
    # Ensure logging_utils uses this path for the duration of the test
    logging_utils.configure_logging(enable_console_logging=False, log_file_path=str(log_file))
    return log_file

@freeze_time("2023-01-01 12:00:00")
def test_configure_logging(tmp_path: Path, capsys):
    log_file_path = tmp_path / "custom_config.log"
    
    logging_utils.configure_logging(enable_console_logging=True, log_file_path=str(log_file_path))
    
    assert logging_utils._CONSOLE_LOGGING_ENABLED is True
    assert logging_utils._LOG_FILE_PATH == str(log_file_path)
    
    # Check if the initial configuration message was written to the file
    assert log_file_path.exists()
    content = log_file_path.read_text()
    expected_log_init_msg = f"2023-01-01T12:00:00 [INFO] Logging configured by configure_logging. Console: enabled. Target Log File: {str(log_file_path)}"
    assert expected_log_init_msg in content

@freeze_time("2023-01-15 10:30:00")
@pytest.mark.parametrize(
    "log_function_name, level_key, message_args, expected_file_content, expected_console_prefix, include_details",
    [
        ("log_router_activity", "ROUTER_ACTIVITY", ["Router started"], "2023-01-15T10:30:00 [ROUTER_ACTIVITY] Router started", "[ROUTER_ACTIVITY]", False),
        ("log_warning", "WARNING", ["Cache miss"], "2023-01-15T10:30:00 [WARNING] Cache miss", "[WARNING]", False),
        ("log_debug", "DEBUG", ["Variable x=5"], "2023-01-15T10:30:00 [DEBUG] Variable x=5", "[DEBUG]", False),
        ("log_info", "INFO", ["Processing item 1"], "2023-01-15T10:30:00 [INFO] Processing item 1", "[INFO]", False),
        ("log_error", "ERROR", ["File not found", "IOError: Details"], "2023-01-15T10:30:00 [ERROR] File not found\n    Details: IOError: Details", "[ERROR]", True),
        ("log_tool_call", "TOOL_CALL", ["my_tool", {"arg": "val"}, {"res": "ok"}], '2023-01-15T10:30:00 [TOOL_CALL] Tool: my_tool, Args: {"arg": "val"} -> Result: {"res": "ok"}', "[TOOL_CALL]", False),
        ("log_tool_call", "TOOL_CALL", ["another_tool", {"input": 1}], '2023-01-15T10:30:00 [TOOL_CALL] Tool: another_tool, Args: {"input": 1}', "[TOOL_CALL]", False), # No result
        ("log_user_command_raw_text", "USER_COMMAND_RAW_TEXT", ["User typed this"], "2023-01-15T10:30:00 [USER_COMMAND_RAW_TEXT] User typed this", "[USER_COMMAND_RAW_TEXT]", False),
        ("log_user_command_raw_voice", "USER_COMMAND_RAW_VOICE", ["User said that"], "2023-01-15T10:30:00 [USER_COMMAND_RAW_VOICE] User said that", "[USER_COMMAND_RAW_VOICE]", False),
    ]
)
def test_log_functions_file_and_console(temp_log_file: Path, capsys, log_function_name, level_key, message_args, expected_file_content, expected_console_prefix, include_details):
    # Test file logging (always on)
    log_func = getattr(logging_utils, log_function_name)
    log_func(*message_args)
    
    file_content = temp_log_file.read_text()
    assert expected_file_content in file_content

    # Test console logging (when enabled)
    logging_utils.configure_logging(enable_console_logging=True, log_file_path=str(temp_log_file))
    log_func(*message_args) # Call again to capture console output
    
    captured = capsys.readouterr()
    console_output = strip_ansi(captured.out)
    
    # Construct expected console message parts
    # The message part itself might be colored differently or not, depending on the level_key
    # For USER_COMMAND_RAW_TEXT, the message is not colored with the prefix color.
    main_message_content = message_args[0] if log_function_name != "log_tool_call" else f'Tool: {message_args[0]}, Args: {logging_utils.json.dumps(message_args[1])}'
    if log_function_name == "log_tool_call" and len(message_args) > 2 and message_args[2] is not None:
        result_part = message_args[2]
        if isinstance(result_part, dict):
            main_message_content += f' -> Result: {logging_utils.json.dumps(result_part)}'
        else:
            main_message_content += f" -> Result: {str(result_part)}"
            
    expected_console_msg_part1 = f"2023-01-15T10:30:00 {expected_console_prefix} {main_message_content}"
    assert expected_console_msg_part1 in console_output

    if include_details and len(message_args) > 1 and message_args[1] is not None:
        details_content = message_args[1] if log_function_name == "log_error" else message_args[2] # Crude, adjust if more complex cases
        expected_console_details = f"Details: {details_content}"
        assert expected_console_details in console_output

def test_console_logging_disabled(temp_log_file: Path, capsys):
    logging_utils.configure_logging(enable_console_logging=False, log_file_path=str(temp_log_file))
    logging_utils.log_info("This should not appear on console")
    captured = capsys.readouterr()
    assert "This should not appear on console" not in captured.out
    assert "This should not appear on console" not in captured.err
    
    # But it should be in the file
    file_content = temp_log_file.read_text()
    assert "This should not appear on console" in file_content

@freeze_time("2023-02-01 11:00:00")
def test_logging_to_unwritable_file(capsys, monkeypatch):
    unwritable_path = "/this/path/should/not/be/writable/test_log.log"
    
    # Mock open to raise an exception
    def mock_open_raiser(*args, **kwargs):
        raise OSError("Permission denied")
    
    monkeypatch.setattr("builtins.open", mock_open_raiser)
    
    # Must configure first, even if it fails, to set the path
    logging_utils.configure_logging(enable_console_logging=True, log_file_path=unwritable_path)
    
    # Attempt a log operation
    logging_utils.log_warning("A test warning")
    
    captured = capsys.readouterr()
    stderr_output = strip_ansi(captured.err)
    
    # Check for key parts of the error messages
    # Expected: 1. Initialization failure message, 2. Regular log failure message, 3. Original message log
    assert f"[LOGGING_ERROR] INITIALIZATION: Failed to write to log file {unwritable_path}" in stderr_output
    # Check error message more flexibly since the exact format might vary by platform
    assert "Permission denied" in stderr_output # This is part of both messages
    assert f"[LOGGING_ERROR] Failed to write to log file {unwritable_path}" in stderr_output # From the second attempt
    assert "[LOGGING_ERROR] ORIGINAL MESSAGE (WARNING): A test warning" in stderr_output

@freeze_time("2023-02-01 11:30:00")
def test_initial_configure_logging_fails_to_write(capsys, monkeypatch, tmp_path):
    # Use a real path that we will make temporarily unwritable for the config write itself
    log_file = tmp_path / "init_fail_test.log"

    def mock_open_for_config_fail(file, mode, encoding):
        if file == str(log_file) and mode == 'a': # Target the specific initial write
            raise OSError("Cannot write initial config")
        return open(file, mode, encoding=encoding) # Allow other opens (like for reading if any)
    
    monkeypatch.setattr("builtins.open", mock_open_for_config_fail)

    logging_utils.configure_logging(enable_console_logging=True, log_file_path=str(log_file))

    captured = capsys.readouterr()
    stderr_output = strip_ansi(captured.err)
    # Check for key parts
    assert f"[LOGGING_ERROR] INITIALIZATION: Failed to write to log file {str(log_file)}" in stderr_output
    # Check error message more flexibly since the exact format might vary by platform
    assert "Cannot write initial config" in stderr_output 