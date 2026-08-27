"""Fetcher-friendly public endpoint for ChatGPT and other read-only clients."""

import json
import re

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from .analysis_data import unified_analysis_data


def register_chatgpt_bridge(app):
    @app.get("/public/analysis-text/{symbol}", response_class=PlainTextResponse, include_in_schema=False)
    def public_analysis_text(symbol: str):
        if not re.fullmatch(r"\d{6}", symbol):
            raise HTTPException(status_code=422, detail="symbol must be a 6-digit A-share code")
        try:
            payload = unified_analysis_data(symbol)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Unified market data request failed: {exc}") from exc
        return PlainTextResponse(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            media_type="application/json; charset=utf-8",
            headers={
                "Cache-Control": "public, max-age=5, s-maxage=5",
                "X-Robots-Tag": "index, follow",
                "X-Content-Type-Options": "nosniff",
            },
        )
