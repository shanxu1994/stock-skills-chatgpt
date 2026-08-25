from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
from typing import Any, Callable

from .t_strategy import TState, evaluate_t_state


DASHBOARD_STOCKS = (
    {"symbol": "001309", "name": "德明利"},
    {"symbol": "600110", "name": "诺德股份"},
    {"symbol": "300199", "name": "翰宇药业"},
)
MAX_DASHBOARD_STOCKS = 10


def _price(value: float) -> float:
    return round(float(value), 2)


def build_strict_signals(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build explainable signals while preserving the dashboard response shape."""
    metrics = snapshot["metrics"]
    current = float(metrics["current"])
    high = float(metrics["session_high"])
    low = float(metrics["session_low"])
    raw_vwap = metrics.get("vwap")
    vwap = float(raw_vwap) if raw_vwap is not None else None
    change_15m = metrics.get("change_15m_pct")
    change_30m = metrics.get("change_30m_pct")
    volume_ratio = metrics.get("last_5m_volume_ratio_vs_prev20")
    higher_lows = bool(metrics.get("higher_lows_last_3_bars"))

    day_range = max(high - low, current * 0.005)
    support = max(low, vwap - day_range * 0.18) if vwap is not None else low
    buy_upper = min(current, vwap + day_range * 0.06) if vwap is not None else low + day_range * 0.38
    reduce_low = max(current, high - day_range * 0.18)
    invalidation = max(0.01, low - day_range * 0.08)
    breakout = high + max(current * 0.001, day_range * 0.04)

    minute_bars = snapshot.get("one_minute_bars") or []
    state_result = evaluate_t_state(minute_bars)
    if not minute_bars:
        # Compatibility for callers that only provide aggregate metrics. Being
        # in the price zone is WATCH at most; aggregate data can never confirm.
        if vwap is None:
            fallback_state = TState.WAIT
        elif current > vwap * 1.025 or (change_15m is not None and change_15m < -1.2):
            fallback_state = TState.NO_TRADE
        elif abs(current / vwap - 1) <= 0.012:
            fallback_state = TState.WATCH
        else:
            fallback_state = TState.WAIT
        state_result = {
            "state": fallback_state.value,
            "structure": None,
            "score": 0,
            "conditions": {},
            "reasons": ["仅有汇总指标，价格到区只观察，分钟结构确认后才可触发"],
        }
    labels = {
        TState.WAIT.value: "WAIT · 等待结构",
        TState.WATCH.value: "WATCH · 观察确认",
        TState.CONFIRMED.value: "CONFIRMED · 共振确认",
        TState.NO_TRADE.value: "NO_TRADE · 禁止交易",
    }
    t_status = state_result["state"]
    t_label = labels[t_status]
    t_reasons = list(state_result["reasons"])

    positive_momentum = sum(value is not None and value > 0 for value in (change_15m, change_30m))
    if vwap is not None and current >= vwap and higher_lows and positive_momentum >= 1:
        trend_status, trend_label = "trial", "右侧试错观察"
        trend_reasons = ["价格位于 VWAP 上方", "低点抬高且动能为正"]
    elif current >= breakout:
        trend_status, trend_label = "confirm", "突破确认"
        trend_reasons = ["价格突破日内高点确认线"]
    else:
        trend_status, trend_label = "wait", "等待右侧确认"
        trend_reasons = ["尚未同时满足 VWAP、低点和动能条件"]

    return {
        "t_system": {
            "status": t_status,
            "label": t_label,
            "state": t_status,
            "structure": state_result.get("structure"),
            "resonance_score": state_result.get("score", 0),
            "conditions": state_result.get("conditions", {}),
            "buy_zone": [_price(support), _price(max(support, buy_upper))],
            "reduce_zone": [_price(reduce_low), _price(high)],
            "invalidation": _price(invalidation),
            "reasons": t_reasons,
        },
        "trend_system": {
            "status": trend_status.upper(),
            "label": trend_label,
            "trial_reference": _price(vwap if vwap is not None else current),
            "breakout_confirmation": _price(breakout),
            "add_condition": "突破确认位后回踩不破，且近5分钟量比不低于1",
            "invalidation": _price(min(vwap, low) if vwap is not None else low),
            "reasons": trend_reasons,
        },
    }


def dashboard_symbols(raw_symbols: str | None) -> list[dict[str, str]]:
    if not raw_symbols:
        return [dict(item) for item in DASHBOARD_STOCKS]
    symbols = []
    for raw in raw_symbols.split(","):
        symbol = raw.strip().upper().removeprefix("SH").removeprefix("SZ")
        symbol = symbol.removesuffix(".SH").removesuffix(".SZ")
        if not re.fullmatch(r"\d{6}", symbol):
            raise ValueError("股票代码必须是6位A股代码")
        if symbol not in symbols:
            symbols.append(symbol)
    if not symbols:
        raise ValueError("请至少输入一只股票")
    if len(symbols) > MAX_DASHBOARD_STOCKS:
        raise ValueError(f"最多同时分析{MAX_DASHBOARD_STOCKS}只股票")
    defaults = {item["symbol"]: item["name"] for item in DASHBOARD_STOCKS}
    return [{"symbol": symbol, "name": defaults.get(symbol, symbol)} for symbol in symbols]


def build_dashboard_payload(
    loader: Callable[[str, int], dict[str, Any]],
    configured_stocks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    selected = configured_stocks or [dict(item) for item in DASHBOARD_STOCKS]

    def load_one(configured: dict[str, str]) -> dict[str, Any]:
        try:
            snapshot = loader(configured["symbol"], 240)
            snapshot["name"] = snapshot.get("name") or configured["name"]
            return {**snapshot, "signals": build_strict_signals(snapshot)}
        except Exception:
            return {
                **configured,
                "error": "行情源暂不可用，请稍后刷新",
                "metrics": None,
                "signals": None,
            }

    # Stocks are independent. Loading concurrently prevents their public
    # provider fallback times from adding up on a Render request.
    with ThreadPoolExecutor(max_workers=min(5, len(selected))) as pool:
        stocks = list(pool.map(load_one, selected))
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "stocks": stocks,
        "disclaimer": "仅供行情研究与做T计划参考，不构成投资建议。",
    }
