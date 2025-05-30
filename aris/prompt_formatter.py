import re
import os
import uuid
from typing import List, Dict, Optional, Tuple, Any

from .logging_utils import log_router_activity, log_warning, log_error, log_debug
from .context_file_manager import context_file_manager

class PromptFormatter:
    """
    Handles prompt formatting for ARIS, including system prompts,
    context file integration, and variable substitution.
    """
    
    # Template for user message
    PROMPT_TEMPLATE = """
<current_user_message_for_this_turn>
{current_turn_message_placeholder}
</current_user_message_for_this_turn>
"""

    def __init__(self):
        """Initialize the prompt formatter."""
        log_debug("PromptFormatter: Initialized")
    
    def format_prompt(self, current_turn_msg: str) -> str:
        """
        Formats a prompt with just the user message.
        
        In line with the PRD requirements, this method only handles the user message.
        Tools schema and system prompts are handled separately (tools schema via 
        orchestrator.py and system prompts via CLI flags).
        
        Args:
            current_turn_msg: The user's message for the current turn
        
        Returns:
            Formatted prompt string containing only the user message
        """
        return self.PROMPT_TEMPLATE.format(
            current_turn_message_placeholder=current_turn_msg
        )
    
    def prepare_system_prompt(
        self, 
        profile_system_prompt: str, 
        context_files: List[str] = None, 
        template_variables: Dict[str, str] = None,
        session_id: str = None,
        context_mode: str = "auto",
        context_size_threshold: int = 10240,  # 10KB threshold for auto mode
        workspace_path: str = None,  # Optional workspace path for enhancement
        original_cwd: str = None  # Original working directory for comparison
    ) -> Tuple[str, Optional[str]]:
        """
        Prepares the system prompt from a profile by:
        1. Replacing template variables 
        2. Integrating content from context files
        3. Adding workspace context if applicable
        4. Formatting it for use with the Claude CLI's --system-prompt flag
        
        Args:
            profile_system_prompt: The system prompt from the active profile
            context_files: Optional list of paths to context files to include
            template_variables: A dictionary of variable names to values for replacement
            session_id: Optional session ID for reference file naming
            context_mode: How to handle context files: 'embedded', 'referenced', or 'auto'
            context_size_threshold: Size threshold in bytes for auto mode selection
            workspace_path: Optional workspace path for workspace context enhancement
            original_cwd: Original working directory for workspace comparison
        
        Returns:
            Tuple of (processed_system_prompt, reference_file_path)
            reference_file_path will be None if not using referenced mode
        """
        if not profile_system_prompt:
            log_warning("PromptFormatter: Empty system prompt provided")
            return "", None
        
        processed_prompt = profile_system_prompt
        reference_file_path = None
        
        # Replace template variables if provided
        if template_variables:
            for var_name, var_value in template_variables.items():
                placeholder = f"{{{{{var_name}}}}}"
                processed_prompt = processed_prompt.replace(placeholder, var_value)
        
        # Check for any remaining unsubstituted variables
        remaining_vars = re.findall(r'{{(.*?)}}', processed_prompt)
        filtered_vars = [v for v in remaining_vars if not v.startswith('parent:') and v != 'parent_system_prompt']
        if filtered_vars:
            log_warning(f"PromptFormatter: Unsubstituted variables in system prompt: {filtered_vars}")
        
        # Handle context files
        if context_files and len(context_files) > 0:
            # Determine which mode to use
            effective_mode = context_mode
            if context_mode == "auto":
                # Estimate the size of context content
                total_context_size = context_file_manager.estimate_context_size(context_files)
                log_debug(f"PromptFormatter: Total context size is {total_context_size} bytes")
                
                # Use referenced mode if context is large
                effective_mode = "referenced" if total_context_size > context_size_threshold else "embedded"
                log_debug(f"PromptFormatter: Auto mode selected '{effective_mode}' based on context size")
            
            if effective_mode == "embedded":
                # Original approach: Embed context directly in system prompt
                context_content = context_file_manager.prepare_embedded_context(context_files)
                processed_prompt += "\n\nReference materials:\n" + context_content
                log_debug("PromptFormatter: Using embedded mode for context files")
            else:
                # New approach: Generate a consolidated file and add reference instruction
                session_id_for_file = session_id or str(uuid.uuid4())
                reference_file_path = context_file_manager.generate_context_file(
                    context_files, 
                    session_id_for_file
                )
                
                # Add instruction to read the file
                read_instruction = f"""
IMPORTANT: At the beginning of this session, you MUST read the reference file at:
{reference_file_path}

This file contains essential context and documentation required for this conversation.
Use the Read tool to access this file before responding to any user query.
"""
                processed_prompt += "\n\n" + read_instruction
                log_debug(f"PromptFormatter: Using referenced mode, created file at {reference_file_path}")
        
        # Add workspace context if workspace path is provided and different from original directory
        if workspace_path and original_cwd and workspace_path != original_cwd:
            workspace_context = f"""

## Workspace Information
Your workspace directory is: {workspace_path}
Use this workspace for reading previous work and saving your outputs.
When referencing files, you can use relative paths from your workspace.
"""
            processed_prompt += workspace_context
            log_debug(f"PromptFormatter: Added workspace context for: {workspace_path}")
        
        return processed_prompt, reference_file_path
    
    def modify_first_message(self, user_msg: str, reference_file_path: str) -> str:
        """
        Modify the first message in a session to instruct Claude to read the reference file.
        
        Args:
            user_msg: The original user message
            reference_file_path: Path to the reference file
        
        Returns:
            Modified user message with instruction to read the reference file
        """
        if not reference_file_path:
            return user_msg
        
        modified_msg = (
            f"Before addressing my request, please use the Read tool to read the reference file at {reference_file_path} "
            f"which contains important context for our conversation.\n\nAfter reading that file, please respond to: {user_msg}"
        )
        
        log_debug(f"PromptFormatter: Modified first message to include reference file instruction")
        return modified_msg
        
# Create an instance of the PromptFormatter class for use by other modules
prompt_formatter_instance = PromptFormatter()