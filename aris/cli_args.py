"""
Command-line argument parsing and configuration for ARIS.
"""
import argparse
import os
from pathlib import Path
import sys
from typing import Dict, Any

from dotenv import load_dotenv, find_dotenv

from .logging_utils import (
    configure_logging,
    log_router_activity,
    log_error,
    log_warning,
)

# Global variables for flags
INITIAL_VOICE_MODE = False
TRIGGER_WORDS = []
TEXT_MODE_TTS_ENABLED = False

# Parsed command-line arguments
PARSED_ARGS = None

def parse_arguments_and_configure_logging():
    """
    Parses CLI arguments and configures logging.
    
    Returns:
        The parsed arguments namespace
    """
    global INITIAL_VOICE_MODE, TRIGGER_WORDS, TEXT_MODE_TTS_ENABLED

    parser = argparse.ArgumentParser(description="ARIS: Amplified Reasoning & Intelligence Systems - Dynamic voice/text mode CLI.", add_help=True)
    parser.add_argument("--voice", action="store_true", help="Start in voice input/output mode.")
    parser.add_argument("--speak", action="store_true", help="Start with TTS enabled for text mode responses.")
    default_triggers = "claude,cloud,clod,clawd,clode,clause"
    parser.add_argument("--trigger-words", type=str, default=default_triggers, 
                        help=f"Comma-separated list of words that must appear in a spoken sentence to trigger processing (voice mode only). Default: '{default_triggers}'")
    parser.add_argument(
        "--verbose", 
        action="store_true", 
        help="Enable verbose logging to the console."
    )
    parser.add_argument(
        "--log-file", 
        type=str, 
        default="aris_run.log", 
        help="Path to the log file. Default: aris_run.log"
    )
    parser.add_argument(
        "--profile",
        type=str,
        help="Profile to use at startup. If not provided, the 'default' profile is activated."
    )
    parser.add_argument(
        "--no-profile-mcp-server",
        action="store_true",
        help="Disable the Profile MCP Server (enabled by default)"
    )
    parser.add_argument(
        "--profile-mcp-port",
        type=int,
        default=8092,
        help="Port for the Profile MCP Server (default: 8092)"
    )
    args, _ = parser.parse_known_args()

    absolute_log_file_path = Path(args.log_file).resolve()
    configure_logging(
        enable_console_logging=args.verbose,
        log_file_path=str(absolute_log_file_path)
    )

    # Clear the log file AFTER logging is configured and path is known
    try: 
        current_log_path = absolute_log_file_path
        current_log_path.write_text("") 
        log_router_activity(f"Log file '{str(current_log_path)}' cleared/initialized.")
    except Exception as e_clear_log:
        log_error(f"Could not clear/initialize log file '{str(current_log_path)}': {e_clear_log}")

    # Set global flags based on args
    if args.voice:
        INITIAL_VOICE_MODE = True
    if args.speak:
        TEXT_MODE_TTS_ENABLED = True
    TRIGGER_WORDS = [w.strip().lower() for w in args.trigger_words.split(',') if w.strip()]

    return args

def initialize_environment():
    """Initialize environment variables and logging."""
    global PARSED_ARGS
    
    # Load environment variables from .env file
    _ = load_dotenv(find_dotenv())
    
    # Parse arguments and configure logging
    PARSED_ARGS = parse_arguments_and_configure_logging()
    
    # Return parsed args for use by other modules
    return PARSED_ARGS