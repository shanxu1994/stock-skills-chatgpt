from fastapi.testclient import TestClient

from app.main import app
from app import services
from app.services import normalize_symbol


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_validates_empty_symbols():
    response = client.post("/v1/stocks/analyze", json={"symbols": []})
    assert response.status_code == 422


def test_openapi_has_action_operation_ids():
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/v1/stocks/analyze"]["post"]["operationId"] == "analyzeStocks"
    assert schema["paths"]["/v1/tushare/query"]["post"]["operationId"] == "queryTushare"
    assert "HTTPBearer" in schema["components"]["securitySchemes"]


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
