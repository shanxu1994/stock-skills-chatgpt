"""Combined ASGI entrypoint for the existing REST API and read-only MCP API."""

from contextlib import asynccontextmanager

from .main import app
from .mcp_server import mcp, mcp_app


@asynccontextmanager
async def lifespan(_app):
    # Streamable HTTP MCP requires its session manager to run for the lifetime
    # of the host application. The existing FastAPI app has no custom lifespan,
    # so this wrapper does not replace any application startup/shutdown work.
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_app)
