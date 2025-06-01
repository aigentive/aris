"""
Tests for enhanced response formatting in non-interactive mode.
"""
import pytest
from unittest.mock import MagicMock
from aris.cli import format_non_interactive_response


class TestFormatNonInteractiveResponse:
    """Test the non-interactive response formatting function."""
    
    def test_empty_response(self):
        """Test formatting empty response."""
        session_state = MagicMock()
        
        result = format_non_interactive_response("", session_state)
        
        assert result == ""
    
    def test_whitespace_only_response(self):
        """Test formatting whitespace-only response."""
        session_state = MagicMock()
        
        result = format_non_interactive_response("   \n\t  ", session_state)
        
        assert result == ""
    
    def test_single_line_response_default_profile(self):
        """Test formatting single line response with default profile."""
        session_state = MagicMock()
        session_state.active_profile = None
        
        result = format_non_interactive_response("Hello world!", session_state)
        
        assert result == "🤖 aris: Hello world!"
    
    def test_single_line_response_custom_profile(self):
        """Test formatting single line response with custom profile."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "developer"}
        
        result = format_non_interactive_response("Code analysis complete", session_state)
        
        assert result == "🤖 developer: Code analysis complete"
    
    def test_multiline_response_formatting(self):
        """Test formatting multi-line response with proper indentation."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "assistant"}
        response = """First line of response
Second line here
Third line with more content"""
        
        result = format_non_interactive_response(response, session_state)
        
        lines = result.split('\n')
        prefix_length = len("🤖 assistant: ")
        expected_indent = " " * prefix_length
        
        assert lines[0] == "🤖 assistant: First line of response"
        assert lines[1] == expected_indent + "Second line here"
        assert lines[2] == expected_indent + "Third line with more content"
    
    def test_multiline_with_empty_lines(self):
        """Test formatting response with empty lines."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "test"}
        response = """First line

Second line after empty line

Third line"""
        
        result = format_non_interactive_response(response, session_state)
        
        lines = result.split('\n')
        prefix_length = len("🤖 test: ")
        expected_indent = " " * prefix_length
        
        assert lines[0] == "🤖 test: First line"
        assert lines[1] == ""  # Empty line preserved
        assert lines[2] == expected_indent + "Second line after empty line"
        assert lines[3] == ""  # Empty line preserved
        assert lines[4] == expected_indent + "Third line"
    
    def test_session_state_without_active_profile(self):
        """Test handling session state without active_profile attribute."""
        session_state = MagicMock()
        del session_state.active_profile  # Remove the attribute
        
        result = format_non_interactive_response("Test message", session_state)
        
        assert result == "🤖 aris: Test message"
    
    def test_none_session_state(self):
        """Test handling None session state."""
        result = format_non_interactive_response("Test message", None)
        
        assert result == "🤖 aris: Test message"
    
    def test_profile_without_name(self):
        """Test handling profile without profile_name."""
        session_state = MagicMock()
        session_state.active_profile = {}  # Empty profile
        
        result = format_non_interactive_response("Test message", session_state)
        
        assert result == "🤖 aris: Test message"
    
    def test_indentation_calculation(self):
        """Test that indentation is calculated correctly for alignment."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "very_long_profile_name"}
        response = "First line\nSecond line"
        
        result = format_non_interactive_response(response, session_state)
        
        lines = result.split('\n')
        first_line = lines[0]
        second_line = lines[1]
        
        # Calculate expected indentation
        prefix_length = len("🤖 very_long_profile_name: ")
        expected_indent = " " * prefix_length
        
        assert first_line == "🤖 very_long_profile_name: First line"
        assert second_line == expected_indent + "Second line"
    
    def test_complex_multiline_response(self):
        """Test complex multi-line response with various content."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "data_analyst"}
        response = """Data Analysis Results:

1. Total records processed: 1,542
2. Average response time: 2.3ms
3. Error rate: 0.02%

Recommendations:
- Optimize database queries
- Implement caching layer
- Monitor error patterns

Next steps will be provided shortly."""
        
        result = format_non_interactive_response(response, session_state)
        
        lines = result.split('\n')
        prefix_length = len("🤖 data_analyst: ")
        indent = " " * prefix_length
        
        # Check first line has prefix
        assert lines[0] == "🤖 data_analyst: Data Analysis Results:"
        
        # Check subsequent lines are properly indented
        # Let's debug what the actual line numbers are
        for i, line in enumerate(lines):
            if "1. Total records processed:" in line:
                assert line == indent + "1. Total records processed: 1,542"
            if "Recommendations:" in line:
                assert line == indent + "Recommendations:"
            if "- Optimize database queries" in line:
                assert line == indent + "- Optimize database queries"
        
        # Check empty lines are preserved
        assert lines[1] == ""  # After first line
        assert lines[5] == ""  # After the numbered list
        assert lines[10] == ""  # After recommendations
    
    def test_code_block_formatting(self):
        """Test formatting responses containing code blocks."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "coder"}
        response = """Here's the Python function:

```python
def hello_world():
    print("Hello, World!")
    return True
```

This function prints a greeting."""
        
        result = format_non_interactive_response(response, session_state)
        
        lines = result.split('\n')
        prefix_length = len("🤖 coder: ")
        indent = " " * prefix_length
        
        assert lines[0] == "🤖 coder: Here's the Python function:"
        assert lines[2] == indent + "```python"
        assert lines[3] == indent + "def hello_world():"
        assert lines[4] == indent + '    print("Hello, World!")'
        assert lines[5] == indent + "    return True"
        assert lines[6] == indent + "```"
        assert lines[8] == indent + "This function prints a greeting."


class TestResponseFormattingIntegration:
    """Test response formatting integration scenarios."""
    
    def test_formatting_preserves_structure(self):
        """Test that formatting preserves the logical structure of responses."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "architect"}
        
        # Simulate a structured response from Claude
        response = """Project Structure Analysis:

/src
  /components
    - Header.tsx
    - Footer.tsx
  /utils
    - helpers.js
    - constants.js
/tests
  - unit.test.js
  - integration.test.js

Architecture recommendations:
1. Separate concerns properly
2. Implement proper error boundaries
3. Add comprehensive testing

Would you like me to elaborate on any of these points?"""
        
        result = format_non_interactive_response(response, session_state)
        
        # Should maintain readability while adding profile prefix
        lines = result.split('\n')
        assert "🤖 architect:" in lines[0]
        assert "/src" in result
        assert "Architecture recommendations:" in result
        assert "1. Separate concerns properly" in result
        
        # Indentation should be consistent
        indent_lines = [line for line in lines[1:] if line.strip()]
        if indent_lines:
            expected_indent = " " * len("🤖 architect: ")
            for line in indent_lines:
                if line.strip():  # Skip empty lines
                    assert line.startswith(expected_indent)
    
    def test_error_response_formatting(self):
        """Test formatting error responses appropriately."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "error_handler"}
        
        error_response = """Error: Unable to process request

Details:
- Invalid file format
- Missing required parameters
- Connection timeout

Please check your input and try again."""
        
        result = format_non_interactive_response(error_response, session_state)
        
        # Error responses should be formatted the same way
        assert result.startswith("🤖 error_handler: Error: Unable to process request")
        assert "Details:" in result
        assert "- Invalid file format" in result
    
    def test_unicode_content_handling(self):
        """Test handling of Unicode content in responses."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "linguist"}
        
        unicode_response = """Language Analysis: 🔍

Detected languages:
• English: 75% 🇺🇸
• Spanish: 20% 🇪🇸  
• French: 5% 🇫🇷

Confidence: 高 (High)
Next: 分析を続行 (Continue analysis)"""
        
        result = format_non_interactive_response(unicode_response, session_state)
        
        # Should handle Unicode characters properly
        assert "🤖 linguist: Language Analysis: 🔍" in result
        assert "• English: 75% 🇺🇸" in result
        assert "Confidence: 高 (High)" in result
        assert "Next: 分析を続行 (Continue analysis)" in result