# Stock Skills for ChatGPT Mobile

把 `stock-analysis`、`stock-sector-monitoring` 和 `tushare` 三类能力整合成一个云端 FastAPI 服务，通过 Custom GPT Actions 在手机 ChatGPT 中调用。

## 功能

- A股、港股、美股行情与 MA/MACD/RSI/量能/乖离率机械评分
- Tushare 财务、估值、资金流、公告、板块、指数、基金与宏观查询；无 Token 或权限不足时自动降级到 AkShare
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
# 可选；未设置时公开数据查询会自动使用 AkShare
export TUSHARE_TOKEN="your-token"
export API_SECRET="your-long-random-secret"
uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs` 查看接口。

## Render 部署

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/shanxu1994/stock-skills-chatgpt)

1. 点击上方按钮并使用 GitHub 登录 Render。
2. 可选设置 Secret：`TUSHARE_TOKEN`、`TAVILY_API_KEY`。不设置 Tushare Token 也可使用公开数据降级功能。
3. 创建 Blueprint，等待 Docker 构建与健康检查完成。
4. 记录服务 URL 和自动生成的 `API_SECRET`。
5. 检查 `https://你的服务域名/health` 返回 `{"status":"ok"}`。

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

## 数据源与自动降级

服务优先使用免费的公开 HTTP 数据源：概念板块使用东方财富公开行情接口，指定股票基础信息使用腾讯公开行情接口。公开接口暂时不可用时，再尝试 AkShare；配置了 `TUSHARE_TOKEN` 后，其他 Tushare 查询仍会优先使用 Tushare，遇到无权限、额度不足或限流时自动降级。

降级响应尽量沿用原字段，并额外包含 `source`、`fallback: true` 和 `fallback_reason`。`stock_basic` 查询结果会缓存 5 分钟，减少重复请求触发限流。通用查询目前可降级的类型包括 `stock_basic`、`trade_cal`、`daily`、`weekly`、`monthly`、`ths_index` 和 `top_list`；其他 Tushare 专属数据若没有可靠的公开映射，会返回空 `items` 和说明性的 `note`，不会令整个 Action 失败。公开源的更新时间、字段和历史覆盖范围可能与 Tushare 不同。

`/v1/stocks/intraday` 不依赖 Tushare，按腾讯公开行情、新浪公开行情、东方财富直连、AkShare 兼容层的顺序获取 A 股分钟数据。响应中的 `source_attempts` 会列出已经尝试的数据源；发生降级时，`fallback_reason` 会保留每个失败源的异常类型和原因。若全部失败，HTTP 503 的 `detail` 同样包含四路错误，便于从 Render 日志直接定位问题。

## 安全说明

- 不要把 `.env`、Tushare Token 或 API Secret 提交到 GitHub。
- 即使仓库公开，密钥也只应存于 Render Environment。
- 建议定期轮换 `API_SECRET`，泄漏后立即更换。
