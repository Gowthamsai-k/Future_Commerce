# Future Commerce MCP server

Start the server in Codespaces:

```bash
python server.py
```

Open the forwarded port `8000` in the Ports panel. The root URL (`/`) shows a
server status message, and MCP clients should connect to `/mcp`.

For the stdio client, run:

```bash
MCP_TRANSPORT=stdio python server.py
```
