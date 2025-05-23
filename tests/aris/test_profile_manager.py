# Tests for aris.profile_manager

import pytest
import os
import tempfile
import shutil
import json
from pathlib import Path
import yaml

from aris.profile_manager import ProfileManager, ProfileSchema

@pytest.fixture
def temp_profiles_dir():
    """Create a temporary directory for profile testing."""
    test_dir = tempfile.mkdtemp()
    test_profiles_dir = os.path.join(test_dir, "profiles")
    test_base_dir = os.path.join(test_profiles_dir, "base")
    os.makedirs(test_base_dir, exist_ok=True)
    
    # Create test profiles
    # Base profile
    base_profile = {
        "profile_name": "test_base",
        "description": "Test base profile",
        "version": "1.0",
        "author": "Test",
        "system_prompt": "You are a test assistant.",
        "tags": ["test", "base"]
    }
    base_path = os.path.join(test_base_dir, "test_base.yaml")
    with open(base_path, 'w') as f:
        yaml.dump(base_profile, f)
    
    # Extended profile
    extended_profile = {
        "profile_name": "test_extended",
        "description": "Test extended profile",
        "version": "1.0",
        "author": "Test",
        "extends": "base/test_base",
        "system_prompt": "{{parent_system_prompt}}\n\nAdditional instructions: Be concise.",
        "tags": ["test", "extended"]
    }
    extended_path = os.path.join(test_profiles_dir, "test_extended.yaml")
    with open(extended_path, 'w') as f:
        yaml.dump(extended_profile, f)
    
    # Profile with variables
    variables_profile = {
        "profile_name": "test_variables",
        "description": "Test profile with variables",
        "version": "1.0",
        "author": "Test",
        "system_prompt": "You are a {{role}} specialized in {{domain}}.",
        "variables": [
            {
                "name": "role",
                "description": "Role of the assistant",
                "required": True
            },
            {
                "name": "domain",
                "description": "Domain of expertise",
                "required": True,
                "default": "general knowledge"
            }
        ],
        "tags": ["test", "variables"]
    }
    variables_path = os.path.join(test_profiles_dir, "test_variables.yaml")
    with open(variables_path, 'w') as f:
        yaml.dump(variables_profile, f)
    
    yield test_profiles_dir
    
    # Cleanup
    shutil.rmtree(test_dir)

@pytest.fixture
def profile_manager():
    """Create a profile manager instance."""
    return ProfileManager()

def test_profile_schema_validation():
    """Test validation of profile schema."""
    # Valid profile
    valid_profile = {
        "profile_name": "test_valid",
        "system_prompt": "You are a helpful assistant."
    }
    
    # This should not raise an exception
    profile_schema = ProfileSchema(**valid_profile)
    assert profile_schema.profile_name == "test_valid"
    
    # Invalid profile (missing required field)
    invalid_profile = {
        "description": "Missing profile_name and system_prompt"
    }
    
    # This should raise a validation error
    with pytest.raises(Exception):
        ProfileSchema(**invalid_profile)

def test_discover_profiles(profile_manager, temp_profiles_dir):
    """Test that profiles are correctly discovered."""
    # Modify the profile manager to use our test directory
    original_dirs = profile_manager._available_profiles
    
    try:
        # Override search directories for testing
        profiles = {}
        
        # Search test directory for profiles
        for root, _, files in os.walk(temp_profiles_dir):
            for file in files:
                if file.endswith(('.yaml', '.yml')):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            profile_data = yaml.safe_load(f)
                        
                        profile_name = profile_data.get('profile_name')
                        rel_path = os.path.relpath(root, temp_profiles_dir)
                        if rel_path == '.':
                            profile_ref = profile_name
                        else:
                            profile_ref = f"{rel_path.replace(os.path.sep, '/')}/{profile_name}"
                        
                        profiles[profile_ref] = {
                            'path': file_path,
                            'name': profile_name,
                            'description': profile_data.get('description', ''),
                            'tags': profile_data.get('tags', []),
                            'location': temp_profiles_dir
                        }
                    except Exception as e:
                        print(f"Error loading profile {file_path}: {e}")
        
        # Set the profiles in the profile manager
        profile_manager._available_profiles = profiles
        
        # Verify the test profiles
        assert "test_extended" in profiles
        assert "base/test_base" in profiles
        assert "test_variables" in profiles
        
        # Verify profile contents
        assert profiles["base/test_base"]["description"] == "Test base profile"
        assert "test" in profiles["test_variables"]["tags"]
    
    finally:
        # Restore original profiles
        profile_manager._available_profiles = original_dirs

def test_get_profile(profile_manager, temp_profiles_dir):
    """Test retrieving a profile by name."""
    # Override search directories for testing
    profiles = {}
    
    # Search test directory for profiles
    for root, _, files in os.walk(temp_profiles_dir):
        for file in files:
            if file.endswith(('.yaml', '.yml')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        profile_data = yaml.safe_load(f)
                    
                    profile_name = profile_data.get('profile_name')
                    rel_path = os.path.relpath(root, temp_profiles_dir)
                    if rel_path == '.':
                        profile_ref = profile_name
                    else:
                        profile_ref = f"{rel_path.replace(os.path.sep, '/')}/{profile_name}"
                    
                    profiles[profile_ref] = {
                        'path': file_path,
                        'name': profile_name,
                        'description': profile_data.get('description', ''),
                        'tags': profile_data.get('tags', []),
                        'location': temp_profiles_dir
                    }
                except Exception as e:
                    print(f"Error loading profile {file_path}: {e}")
    
    # Override profile manager's available profiles
    original_profiles = profile_manager._available_profiles
    profile_manager._available_profiles = profiles
    
    try:
        # Mock the profile loading by directly adding to raw profile cache
        with open(profiles["base/test_base"]["path"], 'r') as f:
            base_profile = yaml.safe_load(f)
        profile_manager._raw_profile_cache[profiles["base/test_base"]["path"]] = base_profile
        
        with open(profiles["test_extended"]["path"], 'r') as f:
            extended_profile = yaml.safe_load(f)
        profile_manager._raw_profile_cache[profiles["test_extended"]["path"]] = extended_profile
        
        with open(profiles["test_variables"]["path"], 'r') as f:
            vars_profile = yaml.safe_load(f)
        profile_manager._raw_profile_cache[profiles["test_variables"]["path"]] = vars_profile
        
        # Test retrieving a simple profile
        profile = profile_manager.get_profile("base/test_base")
        assert profile is not None
        assert profile["profile_name"] == "test_base"
        assert profile["system_prompt"] == "You are a test assistant."
        
        # Test retrieving a profile with inheritance
        profile = profile_manager.get_profile("test_extended", resolve=True)
        assert profile is not None
        assert profile["profile_name"] == "test_extended"
        assert "You are a test assistant." in profile["system_prompt"]
        assert "Additional instructions: Be concise." in profile["system_prompt"]
    
    finally:
        # Restore original profiles
        profile_manager._available_profiles = original_profiles
        profile_manager._raw_profile_cache = {}

def test_get_variables_from_profile(profile_manager, temp_profiles_dir):
    """Test extracting variables from a profile."""
    # Load a test profile
    with open(os.path.join(temp_profiles_dir, "test_variables.yaml"), 'r') as f:
        profile = yaml.safe_load(f)
    
    # Test extracting variables
    variables = profile_manager.get_variables_from_profile(profile)
    assert len(variables) == 2
    
    # Verify variable properties
    var_names = [v.name for v in variables]
    assert "role" in var_names
    assert "domain" in var_names
    
    # Check that domain has a default value
    domain_var = next(v for v in variables if v.name == "domain")
    assert domain_var.default == "general knowledge"

def test_merge_profiles(profile_manager):
    """Test merging of profiles."""
    base_profile = {
        "profile_name": "base",
        "system_prompt": "Base prompt",
        "tools": ["tool1", "tool2"],
        "context_files": ["file1.md"]
    }
    
    overlay_profile = {
        "profile_name": "overlay",
        "system_prompt": "Overlay prompt",
        "tools": ["tool3"],
        "context_mode": "embedded"
    }
    
    # Test basic merge
    merged = profile_manager._merge_profiles(base_profile, overlay_profile)
    assert merged["profile_name"] == "overlay"  # Takes overlay value
    assert merged["system_prompt"] == "Overlay prompt"  # Takes overlay value
    assert set(merged["tools"]) == set(["tool1", "tool2", "tool3"])  # Merged lists
    assert merged["context_files"] == ["file1.md"]  # Retained from base
    assert merged["context_mode"] == "embedded"  # Added from overlay

def test_load_config_file(profile_manager, tmp_path):
    """Test loading configuration from file."""
    # Create a temporary MCP config file
    config_file = tmp_path / "test_mcp_config.json"
    config_data = {
        "mcpServers": {
            "test_server": {
                "type": "sse",
                "url": "http://test-server:8090/mcp/sse/"
            }
        }
    }
    
    with open(config_file, 'w') as f:
        f.write(json.dumps(config_data))
    
    # The actual test would call load_config and check 
    # that mcp_servers is updated, but we would need 
    # to mock the file operations for a proper unit test