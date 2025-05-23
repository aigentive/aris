# ARIS: Amplified Reasoning & Intelligence Systems

ARIS is an opinionated AI orchestration methodology that demonstrates how to leverage AI compute to scale engineering output exponentially. Inspired by Tony Stark's Jarvis, ARIS provides profile-driven automation patterns for complex AI workflows.

## Quick Start

```bash
# Install dependencies
poetry install

# Run ARIS with default profile
poetry run python -m aris

# Run with specific profile
poetry run python -m aris --profile profile_manager

# Enable voice mode
poetry run python -m aris --voice

# View available options
poetry run python -m aris --help
```

## What is ARIS?

ARIS (Amplified Reasoning & Intelligence Systems) represents a paradigm shift in how we interact with AI tools. Rather than using individual AI services in isolation, ARIS orchestrates multiple AI capabilities through intelligent profiles, maximizing output while maintaining context and coherence.

## Key Features

- **Profile-Driven Specialization**: Each task gets a purpose-built AI configuration
- **MCP Integration**: Built on Model Context Protocol for extensible tool integration
- **Voice & Text Modes**: Seamless switching between voice and text interaction
- **Context Preservation**: Maintain intelligent context across multi-step operations
- **Tool Agnostic**: Built on Claude Code today, adaptable to any AI system tomorrow
- **Private Profile Support**: Keep proprietary profiles and configurations separate

## Installation

### Prerequisites

- Python 3.10-3.11 (Python 3.12+ not yet supported)
- Poetry package manager
- API keys for AI services (Anthropic Claude recommended)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/aigentive/aris.git
cd aris
```

2. Install dependencies:
```bash
poetry install
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

4. Run ARIS:
```bash
poetry run python -m aris
```

## Profile System

ARIS uses a sophisticated profile system to specialize AI behavior for different tasks. Profiles can:

- Inherit from other profiles
- Include context files and documentation
- Configure specific MCP tools and servers
- Define custom variables and templates
- Override system prompts and behavior

### Profile Locations

ARIS looks for profiles in three locations (in order of priority):

1. **Package profiles**: Built-in profiles in `aris/profiles/`
2. **Project profiles**: Local profiles in `./.aris/`
3. **User profiles**: Personal profiles in `~/.aris/`

### Built-in Profiles

- `default`: Basic ARIS functionality
- `profile_manager`: Enhanced profile management capabilities

### Managing Profiles

```bash
# List available profiles
poetry run python -m aris
# Then type: @profile list

# Create a new profile
@profile create my_custom_profile

# Switch to a profile
@profile my_custom_profile

# View current profile
@profile current
```

## Environment Configuration

Create a `.env` file with your configuration:

```bash
# AI Service Configuration
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here

# Voice Features (optional)
# Set these if you want to use voice capabilities
# OPENAI_API_KEY is required for text-to-speech

# MCP Server Configuration (optional)
# Configure if you have custom MCP servers
```

## Usage Examples

### Basic Text Interaction
```bash
poetry run python -m aris
# Type your questions and requests naturally
```

### Voice Interaction
```bash
poetry run python -m aris --voice
# Speak your requests using trigger words like "Claude" or "Hey Claude"
```

### Profile-Specific Usage
```bash
# Use the profile manager for profile operations
poetry run python -m aris --profile profile_manager

# Then interact with profile management:
# "List all available profiles"
# "Create a new profile for data analysis"
# "Show me the details of the default profile"
```

## MCP Integration

ARIS is built on the Model Context Protocol (MCP), enabling:

- **Extensible Tools**: Add custom tools via MCP servers
- **External Integrations**: Connect to databases, APIs, and services
- **Profile-Specific Tools**: Different profiles can use different tool sets

### Adding Custom MCP Servers

1. Create an MCP server configuration in `~/.aris/configs/`
2. Reference it in your profile's `mcp_config_files` section
3. ARIS will automatically load and use the tools

## Advanced Features

### Voice Mode
- Natural speech recognition
- Configurable trigger words
- Text-to-speech responses
- Seamless mode switching

### Context Management
- Automatic context file generation
- Smart context pruning
- Multi-turn conversation support

### Session Management
- Persistent conversation history
- Session state preservation
- Resume previous conversations

## Development

### Running Tests
```bash
poetry run pytest tests/
```

### Code Structure
```
aris/
├── aris/                 # Main package
│   ├── orchestrator.py   # Core orchestration engine
│   ├── profile_manager.py # Profile system
│   ├── cli.py           # Command-line interface
│   └── profiles/        # Built-in profiles
├── tests/               # Test suite
└── README.md           # This file
```

## Contributing

We welcome contributions that enhance the ARIS methodology! Areas of interest:

- New profile patterns for common workflows
- MCP server integrations
- Documentation and examples
- Performance optimizations

Please ensure all tests pass before submitting PRs:
```bash
poetry run pytest tests/
```

## License

MIT License - See LICENSE file for details.

## Troubleshooting

### Common Issues

**Python Version Errors**: Ensure you're using Python 3.10 or 3.11
```bash
pyenv local 3.11.8  # If using pyenv
poetry env use 3.11.8
```

**Voice Features Not Working**: Install additional dependencies and set OPENAI_API_KEY

**Profile Not Found**: Check profile locations and naming

**MCP Server Connection Issues**: Verify server URLs and configurations

### Getting Help

- Check the built-in profile documentation: `aris/README_PROFILES.md`
- Review test files for usage examples
- Use the profile manager for interactive help

---

*ARIS: Amplifying human intelligence through strategic AI orchestration*