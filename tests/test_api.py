from fastapi.testclient import TestClient

from app.main import app, _fetch_tencent_1m, intraday_snapshot
from app import services
from app.dashboard import build_dashboard_payload, build_strict_signals, dashboard_symbols
from app.services import normalize_symbol


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_page_is_mobile_ready():
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert 'name="viewport"' in response.text


def test_dashboard_payload_contains_fixed_stocks_and_signals():
    def loader(symbol, bars):
        assert bars == 240
        return {
            "symbol": symbol, "name": None, "as_of": "2026-08-24 10:00",
            "metrics": {
                "current": 10.10, "session_high": 10.30, "session_low": 9.90,
                "vwap": 10.05, "change_15m_pct": 0.3, "change_30m_pct": 0.5,
                "last_5m_volume_ratio_vs_prev20": 1.2,
                "higher_lows_last_3_bars": True,
                "recovery_from_session_low_pct": 2.02,
            },
        }
    payload = build_dashboard_payload(loader)
    assert [item["name"] for item in payload["stocks"]] == ["德明利", "诺德股份", "翰宇药业"]
    assert all(item["signals"]["t_system"]["buy_zone"] for item in payload["stocks"])
    assert all(item["signals"]["trend_system"]["breakout_confirmation"] for item in payload["stocks"])


def test_dashboard_symbols_default_and_custom():
    assert dashboard_symbols(None) == ["001309", "600110", "300199"]
    assert dashboard_symbols("001309,600110") == ["001309", "600110"]


def test_strict_signals_contains_expected_structure():
    snapshot = {
        "symbol": "001309.SZ",
        "metrics": {
            "current": 10.0, "session_high": 10.5, "session_low": 9.5,
            "vwap": 9.9, "above_vwap": True, "change_15m_pct": 0.2,
            "change_30m_pct": 0.4, "last_5m_volume_ratio_vs_prev20": 1.1,
            "higher_lows_last_3_bars": True, "recovery_from_session_low_pct": 5.26,
        },
    }
    signals = build_strict_signals(snapshot)
    assert "t_system" in signals
    assert "trend_system" in signals


def test_tencent_parser_converts_cumulative_volume_and_amount(monkeypatch):
    class Response:
        def json(self):
            return {
                "data": {
                    "sz001309": {
                        "data": {
                            "date": "20260824",
                            "data": [
                                "0930 10.00 100 100000",
                                "0931 10.10 150 150500",
                                "0932 10.20 220 221900",
                            ],
                        },
                        "qt": {"sz001309": [None, "德明利"]},
                    }
                }
            }

    monkeypatch.setattr("app.main._public_get", lambda *args, **kwargs: Response())
    frame, name = _fetch_tencent_1m("001309.SZ", 240)
    assert name == "德明利"
    assert frame["volume"].tolist() == [100.0, 50.0, 70.0]
    assert frame["amount"].tolist() == [100000.0, 50500.0, 71400.0]


def test_intraday_snapshot_uses_tencent_first(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame([
        {"time": "2026-08-24 09:30", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100, "amount": 100000},
        {"time": "2026-08-24 09:31", "open": 10, "high": 10.1, "low": 10, "close": 10.1, "volume": 100, "amount": 101000},
    ])
    monkeypatch.setattr("app.main._fetch_tencent_1m", lambda normalized, bars: (frame, "德明利"))
    result = intraday_snapshot("001309", 240)
    assert result["source"] == "tencent_public_http"
    assert result["fallback"] is False


def test_intraday_snapshot_falls_back_when_tencent_fails(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame([
        {"time": "2026-08-24 09:30", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100, "amount": 100000},
        {"time": "2026-08-24 09:31", "open": 10, "high": 10.1, "low": 10, "close": 10.1, "volume": 100, "amount": 101000},
    ])
    monkeypatch.setattr("app.main._fetch_tencent_1m", lambda *args: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr("app.main._fetch_sina_1m", lambda normalized, bars: (frame, None))
    result = intraday_snapshot("001309", 240)
    assert result["source"] == "sina_public_http"
    assert result["fallback"] is True


def test_health_route_with_auth_env_does_not_require_key(monkeypatch):
    monkeypatch.setenv("API_SECRET", "secret")
    response = client.get("/health")
    assert response.status_code == 200


def test_intraday_route_requires_bearer_when_secret_configured(monkeypatch):
    monkeypatch.setenv("API_SECRET", "secret")
    response = client.post("/v1/stocks/intraday", json={"symbol": "001309"})
    assert response.status_code == 401


def test_normalize_symbol_formats():
    assert normalize_symbol("001309") == ("a", "001309.SZ")
    assert normalize_symbol("600519") == ("a", "600519.SH")
    assert normalize_symbol("SH600519") == ("a", "600519.SH")
    assert normalize_symbol("HK00700") == ("hk", "0700.HK")


def test_sector_falls_back_without_tushare_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    frame = __import__("pandas").DataFrame([{"板块代码": "BK1", "板块名称": "机器人", "涨跌幅": 3.2}])
    monkeypatch.setattr(services, "_akshare", lambda: type("AK", (), {"stock_board_concept_name_em": staticmethod(lambda: frame)})())
    result = services.sector_rank("20260812", 10)
    assert result["source"] == "akshare"
    assert result["fallback"] is True
    assert result["items"][0]["name"] == "机器人"


def test_query_falls_back_when_tushare_permission_fails(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "configured")
    monkeypatch.setattr(services, "_public_stock_name", lambda _: __import__("pandas").DataFrame())
    monkeypatch.setattr(services, "_tushare_client", lambda: (_ for _ in ()).throw(RuntimeError("permission denied")))
    frame = __import__("pandas").DataFrame([{"code": "600519", "name": "贵州茅台"}])
    monkeypatch.setattr(services, "_akshare", lambda: type("AK", (), {"stock_info_a_code_name": staticmethod(lambda: frame)})())
    services._QUERY_CACHE.clear()
    result = services.tushare_query("stock_basic", {}, None, 10)
    assert result["source"] == "akshare"
    assert result["count"] == 1
    assert "permission denied" in result["fallback_reason"]


def test_unsupported_fallback_is_structured(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(services, "_akshare", lambda: object())
    result = services.tushare_query("income", {}, None, 10)
    assert result["items"] == []
    assert result["fallback"] is True
    assert "does not currently support" in result["note"]


def test_lhb_falls_back_without_tushare_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    frame = __import__("pandas").DataFrame([{
        "代码": "600519", "名称": "贵州茅台", "涨跌幅": 2.1,
        "龙虎榜净买额": 1200000, "龙虎榜净买额占总成交额比": 3.4,
    }])
    monkeypatch.setattr(services, "_akshare", lambda: type("AK", (), {
        "stock_lhb_detail_em": staticmethod(lambda **_: frame),
    })())
    result = services.lhb_rank("20260812", 5, None)
    assert result["source"] == "akshare"
    assert result["fallback"] is True
    assert result["items"][0]["name"] == "贵州茅台"


def test_query_concept_index_fallback_returns_items(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    frame = __import__("pandas").DataFrame([{"板块代码": "BK1", "板块名称": "机器人", "涨跌幅": 3.2}])
    monkeypatch.setattr(services, "_akshare", lambda: type("AK", (), {
        "stock_board_concept_name_em": staticmethod(lambda: frame),
    })())
    result = services.tushare_query("ths_index", {}, None, 5)
    assert result["source"] == "akshare"
    assert result["count"] == 1
    assert result["items"][0]["name"] == "机器人"


def test_query_stock_basic_uses_public_name_fallback(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(services, "_public_stock_name", lambda _: __import__("pandas").DataFrame([{"symbol": "600519", "name": "贵州茅台"}]))
    monkeypatch.setattr(services, "_akshare", lambda: object())
    services._QUERY_CACHE.clear()
    result = services.tushare_query("stock_basic", {"ts_code": "600519.SH"}, None, 5)
    assert result["count"] == 1
    assert result["items"][0]["name"] == "贵州茅台"


def test_query_cache_returns_cached_result(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "configured")
    monkeypatch.setattr(services, "_public_stock_name", lambda _: __import__("pandas").DataFrame())
    calls = {"count": 0}
    class Pro:
        def stock_basic(self, **_):
            calls["count"] += 1
            return __import__("pandas").DataFrame([{"ts_code": "600519.SH", "name": "贵州茅台"}])
    monkeypatch.setattr(services, "_tushare_client", lambda: Pro())
    services._QUERY_CACHE.clear()
    first = services.tushare_query("stock_basic", {"ts_code": "600519.SH"}, None, 5)
    second = services.tushare_query("stock_basic", {"ts_code": "600519.SH"}, None, 5)
    assert first["cached"] is False
    assert second["cached"] is True
    assert calls["count"] == 1
