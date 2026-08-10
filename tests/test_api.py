from fastapi.testclient import TestClient

from app.main import app
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
