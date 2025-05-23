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

def configure_logging(enable_console_logging: bool, log_file_path: str = "aris_run.log"):
    """Configures logging behavior (console and file)."""
    global _CONSOLE_LOGGING_ENABLED, _LOG_FILE_PATH
    _CONSOLE_LOGGING_ENABLED = enable_console_logging
    _LOG_FILE_PATH = log_file_path # This should be an absolute path when called from cli.py
    
    timestamp = datetime.now().isoformat()
    console_status = "enabled" if _CONSOLE_LOGGING_ENABLED else "disabled"
    # This initial log should also go to stderr for visibility during debugging if file fails
    # init_log_message = f"{timestamp} [INFO] Logging configured by configure_logging. Console: {console_status}. Target Log File: {_LOG_FILE_PATH}"
    # print(f"[DEBUG_LOGGING_INIT] {init_log_message}", file=sys.stderr) # Removed
    try:
        with open(_LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} [INFO] Logging configured by configure_logging. Console: {console_status}. Target Log File: {_LOG_FILE_PATH}\n")
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