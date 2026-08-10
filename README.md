# Stock Skills for ChatGPT Mobile

把 `stock-analysis`、`stock-sector-monitoring` 和 `tushare` 三类能力整合成一个云端 FastAPI 服务，通过 Custom GPT Actions 在手机 ChatGPT 中调用。

## 功能

- A股、港股、美股行情与 MA/MACD/RSI/量能/乖离率机械评分
- Tushare 财务、估值、资金流、公告、板块、指数、基金与宏观查询
- A股概念板块排行
- 龙虎榜排行并过滤 ST 类股票
- 可选 Tavily 新闻搜索
- Bearer API Key 保护，密钥不进入仓库

> 本项目仅供市场研究，不构成投资建议。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export TUSHARE_TOKEN="your-token"
export API_SECRET="your-long-random-secret"
uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs` 查看接口。

## Render 部署

1. 在 Render 选择 **New → Blueprint**，连接本仓库。
2. 设置 Secret：`TUSHARE_TOKEN`；可选设置 `TAVILY_API_KEY`。
3. 部署完成后记录服务 URL 和自动生成的 `API_SECRET`。
4. 检查 `https://你的服务域名/health` 返回 `{"status":"ok"}`。

## 配置 Custom GPT Actions

1. 在网页版 ChatGPT 创建 GPT（手机端用于使用）。
2. 将 [custom-gpt-instructions.md](custom-gpt-instructions.md) 内容复制到 Instructions。
3. 在 Actions 中选择 **Import from URL**，填写：`https://你的服务域名/openapi.json`。
4. Authentication 选择 **API Key → Bearer**，值为 Render 的 `API_SECRET`。
5. 在 Preview 依次测试：
   - `分析 600519 和 AAPL`
   - `查看今天概念板块前 5 名`
   - `查看最近交易日龙虎榜，过滤 ST`
   - `查询贵州茅台最近 8 个季度财务指标`
6. 保存为“仅自己”或按需分享，之后从手机 ChatGPT 的 GPTs 列表打开。

## API

- `GET /health`
- `POST /v1/stocks/analyze`
- `POST /v1/market/sectors`
- `POST /v1/market/dragon-tiger-list`
- `POST /v1/tushare/query`

完整 schema 由 FastAPI 自动生成在 `/openapi.json`。

## 安全说明

- 不要把 `.env`、Tushare Token 或 API Secret 提交到 GitHub。
- 即使仓库公开，密钥也只应存于 Render Environment。
- 建议定期轮换 `API_SECRET`，泄漏后立即更换。
