"""
Entry point for running ARIS as a module.
"""
import asyncio
from .cli_args import initialize_environment
from .cli import fully_initialize_app_components, run_cli_orchestrator

def main():
    """Main entry point for the CLI."""
    # Parse arguments and configure logging
    initialize_environment()
    
    # Now, perform full application component initialization
    asyncio.run(fully_initialize_app_components())
    
    try:
        asyncio.run(run_cli_orchestrator())
    except KeyboardInterrupt:
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import FormattedText
        from .cli import cli_style
        from .logging_utils import log_router_activity
        
        print_formatted_text(FormattedText([
            ("bold", "\nExiting ARIS via Ctrl+C...")
        ]), style=cli_style)
        log_router_activity("Chat session ended by KeyboardInterrupt.")

if __name__ == "__main__":
    main()