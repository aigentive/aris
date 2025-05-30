# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development
```bash
# Install dependencies
poetry install

# Run ARIS with default profile
poetry run python -m aris

# Run with specific profile
poetry run python -m aris --profile profile_manager

# Run with workspace (creates ./my-project/ and works from there)
poetry run python -m aris --workspace my-project

# Run with absolute workspace path
poetry run python -m aris --workspace /path/to/project

# Combine profile and workspace
poetry run python -m aris --profile profile_manager --workspace my-project

# Enable voice mode
poetry run python -m aris --voice

# Enable verbose logging
poetry run python -m aris --verbose
```

### Testing
```bash
# Run all tests
poetry run pytest tests/

# Run specific test file
poetry run pytest tests/aris/test_profile_manager.py

# Run specific test
poetry run pytest tests/aris/test_profile_manager.py::test_discover_profiles

# Run with coverage
poetry run pytest tests/ --cov=aris
```

### Package Management
```bash
# Build package
poetry build

# Check package configuration
poetry check

# Install in editable mode for development
poetry install
```

## Architecture

ARIS is a profile-driven AI orchestration platform built on the Model Context Protocol (MCP). The system routes user interactions through specialized AI profiles that can include custom tools, context, and configurations.

### Core Components

**orchestrator.py**: Central orchestration engine that coordinates between profiles, MCP services, and the Claude CLI. Manages the main execution flow and component initialization.

**profile_manager.py**: Manages profile discovery, loading, and inheritance. Profiles can inherit from other profiles and include template variable substitution. Searches three locations: package profiles, project profiles (~/.aris), and user profiles (./.aris).

**cli.py**: Main CLI interface that handles user interaction, session management, and coordinates with the orchestrator. Manages both text and voice modes.

**mcp_service.py**: Handles Model Context Protocol integration, allowing profiles to specify custom tools and external service connections. Manages MCP server lifecycle and tool schema.

### Profile System

Profiles are YAML files that define specialized AI configurations:
- **Inheritance**: Profiles can inherit from other profiles using `inherits_from`
- **Context**: Include context files and documentation via `context_files`
- **Tools**: Configure MCP servers and tools via `mcp_config_files`
- **Variables**: Template variables for dynamic configuration
- **Instructions**: Custom system prompts and assistant instructions

Profile search order: package profiles → project profiles (./.aris) → user profiles (~/.aris)

### Workspace System

ARIS includes native workspace support for organized project work and file management:

**Workspace Setup**: The `--workspace` CLI argument creates and navigates to project directories automatically.
- No argument: Uses current working directory
- Relative path: Creates subdirectory in current location (e.g., `./my-project/`)  
- Absolute path: Uses specified path directly

**Automatic Variables**: Workspace information is automatically injected as template variables:
- `{workspace}`: Full path to the workspace directory
- `{workspace_name}`: Name of the workspace directory

**System Prompt Enhancement**: Profiles automatically receive workspace context when using a different directory than the original working directory, informing Claude of the workspace location and encouraging relative path usage.

**Session Integration**: Workspace information is tracked in session state and preserved across interactions within the same session.

### Key Services

**claude_cli_executor.py**: Executes Claude CLI commands with profile-specific configurations and context management.

**voice_handler.py** + **tts_handler.py**: Voice interaction capabilities including speech recognition and text-to-speech.

**session_state.py**: Manages conversation state, context preservation, and session persistence.

**context_file_manager.py**: Handles automatic context file generation and management for maintaining conversation context.

**workspace_manager.py**: Manages workspace setup, directory navigation, and automatic workspace variable injection for organized project work.

### Testing Strategy

Tests are organized by component with comprehensive coverage for:
- Profile system functionality (inheritance, variable substitution)
- MCP service integration and error handling
- CLI argument parsing and session management
- Voice and TTS capabilities
- Orchestrator coordination logic

## Environment Requirements

- Python 3.10-3.11 (3.12+ not yet supported)
- Poetry for dependency management
- Required: ANTHROPIC_API_KEY for Claude integration
- Optional: OPENAI_API_KEY for voice features