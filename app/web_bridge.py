"""Crawler-friendly read-only bridge for realtime stock analysis.

Keeps the existing REST/MCP API unchanged while exposing simple server-rendered
text plus discovery endpoints that generic web readers can consume reliably.
"""

import json

from fastapi import Path
from fastapi.responses import PlainTextResponse, Response

from .asgi import app, _load_analysis_data, _validate_fixed_symbol


_BASE = "https://stock-skills-chatgpt-p4vq.onrender.com"


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots_txt():
    return PlainTextResponse(
        "User-agent: *\nAllow: /public/\nSitemap: " + _BASE + "/sitemap.xml\n",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    urls = [
        f"{_BASE}/public/analysis",
        f"{_BASE}/public/analysis/001309",
        f"{_BASE}/public/analysis-text/001309",
        f"{_BASE}/public/analysis/600110",
        f"{_BASE}/public/analysis-text/600110",
    ]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n' + (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{url}</loc></url>\n" for url in urls)
        + "</urlset>\n"
    )
    return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=300"})


@app.get("/public/analysis-text/{symbol}", operation_id="publicAnalysisText", response_class=PlainTextResponse)
def public_analysis_text(symbol: str = Path(...)):
    symbol = _validate_fixed_symbol(symbol)
    payload = _load_analysis_data(symbol)
    intraday = payload.get("intraday") or {}
    metrics = intraday.get("metrics") or {}
    daily = payload.get("daily") or {}
    indicators = daily.get("indicators") or {}
    meta = payload.get("meta") or {}

    fields = {
        "symbol": payload.get("symbol") or symbol,
        "name": payload.get("name"),
        "intraday_as_of": meta.get("intraday_as_of") or intraday.get("as_of"),
        "intraday_source": meta.get("intraday_source") or intraday.get("source"),
        "current": metrics.get("current"),
        "vwap": metrics.get("vwap"),
        "session_high": metrics.get("session_high"),
        "session_low": metrics.get("session_low"),
        "change_15m_pct": metrics.get("change_15m_pct"),
        "change_30m_pct": metrics.get("change_30m_pct"),
        "daily_as_of": meta.get("daily_as_of") or daily.get("as_of"),
        "daily_source": meta.get("daily_source") or daily.get("source"),
        "ma5": indicators.get("ma5"),
        "ma10": indicators.get("ma10"),
        "ma20": indicators.get("ma20"),
        "macd": indicators.get("macd"),
        "macd_signal": indicators.get("macd_signal"),
        "rsi14": indicators.get("rsi14"),
        "bias_ma5_pct": indicators.get("bias_ma5_pct"),
        "volume_ratio_5_20": indicators.get("volume_ratio_5_20"),
        "strict_signal": indicators.get("signal") or indicators.get("strict_signal"),
        "strict_score": indicators.get("score") or indicators.get("strict_score"),
        "recent_1m_bars": (intraday.get("one_minute_bars") or [])[-30:],
    }
    text = "REALTIME A-SHARE ANALYSIS\n" + "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        for key, value in fields.items()
    )
    return PlainTextResponse(
        text + "\n",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Robots-Tag": "index, follow",
            "Access-Control-Allow-Origin": "*",
        },
    )
