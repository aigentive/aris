import os
import yaml
import json
import re
import uuid
import copy
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Set
import tempfile
import shutil
from datetime import datetime

try:
    # Use Pydantic V2 style validators
    from pydantic import BaseModel, Field, field_validator, model_validator
except ImportError:
    try:
        import pip
        pip.main(['install', 'pydantic'])
        from pydantic import BaseModel, Field, field_validator, model_validator
    except Exception as e:
        raise ImportError(f"Failed to import or install pydantic: {e}")

from .logging_utils import log_router_activity, log_error, log_warning, log_debug

# Custom YAML representer for multiline strings
class LiteralStr(str):
    """Custom string class to force literal block scalar representation in YAML."""
    pass

def represent_literal_str(dumper, data):
    """Custom YAML representer for literal string blocks."""
    # Use literal block scalar style that preserves newlines
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data), style='|')

# Register the custom representer for both regular and safe dumpers
yaml.add_representer(LiteralStr, represent_literal_str)
try:
    yaml.add_representer(LiteralStr, represent_literal_str, yaml.SafeDumper)
except AttributeError:
    # SafeDumper might not be available in all PyYAML versions
    pass

# Define constants for profile locations
USER_PROFILES_DIR = os.path.expanduser("~/.aris")
PROJECT_PROFILES_DIR = "./.aris"  # Relative to working directory
PACKAGE_PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")


# Pydantic models for profile validation
class TemplateVariable(BaseModel):
    """Model for expected template variables in a profile."""
    name: str
    description: str
    required: bool = True
    default: Optional[str] = None


class ProfileSchema(BaseModel):
    """Pydantic model defining the structure and validation rules for profiles."""
    # Required fields
    profile_name: str = Field(..., description="Unique identifier for the profile")
    
    # Optional fields
    extends: Optional[Union[str, List[str]]] = Field(None, description="Parent profile(s) to inherit from")
    description: Optional[str] = Field(None, description="Brief explanation of profile purpose")
    version: Optional[str] = Field(None, description="Version of the profile")
    author: Optional[str] = Field(None, description="Creator of the profile")
    
    # Content fields
    system_prompt: Optional[str] = Field(None, description="Direct specification of system prompt text")
    system_prompt_file: Optional[str] = Field(None, description="Path to file containing the system prompt")
    
    # Tool and context configuration
    tools: Optional[List[str]] = Field(None, description="Tool names to be made available")
    context_files: Optional[List[str]] = Field(None, description="Paths to context files to be loaded")
    context_mode: Optional[str] = Field("auto", description="How to handle context files: embedded, referenced, or auto")
    
    # MCP configuration
    mcp_config_files: Optional[List[str]] = Field(None, description="MCP config files to be merged")
    
    # Template variables
    variables: Optional[List[TemplateVariable]] = Field(None, description="Variables that need user values")
    
    # User experience
    welcome_message: Optional[str] = Field(None, description="Message shown on profile activation")
    tags: Optional[List[str]] = Field(None, description="Categorization tags for profile discovery")
    
    @model_validator(mode="after")
    def check_system_prompt_provided(cls, values):
        """Validate that either system_prompt, system_prompt_file is provided or extends is specified."""
        system_prompt = values.system_prompt
        system_prompt_file = values.system_prompt_file
        extends = values.extends
        
        if not extends and not system_prompt and not system_prompt_file:
            raise ValueError(
                "Either 'system_prompt', 'system_prompt_file', or 'extends' must be provided"
            )
        return values
    
    @field_validator("context_mode", mode="before")
    @classmethod
    def validate_context_mode(cls, v):
        """Validate that context_mode is one of 'embedded', 'referenced', or 'auto'."""
        if v not in ["embedded", "referenced", "auto"]:
            raise ValueError(f"context_mode must be 'embedded', 'referenced', or 'auto', got '{v}'")
        return v


class ProfileManager:
    """
    Manages loading, resolving, and caching profiles from different locations.
    Handles profile inheritance, merging, and validation.
    """
    
    def __init__(self):
        self._profile_cache = {}  # Cache resolved profiles to avoid reprocessing
        self._raw_profile_cache = {}  # Cache raw (unresolved) profiles
        self._file_content_cache = {}  # Cache file contents
        self._parent_resolution_stack = []  # Used for circular dependency detection
        
        # Ensure profile directories exist
        self._create_profile_dirs()
        self._available_profiles = None  # Will be set by refresh_profiles()
        self.refresh_profiles()  # Initial scan
    
    def _create_profile_dirs(self):
        """Create profile directories if they don't exist."""
        # User profiles
        os.makedirs(USER_PROFILES_DIR, exist_ok=True)
        # Package profiles (should exist in the package, but ensure base dir)
        os.makedirs(os.path.join(PACKAGE_PROFILES_DIR, "base"), exist_ok=True)
        # Don't create project profiles by default - let the user do it explicitly
    
    def refresh_profiles(self):
        """
        Rescan all profile locations and update the registry.
        This should be called when profiles are added or modified.
        """
        log_debug("ProfileManager: Refreshing profiles...")
        self._available_profiles = self._discover_profiles()
        self._profile_cache = {}  # Clear cache when refreshing
        self._raw_profile_cache = {}
        self._file_content_cache = {}
        return self._available_profiles
    
    def get_available_profiles(self):
        """Returns a list of all available profile references."""
        return self._available_profiles
    
    def _discover_profiles(self) -> Dict[str, Dict]:
        """
        Scan all profile locations and build a registry of available profiles.
        Returns a dictionary mapping profile reference to its location and metadata.
        """
        profiles = {}
        
        # Priority order is USER_PROFILES_DIR > PROJECT_PROFILES_DIR > PACKAGE_PROFILES_DIR
        for profile_dir in [PACKAGE_PROFILES_DIR, PROJECT_PROFILES_DIR, USER_PROFILES_DIR]:
            if os.path.exists(profile_dir):
                for root, _, files in os.walk(profile_dir):
                    for file in files:
                        if file.endswith(('.yaml', '.yml')):
                            file_path = os.path.join(root, file)
                            try:
                                # Load the basic metadata without resolving
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    profile_data = yaml.safe_load(f)
                                
                                if not profile_data or not isinstance(profile_data, dict):
                                    log_warning(f"ProfileManager: Invalid profile format in {file_path}")
                                    continue
                                
                                profile_name = profile_data.get('profile_name')
                                if not profile_name:
                                    log_warning(f"ProfileManager: Missing profile_name in {file_path}")
                                    continue
                                
                                # Construct the profile reference using its directory structure
                                rel_path = os.path.relpath(root, profile_dir)
                                if rel_path == '.':
                                    profile_ref = profile_name
                                else:
                                    # Convert directory path to profile reference format
                                    profile_ref = f"{rel_path.replace(os.path.sep, '/')}/{profile_name}"
                                
                                # Store the profile info with its location and basic metadata
                                profiles[profile_ref] = {
                                    'path': file_path,
                                    'name': profile_name,
                                    'description': profile_data.get('description', ''),
                                    'tags': profile_data.get('tags', []),
                                    'location': profile_dir
                                }
                                log_debug(f"ProfileManager: Discovered profile {profile_ref} at {file_path}")
                            except Exception as e:
                                log_error(f"ProfileManager: Error loading profile {file_path}: {e}")
        
        log_router_activity(f"ProfileManager: Discovered {len(profiles)} profiles")
        return profiles
    
    def get_profile(self, profile_ref: str, resolve: bool = True, workspace_variables: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        """
        Get a profile by its reference.
        Args:
            profile_ref: The profile reference in the format "dir/subdir/name" or just "name"
            resolve: Whether to resolve inheritance and return a fully resolved profile
            workspace_variables: Optional workspace variables to inject into the profile
        
        Returns:
            The profile data as a dictionary, or None if not found
        """
        # Check cache first
        cache_key = f"{profile_ref}_{resolve}"
        if cache_key in self._profile_cache:
            return copy.deepcopy(self._profile_cache[cache_key])
        
        # Find the profile data
        if profile_ref not in self._available_profiles:
            log_warning(f"ProfileManager: Profile '{profile_ref}' not found")
            return None
        
        # Load the raw profile data
        try:
            profile_path = self._available_profiles[profile_ref]['path']
            
            # Check raw profile cache
            if profile_path in self._raw_profile_cache:
                profile_data = copy.deepcopy(self._raw_profile_cache[profile_path])
            else:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_data = yaml.safe_load(f)
                    self._raw_profile_cache[profile_path] = copy.deepcopy(profile_data)
            
            # Validate with Pydantic
            try:
                # This will raise ValidationError if the profile is invalid
                ProfileSchema(**profile_data)
            except Exception as e:
                log_error(f"ProfileManager: Profile validation error for {profile_ref}: {e}")
                # Still continue with the raw data to allow partial functionality
            
            # Resolve inheritance if requested
            if resolve and 'extends' in profile_data and profile_data['extends']:
                profile_data = self._resolve_inheritance(profile_data, profile_path)
            
            # Inject workspace variables if provided
            if workspace_variables:
                profile_data = self._inject_workspace_variables(profile_data, workspace_variables)
            
            # Cache the result
            self._profile_cache[cache_key] = copy.deepcopy(profile_data)
            
            return copy.deepcopy(profile_data)
        except Exception as e:
            log_error(f"ProfileManager: Error getting profile {profile_ref}: {e}")
            return None
    
    def _resolve_inheritance(self, profile_data: Dict, profile_path: str) -> Dict:
        """
        Resolve profile inheritance by loading and merging parent profiles.
        
        Args:
            profile_data: The raw profile data to resolve
            profile_path: The path to the profile file (used for relative path resolution)
        
        Returns:
            The fully resolved profile data
        """
        profile_name = profile_data.get('profile_name')
        
        # Add to resolution stack to detect circular dependencies
        if profile_name in self._parent_resolution_stack:
            raise ValueError(
                f"Circular dependency detected in profile inheritance: "
                f"{' -> '.join(self._parent_resolution_stack)} -> {profile_name}"
            )
        
        self._parent_resolution_stack.append(profile_name)
        
        try:
            extends = profile_data.get('extends')
            
            # Convert to list if it's a string
            if isinstance(extends, str):
                extends = [extends]
            elif not extends:
                # No inheritance to resolve
                return profile_data
            
            # Initialize with an empty profile
            resolved_profile = {}
            
            # Merge all parent profiles in order
            for parent_ref in extends:
                parent_profile = self.get_profile(parent_ref, resolve=True)  # Recursive resolution
                if not parent_profile:
                    log_warning(f"ProfileManager: Parent profile '{parent_ref}' not found for {profile_name}")
                    continue
                
                # Merge parent into resolved profile
                resolved_profile = self._merge_profiles(resolved_profile, parent_profile)
            
            # Finally, merge the child profile
            resolved_profile = self._merge_profiles(resolved_profile, profile_data)
            
            # Handle system_prompt placeholder for parent content
            if 'system_prompt' in resolved_profile:
                resolved_profile['system_prompt'] = self._handle_parent_placeholders(
                    resolved_profile['system_prompt'], extends, profile_data
                )
            
            return resolved_profile
        finally:
            # Remove from resolution stack when done
            self._parent_resolution_stack.pop()
    
    def _handle_parent_placeholders(self, system_prompt: str, parent_refs: List[str], child_profile: Dict) -> str:
        """
        Replace placeholders like {{parent_system_prompt}} and {{parent:name}} in the system prompt.
        
        Args:
            system_prompt: The system prompt with potential placeholders
            parent_refs: List of parent profile references
            child_profile: The child profile data
        
        Returns:
            The system prompt with placeholders replaced
        """
        if not system_prompt:
            return system_prompt
        
        # Handle {{parent_system_prompt}} placeholder (insert content from all parents)
        if "{{parent_system_prompt}}" in system_prompt:
            # Collect all parent system prompts
            parent_prompts = []
            for parent_ref in parent_refs:
                parent = self.get_profile(parent_ref, resolve=True)
                if parent and 'system_prompt' in parent:
                    parent_prompts.append(parent['system_prompt'])
                elif parent and 'system_prompt_file' in parent:
                    # Load from file
                    parent_file_content = self.load_file_content(parent['system_prompt_file'])
                    if parent_file_content:
                        parent_prompts.append(parent_file_content)
            
            # Replace placeholder with combined parent prompts
            if parent_prompts:
                parent_content = "\n\n".join(parent_prompts)
                system_prompt = system_prompt.replace("{{parent_system_prompt}}", parent_content)
            else:
                # Remove placeholder if no parent content
                system_prompt = system_prompt.replace("{{parent_system_prompt}}", "")
        
        # Handle {{parent:name}} placeholders (insert specific parent content)
        parent_placeholders = re.findall(r'{{parent:(.*?)}}', system_prompt)
        for parent_name in parent_placeholders:
            parent = self.get_profile(parent_name, resolve=True)
            placeholder = f"{{{{parent:{parent_name}}}}}"
            
            if parent and 'system_prompt' in parent:
                system_prompt = system_prompt.replace(placeholder, parent['system_prompt'])
            elif parent and 'system_prompt_file' in parent:
                # Load from file
                parent_file_content = self.load_file_content(parent['system_prompt_file'])
                if parent_file_content:
                    system_prompt = system_prompt.replace(placeholder, parent_file_content)
                else:
                    system_prompt = system_prompt.replace(placeholder, "")
            else:
                # Remove placeholder if parent not found
                system_prompt = system_prompt.replace(placeholder, "")
        
        return system_prompt
    
    def _merge_profiles(self, base_profile: Dict, overlay_profile: Dict) -> Dict:
        """
        Merge two profiles according to the merge strategy.
        
        Args:
            base_profile: The base profile to merge into
            overlay_profile: The profile to merge on top
        
        Returns:
            The merged profile
        """
        result = copy.deepcopy(base_profile)
        
        for key, value in overlay_profile.items():
            # Skip profile_name - it's not merged
            if key == 'profile_name':
                result[key] = value
                continue
            
            # Handle extends separately - not merged
            if key == 'extends':
                result[key] = value
                continue
            
            # Different merge strategies based on field type
            if key not in result:
                # Simple case: key not in base, just add it
                result[key] = copy.deepcopy(value)
            elif isinstance(value, list) and isinstance(result[key], list):
                # List merge strategy
                # Check for special directives at the start of the list
                if value and isinstance(value[0], str):
                    if value[0] == "!REPLACE":
                        # Replace entire list
                        result[key] = copy.deepcopy(value[1:])
                    elif value[0] == "!PREPEND":
                        # Prepend items to list
                        new_list = copy.deepcopy(value[1:])
                        # Filter out duplicates
                        for item in result[key]:
                            if item not in new_list:
                                new_list.append(item)
                        result[key] = new_list
                    else:
                        # Default: append with unique
                        new_list = copy.deepcopy(result[key])
                        for item in value:
                            if item not in new_list:
                                new_list.append(item)
                        result[key] = new_list
                else:
                    # Handle special case: empty list in child should preserve parent list
                    if not value:  # Empty list in child
                        # Keep the parent list - don't replace with empty
                        pass  # result[key] already has the parent list
                    else:
                        # No directive, use default strategy (append with unique)
                        new_list = copy.deepcopy(result[key])
                        for item in value:
                            if item not in new_list:
                                new_list.append(item)
                        result[key] = new_list
            elif isinstance(value, dict) and isinstance(result[key], dict):
                # Dict merge strategy: deep merge
                result[key] = self._merge_profiles(result[key], value)  # Recursive merge
            else:
                # Scalar values: overlay replaces base
                result[key] = copy.deepcopy(value)
        
        return result
    
    def load_file_content(self, file_path: str, relative_to: Optional[str] = None) -> Optional[str]:
        """
        Load content from a file with path resolution and caching.
        
        Args:
            file_path: The path to the file
            relative_to: Optional base path for relative path resolution
        
        Returns:
            The file content as a string, or None if file not found
        """
        # Check cache first
        cache_key = f"{file_path}_{relative_to}"
        if cache_key in self._file_content_cache:
            return self._file_content_cache[cache_key]
        
        # Resolve path
        resolved_path = self._resolve_file_path(file_path, relative_to)
        if not resolved_path or not os.path.exists(resolved_path):
            log_warning(f"ProfileManager: File not found: {file_path}")
            return None
        
        # Load file content
        try:
            with open(resolved_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Cache the content
            self._file_content_cache[cache_key] = content
            
            return content
        except Exception as e:
            log_error(f"ProfileManager: Error reading file {resolved_path}: {e}")
            return None
    
    def _resolve_file_path(self, file_path: str, relative_to: Optional[str] = None) -> Optional[str]:
        """
        Resolve a file path relative to a base path or using the profile search paths.
        
        Args:
            file_path: The path to resolve
            relative_to: Optional base path for relative path resolution
        
        Returns:
            The resolved absolute path, or None if path cannot be resolved
        """
        # Expand home directory and environment variables
        file_path = os.path.expanduser(file_path)
        file_path = os.path.expandvars(file_path)
        
        log_router_activity(f"ProfileManager: Resolving file path: {file_path}, relative to: {relative_to}")
        
        # Absolute path handling
        if os.path.isabs(file_path):
            path_exists = os.path.exists(file_path)
            log_router_activity(f"ProfileManager: Absolute path {file_path} exists: {path_exists}")
            return file_path if path_exists else None
        
        # Track all paths we try for better debugging
        tried_paths = []
        
        # For common config paths, add additional search locations
        is_config_file = "config" in file_path.lower() or file_path.endswith(('.json', '.yaml', '.yml'))
        
        # Special handling for configs/ directory path
        if file_path.startswith("configs/") or file_path.startswith("./configs/"):
            log_router_activity(f"ProfileManager: Special handling for configs/ path: {file_path}")
            # First try package profiles config directory
            package_configs_path = os.path.join(PACKAGE_PROFILES_DIR, file_path)
            tried_paths.append(package_configs_path)
            
            if os.path.exists(package_configs_path):
                log_router_activity(f"ProfileManager: Found config file in package configs: {package_configs_path}")
                return package_configs_path
                
            # Then try script directory configs
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # Extract the filename or path after configs/
            if "/" in file_path[8:]:  # If there are subdirectories after configs/
                rest_path = file_path[8:]
                script_configs_path = os.path.join(script_dir, "profiles", "configs", rest_path)
            else:
                filename = os.path.basename(file_path)
                script_configs_path = os.path.join(script_dir, "profiles", "configs", filename)
                
            tried_paths.append(script_configs_path)
            
            if os.path.exists(script_configs_path):
                log_router_activity(f"ProfileManager: Found config file in script configs: {script_configs_path}")
                return script_configs_path
        
        # Relative to a specific path (likely the profile path)
        if relative_to:
            base_dir = os.path.dirname(relative_to) if os.path.isfile(relative_to) else relative_to
            resolved_path = os.path.abspath(os.path.join(base_dir, file_path))
            tried_paths.append(resolved_path)
            
            if os.path.exists(resolved_path):
                log_router_activity(f"ProfileManager: Found file at path relative to {base_dir}: {resolved_path}")
                return resolved_path
                
            # For config files, also try relative to the profile's parent directory
            if is_config_file:
                parent_dir = os.path.dirname(base_dir)
                resolved_path = os.path.abspath(os.path.join(parent_dir, file_path))
                tried_paths.append(resolved_path)
                
                if os.path.exists(resolved_path):
                    log_router_activity(f"ProfileManager: Found config file at path relative to parent dir {parent_dir}: {resolved_path}")
                    return resolved_path
                
                # Special case for "configs/" directory - check if path needs adjusting
                if "configs/" in file_path:
                    # Try looking for the configs directory at the same level as the profile
                    configs_dir = os.path.join(os.path.dirname(base_dir), "configs")
                    if os.path.exists(configs_dir):
                        # Get just the filename from the path
                        filename = os.path.basename(file_path)
                        resolved_path = os.path.join(configs_dir, filename)
                        tried_paths.append(resolved_path)
                        
                        if os.path.exists(resolved_path):
                            log_router_activity(f"ProfileManager: Found config file in configs dir at same level: {resolved_path}")
                            return resolved_path
        
        # Try profile search paths with more options for config files
        for profile_dir in [USER_PROFILES_DIR, PROJECT_PROFILES_DIR, PACKAGE_PROFILES_DIR]:
            # First try direct path from the profile directory
            resolved_path = os.path.abspath(os.path.join(profile_dir, file_path))
            tried_paths.append(resolved_path)
            
            if os.path.exists(resolved_path):
                log_router_activity(f"ProfileManager: Found file in profile dir {profile_dir}: {resolved_path}")
                return resolved_path
                
            # For config files, also try in a "configs" subdirectory
            if is_config_file:
                # Just the filename without the "configs/" prefix if it exists
                filename = os.path.basename(file_path)
                configs_path = os.path.join(profile_dir, "configs", filename)
                tried_paths.append(configs_path)
                
                if os.path.exists(configs_path):
                    log_router_activity(f"ProfileManager: Found config file in configs subdir: {configs_path}")
                    return configs_path
        
        # Try standard system locations for config files
        if is_config_file:
            # Check in the local directory
            local_path = os.path.abspath(file_path)
            tried_paths.append(local_path)
            
            if os.path.exists(local_path):
                log_router_activity(f"ProfileManager: Found config file in local directory: {local_path}")
                return local_path
            
            # Check in the current script directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(script_dir, file_path)
            tried_paths.append(script_path)
            
            if os.path.exists(script_path):
                log_router_activity(f"ProfileManager: Found config file in script directory: {script_path}")
                return script_path
                
            # Also try in a configs subdirectory of the script directory
            script_configs_path = os.path.join(script_dir, "profiles", "configs", os.path.basename(file_path))
            tried_paths.append(script_configs_path)
            
            if os.path.exists(script_configs_path):
                log_router_activity(f"ProfileManager: Found config file in script configs directory: {script_configs_path}")
                return script_configs_path
        
        # File not found in any search path
        log_warning(f"ProfileManager: Could not resolve file path {file_path}. Tried: {tried_paths}")
        return None
    
    def get_merged_mcp_config(self, profile: Dict) -> Optional[Dict]:
        """
        Load and merge MCP configuration files specified in the profile.
        
        Args:
            profile: The profile data
        
        Returns:
            The merged MCP configuration, or None if no config files
        """
        config_files = profile.get('mcp_config_files', [])
        if not config_files:
            log_debug(f"ProfileManager: No MCP config files specified in profile {profile.get('profile_name')}")
            return None
        
        # Log all config files for debugging
        log_router_activity(f"ProfileManager: Merging MCP config files for profile {profile.get('profile_name')}: {config_files}")
        
        # Get the profile path from its name
        profile_name = profile.get('profile_name')
        profile_path = None
        profile_location = None
        for ref, info in self._available_profiles.items():
            if ref.endswith('/' + profile_name) or ref == profile_name:
                profile_path = info['path']
                profile_location = info.get('location')
                log_router_activity(f"ProfileManager: Found profile path for {profile_name}: {profile_path}, location: {profile_location}")
                break
        
        # Start with an empty config
        merged_config = {"mcpServers": {}}
        resolved_paths = []
        missing_paths = []
        
        # Load and merge each config file in order
        for file_path in config_files:
            try:
                # Try special handling for configs/ directory first
                if file_path.startswith("configs/"):
                    log_router_activity(f"ProfileManager: Special handling for configs/ path: {file_path}")
                
                # Resolve path relative to the profile or search paths
                resolved_path = self._resolve_file_path(file_path, profile_path)
                if not resolved_path:
                    log_warning(f"ProfileManager: MCP config file not found: {file_path}")
                    missing_paths.append(file_path)
                    continue
                
                resolved_paths.append(resolved_path)
                log_router_activity(f"ProfileManager: Successfully resolved config path {file_path} to {resolved_path}")
                
                # Load the config file
                with open(resolved_path, 'r', encoding='utf-8') as f:
                    if resolved_path.endswith('.json'):
                        config = json.load(f)
                    elif resolved_path.endswith(('.yaml', '.yml')):
                        config = yaml.safe_load(f)
                    else:
                        log_warning(f"ProfileManager: Unsupported MCP config file format: {resolved_path}")
                        continue
                
                # Merge with existing config
                self._deep_merge_dict(merged_config, config)
                
                # Log server information for each config file
                if 'mcpServers' in config:
                    server_names = list(config['mcpServers'].keys())
                    log_router_activity(f"ProfileManager: Config file {file_path} contains servers: {server_names}")
                    
                    # Log detailed server info for debugging
                    for server_name, server_config in config['mcpServers'].items():
                        server_type = server_config.get('type', 'unknown')
                        log_router_activity(f"ProfileManager: Server '{server_name}' has type '{server_type}'")
                else:
                    log_warning(f"ProfileManager: Config file {file_path} does not contain mcpServers section")
                
                log_router_activity(f"ProfileManager: Merged MCP config file: {resolved_path}")
            except Exception as e:
                log_error(f"ProfileManager: Error loading MCP config file {file_path}: {e}")
                import traceback
                log_error(f"ProfileManager: Traceback: {traceback.format_exc()}")
        
        # Log summary of the merge operation
        if 'mcpServers' in merged_config:
            server_names = list(merged_config['mcpServers'].keys())
            log_router_activity(f"ProfileManager: Final merged config contains servers: {server_names}")
            
            # Verify each server configuration
            for server_name, server_config in merged_config['mcpServers'].items():
                server_type = server_config.get('type', 'unknown')
                log_router_activity(f"ProfileManager: Final merged config server '{server_name}' has type '{server_type}'")
            
            # Check for any tool preferences that might need specific servers
            if 'tools' in profile and profile['tools']:
                tool_servers = set()
                for tool in profile['tools']:
                    if tool.startswith('mcp__') and '__' in tool:
                        parts = tool.split('__')
                        if len(parts) > 2:
                            server_name = parts[1]
                            tool_servers.add(server_name)
                
                log_router_activity(f"ProfileManager: Profile requires servers from tools: {tool_servers}")
                
                # Check if all required servers are included
                missing_servers = tool_servers - set(server_names)
                if missing_servers:
                    log_warning(f"ProfileManager: Profile requires servers {missing_servers} but they are not in the merged config")
        else:
            log_warning(f"ProfileManager: Final merged config does not contain mcpServers section")
        
        # Log summary of file resolution
        log_router_activity(f"ProfileManager: Successfully resolved {len(resolved_paths)} of {len(config_files)} MCP config files")
        if missing_paths:
            log_warning(f"ProfileManager: Could not resolve these MCP config files: {missing_paths}")
        
        return merged_config
    
    def get_merged_mcp_config_path(self, profile: Dict) -> Optional[str]:
        """
        Create a temporary file with the merged MCP config for the profile.
        
        Args:
            profile: The profile data
        
        Returns:
            The path to the temporary config file, or None if no config
        """
        # First check if the profile has any MCP config files specified
        if not profile or not profile.get('mcp_config_files'):
            log_debug(f"ProfileManager: No MCP config files specified in profile")
            return None
        
        profile_name = profile.get('profile_name', 'unknown')
        log_router_activity(f"ProfileManager: Generating merged MCP config for profile: {profile_name}")
        log_router_activity(f"ProfileManager: MCP config files specified: {profile.get('mcp_config_files', [])}")
        
        # Check if we need to handle paths relative to a user profile
        profile_path = None
        for ref, info in self._available_profiles.items():
            if ref.endswith('/' + profile_name) or ref == profile_name:
                profile_path = info['path']
                log_router_activity(f"ProfileManager: Found profile path: {profile_path}")
                
                # Also log the location (directory) of the profile
                profile_location = info.get('location')
                if profile_location:
                    log_router_activity(f"ProfileManager: Profile is in location: {profile_location}")
                break
        
        # Additional search paths for config files
        if profile_path:
            # For user profiles in USER_PROFILES_DIR, we need special handling
            if os.path.dirname(profile_path).startswith(USER_PROFILES_DIR):
                log_router_activity(f"ProfileManager: Profile is a user profile in {USER_PROFILES_DIR}")
                
                # Check if user profile has configs dir
                user_configs_dir = os.path.join(USER_PROFILES_DIR, "configs")
                if os.path.exists(user_configs_dir):
                    log_router_activity(f"ProfileManager: User configs directory exists: {user_configs_dir}")
                else:
                    log_router_activity(f"ProfileManager: User configs directory does not exist, checking if we need to copy standard configs")
                    
                    # Try to copy the standard configs to the user profile directory
                    standard_configs_dir = os.path.join(PACKAGE_PROFILES_DIR, "configs")
                    if os.path.exists(standard_configs_dir):
                        log_router_activity(f"ProfileManager: Standard configs exist at {standard_configs_dir}, copying to user directory")
                        try:
                            os.makedirs(user_configs_dir, exist_ok=True)
                            for config_file in os.listdir(standard_configs_dir):
                                if config_file.endswith('.json'):
                                    src_path = os.path.join(standard_configs_dir, config_file)
                                    dst_path = os.path.join(user_configs_dir, config_file)
                                    if not os.path.exists(dst_path):
                                        shutil.copy2(src_path, dst_path)
                                        log_router_activity(f"ProfileManager: Copied {config_file} to user configs directory")
                                    else:
                                        log_router_activity(f"ProfileManager: Config file {config_file} already exists in user directory")
                        except Exception as e:
                            log_warning(f"ProfileManager: Error copying standard configs: {e}")
        
        # Get the merged config
        merged_config = self.get_merged_mcp_config(profile)
        if not merged_config:
            log_warning(f"ProfileManager: Failed to get merged MCP config for profile {profile_name}")
            return None
        
        try:
            # Create a temporary file for the merged config
            config_dir = os.path.join(tempfile.gettempdir(), "aris_profiles")
            os.makedirs(config_dir, exist_ok=True)
            
            # Log the mcpServers section from the config for debugging
            if 'mcpServers' in merged_config:
                server_names = list(merged_config['mcpServers'].keys())
                server_types = {}
                
                # Analyze server types for better logging
                for server_name, server_config in merged_config['mcpServers'].items():
                    server_type = server_config.get('type', 'unknown')
                    if server_type not in server_types:
                        server_types[server_type] = []
                    server_types[server_type].append(server_name)
                
                log_router_activity(f"ProfileManager: Merged MCP config contains servers: {server_names}")
                log_router_activity(f"ProfileManager: Server types: {server_types}")
                
                # If we have tools preferences in profile, check for required servers
                if 'tools' in profile and profile['tools']:
                    tool_servers = set()
                    for tool in profile['tools']:
                        if tool.startswith('mcp__') and '__' in tool:
                            parts = tool.split('__')
                            if len(parts) > 2:
                                server_name = parts[1]
                                tool_servers.add(server_name)
                    
                    log_router_activity(f"ProfileManager: Tool preferences require servers: {tool_servers}")
                    
                    # Check if all required servers are included
                    missing_servers = tool_servers - set(server_names)
                    if missing_servers:
                        log_warning(f"ProfileManager: Profile requires servers {missing_servers} but they are not in the merged config")
            else:
                log_warning(f"ProfileManager: Merged MCP config is missing 'mcpServers' section")
            
            # Generate a unique ID based on profile name and timestamp for better identification
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            config_id = f"{profile_name}_{timestamp}_{str(uuid.uuid4())[:8]}"
            config_path = os.path.join(config_dir, f"mcp_config_{config_id}.json")
            
            # Perform environment variable substitution before writing
            merged_config_with_env = self._substitute_env_variables(merged_config)
            
            # Write the merged config to the file
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(merged_config_with_env, f, indent=2)
            
            # Verify the file was created
            if os.path.exists(config_path):
                file_size = os.path.getsize(config_path)
                log_router_activity(f"ProfileManager: Created merged MCP config file: {config_path} (size: {file_size} bytes)")
                
                # Read back the file to verify its contents
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_content = json.load(f)
                    
                    if 'mcpServers' in config_content:
                        server_names = list(config_content['mcpServers'].keys())
                        log_router_activity(f"ProfileManager: Verified config file contains servers: {server_names}")
                    else:
                        log_warning(f"ProfileManager: Verification found MCP config file is missing mcpServers section")
                except Exception as e:
                    log_warning(f"ProfileManager: Failed to verify MCP config file content: {e}")
            else:
                log_error(f"ProfileManager: MCP config file was not created at {config_path}")
                return None
                
            # Return the absolute path to ensure no path resolution issues
            absolute_config_path = os.path.abspath(config_path)
            log_router_activity(f"ProfileManager: Returning absolute MCP config path: {absolute_config_path}")
            return absolute_config_path
        except Exception as e:
            log_error(f"ProfileManager: Error creating merged MCP config file: {e}")
            import traceback
            log_error(f"ProfileManager: Traceback: {traceback.format_exc()}")
            return None
    
    def _substitute_env_variables(self, config: Dict) -> Dict:
        """
        Substitute environment variables in MCP configuration.
        
        Supports the following syntax:
        - ${VAR_NAME} - substitutes with environment variable value
        - ${VAR_NAME:-default} - substitutes with environment variable value or default if not set
        
        Args:
            config: The configuration dictionary to process
            
        Returns:
            A new configuration dictionary with environment variables substituted
        """
        import re
        import copy
        
        def substitute_string(text: str) -> str:
            """Substitute environment variables in a string."""
            if not isinstance(text, str):
                return text
                
            # Pattern to match ${VAR_NAME} or ${VAR_NAME:-default}
            pattern = r'\$\{([^}:]+)(?::-(.*?))?\}'
            
            def replace_match(match):
                var_name = match.group(1)
                default_value = match.group(2) if match.group(2) is not None else ""
                
                # Get the environment variable value
                env_value = os.getenv(var_name)
                
                if env_value is not None:
                    return env_value
                elif default_value:
                    return default_value
                else:
                    # If no default and var not set, leave as-is or return empty
                    log_warning(f"ProfileManager: Environment variable '{var_name}' not found and no default provided")
                    return ""
            
            return re.sub(pattern, replace_match, text)
        
        def substitute_recursive(obj):
            """Recursively substitute environment variables in nested structures."""
            if isinstance(obj, dict):
                return {key: substitute_recursive(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [substitute_recursive(item) for item in obj]
            elif isinstance(obj, str):
                return substitute_string(obj)
            else:
                return obj
        
        # Create a deep copy to avoid modifying the original
        config_copy = copy.deepcopy(config)
        
        # Perform substitution
        substituted_config = substitute_recursive(config_copy)
        
        log_router_activity("ProfileManager: Performed environment variable substitution in MCP config")
        
        return substituted_config
    
    def _deep_merge_dict(self, base: Dict, overlay: Dict):
        """
        Deep merge two dictionaries in place.
        
        Args:
            base: The base dictionary to merge into (modified in place)
            overlay: The dictionary to merge on top
        """
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge_dict(base[key], value)
            else:
                base[key] = copy.deepcopy(value)
    
    def get_variables_from_profile(self, profile: Dict) -> List[TemplateVariable]:
        """
        Extract all template variables from a profile.
        
        Args:
            profile: The profile data
        
        Returns:
            List of TemplateVariable objects
        """
        declared_vars = []
        
        # Add explicitly declared variables
        if 'variables' in profile and profile['variables']:
            for var in profile['variables']:
                if isinstance(var, dict):
                    # Convert dict to TemplateVariable
                    declared_vars.append(TemplateVariable(**var))
                else:
                    # It's already a TemplateVariable
                    declared_vars.append(var)
        
        # Check system_prompt for {{var}} patterns not already declared
        if 'system_prompt' in profile and profile['system_prompt']:
            system_prompt = profile['system_prompt']
            self._extract_variables_from_text(system_prompt, declared_vars)
        
        # Check system_prompt_file if specified
        if 'system_prompt_file' in profile and profile['system_prompt_file']:
            file_content = self.load_file_content(profile['system_prompt_file'])
            if file_content:
                self._extract_variables_from_text(file_content, declared_vars)
        
        return declared_vars
    
    def _extract_variables_from_text(self, text: str, declared_vars: List[TemplateVariable]):
        """
        Extract template variables from text and add them to declared_vars if not already present.
        
        Args:
            text: The text to extract variables from
            declared_vars: List of already declared variables (modified in place)
        """
        if not text:
            return
        
        # Find all {{var}} patterns, excluding {{parent_system_prompt}} and {{parent:name}}
        var_matches = re.findall(r'{{(.*?)}}', text)
        declared_var_names = [var.name for var in declared_vars]
        
        for var_name in var_matches:
            # Skip parent prompts
            if var_name == 'parent_system_prompt' or var_name.startswith('parent:'):
                continue
            
            # Add if not already declared
            if var_name not in declared_var_names:
                declared_vars.append(TemplateVariable(
                    name=var_name,
                    description=f"Value for {var_name}",
                    required=True
                ))
                declared_var_names.append(var_name)
    
    def collect_profile_paths(self, profile_ref: str, path_type: str) -> List[str]:
        """
        Collect all file paths of a specific type (context_files, mcp_config_files) from a profile and its parents.
        
        Args:
            profile_ref: The profile reference
            path_type: The type of paths to collect ('context_files' or 'mcp_config_files')
        
        Returns:
            List of resolved file paths
        """
        if path_type not in ['context_files', 'mcp_config_files']:
            log_warning(f"ProfileManager: Invalid path type: {path_type}")
            return []
        
        profile = self.get_profile(profile_ref, resolve=True)
        if not profile:
            return []
        
        paths = profile.get(path_type, [])
        if not paths:
            return []
        
        # Get the profile path from its name
        profile_name = profile.get('profile_name')
        profile_path = None
        for ref, info in self._available_profiles.items():
            if ref.endswith('/' + profile_name) or ref == profile_name:
                profile_path = info['path']
                break
        
        resolved_paths = []
        for path in paths:
            resolved_path = self._resolve_file_path(path, profile_path)
            if resolved_path:
                resolved_paths.append(resolved_path)
            else:
                log_warning(f"ProfileManager: File not found: {path} for profile {profile_ref}")
        
        return resolved_paths
    
    def create_profile_interactive(self, profile_name: str) -> Optional[str]:
        """
        Create a new profile interactively and save it to the user profiles directory.
        
        Args:
            profile_name: The name for the new profile
        
        Returns:
            The path to the created profile file, or None if creation failed
        """
        # Build profile data from user input
        profile_data = {
            'profile_name': profile_name,
            'description': input("Enter a description for the profile: "),
            'version': "1.0",
            'author': input("Enter your name as the author: ")
        }
        
        # System prompt
        prompt_source = input("System prompt source (1 - direct, 2 - file): ")
        if prompt_source == "1":
            print("Enter the system prompt (end with Enter + Ctrl+D or Enter + Ctrl+Z on Windows):")
            system_prompt_lines = []
            try:
                while True:
                    line = input()
                    system_prompt_lines.append(line)
            except EOFError:
                profile_data['system_prompt'] = "\n".join(system_prompt_lines)
        else:
            profile_data['system_prompt_file'] = input("Enter the path to the system prompt file: ")
        
        # Inheritance
        extends = input("Extend another profile? (Enter profile name or leave empty): ")
        if extends:
            profile_data['extends'] = extends
        
        # Tool preferences
        tools_input = input("Enter tool names to make available (comma-separated, leave empty for all): ")
        if tools_input:
            profile_data['tools'] = [tool.strip() for tool in tools_input.split(",")]
        
        # Context files
        context_files_input = input("Enter paths to context files (comma-separated, leave empty for none): ")
        if context_files_input:
            profile_data['context_files'] = [file.strip() for file in context_files_input.split(",")]
            
            context_mode = input("Context mode (embedded, referenced, auto) [default=auto]: ")
            if context_mode in ["embedded", "referenced"]:
                profile_data['context_mode'] = context_mode
            else:
                profile_data['context_mode'] = "auto"
        
        # MCP config files
        mcp_config_input = input("Enter paths to MCP config files (comma-separated, leave empty for none): ")
        if mcp_config_input:
            profile_data['mcp_config_files'] = [file.strip() for file in mcp_config_input.split(",")]
        
        # Welcome message
        welcome_message = input("Enter a welcome message to show when the profile is activated: ")
        if welcome_message:
            profile_data['welcome_message'] = welcome_message
        
        # Tags
        tags_input = input("Enter tags for the profile (comma-separated, leave empty for none): ")
        if tags_input:
            profile_data['tags'] = [tag.strip() for tag in tags_input.split(",")]
        
        # Create directory structure
        profile_path_parts = profile_name.split("/")
        if len(profile_path_parts) > 1:
            # Create directories for nested profile
            profile_dir = os.path.join(USER_PROFILES_DIR, *profile_path_parts[:-1])
            os.makedirs(profile_dir, exist_ok=True)
            file_name = profile_path_parts[-1] + ".yaml"
            profile_file_path = os.path.join(profile_dir, file_name)
        else:
            # Simple profile in root directory
            file_name = profile_name + ".yaml"
            profile_file_path = os.path.join(USER_PROFILES_DIR, file_name)
        
        # Validate profile data
        try:
            ProfileSchema(**profile_data)
        except Exception as e:
            log_error(f"ProfileManager: Validation error for new profile {profile_name}: {e}")
            print(f"Error: Profile validation failed: {e}")
            return None
        
        # Write profile to file
        try:
            # Convert multiline string fields to LiteralStr for better YAML formatting
            formatted_profile_data = self._format_multiline_strings_for_yaml(profile_data)
            
            with open(profile_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(formatted_profile_data, f, default_flow_style=False, sort_keys=False)
            
            # Refresh profiles to include the new one
            self.refresh_profiles()
            
            log_router_activity(f"ProfileManager: Created new profile {profile_name} at {profile_file_path}")
            print(f"Profile '{profile_name}' created successfully at {profile_file_path}")
            
            return profile_file_path
        except Exception as e:
            log_error(f"ProfileManager: Error creating profile file {profile_file_path}: {e}")
            print(f"Error: Failed to create profile file: {e}")
            return None
    
    def _format_multiline_strings_for_yaml(self, profile_data: Dict) -> Dict:
        """
        Convert multiline string fields to LiteralStr for better YAML formatting.
        
        This ensures that fields like system_prompt and welcome_message are written
        as literal block scalars (|) instead of quoted strings with escape sequences.
        
        Args:
            profile_data: The profile data dictionary
            
        Returns:
            A new dictionary with multiline strings formatted as LiteralStr
        """
        import copy
        
        # List of fields that should use literal block scalar formatting
        multiline_fields = {'system_prompt', 'welcome_message'}
        
        # Create a deep copy to avoid modifying the original
        formatted_data = copy.deepcopy(profile_data)
        
        for field in multiline_fields:
            if field in formatted_data and isinstance(formatted_data[field], str):
                # Check if the string contains newlines or is long enough to benefit from literal formatting
                value = formatted_data[field]
                if '\n' in value or len(value) > 80:
                    formatted_data[field] = LiteralStr(value)
        
        return formatted_data
    
    def _inject_workspace_variables(self, profile_data: Dict, workspace_variables: Dict[str, str]) -> Dict:
        """
        Inject workspace variables into profile configuration.
        
        Args:
            profile_data: The profile data dictionary
            workspace_variables: Workspace variables to inject
            
        Returns:
            Profile data with workspace variables injected
        """
        # Create a copy to avoid modifying the original
        enhanced_profile = copy.deepcopy(profile_data)
        
        # Add workspace variables to the profile's variables
        if 'variables' not in enhanced_profile:
            enhanced_profile['variables'] = {}
        
        # Merge workspace variables (workspace variables take precedence)
        enhanced_profile['variables'].update(workspace_variables)
        
        log_debug(f"ProfileManager: Injected workspace variables: {workspace_variables}")
        
        return enhanced_profile
    
    def cleanup_old_files(self, max_age_hours: int = 24):
        """
        Clean up temporary files created by the profile manager.
        
        Args:
            max_age_hours: Maximum age in hours before a file is considered old
        """
        # Clean up temporary MCP config files
        config_dir = os.path.join(tempfile.gettempdir(), "aris_profiles")
        if not os.path.exists(config_dir):
            return
        
        import time
        current_time = time.time()
        
        for file in os.listdir(config_dir):
            if file.startswith("mcp_config_") and file.endswith(".json"):
                file_path = os.path.join(config_dir, file)
                file_age = current_time - os.path.getmtime(file_path)
                
                if file_age > max_age_hours * 3600:
                    try:
                        os.remove(file_path)
                        log_debug(f"ProfileManager: Removed old temp file: {file_path}")
                    except Exception as e:
                        log_warning(f"ProfileManager: Failed to remove old temp file {file_path}: {e}")


# Initialize the profile manager on module import
profile_manager = ProfileManager()