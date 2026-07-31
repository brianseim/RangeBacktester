# EvoD Trader — Range Backtester

Pine Script v6 indicator for backtesting range-breakout, mid-range-cross, and
wick-rejection trading strategies — anchored to New York, London, or Tokyo
market opens, or the CME's daily reopen — on TradingView. Works on futures,
stocks, and forex.

## Files

| File | Description |
|---|---|
| `EvoD_Trader_Range.pine` | Main Range backtest indicator with alerts |

---

## EvoD Trader Range

### How to Use
1. Open TradingView on any 5-min chart (MES, MGC, AAPL, USDEUR, etc.)
2. Pine Editor → New → paste the `.pine` file → Add to Chart
3. Pick a **Range Shape** and **Market** from the settings (or Custom for
   manual HHMM times)
4. Pin the indicator to the main price scale (right-click scale → merge)

### Range Shape × Market

Two independent pickers instead of enumerated presets — Range Shape sets the
time offsets, Market sets which open they're relative to.

| Range Shape | Window | Uses Market? |
|---|---|---|
| IB | `[open, open + N hours]` | Yes |
| ORB | `[open − N hours, open]` | Yes |
| EvoD ORB | `[open + 15min − N hours, open + 15min]` | Yes |
| Futures Start 15min | `[CME reopen, +15min]` (fixed to 5:00 PM CT) | No |
| Futures Start IB | `[CME reopen, +N hours]` (5:00 PM CT) | No |
| Custom | Manual HHMM, in the TZ setting | No |

- **N Hours** — shared decimal-hours input (default 1.0), used by IB, ORB,
  EvoD ORB, and Futures Start IB.
- **Entry Window Duration** — decimal hours (default 6.0), applied uniformly
  to every non-Custom shape: entry opens exactly when the range ends, and
  the position must exit by the time the entry window closes (no separate
  timeout time anymore).
- **Market opens**: New York 9:30 AM ET, London 8:00 AM GMT/BST, Tokyo 9:00
  AM JST — all DST-correct.

### Twelve Signals Tracked

Only one trade can be live at a time, across every signal below — whichever
fires first takes the slot, and no other signal can trigger until it fully
resolves (stop-out or final target; partial scale-outs don't free it up).

**BOL / BOS — Breakout**
5-min bar closes beyond the range high (BOL, long) or range low (BOS,
short). Entry at that bar's close.

**FAL / FAS — Failed-Auction Reversal**
After a BOL/BOS stops out, price closes beyond the *opposite* range edge →
enter the reversal (FAL if the failed breakout was short, FAS if it was
long). One reversal per day max.

**MIDL / MIDS — Mid-Range Cross**
5-min bar closes on the opposite side of the range midpoint from where it
came (edge-triggered, not level-triggered). MIDL/MIDS can follow each other
within the same day once the prior one resolves — common right after a
failed cross, since entry is right at the midpoint to begin with.

**WHL / WHS / WLL / WLS / WML / WMS — Wick Rejection**
A two-bar pattern at any of the three boundaries (range high, range low,
mid): one bar wicks through the boundary but closes back on its original
side (the "wick bar"); the very next bar must close beyond the wick bar's
own high (→ long: WHL/WLL/WML) or low (→ short: WHS/WLS/WMS) to confirm.
Unconfirmed wicks expire after one bar — there's no waiting for a later
confirmation.

### Stop Rule (all 12 signals, one unified model)
Tighter of two options, whichever is closer to entry:
- **Body/wick-extreme ± ATR:** `math.min(open, close) − ATR(14) × mult` for
  longs (mirrored for shorts) — using the wick bar's own high/low instead of
  the entry candle's body for the six wick-rejection signals.
- **Quartile cap:** `entry ∓ rangeHeight × 0.25` — guarantees the stop never
  exceeds one quartile of the range.

Triggered by 5-min bar **close** beyond the stop (not intrabar wick) —
except the wick-rejection signals, where the *wick itself* is the entry
trigger by definition.

### Targets
- 50%, 100%, 200% of range height from entry, same formula for all 12
  signals.
- Registered on intrabar high/low touch.
- Exit mode (Scale / Full@100 / Full@50) controls how the position actually
  exits — reach-tracking (did price ever touch each leg) is recorded
  separately from the realized P&L outcome.

### Performance Table
One consolidated table (rows = whichever signals are enabled, plus an ALL
row) instead of separate tables per family. Columns: Trades, Win%, T1/T2/
Final reach%, Avg Win/Loss, Expectancy (points and $MNQ), Profit Factor, Max
Drawdown, Max Loss Streak, Avg Range, Avg ATR, and a per-weekday win/loss
cross-tab (Monday–Friday). Disabling a signal drops its row entirely.

### Visuals
- **Orange filled rectangle** = range build zone (amber border on days the
  quartile stop cap was tighter than body/wick+ATR)
- **Blue filled rectangle** = entry window zone
- **Dashed lines inside range** = 25%, 50%, 75% quartiles/midpoint, with
  price labels on the left
- **Dashed extension lines** = 50%, 100%, 200% targets above and below the
  range, with price labels on the left
- **Range size label** = points, lower-right corner of the range box
- **Entry labels:** signal name + entry price + stop distance in points and
  ticks
- **Outcome labels:** STOP (red), TARGET (lime), TIMEOUT (gray), with the
  realized points

### Configurable Settings

**Date Range:** Backtest lookback in days (default 365, always relative to
"now" — no stale hardcoded dates to remember to update).

**Preset:** Range Shape, Market, N Hours, Entry Window Duration.

**Session (Custom shape only):** Timezone, manual Range/Entry/Exit HHMM.

**Risk:** ATR Length (default 14), ATR stop buffer multiplier (default 1.0).

**Filters:** Holiday exclusion, Range Quality Filter (skip entries where
range height < N × ATR14).

**Display:** Range lines/zones, signal labels, extension labels, reference
price labels, recent-N-days-only pruning, zone colors.

**Signals:** 12 independent enable/disable toggles (BOL, BOS, FAL, FAS,
MIDL, MIDS, WHL, WHS, WLL, WLS, WML, WMS).

**Alerts (fire on confirmed bar close):** grouped by family — breakout
(BOL/BOS), failed-auction (FAL/FAS), mid-cross (MIDL/MIDS), wick-rejection
(all six).

**Exit Simulation:** Exit Mode (Scale/Full@100/Full@50), MNQ contracts (for
$ expectancy).

---

## Disclaimer
This software is for educational and research purposes only. Not financial advice. Past backtest performance does not guarantee future results. Always forward test before risking real capital.

---

## License
MIT — use freely, attribution appreciated.
