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
#   trusting the day-of-week logic if you extend this.
# - Not run against a live ToS chart before delivery. Treat as a first
#   draft: fix whatever the Script Editor's compiler flags, then sanity
#   check a handful of trades on the chart against the "VERIFY" checklist
#   at the bottom before trusting the Strategy Report's numbers.
#

# ------------------------------------------------------------
# INPUTS
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
# HELPER SCRIPTS (pure, no persistent state)
# ------------------------------------------------------------
script hm2min {
    input hm = 0;
    Floor(hm / 100) * 60 + hm % 100;
}

script tighterStop {
    input refPrice = 0.0;
    input entryPrice = 0.0;
    input atrVal = 0.0;
    input atrMultV = 0.0;
    input rangeH = 0.0;
    def bodyStop = refPrice - atrVal * atrMultV;
    def qtrStop  = entryPrice - rangeH * 0.25;
    plot result = Max(bodyStop, qtrStop);   # long-only: tighter = higher of the two
}

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

def rangeStartM =
    if isCustom then hm2min(rangeStartHM)
    else if rangeShape == rangeShape.IB then marketOpenM
    else if rangeShape == rangeShape.ORB then marketOpenM - nMin
    else if rangeShape == rangeShape.EvoDORB then marketOpenM + 15 - nMin
    else if rangeShape == rangeShape.FuturesStart15 then cmeReopenM
    else cmeReopenM;

def rangeEndM =
    if isCustom then hm2min(rangeEndHM)
    else if rangeShape == rangeShape.IB then marketOpenM + nMin
    else if rangeShape == rangeShape.ORB then marketOpenM
    else if rangeShape == rangeShape.EvoDORB then marketOpenM + 15
    else if rangeShape == rangeShape.FuturesStart15 then cmeReopenM + 15
    else cmeReopenM + nMin;

def entryStartM = if isCustom then hm2min(entryStartHM) else rangeEndM;
def entryEndM   = if isCustom then hm2min(entryEndHM)   else rangeEndM + entryWinMin;
def exitM       = if isCustom then hm2min(exitHM)       else entryEndM;

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
# one self-contained per-bar formula (thinkScript has no mid-bar mutation —
# see EvoD_Trader_Range_TOS.ts's header note #3 for why this shape is
# correct, not just a workaround).
# ------------------------------------------------------------
def bodyRefLong = Min(open, close);

def trigBOL = canEnterBase and open <= orHigh and close > orHigh and inTrade[1] == 0;

def newStop = tighterStop(bodyRefLong, close, atr14, atrMult, rangeHeight);

rec entryPx = if trigBOL then close else entryPx[1];
rec entryBarNum = if trigBOL then BarNumber() else entryBarNum[1];
rec t1 = if trigBOL then close + rangeHeight * 0.5 else t1[1];
rec t2 = if trigBOL then close + rangeHeight * 1.0 else t2[1];
rec t3 = if trigBOL then close + rangeHeight * 2.0 else t3[1];

def liveNow = inTrade[1] == 1 and validDay and BarNumber() > entryBarNum[1];
def isScale = exitMode == exitMode.Scale;
def tgtFull = if exitMode == exitMode.Full50 then t1[1] else t2[1];

def hitT1 = liveNow and high >= t1[1];
def hitT2 = liveNow and high >= t2[1];
def hitT3 = liveNow and high >= t3[1];
def hitTFull = liveNow and high >= tgtFull;

# Failure confirmation: BOL is a breakout above the range high (orHigh). If
# it hasn't held after 2 bars in the trade (i.e. from the 2nd bar following
# entry onward), a close back below orHigh counts as a stop-out too — on top
# of, not instead of, the ATR/quartile stop (stopPx). orHigh stays frozen at
# today's range high for the rest of the day once range-building ends, so
# this is a stable reference throughout the trade.
def barsSinceEntry = BarNumber() - entryBarNum[1];
def failureStop = liveNow and barsSinceEntry >= 2 and close < orHigh;
def hitS = liveNow and (close < stopPx[1] or failureStop);

def s0adv = liveNow and isScale and stage[1] == 0 and hitT1 and !hitS;
def s1adv = liveNow and isScale and stage[1] == 1 and hitT2 and !hitS;

rec stage = if trigBOL then 0 else if s0adv then 1 else if s1adv then 2 else stage[1];
rec stopPx = if trigBOL then newStop else if s0adv then entryPx[1] else stopPx[1];

def resolveStop = liveNow and hitS;
def resolveTgt = liveNow and (
    (isScale and stage[1] == 2 and hitT3 and !hitS) or
    (!isScale and hitTFull and !hitS)
);
def timeoutCross = barTimeMinutes >= exitM and barTimeMinutes[1] < exitM;
def resolveTimeout = liveNow and timeoutCross and !resolveStop and !resolveTgt;
def exitThisBar = resolveStop or resolveTgt or resolveTimeout;

rec inTrade = if trigBOL then 1 else if exitThisBar then 0 else inTrade[1];

# ------------------------------------------------------------
# ORDERS — this is what makes it a Strategy. TOS's Strategy Report (right-
# click chart -> Show Report once this is added as a Strategy, not a Study)
# computes win rate / P&L / drawdown / equity curve from these fills.
# ------------------------------------------------------------
def entryQty = if isScale then 3 * contractsPerLeg else contractsPerLeg;

AddOrder(OrderType.BUY_AUTO, trigBOL, close, entryQty, Color.CYAN, Color.CYAN, "BOL");

# Scale mode: two partial exits (1 leg each) at T1/T2, breakeven-stop already
# reflected in stopPx above.
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
