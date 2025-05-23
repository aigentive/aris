# ARIS Profile System

This directory contains the profile system for ARIS (Amplified Reasoning & Intelligence Systems).

## Profile Structure

- `default.yaml` - The default profile loaded when ARIS starts
- `base/` - Base profile components that can be extended
  - `default_assistant_instructions.yaml` - Default assistant behavior
  - `manager_guide.yaml` - General profile management guidance
- `composite/` - Complex profiles that combine multiple base profiles
  - `profile_manager.yaml` - Profile for managing profiles
- `configs/` - MCP server configuration files
  - `example.mcp-servers.json` - Example MCP configuration
  - `profile_mcp_server.json` - Profile MCP server config
- `contexts/` - Context files for profiles
- `definitions/` - Additional profile definitions

## Using Private Profiles

For private or proprietary profiles and configurations, you can store them in:
`$HOME/.aris/`

ARIS will automatically look for profiles in both locations:
1. The application's profiles directory (this directory)
2. Your private profiles directory at `$HOME/.aris/`

This allows you to keep proprietary profiles and configurations separate from the public repository.

### Example Private Profile Structure

Your private profiles directory might contain:
- Company-specific workflow profiles
- Proprietary MCP server configurations
- Custom automation profiles
- Organization-specific tools and integrations

```
$HOME/.aris/
├── base/               # Private base profiles
├── composite/          # Private composite profiles  
├── configs/            # Private MCP configurations
└── *.yaml             # Private top-level profiles
```

## Creating Custom Profiles

See the main README_PROFILES.md for detailed documentation on creating and managing profiles.