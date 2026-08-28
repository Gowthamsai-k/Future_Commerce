import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():

    server_params = StdioServerParameters(
        command="python",
        args=["server.py"],
        env={**os.environ, "MCP_TRANSPORT": "stdio"},
    )

    async with stdio_client(server_params) as (read, write):

        async with ClientSession(read, write) as session:

            # Initialize MCP connection
            await session.initialize()

            # See available tools
            tools = await session.list_tools()

            for tool in tools.tools:
                print(tool.name)

            # Call a tool directly
            result = await session.call_tool(
                "search_product",
                {"query": "headphones"}
            )

            print(result)


asyncio.run(main())