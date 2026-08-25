from __future__ import annotations

from math import prod
from typing import Any, Iterable

from .t_strategy import StrategyConfig, TState, evaluate_t_state


def replay_signals(
    rows: Iterable[dict[str, Any]],
    *,
    holding_bars: int = 10,
    stop_loss_pct: float = 0.01,
    take_profit_pct: float = 0.02,
    config: StrategyConfig | None = None,
) -> dict[str, Any]:
    """Replay minute bars without look-ahead and summarize completed trades."""
    bars = list(rows)
    events: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None

    for index, bar in enumerate(bars):
        signal = evaluate_t_state(bars[: index + 1], config)
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
        "trigger_count": sum(event["state"] == TState.CONFIRMED.value and (i == 0 or events[i - 1]["state"] != TState.CONFIRMED.value) for i, event in enumerate(events)),
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
