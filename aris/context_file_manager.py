import os
import re
import uuid
import time
import hashlib
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from .logging_utils import log_router_activity, log_error, log_warning, log_debug

class ContextFileManager:
    """Manages consolidated context files for optimized token usage."""
    
    def __init__(self, base_temp_dir: str = None):
        """
        Initialize the context file manager.
        
        Args:
            base_temp_dir: Directory for temporary context files. If None, uses the system temp directory.
        """
        if base_temp_dir:
            self.base_temp_dir = base_temp_dir
        else:
            import tempfile
            self.base_temp_dir = os.path.join(tempfile.gettempdir(), "cc_so_context")
        
        os.makedirs(self.base_temp_dir, exist_ok=True)
        self.temp_files = {}  # Maps context hash -> temp file path
        log_debug(f"ContextFileManager: Initialized with temp directory: {self.base_temp_dir}")
    
    def _generate_context_hash(self, context_files: List[str]) -> str:
        """
        Generate a hash of the context files and their modification times.
        
        Args:
            context_files: List of paths to context files
        
        Returns:
            A hash string representing the files and their current state
        """
        # Combine filenames and mod times to detect changes
        hash_input = []
        for file_path in context_files:
            if os.path.exists(file_path):
                mod_time = os.path.getmtime(file_path)
                file_size = os.path.getsize(file_path)
                hash_input.append(f"{file_path}:{mod_time}:{file_size}")
        
        # Generate a hash for this combination
        hasher = hashlib.md5()
        hasher.update(";".join(hash_input).encode('utf-8'))
        return hasher.hexdigest()
    
    def generate_context_file(self, context_files: List[str], session_id: str) -> str:
        """
        Generates a consolidated context file from multiple source files.
        
        Args:
            context_files: List of paths to context files
            session_id: Unique ID for the current session
        
        Returns:
            Path to the generated context file
        """
        # Generate a hash of the context files and their modification times
        context_hash = self._generate_context_hash(context_files)
        
        # Check if we already have a temp file for this context combination
        if context_hash in self.temp_files and os.path.exists(self.temp_files[context_hash]):
            log_debug(f"ContextFileManager: Using cached context file: {self.temp_files[context_hash]}")
            return self.temp_files[context_hash]
        
        # Create a new temporary file
        safe_session_id = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
        temp_file_path = os.path.join(
            self.base_temp_dir, 
            f"context_{safe_session_id}_{context_hash[:8]}.md"
        )
        
        with open(temp_file_path, 'w', encoding='utf-8') as temp_file:
            temp_file.write("# ARIS Context Reference\n\n")
            temp_file.write("This file contains reference materials assembled for this session.\n\n")
            
            # Process each context file
            for file_path in context_files:
                try:
                    # Extract filename for section heading
                    file_name = os.path.basename(file_path)
                    file_name_without_ext = os.path.splitext(file_name)[0]
                    
                    # Read the original file
                    with open(file_path, 'r', encoding='utf-8') as source_file:
                        content = source_file.read()
                    
                    # Write to consolidated file with clear section heading
                    temp_file.write(f"\n\n## {file_name_without_ext}\n\n")
                    temp_file.write(content)
                    temp_file.write("\n\n---\n\n")
                    
                except Exception as e:
                    temp_file.write(f"\n\n## ERROR: Failed to include {file_path}\n\n")
                    temp_file.write(f"Error: {str(e)}\n\n")
                    log_error(f"ContextFileManager: Failed to include file {file_path}: {e}")
        
        # Register for cleanup
        self.temp_files[context_hash] = temp_file_path
        self._register_for_cleanup(temp_file_path)
        
        log_router_activity(f"ContextFileManager: Generated context file at {temp_file_path}")
        return temp_file_path
    
    def _register_for_cleanup(self, file_path: str):
        """
        Register a file for cleanup. In this implementation, we handle cleanup separately.
        
        Args:
            file_path: Path to the file to clean up
        """
        # Actual cleanup is done by cleanup_old_files method, this is a placeholder
        pass
    
    def prepare_embedded_context(self, context_files: List[str]) -> str:
        """
        Prepare context files for embedding directly in the system prompt.
        
        Args:
            context_files: List of paths to context files
        
        Returns:
            Formatted content with XML tags for embedding in the system prompt
        """
        context_content = ""
        
        for file_path in context_files:
            try:
                # Extract filename for tag name
                file_name = os.path.basename(file_path)
                file_name_without_ext = os.path.splitext(file_name)[0]
                
                # Create a sanitized tag name (remove spaces, special chars)
                tag_name = re.sub(r'[^a-zA-Z0-9_]', '_', file_name_without_ext)
                
                # Read the original file
                with open(file_path, 'r', encoding='utf-8') as source_file:
                    content = source_file.read()
                
                # Add the content with XML-style tags
                context_content += f"\n\n<context_{tag_name}>\n{content}\n</context_{tag_name}>\n\n"
                
            except Exception as e:
                log_error(f"ContextFileManager: Failed to prepare embedded context for {file_path}: {e}")
                context_content += f"\n\n<context_error>\nFailed to include {file_path}: {str(e)}\n</context_error>\n\n"
        
        return context_content
    
    def estimate_context_size(self, context_files: List[str]) -> int:
        """
        Estimate the total size of context files in bytes.
        
        Args:
            context_files: List of paths to context files
        
        Returns:
            Estimated size in bytes
        """
        total_size = 0
        for file_path in context_files:
            try:
                if os.path.exists(file_path):
                    total_size += os.path.getsize(file_path)
            except Exception as e:
                log_warning(f"ContextFileManager: Failed to get size of {file_path}: {e}")
        
        return total_size
    
    def cleanup_old_files(self, max_age_hours: int = 24) -> None:
        """
        Clean up temporary context files older than max_age_hours.
        
        Args:
            max_age_hours: Maximum age in hours before a file is deleted
        """
        current_time = time.time()
        for root, _, files in os.walk(self.base_temp_dir):
            for file in files:
                if file.startswith("context_"):
                    file_path = os.path.join(root, file)
                    file_age = current_time - os.path.getctime(file_path)
                    if file_age > max_age_hours * 3600:
                        try:
                            os.remove(file_path)
                            log_debug(f"ContextFileManager: Removed old context file: {file_path}")
                            # Remove from cache if present
                            for hash_key, path in list(self.temp_files.items()):
                                if path == file_path:
                                    del self.temp_files[hash_key]
                        except Exception as e:
                            log_warning(f"ContextFileManager: Failed to remove old file {file_path}: {e}")


# Initialize a global context file manager instance
context_file_manager = ContextFileManager()