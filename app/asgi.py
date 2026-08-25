"""Combined ASGI entrypoint for REST, public read-only data, and MCP."""

from contextlib import asynccontextmanager
from html import escape
import re

from fastapi import HTTPException, Path, Query
from fastapi.responses import HTMLResponse

from .main import app, intraday_snapshot
from .analysis_data import unified_analysis_data
from .mcp_server import mcp, mcp_app


def _load_public_intraday(symbol: str, bars: int):
    try:
        return intraday_snapshot(symbol, bars)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream data request failed: {exc}") from exc


def _load_analysis_data(symbol: str):
    try:
        return unified_analysis_data(symbol)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unified market data request failed: {exc}") from exc


def _validate_fixed_symbol(symbol: str) -> str:
    if not re.fullmatch(r"\d{6}", symbol):
        raise HTTPException(status_code=422, detail="symbol must be a 6-digit A-share code")
    return symbol


def _intraday_html(snapshot: dict, symbol: str) -> HTMLResponse:
    metrics = snapshot.get("metrics") or {}; bars = snapshot.get("one_minute_bars") or []
    def v(k):
        x=metrics.get(k); return "—" if x is None else escape(str(x))
    rows="".join("<tr>"+"".join(f"<td>{escape(str(b.get(k,'')))}</td>" for k in ("time","open","high","low","close","volume"))+"</tr>" for b in bars[-60:])
    title=escape(str(snapshot.get("name") or snapshot.get("symbol") or symbol)); normalized=escape(str(snapshot.get("symbol") or symbol)); source=escape(str(snapshot.get("source") or "unknown")); as_of=escape(str(snapshot.get("as_of") or ""))
    html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><title>{title} 分时行情</title><style>body{{font-family:system-ui,sans-serif;margin:24px;line-height:1.5}}main{{max-width:980px;margin:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}.card{{border:1px solid #ddd;border-radius:10px;padding:12px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px;border-bottom:1px solid #eee;text-align:right}}</style></head><body><main><h1>{title} {normalized}</h1><p>更新时间：{as_of} ｜ 数据源：{source}</p><div class="grid">{''.join(f'<div class="card">{label}<br><strong>{v(key)}</strong></div>' for label,key in [('当前价','current'),('VWAP','vwap'),('日内高点','session_high'),('日内低点','session_low'),('15分钟变化%','change_15m_pct'),('30分钟变化%','change_30m_pct')])}</div><h2>最近1分钟数据</h2><table><tbody>{rows}</tbody></table></main></body></html>'''
    return HTMLResponse(html,headers={"Cache-Control":"no-store, max-age=0"})


def _analysis_html(payload: dict, symbol: str) -> HTMLResponse:
    intraday=payload.get("intraday") or {}; im=intraday.get("metrics") or {}; daily=payload.get("daily") or {}; indicators=daily.get("indicators") or {}; meta=payload.get("meta") or {}
    title=escape(str(payload.get("name") or payload.get("symbol") or symbol)); normalized=escape(str(payload.get("symbol") or symbol))
    def pick(m,*keys):
        for k in keys:
            if k in m and m[k] is not None: return escape(str(m[k]))
        return "—"
    cards=[("当前价",pick(im,"current")),("VWAP",pick(im,"vwap")),("日内高点",pick(im,"session_high")),("日内低点",pick(im,"session_low")),("15分钟变化%",pick(im,"change_15m_pct")),("30分钟变化%",pick(im,"change_30m_pct")),("MA5",pick(indicators,"ma5","MA5")),("MA10",pick(indicators,"ma10","MA10")),("MA20",pick(indicators,"ma20","MA20")),("MACD",pick(indicators,"macd","MACD")),("MACD Signal",pick(indicators,"macd_signal","MACD_SIGNAL","signal")),("RSI14",pick(indicators,"rsi14","RSI14","rsi")),("MA5乖离率%",pick(indicators,"bias_ma5_pct","bias5_pct","BIAS_MA5_PCT")),("5/20成交量比",pick(indicators,"volume_ratio_5_20","vol_ratio_5_20","volume_ratio")),("严进信号",pick(indicators,"signal","strict_signal","decision")),("严进评分",pick(indicators,"score","strict_score"))]
    card_html="".join(f'<div class="card"><div class="label">{escape(a)}</div><div class="value">{b}</div></div>' for a,b in cards)
    minute_rows="".join("<tr>"+"".join(f"<td>{escape(str(b.get(k,'')))}</td>" for k in ("time","open","high","low","close","volume"))+"</tr>" for b in (intraday.get("one_minute_bars") or [])[-30:])
    daily_rows="".join("<tr>"+"".join(f"<td>{escape(str(b.get(k,'')))}</td>" for k in ("trade_date","open","high","low","close","volume"))+"</tr>" for b in (daily.get("recent_daily_bars") or [])[-20:])
    html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><title>{title} 严进策略实时分析数据</title><style>body{{font-family:system-ui,sans-serif;margin:24px;line-height:1.5}}main{{max-width:1100px;margin:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}.card{{border:1px solid #ddd;border-radius:10px;padding:12px}}.label,.meta{{color:#666}}.value{{font-size:19px;font-weight:650}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px;border-bottom:1px solid #eee;text-align:right}}</style></head><body><main><p><a href="/public/analysis">← 实时分析入口</a></p><h1>{title} <small>{normalized}</small></h1><p class="meta">分时更新时间：{pick(meta,'intraday_as_of')} ｜ 分时源：{pick(meta,'intraday_source')} ｜ 日线更新时间：{pick(meta,'daily_as_of')} ｜ 日线源：{pick(meta,'daily_source')}</p><p class="meta">策略参数改变：{pick(payload.get('strategy_contract') or {},'parameters_changed')} ｜ 服务器端实时生成，无 JavaScript。</p><div class="grid">{card_html}</div><h2>最近30根1分钟数据</h2><table><tbody>{minute_rows}</tbody></table><h2>最近20根日线</h2><table><tbody>{daily_rows}</tbody></table></main></body></html>'''
    return HTMLResponse(html,headers={"Cache-Control":"no-store, max-age=0","X-Robots-Tag":"index, follow"})


def _analysis_hub_html() -> HTMLResponse:
    # Keep this page static and cheap: it is a stable navigation root that lets
    # readers discover dynamic stock pages by following ordinary same-origin links.
    html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><title>严进策略实时分析入口</title><style>body{font-family:system-ui,sans-serif;margin:24px;line-height:1.6}main{max-width:760px;margin:auto}a{display:block;border:1px solid #ddd;border-radius:12px;padding:16px;margin:12px 0;font-size:20px;text-decoration:none;color:#111}</style></head><body><main><h1>严进策略实时分析入口</h1><p>固定服务器端导航页。点击股票后实时读取统一行情数据；策略参数不在此页修改。</p><a href="/public/analysis/001309">德明利 001309</a><a href="/public/analysis/600110">诺德股份 600110</a></main></body></html>'''
    return HTMLResponse(html,headers={"Cache-Control":"public, max-age=60","X-Robots-Tag":"index, follow"})


@app.get("/public/intraday",operation_id="publicIntraday",include_in_schema=True)
def public_intraday(symbol:str=Query(...,min_length=6,max_length=20),bars:int=Query(240,ge=30,le=600)): return _load_public_intraday(symbol,bars)
@app.get("/public/intraday/view",response_class=HTMLResponse,include_in_schema=False)
def public_intraday_view(symbol:str=Query(...,min_length=6,max_length=20),bars:int=Query(240,ge=30,le=600)): return _intraday_html(_load_public_intraday(symbol,bars),symbol)
@app.get("/public/intraday/{symbol}",operation_id="publicIntradayFixed",include_in_schema=True)
def public_intraday_fixed(symbol:str=Path(...)): symbol=_validate_fixed_symbol(symbol); return _load_public_intraday(symbol,240)
@app.get("/public/intraday/{symbol}/view",response_class=HTMLResponse,include_in_schema=False)
def public_intraday_fixed_view(symbol:str=Path(...)): symbol=_validate_fixed_symbol(symbol); return _intraday_html(_load_public_intraday(symbol,240),symbol)
@app.get("/public/analysis-data/{symbol}",operation_id="publicAnalysisData",include_in_schema=True)
def public_analysis_data(symbol:str=Path(...)): symbol=_validate_fixed_symbol(symbol); return _load_analysis_data(symbol)
@app.get("/public/analysis",response_class=HTMLResponse,include_in_schema=False)
def public_analysis_hub(): return _analysis_hub_html()
@app.get("/public/analysis/{symbol}",response_class=HTMLResponse,include_in_schema=False)
def public_analysis_view(symbol:str=Path(...)): symbol=_validate_fixed_symbol(symbol); return _analysis_html(_load_analysis_data(symbol),symbol)

@asynccontextmanager
async def lifespan(_app):
    async with mcp.session_manager.run(): yield
app.router.lifespan_context=lifespan
app.mount("/mcp",mcp_app)
