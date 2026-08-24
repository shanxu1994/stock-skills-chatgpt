"""Combined ASGI entrypoint for REST, public read-only data, and MCP."""

from contextlib import asynccontextmanager

from fastapi import HTTPException, Query

from .main import app, intraday_snapshot
from .mcp_server import mcp, mcp_app


@app.get("/public/intraday", operation_id="publicIntraday", include_in_schema=True)
def public_intraday(
    symbol: str = Query(..., min_length=6, max_length=20, description="A-share code, e.g. 001309"),
    bars: int = Query(240, ge=30, le=600, description="Minute bars requested"),
):
    """Public read-only A-share intraday snapshot for research.

    Reuses the same Tencent-first minute pipeline as the authenticated Action
    and MCP tool. No credentials, writes, account data, or private data are
    exposed by this endpoint.
    """
    try:
        return intraday_snapshot(symbol, bars)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream data request failed: {exc}") from exc


@asynccontextmanager
async def lifespan(_app):
    # Streamable HTTP MCP requires its session manager to run for the lifetime
    # of the host application. The existing FastAPI app has no custom lifespan,
    # so this wrapper does not replace any application startup/shutdown work.
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_app)
