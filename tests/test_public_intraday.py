from fastapi.testclient import TestClient

from app import asgi


client = TestClient(asgi.app)


def _expected_snapshot():
    return {
        "symbol": "001309.SZ",
        "name": "德明利",
        "as_of": "2026-08-24 14:59",
        "source": "tencent_public_http",
        "metrics": {
            "current": 400.0,
            "vwap": 398.0,
            "session_high": 405.0,
            "session_low": 386.16,
            "change_15m_pct": 0.5,
            "change_30m_pct": 1.2,
            "last_5m_volume_ratio_vs_prev20": 1.1,
            "higher_lows_last_3_bars": True,
        },
        "one_minute_bars": [
            {"time": "2026-08-24 14:59", "open": 399.0, "high": 400.2, "low": 398.8, "close": 400.0, "volume": 1234}
        ],
    }


def test_public_intraday_get_reuses_snapshot_without_auth(monkeypatch):
    expected = _expected_snapshot()

    def fake_snapshot(symbol, bars):
        assert symbol == "001309"
        assert bars == 240
        return expected

    monkeypatch.setattr(asgi, "intraday_snapshot", fake_snapshot)
    response = client.get("/public/intraday", params={"symbol": "001309", "bars": 240})
    assert response.status_code == 200
    assert response.json() == expected


def test_public_intraday_view_is_human_readable_and_uncached(monkeypatch):
    expected = _expected_snapshot()
    monkeypatch.setattr(asgi, "intraday_snapshot", lambda symbol, bars: expected)
    response = client.get("/public/intraday/view", params={"symbol": "001309", "bars": 240})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "德明利" in response.text
    assert "001309.SZ" in response.text
    assert "tencent_public_http" in response.text
    assert "VWAP" in response.text
    assert "15分钟变化" in response.text
    assert "2026-08-24 14:59" in response.text
    assert "400.0" in response.text


def test_public_intraday_validates_bar_limits():
    response = client.get("/public/intraday", params={"symbol": "001309", "bars": 10})
    assert response.status_code == 422
    response = client.get("/public/intraday/view", params={"symbol": "001309", "bars": 601})
    assert response.status_code == 422


def test_public_intraday_requires_symbol():
    assert client.get("/public/intraday").status_code == 422
    assert client.get("/public/intraday/view").status_code == 422
