# MCP Server Configurations

This directory contains MCP (Model Context Protocol) server configuration files.

## Adding Your Own MCP Servers

To add your own MCP server configurations:

1. Create a new JSON file in this directory (e.g., `myserver.mcp-servers.json`)
2. Follow the format shown in `example.mcp-servers.json`
3. Reference your config file in your profile's `mcp_config_files` section

## Example Configuration

```json
{
  "mcpServers": {
    "myserver": {
      "type": "sse",
      "url": "http://localhost:8080/mcp/sse/"
    }
  }
}
```

## Private Configurations

For private or proprietary MCP configurations, we recommend storing them in:
`$HOME/.aris/configs/`

You can reference these external configs in your profiles using absolute paths.