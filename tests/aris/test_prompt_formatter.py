# Tests for aris.prompt_formatter

import pytest
from aris.prompt_formatter import PromptFormatter
from aris.profile_manager import profile_manager

@pytest.fixture
def formatter() -> PromptFormatter:
    return PromptFormatter()

def test_format_prompt(formatter: PromptFormatter):
    """Test that format_prompt correctly formats the user's message"""
    user_msg = "Tell me about workflows."
    prompt = formatter.format_prompt(user_msg)
    assert f"<current_user_message_for_this_turn>\n{user_msg}\n</current_user_message_for_this_turn>" in prompt

def test_format_prompt_with_empty_message(formatter: PromptFormatter):
    """Test that format_prompt works with an empty user message"""
    user_msg = ""
    prompt = formatter.format_prompt(user_msg)
    assert "<current_user_message_for_this_turn>\n\n</current_user_message_for_this_turn>" in prompt

def test_prompt_template_structure(formatter: PromptFormatter):
    """Test that the prompt template contains the required placeholder"""
    assert "{current_turn_message_placeholder}" in formatter.PROMPT_TEMPLATE

def test_prepare_system_prompt(formatter: PromptFormatter):
    """Test that prepare_system_prompt properly formats the system prompt"""
    system_prompt = "This is a system prompt with a {{variable}}"
    template_variables = {"variable": "test value"}
    
    processed_prompt, reference_file = formatter.prepare_system_prompt(
        profile_system_prompt=system_prompt,
        template_variables=template_variables
    )
    
    assert "This is a system prompt with a test value" == processed_prompt
    assert reference_file is None

def test_prepare_system_prompt_with_empty_prompt(formatter: PromptFormatter):
    """Test that prepare_system_prompt handles an empty system prompt"""
    processed_prompt, reference_file = formatter.prepare_system_prompt(
        profile_system_prompt=""
    )
    
    assert processed_prompt == ""
    assert reference_file is None

def test_modify_first_message(formatter: PromptFormatter):
    """Test that modify_first_message adds instructions to read the reference file"""
    user_msg = "Hello, how are you?"
    reference_file_path = "/tmp/reference.txt"
    
    modified_msg = formatter.modify_first_message(user_msg, reference_file_path)
    
    assert reference_file_path in modified_msg
    assert "Read tool" in modified_msg
    assert user_msg in modified_msg

def test_modify_first_message_with_no_reference(formatter: PromptFormatter):
    """Test that modify_first_message returns the original message if no reference file"""
    user_msg = "Hello, how are you?"
    
    modified_msg = formatter.modify_first_message(user_msg, None)
    
    assert modified_msg == user_msg

def test_profiles_exist_for_all_sections():
    """Test that all required profile files exist and can be loaded."""
    required_profiles = [
        "base/default_assistant_instructions",
        "base/manager_guide",
        "base/create_workflow_rules",
        "base/run_workflow_rules",
        "base/sdk_manager_interaction_rules",
        "base/wizard_operator_rules"
    ]
    
    for profile_ref in required_profiles:
        profile = profile_manager.get_profile(profile_ref, resolve=False)
        assert profile is not None, f"Required profile '{profile_ref}' not found"
        assert "system_prompt" in profile, f"Profile '{profile_ref}' does not have a system_prompt field"
        assert profile.get("system_prompt"), f"Profile '{profile_ref}' has an empty system_prompt"