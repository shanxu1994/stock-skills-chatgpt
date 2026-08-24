"""Read-only MCP tools for ChatGPT and other MCP clients.

This module deliberately reuses the existing intraday_snapshot service so the
REST Action endpoint and MCP endpoint always share the same Tencent-first data
pipeline and fallback behavior.
"""

from mcp.server.fastmcp import FastMCP

from .main import intraday_snapshot


mcp = FastMCP(
    "Stock Skills Intraday",
    stateless_http=True,
    json_response=True,
)
# This MCP app is mounted by FastAPI at /mcp. FastMCP defaults its internal
# Streamable HTTP route to /mcp too, which would produce /mcp/mcp. Setting the
# internal path to / makes the public endpoint exactly /mcp while remaining
# compatible with the pinned MCP 1.x dependency range.
mcp.settings.streamable_http_path = "/"


@mcp.tool()
def analyze_intraday(symbol: str, bars: int = 240) -> dict:
    """Get current A-share intraday data for trading research.

    Returns the latest minute snapshot using the existing Tencent-first public
    data pipeline, including VWAP, 15/30-minute change, volume behavior, recent
    one-minute bars, and five-minute bars. This tool is read-only.

    Args:
        symbol: A-share code such as 001309 or 001309.SZ.
        bars: Number of minute bars requested, from 30 to 600.
    """
    if bars < 30 or bars > 600:
        raise ValueError("bars must be between 30 and 600")
    return intraday_snapshot(symbol, bars)


mcp_app = mcp.streamable_http_app()
