#!/usr/bin/env python3

"""
MCP Startup Analyzer

Analyzes profile MCP requirements to enable conditional startup of built-in MCP servers.
Only starts servers that are actually needed by the active profile and its inheritance chain.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Set, Optional

from .profile_manager import profile_manager
from .logging_utils import log_debug, log_warning, log_router_activity


@dataclass
class MCPRequirements:
    """Analysis results for what MCP servers a profile requires."""
    needs_profile_mcp_server: bool = False
    needs_workflow_mcp_server: bool = False
    detected_mcp_configs: List[str] = field(default_factory=list)
    analysis_time_ms: float = 0.0
    profile_name: str = ""
    inheritance_chain: List[str] = field(default_factory=list)


class MCPStartupAnalyzer:
    """
    Analyzes profile MCP requirements for conditional server startup.
    
    Determines which built-in MCP servers are actually needed by examining
    the profile's mcp_config_files and inheritance chain.
    """
    
    # Built-in MCP server config file patterns
    PROFILE_MCP_CONFIG = "configs/profile_mcp_server.json"
    WORKFLOW_MCP_CONFIG = "configs/workflow_orchestrator.mcp-servers.json"
    
    @classmethod
    def analyze_profile_mcp_requirements(cls, profile_name: str) -> MCPRequirements:
        """
        Analyze what built-in MCP servers a profile actually needs.
        
        Args:
            profile_name: Name of the profile to analyze
            
        Returns:
            MCPRequirements object with analysis results
        """
        start_time = time.time()
        
        try:
            log_debug(f"Analyzing MCP requirements for profile: {profile_name}")
            
            # Get the resolved profile (includes inheritance)
            profile = profile_manager.get_profile(profile_name, resolve=True)
            if not profile:
                log_warning(f"Profile '{profile_name}' not found, assuming no MCP requirements")
                return MCPRequirements(
                    profile_name=profile_name,
                    analysis_time_ms=(time.time() - start_time) * 1000
                )
            
            # Analyze inheritance chain for debugging
            inheritance_chain = cls._get_inheritance_chain(profile_name)
            
            # Extract MCP config files
            mcp_config_files = cls._extract_mcp_config_files(profile)
            
            # Detect built-in MCP server dependencies
            requirements = cls._detect_builtin_mcp_dependencies(mcp_config_files)
            
            # Fill in analysis metadata
            requirements.profile_name = profile_name
            requirements.inheritance_chain = inheritance_chain
            requirements.analysis_time_ms = (time.time() - start_time) * 1000
            
            # Log analysis results
            log_debug(f"MCP analysis for '{profile_name}': "
                     f"Profile MCP={requirements.needs_profile_mcp_server}, "
                     f"Workflow MCP={requirements.needs_workflow_mcp_server}, "
                     f"Time={requirements.analysis_time_ms:.1f}ms")
            
            return requirements
            
        except Exception as e:
            log_warning(f"Failed to analyze MCP requirements for '{profile_name}': {e}")
            # Return conservative requirements (assume all servers needed)
            return MCPRequirements(
                needs_profile_mcp_server=True,
                needs_workflow_mcp_server=True,
                profile_name=profile_name,
                analysis_time_ms=(time.time() - start_time) * 1000
            )
    
    @classmethod
    def _get_inheritance_chain(cls, profile_name: str) -> List[str]:
        """Get the inheritance chain for a profile for debugging purposes."""
        try:
            # Get raw profile to examine extends
            raw_profile = profile_manager.get_profile(profile_name, resolve=False)
            if not raw_profile:
                return [profile_name]
            
            chain = [profile_name]
            extends = raw_profile.get('extends', [])
            
            # Add immediate parents
            for parent in extends:
                chain.append(parent)
            
            return chain
            
        except Exception as e:
            log_debug(f"Failed to get inheritance chain for '{profile_name}': {e}")
            return [profile_name]
    
    @classmethod
    def _extract_mcp_config_files(cls, profile: Dict[str, Any]) -> Set[str]:
        """Extract MCP config file paths from resolved profile."""
        config_files = profile.get('mcp_config_files', [])
        
        # Handle both strings and lists
        if isinstance(config_files, str):
            config_files = [config_files]
        elif not isinstance(config_files, list):
            config_files = []
        
        return set(config_files)
    
    @classmethod
    def _detect_builtin_mcp_dependencies(cls, config_files: Set[str]) -> MCPRequirements:
        """
        Detect which built-in MCP servers are needed based on config files.
        
        Args:
            config_files: Set of MCP config file paths from profile
            
        Returns:
            MCPRequirements with detected dependencies
        """
        requirements = MCPRequirements()
        requirements.detected_mcp_configs = list(config_files)
        
        # Profile MCP Server detection
        if cls.PROFILE_MCP_CONFIG in config_files:
            requirements.needs_profile_mcp_server = True
            log_debug(f"Profile requires Profile MCP Server (found {cls.PROFILE_MCP_CONFIG})")
        
        # Workflow MCP Server detection
        if cls.WORKFLOW_MCP_CONFIG in config_files:
            requirements.needs_workflow_mcp_server = True
            log_debug(f"Profile requires Workflow MCP Server (found {cls.WORKFLOW_MCP_CONFIG})")
        
        return requirements
    
    @classmethod
    def get_target_profile_name(cls, parsed_args) -> str:
        """
        Get the profile name that will be activated based on CLI args.
        
        Args:
            parsed_args: Parsed command line arguments
            
        Returns:
            Profile name string
        """
        return getattr(parsed_args, 'profile', 'default')
    
    @classmethod
    def should_start_profile_mcp_server(cls, requirements: MCPRequirements, parsed_args) -> bool:
        """
        Determine if Profile MCP Server should be started.
        
        Args:
            requirements: MCP analysis results
            parsed_args: Parsed command line arguments
            
        Returns:
            True if Profile MCP Server should start
        """
        # Check if explicitly disabled
        if getattr(parsed_args, 'no_profile_mcp_server', False):
            log_debug("Profile MCP Server disabled via --no-profile-mcp-server")
            return False
        
        # Check if profile requires it
        if requirements.needs_profile_mcp_server:
            log_debug(f"Profile MCP Server needed by profile '{requirements.profile_name}'")
            return True
        
        log_debug(f"Profile MCP Server not needed by profile '{requirements.profile_name}'")
        return False
    
    @classmethod
    def should_start_workflow_mcp_server(cls, requirements: MCPRequirements, parsed_args) -> bool:
        """
        Determine if Workflow MCP Server should be started.
        
        Args:
            requirements: MCP analysis results
            parsed_args: Parsed command line arguments
            
        Returns:
            True if Workflow MCP Server should start
        """
        # Check if explicitly disabled
        if getattr(parsed_args, 'no_workflow_mcp_server', False):
            log_debug("Workflow MCP Server disabled via --no-workflow-mcp-server")
            return False
        
        # Check if profile requires it
        if requirements.needs_workflow_mcp_server:
            log_debug(f"Workflow MCP Server needed by profile '{requirements.profile_name}'")
            return True
        
        log_debug(f"Workflow MCP Server not needed by profile '{requirements.profile_name}'")
        return False
    
    @classmethod
    def log_startup_decision(cls, requirements: MCPRequirements, 
                           profile_mcp_starting: bool, 
                           workflow_mcp_starting: bool,
                           verbose: bool = False):
        """
        Log the startup decision for debugging and user information.
        
        Args:
            requirements: MCP analysis results
            profile_mcp_starting: Whether Profile MCP Server will start
            workflow_mcp_starting: Whether Workflow MCP Server will start
            verbose: Whether to log to console in addition to file
        """
        analysis_msg = (f"MCP startup analysis for '{requirements.profile_name}' "
                       f"({requirements.analysis_time_ms:.1f}ms): "
                       f"Profile MCP={'starting' if profile_mcp_starting else 'skipping'}, "
                       f"Workflow MCP={'starting' if workflow_mcp_starting else 'skipping'}")
        
        log_router_activity(analysis_msg)
        
        if verbose:
            print(f"🔍 {analysis_msg}")
            
            if requirements.detected_mcp_configs:
                configs_msg = f"   Detected MCP configs: {', '.join(requirements.detected_mcp_configs)}"
                log_debug(configs_msg)
                if verbose:
                    print(f"   {configs_msg}")
            
            if requirements.inheritance_chain and len(requirements.inheritance_chain) > 1:
                chain_msg = f"   Inheritance chain: {' → '.join(requirements.inheritance_chain)}"
                log_debug(chain_msg)
                if verbose:
                    print(f"   {chain_msg}")


# Convenience functions for external use
def analyze_profile_mcp_requirements(profile_name: str) -> MCPRequirements:
    """Convenience function for external modules."""
    return MCPStartupAnalyzer.analyze_profile_mcp_requirements(profile_name)


def get_target_profile_name(parsed_args) -> str:
    """Convenience function for external modules."""
    return MCPStartupAnalyzer.get_target_profile_name(parsed_args)