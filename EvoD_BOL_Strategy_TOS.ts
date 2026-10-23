#
# EvoD BOL Strategy — ThinkOrSwim (thinkScript), BOL signal only
#
# Ported from EvoD_Trader_Range.pine (TradingView Pine v6), scoped down to
# just the BOL (Break Out Long) signal so it can run as a real thinkScript
# STRATEGY — not a Study. Add it via ToS: Charts -> Studies -> Edit Studies
# -> Strategies tab -> New (not the Studies tab). Once attached, right-click
# the chart -> "Show Report" for TOS's native trade list / win rate / P&L /
# equity curve — that's the actual backtest output; this script doesn't try
# to reproduce Pine's table by hand.
#
# Why BOL only, why a Strategy not a Study: thinkScript Studies have no
# native concept of a trade or P&L — building that by hand for all 12
# signals (see EvoD_Trader_Range.pine's engine) would mean hand-duplicating
# a full stats accumulator set 12 times, since thinkScript also has no
# arrays. A Strategy sidesteps almost all of that: AddOrder() places real
# simulated fills, and ToS's built-in Strategy Report computes win rate/P&L/
# drawdown/equity curve natively. Starting with just BOL keeps the entry/
# exit logic small enough to trust without a local compiler to test against.
# Run this same script unmodified on MNQ, MES, MGC, MCL, M2K, and M6E/MYM
# charts to compare — position size and $ P&L will reflect each symbol's own
# tick value automatically since AddOrder trades real price levels.
#
# Platform notes carried over from the Study-port attempt:
# - Session math assumes Market = New York (9:30 AM open). thinkScript's
#   SecondsFromTime/GetDayOfWeek/GetYYYYMMDD run in the chart's exchange
#   time, not an arbitrary IANA zone the way Pine's hour(time,"...") does.
# - "Futures Start" shapes (CME 5:00pm reopen) assume exchange time for the
#   futures symbol is already Central — ToS's usual convention for CME
#   instruments, but verify on your own chart before trusting those shapes.
# - GetDayOfWeek()'s exact numbering (1=Sunday? 0=Sunday?) could not be
#   verified without a compiler — check TOS's Function Reference before
#   trusting the day-of-week logic if you extend this. (Not currently used
#   by this file — BOL doesn't need day-of-week — but noted in case you
#   extend this.)
# - Entry/exit gating uses GetQuantity() (current bar) and GetQuantity()[1]
#   (previous bar) to know whether a position is open, instead of a
#   hand-rolled "in trade" flag — see the long comment above trigBOL for why
#   (a hand-rolled version created a real circular dependency thinkScript's
#   compiler rejected). GetQuantity()'s exact same-bar timing (does it
#   reflect an order placed earlier in the SAME bar's evaluation, or only
#   settle on the next bar?) could not be verified without a compiler either
#   — this is the single highest-risk assumption in the file. Check the
#   VERIFY checklist at the bottom.
# - Not run against a live ToS chart before delivery. Treat as a first
#   draft: fix whatever the Script Editor's compiler flags, then work
#   through the VERIFY checklist at the bottom before trusting the Strategy
#   Report's numbers.
#

# ------------------------------------------------------------
# INPUTS
#
# NOTE: earlier drafts used `script hm2min {...}` / `script tighterStop
# {...}` helper blocks here (mirroring Pine's => functions). ToS's compiler
# rejected them ("Invalid statement: script") regardless of where in the
# file they were placed, and there was no way to isolate the exact cause
# without a working compiler to iterate against. Rather than keep guessing
# at script-block syntax one round-trip at a time, both are inlined below as
# plain `def`s instead — functionally identical, just written out at each
# use site instead of factored into a named helper.
# ------------------------------------------------------------
input rangeShape = {default ORB, IB, EvoDORB, FuturesStart15, FuturesStartIB, Custom};
input nHours = 1.0;
input entryWindowHours = 6.0;

input rangeStartHM = 845;
input rangeEndHM = 945;
input entryStartHM = 945;
input entryEndHM = 1030;
input exitHM = 1200;

input atrLen = 14;
input atrMult = 1.0;

input useHolidays = yes;
input minRangeATR = 1.5;

input startDateYYYYMMDD = 20240101;
input endDateYYYYMMDD = 20271231;

input exitMode = {default Scale, Full100, Full50};
input contractsPerLeg = 1;   # Scale mode trades 3x this (1 per leg); Full modes trade this exact size

# ------------------------------------------------------------
# SESSION / RANGE — New York only, see header note
# ------------------------------------------------------------
def isCustom = rangeShape == rangeShape.Custom;
def isFutures = rangeShape == rangeShape.FuturesStart15 or rangeShape == rangeShape.FuturesStartIB;

def barTimeMinutes = Floor(SecondsFromTime(0000) / 60);

def marketOpenM = 9 * 60 + 30;
def cmeReopenM  = 17 * 60;
def nMin        = Round(nHours * 60, 0);
def entryWinMin = Round(entryWindowHours * 60, 0);

# HHMM -> minutes-since-midnight, inlined per input (see NOTE above)
def rangeStartHMmin = Floor(rangeStartHM / 100) * 60 + rangeStartHM % 100;
def rangeEndHMmin   = Floor(rangeEndHM / 100) * 60 + rangeEndHM % 100;
def entryStartHMmin = Floor(entryStartHM / 100) * 60 + entryStartHM % 100;
def entryEndHMmin   = Floor(entryEndHM / 100) * 60 + entryEndHM % 100;
def exitHMmin       = Floor(exitHM / 100) * 60 + exitHM % 100;

def rangeStartM =
    if isCustom then rangeStartHMmin
    else if rangeShape == rangeShape.IB then marketOpenM
    else if rangeShape == rangeShape.ORB then marketOpenM - nMin
    else if rangeShape == rangeShape.EvoDORB then marketOpenM + 15 - nMin
    else if rangeShape == rangeShape.FuturesStart15 then cmeReopenM
    else cmeReopenM;

def rangeEndM =
    if isCustom then rangeEndHMmin
    else if rangeShape == rangeShape.IB then marketOpenM + nMin
    else if rangeShape == rangeShape.ORB then marketOpenM
    else if rangeShape == rangeShape.EvoDORB then marketOpenM + 15
    else if rangeShape == rangeShape.FuturesStart15 then cmeReopenM + 15
    else cmeReopenM + nMin;

def entryStartM = if isCustom then entryStartHMmin else rangeEndM;
def entryEndM   = if isCustom then entryEndHMmin   else rangeEndM + entryWinMin;
def exitM       = if isCustom then exitHMmin       else entryEndM;

def inRangeWindow = barTimeMinutes >= rangeStartM and barTimeMinutes < rangeEndM;
def entryWindow   = barTimeMinutes >= entryStartM and barTimeMinutes < entryEndM;

def barYMD = GetYYYYMMDD();
def inDateRange = barYMD >= startDateYYYYMMDD and barYMD <= endDateYYYYMMDD;

def hy = GetYear();
def hmo = GetMonth();
def hd = GetDayOfMonth(barYMD);
def isHol = useHolidays and (
    (hy == 2025 and hmo == 7  and hd == 4)  or
    (hy == 2025 and hmo == 9  and hd == 1)  or
    (hy == 2025 and hmo == 11 and hd == 11) or
    (hy == 2025 and hmo == 11 and hd == 27) or
    (hy == 2025 and hmo == 11 and hd == 28) or
    (hy == 2025 and hmo == 12 and hd == 25) or
    (hy == 2025 and hmo == 12 and hd == 26) or
    (hy == 2026 and hmo == 1  and hd == 1)  or
    (hy == 2026 and hmo == 1  and hd == 19) or
    (hy == 2026 and hmo == 2  and hd == 16) or
    (hy == 2026 and hmo == 4  and hd == 3)  or
    (hy == 2026 and hmo == 5  and hd == 25) or
    (hy == 2026 and hmo == 7  and hd == 3)  or
    (hy == 2026 and hmo == 9  and hd == 7)  or
    (hy == 2026 and hmo == 11 and hd == 11) or
    (hy == 2026 and hmo == 11 and hd == 26) or
    (hy == 2026 and hmo == 12 and hd == 25)
);
def validDay = inDateRange and !isHol;

def atr14 = WildersAverage(TrueRange(high, close, low), atrLen);

def isFirstRangeBar = inRangeWindow and (barTimeMinutes[1] < rangeStartM or barTimeMinutes[1] >= rangeEndM);

rec orHigh = if isFirstRangeBar then high else if inRangeWindow then Max(orHigh[1], high) else orHigh[1];
rec orLow  = if isFirstRangeBar then low  else if inRangeWindow then Min(orLow[1], low)   else orLow[1];

def dayResetPoint = barTimeMinutes >= rangeEndM and barTimeMinutes[1] < rangeEndM;
rec rangeSet = if dayResetPoint then 1 else if isFirstRangeBar then 0 else rangeSet[1];

def rangeHeight = orHigh - orLow;

rec entryAtrToday = if (barTimeMinutes >= entryStartM and barTimeMinutes[1] < entryStartM) then atr14 else entryAtrToday[1];
def rangeQualityOK = minRangeATR <= 0 or (rangeHeight >= minRangeATR * entryAtrToday);

def canEnterBase = rangeSet == 1 and entryWindow and validDay and rangeQualityOK;

# ------------------------------------------------------------
# BOL TRADE STATE — single signal, so no slot dispatch needed. Each rec is
# one self-contained per-bar formula: thinkScript has no mid-bar mutation
# (no Pine-style `:=` reassignment partway through a bar's script), so every
# way a variable can change has to be expressed as one formula rather than
# several sequential assignments.
# ------------------------------------------------------------
def bodyRefLong = Min(open, close);

# NOTE on this section's structure: thinkScript requires every name to be
# fully declared (with its formula) before ANYTHING else references it, even
# via a shifted [1]. The natural way to write this state machine — stage and
# the active stop level each need to know whether the OTHER "just advanced"
# this bar — creates a genuine cycle (stage needs the stop-hit check, which
# needs the active stop level, which needs to know whether stage just
# advanced). It can't be fixed by reordering alone. The fix: instead of a
# single mutable "current stop" rec, track the ORIGINAL entry stop and the
# breakeven level (entryPx) as two independent, order-safe recs, and derive
# "what's the active stop right now" as a plain expression of stage[1] —
# computed fresh each bar, not carried as its own rec — once stage is
# available. Also: trigBOL/liveNow use GetQuantity() (a strategy built-in
# tracking the real position ToS's engine is holding) instead of a
# hand-rolled "in trade" rec, since that hand-rolled version was the other
# half of the original cycle (entry needed to know "not already in a trade,"
# which needed to know "did the trade resolve," which needed the stop/stage
# recs, which needed to know about entry).
def trigBOL = canEnterBase and open <= orHigh and close > orHigh and GetQuantity() == 0;

# Tighter of body/wick-extreme +/- ATR vs. a quartile cap — long-only here
# (mirrors Pine's tighterStop(); see CLAUDE.md "Why every signal uses the
# tighter of body/wick-extreme +/- ATR vs. a quartile cap")
def bodyStopNew = bodyRefLong - atr14 * atrMult;
def qtrStopNew  = close - rangeHeight * 0.25;
def newStop = Max(bodyStopNew, qtrStopNew);

rec entryPx = if trigBOL then close else entryPx[1];
rec entryBarNum = if trigBOL then BarNumber() else entryBarNum[1];
rec entryStopOriginal = if trigBOL then newStop else entryStopOriginal[1];
rec t1 = if trigBOL then close + rangeHeight * 0.5 else t1[1];
rec t2 = if trigBOL then close + rangeHeight * 1.0 else t2[1];
rec t3 = if trigBOL then close + rangeHeight * 2.0 else t3[1];

def liveNow = GetQuantity()[1] != 0 and validDay and BarNumber() > entryBarNum[1];
def isScale = exitMode == exitMode.Scale;

def hitT1raw = liveNow and high >= t1[1];
def hitT2raw = liveNow and high >= t2[1];

# Failure confirmation: BOL is a breakout above the range high (orHigh). If
# it hasn't held after 2 bars in the trade (from the 2nd bar following entry
# onward), a close back below orHigh counts as a stop-out too — on top of,
# not instead of, the ATR/quartile stop. orHigh stays frozen at today's
# range high for the rest of the day once range-building ends, so this is a
# stable reference throughout the trade.
def barsSinceEntry = BarNumber() - entryBarNum[1];
def failureStopRaw = liveNow and barsSinceEntry >= 2 and close < orHigh;

# stage's own advance conditions are fully inlined here (not referencing a
# separately-named hitS/s0adv) — during stage 0 the active stop is always
# entryStopOriginal, during stage 1 it's always entryPx (breakeven); neither
# needs stage's own current-bar value, which is what breaks the cycle.
rec stage = if trigBOL then 0
    else if (liveNow and stage[1] == 0 and hitT1raw and close >= entryStopOriginal[1] and !failureStopRaw) then 1
    else if (liveNow and stage[1] == 1 and hitT2raw and close >= entryPx[1] and !failureStopRaw) then 2
    else stage[1];

# Active stop as of this bar, derived from stage[1] now that stage is safely
# declared — this replaces what would otherwise be a separate "current stop"
# rec (the other half of the original cycle).
def activeStop = if stage[1] == 0 then entryStopOriginal[1] else entryPx[1];

def tgtFull = if exitMode == exitMode.Full50 then t1[1] else t2[1];
def hitT3 = liveNow and high >= t3[1];
def hitTFull = liveNow and high >= tgtFull;
def hitS = liveNow and (close < activeStop or failureStopRaw);

def s0adv = liveNow and isScale and stage[1] == 0 and hitT1raw and !hitS;
def s1adv = liveNow and isScale and stage[1] == 1 and hitT2raw and !hitS;

def resolveStop = liveNow and hitS;
def resolveTgt = liveNow and (
    (isScale and stage[1] == 2 and hitT3 and !hitS) or
    (!isScale and hitTFull and !hitS)
);
def timeoutCross = barTimeMinutes >= exitM and barTimeMinutes[1] < exitM;
def resolveTimeout = liveNow and timeoutCross and !resolveStop and !resolveTgt;
def exitThisBar = resolveStop or resolveTgt or resolveTimeout;

# ------------------------------------------------------------
# ORDERS — this is what makes it a Strategy. TOS's Strategy Report (right-
# click chart -> Show Report once this is added as a Strategy, not a Study)
# computes win rate / P&L / drawdown / equity curve from these fills.
# ------------------------------------------------------------
def entryQty = if isScale then 3 * contractsPerLeg else contractsPerLeg;

AddOrder(OrderType.BUY_AUTO, trigBOL, close, entryQty, Color.CYAN, Color.CYAN, "BOL");

# Scale mode: two partial exits (1 leg each) at T1/T2 — the breakeven-stop
# move after T1 is reflected in `activeStop`/`stage` above, not in the order
# itself (this order just books the partial exit at that bar's close).
AddOrder(OrderType.SELL_AUTO, isScale and s0adv, close, contractsPerLeg, Color.GRAY, Color.GRAY, "T1");
AddOrder(OrderType.SELL_AUTO, isScale and s1adv, close, contractsPerLeg, Color.GRAY, Color.GRAY, "T2");

# Final exit — whatever's left when the trade actually resolves (stop, final
# target, or timeout). In Full100/Full50 mode this is the entire position.
def finalExitQty = if isScale then contractsPerLeg else entryQty;
AddOrder(OrderType.SELL_AUTO, exitThisBar, close, finalExitQty, Color.RED, Color.GREEN, "BOL exit");

# ------------------------------------------------------------
# VISUALS — range high/low while building + through the entry window, so you
# can eyeball entries against the actual range on the chart.
# ------------------------------------------------------------
plot RangeHigh = if inRangeWindow or entryWindow then orHigh else Double.NaN;
plot RangeLow  = if inRangeWindow or entryWindow then orLow  else Double.NaN;
RangeHigh.SetDefaultColor(Color.ORANGE);
RangeLow.SetDefaultColor(Color.ORANGE);
AddCloud(RangeHigh, RangeLow, Color.ORANGE, Color.ORANGE);

# ------------------------------------------------------------
# VERIFY BEFORE TRUSTING THE STRATEGY REPORT
# ------------------------------------------------------------
# - Entry timing: does BUY_AUTO actually fill at that bar's own close (as
#   coded), or at the next bar's open? Compare a handful of fills in the
#   Strategy Report against the chart's breakout bars.
# - GetQuantity()/GetQuantity()[1] gating: force a case where a breakout bar
#   immediately follows a still-open trade's resolution bar and confirm no
#   double-entry / no skipped entry.
# - Scale mode: confirm exactly 3 * contractsPerLeg fills on entry and the
#   three exits (T1 partial, T2 partial, final) sum back to that same size,
#   for a trade that actually reaches T3.
# - Breakeven stop: after a T1 partial in Scale mode, confirm a losing exit
#   on the remainder books ~0 points (entry price), not the original wider
#   ATR/quartile stop.
# - Failure confirmation: find a trade that closes back below orHigh on the
#   2nd+ bar after entry without tagging the ATR/quartile stop, and confirm
#   it exits there rather than riding to the wider stop.
# - Full100/Full50 modes: confirm a single full-size exit at the target or
#   stop, no partials.
# - Range/session times: spot-check the plotted RangeHigh/RangeLow box
#   against the instrument's actual New York session open for your Range
#   Shape setting.
# - Day-of-week/holiday logic isn't exercised by this BOL-only file (no
#   day-of-week stats here), so the GetDayOfWeek() numbering question from
#   the header notes doesn't block this version — only matters if you add
#   day-of-week breakdowns later.
