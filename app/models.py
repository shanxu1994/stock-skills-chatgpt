from typing import Literal

from pydantic import BaseModel, Field, field_validator


class StockAnalyzeRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=10)
    days: int = Field(default=120, ge=35, le=1000)
    include_news: bool = True

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, symbols: list[str]) -> list[str]:
        cleaned = [item.strip().upper() for item in symbols if item.strip()]
        if not cleaned:
            raise ValueError("At least one symbol is required")
        return list(dict.fromkeys(cleaned))


class MarketRequest(BaseModel):
    trade_date: str | None = Field(default=None, pattern=r"^\d{8}$")
    top: int = Field(default=10, ge=1, le=50)


class LhbRequest(MarketRequest):
    ts_code: str | None = None


class TushareQueryRequest(BaseModel):
    api_name: Literal[
        "stock_basic", "trade_cal", "daily", "weekly", "monthly",
        "daily_basic", "fina_indicator", "income", "balancesheet",
        "cashflow", "forecast", "express", "moneyflow", "moneyflow_hsgt",
        "hsgt_top10", "top_list", "top_inst", "index_basic", "index_daily",
        "index_classify", "index_member_all", "sw_daily", "ths_index",
        "ths_member", "ths_daily", "limit_list_d", "limit_step", "news",
        "major_news", "research_report", "anns_d", "cn_cpi", "cn_ppi",
        "cn_pmi", "cn_gdp", "cn_m", "sf_month", "shibor", "shibor_lpr",
        "us_tycr", "us_daily", "hk_daily", "index_global", "fund_basic",
        "fund_nav",
    ]
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    fields: list[str] | None = None
    limit: int = Field(default=200, ge=1, le=2000)
