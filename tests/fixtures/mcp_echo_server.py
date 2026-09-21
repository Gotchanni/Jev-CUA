from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cua-jev-test")


@mcp.tool()
def echo(text: str) -> dict[str, str]:
    """Return controlled test input."""
    return {"echo": text}


if __name__ == "__main__":
    mcp.run(transport="stdio")
