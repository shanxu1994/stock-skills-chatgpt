from fastapi.testclient import TestClient

from app import asgi


client = TestClient(asgi.app)


def _snapshot(symbol: str):
    return {
        "symbol": f"{symbol}.SZ",
        "name": "德明利" if symbol == "001309" else symbol,
        "source": "tencent_public_http",
        "as_of": "2026-08-25 10:00",
        "metrics": {"current": 400.0, "vwap": 398.0},
        "one_minute_bars": [{"time": "2026-08-25 09:59", "open": 399.0, "high": 400.0, "low": 398.5, "close": 400.0, "volume": 1000}],
    }


def test_fixed_public_intraday_json_path(monkeypatch):
    monkeypatch.setattr(asgi, "intraday_snapshot", lambda symbol, bars: _snapshot(symbol))
    response = client.get("/public/intraday/001309")
    assert response.status_code == 200
    assert response.json()["symbol"] == "001309.SZ"
    assert response.json()["source"] == "tencent_public_http"


def test_fixed_public_intraday_html_path(monkeypatch):
    monkeypatch.setattr(asgi, "intraday_snapshot", lambda symbol, bars: _snapshot(symbol))
    response = client.get("/public/intraday/001309/view")
    assert response.status_code == 200
    assert "德明利" in response.text
    assert "VWAP" in response.text
    assert "tencent_public_http" in response.text
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_fixed_public_intraday_rejects_bad_symbol():
    response = client.get("/public/intraday/ABC")
    assert response.status_code == 422
