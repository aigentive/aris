# ARIS Profile System

The ARIS Profile System enables you to define, load, and switch between different operational profiles that customize Claude's behavior for specific tasks.

## Profile Concepts

Profiles allow you to:

1. **Define system prompts** that configure Claude's behavior
2. **Include context files** with reference materials
3. **Set tool preferences** to make specific tools available
4. **Configure multiple MCP servers** for specialized tools
5. **Create inheritance hierarchies** where profiles extend others
6. **Use template variables** for customization

## Using Profiles

### Command-Line Arguments

Start ARIS with a specific profile:

```bash
# Inside the project directory
poetry run python -m aris --profile workflow_manager

# Or if installed via pip
python -m aris --profile workflow_manager
```

### In-Session Commands

While in a ARIS session, you can use the following commands:

- `@profile list` - List all available profiles
- `@profile show <profile_name>` - Show details of a specific profile
- `@profile current` - Show the currently active profile
- `@profile clear` - Clear the active profile and return to default behavior
- `@profile <profile_name>` - Activate a specific profile
- `@profile variables` - List all variables in the active profile
- `@profile variables <name> <value>` - Set a variable in the active profile
- `@profile refresh` - Refresh the profile registry if you've added new profiles
- `@profile create <new_profile_name>` - Start the interactive profile creation wizard

## Profile Locations and Discovery

Profiles are searched for in the following locations, in order of precedence:

1. **User profiles**: `~/.aris/`
2. **Project profiles**: `./.aris/` (in the working directory)
3. **Package profiles**: Built-in profiles in the ARIS package`

### Profile Directory Structure

Within each profile location, profiles can be organized in a directory structure that affects their reference names:

```
profiles/
├── default.yaml                  # Referenced as "default"
├── base/
│   ├── default_assistant_instructions.yaml  # Referenced as "base/default_assistant_instructions"
│   └── manager_guide.yaml        # Referenced as "base/manager_guide"
├── composite/
│   ├── workflow_manager.yaml     # Referenced as "composite/workflow_manager"
│   └── profile_manager.yaml      # Referenced as "composite/profile_manager"
└── configs/
    ├── aigentive.mcp-servers.json  # MCP config file
    └── profile_mcp_server.json     # MCP config file
```

### Profile Reference Names

Profiles are referenced by their relative path within the profile directory, without the file extension:

- `default.yaml` → referenced as `default`
- `base/manager_guide.yaml` → referenced as `base/manager_guide`
- `composite/workflow_manager.yaml` → referenced as `composite/workflow_manager`

### File Path Resolution

When referencing files in your profiles (system_prompt_file, context_files, mcp_config_files, etc.), paths are resolved in the following order:

1. Absolute paths are used as-is
2. Relative paths are first checked relative to the profile file's location
3. If not found, paths are checked relative to each profile directory (user, project, package)

For example, when specifying `configs/profile_mcp_server.json` in a profile, the system will look for:

1. `~/.aris/configs/profile_mcp_server.json`
2. `./.aris/configs/profile_mcp_server.json`
3. `<package_path>/profiles/configs/profile_mcp_server.json`

This is why MCP config files should be placed in the `configs/` directory, not in `profiles/configs/`.

## Creating Custom Profiles

### YAML File Structure

Profiles are defined in YAML files with the following structure:

```yaml
profile_name: my_custom_profile
description: A custom profile for specific tasks
version: "1.0"
author: Your Name

# Optional parent profile(s) to inherit from
extends: base/default_assistant_instructions  # Or an array of profiles

# System prompt (either direct or from a file)
system_prompt: |
  You are an assistant specialized in {{domain}}.
  Please help the user with their tasks related to {{domain}}.

# Alternatively, load from a file
# system_prompt_file: path/to/prompt.txt

# Tool preferences
tools:
  - mcp_tool1
  - mcp_tool2

# Context files
context_files:
  - path/to/documentation.md
context_mode: auto  # "embedded", "referenced", or "auto"

# MCP configuration
mcp_config_files:
  - "configs/aigentive.mcp-servers.json"

# Template variables for customization
variables:
  - name: domain
    description: Domain of expertise
    required: true
    default: software development

# Welcome message shown when profile is activated
welcome_message: |
  Welcome to the custom profile!
  You can ask questions about {{domain}}.

# Categorization tags
tags:
  - custom
  - specialized
```

### Profile Inheritance

Profiles can inherit from one or more parent profiles:

```yaml
# Single parent
extends: base/default_assistant_instructions

# Multiple parents
extends:
  - base/default_assistant_instructions
  - base/manager_guide
```

When inheriting, you can refer to the parent's system prompt:

```yaml
system_prompt: |
  {{parent_system_prompt}}
  
  Additional specialized instructions:
  - Be concise
  - Focus on {{domain}} concepts
```

You can also refer to specific parent profiles:

```yaml
system_prompt: |
  {{parent:base/default_assistant_instructions}}
  
  Additional instructions...
```

### Template Variables

Define variables that need user values:

```yaml
variables:
  - name: domain
    description: The domain of expertise
    required: true
    default: software development
    
  - name: user_name
    description: User's name for personalization
    required: false
```

Variables are referenced in the system prompt as `{{variable_name}}`.

### Context Files

Include reference materials in your profile:

```yaml
context_files:
  - documentation/api_reference.md
  - documentation/examples.md
context_mode: auto  # "embedded", "referenced", or "auto"
```

### MCP Configuration

MCP (Managed Communication Protocol) configuration allows you to connect to tool servers. Configure MCP by creating JSON files in the `configs/` directory relative to your profiles:

File: `configs/aigentive.mcp-servers.json`
```json
{
  "mcpServers": {
    "aigentive": {
      "type": "sse",
      "url": "http://127.0.0.1:8090/mcp/sse/"
    }
  }
}
```

Refer to these in your profile:

```yaml
# Explicit MCP configuration reference
mcp_config_files:
  - "profiles/configs/aigentive.mcp-servers.json"
```

With this approach, MCP configuration is profile-driven rather than relying on a hardcoded `.mcp.json` file in the working directory. The configuration specifies:

1. `mcpServers`: The top-level object containing server configurations
2. Server name (e.g., `aigentive`): A named server configuration
3. `type`: The connection type (e.g., `sse` for Server-Sent Events)
4. `url`: The endpoint URL for the MCP server

You can define multiple MCP servers in a single configuration file:

File: `configs/multi-server-example.json`
```json
{
  "mcpServers": {
    "aigentive": {
      "type": "sse",
      "url": "http://127.0.0.1:8090/mcp/sse/"
    },
    "secondary": {
      "type": "sse",
      "url": "http://127.0.0.1:8091/mcp/sse/"
    }
  }
}
```

Or you can merge multiple configuration files in your profile:

```yaml
mcp_config_files:
  - "configs/aigentive.mcp-servers.json"
  - "configs/additional-servers.json"
```

The profile manager will merge these configurations, with later files taking precedence for any overlapping server definitions.

## Examples

See the `profiles/` directory for example profiles:

- `profiles/default.yaml`: Default profile
- `profiles/base/`: Base components for building profiles
- `profiles/composite/`: Pre-built profiles for specific use cases

## Best Practices

1. **Start with Base Profiles**: Build on the existing base profiles rather than starting from scratch
2. **Use Inheritance**: Create modular, reusable profiles that can be combined
3. **Provide Clear Descriptions**: Help users understand what your profile does
4. **Use Variables Judiciously**: Only add variables for truly customizable elements
5. **Test Your Profiles**: Ensure they work as expected in different scenarios

## Advanced Features

### List Directives

When inheriting lists (like tools or context files), you can control the merge behavior:

```yaml
# Replace parent list entirely
tools:
  - "!REPLACE"
  - new_tool1
  - new_tool2

# Prepend to parent list
context_files:
  - "!PREPEND"
  - most_important_file.md
  - second_important_file.md
```

Without directives, child lists are appended to parent lists.

## Troubleshooting

If you encounter issues:

1. **Check for Syntax Errors**: Ensure your YAML is valid
2. **Verify File Paths**: Make sure context files and system prompt files exist
3. **Refresh the Registry**: Use `@profile refresh` after adding new profiles
4. **Inspect the Active Profile**: Use `@profile current` to see what's active
5. **Review Variables**: Make sure all required variables have values