from fastapi.testclient import TestClient
from app import asgi

client = TestClient(asgi.app)


def test_analysis_hub_accepts_any_six_digit_a_share_code():
    response = client.get("/public/analysis")
    assert response.status_code == 200
    assert 'action="/public/analysis/open"' in response.text
    assert 'name="symbol"' in response.text
    assert 'pattern="[0-9]{6}"' in response.text
    assert "300750" in response.text
    assert "001309" in response.text
    assert "600110" in response.text
    assert "<script" not in response.text.lower()


def test_analysis_open_redirects_generic_symbol():
    response = client.get("/public/analysis/open?symbol=300750", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/public/analysis/300750"


def test_analysis_open_rejects_invalid_symbol():
    response = client.get("/public/analysis/open?symbol=ABC123", follow_redirects=False)
    assert response.status_code == 422
