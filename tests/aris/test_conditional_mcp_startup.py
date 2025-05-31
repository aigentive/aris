#!/usr/bin/env python3

import pytest
import tempfile
import os
import json
from unittest.mock import Mock, patch, MagicMock
from dataclasses import FrozenInstanceError

from aris.mcp_startup_analyzer import MCPStartupAnalyzer, MCPRequirements


class TestMCPRequirements:
    """Test the MCPRequirements dataclass."""
    
    def test_mcp_requirements_default_values(self):
        """Test that MCPRequirements has correct default values."""
        req = MCPRequirements()
        
        assert req.needs_profile_mcp_server is False
        assert req.needs_workflow_mcp_server is False
        assert req.detected_mcp_configs == []
        assert req.analysis_time_ms == 0.0
        assert req.profile_name == ""
        assert req.inheritance_chain == []
    
    def test_mcp_requirements_custom_values(self):
        """Test MCPRequirements with custom values."""
        req = MCPRequirements(
            needs_profile_mcp_server=True,
            needs_workflow_mcp_server=True,
            detected_mcp_configs=["config1.json", "config2.json"],
            analysis_time_ms=42.5,
            profile_name="test_profile",
            inheritance_chain=["test_profile", "parent"]
        )
        
        assert req.needs_profile_mcp_server is True
        assert req.needs_workflow_mcp_server is True
        assert req.detected_mcp_configs == ["config1.json", "config2.json"]
        assert req.analysis_time_ms == 42.5
        assert req.profile_name == "test_profile"
        assert req.inheritance_chain == ["test_profile", "parent"]


class TestMCPStartupAnalyzer:
    """Test the MCPStartupAnalyzer class."""
    
    def test_config_patterns(self):
        """Test that the config file patterns are correct."""
        assert MCPStartupAnalyzer.PROFILE_MCP_CONFIG == "configs/profile_mcp_server.json"
        assert MCPStartupAnalyzer.WORKFLOW_MCP_CONFIG == "configs/workflow_orchestrator.mcp-servers.json"
    
    def test_extract_mcp_config_files_empty(self):
        """Test extracting MCP config files from profile with no configs."""
        profile = {"profile_name": "test"}
        
        result = MCPStartupAnalyzer._extract_mcp_config_files(profile)
        
        assert result == set()
    
    def test_extract_mcp_config_files_list(self):
        """Test extracting MCP config files from profile with list of configs."""
        profile = {
            "profile_name": "test",
            "mcp_config_files": ["config1.json", "config2.json"]
        }
        
        result = MCPStartupAnalyzer._extract_mcp_config_files(profile)
        
        assert result == {"config1.json", "config2.json"}
    
    def test_extract_mcp_config_files_string(self):
        """Test extracting MCP config files from profile with single string config."""
        profile = {
            "profile_name": "test",
            "mcp_config_files": "single_config.json"
        }
        
        result = MCPStartupAnalyzer._extract_mcp_config_files(profile)
        
        assert result == {"single_config.json"}
    
    def test_extract_mcp_config_files_invalid_type(self):
        """Test extracting MCP config files with invalid type."""
        profile = {
            "profile_name": "test",
            "mcp_config_files": 42  # Invalid type
        }
        
        result = MCPStartupAnalyzer._extract_mcp_config_files(profile)
        
        assert result == set()
    
    def test_detect_builtin_mcp_dependencies_none(self):
        """Test detecting built-in MCP dependencies when none are present."""
        config_files = {"external_config.json", "another_config.json"}
        
        result = MCPStartupAnalyzer._detect_builtin_mcp_dependencies(config_files)
        
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is False
        assert set(result.detected_mcp_configs) == config_files
    
    def test_detect_builtin_mcp_dependencies_profile_only(self):
        """Test detecting Profile MCP dependency only."""
        config_files = {
            "configs/profile_mcp_server.json",
            "external_config.json"
        }
        
        result = MCPStartupAnalyzer._detect_builtin_mcp_dependencies(config_files)
        
        assert result.needs_profile_mcp_server is True
        assert result.needs_workflow_mcp_server is False
        assert set(result.detected_mcp_configs) == config_files
    
    def test_detect_builtin_mcp_dependencies_workflow_only(self):
        """Test detecting Workflow MCP dependency only."""
        config_files = {
            "configs/workflow_orchestrator.mcp-servers.json",
            "external_config.json"
        }
        
        result = MCPStartupAnalyzer._detect_builtin_mcp_dependencies(config_files)
        
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is True
        assert set(result.detected_mcp_configs) == config_files
    
    def test_detect_builtin_mcp_dependencies_both(self):
        """Test detecting both built-in MCP dependencies."""
        config_files = {
            "configs/profile_mcp_server.json",
            "configs/workflow_orchestrator.mcp-servers.json",
            "external_config.json"
        }
        
        result = MCPStartupAnalyzer._detect_builtin_mcp_dependencies(config_files)
        
        assert result.needs_profile_mcp_server is True
        assert result.needs_workflow_mcp_server is True
        assert set(result.detected_mcp_configs) == config_files
    
    def test_get_target_profile_name_default(self):
        """Test getting target profile name with default."""
        parsed_args = Mock(spec=[])  # Empty spec means no attributes
        
        result = MCPStartupAnalyzer.get_target_profile_name(parsed_args)
        
        assert result == 'default'
    
    def test_get_target_profile_name_custom(self):
        """Test getting target profile name with custom profile."""
        parsed_args = Mock()
        parsed_args.profile = 'custom_profile'
        
        result = MCPStartupAnalyzer.get_target_profile_name(parsed_args)
        
        assert result == 'custom_profile'
    
    def test_should_start_profile_mcp_server_disabled_by_flag(self):
        """Test Profile MCP Server startup decision when disabled by flag."""
        requirements = MCPRequirements(needs_profile_mcp_server=True)
        parsed_args = Mock()
        parsed_args.no_profile_mcp_server = True
        
        result = MCPStartupAnalyzer.should_start_profile_mcp_server(requirements, parsed_args)
        
        assert result is False
    
    def test_should_start_profile_mcp_server_needed(self):
        """Test Profile MCP Server startup decision when needed."""
        requirements = MCPRequirements(needs_profile_mcp_server=True)
        parsed_args = Mock()
        parsed_args.no_profile_mcp_server = False
        
        result = MCPStartupAnalyzer.should_start_profile_mcp_server(requirements, parsed_args)
        
        assert result is True
    
    def test_should_start_profile_mcp_server_not_needed(self):
        """Test Profile MCP Server startup decision when not needed."""
        requirements = MCPRequirements(needs_profile_mcp_server=False)
        parsed_args = Mock()
        parsed_args.no_profile_mcp_server = False
        
        result = MCPStartupAnalyzer.should_start_profile_mcp_server(requirements, parsed_args)
        
        assert result is False
    
    def test_should_start_workflow_mcp_server_disabled_by_flag(self):
        """Test Workflow MCP Server startup decision when disabled by flag."""
        requirements = MCPRequirements(needs_workflow_mcp_server=True)
        parsed_args = Mock()
        parsed_args.no_workflow_mcp_server = True
        
        result = MCPStartupAnalyzer.should_start_workflow_mcp_server(requirements, parsed_args)
        
        assert result is False
    
    def test_should_start_workflow_mcp_server_needed(self):
        """Test Workflow MCP Server startup decision when needed."""
        requirements = MCPRequirements(needs_workflow_mcp_server=True)
        parsed_args = Mock()
        parsed_args.no_workflow_mcp_server = False
        
        result = MCPStartupAnalyzer.should_start_workflow_mcp_server(requirements, parsed_args)
        
        assert result is True
    
    def test_should_start_workflow_mcp_server_not_needed(self):
        """Test Workflow MCP Server startup decision when not needed."""
        requirements = MCPRequirements(needs_workflow_mcp_server=False)
        parsed_args = Mock()
        parsed_args.no_workflow_mcp_server = False
        
        result = MCPStartupAnalyzer.should_start_workflow_mcp_server(requirements, parsed_args)
        
        assert result is False


class TestProfileAnalysisIntegration:
    """Test profile analysis integration with real profiles."""
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_analyze_profile_mcp_requirements_profile_not_found(self, mock_profile_manager):
        """Test analysis when profile is not found."""
        mock_profile_manager.get_profile.return_value = None
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("nonexistent_profile")
        
        assert result.profile_name == "nonexistent_profile"
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is False
        assert result.analysis_time_ms > 0
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_analyze_profile_mcp_requirements_no_mcp_configs(self, mock_profile_manager):
        """Test analysis for profile with no MCP configs."""
        mock_profile = {
            "profile_name": "simple_profile",
            "description": "A simple profile"
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("simple_profile")
        
        assert result.profile_name == "simple_profile"
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is False
        assert result.detected_mcp_configs == []
        assert result.analysis_time_ms > 0
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_analyze_profile_mcp_requirements_with_profile_mcp(self, mock_profile_manager):
        """Test analysis for profile that needs Profile MCP Server."""
        mock_profile = {
            "profile_name": "profile_manager_profile",
            "mcp_config_files": ["configs/profile_mcp_server.json"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("profile_manager_profile")
        
        assert result.profile_name == "profile_manager_profile"
        assert result.needs_profile_mcp_server is True
        assert result.needs_workflow_mcp_server is False
        assert "configs/profile_mcp_server.json" in result.detected_mcp_configs
        assert result.analysis_time_ms > 0
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_analyze_profile_mcp_requirements_with_workflow_mcp(self, mock_profile_manager):
        """Test analysis for profile that needs Workflow MCP Server."""
        mock_profile = {
            "profile_name": "orchestrator_profile",
            "mcp_config_files": ["configs/workflow_orchestrator.mcp-servers.json"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("orchestrator_profile")
        
        assert result.profile_name == "orchestrator_profile"
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is True
        assert "configs/workflow_orchestrator.mcp-servers.json" in result.detected_mcp_configs
        assert result.analysis_time_ms > 0
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_analyze_profile_mcp_requirements_with_both_mcp(self, mock_profile_manager):
        """Test analysis for profile that needs both MCP servers."""
        mock_profile = {
            "profile_name": "full_featured_profile",
            "mcp_config_files": [
                "configs/profile_mcp_server.json",
                "configs/workflow_orchestrator.mcp-servers.json",
                "configs/external_server.json"
            ]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("full_featured_profile")
        
        assert result.profile_name == "full_featured_profile"
        assert result.needs_profile_mcp_server is True
        assert result.needs_workflow_mcp_server is True
        assert len(result.detected_mcp_configs) == 3
        assert "configs/profile_mcp_server.json" in result.detected_mcp_configs
        assert "configs/workflow_orchestrator.mcp-servers.json" in result.detected_mcp_configs
        assert "configs/external_server.json" in result.detected_mcp_configs
        assert result.analysis_time_ms > 0
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_analyze_profile_mcp_requirements_exception_handling(self, mock_profile_manager):
        """Test analysis exception handling with fallback to conservative requirements."""
        mock_profile_manager.get_profile.side_effect = Exception("Profile manager error")
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("error_profile")
        
        # Should fallback to conservative requirements (start all servers)
        assert result.profile_name == "error_profile"
        assert result.needs_profile_mcp_server is True
        assert result.needs_workflow_mcp_server is True
        assert result.analysis_time_ms > 0


class TestInheritanceChainAnalysis:
    """Test inheritance chain analysis functionality."""
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_get_inheritance_chain_simple(self, mock_profile_manager):
        """Test getting inheritance chain for simple profile."""
        mock_profile = {
            "profile_name": "child_profile",
            "extends": ["parent_profile"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer._get_inheritance_chain("child_profile")
        
        assert result == ["child_profile", "parent_profile"]
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_get_inheritance_chain_multiple_parents(self, mock_profile_manager):
        """Test getting inheritance chain with multiple parents."""
        mock_profile = {
            "profile_name": "child_profile",
            "extends": ["parent1", "parent2"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer._get_inheritance_chain("child_profile")
        
        assert result == ["child_profile", "parent1", "parent2"]
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_get_inheritance_chain_no_parents(self, mock_profile_manager):
        """Test getting inheritance chain for profile with no parents."""
        mock_profile = {
            "profile_name": "standalone_profile"
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer._get_inheritance_chain("standalone_profile")
        
        assert result == ["standalone_profile"]
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_get_inheritance_chain_profile_not_found(self, mock_profile_manager):
        """Test getting inheritance chain when profile is not found."""
        mock_profile_manager.get_profile.return_value = None
        
        result = MCPStartupAnalyzer._get_inheritance_chain("missing_profile")
        
        assert result == ["missing_profile"]
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_get_inheritance_chain_exception(self, mock_profile_manager):
        """Test getting inheritance chain when exception occurs."""
        mock_profile_manager.get_profile.side_effect = Exception("Error getting profile")
        
        result = MCPStartupAnalyzer._get_inheritance_chain("error_profile")
        
        assert result == ["error_profile"]


class TestLoggingAndMetrics:
    """Test logging and metrics functionality."""
    
    @patch('aris.mcp_startup_analyzer.log_router_activity')
    @patch('aris.mcp_startup_analyzer.log_debug')
    def test_log_startup_decision_basic(self, mock_log_debug, mock_log_router_activity):
        """Test basic startup decision logging."""
        requirements = MCPRequirements(
            profile_name="test_profile",
            analysis_time_ms=25.5
        )
        
        MCPStartupAnalyzer.log_startup_decision(
            requirements, 
            profile_mcp_starting=True, 
            workflow_mcp_starting=False,
            verbose=False
        )
        
        # Check that router activity was logged
        mock_log_router_activity.assert_called_once()
        call_args = mock_log_router_activity.call_args[0][0]
        assert "test_profile" in call_args
        assert "25.5ms" in call_args
        assert "Profile MCP=starting" in call_args
        assert "Workflow MCP=skipping" in call_args
    
    @patch('aris.mcp_startup_analyzer.log_router_activity')
    @patch('aris.mcp_startup_analyzer.log_debug')
    @patch('builtins.print')
    def test_log_startup_decision_verbose(self, mock_print, mock_log_debug, mock_log_router_activity):
        """Test startup decision logging with verbose output."""
        requirements = MCPRequirements(
            profile_name="test_profile",
            analysis_time_ms=25.5,
            detected_mcp_configs=["config1.json", "config2.json"],
            inheritance_chain=["test_profile", "parent_profile"]
        )
        
        MCPStartupAnalyzer.log_startup_decision(
            requirements, 
            profile_mcp_starting=False, 
            workflow_mcp_starting=True,
            verbose=True
        )
        
        # Check that both router activity and console output happened
        mock_log_router_activity.assert_called_once()
        assert mock_print.call_count >= 3  # Main message + configs + inheritance
        
        # Check print call contents
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        
        # Main message should be printed
        main_msg = next((call for call in print_calls if "🔍" in call and "test_profile" in call), None)
        assert main_msg is not None
        assert "Workflow MCP=starting" in main_msg
        assert "Profile MCP=skipping" in main_msg
        
        # Config message should be printed
        config_msg = next((call for call in print_calls if "Detected MCP configs" in call), None)
        assert config_msg is not None
        assert "config1.json" in config_msg
        
        # Inheritance message should be printed
        inheritance_msg = next((call for call in print_calls if "Inheritance chain" in call), None)
        assert inheritance_msg is not None
        assert "parent_profile" in inheritance_msg


class TestConvenienceFunctions:
    """Test convenience functions for external use."""
    
    @patch('aris.mcp_startup_analyzer.MCPStartupAnalyzer.analyze_profile_mcp_requirements')
    def test_analyze_profile_mcp_requirements_convenience(self, mock_analyze):
        """Test convenience function for analyzing profile MCP requirements."""
        mock_requirements = MCPRequirements(profile_name="test")
        mock_analyze.return_value = mock_requirements
        
        from aris.mcp_startup_analyzer import analyze_profile_mcp_requirements
        result = analyze_profile_mcp_requirements("test_profile")
        
        mock_analyze.assert_called_once_with("test_profile")
        assert result == mock_requirements
    
    @patch('aris.mcp_startup_analyzer.MCPStartupAnalyzer.get_target_profile_name')
    def test_get_target_profile_name_convenience(self, mock_get_target):
        """Test convenience function for getting target profile name."""
        mock_get_target.return_value = "test_profile"
        parsed_args = Mock()
        
        from aris.mcp_startup_analyzer import get_target_profile_name
        result = get_target_profile_name(parsed_args)
        
        mock_get_target.assert_called_once_with(parsed_args)
        assert result == "test_profile"


class TestRealProfileScenarios:
    """Test with real ARIS profile scenarios."""
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_default_profile_scenario(self, mock_profile_manager):
        """Test analysis for default profile (should need no MCP servers)."""
        mock_profile = {
            "profile_name": "default",
            "description": "Default ARIS profile",
            "system_prompt": "You are a helpful AI assistant."
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("default")
        
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is False
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_profile_manager_scenario(self, mock_profile_manager):
        """Test analysis for profile manager profile (should need Profile MCP)."""
        mock_profile = {
            "profile_name": "profile_manager",
            "mcp_config_files": ["configs/profile_mcp_server.json"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("profile_manager")
        
        assert result.needs_profile_mcp_server is True
        assert result.needs_workflow_mcp_server is False
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_master_orchestrator_scenario(self, mock_profile_manager):
        """Test analysis for master orchestrator profile (should need Workflow MCP)."""
        mock_profile = {
            "profile_name": "master",
            "mcp_config_files": ["configs/workflow_orchestrator.mcp-servers.json"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("master")
        
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is True
    
    @patch('aris.mcp_startup_analyzer.profile_manager')
    def test_content_orchestrator_scenario(self, mock_profile_manager):
        """Test analysis for content orchestrator (inherits from master, should need Workflow MCP)."""
        mock_profile = {
            "profile_name": "content_orchestrator",
            "extends": ["base/master"],
            "mcp_config_files": ["configs/workflow_orchestrator.mcp-servers.json"]
        }
        mock_profile_manager.get_profile.return_value = mock_profile
        
        result = MCPStartupAnalyzer.analyze_profile_mcp_requirements("content_orchestrator")
        
        assert result.needs_profile_mcp_server is False
        assert result.needs_workflow_mcp_server is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])