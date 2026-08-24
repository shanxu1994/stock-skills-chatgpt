from fastapi.testclient import TestClient

from app import asgi


client = TestClient(asgi.app)


def test_public_intraday_get_reuses_snapshot_without_auth(monkeypatch):
    expected = {
        "symbol": "001309.SZ",
        "name": "德明利",
        "source": "tencent_public_http",
        "metrics": {"current": 400.0, "vwap": 398.0},
        "one_minute_bars": [{"time": "2026-08-24 14:59", "close": 400.0}],
    }

    def fake_snapshot(symbol, bars):
        assert symbol == "001309"
        assert bars == 240
        return expected

    monkeypatch.setattr(asgi, "intraday_snapshot", fake_snapshot)
    response = client.get("/public/intraday", params={"symbol": "001309", "bars": 240})
    assert response.status_code == 200
    assert response.json() == expected


def test_public_intraday_validates_bar_limits():
    response = client.get("/public/intraday", params={"symbol": "001309", "bars": 10})
    assert response.status_code == 422


def test_public_intraday_requires_symbol():
    response = client.get("/public/intraday")
    assert response.status_code == 422
