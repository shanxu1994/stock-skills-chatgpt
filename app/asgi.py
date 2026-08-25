"""Combined ASGI entrypoint for REST, public read-only data, and MCP."""

from contextlib import asynccontextmanager
from html import escape

from fastapi import HTTPException, Query
from fastapi.responses import HTMLResponse

from .main import app, intraday_snapshot
from .mcp_server import mcp, mcp_app


def _load_public_intraday(symbol: str, bars: int):
    try:
        return intraday_snapshot(symbol, bars)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream data request failed: {exc}") from exc


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
    return _load_public_intraday(symbol, bars)


@app.get("/public/intraday/view", response_class=HTMLResponse, include_in_schema=False)
def public_intraday_view(
    symbol: str = Query(..., min_length=6, max_length=20, description="A-share code, e.g. 001309"),
    bars: int = Query(240, ge=30, le=600, description="Minute bars requested"),
):
    """Human-readable, crawl-friendly view of the public intraday snapshot."""
    snapshot = _load_public_intraday(symbol, bars)
    metrics = snapshot.get("metrics") or {}
    one_minute = snapshot.get("one_minute_bars") or []

    def value(key: str):
        raw = metrics.get(key)
        return "—" if raw is None else escape(str(raw))

    rows = "".join(
        "<tr>"
        f"<td>{escape(str(bar.get('time', '')))}</td>"
        f"<td>{escape(str(bar.get('open', '')))}</td>"
        f"<td>{escape(str(bar.get('high', '')))}</td>"
        f"<td>{escape(str(bar.get('low', '')))}</td>"
        f"<td>{escape(str(bar.get('close', '')))}</td>"
        f"<td>{escape(str(bar.get('volume', '')))}</td>"
        "</tr>"
        for bar in one_minute[-60:]
    )

    title = escape(str(snapshot.get("name") or snapshot.get("symbol") or symbol))
    normalized = escape(str(snapshot.get("symbol") or symbol))
    source = escape(str(snapshot.get("source") or "unknown"))
    as_of = escape(str(snapshot.get("as_of") or ""))

    html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{title} 分时行情</title>
<style>
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;margin:24px;line-height:1.5;color:#111}}
main{{max-width:980px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}}
.card{{border:1px solid #ddd;border-radius:10px;padding:12px}}
.label{{font-size:12px;color:#666}} .value{{font-size:20px;font-weight:650}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:7px;border-bottom:1px solid #eee;text-align:right}} th:first-child,td:first-child{{text-align:left}}
small{{color:#666}}
</style>
</head>
<body><main>
<h1>{title} <small>{normalized}</small></h1>
<p>更新时间：{as_of} ｜ 数据源：{source}</p>
<div class=\"grid\">
<div class=\"card\"><div class=\"label\">当前价</div><div class=\"value\">{value('current')}</div></div>
<div class=\"card\"><div class=\"label\">VWAP</div><div class=\"value\">{value('vwap')}</div></div>
<div class=\"card\"><div class=\"label\">日内高点</div><div class=\"value\">{value('session_high')}</div></div>
<div class=\"card\"><div class=\"label\">日内低点</div><div class=\"value\">{value('session_low')}</div></div>
<div class=\"card\"><div class=\"label\">15分钟变化%</div><div class=\"value\">{value('change_15m_pct')}</div></div>
<div class=\"card\"><div class=\"label\">30分钟变化%</div><div class=\"value\">{value('change_30m_pct')}</div></div>
<div class=\"card\"><div class=\"label\">近5分钟量比</div><div class=\"value\">{value('last_5m_volume_ratio_vs_prev20')}</div></div>
<div class=\"card\"><div class=\"label\">最近3根低点抬高</div><div class=\"value\">{value('higher_lows_last_3_bars')}</div></div>
</div>
<h2>最近1分钟数据</h2>
<table><thead><tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>量</th></tr></thead><tbody>{rows}</tbody></table>
<p><small>仅供行情研究，不构成投资建议。</small></p>
</main></body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})


@asynccontextmanager
async def lifespan(_app):
    # Streamable HTTP MCP requires its session manager to run for the lifetime
    # of the host application. The existing FastAPI app has no custom lifespan,
    # so this wrapper does not replace any application startup/shutdown work.
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_app)
