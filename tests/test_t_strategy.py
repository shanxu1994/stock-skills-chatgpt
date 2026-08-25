from app.backtest import replay_signals
from app.dashboard import build_strict_signals
from app.t_strategy import TState, evaluate_t_state


def bar(index, close, volume=1000, low=None, high=None):
    low = close - 0.01 if low is None else low
    high = close + 0.01 if high is None else high
    return {
        "time": f"2026-08-24 10:{index:02d}",
        "open": close, "high": high, "low": low, "close": close,
        "volume": volume, "amount": close * volume,
    }


def pullback_restart_bars():
    rows = [bar(i, 10 + i * 0.001) for i in range(32)]
    rows += [bar(i, value) for i, value in enumerate(
        [10.08, 10.12, 10.18, 10.23, 10.28, 10.32, 10.35, 10.34, 10.33, 10.32, 10.31, 10.30], start=32
    )]
    rows += [
        bar(44, 10.16, 500, 10.14), bar(45, 10.13, 500, 10.11),
        bar(46, 10.14, 500, 10.12), bar(47, 10.15, 500, 10.13),
        bar(48, 10.16, 500, 10.14), bar(49, 10.23, 1200, 10.20),
    ]
    return rows


def breakout_retest_bars():
    rows = [bar(i, 9.92 + (i % 5) * 0.01, 850) for i in range(41)]
    rows += [
        bar(41, 9.98, 900, 9.97, 10.00),
        bar(42, 10.06, 1800, 10.01, 10.08),
        bar(43, 10.03, 1000, 10.00, 10.06),
        bar(44, 10.02, 900, 9.99, 10.04),
        bar(45, 10.03, 900, 10.00, 10.05),
        bar(46, 10.04, 950, 10.01, 10.06),
        bar(47, 10.05, 1000, 10.02, 10.07),
        bar(48, 10.06, 1050, 10.03, 10.08),
        bar(49, 10.12, 1800, 10.08, 10.13),
    ]
    return rows


def test_price_zone_is_watch_not_direct_buy():
    rows = [bar(i, 10 + i * 0.0002) for i in range(40)]
    result = evaluate_t_state(rows)
    assert result["state"] == TState.WATCH.value
    assert result["structure"] is None


def test_pullback_support_then_restart_is_confirmed():
    result = evaluate_t_state(pullback_restart_bars())
    assert result["state"] == TState.CONFIRMED.value
    assert result["structure"] == "PULLBACK_RESTART"
    assert result["score"] >= 5


def test_demingli_surge_then_fade_is_not_tradeable():
    rows = [bar(i, 10.0, 800) for i in range(34)]
    rows += [bar(i, value, 1800 if i < 38 else 900) for i, value in enumerate(
        [10.15, 10.35, 10.60, 10.85, 10.72, 10.58, 10.45, 10.34], start=34
    )]
    result = evaluate_t_state(rows)
    assert result["state"] == TState.NO_TRADE.value
    assert result["state"] != TState.CONFIRMED.value


def test_nord_afternoon_volume_breakout_retest_restart():
    result = evaluate_t_state(breakout_retest_bars())
    assert result["state"] == TState.CONFIRMED.value
    assert result["structure"] == "BREAKOUT_RETEST_RESTART"
    assert result["conditions"]["volume_resonance"] is True


def test_dashboard_keeps_shape_and_exposes_state_machine():
    rows = pullback_restart_bars()
    snapshot = {
        "metrics": {
            "current": rows[-1]["close"], "session_high": 10.35, "session_low": 10.0,
            "vwap": 10.12, "change_15m_pct": 0.5, "change_30m_pct": 1.0,
            "last_5m_volume_ratio_vs_prev20": 1.0, "higher_lows_last_3_bars": True,
        },
        "one_minute_bars": rows,
    }
    signals = build_strict_signals(snapshot)
    assert signals["t_system"]["status"] == "CONFIRMED"
    assert signals["t_system"]["buy_zone"]
    assert signals["trend_system"]["breakout_confirmation"]


def test_replay_statistics_and_no_future_leakage():
    history = breakout_retest_bars()
    base = replay_signals(history, holding_bars=4)
    extended = replay_signals(history + [bar(50 + i, 8.0, 5000) for i in range(4)], holding_bars=4)
    assert base["events"] == extended["events"][:len(history)]
    assert base["trigger_count"] >= 1
    assert {"win_rate", "average_return", "average_loss", "profit_loss_ratio", "max_drawdown"} <= base.keys()
