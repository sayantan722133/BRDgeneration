import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CLIENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = PROJECT_ROOT / "brd_generation" / "mcp_server&functions"
SERVER_SCRIPT = SERVER_DIR / "customfun.py"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CLIENT_DIR))

from brd_generator import generate_brd


async def run_client(jira_key: str, provider: str) -> None:
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=os.environ.copy(),
    )

    print("Connecting to Jira MCP Server via stdio...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            print(
                f"Discovered {len(tools_result.tools)} tools from MCP server: "
                f"{[tool.name for tool in tools_result.tools]}"
            )
            await generate_brd(session, jira_key, tools_result.tools, provider)


def main(default_provider: str = "gemini") -> None:
    parser = argparse.ArgumentParser(description="Generate a BRD from a Jira business vision.")
    parser.add_argument("jira_key", help="Jira issue key, for example PROJ-12")
    parser.add_argument(
        "--provider",
        choices=("gemini", "local"),
        default=default_provider,
        help="Language model provider (default: %(default)s)",
    )
    args = parser.parse_args()
    asyncio.run(run_client(args.jira_key, args.provider))


if __name__ == "__main__":
    main()