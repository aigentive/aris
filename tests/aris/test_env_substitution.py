"""
Tests for environment variable substitution in MCP configurations.
"""
import pytest
import os
from unittest.mock import patch
from aris.profile_manager import ProfileManager


class TestEnvSubstitution:
    """Test environment variable substitution functionality."""
    
    @pytest.fixture
    def profile_manager(self):
        """Create a ProfileManager instance for testing."""
        return ProfileManager()
    
    @pytest.fixture
    def test_config(self):
        """Create a test MCP config with environment variables."""
        return {
            "description": "Test config with env vars",
            "mcpServers": {
                "openai-image-mcp": {
                    "type": "stdio",
                    "command": "poetry",
                    "args": ["run", "python", "-m", "openai_image_mcp.server"],
                    "cwd": "/Users/lazabogdan/Code/openai-image-mcp",
                    "env": {
                        "OPENAI_API_KEY": "${TEST_OPENAI_API_KEY}",
                        "LOG_LEVEL": "${TEST_LOG_LEVEL:-INFO}",
                        "FALLBACK_VAR": "${NONEXISTENT_VAR:-fallback_value}",
                        "MISSING_VAR": "${MISSING_NO_DEFAULT}"
                    }
                },
                "test-server": {
                    "type": "stdio", 
                    "command": "${TEST_OPENAI_API_KEY}",
                    "args": ["--log-level", "${TEST_LOG_LEVEL}"],
                    "env": {
                        "NESTED_PATH": "/path/to/${TEST_LOG_LEVEL}/config"
                    }
                }
            }
        }
    
    def test_basic_env_var_substitution(self, profile_manager, test_config):
        """Test basic environment variable substitution."""
        with patch.dict(os.environ, {
            'TEST_OPENAI_API_KEY': 'sk-test-123456789',
            'TEST_LOG_LEVEL': 'DEBUG'
        }):
            result = profile_manager._substitute_env_variables(test_config)
            
            openai_server = result["mcpServers"]["openai-image-mcp"]
            assert openai_server["env"]["OPENAI_API_KEY"] == "sk-test-123456789"
            assert openai_server["env"]["LOG_LEVEL"] == "DEBUG"
    
    def test_default_value_substitution(self, profile_manager, test_config):
        """Test substitution with default values."""
        with patch.dict(os.environ, {}, clear=True):
            result = profile_manager._substitute_env_variables(test_config)
            
            openai_server = result["mcpServers"]["openai-image-mcp"]
            # Should use default value when env var not set
            assert openai_server["env"]["LOG_LEVEL"] == "INFO"
            assert openai_server["env"]["FALLBACK_VAR"] == "fallback_value"
    
    def test_missing_env_var_no_default(self, profile_manager, test_config):
        """Test behavior when env var missing and no default provided."""
        with patch.dict(os.environ, {}, clear=True):
            result = profile_manager._substitute_env_variables(test_config)
            
            openai_server = result["mcpServers"]["openai-image-mcp"]
            # Should be empty string when no default and var not set
            assert openai_server["env"]["MISSING_VAR"] == ""
    
    def test_nested_substitution(self, profile_manager, test_config):
        """Test substitution in nested structures."""
        with patch.dict(os.environ, {
            'TEST_OPENAI_API_KEY': 'sk-test-123456789',
            'TEST_LOG_LEVEL': 'DEBUG'
        }):
            result = profile_manager._substitute_env_variables(test_config)
            
            test_server = result["mcpServers"]["test-server"]
            assert test_server["command"] == "sk-test-123456789"
            assert test_server["args"][1] == "DEBUG"
            assert test_server["env"]["NESTED_PATH"] == "/path/to/DEBUG/config"
    
    def test_non_string_values_unchanged(self, profile_manager):
        """Test that non-string values are not modified."""
        test_config = {
            "mcpServers": {
                "test": {
                    "port": 8080,
                    "enabled": True,
                    "timeout": 30.5,
                    "items": ["item1", "${TEST_VAR}", "item3"]
                }
            }
        }
        
        with patch.dict(os.environ, {'TEST_VAR': 'replaced'}):
            result = profile_manager._substitute_env_variables(test_config)
            
            test_server = result["mcpServers"]["test"]
            assert test_server["port"] == 8080
            assert test_server["enabled"] is True
            assert test_server["timeout"] == 30.5
            assert test_server["items"][1] == "replaced"  # String in list should be substituted
    
    def test_original_config_unchanged(self, profile_manager, test_config):
        """Test that original config is not modified."""
        original_api_key = test_config["mcpServers"]["openai-image-mcp"]["env"]["OPENAI_API_KEY"]
        
        with patch.dict(os.environ, {'TEST_OPENAI_API_KEY': 'sk-test-123456789'}):
            result = profile_manager._substitute_env_variables(test_config)
            
            # Original should be unchanged
            assert test_config["mcpServers"]["openai-image-mcp"]["env"]["OPENAI_API_KEY"] == original_api_key
            # Result should be substituted
            assert result["mcpServers"]["openai-image-mcp"]["env"]["OPENAI_API_KEY"] == "sk-test-123456789"
    
    def test_complex_env_var_patterns(self, profile_manager):
        """Test various environment variable patterns."""
        test_config = {
            "mcpServers": {
                "test": {
                    "env": {
                        "SIMPLE": "${SIMPLE_VAR}",
                        "WITH_DEFAULT": "${VAR_WITH_DEFAULT:-default}",
                        "EMPTY_DEFAULT": "${EMPTY_DEFAULT:-}",
                        "MIXED": "prefix_${MIX_VAR}_suffix",
                        "MULTIPLE": "${VAR1}/${VAR2:-default2}",
                        "NO_BRACES": "$VAR_NO_BRACES"  # Should not be substituted
                    }
                }
            }
        }
        
        with patch.dict(os.environ, {
            'SIMPLE_VAR': 'simple_value',
            'MIX_VAR': 'mixed',
            'VAR1': 'value1'
        }):
            result = profile_manager._substitute_env_variables(test_config)
            
            env_vars = result["mcpServers"]["test"]["env"]
            assert env_vars["SIMPLE"] == "simple_value"
            assert env_vars["WITH_DEFAULT"] == "default"
            assert env_vars["EMPTY_DEFAULT"] == ""
            assert env_vars["MIXED"] == "prefix_mixed_suffix"
            assert env_vars["MULTIPLE"] == "value1/default2"
            assert env_vars["NO_BRACES"] == "$VAR_NO_BRACES"  # Should remain unchanged