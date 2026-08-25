from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

import pandas as pd


class TState(str, Enum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    CONFIRMED = "CONFIRMED"
    NO_TRADE = "NO_TRADE"


class DailyPermission(str, Enum):
    ALLOW = "ALLOW"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class StrategyConfig:
    min_bars: int = 31
    watch_vwap_distance: float = 0.012
    max_vwap_extension: float = 0.025
    breakout_buffer: float = 0.001
    retest_tolerance: float = 0.004
    min_confirmation_score: int = 5


def _frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows).copy()
    required = {"open", "high", "low", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    for column in required | {"amount"}:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=list(required)).reset_index(drop=True)


def _vwap(frame: pd.DataFrame) -> float | None:
    volume = float(frame["volume"].sum())
    if volume <= 0:
        return None
    if "amount" in frame and float(frame["amount"].fillna(0).sum()) > 0:
        amount = float(frame["amount"].fillna(0).sum())
        current = float(frame.iloc[-1]["close"])
        for candidate in (amount / volume, amount / (volume * 100)):
            if current * 0.25 <= candidate <= current * 4:
                return candidate
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    return float((typical * frame["volume"]).sum() / volume)


def _pct_change(frame: pd.DataFrame, bars: int) -> float | None:
    if len(frame) <= bars:
        return None
    base = float(frame.iloc[-bars - 1]["close"])
    return (float(frame.iloc[-1]["close"]) / base - 1) * 100 if base else None


def evaluate_daily_trend(
    rows: Iterable[dict[str, Any]], *, before_date: str | None = None
) -> dict[str, Any]:
    """Decide whether intraday T trading is allowed using completed daily bars."""
    frame = _frame(rows)
    if before_date and "trade_date" in frame:
        dates = pd.to_datetime(frame["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        frame = frame.loc[dates < before_date].reset_index(drop=True)
    if len(frame) < 20:
        return {
            "permission": DailyPermission.BLOCK.value,
            "regime": "INSUFFICIENT_DATA",
            "score": 0,
            "reasons": ["不足20根已完成日K，禁止仅凭分时入场"],
            "as_of": None,
        }

    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    ma5 = float(close.tail(5).mean())
    ma10 = float(close.tail(10).mean())
    ma20 = float(close.tail(20).mean())
    prior_ma20 = float(close.iloc[-25:-5].mean()) if len(frame) >= 25 else float(close.iloc[:-5].tail(20).mean())
    current = float(close.iloc[-1])
    bias_ma5 = (current / ma5 - 1) * 100 if ma5 else 0.0
    delta = close.diff()
    gains = delta.clip(lower=0).tail(14).mean()
    losses = -delta.clip(upper=0).tail(14).mean()
    if losses == 0 and gains == 0:
        rsi14 = 50.0
    elif losses == 0:
        rsi14 = 100.0
    else:
        rsi14 = float(100 - 100 / (1 + gains / losses))
    volume_ratio = float(volume.tail(5).mean() / volume.tail(20).mean()) if volume.tail(20).mean() > 0 else None

    conditions = {
        "above_ma20": current >= ma20,
        "bullish_alignment": ma5 > ma10 > ma20,
        "ma20_rising": ma20 >= prior_ma20,
        "not_extended": bias_ma5 <= 5 and rsi14 <= 80,
    }
    score = sum(conditions.values())
    hard_downtrend = current < ma20 and ma5 < ma10 < ma20 and not conditions["ma20_rising"]
    extended = not conditions["not_extended"]
    if hard_downtrend or extended:
        permission = DailyPermission.BLOCK
        regime = "DOWNTREND" if hard_downtrend else "EXTENDED"
    elif score >= 3:
        permission = DailyPermission.ALLOW
        regime = "UPTREND"
    else:
        permission = DailyPermission.CAUTION
        regime = "RANGE"

    reasons = [f"日线趋势条件 {score}/4"]
    if hard_downtrend:
        reasons.append("收盘低于MA20且均线空头排列，暂停做T")
    elif extended:
        reasons.append("日线乖离或RSI过热，避免盘中追高")
    elif permission == DailyPermission.ALLOW:
        reasons.append("日线趋势允许，等待分时结构确认")
    else:
        reasons.append("日线震荡，仅允许更严格的分时确认")
    return {
        "permission": permission.value,
        "regime": regime,
        "score": score,
        "conditions": conditions,
        "reasons": reasons,
        "as_of": str(frame.iloc[-1].get("trade_date", "")),
        "metrics": {
            "close": round(current, 4), "ma5": round(ma5, 4),
            "ma10": round(ma10, 4), "ma20": round(ma20, 4),
            "rsi14": round(rsi14, 4), "bias_ma5_pct": round(bias_ma5, 4),
            "volume_ratio_5_20": round(volume_ratio, 4) if volume_ratio is not None else None,
        },
    }


def evaluate_t_state(
    rows: Iterable[dict[str, Any]], config: StrategyConfig | None = None,
    daily_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the latest bar using its prefix only; safe for live use and replay."""
    config = config or StrategyConfig()
    if daily_gate and daily_gate.get("permission") == DailyPermission.BLOCK.value:
        return {
            "state": TState.NO_TRADE.value, "structure": None, "score": 0,
            "conditions": {},
            "reasons": ["日线门控禁止当日做T", *daily_gate.get("reasons", [])],
            "daily_gate": daily_gate,
        }
    frame = _frame(rows)
    if len(frame) < config.min_bars:
        return {
            "state": TState.WAIT.value, "structure": None, "score": 0,
            "conditions": {}, "reasons": [f"至少需要{config.min_bars}根分钟K线"],
        }

    current = float(frame.iloc[-1]["close"])
    previous = float(frame.iloc[-2]["close"])
    vwap = _vwap(frame)
    change_15m = _pct_change(frame, 15)
    change_30m = _pct_change(frame, 30)
    recent5 = float(frame.tail(5)["volume"].mean())
    prev20 = float(frame.iloc[-25:-5]["volume"].mean())
    volume_ratio = recent5 / prev20 if prev20 > 0 else None
    lows = frame.tail(3)["low"].astype(float).tolist()
    higher_lows = lows[0] < lows[1] < lows[2]

    # Structure A: an earlier impulse, a controlled/contracting pullback, then
    # a fresh uptick. The peak is deliberately excluded from the latest bars.
    impulse_peak = float(frame.iloc[-18:-6]["high"].max())
    pullback_low = float(frame.iloc[-6:-1]["low"].min())
    pullback_depth = (impulse_peak - pullback_low) / impulse_peak if impulse_peak else 0
    contraction_base = float(frame.iloc[-16:-6]["volume"].mean())
    contraction = float(frame.iloc[-6:-1]["volume"].mean()) < contraction_base * 0.85
    restart = current > previous and float(frame.iloc[-1]["volume"]) > float(frame.iloc[-4:-1]["volume"].mean())
    pullback_structure = 0.003 <= pullback_depth <= 0.035 and contraction and restart

    # Structure B: break the prior range, retest that known level, and restart.
    range_high = float(frame.iloc[-25:-9]["high"].max())
    post_range = frame.iloc[-9:]
    breakout_positions = [
        i for i in range(0, len(post_range) - 2)
        if float(post_range.iloc[i]["close"]) >= range_high * (1 + config.breakout_buffer)
    ]
    breakout_retest = False
    if breakout_positions:
        breakout_pos = breakout_positions[0]
        retest = post_range.iloc[breakout_pos + 1:-1]
        breakout_retest = (
            not retest.empty
            and float(retest["low"].min()) >= range_high * (1 - config.retest_tolerance)
            and current > range_high
            and restart
        )

    conditions = {
        "above_vwap": vwap is not None and current >= vwap,
        "higher_lows": higher_lows,
        "momentum_15m": change_15m is not None and change_15m > 0,
        "momentum_30m": change_30m is not None and change_30m > -0.30,
        "volume_resonance": volume_ratio is not None and volume_ratio >= 0.90,
        "restart": restart,
    }
    score = sum(conditions.values())
    structure = "PULLBACK_RESTART" if pullback_structure else "BREAKOUT_RETEST_RESTART" if breakout_retest else None

    overheated = (
        vwap is None
        or current > vwap * (1 + config.max_vwap_extension)
        or (change_15m is not None and change_15m > 2.5)
        or (change_15m is not None and change_15m < -1.2)
    )
    near_setup = (
        vwap is not None
        and abs(current / vwap - 1) <= config.watch_vwap_distance
        and (pullback_depth <= 0.045 or bool(breakout_positions))
    )

    required_score = config.min_confirmation_score + (
        1 if daily_gate and daily_gate.get("permission") == DailyPermission.CAUTION.value else 0
    )
    if daily_gate and daily_gate.get("permission") == DailyPermission.CAUTION.value:
        required_score = min(required_score, len(conditions))

    if overheated:
        state = TState.NO_TRADE
    elif structure and score >= required_score:
        state = TState.CONFIRMED
    elif near_setup or pullback_structure or breakout_retest:
        state = TState.WATCH
    else:
        state = TState.WAIT

    reasons = [f"共振条件 {score}/6"]
    if structure:
        reasons.append("缩量回踩承接后再启动" if structure == "PULLBACK_RESTART" else "突破后回踩确认再启动")
    elif state == TState.WATCH:
        reasons.append("价格进入观察区域，等待结构与共振确认")
    elif state == TState.NO_TRADE:
        reasons.append("价格过热、动能转弱或 VWAP 无效，禁止交易")
    else:
        reasons.append("确认结构尚未形成")

    return {
        "state": state.value,
        "structure": structure,
        "score": score,
        "conditions": conditions,
        "required_score": required_score,
        "daily_gate": daily_gate,
        "reasons": reasons,
        "diagnostics": {
            "vwap": round(vwap, 4) if vwap is not None else None,
            "change_15m_pct": round(change_15m, 4) if change_15m is not None else None,
            "change_30m_pct": round(change_30m, 4) if change_30m is not None else None,
            "last_5m_volume_ratio_vs_prev20": round(volume_ratio, 4) if volume_ratio is not None else None,
        },
    }
