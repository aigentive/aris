#!/usr/bin/env python3

import pytest
from aris.profile_manager import profile_manager


class TestProfileInheritanceFix:
    """Test that profile inheritance works correctly for tools and mcp_config_files."""
    
    def test_inheritance_without_explicit_keys_real_profiles(self):
        """Test inheritance using real ARIS profiles without explicit key declarations."""
        
        # Test base/master profile has tools and configs
        base_profile = profile_manager.get_profile('base/master', resolve=True)
        assert base_profile is not None
        assert 'execute_workflow_phase' in base_profile.get('tools', [])
        assert 'configs/workflow_orchestrator.mcp-servers.json' in base_profile.get('mcp_config_files', [])
        
        # Test content orchestrator inherits without explicit declarations
        content_profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        assert content_profile is not None
        
        # Should inherit all tools from base/master
        base_tools = set(base_profile.get('tools', []))
        content_tools = set(content_profile.get('tools', []))
        assert base_tools.issubset(content_tools)  # All base tools should be inherited
        assert 'execute_workflow_phase' in content_tools
        
        # Should inherit MCP configs from base/master
        base_configs = set(base_profile.get('mcp_config_files', []))
        content_configs = set(content_profile.get('mcp_config_files', []))
        assert base_configs.issubset(content_configs)  # All base configs should be inherited
        assert 'configs/workflow_orchestrator.mcp-servers.json' in content_configs
    
    def test_inheritance_behavior_with_merge_profiles(self):
        """Test inheritance behavior directly using _merge_profiles method."""
        
        # Create parent profile with tools and configs
        parent = {
            "profile_name": "test_parent",
            "description": "Test parent profile",
            "system_prompt": "Parent system prompt",
            "tools": ["parent_tool1", "parent_tool2", "Read", "Write"],
            "mcp_config_files": ["configs/parent1.json", "configs/parent2.json"]
        }
        
        # Test case 1: Child with missing keys (should inherit everything)
        child_missing = {
            "profile_name": "child_missing_keys",
            "extends": ["test_parent"],
            "system_prompt": "{{parent_system_prompt}} Child content"
            # No tools or mcp_config_files declared
        }
        
        result_missing = profile_manager._merge_profiles(parent, child_missing)
        
        # Should inherit parent tools and configs completely
        assert result_missing.get('tools') == parent['tools']
        assert result_missing.get('mcp_config_files') == parent['mcp_config_files']
        
        # Test case 2: Child with empty lists (should also inherit everything)
        child_empty = {
            "profile_name": "child_empty_lists",
            "extends": ["test_parent"],
            "system_prompt": "{{parent_system_prompt}} Child content",
            "tools": [],  # Empty list
            "mcp_config_files": []  # Empty list
        }
        
        result_empty = profile_manager._merge_profiles(parent, child_empty)
        
        # Should inherit parent tools and configs (empty lists should not override)
        assert result_empty.get('tools') == parent['tools']
        assert result_empty.get('mcp_config_files') == parent['mcp_config_files']
        
        # Test case 3: Child with additional items (should merge)
        child_additional = {
            "profile_name": "child_additional",
            "extends": ["test_parent"],
            "system_prompt": "{{parent_system_prompt}} Child content",
            "tools": ["child_tool"],
            "mcp_config_files": ["configs/child.json"]
        }
        
        result_additional = profile_manager._merge_profiles(parent, child_additional)
        
        # Should have parent + child items
        expected_tools = parent['tools'] + child_additional['tools']
        expected_configs = parent['mcp_config_files'] + child_additional['mcp_config_files']
        
        assert set(result_additional.get('tools', [])) == set(expected_tools)
        assert set(result_additional.get('mcp_config_files', [])) == set(expected_configs)
    
    def test_inheritance_merge_directives(self):
        """Test inheritance with merge directives like !REPLACE and !PREPEND."""
        
        parent = {
            "profile_name": "directive_parent",
            "tools": ["parent_tool1", "parent_tool2"],
            "mcp_config_files": ["configs/parent.json"]
        }
        
        # Test !REPLACE directive
        child_replace = {
            "profile_name": "child_replace",
            "extends": ["directive_parent"],
            "tools": ["!REPLACE", "only_child_tool"],
            "mcp_config_files": ["!REPLACE", "configs/only_child.json"]
        }
        
        result_replace = profile_manager._merge_profiles(parent, child_replace)
        
        # Should completely replace parent lists
        assert result_replace.get('tools') == ["only_child_tool"]
        assert result_replace.get('mcp_config_files') == ["configs/only_child.json"]
        
        # Test !PREPEND directive
        child_prepend = {
            "profile_name": "child_prepend",
            "extends": ["directive_parent"],
            "tools": ["!PREPEND", "first_tool", "second_tool"],
            "mcp_config_files": ["!PREPEND", "configs/first.json"]
        }
        
        result_prepend = profile_manager._merge_profiles(parent, child_prepend)
        
        # Should prepend child items before parent items
        expected_tools = ["first_tool", "second_tool"] + parent['tools']
        expected_configs = ["configs/first.json"] + parent['mcp_config_files']
        
        assert result_prepend.get('tools') == expected_tools
        assert result_prepend.get('mcp_config_files') == expected_configs
    
    def test_inheritance_with_mixed_scenarios(self):
        """Test inheritance with mix of missing keys and declared keys."""
        
        parent = {
            "profile_name": "mixed_parent",
            "tools": ["parent_tool"],
            "mcp_config_files": ["configs/parent.json"],
            "custom_field": ["parent_custom"]
        }
        
        # Child has tools but missing mcp_config_files
        child_mixed = {
            "profile_name": "child_mixed",
            "extends": ["mixed_parent"],
            "tools": ["child_tool"],  # Has tools
            # Missing mcp_config_files - should inherit
            "custom_field": []  # Empty list - should inherit
        }
        
        result_mixed = profile_manager._merge_profiles(parent, child_mixed)
        
        # Should merge tools (has both parent and child)
        expected_tools = parent['tools'] + child_mixed['tools']
        assert set(result_mixed.get('tools', [])) == set(expected_tools)
        
        # Should inherit mcp_config_files from parent (key was missing)
        assert result_mixed.get('mcp_config_files') == parent['mcp_config_files']
        
        # Should inherit custom_field from parent (empty list)
        assert result_mixed.get('custom_field') == parent['custom_field']
    
    def test_content_orchestrator_clean_inheritance(self):
        """Test that content orchestrator works cleanly without explicit tool declarations."""
        
        # Get raw profile (before inheritance resolution)
        raw_profile = profile_manager.get_profile('composite/content_orchestrator', resolve=False)
        
        # Should not have explicit tools or mcp_config_files declarations
        assert raw_profile.get('tools') is None or raw_profile.get('tools') == []
        assert raw_profile.get('mcp_config_files') is None or raw_profile.get('mcp_config_files') == []
        
        # Get resolved profile (after inheritance)
        resolved_profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        
        # Should have inherited tools and configs from base/master
        assert len(resolved_profile.get('tools', [])) > 0
        assert 'execute_workflow_phase' in resolved_profile.get('tools', [])
        assert 'configs/workflow_orchestrator.mcp-servers.json' in resolved_profile.get('mcp_config_files', [])
        
        # Should inherit all base tools
        base_profile = profile_manager.get_profile('base/master', resolve=True)
        base_tools = set(base_profile.get('tools', []))
        resolved_tools = set(resolved_profile.get('tools', []))
        
        assert base_tools.issubset(resolved_tools)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])