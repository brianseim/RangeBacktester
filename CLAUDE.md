# CLAUDE.md — EvoD Trader Range Backtester

This file gives Claude Code the context needed to work on this project without
breaking things or repeating mistakes already solved.

---

## What This Project Is

A Pine Script v6 indicator for TradingView that backtests range-breakout,
mid-range-cross, and wick-rejection trading strategies across any instrument
(futures, stocks, forex), anchored to New York/London/Tokyo market opens or
the CME's daily reopen. Built for a prop trading account (Apex 25K).

**Primary file:** `EvoD_Trader_Range.pine` — this is the one to edit. Renamed
from `EvoD_Trader_ORB_Backtest.pine` since the tool now covers far more than
opening-range breakouts.
**Ignore:** Any other `.pine` files in the repo are old/superseded versions.
**Removed:** `EvoD_NewsReversal_Backtest.pine` was deleted — abandoned approach, do not recreate.

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
Pine v6 forbids functions from writing to global `var` state — including
`array.set()`/`array.push()` on a global array — from inside a `=>` function
body:
```pine
myFunc() =>
    globalCounter += 1        // ❌ CE10088 error
    array.set(globalArr, 0, 1) // ❌ also forbidden
```
**The workaround we use:** every stat-accumulator update (`cs_*`, `cx_*`,
`ov_*`) happens directly at the top level, inside plain `if` blocks in the
main script body — never wrapped in a function. Nesting depth doesn't matter
(3+ levels of `if`/`else` is fine); only crossing into a `=>` function body
is forbidden. The only functions in this script are pure calculations with
no side effects (`hm2min`, `tighterStop`, `pct`, `avgOrNA`, `pfOrNA`,
`usdOrNA`, `slotName`) — none of them touch a global variable.

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

### 9. Timezone functions must use the effective timezone variable
Always pass the relevant timezone, never the bare chart timezone:
```pine
barHour = hour(time, effectiveTz)    // ✅
barHour = hour(time)                 // ❌ uses chart timezone, not the shape's timezone
```
`effectiveTz` is `tz` for Custom, the CME's `"America/Chicago"` for the two
Futures Start shapes, or the selected market's IANA timezone string
(`"America/New_York"`/`"Europe/London"`/`"Asia/Tokyo"`) otherwise — see
"Why Range Shape and Market are two separate pickers" below.

### 10. `timenow` can't be used as an `input.time()` default
`timenow` is series-qualified (it changes as real time passes), and
`input.*` default values must not be. This is why the date range is a plain
`lookbackDays` integer input instead of two `input.time()` pickers — both
`startDate`/`endDate` are computed as `timenow ± lookbackDays*86400000` at
the top level, never inside an input default expression.

**Update:** the lookback-days approach was reverted back to explicit
`startDate`/`endDate` via `input.time()` — a rolling "last N days from now"
window can't isolate a specific season or month (e.g. "just last summer"),
which is a real use case. The gotcha above still applies if this ever comes
up again: `input.time()` defaults must be static `timestamp(...)` literals,
never `timenow`-derived, which is why the defaults are wide/future-dated
(2024-01-01 → 2027-01-01) rather than computed — they're meant to be
narrowed manually per backtest, not auto-updated.

---

## Architecture Decisions

### Why only one trade can be live at a time, across every signal family
With 12 signal types (BOL, BOS, FAL, FAS, MIDL, MIDS, WHL, WHS, WLL, WLS,
WML, WMS), giving each its own independent position-tracking state (the old
`a1_*`/`a2_*`/`x1_*`/`x2_*` pattern, duplicated 12 times) would be enormous
and unmaintainable. Instead: a **single set of "current trade" scalars**
(`tradeLive`, `curSlot`, `curEntry`, `curStopCur`, `curT1/T2/T3`, `curStage`,
`curRealized`, `curH1/H2/H3`, `curDow`, `curEbar`, `curRangeH`, `curAtrE`) is
reused sequentially — valid because a live position blocks every other
signal from triggering (`canEnter` requires `not tradeLive`), so there is
never more than one to track. The 12-way split only matters afterward, for
bucketing a *resolved* trade's stats into `cs_*[slot]`.

**Re-entry**: a live trade only frees the gate on stop-out or reaching the
final target — not on partial scale-outs. Any signal (not just the one that
was live) can trigger next, immediately, same day, as many times as the
entry window allows.

**Same-bar chaining is expected, not a bug**: the resolution block runs
*before* the entry-trigger blocks each bar, so if a trade's stop-out bar's
close also satisfies another signal's trigger, that signal fires the same
bar. For MID trades specifically this is the *common* case: since entry ≈
mid, stopping out away from entry means the close is, by construction,
already back on the opposite side of mid.

**Same-bar precedence**: a fresh, immediate trigger (BOL/BOS/FAL/FAS/MIDL/
MIDS closing through a level) is checked *before* wick-rejection
confirmations each bar, so an immediate signal always wins a same-bar race
against the laggier (two-bar) wick layer. Wick confirmations only look at
the *immediately preceding* bar's pending candidate — they're one-shot, not
held open waiting for a slot to free up.

### Why FAL/FAS specifically still cap at one per day
Unlike the other ten signals (gated purely by `not tradeLive`), FAL/FAS also
check `fa_done`, which only resets at the next day's range-end crossing.
This preserves the original Failed-Auction behavior exactly: it's a
second, dependent entry watching the opposite edge after a BOL/BOS stop-out,
not a general-purpose reversal signal, and only ever fires once per arming
cycle.

### Why BOL/BOS/FAL/FAS require the entry bar's OPEN inside the range, not just the close outside
`close > orHigh` alone is a *state* check (true on every subsequent bar while
price stays beyond the edge), not a *crossing* check. Once BOL/BOS lost their
daily cap (see above), that distinction became a real bug: a trending move
would keep re-triggering fresh entries bar after bar as each prior one
resolved, scattered far from the actual range edge, not clustered at it.
Fixed by requiring `open <= orHigh and close > orHigh` (mirrored for the
other three) — the entry bar must itself span the boundary, matching gotcha
#5's boundary-crossing principle applied to price instead of time. FAL/FAS
got the same fix for consistency even though `fa_done` already bounded the
practical impact. The wick-candidate conditions (`WHL`/`WLS` boundary
detection) are intentionally NOT changed — they're a different pattern
(wick-then-confirm, already bounded to a one-bar confirmation window) where
"currently beyond the level" is the expected precondition, not a bug.

### Why BOL/BOS have a "failure confirmation" stop on top of the ATR/quartile stop
A breakout is expected to hold beyond the range edge it broke through. If a
BOL/BOS trade hasn't by 2 bars after entry (`bar_index > curEbar + 1`), a
close back inside the range (`close < orHigh` for BOL, `close > orLow` for
BOS) now counts as a stop-out too — `failureConfirm`, OR'd into every
`hitS` check in the resolution block (all three Scale stages plus the
Full@100/Full@50 branch). This exists because the ATR/quartile stop can be
much wider than "did the breakout actually fail" — price can drift back
under the range high for several bars without ever tagging a stop that's
sized off ATR or a range quartile, quietly turning a failed breakout into a
slow bleed instead of a clean exit. Only applied to BOL/BOS (`curSlot == 0
or curSlot == 1`) — not the other 10 signals, since MID/wick entries are
already on the "inside" side of their trigger level by construction, so
"back inside the range" isn't a failure signal for them the way it is for a
breakout. This also means FAL/FAS now arm off a breakout that failed this
way, for free — FA arming is keyed off `curExitReason == 0` (any stop-out of
slot 0/1), not off a specific stop *type*, so no separate wiring was needed.
Ported to the ThinkOrSwim BOL strategy (`EvoD_BOL_Strategy_TOS.ts`) first,
then back-ported here for parity across platforms.

### Why stop uses candle body / wick-bar extreme, not the confirmation bar's body
`math.min(open, close)` = body bottom (long stop reference), mirrored for
shorts. For the six wick-rejection signals specifically, the reference is
the **wick bar's own high/low** (not the confirmation bar's body) — the
wick bar is what defines the rejection level; the confirmation bar just
proves it. Both feed the same `tighterStop()` function.

### Why every signal uses the tighter of body/wick-extreme ± ATR vs. a quartile cap
`tighterStop(isLong, refPrice, entryPrice, atrVal, atrMultV, rangeH)` picks
`math.max(bodyStop, quartileStop)` for longs / `math.min(...)` for shorts —
whichever is closer to entry:
- `bodyStop` = refPrice ± ATR14×mult
- `quartileStop` = entry ∓ rangeHeight×0.25

This guarantees the stop never exceeds one quartile of the range, so R/R to
the 50% target is never worse than 1:1 even when ATR is unusually wide
relative to the day's range. When the quartile cap is the one actually
chosen, the day's range box border turns amber instead of orange. All 12
signals use this same function — there's no longer a separate
`stopMode`/`computeStopSim` system with ATR/RangePct/Hybrid options; that
was retired in favor of one unified model.

### Why targets are still entry ± rangeHeight × {0.5, 1.0, 2.0} for every signal
Kept uniform rather than giving MID/wick signals their own structural
targets. For MID-anchored entries this naturally lands the first leg almost
exactly at the range edge already (entry≈mid, so `mid + 0.5×rng ≈ orHigh`) —
no special-casing needed.

### Why targets register on intrabar HIGH/LOW touch but reach-tracking is separate from the P&L exit
Targets touching (not requiring a close) is intentional — it credits the
move without requiring a close beyond the target. `curH1`/`curH2`/`curH3`
track whether each leg was ever touched, **independent of exitMode** — this
feeds the table's "Reach%" columns (a trade can touch T1 informationally
and still stop out on the remainder in Scale mode; both facts are recorded).
The actual realized P&L (`curPts`) is a separate calculation driven by
`exitMode` (Scale/Full@100/Full@50).

### Why `bar_index > curEbar` exists in resolution
The entry bar itself is excluded from stop/target resolution. Without this, a
large entry candle could immediately trigger the stop on the same bar it entered.

### Why Range Shape and Market are two separate pickers
Rather than enumerating combo presets ("NY ORB", "London IB", ...), Range
Shape (`IB`/`ORB`/`EvoD ORB`/`Futures Start 15min`/`Futures Start IB`/
`Custom`) and Market (`New York`/`London`/`Tokyo`) are independent inputs.
Shape defines the time offsets; Market defines which open those offsets are
relative to. The two Futures Start shapes ignore Market entirely — they're
fixed to the CME's own daily maintenance reopen (5:00 PM CT), which is a
CME-specific schedule, not an NY/London/Tokyo equity concept. `effectiveTz`
picks the right timezone for each case (see gotcha #9) so DST is handled
correctly via IANA timezone strings rather than fixed offsets.

**Known limitation**: the session math assumes the resulting range/entry
window stays within a single calendar day in the relevant timezone. This
always holds with the default `nHours=1.0`/`entryWindowHours=6.0`; a very
large `nHours` could push the range start across local midnight, which
isn't handled (same-day is the supported case).

### Why Sunday bars bucket as Monday for day-of-week stats
CME futures (and forex) reopen Sunday evening, and that session is
"Monday's" trading day, not a stray weekend bucket. `dowNow` maps
`dayofweek.sunday` to index 0 (same as Monday) — without this, any
Sunday-evening entry (relevant now that Futures Start shapes can begin then)
would silently misbucket into the Friday column, since the old mapping
defaulted anything that wasn't Mon–Thu to index 4.

### Why the old t1/t2 MFE-style tables were retired
They tracked "furthest target reached" without any real exit logic, which
overstates results (a trade touching 50% then reversing to the stop logged
as a win). Every signal now goes through the same real exit simulation
(entry → stop/target/scale-out → recorded outcome) into one consolidated
table, with reach-rate ("Reach%") columns preserving the old table's
touch-rate information alongside the real P&L numbers.

### Why the performance table's row count is computed from the enable toggles
`table.new()` needs its row count at creation time. `tableRows = 1 (header)
+ enabledCount + 1 (ALL) + 1 (footer)`, where `enabledCount` sums the 12
per-signal boolean inputs. Disabling a signal drops its row entirely instead
of showing a zeroed-out one. The ALL row always sums every slot regardless
of current toggle state, so toggling a signal off doesn't change historical
totals already recorded for it.

### Why visual elements use `xloc.bar_time` not `xloc.bar_index`
`bar_index` anchored objects shift when TradingView loads more historical
data (bar indices get reassigned). `xloc.bar_time` anchors to Unix
timestamps which never shift. All `line.new()`, `box.new()`, and
`label.new()` calls must use `xloc=xloc.bar_time` and pass `time` (not
`bar_index`) as the x coordinate.

### Why there's a `plot(close, "scale_anchor", ...)` at the bottom
Without any `plot()` call, TradingView gives the indicator its own price axis
independent of the candles. The transparent close plot forces the indicator to
share the candle price scale so labels and lines track candles vertically on scroll.

---

## Known Issues / To-Do List

### Pending features (not yet built)
1. **Backtest re-validation** — the "Qualified Instruments" table below
   reflects the *pre-rewrite* MFE-touch model (old S1/S2). The exit-sim
   engine, unified stop model, and new signal set (BOL/BOS/FAL/FAS/MIDL/
   MIDS + 6 wick signals) haven't been re-backtested against those numbers
   yet. Treat the win-rate table as historical context, not current truth,
   until re-run.
2. **Table width on smaller screens** — the consolidated table is 25 columns
   wide by design (one table, not three) per explicit user preference; worth
   revisiting if it's unreadable on a given screen size.
3. **Large `nHours` crossing local midnight** — see the "Known limitation"
   note under Range Shape/Market above.

### Previously attempted, reverted
- **Multi-timeframe (MTF) support** — attempted to force 5-min calculation on
  any chart TF using `request.security_lower_tf()`. Broke signal counts to zero
  even on native 5-min charts. Root cause unclear (possibly `isNativeTF` branch
  not short-circuiting correctly). Reverted entirely. The script is designed for
  5-min charts only.

---

## Range Shape / Market Reference

| Range Shape | Window | Uses Market picker? |
|---|---|---|
| IB | `[open, open+N hours]` | Yes |
| ORB | `[open−N hours, open]` | Yes |
| EvoD ORB | `[open+15min−N hours, open+15min]` | Yes |
| Futures Start 15min | `[CME reopen, +15min]` (fixed, CT) | No |
| Futures Start IB | `[CME reopen, +N hours]` (CT) | No |
| Custom | Manual HHMM, in the `tz` input | No |

Entry window for every non-Custom shape: `[rangeEnd, rangeEnd +
entryWindowHours]`, exit = end of that window (no separate timeout time).
Market opens: New York 9:30 AM ET, London 8:00 AM GMT/BST, Tokyo 9:00 AM JST.

**Extended hours:** ON for futures and IB-style shapes. OFF or ON for stocks
(ON required if the range start falls before 9:30 ET).

---

## Qualified Instruments (66%+ win rate threshold, Jun 2025–Jun 2026 backtest)

**⚠ Pre-rewrite data — see "Backtest re-validation" above.** These numbers
were measured against the old S1/S2 MFE-touch model, not the current
exit-simulation engine or the new signal set. Useful for historical
intuition about which instruments/days had edge; not a substitute for
re-running the new backtest.

| Instrument | Setup | Direction | Win Rate | Best Days | Notes |
|---|---|---|---|---|---|
| MGC (Gold micro) | S1 (→BOL/BOS) | SHORT | 71% / 75% Thu | Tue/Thu/Fri | Skip Mon/Wed |
| M2K (Russell micro) | S1 (→BOL/BOS) | LONG | 71% / 67% Thu | Thursday | Borderline other days |
| M6E (Euro micro) | All | All | 69% Tue / 67% Thu | Tue/Thu only | Fri 35% — avoid |
| MES (ES micro) | S1 (→BOL/BOS) | LONG | 61% | Any | Borderline; supplemental |
| MNQ (NQ micro) | — | — | 44% | — | NO EDGE — do not use |
| MYM (Dow micro) | — | — | 50% | — | NO EDGE — do not use |
| MCL (Crude micro) | — | — | No day ≥66% | — | Removed from plan |

**Day-of-week pattern (pre-rewrite):**
- Monday: dead (50–75% loss rate)
- Tuesday: qualified (MGC 67%, M6E 69%)
- Wednesday: dead (50–69% loss rate)
- Thursday: best day (MGC 75%, M2K 67%, M6E 67%)
- Friday: qualified (MGC 71%)

**⚠ SUPERSEDED as of Aug 4 2026 — see "Validated Trade-Log Results" below.**
A 546-trade export analyzed directly from `EvoD_Trader_TradeLog.pine`
contradicts this table on two counts: MNQ shows a clear positive edge (not
"NO EDGE"), and the day-of-week pattern is flat (not Monday-dead/
Thursday-best). The table above is pre-rewrite MFE-touch data on a
3.5-month 5-min window; the new results are exit-simulation data on 546
trades across 11 months. Prefer the new numbers.

---

## Validated Trade-Log Results (Aug 4 2026)

First analysis run on real per-trade data rather than aggregate table stats.
Source: `EvoD_Trader_TradeLog.pine` export, parsed and analyzed by
`tools/analyze_tradelog.py`.

**Config:** MNQ1!, 15-min, ORB (New York), N=0.25h, entry=6h, Scale exit,
filter OFF. 546 trades over 228 trading days, Sept 2025 – Aug 2026.

| | n | win% | avgW | avgL | expectancy | PF |
|---|---|---|---|---|---|---|
| ALL | 546 | 58.1% | +33.50 | −12.26 | +14.31 pts | 3.78 |
| BOL | 287 | 60.3% | +34.36 | −12.84 | +15.61 pts | 4.06 |
| BOS | 259 | 55.6% | +32.47 | −11.69 | +12.86 pts | 3.48 |

Chronological: +7,812 pts total, max drawdown 115.69 pts, worst losing
streak 7 trades.

### `exit_reason` is a mechanism label, NOT an outcome label
**135 of 363 `stop` exits (37%) are profitable**, worth +1,822 pts. Cause:
Scale mode banks 1/3 at T1 then moves the stop to breakeven, so the
remainder stopping out still nets positive. Any analysis that buckets by
`exit_reason` instead of the sign of `pts` will read this strategy as a
~30%-win-rate disaster. The Pine table was always correct (`curIsWin =
curPts > 0`); this trap only bites downstream consumers of the log. Strongly
suspected source of repeated misreadings in parallel analysis sessions.

### Day-of-week edge is flat — retire the old filter
Mon 57.3% / Tue 58.5% / Wed 63.1% / Thu 55.1% / Fri 56.0%. Within noise, and
Thursday is now the *worst* day, directly inverting the pre-rewrite table's
"Thursday best" claim. Do not filter by weekday on the old numbers.

### Entry extension past the range edge does NOT predict outcome
Bucketed by `entry_ext_pct` (0-25/25-50/50-100/100-200/200%+): win rates
57/64/54/61/54%, non-monotonic. Hypothesis was that late/extended entries
would underperform — they don't. No filter justified. (Extension is often
large by construction: at N=0.25h the range is one 15-min pre-open bar, and
the RTH-open bar routinely dwarfs it.)

### Cost robustness
Breakeven friction is 14.31 pts/trade ($28.62 round trip). At a realistic
2–4 pts (commissions + a tick or two, times Scale mode's extra fills),
PF stays 2.5–3.1 and expectancy +10 to +12 pts. Edge survives with margin.

### Loss clustering is mild
Win rate 54.4% after a loss vs 60.6% after a win. Block-bootstrap (resampling
whole trading days, preserving intra-day clustering) vs IID bootstrap barely
differ below 20 contracts; at 20 contracts clustering roughly doubles bust
risk (1.6% → 3.7%).

### ⚠ Two unmodeled risks — the results are optimistic until these are tested
1. **Entry fills at the signal bar's close.** You only know the bar closed
   beyond the range once it *has* closed, so that fill isn't achievable
   live — realistically you fill at the next bar's open, which on a momentum
   breakout is systematically worse. Not captured by the symmetric cost
   sweep above.
2. **"Breakeven" isn't free live.** Slippage turns many of the +0.00 exits
   into small losses — and those exits are exactly what produces the
   unusually smooth equity curve (68:1 return-to-drawdown, which is not what
   real strategies look like).

Fix for both: log the next bar's open alongside the close and re-run on
realistic fills. Until then treat the numbers as an upper bound.

---

## Backtest Sample-Size & Session-Timing Notes (Aug 2026)

Findings from reconciling a parallel Claude.ai analysis session against
this script's actual logic. Mechanics below are verified directly against
the code; specific win-rate/PF numbers from that session are not — treat
those as a lead to re-verify, not a validated result.

**TradingView's intraday calculation-bar limit is real but not precisely
verifiable from this script.** TradingView caps how many historical bars a
script can calculate over on intraday timeframes as a fixed *bar count*, so
shorter timeframes cover less calendar history (a 5-min chart's usable
lookback is shorter than a 15-min chart's). The parallel session's figures
(~3.5 months on 5-min, ~11 months on 15-min) are directionally consistent
with how this limit works, but the exact cutoff depends on plan tier and
the specific instrument's data feed, and isn't something the script itself
can report — check your own chart directly (scroll to the earliest bar
that actually gets a signal, or watch `bar_index` at the leftmost loaded
bar) rather than trusting a fixed number.

**Confirmed: ORB + New York + N=0.25h session timing**, verified against
MARKET/SESSION RESOLUTION ([EvoD_Trader_Range.pine:159-198](EvoD_Trader_Range.pine:159)):
`rangeStartM = marketOpenM(570) - nMin(15) = 555` (9:15 ET),
`rangeEndM = marketOpenM = 570` (9:30 ET), `entryStartM = rangeEndM = 570`.
On a 15-min chart this window is exactly one bar (9:15–9:30) — both
boundaries are multiples of 15 and align to the chart's bar grid, so this
is deterministic, not a coincidence of this particular dataset. The range
genuinely is a single pre-open bar's high/low, and the first entry-eligible
bar (9:30–9:45) tests whether that bar's own OHLC breaks it — confirming
the parallel session's read: *"did the first RTH bar break the last
pre-market bar's high/low."* This does NOT generalize to every N/timeframe
combination — if N isn't a multiple of the chart's bar size, or the
market-open boundary doesn't land on the bar grid, the range could span a
different or uneven number of bars.

**Why the Range Quality Filter "destroys" signal count at very small N —
structural, not a bug.** The filter compares `rangeHeight` against
`entryAtrToday`, which snapshots `ta.atr(atrLen)` — computed over the
*chart's own bars* ([EvoD_Trader_Range.pine:218](EvoD_Trader_Range.pine:218))
— at the moment the entry window opens. On a 15-min chart, ATR14 reflects
~3.5 hours of volatility. At N=0.25h, `rangeHeight` is just **one 15-min
bar's** high-low span. A single bar's range being ≥1.5–2.0× a 14-bar ATR is
structurally rare, so the filter is nearly incompatible with single-bar
range windows by construction — not "too strict," just measuring the wrong
thing at that N. When tuning N and the Filter together in a sweep, the
filter multiplier needs to scale with N (or be off entirely at very small
N), not stay fixed across every N tested.

**On exporting bar data via Pine Logs for a Python sweep: reconsider
before building this.** Two problems. First, a 1-min chart has *less*
usable calculation history under TradingView's bar-count cap than the
15-min chart already in use — exporting from 1-min bars shrinks the
available window, it doesn't extend it. Second, Pine's log panel isn't
built for bulk export — months of 1-min OHLCV is 100,000+ rows, far beyond
what `log.info()`/the Pine Logs panel can hold or let you copy in one
piece (see the existing CSV-export mechanism's own scale, which tops out at
a ~25-row table, not raw bar data). A dedicated OHLCV source outside Pine
entirely — a broker/data API, a data vendor, or Tradovate's own historical
data — is a more direct path to a real Python sweep than round-tripping
through Pine Logs.

---

## Account Context

**Current: two Legacy 25K accounts**, each with a $1,500 trailing drawdown.
- Daily loss limit: $200, enforced at the platform level in Tradovate (a
  hard stop, not self-imposed)
- Daily profit cap: $400 (consistency-rule protection)
- Starting size: 3 MNQ micros — deliberately conservative
- Prior **Apex 25K Performance Account** was blown via revenge trading; kept
  below as historical reference for the risk-rule structure, not a live
  account

**Prior Apex 25K Performance Account (historical reference):**
- Profit target: $26,600
- Trailing drawdown: $1,000 EOD
- Daily loss limit (self-imposed): $150
- Daily profit cap (self-imposed): $300 (consistency rule: no day > 40% of total)
- Max contracts: 1 MES mini / 10 micros
- MGC fits larger accounts (Tradeify 150K) — stop too large for 25K
- MNQ: "proven negative edge, never trade" — per the pre-rewrite Qualified
  Instruments table above; see the Aug 2026 note there questioning this
  under the new engine

---

## Script Structure (EvoD_Trader_Range.pine)

Sections in order:
1. `indicator()` declaration
2. INPUTS (Date Range, Session/Custom, Range Shape/Market preset, Risk,
   Filters, Display, Signals enable toggles, Alerts, Exit Simulation)
3. `hm2min` helper
4. HOLIDAY EXCLUSION (US federal holidays hardcoded)
5. MARKET / SESSION RESOLUTION (effectiveTz, barTimeMinutes, rangeStartM/
   rangeEndM/entryStartM/entryEndM/exitM computed from Range Shape × Market,
   dowNow with the Sunday→Monday mapping, `tighterStop()`)
6. RANGE CALCULATION (orHigh, orLow, mid, rangeSet, isFirstRangeBar, range
   quality filter)
7. RANGE LINES + ZONE BOXES (orange range, blue entry, dashed splits +
   left-side price labels, extensions, range-size label)
8. STATS ACCUMULATORS (`cs_*` size-12 setup axis, `cx_*` size-60
   signal×weekday cross-tab, `ov_*` overall running sequence)
9. LIVE TRADE STATE (single `cur*` scalar set — see "Why only one trade can
   be live" above), FA arming state, pending-wick-candidate state
10. DAILY RESET
11. RESOLUTION (reach-tracking + Scale/Full exit mechanics + timeout +
    record outcome into `cs_*`/`cx_*`/`ov_*` + arm FA)
12. Shared entry gate (`canEnter`), `slotName()` helper
13. BOL / BOS entries
14. FAL / FAS entries
15. MIDL / MIDS entries
16. Wick-rejection confirmations (6 blocks, using prior-bar pending state)
17. New wick-candidate detection (sets pending state for next bar)
18. TABLE (one consolidated table, rows = enabled signals + ALL)
19. Scale anchor plot

---

## Testing Checklist After Any Change

Before committing changes, verify on TradingView:
- [ ] Compiles without errors on Pine v6
- [ ] BOL/BOS fire roughly where S1 LONG/SHORT used to on MES 5-min (trigger
      logic is unchanged, only the engine/naming changed)
- [ ] Table columns are internally consistent: Reach% is non-increasing
      (T1 ≥ T2 ≥ Final), day-of-week W+L per row roughly equals that row's
      Trades count
- [ ] Range box border turns amber (not orange) on days where the quartile
      stop cap is tighter than body/wick+ATR; entry labels show a matching
      `ST:` distance ≤ 25% of that day's range height, plus a tick count
- [ ] Range size (points) label appears in the lower-right corner of each
      range box; price labels appear at the left of the q1/mid/q3 and
      50/100/200% lines
- [ ] Labels/lines track with candles when scrolling (time-anchored)
- [ ] Range Shape × Market combinations draw range boxes at the times you'd
      expect for each market's real open (spot-check NY, London, Tokyo), and
      the two Futures Start shapes anchor to 5:00 PM CT regardless of Market
- [ ] Works on AAPL 5-min chart with extended hours ON and New York market
- [ ] Works on a forex pair (e.g. EURUSD) — session times still resolve
      sanely even though "market open" is a looser concept there
- [ ] Only one trade is ever live at a time — spot-check a busy day's
      timestamps for overlaps
- [ ] FAL/FAS and MIDL/MIDS follow-ups can fire on the identical bar as the
      stop-out that armed them (expected, not a bug)
- [ ] Wick-rejection signals: manually verify a few on the chart against the
      2-bar wick-then-confirm pattern before trusting the backtest numbers
- [ ] Toggling a signal off in Signals removes its row from the table
      entirely (not just zeros it out)
