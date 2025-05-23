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
    
    # For macOS, set up ThreadedChildWatcher to avoid NotImplementedError
    try:
        from asyncio import ThreadedChildWatcher
        
        # Create a simple custom policy that always uses ThreadedChildWatcher
        class MacOSAsyncioPolicy(asyncio.DefaultEventLoopPolicy):
            def get_child_watcher(self):
                if not hasattr(self, '_watcher') or self._watcher is None:
                    self._watcher = ThreadedChildWatcher()
                return self._watcher
                
            def set_child_watcher(self, watcher):
                self._watcher = watcher
        
        # Set the custom policy GLOBALLY for all subprocess creation
        policy = MacOSAsyncioPolicy()
        asyncio.set_event_loop_policy(policy)
        
        # Also monkey-patch the asyncio.events module to always return our watcher
        import asyncio.events
        original_get_child_watcher = asyncio.events.get_child_watcher
        
        def patched_get_child_watcher():
            try:
                return original_get_child_watcher()
            except NotImplementedError:
                # Return our ThreadedChildWatcher as fallback
                if not hasattr(patched_get_child_watcher, '_fallback_watcher'):
                    patched_get_child_watcher._fallback_watcher = ThreadedChildWatcher()
                return patched_get_child_watcher._fallback_watcher
        
        asyncio.events.get_child_watcher = patched_get_child_watcher
        
    except ImportError:
        # Fallback for older Python versions
        pass

# Add imports for main components that should be available at the module level
from .cli import run_cli_orchestrator
from .cli_args import initialize_environment, PARSED_ARGS
from .session_state import SessionState, get_current_session_state, set_current_session_state
from .profile_manager import profile_manager