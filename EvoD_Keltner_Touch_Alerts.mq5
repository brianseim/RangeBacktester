//+------------------------------------------------------------------+
//| EvoD_Keltner_Touch_Alerts.mq5                                    |
//| MT5 port of EvoD_Keltner_Touch_Alerts.pine                       |
//|                                                                  |
//| Dual-multiplier Keltner channels (inner/outer) off one basis,    |
//| with per-band touch detection and alerts.                        |
//|                                                                  |
//| PARITY NOTE: this deliberately does NOT call iATR(). MetaTrader  |
//| averages true range with a SIMPLE moving average, while Pine's   |
//| ta.atr() uses Wilder RMA. Calling iATR would put the bands in a  |
//| visibly different place from the TradingView version, so the RMA |
//| is computed here instead. Same reason the EMA is hand-rolled     |
//| rather than delegated to iMA: Pine seeds ta.ema with an SMA of   |
//| the first `length` values, and the seeding has to match too.     |
//+------------------------------------------------------------------+
#property copyright "EvoD Trader"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 19
#property indicator_plots   11

//--- plot / buffer map ---------------------------------------------
// 0,1   upper zone fill       2,3   lower zone fill
// 4     upper outer line      5     upper inner line      6  basis
// 7     lower inner line      8     lower outer line
// 9-12  touch markers         13    rangema               14 true range
// 15-18 armed flags (calculation buffers, not plotted)

enum ENUM_BANDS_STYLE
  {
   BANDS_ATR,        // Average True Range
   BANDS_TR,         // True Range
   BANDS_RANGE       // Range
  };

enum ENUM_TOUCH_MODE
  {
   TOUCH_WICK,       // Wick (high/low)
   TOUCH_CLOSE       // Close
  };

//--- Keltner inputs (defaults match the Pine version) ---------------
input int                InpLength       = 13;           // Length
input double             InpMultInner    = 3.0;          // Multiplier - inner
input double             InpMultOuter    = 4.0;          // Multiplier - outer
input ENUM_APPLIED_PRICE InpAppliedPrice = PRICE_CLOSE;  // Source
input bool               InpUseEMA       = true;         // Use Exponential MA
input ENUM_BANDS_STYLE   InpBandsStyle   = BANDS_ATR;    // Bands Style
input int                InpAtrLength    = 10;           // ATR Length

//--- touch alerts ---------------------------------------------------
input ENUM_TOUCH_MODE    InpTouchMode    = TOUCH_WICK;   // Touch definition
input double             InpTolPct       = 0.0;          // Tolerance (% of band width)
input bool               InpReArm        = true;         // First touch only (re-arm after price leaves)
input bool               InpShowMarks    = true;         // Mark touches on chart

//--- notification channels -----------------------------------------
input bool               InpAlertPopup   = true;         // Alert() popup on terminal
input bool               InpAlertPush    = false;        // Push to MetaTrader mobile app
input bool               InpAlertEmail   = false;        // Send email
input bool               InpAlertInner   = true;         // Alert on inner band touches
input bool               InpAlertOuter   = true;         // Alert on outer band touches

//--- colors, as 0xBBGGRR. MT5 indicator plots have no alpha channel,
//--- so the Pine version 90%-transparent fills are approximated with
//--- dark muted shades that read similarly against a dark chart.
input color              InpColUp        = 0x4536F2;     // Upper band color
input color              InpColDn        = 0x819908;     // Lower band color
input color              InpColBasis     = 0x3BEBFF;     // Basis color
input color              InpFillUp       = 0x161230;     // Upper zone fill
input color              InpFillDn       = 0x212608;     // Lower zone fill
input int                InpArrowInner   = 110;          // Wingdings code, inner touch
input int                InpArrowOuter   = 159;          // Wingdings code, outer touch

//--- buffers --------------------------------------------------------
double BufUpFillA[], BufUpFillB[], BufDnFillA[], BufDnFillB[];
double BufUpOut[], BufUpIn[], BufBasis[], BufDnIn[], BufDnOut[];
double BufMarkUpIn[], BufMarkUpOut[], BufMarkDnIn[], BufMarkDnOut[];
double BufRange[], BufTR[];
double BufArmUpIn[], BufArmUpOut[], BufArmDnIn[], BufArmDnOut[];

//--- multipliers sorted, so inner/outer stay truthful whichever way
//--- round the two inputs are typed (mirrors the Pine min/max).
double   g_multIn, g_multOut;
int      g_maPeriod, g_rangePeriod, g_warmup;
datetime g_lastAlertBar = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpLength < 1 || InpAtrLength < 1)
     {
      Print("EvoD KC: Length and ATR Length must be >= 1");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpMultInner <= 0.0 || InpMultOuter <= 0.0)
     {
      Print("EvoD KC: multipliers must be greater than 0");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_multIn  = MathMin(InpMultInner, InpMultOuter);
   g_multOut = MathMax(InpMultInner, InpMultOuter);

   g_maPeriod    = InpLength;
   g_rangePeriod = (InpBandsStyle == BANDS_ATR) ? InpAtrLength : InpLength;
   g_warmup      = MathMax(g_maPeriod, g_rangePeriod) + 1;

   SetIndexBuffer(0,  BufUpFillA,   INDICATOR_DATA);
   SetIndexBuffer(1,  BufUpFillB,   INDICATOR_DATA);
   SetIndexBuffer(2,  BufDnFillA,   INDICATOR_DATA);
   SetIndexBuffer(3,  BufDnFillB,   INDICATOR_DATA);
   SetIndexBuffer(4,  BufUpOut,     INDICATOR_DATA);
   SetIndexBuffer(5,  BufUpIn,      INDICATOR_DATA);
   SetIndexBuffer(6,  BufBasis,     INDICATOR_DATA);
   SetIndexBuffer(7,  BufDnIn,      INDICATOR_DATA);
   SetIndexBuffer(8,  BufDnOut,     INDICATOR_DATA);
   SetIndexBuffer(9,  BufMarkUpIn,  INDICATOR_DATA);
   SetIndexBuffer(10, BufMarkUpOut, INDICATOR_DATA);
   SetIndexBuffer(11, BufMarkDnIn,  INDICATOR_DATA);
   SetIndexBuffer(12, BufMarkDnOut, INDICATOR_DATA);
   SetIndexBuffer(13, BufRange,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(14, BufTR,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(15, BufArmUpIn,   INDICATOR_CALCULATIONS);
   SetIndexBuffer(16, BufArmUpOut,  INDICATOR_CALCULATIONS);
   SetIndexBuffer(17, BufArmDnIn,   INDICATOR_CALCULATIONS);
   SetIndexBuffer(18, BufArmDnOut,  INDICATOR_CALCULATIONS);

   //--- zone fills (plots 0 and 1) ----------------------------------
   PlotIndexSetInteger(0, PLOT_DRAW_TYPE, DRAW_FILLING);
   PlotIndexSetInteger(0, PLOT_LINE_COLOR, 0, InpFillUp);
   PlotIndexSetInteger(0, PLOT_LINE_COLOR, 1, InpFillUp);
   PlotIndexSetString(0, PLOT_LABEL, "Upper channel");

   PlotIndexSetInteger(1, PLOT_DRAW_TYPE, DRAW_FILLING);
   PlotIndexSetInteger(1, PLOT_LINE_COLOR, 0, InpFillDn);
   PlotIndexSetInteger(1, PLOT_LINE_COLOR, 1, InpFillDn);
   PlotIndexSetString(1, PLOT_LABEL, "Lower channel");

   //--- band lines. Outer solid, inner dashed. MT5 renders real
   //--- dashes natively through PLOT_LINE_STYLE, so none of the
   //--- gapped-series trickery the Pine version needed applies here.
   SetupLine(2, InpColUp,    STYLE_SOLID, "Upper outer");
   SetupLine(3, InpColUp,    STYLE_DASH,  "Upper inner");
   SetupLine(4, InpColBasis, STYLE_SOLID, "Basis");
   SetupLine(5, InpColDn,    STYLE_DASH,  "Lower inner");
   SetupLine(6, InpColDn,    STYLE_SOLID, "Lower outer");

   //--- touch markers -----------------------------------------------
   SetupArrow(7,  InpColUp, InpArrowInner, -1, "Inner upper touch");
   SetupArrow(8,  InpColUp, InpArrowOuter, -1, "Outer upper touch");
   SetupArrow(9,  InpColDn, InpArrowInner,  1, "Inner lower touch");
   SetupArrow(10, InpColDn, InpArrowOuter,  1, "Outer lower touch");

   IndicatorSetString(INDICATOR_SHORTNAME,
                      StringFormat("EvoD KC(%d, %.1f/%.1f)",
                                   InpLength, g_multIn, g_multOut));
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void SetupLine(const int plot, const color clr,
               const ENUM_LINE_STYLE style, const string label)
  {
   PlotIndexSetInteger(plot, PLOT_DRAW_TYPE, DRAW_LINE);
   PlotIndexSetInteger(plot, PLOT_LINE_COLOR, clr);
   PlotIndexSetInteger(plot, PLOT_LINE_STYLE, style);
   PlotIndexSetInteger(plot, PLOT_LINE_WIDTH, 1);
   PlotIndexSetString(plot, PLOT_LABEL, label);
   PlotIndexSetDouble(plot, PLOT_EMPTY_VALUE, EMPTY_VALUE);
  }

//+------------------------------------------------------------------+
void SetupArrow(const int plot, const color clr, const int code,
                const int vshift, const string label)
  {
   PlotIndexSetInteger(plot, PLOT_DRAW_TYPE, InpShowMarks ? DRAW_ARROW : DRAW_NONE);
   PlotIndexSetInteger(plot, PLOT_ARROW, code);
   PlotIndexSetInteger(plot, PLOT_ARROW_SHIFT, vshift * 10);
   PlotIndexSetInteger(plot, PLOT_LINE_COLOR, clr);
   PlotIndexSetString(plot, PLOT_LABEL, label);
   PlotIndexSetDouble(plot, PLOT_EMPTY_VALUE, EMPTY_VALUE);
  }

//+------------------------------------------------------------------+
//| Source price, mirroring the Pine `src` input.                    |
//| NOTE: PRICE_WEIGHTED is (H+L+2C)/4, which is NOT the same as the |
//| Pine ohlc4 option. Everything else maps one to one.              |
//+------------------------------------------------------------------+
double AppliedPrice(const int i, const double &o[], const double &h[],
                    const double &l[], const double &c[])
  {
   switch(InpAppliedPrice)
     {
      case PRICE_OPEN:     return(o[i]);
      case PRICE_HIGH:     return(h[i]);
      case PRICE_LOW:      return(l[i]);
      case PRICE_MEDIAN:   return((h[i] + l[i]) / 2.0);
      case PRICE_TYPICAL:  return((h[i] + l[i] + c[i]) / 3.0);
      case PRICE_WEIGHTED: return((h[i] + l[i] + 2.0 * c[i]) / 4.0);
      default:             return(c[i]);
     }
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total < g_warmup + 2)
      return(0);

   // The recursive series (Wilder RMA, EMA) need the previous bar
   // value, so a recalculation restarts one bar back rather than
   // exactly at prev_calculated.
   int start = (prev_calculated > 1) ? prev_calculated - 1 : 0;

   for(int i = start; i < rates_total; i++)
     {
      //--- true range -----------------------------------------------
      // Pine ta.tr(true) falls back to high-low on the very first bar,
      // where there is no previous close to compare against.
      if(i == 0)
         BufTR[i] = high[i] - low[i];
      else
         BufTR[i] = MathMax(high[i] - low[i],
                            MathMax(MathAbs(high[i] - close[i - 1]),
                                    MathAbs(low[i] - close[i - 1])));

      //--- rangema: ATR / True Range / Range ------------------------
      if(InpBandsStyle == BANDS_TR)
         BufRange[i] = BufTR[i];
      else
        {
         int    per = g_rangePeriod;
         double src = (InpBandsStyle == BANDS_ATR) ? BufTR[i] : (high[i] - low[i]);

         if(i < per - 1)
            BufRange[i] = 0.0;
         else if(i == per - 1)
           {
            // Wilder RMA seeds with a simple average of the first
            // `per` values, exactly as Pine ta.rma does.
            double sum = 0.0;
            for(int k = 0; k < per; k++)
               sum += (InpBandsStyle == BANDS_ATR) ? BufTR[k] : (high[k] - low[k]);
            BufRange[i] = sum / per;
           }
         else
            BufRange[i] = (BufRange[i - 1] * (per - 1) + src) / per;
        }

      //--- basis ----------------------------------------------------
      if(i < g_maPeriod - 1)
         BufBasis[i] = EMPTY_VALUE;
      else
        {
         bool needSeed = (!InpUseEMA
                          || i == g_maPeriod - 1
                          || BufBasis[i - 1] == EMPTY_VALUE);
         if(needSeed)
           {
            double sum = 0.0;
            for(int k = i - g_maPeriod + 1; k <= i; k++)
               sum += AppliedPrice(k, open, high, low, close);
            BufBasis[i] = sum / g_maPeriod;
           }
         else
           {
            double alpha = 2.0 / (g_maPeriod + 1.0);
            BufBasis[i] = alpha * AppliedPrice(i, open, high, low, close)
                          + (1.0 - alpha) * BufBasis[i - 1];
           }
        }

      //--- bands ----------------------------------------------------
      if(BufBasis[i] == EMPTY_VALUE || i < g_warmup)
        {
         BufUpOut[i]     = EMPTY_VALUE;  BufUpIn[i]      = EMPTY_VALUE;
         BufDnIn[i]      = EMPTY_VALUE;  BufDnOut[i]     = EMPTY_VALUE;
         BufUpFillA[i]   = EMPTY_VALUE;  BufUpFillB[i]   = EMPTY_VALUE;
         BufDnFillA[i]   = EMPTY_VALUE;  BufDnFillB[i]   = EMPTY_VALUE;
         BufMarkUpIn[i]  = EMPTY_VALUE;  BufMarkUpOut[i] = EMPTY_VALUE;
         BufMarkDnIn[i]  = EMPTY_VALUE;  BufMarkDnOut[i] = EMPTY_VALUE;
         BufArmUpIn[i]   = 1.0;          BufArmUpOut[i]  = 1.0;
         BufArmDnIn[i]   = 1.0;          BufArmDnOut[i]  = 1.0;
         continue;
        }

      double ma = BufBasis[i];
      double rm = BufRange[i];
      BufUpIn[i]  = ma + rm * g_multIn;
      BufUpOut[i] = ma + rm * g_multOut;
      BufDnIn[i]  = ma - rm * g_multIn;
      BufDnOut[i] = ma - rm * g_multOut;

      BufUpFillA[i] = BufUpOut[i];  BufUpFillB[i] = BufUpIn[i];
      BufDnFillA[i] = BufDnIn[i];   BufDnFillB[i] = BufDnOut[i];

      //--- touch detection ------------------------------------------
      // Tolerance is a fraction of each band OWN basis-to-band
      // distance, so it scales with volatility and is proportionally
      // the same on both bands rather than a fixed point value.
      double tolIn  = rm * g_multIn  * InpTolPct / 100.0;
      double tolOut = rm * g_multOut * InpTolPct / 100.0;
      double upRef  = (InpTouchMode == TOUCH_CLOSE) ? close[i] : high[i];
      double loRef  = (InpTouchMode == TOUCH_CLOSE) ? close[i] : low[i];

      bool rawUpIn  = (upRef >= BufUpIn[i]  - tolIn);
      bool rawUpOut = (upRef >= BufUpOut[i] - tolOut);
      bool rawDnIn  = (loRef <= BufDnIn[i]  + tolIn);
      bool rawDnOut = (loRef <= BufDnOut[i] + tolOut);

      // Armed state is read from the PREVIOUS bar and written for this
      // one, so the first touching bar of a run is the one that fires.
      // Kept in buffers rather than statics so that recalculating the
      // same bars reproduces identical results.
      bool armUpIn  = (i > 0) ? (BufArmUpIn[i - 1]  != 0.0) : true;
      bool armUpOut = (i > 0) ? (BufArmUpOut[i - 1] != 0.0) : true;
      bool armDnIn  = (i > 0) ? (BufArmDnIn[i - 1]  != 0.0) : true;
      bool armDnOut = (i > 0) ? (BufArmDnOut[i - 1] != 0.0) : true;

      bool upInTouch  = rawUpIn  && (!InpReArm || armUpIn);
      bool upOutTouch = rawUpOut && (!InpReArm || armUpOut);
      bool dnInTouch  = rawDnIn  && (!InpReArm || armDnIn);
      bool dnOutTouch = rawDnOut && (!InpReArm || armDnOut);

      BufArmUpIn[i]  = rawUpIn  ? 0.0 : 1.0;
      BufArmUpOut[i] = rawUpOut ? 0.0 : 1.0;
      BufArmDnIn[i]  = rawDnIn  ? 0.0 : 1.0;
      BufArmDnOut[i] = rawDnOut ? 0.0 : 1.0;

      //--- markers. A bar that tags the outer band suppresses its own
      //--- inner marker, so there is one mark per side per bar.
      BufMarkUpIn[i]  = (upInTouch && !upOutTouch) ? high[i] : EMPTY_VALUE;
      BufMarkUpOut[i] = upOutTouch                 ? high[i] : EMPTY_VALUE;
      BufMarkDnIn[i]  = (dnInTouch && !dnOutTouch) ? low[i]  : EMPTY_VALUE;
      BufMarkDnOut[i] = dnOutTouch                 ? low[i]  : EMPTY_VALUE;
     }

   //--- alerts: last CLOSED bar only, at most once per bar -----------
   // prev_calculated == 0 means a full history rebuild (attach,
   // timeframe change, reconnect). Alerting there would fire once for
   // every historical touch at the same instant.
   if(prev_calculated == 0 && rates_total > 1)
     {
      // Seed the latch on the first full pass so the next tick does not
      // re-alert the most recent historical bar as if it were new.
      g_lastAlertBar = time[rates_total - 2];
     }
   else if(prev_calculated > 0 && rates_total > 1)
     {
      int last = rates_total - 2;
      if(last >= 0 && time[last] != g_lastAlertBar)
        {
         g_lastAlertBar = time[last];

         if(InpAlertOuter && BufMarkUpOut[last] != EMPTY_VALUE)
            FireAlert("OUTER UPPER", g_multOut, BufUpOut[last], close[last]);
         else if(InpAlertInner && BufMarkUpIn[last] != EMPTY_VALUE)
            FireAlert("INNER UPPER", g_multIn, BufUpIn[last], close[last]);

         if(InpAlertOuter && BufMarkDnOut[last] != EMPTY_VALUE)
            FireAlert("OUTER LOWER", g_multOut, BufDnOut[last], close[last]);
         else if(InpAlertInner && BufMarkDnIn[last] != EMPTY_VALUE)
            FireAlert("INNER LOWER", g_multIn, BufDnIn[last], close[last]);
        }
     }

   return(rates_total);
  }

//+------------------------------------------------------------------+
void FireAlert(const string band, const double mult,
               const double level, const double px)
  {
   string msg = StringFormat("KC %s (%.1fx) touched on %s %s @ %s (price %s)",
                             band, mult, _Symbol,
                             EnumToString((ENUM_TIMEFRAMES)_Period),
                             DoubleToString(level, _Digits),
                             DoubleToString(px, _Digits));
   if(InpAlertPopup)
      Alert(msg);
   if(InpAlertPush)
      SendNotification(msg);
   if(InpAlertEmail)
      SendMail("EvoD KC touch alert", msg);
  }
//+------------------------------------------------------------------+
