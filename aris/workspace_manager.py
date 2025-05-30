"""
Workspace management utilities for ARIS.
"""
import os
from typing import Optional, Tuple
from .logging_utils import log_router_activity, log_debug, log_warning, log_error


class WorkspaceManager:
    """
    Manages workspace setup, path resolution, and directory management for ARIS.
    """
    
    def __init__(self):
        self.original_cwd: Optional[str] = None
        self.current_workspace: Optional[str] = None
    
    def resolve_workspace_path(self, workspace_arg: Optional[str]) -> str:
        """
        Resolve workspace argument to absolute path.
        
        Args:
            workspace_arg: CLI workspace argument (None, relative, or absolute path)
            
        Returns:
            str: Resolved absolute workspace path
        """
        if workspace_arg is None:
            workspace_path = os.getcwd()
            log_debug(f"WorkspaceManager: No workspace specified, using current directory: {workspace_path}")
            return workspace_path
        
        if os.path.isabs(workspace_arg):
            workspace_path = workspace_arg
            log_debug(f"WorkspaceManager: Using absolute workspace path: {workspace_path}")
        else:
            workspace_path = os.path.join(os.getcwd(), workspace_arg)
            log_debug(f"WorkspaceManager: Resolved relative workspace path to: {workspace_path}")
        
        return workspace_path
    
    def setup_workspace(self, workspace_path: str) -> str:
        """
        Create workspace directory and change to it.
        
        Args:
            workspace_path: Resolved workspace path
            
        Returns:
            str: Original working directory for restoration
        """
        # Store original directory
        original_cwd = os.getcwd()
        
        try:
            # Create workspace if it doesn't exist
            if not os.path.exists(workspace_path):
                os.makedirs(workspace_path, exist_ok=True)
                log_router_activity(f"WorkspaceManager: Created workspace directory: {workspace_path}")
            else:
                log_debug(f"WorkspaceManager: Using existing workspace directory: {workspace_path}")
            
            # Change to workspace directory
            os.chdir(workspace_path)
            log_router_activity(f"WorkspaceManager: Changed to workspace directory: {workspace_path}")
            
            # Store workspace state
            self.original_cwd = original_cwd
            self.current_workspace = workspace_path
            
            return original_cwd
        except OSError as e:
            log_error(f"WorkspaceManager: Failed to create or access workspace '{workspace_path}': {e}")
            raise
        except Exception as e:
            log_error(f"WorkspaceManager: Unexpected error setting up workspace '{workspace_path}': {e}")
            raise
    
    def restore_original_directory(self):
        """
        Restore the original working directory.
        """
        if self.original_cwd and os.path.exists(self.original_cwd):
            try:
                os.chdir(self.original_cwd)
                log_debug(f"WorkspaceManager: Restored original directory: {self.original_cwd}")
                self.current_workspace = None
            except Exception as e:
                log_warning(f"WorkspaceManager: Failed to restore original directory '{self.original_cwd}': {e}")
        else:
            log_debug("WorkspaceManager: No original directory to restore or directory no longer exists")
    
    def get_workspace_variables(self, workspace_path: str) -> dict:
        """
        Generate workspace variables for template substitution.
        
        Args:
            workspace_path: Current workspace path
            
        Returns:
            dict: Workspace variables for template substitution
        """
        workspace_name = os.path.basename(workspace_path)
        
        variables = {
            'workspace': workspace_path,
            'workspace_name': workspace_name
        }
        
        log_debug(f"WorkspaceManager: Generated workspace variables: {variables}")
        return variables
    
    def enhance_system_prompt_with_workspace(self, system_prompt: str, workspace_path: str) -> str:
        """
        Add workspace context to system prompt if workspace is different from original CWD.
        
        Args:
            system_prompt: Original system prompt
            workspace_path: Current workspace path
            
        Returns:
            str: Enhanced system prompt with workspace context
        """
        # Only add workspace context if we've changed directories
        if self.original_cwd and workspace_path != self.original_cwd:
            workspace_context = f"""

## Workspace Information
Your workspace directory is: {workspace_path}
Use this workspace for reading previous work and saving your outputs.
When referencing files, you can use relative paths from your workspace.
"""
            enhanced_prompt = system_prompt + workspace_context
            log_debug(f"WorkspaceManager: Enhanced system prompt with workspace context")
            return enhanced_prompt
        
        return system_prompt
    
    def get_current_workspace_info(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get current workspace information.
        
        Returns:
            Tuple of (current_workspace_path, original_cwd)
        """
        return self.current_workspace, self.original_cwd


# Global workspace manager instance
workspace_manager = WorkspaceManager()