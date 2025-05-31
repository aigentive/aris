import json
from datetime import datetime
import os # Added for path normalization if needed in future
import sys # Import sys for stderr printing

# print("[DEBUG_TRACE_IMPORT] TOP OF logging_utils.py", file=sys.stderr) # Removed

# ANSI escape codes for colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'
DIM = '\033[2m'

LOG_LEVELS = {
    "DEBUG": {"color": DIM, "prefix": "DEBUG"},
    "INFO": {"color": RESET, "prefix": "INFO"},
    "ROUTER_ACTIVITY": {"color": CYAN, "prefix": "ROUTER_ACTIVITY"},
    "TOOL_CALL": {"color": GREEN, "prefix": "TOOL_CALL"},
    "WARNING": {"color": YELLOW, "prefix": "WARNING"},
    "ERROR": {"color": RED, "prefix": "ERROR"},
    "USER_COMMAND_RAW_TEXT": {"color": RESET, "prefix": "USER_COMMAND_RAW_TEXT"}, # Console color is RESET (none)
    "USER_COMMAND_RAW_VOICE": {"color": RESET, "prefix": "USER_COMMAND_RAW_VOICE"}, # New level for voice input
    "LOGGING_ERROR": {"color": RED, "prefix": "LOGGING_ERROR"},
}

# --- Logging Configuration --- #
_CONSOLE_LOGGING_ENABLED = False
_LOG_FILE_PATH = "aris_run.log" # Default log file name

def create_timestamped_log_path(base_log_file: str = "aris_run.log", workspace_path: str = None) -> str:
    """
    Create a timestamped log file path with optional workspace support.
    
    Args:
        base_log_file: Base log file name or path
        workspace_path: Optional workspace path to create logs within
        
    Returns:
        str: Absolute path to timestamped log file
    """
    # Generate timestamp for filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Extract base name without extension
    if "." in base_log_file:
        name_part, ext_part = base_log_file.rsplit(".", 1)
        timestamped_filename = f"{name_part}_{timestamp}.{ext_part}"
    else:
        timestamped_filename = f"{base_log_file}_{timestamp}.log"
    
    # Determine logs directory location
    if workspace_path:
        # Create logs directory within workspace
        logs_dir = os.path.join(workspace_path, "logs")
    else:
        # Create logs directory in current working directory
        logs_dir = os.path.join(os.getcwd(), "logs")
    
    # Create logs directory if it doesn't exist
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except Exception as e:
        # Fallback to current directory if logs dir creation fails
        print(f"{RED}[LOGGING_ERROR] Failed to create logs directory {logs_dir}: {e}. Using current directory.{RESET}", file=sys.stderr)
        logs_dir = os.getcwd()
    
    # Return absolute path to timestamped log file
    log_file_path = os.path.join(logs_dir, timestamped_filename)
    return os.path.abspath(log_file_path)

def configure_logging(enable_console_logging: bool, log_file_path: str = "aris_run.log", workspace_path: str = None):
    """Configures logging behavior (console and file) with timestamped log files."""
    global _CONSOLE_LOGGING_ENABLED, _LOG_FILE_PATH
    _CONSOLE_LOGGING_ENABLED = enable_console_logging
    
    # Create timestamped log path
    _LOG_FILE_PATH = create_timestamped_log_path(log_file_path, workspace_path)
    
    timestamp = datetime.now().isoformat()
    console_status = "enabled" if _CONSOLE_LOGGING_ENABLED else "disabled"
    
    try:
        with open(_LOG_FILE_PATH, "w", encoding="utf-8") as f:  # Use 'w' to create new file
            f.write(f"{timestamp} [INFO] Logging configured by configure_logging. Console: {console_status}. Target Log File: {_LOG_FILE_PATH}\n")
            if workspace_path:
                f.write(f"{timestamp} [INFO] Workspace-aware logging enabled. Workspace: {workspace_path}\n")
    except Exception as e:
        print(f"{RED}{timestamp} [LOGGING_ERROR] INITIALIZATION: Failed to write to log file {_LOG_FILE_PATH}: {e}{RESET}", file=sys.stderr)

def _log_message(level_key: str, message: str, exception_info: str | None = None):
    """Internal generic logging function. Logs to file always, and to console if enabled."""
    timestamp = datetime.now().isoformat()
    log_level_config = LOG_LEVELS.get(level_key, {"color": RESET, "prefix": level_key})
    
    # --- Absolute crucial debug print to stderr --- #
    # print(f"[DEBUG_LOGGING_UTIL] _log_message trying to write to: {_LOG_FILE_PATH} (Level: {level_key})", file=sys.stderr) # Removed

    # 1. Prepare and write to log file (always, plain text)
    file_log_prefix = f"{timestamp} [{log_level_config['prefix']}]"
    file_log_message = f"{file_log_prefix} {message}"
    if exception_info:
        file_log_message += f"\n    Details: {exception_info}"

    try:
        with open(_LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(file_log_message + "\n")
    except Exception as e:
        # Fallback: If file logging fails, print a critical error to console regardless of verbosity.
        # These LOGGING_ERROR messages also go to stderr for max visibility
        print(f"{RED}{timestamp} [{LOG_LEVELS['LOGGING_ERROR']['prefix']}] Failed to write to log file {_LOG_FILE_PATH}: {e}{RESET}", file=sys.stderr)
        print(f"{RED}{timestamp} [{LOG_LEVELS['LOGGING_ERROR']['prefix']}] ORIGINAL MESSAGE ({log_level_config['prefix']}): {message}{RESET}", file=sys.stderr)
        if exception_info:
            print(f"{RED}{timestamp} [{LOG_LEVELS['LOGGING_ERROR']['prefix']}] ORIGINAL DETAILS: {exception_info}{RESET}", file=sys.stderr)

    # 2. Conditional console printing
    if _CONSOLE_LOGGING_ENABLED:
        console_prefix_for_print = f"{timestamp} [{log_level_config['prefix']}]"
        
        if level_key == "USER_COMMAND_RAW_TEXT":
            # USER_COMMAND_RAW_TEXT gets no special coloring for message, prefix is standard color.
            print(f"{log_level_config['color']}{console_prefix_for_print}{RESET} {message}")
        else:
            # Other levels: colorize prefix and message for console.
            colored_console_prefix = f"{log_level_config['color']}{console_prefix_for_print}{RESET}"
            print(f"{colored_console_prefix} {log_level_config['color']}{message}{RESET}")
            if exception_info:
                print(f"{log_level_config['color']}{DIM}    Details: {exception_info}{RESET}")

def log_router_activity(message: str):
    _log_message("ROUTER_ACTIVITY", message)

def log_tool_call(tool_name: str, tool_args: dict, tool_result: dict | str | None = None):
    args_str = json.dumps(tool_args)
    result_str = ""
    if tool_result is not None:
        if isinstance(tool_result, dict):
            result_str = f" -> Result: {json.dumps(tool_result)}"
        else: # Handle plain string results or other non-dict serializable results
            result_str = f" -> Result: {str(tool_result)}" # Truncate if too long? For now, no.
    _log_message("TOOL_CALL", f"Tool: {tool_name}, Args: {args_str}{result_str}")

def log_error(message: str, exception_info: str | None = None):
    _log_message("ERROR", message, exception_info)

def log_warning(message: str):
    _log_message("WARNING", message)

def log_debug(message: str): # Added for general debug purposes
    _log_message("DEBUG", message)

# Added a simple log_info for testing purposes in __main__
def log_info(message: str):
    _log_message("INFO", message) 

def log_user_command_raw_text(message: str):
    """Logs the raw user command text without additional color formatting for easier parsing."""
    _log_message("USER_COMMAND_RAW_TEXT", message)

def log_user_command_raw_voice(message: str):
    """Logs the raw user voice command text without additional color formatting for easier parsing."""
    _log_message("USER_COMMAND_RAW_VOICE", message)

def get_current_log_file_path() -> str:
    """Returns the current log file path."""
    return _LOG_FILE_PATH

# Example usage (optional, can be removed or kept for testing)
if __name__ == '__main__':
    # Test basic file logging (console disabled by default here)
    print(f"Testing logging. Default log file: {_LOG_FILE_PATH}")
    print("Run 1: Console logging OFF (default for this direct test)")
    log_info("Info message - file only.")
    log_warning("Warning message - file only.")
    log_user_command_raw_text("User command - file only.")

    # Test with console logging enabled
    print("\nRun 2: Enabling console logging.")
    configure_logging(enable_console_logging=True, log_file_path="test_aris_run.log")
    print(f"Console logging is now ON. Log file: {_LOG_FILE_PATH}")
    
    log_router_activity("Router is starting up...")
    log_tool_call("example_tool", {"param1": "value1"}, {"status": "success"})
    log_warning("This is a warning message.")
    log_error("This is an error message.", "SomeException: Details here.")
    log_debug("This is a debug message.")
    log_user_command_raw_text("This is exactly what the user typed with console out.")
    log_user_command_raw_voice("This is what the user said with console out.")
    print(f"\nCheck '{_LOG_FILE_PATH}' for log entries from both runs.")