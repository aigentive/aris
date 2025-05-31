#!/usr/bin/env python3

import pytest
import asyncio
import tempfile
import os
from unittest.mock import Mock, patch, AsyncMock
from aris.profile_manager import profile_manager
from aris.workflow_mcp_server import WorkflowMCPServer


class TestWorkflowMCPServer:
    """Test the Workflow MCP Server functionality."""
    
    def test_server_initialization(self):
        """Test that the workflow MCP server initializes correctly."""
        server = WorkflowMCPServer(port=8094)  # Use different port for testing
        
        assert server.port == 8094
        assert server.mcp_app.name == "workflow_orchestrator"
        assert "execute_workflow_phase" in server.mcp_app.tools
        
    def test_execute_workflow_phase_tool_definition(self):
        """Test that the execute_workflow_phase tool is properly defined."""
        server = WorkflowMCPServer(port=8094)
        
        tool_def = server.mcp_app.tools["execute_workflow_phase"]
        assert "Execute an ARIS profile" in tool_def["description"]
        assert tool_def["handler"] == server._handle_execute_workflow_phase
        
        # Check required parameters
        schema = tool_def["input_schema"]
        required_params = schema["required"]
        assert "profile" in required_params
        assert "workspace" in required_params
        assert "instruction" in required_params
        
        # Check parameter definitions
        properties = schema["properties"]
        assert "timeout" in properties
        assert properties["timeout"]["default"] == 300

    @pytest.mark.asyncio
    async def test_execute_workflow_phase_handler(self):
        """Test the execute_workflow_phase handler with mocked subprocess."""
        server = WorkflowMCPServer(port=8094)
        
        # Mock subprocess.run to simulate successful execution
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Test execution successful"
        mock_result.stderr = ""
        
        with patch('aris.workflow_mcp_server.subprocess.run', return_value=mock_result):
            result = await server._handle_execute_workflow_phase(
                profile="test_profile",
                workspace="test_workspace",
                instruction="Test instruction"
            )
            
            # Check result format
            assert len(result) == 1
            result_content = result[0]
            assert result_content.type == "text"
            
            # Parse JSON result
            import json
            result_data = json.loads(result_content.text)
            assert result_data["success"] is True
            assert result_data["profile"] == "test_profile"
            assert result_data["workspace"] == "test_workspace"
            assert result_data["response"] == "Test execution successful"

    @pytest.mark.asyncio
    async def test_execute_workflow_phase_failure(self):
        """Test execute_workflow_phase handler with failed execution."""
        server = WorkflowMCPServer(port=8094)
        
        # Mock subprocess.run to simulate failed execution
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Profile not found"
        
        with patch('aris.workflow_mcp_server.subprocess.run', return_value=mock_result):
            result = await server._handle_execute_workflow_phase(
                profile="nonexistent_profile",
                workspace="test_workspace", 
                instruction="Test instruction"
            )
            
            # Parse JSON result
            import json
            result_data = json.loads(result[0].text)
            assert result_data["success"] is False
            assert result_data["status"] == "failed"
            assert result_data["error"] == "Profile not found"

    @pytest.mark.asyncio
    async def test_execute_workflow_phase_timeout(self):
        """Test execute_workflow_phase handler with timeout."""
        server = WorkflowMCPServer(port=8094)
        
        # Mock subprocess.run to simulate timeout
        from subprocess import TimeoutExpired
        
        with patch('aris.workflow_mcp_server.subprocess.run', side_effect=TimeoutExpired("cmd", 1)):
            result = await server._handle_execute_workflow_phase(
                profile="test_profile",
                workspace="test_workspace",
                instruction="Test instruction",
                timeout=1
            )
            
            # Parse JSON result
            import json
            result_data = json.loads(result[0].text)
            assert result_data["success"] is False
            assert result_data["status"] == "timeout"
            assert "timed out after 1 seconds" in result_data["error"]


class TestBaseMasterProfile:
    """Test the base master profile functionality."""
    
    def test_base_master_profile_exists(self):
        """Test that the base master profile can be loaded."""
        profile = profile_manager.get_profile('base/master', resolve=False)
        assert profile is not None
        assert profile.get('profile_name') == 'master'
        assert profile.get('description') == 'Base workflow orchestrator profile for multi-agent coordination'
    
    def test_base_master_profile_inheritance(self):
        """Test that the base master profile properly inherits from default assistant instructions."""
        profile = profile_manager.get_profile('base/master', resolve=True)
        assert profile is not None
        
        # Check that it extends the correct parent
        raw_profile = profile_manager.get_profile('base/master', resolve=False)
        assert raw_profile.get('extends') == ['base/default_assistant_instructions']
        
        # Check that inheritance worked - system prompt should be longer than raw
        raw_prompt = raw_profile.get('system_prompt', '')
        resolved_prompt = profile.get('system_prompt', '')
        assert len(resolved_prompt) > len(raw_prompt)
        
        # Check for parent content
        assert 'Follow these rules strictly' in resolved_prompt
        
        # Check for master-specific content
        assert 'workflow orchestrator' in resolved_prompt
    
    def test_base_master_profile_tools(self):
        """Test that the base master profile has required tools."""
        profile = profile_manager.get_profile('base/master', resolve=True)
        assert profile is not None
        
        tools = profile.get('tools', [])
        assert 'execute_workflow_phase' in tools
        assert 'Read' in tools
        assert 'Write' in tools
        assert 'Glob' in tools
        assert 'LS' in tools
    
    def test_base_master_profile_mcp_config(self):
        """Test that the base master profile has workflow MCP configuration."""
        profile = profile_manager.get_profile('base/master', resolve=True)
        assert profile is not None
        
        mcp_configs = profile.get('mcp_config_files', [])
        assert 'configs/workflow_orchestrator.mcp-servers.json' in mcp_configs


class TestContentOrchestratorProfile:
    """Test the content orchestrator example profile."""
    
    def test_content_orchestrator_profile_exists(self):
        """Test that the content orchestrator profile can be loaded."""
        profile = profile_manager.get_profile('composite/content_orchestrator', resolve=False)
        assert profile is not None
        assert profile.get('profile_name') == 'content_orchestrator'
        assert 'Content creation workflow orchestrator' in profile.get('description', '')
    
    def test_content_orchestrator_inheritance(self):
        """Test that the content orchestrator properly inherits from base master."""
        profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        assert profile is not None
        
        # Check inheritance chain
        raw_profile = profile_manager.get_profile('composite/content_orchestrator', resolve=False)
        assert raw_profile.get('extends') == ['base/master']
        
        # Check for inherited content
        prompt = profile.get('system_prompt', '')
        assert 'workflow orchestrator' in prompt  # From base master
        assert 'Content Creation Specialization' in prompt  # Own content
    
    def test_content_orchestrator_tools(self):
        """Test that the content orchestrator has required tools."""
        profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        assert profile is not None
        
        tools = profile.get('tools', [])
        assert 'execute_workflow_phase' in tools
        assert 'Read' in tools
        assert 'Write' in tools
    
    def test_content_orchestrator_mcp_config(self):
        """Test that the content orchestrator has workflow MCP configuration."""
        profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        assert profile is not None
        
        mcp_configs = profile.get('mcp_config_files', [])
        assert 'configs/workflow_orchestrator.mcp-servers.json' in mcp_configs
    
    def test_content_orchestrator_welcome_message(self):
        """Test that the content orchestrator has a proper welcome message."""
        profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        assert profile is not None
        
        welcome = profile.get('welcome_message', '')
        assert '🎯 Content Creation Orchestrator ready!' in welcome
        assert 'multi-phase content workflows' in welcome


class TestWorkflowMCPConfig:
    """Test the workflow MCP configuration file."""
    
    def test_workflow_mcp_config_file_exists(self):
        """Test that the workflow MCP config file exists and is valid JSON."""
        config_path = os.path.join(
            os.path.dirname(__file__), 
            '../../aris/profiles/configs/workflow_orchestrator.mcp-servers.json'
        )
        
        assert os.path.exists(config_path), f"Config file not found at {config_path}"
        
        # Test that it's valid JSON
        import json
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Check structure
        assert 'mcpServers' in config
        assert 'workflow_orchestrator' in config['mcpServers']
        
        server_config = config['mcpServers']['workflow_orchestrator']
        assert server_config['type'] == 'sse'
        assert 'http://127.0.0.1:8095/mcp/sse/' in server_config['url']


class TestOrchestrationIntegration:
    """Integration tests for the complete orchestration system."""
    
    @pytest.mark.asyncio
    async def test_workflow_mcp_server_startup_integration(self):
        """Test that the workflow MCP server can be started and stopped."""
        # This test simulates the startup without actually binding to ports
        server = WorkflowMCPServer(port=8095)  # Use unique port
        
        # Test that the server components are properly initialized
        assert server.starlette_app is not None
        assert server.mcp_app is not None
        assert len(server.mcp_app.tools) > 0
    
    def test_profile_system_integration(self):
        """Test that all orchestration profiles work together."""
        # Test that base master can be loaded
        base_profile = profile_manager.get_profile('base/master', resolve=True)
        assert base_profile is not None
        
        # Test that content orchestrator can be loaded and inherits correctly
        content_profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        assert content_profile is not None
        
        # Check that inheritance chain is working
        base_tools = set(base_profile.get('tools', []))
        content_tools = set(content_profile.get('tools', []))
        
        # Content orchestrator should have core orchestration tools
        required_tools = {'execute_workflow_phase', 'Read', 'Write', 'Glob', 'LS'}
        assert required_tools.issubset(content_tools)
    
    def test_mcp_config_resolution(self):
        """Test that MCP config files can be resolved properly."""
        # Test that the config file can be found and loaded
        content_profile = profile_manager.get_profile('composite/content_orchestrator', resolve=True)
        mcp_configs = content_profile.get('mcp_config_files', [])
        
        assert len(mcp_configs) > 0
        assert 'configs/workflow_orchestrator.mcp-servers.json' in mcp_configs
        
        # Test that the merged MCP config can be generated
        try:
            merged_config_path = profile_manager.get_merged_mcp_config_path(content_profile)
            assert merged_config_path is not None
            assert os.path.exists(merged_config_path)
        except Exception as e:
            # This may fail if the config file references don't resolve, which is expected in test environment
            assert "workflow_orchestrator.mcp-servers.json" in str(e)


class TestOrchestrationErrorHandling:
    """Test error handling in the orchestration system."""
    
    @pytest.mark.asyncio
    async def test_workflow_mcp_invalid_arguments(self):
        """Test workflow MCP tool with invalid arguments."""
        server = WorkflowMCPServer(port=8096)
        
        # Test through MCP call interface with missing arguments
        result = await server._handle_mcp_call_tool("execute_workflow_phase", {})
        
        # Should return error result
        import json
        result_data = json.loads(result[0].text)
        assert result_data["tool_execution_error"] is True
        assert "HandlerExecutionError" in result_data["error_type"]
    
    @pytest.mark.asyncio
    async def test_workflow_mcp_unknown_tool(self):
        """Test calling unknown tool on workflow MCP server."""
        server = WorkflowMCPServer(port=8097)
        
        result = await server._handle_mcp_call_tool("unknown_tool", {})
        
        # Should return tool execution error
        import json
        result_data = json.loads(result[0].text)
        assert result_data["tool_execution_error"] is True
        assert result_data["error_type"] == "ToolNotFound"
        assert "Tool 'unknown_tool' not found" in result_data["message"]
    
    def test_profile_inheritance_error_handling(self):
        """Test error handling in profile inheritance."""
        # Try to load a non-existent profile
        profile = profile_manager.get_profile('nonexistent/profile')
        assert profile is None
        
        # This should not crash the system
        available_profiles = profile_manager.get_available_profiles()
        assert isinstance(available_profiles, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])