"""
ARIS module initialization.
"""
# Set up proper subprocess handling for macOS
import sys
import asyncio
import warnings

if sys.platform == 'darwin':
    # Suppress deprecation warnings for child watcher
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="asyncio")
    
    # For Python 3.8+, use the new subprocess creation method that doesn't require child watchers
    if hasattr(asyncio, 'create_subprocess_exec'):
        # Force use of ThreadedChildWatcher to avoid NotImplementedError
        from asyncio import ThreadedChildWatcher
        
        # Create a custom policy that always uses ThreadedChildWatcher
        class MacOSAsyncioPolicy(asyncio.DefaultEventLoopPolicy):
            def __init__(self):
                super().__init__()
                self._watcher = ThreadedChildWatcher()
                
            def get_child_watcher(self):
                return self._watcher
                
            def set_child_watcher(self, watcher):
                self._watcher = watcher
        
        # Set the custom policy
        asyncio.set_event_loop_policy(MacOSAsyncioPolicy())

# Add imports for main components that should be available at the module level
from .cli import run_cli_orchestrator
from .cli_args import initialize_environment, PARSED_ARGS
from .session_state import SessionState, get_current_session_state, set_current_session_state
from .profile_manager import profile_manager