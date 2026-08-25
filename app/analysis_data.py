"""Unified read-only market data payload for strict-entry analysis.

This module intentionally reuses the existing intraday pipeline and existing
indicator function. Strategy thresholds and indicator formulas are not changed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from . import services as stock_services
from .main import _eastmoney_secid, _public_get, intraday_snapshot


STRICT_POLICY_VERSION = "existing-strict-entry-v1"


def _normalize_daily_frame(frame: pd.DataFrame, days: int) -> pd.DataFrame:
    rename = {
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    frame = frame.rename(columns={k: v for k, v in rename.items() if k in frame.columns}).copy()
    required = ["trade_date", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"Daily data missing columns: {missing}")
    frame = frame[required]
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "close", "volume"]).tail(days)
    if frame.empty:
        raise RuntimeError("No valid daily bars")
    return frame


def _fetch_eastmoney_daily(normalized: str, days: int) -> tuple[pd.DataFrame, str | None]:
    response = _public_get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": _eastmoney_secid(normalized),
            "klt": 101,
            "fqt": 1,
            "lmt": max(days, 120),
            "end": "20500101",
            "iscca": 1,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        },
        referer="https://quote.eastmoney.com/",
    )
    payload = response.json().get("data") or {}
    rows = payload.get("klines") or []
    if not rows:
        raise RuntimeError("Eastmoney returned no daily bars")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 6:
            continue
        parsed.append({
            "trade_date": parts[0],
            "open": parts[1],
            "close": parts[2],
            "high": parts[3],
            "low": parts[4],
            "volume": parts[5],
        })
    return _normalize_daily_frame(pd.DataFrame(parsed), days), payload.get("name")


def _fetch_akshare_daily(normalized: str, days: int) -> tuple[pd.DataFrame, str | None]:
    code = normalized.split(".")[0]
    ak = stock_services._akshare()
    frame = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    if frame is None or frame.empty:
        raise RuntimeError("AkShare returned no daily bars")
    return _normalize_daily_frame(frame, days), None


def daily_snapshot(symbol: str, days: int = 120) -> dict[str, Any]:
    market, normalized = stock_services.normalize_symbol(symbol)
    if market != "a":
        raise RuntimeError("Unified public analysis currently supports A-shares only")

    providers = [
        ("eastmoney_public_http", _fetch_eastmoney_daily),
        ("akshare_public", _fetch_akshare_daily),
    ]
    attempts: list[dict[str, Any]] = []
    frame = None
    name = None
    source = None
    for source_name, provider in providers:
        try:
            frame, name = provider(normalized, days)
            source = source_name
            attempts.append({"source": source_name, "ok": True})
            break
        except Exception as exc:
            attempts.append({"source": source_name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    if frame is None or source is None:
        # Final compatibility fallback: reuse the existing history implementation
        # when the deployment already has Tushare configured.
        try:
            frame, name = stock_services._a_share_history(normalized, days)
            source = "tushare_compatibility_fallback"
            attempts.append({"source": source, "ok": True})
        except Exception as exc:
            attempts.append({"source": "tushare_compatibility_fallback", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            details = "; ".join(f"{item['source']} -> {item.get('error', 'ok')}" for item in attempts)
            raise RuntimeError(f"All daily providers failed for {normalized}: {details}") from exc

    if not name:
        try:
            name_df = stock_services._public_stock_name(normalized)
            if name_df is not None and not name_df.empty:
                name = str(name_df.iloc[0]["name"])
        except Exception:
            name = None

    indicators = stock_services._indicators(frame.copy())
    latest = frame.iloc[-1]
    recent_bars = []
    for _, row in frame.tail(30).iterrows():
        recent_bars.append({
            "trade_date": str(row["trade_date"]),
            "open": round(float(row["open"]), 4),
            "high": round(float(row["high"]), 4),
            "low": round(float(row["low"]), 4),
            "close": round(float(row["close"]), 4),
            "volume": round(float(row["volume"]), 4),
        })

    failed = [item for item in attempts if not item["ok"]]
    return {
        "symbol": normalized,
        "name": name,
        "as_of": str(latest["trade_date"]),
        "source": source,
        "fallback": bool(failed),
        "source_attempts": attempts,
        "indicators": indicators,
        "recent_daily_bars": recent_bars,
        "data_points": len(frame),
    }


def unified_analysis_data(symbol: str) -> dict[str, Any]:
    intraday = intraday_snapshot(symbol, 240)
    daily = daily_snapshot(symbol, 120)
    return {
        "symbol": daily["symbol"],
        "name": intraday.get("name") or daily.get("name"),
        "generated_at": datetime.now().astimezone().isoformat(),
        "strategy_contract": {
            "version": STRICT_POLICY_VERSION,
            "indicator_engine": "services._indicators",
            "parameters_changed": False,
        },
        "intraday": intraday,
        "daily": daily,
        "meta": {
            "intraday_source": intraday.get("source"),
            "intraday_as_of": intraday.get("as_of"),
            "daily_source": daily.get("source"),
            "daily_as_of": daily.get("as_of"),
            "intraday_fallback": intraday.get("fallback"),
            "daily_fallback": daily.get("fallback"),
        },
        "disclaimer": "Market research only; not investment advice.",
    }
