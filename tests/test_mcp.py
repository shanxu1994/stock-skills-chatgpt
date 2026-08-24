from app import mcp_server


def test_mcp_public_path_is_mount_root():
    assert mcp_server.mcp.settings.streamable_http_path == "/"


def test_analyze_intraday_reuses_existing_snapshot(monkeypatch):
    expected = {"symbol": "001309.SZ", "source": "tencent", "metrics": {"current": 400.0}}

    def fake_snapshot(symbol, bars):
        assert symbol == "001309"
        assert bars == 240
        return expected

    monkeypatch.setattr(mcp_server, "intraday_snapshot", fake_snapshot)
    assert mcp_server.analyze_intraday("001309", 240) == expected


def test_analyze_intraday_rejects_invalid_bar_count():
    try:
        mcp_server.analyze_intraday("001309", 10)
    except ValueError as exc:
        assert "between 30 and 600" in str(exc)
    else:
        raise AssertionError("invalid bars should fail")
