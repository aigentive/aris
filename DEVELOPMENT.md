# ARIS Development Guide

This guide covers everything you need to know for developing and contributing to ARIS.

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Local Development](#local-development)
- [Testing](#testing)
- [Code Style](#code-style)
- [Contributing](#contributing)
- [Release Process](#release-process)
- [Troubleshooting](#troubleshooting)

## Development Setup

### Prerequisites

- Python 3.10 or 3.11 (3.12+ not yet supported)
- Poetry package manager
- Git
- API keys for AI services (Anthropic Claude recommended)

### Initial Setup

1. **Clone the repository**:
```bash
git clone https://github.com/aigentive/aris.git
cd aris
```

2. **Set Python version** (if using pyenv):
```bash
pyenv local 3.11.8
```

3. **Install dependencies**:
```bash
poetry install
```

4. **Configure environment**:
```bash
cp .env.example .env
# Edit .env with your API keys
```

5. **Verify installation**:
```bash
poetry run pytest tests/
poetry run aris --help
```

## Project Structure

```
aris/
├── aris/                          # Main package
│   ├── __init__.py                # Package initialization
│   ├── __main__.py                # CLI entry point
│   ├── orchestrator.py            # Core orchestration engine
│   ├── profile_manager.py         # Profile system
│   ├── cli.py                     # Main CLI interface
│   ├── cli_args.py                # Argument parsing
│   ├── session_state.py           # Session management
│   ├── interaction_handler.py     # User interaction
│   ├── voice_handler.py           # Voice capabilities
│   ├── tts_handler.py             # Text-to-speech
│   ├── mcp_service.py             # MCP integration
│   ├── prompt_formatter.py        # Prompt formatting
│   ├── context_file_manager.py    # Context handling
│   ├── logging_utils.py           # Logging utilities
│   ├── profile_handler.py         # Profile operations
│   ├── profile_mcp_server.py      # Profile MCP server
│   ├── claude_cli_executor.py     # Claude CLI execution
│   ├── cli_flag_manager.py        # CLI flag management
│   ├── core/                      # Core components
│   ├── interfaces/                # Interface modules
│   ├── utils/                     # Utilities
│   └── profiles/                  # Built-in profiles
│       ├── default.yaml           # Default profile
│       ├── base/                  # Base profile components
│       ├── composite/             # Composite profiles
│       └── configs/               # MCP configurations
├── tests/                         # Test suite
│   ├── aris/                      # Package tests
│   └── conftest.py                # Test configuration
├── .env.example                   # Environment template
├── .gitignore                     # Git ignore rules
├── LICENSE                        # MIT License
├── README.md                      # Main documentation
├── DEVELOPMENT.md                 # This file
└── pyproject.toml                 # Project configuration
```

## Local Development

### Running ARIS Locally

```bash
# Run with default profile
poetry run python -m aris

# Run with specific profile
poetry run aris --profile profile_manager

# Enable voice mode
poetry run aris --voice

# Verbose logging
poetry run aris --verbose
```

### Editable Installation

For immediate reflection of code changes:

```bash
# Install in development mode
poetry install

# Now you can use aris globally within poetry shell
poetry shell
aris --help
```

### Using in Other Projects

To use your local ARIS development version in other projects:

```bash
# In another project directory
poetry add --editable /path/to/aris

# Or with pip
pip install -e /path/to/aris
```

### Global Development Install

```bash
# Install globally in development mode
pip install -e .

# Now 'aris' is available system-wide
aris --help
```

## Testing

### Running Tests

```bash
# Run all tests
poetry run pytest tests/

# Run with verbose output
poetry run pytest tests/ -v

# Run specific test file
poetry run pytest tests/aris/test_profile_manager.py

# Run specific test
poetry run pytest tests/aris/test_profile_manager.py::test_discover_profiles

# Run with coverage
poetry run pytest tests/ --cov=aris
```

### Test Structure

- **Unit tests**: Test individual components in isolation
- **Integration tests**: Test component interactions
- **CLI tests**: Test command-line interface
- **Profile tests**: Test profile system functionality

### Writing Tests

```python
# Example test structure
import pytest
from unittest.mock import patch, MagicMock
from aris.profile_manager import ProfileManager

def test_profile_discovery():
    """Test that profiles are discovered correctly."""
    manager = ProfileManager()
    profiles = manager.get_available_profiles()
    assert 'default' in profiles
    assert isinstance(profiles['default'], dict)
```

## Code Style

### Python Standards

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write docstrings for public functions and classes
- Keep functions focused and single-purpose

### Code Formatting

```bash
# Format code (if using black)
poetry run black aris/ tests/

# Check imports (if using isort)
poetry run isort aris/ tests/

# Lint code (if using flake8)
poetry run flake8 aris/ tests/
```

### Documentation

- Document all public APIs
- Include examples in docstrings
- Update README.md for user-facing changes
- Update this guide for development changes

## Contributing

### Development Workflow

1. **Create a feature branch**:
```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes**:
   - Write code with tests
   - Update documentation
   - Follow code style guidelines

3. **Test your changes**:
```bash
poetry run pytest tests/
poetry run aris --help  # Basic functionality test
```

4. **Commit your changes**:
```bash
git add .
git commit -m "Add feature: description of changes"
```

5. **Push and create PR**:
```bash
git push origin feature/your-feature-name
# Create pull request on GitHub
```

### Commit Messages

Use clear, descriptive commit messages:

```
Add profile inheritance system

- Implement parent profile resolution
- Add template variable substitution
- Update profile validation logic
- Add comprehensive tests

Fixes #123
```

### Pull Request Guidelines

- Include a clear description of changes
- Reference any related issues
- Ensure all tests pass
- Update documentation as needed
- Request review from maintainers

## Release Process

### Version Management

ARIS uses semantic versioning (SemVer):
- `MAJOR.MINOR.PATCH` (e.g., `1.2.3`)
- Major: Breaking changes
- Minor: New features (backward compatible)
- Patch: Bug fixes

### Creating a Release

1. **Update version**:
```bash
# In pyproject.toml
version = "0.2.0"
```

2. **Update changelog** (if using one):
```bash
# Add release notes to CHANGELOG.md
```

3. **Test thoroughly**:
```bash
poetry run pytest tests/
poetry build  # Test package building
```

4. **Commit and tag**:
```bash
git add .
git commit -m "Release v0.2.0"
git tag v0.2.0
git push origin main --tags
```

5. **Publish to PyPI**:
```bash
poetry build
poetry publish
```

### Publishing to PyPI

First-time setup:
```bash
# Create PyPI account and API token
poetry config pypi-token.pypi <your-token>
```

Publishing:
```bash
poetry build
poetry publish
```

## Troubleshooting

### Common Development Issues

**Python Version Errors**:
```bash
# Check current version
python --version

# Set correct version with pyenv
pyenv local 3.11.8
poetry env use 3.11.8
```

**Poetry Issues**:
```bash
# Clear poetry cache
poetry cache clear --all pypi

# Remove and recreate environment
poetry env remove python
poetry install
```

**Import Errors**:
```bash
# Ensure you're in the poetry environment
poetry shell

# Or use poetry run
poetry run python -c "import aris; print('Success')"
```

**Test Failures**:
```bash
# Run tests with verbose output to debug
poetry run pytest tests/ -v -s

# Run specific failing test
poetry run pytest tests/aris/test_failing.py::test_function -v -s
```

### Environment Issues

**Missing API Keys**:
```bash
# Check .env file exists and has required keys
cat .env

# Required for basic functionality:
ANTHROPIC_API_KEY=your_key_here

# Optional for voice features:
OPENAI_API_KEY=your_key_here
```

**Profile Issues**:
```bash
# Check profile directories
ls -la ~/.aris/
ls -la ./.aris/
ls -la aris/profiles/

# Test profile loading
poetry run python -c "
from aris.profile_manager import profile_manager
print(list(profile_manager.get_available_profiles().keys()))
"
```

### Getting Help

1. **Check existing issues**: https://github.com/aigentive/aris/issues
2. **Run tests**: Often reveals the problem
3. **Check logs**: Use `--verbose` flag for detailed output
4. **Create an issue**: If you find a bug or need help

## Development Tips

### Useful Commands

```bash
# Quick test after changes
poetry run aris --help

# Test specific profile
poetry run aris --profile profile_manager

# Debug with verbose logging
poetry run aris --verbose --log-file debug.log

# Check package builds correctly
poetry build

# Validate pyproject.toml
poetry check
```

### IDE Setup

For VS Code, recommended extensions:
- Python
- Python Docstring Generator
- Python Type Hint
- GitLens

### Debugging

```python
# Add breakpoints in code
import pdb; pdb.set_trace()

# Or use IDE debugger with launch configuration
```

---

## Questions?

If you have questions about development:
1. Check this guide first
2. Look at existing code and tests for examples
3. Create an issue on GitHub
4. Join the discussion in pull requests

Happy coding! 🚀