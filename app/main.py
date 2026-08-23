from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .auth import require_api_key
from .models import LhbRequest, MarketRequest, StockAnalyzeRequest, TushareQueryRequest
from . import services as stock_services
from .services import analyze_stocks, lhb_rank, sector_rank, tushare_query
from datetime import date, datetime, timedelta

import httpx
import pandas as pd


class HealthResponse(BaseModel):
    status: str


class IntradayRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    bars: int = Field(default=240, ge=30, le=600)


app = FastAPI(
    title="China & Global Stock Research Skills API",
    description="Cloud API for stock analysis, Tushare research, A-share sectors and Dragon Tiger List. Research only; not investment advice.",
    version="1.1.0",
    servers=[{"url": "https://stock-skills-chatgpt-p4vq.onrender.com"}],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chatgpt.com", "https://chat.openai.com"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health", operation_id="healthCheck", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/diagnostics/public-data", operation_id="diagnosePublicData", dependencies=[Depends(require_api_key)])
def diagnose_public_data():
    """Temporary deployment diagnostic; reports counts/sources, never tokens or raw credentials."""
    result = {"trade_date": date.today().strftime("%Y%m%d"), "checks": {}}
    try:
        sectors = sector_rank(result["trade_date"], 5)
        result["checks"]["concept_sectors"] = {
            "source": sectors.get("source"), "count": len(sectors.get("items", [])),
            "fallback": sectors.get("fallback"), "error": sectors.get("note"),
        }
    except Exception as exc:
        result["checks"]["concept_sectors"] = {"source": None, "count": 0, "error": str(exc)}
    try:
        basics = tushare_query("stock_basic", {"ts_code": "600519.SH"}, ["symbol", "name"], 1)
        result["checks"]["stock_basic"] = {
            "source": basics.get("source"), "count": basics.get("count", 0),
            "cached": basics.get("cached", False), "error": basics.get("note"),
        }
    except Exception as exc:
        result["checks"]["stock_basic"] = {"source": None, "count": 0, "error": str(exc)}
    return result


def call(service, *args):
    try:
        return service(*args)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream data request failed: {exc}") from exc


def analyze_stocks_without_basic_limit(symbols: list[str], days: int, include_news: bool):
    """Analyze A-shares without calling Tushare stock_basic."""
    results = []
    passthrough = []

    for requested in symbols:
        market, normalized = stock_services.normalize_symbol(requested)
        if market != "a":
            passthrough.append(requested)
            continue

        try:
            pro = stock_services._tushare_client()
            end = date.today()
            start = end - timedelta(days=max(days * 2, 120))
            frame = pro.daily(
                ts_code=normalized,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if frame is None or frame.empty:
                raise RuntimeError("No market data returned")

            frame = frame.sort_values("trade_date").tail(days).rename(columns={"vol": "volume"})
            frame = frame[["trade_date", "open", "high", "low", "close", "volume"]]

            name = None
            try:
                name_df = stock_services._public_stock_name(normalized)
                if name_df is not None and not name_df.empty:
                    name = str(name_df.iloc[0]["name"])
            except Exception:
                pass

            results.append({
                "requested_symbol": requested,
                "symbol": normalized,
                "market": market,
                "name": name,
                "as_of": str(frame.iloc[-1]["trade_date"]),
                "indicators": stock_services._indicators(frame),
                "news": stock_services._news(name or normalized) if include_news else [],
                "data_points": len(frame),
                "error": None,
            })
        except Exception as exc:
            results.append({
                "requested_symbol": requested,
                "symbol": normalized,
                "market": market,
                "error": str(exc),
            })

    if passthrough:
        other = analyze_stocks(passthrough, days, include_news)
        results.extend(other.get("results", []))

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "results": results,
        "disclaimer": "Market research only; not investment advice.",
    }


def _eastmoney_secid(normalized: str) -> str:
    code = normalized.split(".")[0]
    return f"1.{code}" if normalized.endswith(".SH") else f"0.{code}"


def _fetch_eastmoney_1m(normalized: str, bars: int) -> tuple[pd.DataFrame, str | None]:
    """Fetch minute bars directly from Eastmoney's public HTTP endpoint."""
    secid = _eastmoney_secid(normalized)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "klt": 1,
        "fqt": 1,
        "lmt": bars,
        "end": "20500101",
        "iscca": 1,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    response = httpx.get(url, params=params, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json().get("data") or {}
    rows = payload.get("klines") or []
    if not rows:
        raise RuntimeError("Eastmoney returned no minute bars")

    parsed = []
    for row in rows:
        parts = row.split(",")
        if len(parts) < 7:
            continue
        parsed.append({
            "time": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
        })
    frame = pd.DataFrame(parsed)
    if frame.empty:
        raise RuntimeError("Eastmoney minute data could not be parsed")
    return frame, payload.get("name")


def _fetch_akshare_1m(normalized: str, bars: int) -> tuple[pd.DataFrame, str | None]:
    """Fallback minute bars through AkShare; no Tushare dependency."""
    ak = stock_services._akshare()
    code = normalized.split(".")[0]
    frame = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="")
    if frame is None or frame.empty:
        raise RuntimeError("AkShare returned no minute bars")
    rename = {
        "时间": "time", "开盘": "open", "收盘": "close", "最高": "high",
        "最低": "low", "成交量": "volume", "成交额": "amount",
    }
    frame = frame.rename(columns={k: v for k, v in rename.items() if k in frame.columns})
    required = ["time", "open", "close", "high", "low", "volume", "amount"]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise RuntimeError(f"AkShare minute data missing columns: {missing}")
    return frame[required].tail(bars).copy(), None


def _intraday_metrics(frame: pd.DataFrame) -> dict:
    frame = frame.copy()
    for col in ["open", "close", "high", "low", "volume", "amount"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["close", "high", "low", "volume"])
    if frame.empty:
        raise RuntimeError("No valid minute bars")

    last = frame.iloc[-1]
    current = float(last["close"])
    session_high = float(frame["high"].max())
    session_low = float(frame["low"].min())

    total_volume = float(frame["volume"].sum())
    total_amount = float(frame["amount"].sum()) if "amount" in frame else 0.0
    # Eastmoney A-share volume is normally in hands (100 shares). If the implied
    # price is implausible, fall back to a share-based denominator.
    vwap = None
    if total_volume > 0 and total_amount > 0:
        vwap_hands = total_amount / (total_volume * 100.0)
        vwap_shares = total_amount / total_volume
        if current > 0 and 0.25 * current <= vwap_hands <= 4 * current:
            vwap = vwap_hands
        elif current > 0 and 0.25 * current <= vwap_shares <= 4 * current:
            vwap = vwap_shares

    def pct_change(minutes: int):
        if len(frame) <= minutes:
            return None
        base = float(frame.iloc[-minutes - 1]["close"])
        return round((current / base - 1) * 100, 4) if base else None

    recent5 = frame.tail(5)["volume"].mean() if len(frame) >= 5 else None
    prev20 = frame.iloc[-25:-5]["volume"].mean() if len(frame) >= 25 else None
    volume_ratio = None
    if recent5 is not None and prev20 is not None and prev20 > 0:
        volume_ratio = round(float(recent5 / prev20), 4)

    higher_lows = False
    if len(frame) >= 3:
        lows = frame.tail(3)["low"].astype(float).tolist()
        higher_lows = lows[0] < lows[1] < lows[2]

    recovery_pct = None
    if session_low > 0:
        recovery_pct = round((current / session_low - 1) * 100, 4)

    return {
        "current": round(current, 4),
        "session_high": round(session_high, 4),
        "session_low": round(session_low, 4),
        "vwap": round(vwap, 4) if vwap is not None else None,
        "above_vwap": (current >= vwap) if vwap is not None else None,
        "change_15m_pct": pct_change(15),
        "change_30m_pct": pct_change(30),
        "last_5m_volume_ratio_vs_prev20": volume_ratio,
        "higher_lows_last_3_bars": higher_lows,
        "recovery_from_session_low_pct": recovery_pct,
    }


def _resample_5m(frame: pd.DataFrame) -> list[dict]:
    work = frame.copy()
    work["time"] = pd.to_datetime(work["time"])
    work = work.set_index("time")
    agg = work.resample("5min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "amount": "sum",
    }).dropna(subset=["open", "close"])
    out = []
    for idx, row in agg.tail(48).iterrows():
        out.append({
            "time": idx.strftime("%Y-%m-%d %H:%M"),
            "open": round(float(row["open"]), 4),
            "high": round(float(row["high"]), 4),
            "low": round(float(row["low"]), 4),
            "close": round(float(row["close"]), 4),
            "volume": round(float(row["volume"]), 4),
            "amount": round(float(row["amount"]), 2),
        })
    return out


def intraday_snapshot(symbol: str, bars: int):
    market, normalized = stock_services.normalize_symbol(symbol)
    if market != "a":
        raise RuntimeError("Intraday public minute endpoint currently supports A-shares only")

    source = "eastmoney_public_http"
    fallback = False
    fallback_reason = None
    try:
        frame, name = _fetch_eastmoney_1m(normalized, bars)
    except Exception as first_exc:
        source = "akshare_public"
        fallback = True
        fallback_reason = str(first_exc)
        frame, name = _fetch_akshare_1m(normalized, bars)

    if not name:
        try:
            name_df = stock_services._public_stock_name(normalized)
            if name_df is not None and not name_df.empty:
                name = str(name_df.iloc[0]["name"])
        except Exception:
            name = None

    metrics = _intraday_metrics(frame)
    one_min = []
    for _, row in frame.tail(60).iterrows():
        one_min.append({
            "time": str(row["time"]),
            "open": round(float(row["open"]), 4),
            "high": round(float(row["high"]), 4),
            "low": round(float(row["low"]), 4),
            "close": round(float(row["close"]), 4),
            "volume": round(float(row["volume"]), 4),
            "amount": round(float(row["amount"]), 2),
        })

    as_of = str(frame.iloc[-1]["time"])
    return {
        "symbol": normalized,
        "name": name,
        "as_of": as_of,
        "source": source,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "metrics": metrics,
        "one_minute_bars": one_min,
        "five_minute_bars": _resample_5m(frame),
        "bars_received": len(frame),
        "error": None,
        "disclaimer": "Market research only; not investment advice.",
    }


@app.post("/v1/stocks/analyze", operation_id="analyzeStocks", dependencies=[Depends(require_api_key)])
def stocks_analyze(request: StockAnalyzeRequest):
    return call(analyze_stocks_without_basic_limit, request.symbols, request.days, request.include_news)


@app.post("/v1/stocks/intraday", operation_id="analyzeIntraday", dependencies=[Depends(require_api_key)])
def stocks_intraday(request: IntradayRequest):
    return call(intraday_snapshot, request.symbol, request.bars)


@app.post("/v1/market/sectors", operation_id="rankConceptSectors", dependencies=[Depends(require_api_key)])
def market_sectors(request: MarketRequest):
    return call(sector_rank, request.trade_date, request.top)


@app.post("/v1/market/dragon-tiger-list", operation_id="rankDragonTigerList", dependencies=[Depends(require_api_key)])
def market_lhb(request: LhbRequest):
    return call(lhb_rank, request.trade_date, request.top, request.ts_code)


@app.post("/v1/tushare/query", operation_id="queryTushare", dependencies=[Depends(require_api_key)])
def query_tushare(request: TushareQueryRequest):
    return call(tushare_query, request.api_name, request.params, request.fields, request.limit)
