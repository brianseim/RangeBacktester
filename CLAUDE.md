# CLAUDE.md — EvoD Trader Range Backtester

This file gives Claude Code the context needed to work on this project without
breaking things or repeating mistakes already solved.

---

## What This Project Is

Two Pine Script v6 indicators for TradingView that backtest range-breakout trading
strategies across any instrument (futures, stocks, forex). Built for a prop trading
account (Apex 25K) with a specific set of qualified instruments and rules.

**Primary file:** `EvoD_Trader_ORB_Backtest.pine` — this is the one to edit.
**Secondary file:** `EvoD_NewsReversal_Backtest.pine` — standalone, separate logic.
**Ignore:** Any other `.pine` files in the repo are old/superseded versions.

---

## Pine Script v6 Gotchas — DO NOT REPEAT THESE MISTAKES

These were all discovered through painful trial and error. Every single one will
cause a compile error or silent logic bug if violated.

### 1. No single-line `if x then y`
Pine v6 does NOT allow:
```pine
if condition then statement  // ❌ SYNTAX ERROR
```
Always use multi-line:
```pine
if condition        // ✅
    statement
```

### 2. No comma-separated `var` declarations
Pine v6 does NOT support:
```pine
var int a=0, b=0, c=0  // ❌ only 'a' persists correctly
```
Always declare separately:
```pine
var int a=0  // ✅
var int b=0
var int c=0
```

### 3. No modifying global variables inside functions
Pine v6 forbids functions from writing to global `var` counters:
```pine
myFunc() =>
    globalCounter += 1  // ❌ CE10088 error
```
**The workaround we use:** Set `rr_*` flag variables (e.g. `rr_go`, `rr_out`,
`rr_dow`) inside the trade logic, then process them in a top-level `if rr_go`
block that increments the actual counters. See the "PROCESS RESULT" section
in the ORB script.

### 4. No `array.from()` with color types
```pine
myColors = array.from(color.red, color.green)  // ❌ type error
```
Use inline ternary or `array.new_<type>()` + `array.set()` instead.

### 5. Time detection must use boundary-crossing, not exact match
On futures, bars land exactly at HHMM boundaries. On stocks and forex, they don't.
Using `barTimeMinutes == 585` (exact) will miss bars on non-futures charts.

Always use crossing logic:
```pine
// ✅ fires on first bar that crosses into the window
isFirstRangeBar = barTimeMinutes >= rangeStartM and barTimeMinutes < rangeEndM
    and (barTimeMinutes[1] < rangeStartM or barTimeMinutes[1] >= rangeEndM)

// ✅ fires once when crossing the end boundary
if barTimeMinutes >= rangeEndM and barTimeMinutes[1] < rangeEndM
    rangeSet := true
```

### 6. HHMM to minutes conversion requires math.floor()
Pine treats input integers as floats in division:
```pine
hm2min(hm) => (hm / 100) * 60 + (hm % 100)       // ❌ 845/100 = 8.45 × 60 = 507 (WRONG)
hm2min(hm) => math.floor(hm / 100) * 60 + (hm % 100)  // ✅ gives 525 correctly
```
This bug caused zero signals on all instruments for a long time.

### 7. for-in loops on arrays may be unreliable
Prefer indexed loops:
```pine
// ❌ may not work reliably
for val in myArray
    doSomething(val)

// ✅ use index loop
for i = 0 to array.size(myArray) - 1
    val = array.get(myArray, i)
    doSomething(val)
```

### 8. Paragraph borders: left/right not allowed
Pine v6 paragraph borders only support `top` and `bottom`. Adding `left` or
`right` to a paragraph border causes a validation error. Table cell borders
support all four sides.

### 9. Timezone functions must use the `tz` variable
Always pass the user-configured timezone:
```pine
barHour = hour(time, tz)    // ✅
barHour = hour(time)        // ❌ uses chart timezone, not user setting
```

---

## Architecture Decisions

### Why the `rr_*` flag pattern exists
Pine v6 forbids functions from modifying global variables (CE10088). All counter
increments happen in a top-level `if rr_go` block ("PROCESS RESULT"). The trade
resolution logic sets `rr_go := true` plus outcome details (`rr_out`, `rr_isLong`,
`rr_isS2`, `rr_dow`), then the process block reads them and increments counters.

### Why stop uses candle body, not wick
`math.min(open, close)` = body bottom (long stop)
`math.max(open, close)` = body top (short stop)
The user explicitly chose body-based stops — wicks would make stops too loose and
inconsistent. The ATR buffer is added on top of the body level.

### Why stop is triggered by bar CLOSE not intrabar wick
A 5-min bar closing beyond the stop level confirms the move. Wicks create too many
false stops on volatile instruments like MGC and M2K. This is intentional.

### Why targets use intrabar HIGH/LOW touch
Targets (50/100/200%) register when the bar's high or low touches the level, not
requiring a close. This is the opposite of stop behavior and is intentional — it
gives credit for the move without requiring a close beyond the target.

### Why outcome buckets are exclusive and cumulative
The targets are **cumulative** (50% = reached at least 50%, includes 100/200 trades)
and **exclusive** (each trade lands in exactly one bucket). This was a deliberate
fix — the original script double-counted by recording 50%, 100%, and 200% as
separate non-exclusive counters, causing columns to sum over 100%.

**Furthest target reached wins:** if a trade touches 50% then later stops, it
books as 50% (a win), not a stop. This prevents double-counting.

WIN RATE = 50% + 100% + 200% + Timeout W
LOSS RATE = Stop + Timeout L
WIN + LOSS = 100% always.

### Why `bar_index > entryBar` exists in resolution
The entry bar itself is excluded from stop/target resolution. Without this, a large
entry candle could immediately trigger the stop on the same bar it entered.

### Why the preset overrides manual session fields
The preset dropdown uses `_rangeStartHM` etc. (underscore-prefixed) computed from
the preset, falling back to the user's manual inputs only when preset = "Custom".
The manual fields in the Session group are cosmetically visible but functionally
ignored unless Custom is selected. This is by design — Pine can't auto-populate
input fields programmatically.

### Why visual elements use `xloc.bar_time` not `xloc.bar_index`
`bar_index` anchored objects shift when TradingView loads more historical data
(bar indices get reassigned). `xloc.bar_time` anchors to Unix timestamps which
never shift. All `line.new()`, `box.new()`, and `label.new()` calls must use
`xloc=xloc.bar_time` and pass `time` (not `bar_index`) as the x coordinate.

### Why there's a `plot(close, "scale_anchor", ...)` at the bottom
Without any `plot()` call, TradingView gives the indicator its own price axis
independent of the candles. The transparent close plot forces the indicator to
share the candle price scale so labels and lines track candles vertically on scroll.

---

## Known Issues / To-Do List

### Pending features (not yet built)
1. **Range size filter** — skip S1 signals when range height < N × ATR(14).
   On small ranges (e.g. 11.6 pts with ATR ~5) the stop is nearly as large as the
   50% target, making R/R unfavorable. Add `minRangeRatio` input (default 2.0),
   color range box red when too small, suppress signals.

2. **Market open presets** — offset-based session times anchored to market opens
   (NY Futures 7:30 CT, NY Equities 8:30 CT, London 2:00 CT, Tokyo 6:00 PM CT).
   Instead of HHMM inputs, user would set minutes-before-open and range duration.
   Opens stored in UTC internally; Pine converts to chart timezone automatically.

3. **Conditional probability tracking** — "given S1 reached 50%, what % then
   reached 100%?" Currently the script tracks cumulative probabilities. Adding
   conditional tracking would sharpen the scaling math (2/5 + 2/5 + 1/5 exits).

### Previously attempted, reverted
- **Multi-timeframe (MTF) support** — attempted to force 5-min calculation on
  any chart TF using `request.security_lower_tf()`. Broke signal counts to zero
  even on native 5-min charts. Root cause unclear (possibly `isNativeTF` branch
  not short-circuiting correctly). Reverted entirely. The script is designed for
  5-min charts only.

---

## Instrument Configuration Reference

| Instrument | Range Start | Range End | Entry Start | Entry End | Exit | TZ |
|---|---|---|---|---|---|---|
| MES / MGC / M2K / M6E | 745 | 845 | 845 | 930 | 1200 | America/Chicago |
| AAPL / stocks | 400 | 930 | 945 | 1130 | 1400 | America/New_York |
| IB First Hour | 930 | 1030 | 1030 | 1600 | 1600 | America/Chicago |

**Extended hours:** ON for futures and IB. OFF or ON for stocks (ON required if
range start is before 9:30 ET).

---

## Qualified Instruments (66%+ win rate threshold, Jun 2025–Jun 2026 backtest)

| Instrument | Setup | Direction | Win Rate | Best Days | Notes |
|---|---|---|---|---|---|
| MGC (Gold micro) | S1 | SHORT | 71% / 75% Thu | Tue/Thu/Fri | Skip Mon/Wed |
| M2K (Russell micro) | S1 | LONG | 71% / 67% Thu | Thursday | Borderline other days |
| M6E (Euro micro) | All | All | 69% Tue / 67% Thu | Tue/Thu only | Fri 35% — avoid |
| MES (ES micro) | S1 | LONG | 61% | Any | Borderline; supplemental |
| MNQ (NQ micro) | — | — | 44% | — | NO EDGE — do not use |
| MYM (Dow micro) | — | — | 50% | — | NO EDGE — do not use |
| MCL (Crude micro) | — | — | No day ≥66% | — | Removed from plan |

**Day-of-week pattern:**
- Monday: dead (50–75% loss rate)
- Tuesday: qualified (MGC 67%, M6E 69%)
- Wednesday: dead (50–69% loss rate)
- Thursday: best day (MGC 75%, M2K 67%, M6E 67%)
- Friday: qualified (MGC 71%)

---

## Account Context (Apex 25K Performance Account)

- Profit target: $26,600
- Trailing drawdown: $1,000 EOD
- Daily loss limit (self-imposed): $150
- Daily profit cap (self-imposed): $300 (consistency rule: no day > 40% of total)
- Max contracts: 1 MES mini / 10 micros
- MGC fits larger accounts (Tradeify 150K) — stop too large for 25K
- MNQ: proven negative edge, never trade

---

## Script Structure (EvoD_Trader_ORB_Backtest.pine)

Sections in order:
1. `indicator()` declaration
2. INPUTS (Preset, Date Range, Session, Risk, Display, Alerts)
3. HOLIDAY EXCLUSION (US federal holidays hardcoded)
4. SESSION HELPERS (hm2min, barTimeMinutes, window booleans, dowNow, atr14)
5. RANGE CALCULATION (orHigh, orLow, rangeSet, isFirstRangeBar)
6. RANGE LINES + ZONE BOXES (orange range, blue entry, dashed splits, extensions)
7. OUTCOME COUNTERS (e1l/e1s/e2l/e2s × tot/stop/t50/t100/t200/fw/fl, DOW arrays)
8. TRADE STATE (a1_* for S1/FA, a2_* for S2, rr_* recording flags)
9. DAILY RESET
10. S1 RESOLUTION (target touches, stop check, noon exit)
11. S2 RESOLUTION (same structure)
12. PROCESS RESULT (reads rr_*, increments counters — the global-mod workaround)
13. SETUP 1 — Initial Breakout entry
14. FAILED AUCTION REVERSAL entry
15. SETUP 2 — Wick Retest entry
16. TABLES (top-right overall, bottom-right day-of-week)
17. Scale anchor plot

---

## Testing Checklist After Any Change

Before committing changes, verify on TradingView:
- [ ] Compiles without errors on Pine v6
- [ ] Signals fire on MES 5-min chart (should see ~35 S1 LONG in Jun 2025–Jun 2026)
- [ ] Columns sum to 100% (WIN RATE + LOSS RATE = 100%)
- [ ] Orange range boxes draw at correct times (7:45–8:45 CT for OR preset)
- [ ] Labels/lines track with candles when scrolling (time-anchored)
- [ ] No signals on Monday or Wednesday for MGC when filtered by day table
- [ ] Works on AAPL 5-min chart with extended hours ON and stock settings
- [ ] Preset dropdown switches correctly (footer shows active preset times)
