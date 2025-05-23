"""
Entry point for running ARIS as a module.
"""
import sys
import asyncio

from .cli_args import initialize_environment
from .cli import fully_initialize_app_components, run_cli_orchestrator

def main():
    """Main entry point for the CLI."""
    # Parse arguments and configure logging
    initialize_environment()
    
    # Set up event loop with custom exception handler to preserve signal handling
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Custom exception handler to prevent asyncio from swallowing exceptions
    def exception_handler(loop, context):
        exception = context.get('exception')
        if isinstance(exception, KeyboardInterrupt):
            raise exception
        else:
            # Default handler for other exceptions
            loop.default_exception_handler(context)
    
    loop.set_exception_handler(exception_handler)
    
    try:
        # Initialize components
        loop.run_until_complete(fully_initialize_app_components())
        
        # Run main orchestrator
        loop.run_until_complete(run_cli_orchestrator())
    except KeyboardInterrupt:
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import FormattedText
        from .cli import cli_style
        from .logging_utils import log_router_activity
        
        print_formatted_text(FormattedText([
            ("bold", "\nExiting ARIS via Ctrl+C...")
        ]), style=cli_style)
        log_router_activity("Chat session ended by KeyboardInterrupt.")
    finally:
        loop.close()

if __name__ == "__main__":
    main()