"""
Tests for YAML multiline string formatting in profile creation.
"""
import pytest
import yaml
from aris.profile_manager import ProfileManager, LiteralStr


class TestYAMLMultilineFormatting:
    """Test YAML multiline string formatting functionality."""
    
    @pytest.fixture
    def profile_manager(self):
        """Create a ProfileManager instance for testing."""
        return ProfileManager()
    
    def test_literal_str_class(self):
        """Test that LiteralStr class works correctly."""
        # Create a LiteralStr instance
        literal_str = LiteralStr("Line 1\nLine 2\nLine 3")
        
        # It should behave like a regular string
        assert str(literal_str) == "Line 1\nLine 2\nLine 3"
        assert isinstance(literal_str, str)
        assert isinstance(literal_str, LiteralStr)
    
    def test_yaml_literal_representer(self):
        """Test that LiteralStr is represented as literal block scalar in YAML."""
        test_data = {
            "regular_string": "Single line",
            "literal_string": LiteralStr("Line 1\nLine 2\nLine 3")
        }
        
        yaml_output = yaml.dump(test_data, default_flow_style=False, sort_keys=False)
        
        # Regular string should be quoted or on single line
        assert "regular_string: Single line" in yaml_output
        
        # Literal string should use block scalar notation
        assert "literal_string: |-" in yaml_output or "literal_string: |" in yaml_output
        assert "Line 1" in yaml_output
        assert "Line 2" in yaml_output
        assert "Line 3" in yaml_output
    
    def test_format_multiline_strings_for_yaml_with_newlines(self, profile_manager):
        """Test that strings with newlines are converted to LiteralStr."""
        profile_data = {
            "profile_name": "test",
            "system_prompt": "You are helpful.\n\nBe concise.\nBe accurate.",
            "welcome_message": "Welcome!\n\nLet's get started.",
            "short_field": "No newlines here"
        }
        
        result = profile_manager._format_multiline_strings_for_yaml(profile_data)
        
        # Fields with newlines should be converted to LiteralStr
        assert isinstance(result["system_prompt"], LiteralStr)
        assert isinstance(result["welcome_message"], LiteralStr)
        
        # Fields without newlines should remain as regular strings
        assert isinstance(result["short_field"], str)
        assert not isinstance(result["short_field"], LiteralStr)
        
        # Profile name should remain unchanged
        assert isinstance(result["profile_name"], str)
        assert not isinstance(result["profile_name"], LiteralStr)
    
    def test_format_multiline_strings_for_yaml_with_long_strings(self, profile_manager):
        """Test that long strings (>80 chars) are converted to LiteralStr even without newlines."""
        long_string = "This is a very long string that exceeds 80 characters and should be formatted as a literal block scalar for better readability in YAML files."
        
        profile_data = {
            "system_prompt": long_string,
            "welcome_message": "Short message",
            "other_field": "Also short"
        }
        
        result = profile_manager._format_multiline_strings_for_yaml(profile_data)
        
        # Long string should be converted to LiteralStr
        assert isinstance(result["system_prompt"], LiteralStr)
        
        # Short strings should remain as regular strings
        assert isinstance(result["welcome_message"], str)
        assert not isinstance(result["welcome_message"], LiteralStr)
    
    def test_format_multiline_strings_preserves_other_fields(self, profile_manager):
        """Test that non-string fields are preserved unchanged."""
        profile_data = {
            "profile_name": "test",
            "system_prompt": "Multi\nline\nstring",
            "tools": ["tool1", "tool2"],
            "variables": [{"name": "var1", "default": "value1"}],
            "enabled": True,
            "priority": 5
        }
        
        result = profile_manager._format_multiline_strings_for_yaml(profile_data)
        
        # system_prompt should be converted
        assert isinstance(result["system_prompt"], LiteralStr)
        
        # Other fields should remain unchanged
        assert result["tools"] == ["tool1", "tool2"]
        assert result["variables"] == [{"name": "var1", "default": "value1"}]
        assert result["enabled"] is True
        assert result["priority"] == 5
    
    def test_format_multiline_strings_deep_copy(self, profile_manager):
        """Test that the original profile data is not modified."""
        original_data = {
            "system_prompt": "Multi\nline\nstring",
            "welcome_message": "Another\nmulti\nline\nstring"
        }
        
        # Keep reference to original strings
        original_system_prompt = original_data["system_prompt"]
        original_welcome_message = original_data["welcome_message"]
        
        result = profile_manager._format_multiline_strings_for_yaml(original_data)
        
        # Result should have LiteralStr objects
        assert isinstance(result["system_prompt"], LiteralStr)
        assert isinstance(result["welcome_message"], LiteralStr)
        
        # Original data should be unchanged
        assert isinstance(original_data["system_prompt"], str)
        assert isinstance(original_data["welcome_message"], str)
        assert not isinstance(original_data["system_prompt"], LiteralStr)
        assert not isinstance(original_data["welcome_message"], LiteralStr)
        
        # Content should be the same
        assert str(result["system_prompt"]) == original_system_prompt
        assert str(result["welcome_message"]) == original_welcome_message
    
    def test_format_multiline_strings_handles_missing_fields(self, profile_manager):
        """Test that missing multiline fields are handled gracefully."""
        profile_data = {
            "profile_name": "test",
            "description": "Test profile"
            # Missing system_prompt and welcome_message
        }
        
        result = profile_manager._format_multiline_strings_for_yaml(profile_data)
        
        # Should not crash and should return the same data
        assert result["profile_name"] == "test"
        assert result["description"] == "Test profile"
        assert "system_prompt" not in result
        assert "welcome_message" not in result
    
    def test_full_yaml_output_formatting(self, profile_manager):
        """Test complete YAML output with realistic profile data."""
        profile_data = {
            "profile_name": "image-generator",
            "description": "AI Image Generation Profile",
            "system_prompt": "You are an AI image generation assistant.\n\nYou help users create images using various AI models.\n\nCapabilities:\n• Generate images from text descriptions\n• Edit existing images\n• Provide creative suggestions",
            "welcome_message": "🎨 Welcome to AI Image Generation!\n\nI'm specialized in creating images using OpenAI's GPT-Image-1 model.\n\n🖼️ Available Tools:\n• Generate new images\n• Edit existing images\n\nReady to create amazing images!",
            "tools": ["mcp__image_gen", "mcp__image_edit"],
            "tags": ["image", "generation", "creative"]
        }
        
        formatted_data = profile_manager._format_multiline_strings_for_yaml(profile_data)
        yaml_output = yaml.dump(formatted_data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        
        # Verify that multiline strings use block scalar notation
        assert "system_prompt: |-" in yaml_output or "system_prompt: |" in yaml_output
        assert "welcome_message: |-" in yaml_output or "welcome_message: |" in yaml_output
        
        # Verify content is preserved
        assert "You are an AI image generation assistant." in yaml_output
        assert "🎨 Welcome to AI Image Generation!" in yaml_output
        
        # Verify other fields use regular formatting
        assert "profile_name: image-generator" in yaml_output
        assert "- mcp__image_gen" in yaml_output
        assert "- image" in yaml_output