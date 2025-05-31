"""
Session state management for ARIS.
"""
from typing import Optional, Dict, List

from .profile_manager import profile_manager
from .logging_utils import log_router_activity, log_warning

class SessionState:
    """Manages state for a CC-SO chat session, including profile configuration."""
    def __init__(self, session_id: str = None):
        self.session_id = session_id  # Only set if provided, otherwise None for new sessions
        self.active_profile = None  # The active profile configuration (resolved)
        self.profile_variables = {}  # Template variables for the active profile
        self.mcp_config_file = None  # Path to the merged MCP config file
        self.reference_file_path = None  # Path to referenced context file (if any)
        self.is_new_session = True  # Flag to indicate if this is a new session
        self.has_read_reference_file = False  # Flag to track if Claude has read the reference file
        self.workspace_path = None  # Current workspace path
        self.original_cwd = None  # Original working directory before workspace setup
        
        # MCP server state tracking
        self.workflow_mcp_server_started = False  # Track if workflow MCP server is running
        self.profile_mcp_server_started = False   # Track if profile MCP server is running
    
    def get_system_prompt(self) -> Optional[str]:
        """
        Gets the system prompt for the active profile with variables substituted and context files included.
        
        Returns:
            The fully processed system prompt, or None if no active profile
        """
        from .prompt_formatter import prompt_formatter_instance
        
        if not self.active_profile:
            return None
        
        # Get system prompt from profile
        system_prompt = self.active_profile.get("system_prompt")
        if not system_prompt and self.active_profile.get("system_prompt_file"):
            # Load system prompt from file
            system_prompt = profile_manager.load_file_content(
                self.active_profile["system_prompt_file"]
            )
        
        if not system_prompt:
            return None
        
        # Get context files from the active profile
        context_files = self.active_profile.get("context_files", [])
        
        # Get context mode from the active profile
        context_mode = self.active_profile.get("context_mode", "auto")
        
        # Process the system prompt with variables and context files
        processed_system_prompt, reference_file_path = prompt_formatter_instance.prepare_system_prompt(
            system_prompt, 
            context_files=context_files,
            template_variables=self.profile_variables,
            session_id=self.session_id,
            context_mode=context_mode,
            workspace_path=self.workspace_path,
            original_cwd=self.original_cwd
        )
        
        # Store reference file path for first message handling
        self.reference_file_path = reference_file_path
        
        return processed_system_prompt
    
    def get_tool_preferences(self) -> Optional[List[str]]:
        """
        Gets the tool preferences for the active profile.
        
        Returns:
            List of preferred tool names, or None if no active profile
        """
        if not self.active_profile:
            return None
        
        # Get tools from profile
        return self.active_profile.get("tools")
    
    def is_first_message(self) -> bool:
        """
        Checks if this is the first message in the session.
        Also marks the session as no longer new after checking.
        
        Returns:
            True if this is the first message, False otherwise
        """
        result = self.is_new_session
        self.is_new_session = False
        return result
    
    def clear_profile(self):
        """Clears the active profile and related state."""
        self.active_profile = None
        self.profile_variables = {}
        self.mcp_config_file = None
        self.reference_file_path = None
        # Don't reset is_new_session here to maintain proper session behavior
        self.has_read_reference_file = False


# Global session state reference
current_session_state = None

def get_current_session_state() -> Optional[SessionState]:
    """
    Returns the current session state object.
    
    Returns:
        The current SessionState object or None if not available
    """
    global current_session_state
    return current_session_state

def set_current_session_state(session_state: SessionState):
    """
    Sets the current session state object.
    
    Args:
        session_state: The SessionState object to set as current
    """
    global current_session_state
    current_session_state = session_state