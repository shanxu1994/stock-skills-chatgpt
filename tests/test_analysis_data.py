import pandas as pd
from fastapi.testclient import TestClient

from app import asgi
from app import analysis_data
from app import services


client = TestClient(asgi.app)


def _daily_frame(close_values):
    rows = []
    for i, close in enumerate(close_values):
        rows.append({
            "trade_date": f"2026-07-{(i % 28) + 1:02d}",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000 + i,
        })
    return pd.DataFrame(rows)


def test_strict_entry_indicator_contract_is_unchanged():
    frame = _daily_frame([100.0] * 60)
    result = services._indicators(frame.copy())
    assert set(["ma5", "ma10", "ma20", "ma60", "macd", "macd_signal", "rsi14", "volume_ratio_5_20", "bias_ma5_pct", "score", "signal"]).issubset(result)
    assert result["ma5"] == 100.0
    assert result["ma10"] == 100.0
    assert result["ma20"] == 100.0


def test_strict_entry_keeps_bias_over_5_no_chase_rule():
    closes = [100.0] * 59 + [130.0]
    result = services._indicators(_daily_frame(closes))
    assert result["bias_ma5_pct"] > 5
    assert result["signal"] == "avoid_chasing"


def test_unified_endpoint_reuses_payload(monkeypatch):
    monkeypatch.setattr(asgi, "unified_analysis_data", lambda symbol: {
        "symbol": "001309.SZ",
        "strategy_contract": {"parameters_changed": False},
        "intraday": {"source": "tencent_public_http"},
        "daily": {"source": "eastmoney_public_http", "indicators": {"ma5": 400.0}},
    })
    response = client.get("/public/analysis-data/001309")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "001309.SZ"
    assert payload["strategy_contract"]["parameters_changed"] is False
    assert payload["intraday"]["source"] == "tencent_public_http"


def test_unified_endpoint_rejects_non_six_digit_symbol():
    response = client.get("/public/analysis-data/ABC")
    assert response.status_code == 422


def test_daily_snapshot_prefers_public_provider(monkeypatch):
    frame = _daily_frame([100.0] * 60)
    monkeypatch.setattr(analysis_data, "_fetch_eastmoney_daily", lambda normalized, days: (frame, "测试股"))
    result = analysis_data.daily_snapshot("001309", 60)
    assert result["source"] == "eastmoney_public_http"
    assert result["name"] == "测试股"
    assert result["indicators"]["ma20"] == 100.0
