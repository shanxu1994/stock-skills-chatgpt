from fastapi.testclient import TestClient
from app import asgi

client = TestClient(asgi.app)


def test_public_analysis_html_is_server_rendered(monkeypatch):
    payload = {
        "symbol":"001309.SZ","name":"德明利",
        "strategy_contract":{"parameters_changed":False},
        "intraday":{"metrics":{"current":400.0,"vwap":398.5,"change_15m_pct":0.5,"change_30m_pct":1.0},"one_minute_bars":[{"time":"10:00","open":399,"high":401,"low":398,"close":400,"volume":1000}]},
        "daily":{"indicators":{"ma5":395,"ma10":390,"ma20":380,"macd":2.1,"macd_signal":1.8,"rsi14":65,"bias_ma5_pct":1.27,"volume_ratio_5_20":1.1,"signal":"HOLD","score":72},"recent_daily_bars":[{"trade_date":"2026-08-25","open":390,"high":405,"low":388,"close":400,"volume":100000}]},
        "meta":{"intraday_source":"tencent_public_http","intraday_as_of":"2026-08-25 10:00","daily_source":"eastmoney_public_http","daily_as_of":"2026-08-25"},
    }
    monkeypatch.setattr(asgi,"unified_analysis_data",lambda symbol:payload)
    response=client.get("/public/analysis/001309")
    assert response.status_code==200
    assert "德明利" in response.text
    assert "VWAP" in response.text
    assert "MA5" in response.text
    assert "MACD" in response.text
    assert "RSI14" in response.text
    assert "MA5乖离率" in response.text
    assert "tencent_public_http" in response.text
    assert "eastmoney_public_http" in response.text
    assert "<script" not in response.text.lower()
    assert response.headers["cache-control"]=="no-store, max-age=0"


def test_public_analysis_html_rejects_bad_symbol():
    response=client.get("/public/analysis/ABC")
    assert response.status_code==422
