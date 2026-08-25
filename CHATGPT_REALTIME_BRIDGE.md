# ChatGPT Real-time A-share Analysis Bridge

This public page is a stable navigation bridge to the server-rendered real-time analysis service.

## Universal analysis entry

[Open the universal A-share analysis hub](https://stock-skills-chatgpt-p4vq.onrender.com/public/analysis)

The hub accepts any valid six-digit A-share code and redirects server-side to `/public/analysis/{symbol}`.

## Verification links

- [行云科技 300209](https://stock-skills-chatgpt-p4vq.onrender.com/public/analysis/300209)
- [德明利 001309](https://stock-skills-chatgpt-p4vq.onrender.com/public/analysis/001309)
- [诺德股份 600110](https://stock-skills-chatgpt-p4vq.onrender.com/public/analysis/600110)

## Data contract

The target page is generated server-side and exposes the current intraday snapshot, VWAP, 15/30-minute change, MA5/MA10/MA20, MACD, RSI, MA5 bias, volume metrics, recent one-minute bars, recent daily bars, data source and update timestamps.

The bridge does not modify strict-entry strategy parameters or market-data calculations. It only provides a stable public navigation path to the existing Render service.
