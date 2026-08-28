import asyncio
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain.agents import create_agent


MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN = os.getenv("HF_TOKEN")


async def main():

    # -------------------------
    # 1. Connect to MCP
    # -------------------------

    client = MultiServerMCPClient(
        {
            "gaming_store": {
                "transport": "streamable_http",
                "url": MCP_URL,
            }
        }
    )

    # -------------------------
    # 2. Discover MCP tools
    # -------------------------

    tools = await client.get_tools()

    print("MCP tools:")

    for tool in tools:
        print("-", tool.name)

    # -------------------------
    # 3. Create LLM
    # -------------------------

    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN is required. Set it before running ai.py.")

    endpoint = HuggingFaceEndpoint(
        repo_id=HF_MODEL,
        task="text-generation",
        huggingfacehub_api_token=HF_TOKEN,
        max_new_tokens=512,
        temperature=0,
    )
    model = ChatHuggingFace(llm=endpoint)

    # -------------------------
    # 4. Create agent
    # -------------------------

    agent = create_agent(
        model,
        tools
    )

    # -------------------------
    # 5. Ask the agent
    # -------------------------

    response = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Find me a gaming mouse "
                        "under ₹2000."
                    )
                }
            ]
        }
    )

    # -------------------------
    # 6. Print final response
    # -------------------------

    print("\nFINAL RESPONSE:\n")

    print(
        response["messages"][-1].content
    )


if __name__ == "__main__":
    asyncio.run(main())