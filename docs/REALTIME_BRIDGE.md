# Production realtime stock bridge

This bridge productionizes the proven Tencent -> Render -> GitHub Actions -> GitHub JSON -> ChatGPT path.

## Stable read contract

- Per stock: `data/realtime/<6-digit-code>.json`
- Index: `data/realtime/manifest.json`
- Render source: `/public/analysis-data/<6-digit-code>`
- Manual dispatch accepts any comma-separated 6-digit A-share symbols.
- Scheduled refresh runs every 5 minutes during UTC windows covering A-share sessions; an Asia/Shanghai gate prevents writes outside trading minutes.

## Strategy invariants

The bridge is transport only. It does not modify the existing strict-entry indicator engine, weights, thresholds, score, or signal logic. Payloads retain `strategy_contract.parameters_changed=false`; bridge metadata also records `strategy_parameters_changed=false`.

Downstream analysis must continue to enforce the existing strict-entry rules, including the no-chase rule when MA5 bias is over 5%, and must distinguish raw market facts from rule score/model judgment and T-plan execution.

## Reliability

- Render may return a partial payload if only one upstream market-data family is available.
- Each snapshot validates the requested symbol and presence of market data before replacing the prior JSON.
- Temporary files avoid publishing half-written JSON.
- Workflow concurrency serializes writers.
- Push uses rebase plus bounded retries to tolerate concurrent changes on `main`.
- `manifest.json` exposes freshness (`updated_at`, `intraday_as_of`) so readers can reject stale data instead of silently treating it as realtime.

## Initial validation watchlist

The default production smoke-test set is `001309,600110,300209`. This is only a default scheduled watchlist; manual dispatch supports arbitrary six-digit A-share codes without code changes.
