from __future__ import annotations

from math import prod
from typing import Any, Iterable

import pandas as pd

from .t_strategy import StrategyConfig, TState, evaluate_daily_trend, evaluate_t_state


def _summarize(trades: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [trade["return_pct"] for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    average_return = sum(returns) / len(returns) if returns else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    profit_loss_ratio = (
        (sum(wins) / len(wins)) / abs(average_loss) if wins and losses else None
    )
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return {
        "trigger_count": sum(
            event["state"] == TState.CONFIRMED.value
            and (i == 0 or events[i - 1]["state"] != TState.CONFIRMED.value)
            for i, event in enumerate(events)
        ),
        "trade_count": len(trades),
        "win_rate": len(wins) / len(returns) if returns else 0.0,
        "average_return": average_return,
        "average_loss": average_loss,
        "profit_loss_ratio": profit_loss_ratio,
        "max_drawdown": max_drawdown,
        "total_return": prod(1 + value for value in returns) - 1 if returns else 0.0,
        "trades": trades,
        "events": events,
    }


def replay_signals(
    rows: Iterable[dict[str, Any]],
    *,
    holding_bars: int = 10,
    stop_loss_pct: float = 0.01,
    take_profit_pct: float = 0.02,
    config: StrategyConfig | None = None,
    daily_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay minute bars without look-ahead and summarize completed trades."""
    bars = list(rows)
    events: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None

    for index, bar in enumerate(bars):
        signal = evaluate_t_state(bars[: index + 1], config, daily_gate=daily_gate)
        events.append({"index": index, "state": signal["state"], "structure": signal["structure"]})

        if position is not None:
            entry = position["entry_price"]
            return_pct = float(bar["close"]) / entry - 1
            held = index - position["entry_index"]
            if return_pct <= -stop_loss_pct or return_pct >= take_profit_pct or held >= holding_bars:
                trades.append({**position, "exit_index": index, "exit_price": float(bar["close"]), "return_pct": return_pct})
                position = None

        previous_state = events[-2]["state"] if len(events) > 1 else None
        if position is None and signal["state"] == TState.CONFIRMED.value and previous_state != TState.CONFIRMED.value:
            # Enter at the confirming bar close: no later bar participates in the signal.
            position = {
                "entry_index": index,
                "entry_price": float(bar["close"]),
                "structure": signal["structure"],
            }

    if position is not None and len(bars) - 1 > position["entry_index"]:
        last = bars[-1]
        trades.append({
            **position, "exit_index": len(bars) - 1, "exit_price": float(last["close"]),
            "return_pct": float(last["close"]) / position["entry_price"] - 1,
        })

    return _summarize(trades, events)


def replay_market_days(
    minute_rows: Iterable[dict[str, Any]],
    daily_rows: Iterable[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Replay each session with a gate built only from prior completed daily bars."""
    minute = pd.DataFrame(list(minute_rows))
    if minute.empty or "time" not in minute:
        return _summarize([], [])
    minute["_session"] = pd.to_datetime(minute["time"], errors="coerce").dt.strftime("%Y-%m-%d")
    all_events: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    offset = 0
    daily = list(daily_rows)
    for session_date, group in minute.dropna(subset=["_session"]).groupby("_session", sort=True):
        bars = group.drop(columns=["_session"]).to_dict("records")
        gate = evaluate_daily_trend(daily, before_date=session_date)
        result = replay_signals(bars, daily_gate=gate, **kwargs)
        for event in result["events"]:
            all_events.append({**event, "index": event["index"] + offset, "session": session_date})
        for trade in result["trades"]:
            all_trades.append({
                **trade,
                "entry_index": trade["entry_index"] + offset,
                "exit_index": trade["exit_index"] + offset,
                "session": session_date,
            })
        sessions.append({
            "session": session_date, "daily_gate": gate,
            "trigger_count": result["trigger_count"], "trade_count": result["trade_count"],
        })
        offset += len(bars)
    summary = _summarize(all_trades, all_events)
    summary["sessions"] = sessions
    return summary
