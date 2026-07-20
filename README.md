# EvoD Trader — Range Backtester

Pine Script v6 indicators for backtesting Opening Range Breakout (ORB) and Initial Balance (IB) strategies on TradingView. Works on futures, stocks, and forex.

## Files

| File | Description |
|---|---|
| `EvoD_Trader_ORB_Backtest.pine` | Main ORB/IB backtest indicator with alerts |
| `EvoD_NewsReversal_Backtest.pine` | News spike reversal backtest indicator |

---

## EvoD Trader ORB Backtest with Alerts

### How to Use
1. Open TradingView on any 5-min chart (MES, MGC, AAPL, USDEUR, etc.)
2. Pine Editor → New → paste the `.pine` file → Add to Chart
3. Select a **Strategy Preset** from the settings dropdown
4. Pin the indicator to the main price scale (right-click scale → merge)

### Strategy Presets

| Preset | Range | Entry Window | Exit | Use For |
|---|---|---|---|---|
| Opening Range 745-845 | 7:45–8:45 AM CT | 8:45–9:30 AM CT | 12:00 PM | Futures pre-market |
| IB First Hour 930-1030 | 9:30–10:30 AM CT | 10:30 AM–4:00 PM | 4:00 PM | RTH first hour |
| Custom | Manual HHMM | Manual HHMM | Manual | Any session |

All times in **America/Chicago (CT)** by default. Change timezone in settings.

### Three Setups Tracked

**S1 — Initial Breakout**
5-min bar closes beyond the range high (long) or range low (short). Entry at that bar's close.

**S2 — Wick Retest**
After a breakout, price pulls back to a key level. Prior bar must have closed beyond the level. This bar wicks back to it and closes in the breakout direction. Genuine rejection required — straight-through continuation doesn't count.

**FA — Failed Auction Reversal**
S1 stops out → price closes beyond the opposite range edge → enter the reversal. One per day max, same entry window as S1.

### Stop Rule
- **Long:** `math.min(open, close) − ATR(14) × multiplier`
- **Short:** `math.max(open, close) + ATR(14) × multiplier`
- Uses candle **body** (not wicks) as the base level
- Triggered by 5-min bar **close** beyond the stop (not intrabar wick)

### Targets
- 50%, 100%, 200% of range height from entry
- Registered on intrabar high/low touch

### Outcome Model
Exclusive buckets summing to 100%:

| Outcome | Definition |
|---|---|
| Stop | Closed beyond stop before any target |
| 50% | Reached ≥50% extension (cumulative — includes 100/200 trades) |
| 100% | Reached ≥100% extension |
| 200% | Reached 200% extension |
| Timeout W | Timed out in profit vs entry |
| Timeout L | Timed out in loss vs entry |
| **WIN RATE** | **50% + 100% + 200% + Timeout W** |
| **LOSS RATE** | **Stop + Timeout L** |

**Furthest target reached wins.** Touch 50% then stop = books as 50% (win).

### Visuals
- **Orange filled rectangle** = range build zone
- **Blue filled rectangle** = entry window zone
- **Dashed lines inside range** = 25%, 50%, 75% quartiles/midpoint
- **Dashed extension lines** = 50%, 100%, 200% targets above AND below range
- **Entry labels:** S1L/S1S (green/red), S2L/S2S (green/red), FA-L/FA-S (fuchsia)
- **Outcome labels:** STOP (red), 50%/100% (lime), 200% (aqua), TO+/TO- (teal/gray)

### Configurable Settings

**Preset** — Quick switch between OR, IB, or Custom

**Session (Custom mode):**
- Timezone dropdown (CT, ET, PT, London, UTC)
- Range START / END (HHMM)
- Entry START / END (HHMM)
- Timeout EXIT (HHMM)

**Risk:**
- ATR Length (default 14)
- ATR stop buffer multiplier (default 1.0)

**Display:**
- Show range lines/zones toggle
- Show signal labels toggle
- Show extension labels (50/100/200%) toggle
- Range zone color (configurable)
- Entry zone color (configurable)
- Recent N days only (default 20)

**Alerts (fires on confirmed bar close):**
- S1 breakout entries
- S2 retest entries
- Failed Auction reversals

### Instrument Settings Reference

| Instrument | Preset | Range | Entry | Exit | TZ |
|---|---|---|---|---|---|
| MES / ES micros | OR 745-845 | 7:45–8:45 CT | 8:45–9:30 CT | 12:00 | Chicago |
| MGC / Gold micros | OR 745-845 | 7:45–8:45 CT | 8:45–9:30 CT | 12:00 | Chicago |
| M2K / Russell micros | OR 745-845 | 7:45–8:45 CT | 8:45–9:30 CT | 12:00 | Chicago |
| M6E / Euro micros | OR 745-845 | 7:45–8:45 CT | 8:45–9:30 CT | 12:00 | Chicago |
| AAPL / stocks | Custom | 4:00–9:30 ET | 9:45–11:30 ET | 14:00 | New_York |
| IB (any futures) | IB 930-1030 | 9:30–10:30 CT | 10:30–16:00 CT | 16:00 | Chicago |

### Key Backtest Findings (Jun 2025–Jun 2026, OR Preset)

**66%+ win rate threshold applied. Results in America/Chicago timezone.**

| Instrument | Setup | Direction | Win Rate | Best Days |
|---|---|---|---|---|
| MGC (Gold micro) | S1 | SHORT | 71% / 75% Thu | Tue / Thu / Fri |
| M2K (Russell micro) | S1 | LONG | 71% / 67% Thu | Thursday best |
| M6E (Euro micro) | All | All | 69% Tue / 67% Thu | Tue / Thu only |
| MES (ES micro) | S1 | LONG | 61% | Any |
| MNQ (NQ micro) | — | — | 44% | **AVOID** |
| MYM (Dow micro) | — | — | 50% | **AVOID** |
| MCL (Crude micro) | — | — | No day ≥66% | **AVOID** |

**Day-of-week pattern (consistent across all instruments):**
- **Monday:** 50–75% loss rate — do not trade
- **Tuesday:** MGC 67%, M6E 69% — qualified
- **Wednesday:** 50–69% loss rate — do not trade
- **Thursday:** MGC 75%, M2K 67%, M6E 67% — **best day**
- **Friday:** MGC 71% — qualified

---

## EvoD Trader News Reversal Backtest

Detects unusually large single-bar moves (spikes) and backtests the reversal trade.

### Spike Detection
Bar body ≥ `spikeMultiplier × ATR(14)`. Default multiplier: 3.0.

Flagged with ⚡↓ (down spike, watch for long reversal) or ⚡↑ (up spike, watch for short reversal).

### Two Entry Types

**E1 — First reversal:** First 5-min bar closing back beyond the spike candle's open. Full rejection confirmed.

**E2 — Retest:** After E1, price pulls back to spike open level, wicks to it, closes back in reversal direction.

### Stop
Spike extreme (low for long reversal, high for short). Optional ATR buffer settable in inputs.

### Targets
50%, 100%, 200% of spike body size from entry. Same exclusive outcome model as the ORB script.

---

## Disclaimer
This software is for educational and research purposes only. Not financial advice. Past backtest performance does not guarantee future results. Always forward test before risking real capital.

---

## License
MIT — use freely, attribution appreciated.
