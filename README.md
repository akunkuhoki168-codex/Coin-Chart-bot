# Coin Chart — Binance Spot

Smartphone-first live chart for every Binance Spot USDT pair. BUY marks a confirmed swing bottom and SELL marks a confirmed swing top, using an ATR-adaptive zigzag.

**Live:** https://dedkovic441-hub.github.io/coin-chart/

- Default symbol: PUMP/USDT (last choice is remembered)
- Coin list from `exchangeInfo` (TRADING USDT), live prices via `!miniTicker@arr`
- Per-trade updates (`aggTrade` + kline), timeframes 1m / 5m / 15m / 1h / 4h / 1D
- Indicators: EMA 20/50, RSI 14, volume bars, and an optional SSL baseline (HMA 60, colored by close versus the baseline)
- Signals: ATR-adaptive zigzag with Sensitivity Low / Med / High, optional forming BUY? / SELL? markers, shock-wick clipping, and strict alternation
- Quality stars (0–3) come from RSI stretch or divergence, a small engulfing/hammer check, and volume spikes — stars do not block a signal
- The arrow sits on the actual pivot candle; confirmation comes later, after price reverses by about 5×ATR (Med). Confirmed markers do not repaint
- Connection: Binance REST and WebSocket with failover, plus a REST polling fallback
- Times in UTC+7 (Asia/Jakarta)

The Tokocrypto version has been removed. `binance.html` redirects here.
