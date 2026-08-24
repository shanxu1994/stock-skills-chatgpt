from fastapi.testclient import TestClient

from app.main import app, _fetch_tencent_1m, intraday_snapshot
from app import services
from app.dashboard import build_dashboard_payload, build_strict_signals
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
    assert [item["name"] for item in payload["stocks"]] == ["德明利", "诺德股份"]
    assert all(item["signals"]["t_system"]["buy_zone"] for item in payload["stocks"])
    assert all(item["signals"]["trend_system"]["breakout_confirmation"] for item in payload["stocks"])


def test_strict_signals_do_not_use_fixed_price_levels():
    metrics = {
        "current": 100, "session_high": 102, "session_low": 98, "vwap": 100,
        "change_15m_pct": 0.2, "change_30m_pct": 0.4,
        "last_5m_volume_ratio_vs_prev20": 1.1,
        "higher_lows_last_3_bars": True,
    }
    first = build_strict_signals({"metrics": metrics})
    scaled = {key: value * 2 if key in {"current", "session_high", "session_low", "vwap"} else value for key, value in metrics.items()}
    second = build_strict_signals({"metrics": scaled})
    assert second["t_system"]["buy_zone"][0] == first["t_system"]["buy_zone"][0] * 2
    assert second["trend_system"]["breakout_confirmation"] == first["trend_system"]["breakout_confirmation"] * 2


def test_existing_intraday_bearer_auth_is_unchanged(monkeypatch):
    monkeypatch.setenv("API_SECRET", "secret")
    assert client.post("/v1/stocks/intraday", json={"symbol": "001309"}).status_code == 401
    assert client.get("/dashboard").status_code == 200


def test_public_data_diagnostic_reports_counts(monkeypatch):
    monkeypatch.setattr("app.main.sector_rank", lambda *_: {"source": "akshare", "fallback": True, "items": [{"name": "机器人"}]})
    monkeypatch.setattr("app.main.tushare_query", lambda *_: {"source": "public_http", "count": 1, "cached": False, "items": [{"name": "贵州茅台"}]})
    response = client.get("/diagnostics/public-data")
    assert response.status_code == 200
    assert response.json()["checks"]["concept_sectors"]["count"] == 1
    assert response.json()["checks"]["stock_basic"]["count"] == 1


def test_analyze_validates_empty_symbols():
    response = client.post("/v1/stocks/analyze", json={"symbols": []})
    assert response.status_code == 422


def test_openapi_has_action_operation_ids():
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/v1/stocks/analyze"]["post"]["operationId"] == "analyzeStocks"
    assert schema["paths"]["/v1/stocks/intraday"]["post"]["operationId"] == "analyzeIntraday"
    assert schema["paths"]["/v1/tushare/query"]["post"]["operationId"] == "queryTushare"
    assert "HTTPBearer" in schema["components"]["securitySchemes"]


def _minute_frame():
    pandas = __import__("pandas")
    return pandas.DataFrame([{
        "time": f"2026-08-24 09:{30 + i:02d}", "open": 10 + i / 100,
        "high": 10.02 + i / 100, "low": 9.99 + i / 100,
        "close": 10.01 + i / 100, "volume": 1000 + i, "amount": 100000 + i,
    } for i in range(30)])


def test_tencent_cumulative_turnover_is_converted_to_minute_values(monkeypatch):
    class Response:
        def json(self):
            return {"data": {"sz001309": {
                "data": {"date": "20260824", "data": [
                    "1123 388.72 96974 3850270556.75",
                    "1124 389.00 97116 3855792811.30",
                    "1125 389.80 97200 3859062145.04",
                ]},
                "qt": {"sz001309": ["51", "示例股份"]},
            }}}

    monkeypatch.setattr("app.main._public_get", lambda *_, **__: Response())
    frame, name = _fetch_tencent_1m("001309.SZ", 2)

    assert name == "示例股份"
    assert frame["volume"].tolist() == [142.0, 84.0]
    assert frame["amount"].round(2).tolist() == [5522254.55, 3269333.74]
    assert frame["time"].tolist() == ["2026-08-24 11:24", "2026-08-24 11:25"]


def test_intraday_uses_independent_provider_order(monkeypatch):
    calls = []
    def fail(name):
        def provider(*_):
            calls.append(name)
            raise ConnectionError(f"{name} unavailable")
        return provider
    monkeypatch.setattr("app.main._fetch_tencent_1m", fail("tencent"))
    monkeypatch.setattr("app.main._fetch_sina_1m", fail("sina"))
    monkeypatch.setattr("app.main._fetch_eastmoney_1m", lambda *_: (calls.append("eastmoney") or _minute_frame(), "示例股份"))
    monkeypatch.setattr("app.main._public_stock_name", lambda *_: None, raising=False)

    result = intraday_snapshot("001309", 30)
    assert calls == ["tencent", "sina", "eastmoney"]
    assert result["source"] == "eastmoney_public_http"
    assert result["fallback"] is True
    assert [attempt["ok"] for attempt in result["source_attempts"]] == [False, False, True]
    assert "ConnectionError: tencent unavailable" in result["fallback_reason"]


def test_intraday_all_provider_errors_are_reported(monkeypatch):
    providers = ["tencent", "sina", "eastmoney", "akshare"]
    for attribute, name in zip([
        "_fetch_tencent_1m", "_fetch_sina_1m", "_fetch_eastmoney_1m", "_fetch_akshare_1m",
    ], providers):
        def fail(*_, provider=name):
            raise RuntimeError(f"{provider} failed")
        monkeypatch.setattr(f"app.main.{attribute}", fail)

    try:
        intraday_snapshot("001309", 30)
        assert False, "Expected provider chain to fail"
    except RuntimeError as exc:
        message = str(exc)
        for provider in providers:
            assert provider in message
            assert f"{provider} failed" in message


def test_symbol_normalization_does_not_corrupt_us_tickers():
    assert normalize_symbol("SHOP") == ("us", "SHOP")
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
    monkeypatch.setattr(services, "_tushare_client", lambda: (_ for _ in ()).throw(RuntimeError("permission denied")))
    frame = __import__("pandas").DataFrame([{"code": "600519", "name": "贵州茅台"}])
    monkeypatch.setattr(services, "_akshare", lambda: type("AK", (), {"stock_info_a_code_name": staticmethod(lambda: frame)})())
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
    result = services.tushare_query("stock_basic", {"ts_code": "600519.SH"}, None, 5)
    assert result["count"] == 1
    assert result["items"][0]["name"] == "贵州茅台"


def test_query_cache_returns_cached_result(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "configured")
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
