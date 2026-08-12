from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    clean = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return clean.to_dict(orient="records")


def _tushare_client():
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured")
    import tushare as ts

    return ts.pro_api(token)


def _has_tushare_token() -> bool:
    return bool(os.getenv("TUSHARE_TOKEN", "").strip())


def _fallback_reason(exc: Exception | None) -> str:
    if exc is None:
        return "TUSHARE_TOKEN is not configured"
    return f"Tushare unavailable or permission denied: {exc}"


def _akshare():
    import akshare as ak

    return ak


def _date_value(value: Any) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def _rename_available(df: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    return df.rename(columns={key: value for key, value in columns.items() if key in df.columns})


def _fallback_result(items: list[dict[str, Any]], reason: str, **extra: Any) -> dict[str, Any]:
    return {
        **extra,
        "items": items,
        "source": "akshare",
        "fallback": True,
        "fallback_reason": reason,
        "disclaimer": "Market research only; not investment advice.",
    }


def normalize_symbol(symbol: str) -> tuple[str, str]:
    raw = symbol.strip().upper()
    if raw.startswith("HK") and raw[2:].isdigit():
        return "hk", f"{int(raw[2:]):04d}.HK"
    if raw.startswith(("SH", "SZ")) and raw[2:].isdigit():
        raw = raw[2:]
    raw = raw.removesuffix(".SH").removesuffix(".SS").removesuffix(".SZ")
    if raw.isdigit() and len(raw) == 6:
        suffix = "SH" if raw.startswith(("5", "6", "9")) else "SZ"
        return "a", f"{raw}.{suffix}"
    if symbol.upper().endswith(".HK"):
        return "hk", symbol.upper()
    return "us", symbol.upper()


def _indicators(frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    for window in (5, 10, 20, 60):
        frame[f"ma{window}"] = close.rolling(window).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    frame["macd"] = ema12 - ema26
    frame["macd_signal"] = frame["macd"].ewm(span=9, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    frame["rsi14"] = 100 - (100 / (1 + rs))
    frame["volume_ratio_5_20"] = volume.rolling(5).mean() / volume.rolling(20).mean()
    frame["bias_ma5"] = (close / frame["ma5"] - 1) * 100
    last = frame.iloc[-1]

    score = 50
    score += 10 if last["close"] > last["ma20"] else -10
    score += 8 if last["ma5"] > last["ma10"] > last["ma20"] else -4
    score += 8 if last["macd"] > last["macd_signal"] else -8
    rsi = float(last["rsi14"]) if pd.notna(last["rsi14"]) else 50.0
    score += 6 if 45 <= rsi <= 70 else (-12 if rsi > 80 else 0)
    score += 4 if last["volume_ratio_5_20"] > 1 else 0
    score = max(0, min(100, score))
    if rsi > 80 or last["bias_ma5"] > 5:
        signal = "avoid_chasing"
    elif score >= 72:
        signal = "strong"
    elif score >= 55:
        signal = "neutral_positive"
    elif score >= 40:
        signal = "neutral_negative"
    else:
        signal = "weak"

    def value(name: str) -> float | None:
        item = last[name]
        return round(float(item), 4) if pd.notna(item) else None

    return {
        "close": value("close"),
        "ma5": value("ma5"), "ma10": value("ma10"),
        "ma20": value("ma20"), "ma60": value("ma60"),
        "macd": value("macd"), "macd_signal": value("macd_signal"),
        "rsi14": value("rsi14"), "volume_ratio_5_20": value("volume_ratio_5_20"),
        "bias_ma5_pct": value("bias_ma5"), "score": score, "signal": signal,
    }


def _a_share_history(ts_code: str, days: int) -> tuple[pd.DataFrame, str | None]:
    pro = _tushare_client()
    end = date.today()
    start = end - timedelta(days=max(days * 2, 120))
    df = pro.daily(ts_code=ts_code, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    if df is None or df.empty:
        raise RuntimeError("No market data returned")
    df = df.sort_values("trade_date").tail(days).rename(columns={"vol": "volume"})
    name_df = pro.stock_basic(ts_code=ts_code, fields="name")
    name = None if name_df is None or name_df.empty else str(name_df.iloc[0]["name"])
    return df[["trade_date", "open", "high", "low", "close", "volume"]], name


def _global_history(symbol: str, days: int) -> tuple[pd.DataFrame, str | None]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=f"{max(days * 2, 90)}d", auto_adjust=False)
    if df.empty:
        raise RuntimeError("No market data returned")
    df = df.tail(days).reset_index().rename(columns={
        "Date": "trade_date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    name = ticker.fast_info.get("shortName") if hasattr(ticker, "fast_info") else None
    return df[["trade_date", "open", "high", "low", "close", "volume"]], name


def _news(query: str) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    import httpx

    response = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": f"{query} 股票 最新消息", "max_results": 5, "topic": "news"},
        timeout=20,
    )
    response.raise_for_status()
    return [
        {"title": item.get("title"), "url": item.get("url"), "content": item.get("content"), "score": item.get("score")}
        for item in response.json().get("results", [])[:5]
    ]


def analyze_stocks(symbols: list[str], days: int, include_news: bool) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for requested in symbols:
        market, normalized = normalize_symbol(requested)
        try:
            frame, name = _a_share_history(normalized, days) if market == "a" else _global_history(normalized, days)
            results.append({
                "requested_symbol": requested,
                "symbol": normalized,
                "market": market,
                "name": name,
                "as_of": str(frame.iloc[-1]["trade_date"]),
                "indicators": _indicators(frame),
                "news": _news(name or normalized) if include_news else [],
                "data_points": len(frame),
                "error": None,
            })
        except Exception as exc:
            results.append({"requested_symbol": requested, "symbol": normalized, "market": market, "error": str(exc)})
    return {"generated_at": datetime.now().astimezone().isoformat(), "results": results, "disclaimer": "Market research only; not investment advice."}


def sector_rank(trade_date: str | None, top: int) -> dict[str, Any]:
    selected = trade_date or date.today().strftime("%Y%m%d")
    tushare_error: Exception | None = None
    if _has_tushare_token():
        try:
            df = _tushare_client().ths_daily(trade_date=selected, fields="ts_code,name,close,pct_chg,vol,turnover_rate,total_mv")
            if df is not None and not df.empty:
                df = df[df["ts_code"].astype(str).str.startswith("885")].copy()
                df = df.sort_values("pct_chg", ascending=False).head(top)
                return {"trade_date": selected, "items": _records(df), "source": "tushare", "fallback": False, "disclaimer": "Market research only; not investment advice."}
            tushare_error = RuntimeError("No data returned")
        except Exception as exc:
            tushare_error = exc

    reason = _fallback_reason(tushare_error)
    try:
        df = _akshare().stock_board_concept_name_em()
        df = _rename_available(df, {
            "板块名称": "name", "板块代码": "ts_code", "最新价": "close",
            "涨跌幅": "pct_chg", "成交量": "vol", "换手率": "turnover_rate",
            "总市值": "total_mv",
        })
        if "pct_chg" in df:
            df = df.sort_values("pct_chg", ascending=False)
        return _fallback_result(_records(df.head(top)), reason, trade_date=selected)
    except Exception as exc:
        return _fallback_result([], reason, trade_date=selected, note=f"AkShare fallback failed: {exc}")


def lhb_rank(trade_date: str | None, top: int, ts_code: str | None) -> dict[str, Any]:
    selected = trade_date or date.today().strftime("%Y%m%d")
    params: dict[str, Any] = {"trade_date": selected}
    if ts_code:
        params["ts_code"] = ts_code
    tushare_error: Exception | None = None
    df: pd.DataFrame | None = None
    if _has_tushare_token():
        try:
            df = _tushare_client().top_list(**params)
            if df is None or df.empty:
                tushare_error = RuntimeError("No data returned")
                df = None
        except Exception as exc:
            tushare_error = exc
    if df is None:
        reason = _fallback_reason(tushare_error)
        try:
            df = _akshare().stock_lhb_detail_em(start_date=selected, end_date=selected)
            df = _rename_available(df, {
                "代码": "ts_code", "名称": "name", "上榜日": "trade_date",
                "涨跌幅": "pct_change", "龙虎榜净买额": "net_amount",
                "龙虎榜净买额占总成交额比": "net_rate", "收盘价": "close",
                "成交额": "amount", "换手率": "turnover_rate", "上榜原因": "reason",
            })
            if ts_code and "ts_code" in df:
                code = ts_code.split(".")[0]
                df = df[df["ts_code"].astype(str).str.zfill(6) == code]
        except Exception as exc:
            return _fallback_result([], reason, trade_date=selected, note=f"AkShare fallback failed: {exc}")
    if df.empty:
        result = {"trade_date": selected, "note": "No Dragon Tiger List data for this date."}
        if tushare_error is not None or not _has_tushare_token():
            return _fallback_result([], _fallback_reason(tushare_error), **result)
        return {**result, "source": "tushare", "fallback": False}
    names = df["name"].fillna("").astype(str).str.upper()
    df = df[~names.str.startswith(("ST", "*ST", "S*ST", "SST"))].copy()
    for column in ("pct_change", "net_amount", "net_rate"):
        if column not in df:
            df[column] = 0.0
    df["score"] = (
        df["pct_change"].rank(pct=True) * 40
        + df["net_amount"].rank(pct=True) * 40
        + df["net_rate"].rank(pct=True) * 20
    ).round(2)
    df = df.sort_values("score", ascending=False).head(top)
    result = {"trade_date": selected, "items": _records(df), "disclaimer": "Market research only; not investment advice."}
    if tushare_error is not None or not _has_tushare_token():
        result.update({"source": "akshare", "fallback": True, "fallback_reason": _fallback_reason(tushare_error)})
    else:
        result.update({"source": "tushare", "fallback": False})
    return result


def _akshare_query(api_name: str, params: dict[str, Any], limit: int) -> pd.DataFrame | None:
    ak = _akshare()
    if api_name == "stock_basic":
        df = ak.stock_info_a_code_name()
        return _rename_available(df, {"code": "symbol", "name": "name"})
    if api_name == "trade_cal":
        df = ak.tool_trade_date_hist_sina()
        df = _rename_available(df, {"trade_date": "cal_date"})
        if "cal_date" in df:
            df["cal_date"] = df["cal_date"].map(_date_value)
            start = str(params.get("start_date", ""))
            end = str(params.get("end_date", ""))
            if start:
                df = df[df["cal_date"] >= start]
            if end:
                df = df[df["cal_date"] <= end]
            df["is_open"] = 1
        return df
    if api_name in {"daily", "weekly", "monthly"}:
        code = str(params.get("ts_code", params.get("symbol", ""))).split(".")[0]
        if not code:
            return None
        period = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}[api_name]
        df = ak.stock_zh_a_hist(
            symbol=code,
            period=period,
            start_date=str(params.get("start_date", "19700101")),
            end_date=str(params.get("end_date", date.today().strftime("%Y%m%d"))),
            adjust="",
        )
        df = _rename_available(df, {
            "日期": "trade_date", "股票代码": "ts_code", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "vol", "成交额": "amount",
            "振幅": "amplitude", "涨跌幅": "pct_chg", "涨跌额": "change", "换手率": "turnover_rate",
        })
        if "trade_date" in df:
            df["trade_date"] = df["trade_date"].map(_date_value)
        if "ts_code" not in df:
            df["ts_code"] = params.get("ts_code", code)
        return df
    if api_name == "ths_index":
        return _rename_available(ak.stock_board_concept_name_em(), {"板块代码": "ts_code", "板块名称": "name", "涨跌幅": "pct_chg"})
    if api_name == "top_list":
        selected = str(params.get("trade_date", date.today().strftime("%Y%m%d")))
        return _rename_available(ak.stock_lhb_detail_em(start_date=selected, end_date=selected), {"代码": "ts_code", "名称": "name", "上榜日": "trade_date", "涨跌幅": "pct_change", "龙虎榜净买额": "net_amount"})
    return None


def tushare_query(api_name: str, params: dict[str, Any], fields: list[str] | None, limit: int) -> dict[str, Any]:
    safe_params = {key: value for key, value in params.items() if value is not None}
    tushare_error: Exception | None = None
    if _has_tushare_token():
        try:
            query_params = dict(safe_params)
            if fields:
                query_params["fields"] = ",".join(fields)
            df = getattr(_tushare_client(), api_name)(**query_params)
            rows = [] if df is None else _records(df.head(limit))
            return {"api_name": api_name, "params": query_params, "count": len(rows), "truncated": bool(df is not None and len(df) > limit), "items": rows, "source": "tushare", "fallback": False}
        except Exception as exc:
            tushare_error = exc

    reason = _fallback_reason(tushare_error)
    try:
        df = _akshare_query(api_name, safe_params, limit)
        if df is None:
            return _fallback_result([], reason, api_name=api_name, params=safe_params, count=0, truncated=False, note=f"The public fallback does not currently support {api_name}.")
        if fields:
            available = [field for field in fields if field in df.columns]
            if available:
                df = df[available]
        rows = _records(df.head(limit))
        return _fallback_result(rows, reason, api_name=api_name, params=safe_params, count=len(rows), truncated=len(df) > limit)
    except Exception as exc:
        return _fallback_result([], reason, api_name=api_name, params=safe_params, count=0, truncated=False, note=f"AkShare fallback failed: {exc}")
