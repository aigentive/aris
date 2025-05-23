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
    # Ensure we have our custom policy for macOS
    if sys.platform == 'darwin':
        current_policy = asyncio.get_event_loop_policy()
        if not hasattr(current_policy, '__class__') or 'MacOSAsyncioPolicy' not in str(type(current_policy)):
            # Our custom policy wasn't applied, let's set it now
            try:
                from asyncio import ThreadedChildWatcher
                
                class MacOSAsyncioPolicy(asyncio.DefaultEventLoopPolicy):
                    def get_child_watcher(self):
                        if not hasattr(self, '_watcher') or self._watcher is None:
                            self._watcher = ThreadedChildWatcher()
                        return self._watcher
                        
                    def set_child_watcher(self, watcher):
                        self._watcher = watcher
                
                asyncio.set_event_loop_policy(MacOSAsyncioPolicy())
            except ImportError:
                pass
    
    # Use the event loop policy to get a properly configured loop
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # On macOS, ensure the child watcher is properly set up
    if sys.platform == 'darwin':
        try:
            watcher = policy.get_child_watcher()
            if hasattr(watcher, 'attach_loop'):
                if not hasattr(watcher, '_loop') or watcher._loop is None:
                    watcher.attach_loop(loop)
        except Exception as e:
            # If we still have issues, something is wrong
            from .logging_utils import log_error
            log_error(f"Failed to set up child watcher: {e}")
            raise
    
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