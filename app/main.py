from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import require_api_key
from .models import LhbRequest, MarketRequest, StockAnalyzeRequest, TushareQueryRequest
from .services import analyze_stocks, lhb_rank, sector_rank, tushare_query
from datetime import date


class HealthResponse(BaseModel):
    status: str


app = FastAPI(
    title="China & Global Stock Research Skills API",
    description="Cloud API for stock analysis, Tushare research, A-share sectors and Dragon Tiger List. Research only; not investment advice.",
    version="1.0.0",
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


@app.post("/v1/stocks/analyze", operation_id="analyzeStocks", dependencies=[Depends(require_api_key)])
def stocks_analyze(request: StockAnalyzeRequest):
    return call(analyze_stocks, request.symbols, request.days, request.include_news)


@app.post("/v1/market/sectors", operation_id="rankConceptSectors", dependencies=[Depends(require_api_key)])
def market_sectors(request: MarketRequest):
    return call(sector_rank, request.trade_date, request.top)


@app.post("/v1/market/dragon-tiger-list", operation_id="rankDragonTigerList", dependencies=[Depends(require_api_key)])
def market_lhb(request: LhbRequest):
    return call(lhb_rank, request.trade_date, request.top, request.ts_code)


@app.post("/v1/tushare/query", operation_id="queryTushare", dependencies=[Depends(require_api_key)])
def query_tushare(request: TushareQueryRequest):
    return call(tushare_query, request.api_name, request.params, request.fields, request.limit)
