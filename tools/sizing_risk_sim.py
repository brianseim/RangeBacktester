"""
Position-size risk simulator for trailing-drawdown eval/funded accounts.

Answers the question the Pine table can't: given a strategy's win rate and
average win/loss, and an account's trailing-drawdown mechanics, what is the
probability of busting at each contract size?

The Pine indicator reports MaxDD as a single historical number -- the worst
run that happened to occur in one particular sequence. That understates risk:
the same trades in a different order produce a different worst run. This
reshuffles thousands of alternate sequences to get a distribution instead.

NOT a prediction. Garbage in, garbage out -- the output is only as good as the
win-rate/avg-win/avg-loss inputs, which come from a finite backtest sample.
See "SAMPLE SIZE" note at the bottom of the output.
"""

import random

# ----------------------------------------------------------------------
# ACCOUNT (edit these)
# ----------------------------------------------------------------------
START_BALANCE   = 251_104.0
TRAIL_DRAWDOWN  = 6_500.0     # full trailing allowance
CURRENT_FLOOR   = 247_500.0   # today's actual liquidation floor (~$3.6k room)
POINT_VALUE     = 2.0         # MNQ = $2/point
PROFIT_TARGET   = 265_000.0

# ----------------------------------------------------------------------
# STRATEGY PROFILES (from the indicator's own exports)
# ----------------------------------------------------------------------
PROFILES = {
    # 230-trade BOL sample -- largest sample available, most trustworthy
    "BOL 230-trade":  dict(p_win=0.63, avg_win=33.89, avg_loss=12.75),
    # 13-trade combined week -- tiny sample, wide error bars, shown for contrast
    "ALL 13-trade":   dict(p_win=0.54, avg_win=69.27, avg_loss=20.95),
}

TRADES_PER_DAY = 2.6          # ~13 trades/week from the recent export
HORIZON_DAYS   = 20           # ~4 trading weeks
N_PATHS        = 20_000


def draw_trade(rng, p_win, avg_win, avg_loss):
    """
    One trade's P&L in points, WITH realistic dispersion.

    An earlier version of this used fixed +avg_win / -avg_loss point masses.
    That produced ~0% bust probability at every size -- which is provably
    wrong: the real 13-trade sample showed a 96.56pt drawdown, and a model
    that can't reproduce that is useless for sizing. Variance is where busts
    come from, so it has to be modeled.

    Wins: exponential. A scale-out strategy has a long right tail (runners to
    T3) and many small wins (T1-only, or breakeven-stopped remainder). The
    indicator's own reach data supports this -- 80% reach T1 but only 33%
    reach the final leg, so most wins are partial.

    Losses: clustered near the stop (that's what a stop does) but with a
    right tail for gap-throughs and slippage past the stop level.
    """
    if rng.random() < p_win:
        return rng.expovariate(1.0 / avg_win)
    # 0.85-1.15x the nominal stop normally; occasional overshoot past it
    mult = rng.uniform(0.85, 1.15)
    if rng.random() < 0.08:            # ~8% of losses gap/slip beyond the stop
        mult *= rng.uniform(1.5, 3.0)
    return -avg_loss * mult


def simulate(p_win, avg_win, avg_loss, contracts, n_trades, seed_offset=0):
    """One path. Returns (breached, hit_target, ending_balance)."""
    rng = random.Random(1234 + seed_offset)
    balance = START_BALANCE
    hwm = START_BALANCE
    floor = CURRENT_FLOOR

    for _ in range(n_trades):
        pts = draw_trade(rng, p_win, avg_win, avg_loss)
        balance += pts * POINT_VALUE * contracts

        if balance > hwm:                       # trailing floor follows new highs
            hwm = balance
            floor = max(floor, hwm - TRAIL_DRAWDOWN)

        if balance <= floor:
            return True, False, balance
        if balance >= PROFIT_TARGET:
            return False, True, balance

    return False, False, balance


def validate_against_observed():
    """
    Sanity check: can the model reproduce a drawdown like the one actually
    observed? The real 13-trade export showed MaxDD = 96.56 points. If
    simulated 13-trade sequences never get near that, the model's variance is
    too low and every bust probability it reports is optimistic garbage.
    """
    OBSERVED_MAXDD_PTS = 96.56
    OBSERVED_N = 13
    prof = PROFILES["ALL 13-trade"]

    maxdds = []
    for i in range(20_000):
        rng = random.Random(99_000 + i)
        eq = peak = 0.0
        worst = 0.0
        for _ in range(OBSERVED_N):
            eq += draw_trade(rng, **prof)
            peak = max(peak, eq)
            worst = max(worst, peak - eq)
        maxdds.append(worst)

    maxdds.sort()
    median = maxdds[len(maxdds) // 2]
    p90 = maxdds[int(len(maxdds) * 0.90)]
    pct_at_least = sum(d >= OBSERVED_MAXDD_PTS for d in maxdds) / len(maxdds)

    print(f"\n{'=' * 72}")
    print("MODEL VALIDATION vs. observed data")
    print(f"{'=' * 72}")
    print(f"Observed MaxDD over {OBSERVED_N} real trades: {OBSERVED_MAXDD_PTS:.2f} pts")
    print(f"Simulated {OBSERVED_N}-trade MaxDD:  median {median:.1f} pts, "
          f"90th pct {p90:.1f} pts")
    print(f"Share of simulated runs >= observed: {pct_at_least:.1%}")
    if pct_at_least < 0.05:
        print("  --> MODEL VARIANCE TOO LOW. Bust probabilities below are")
        print("      understated. Do not size off them.")
    else:
        print("  --> Observed drawdown sits inside the model's normal range.")


def run():
    validate_against_observed()
    n_trades = int(TRADES_PER_DAY * HORIZON_DAYS)
    print(f"Horizon: {HORIZON_DAYS} trading days (~{n_trades} trades)")
    print(f"Start ${START_BALANCE:,.0f} | floor ${CURRENT_FLOOR:,.0f} "
          f"(${START_BALANCE - CURRENT_FLOOR:,.0f} room) | target ${PROFIT_TARGET:,.0f}")

    for name, prof in PROFILES.items():
        exp_pts = prof["p_win"] * prof["avg_win"] - (1 - prof["p_win"]) * prof["avg_loss"]
        print(f"\n{'=' * 72}")
        print(f"{name}  |  {prof['p_win']:.0%} win, "
              f"+{prof['avg_win']:.2f} / -{prof['avg_loss']:.2f} pts, "
              f"expectancy {exp_pts:+.2f} pts/trade")
        print(f"{'=' * 72}")
        print(f"{'Size':>5} {'P(bust)':>9} {'P(target)':>10} "
              f"{'median end':>13} {'worst 5%':>12}")
        print("-" * 72)

        for contracts in (1, 2, 3, 5, 10, 20):
            busts = targets = 0
            endings = []
            for i in range(N_PATHS):
                b, t, end = simulate(**prof, contracts=contracts,
                                     n_trades=n_trades, seed_offset=i)
                busts += b
                targets += t
                endings.append(end)
            endings.sort()
            median = endings[len(endings) // 2]
            p05 = endings[len(endings) // 20]
            print(f"{contracts:>5} {busts / N_PATHS:>8.1%} {targets / N_PATHS:>9.1%} "
                  f"{median:>13,.0f} {p05:>12,.0f}")

    print(f"""
{'=' * 72}
ASSUMPTIONS -- read before acting on any of this
{'=' * 72}
* Win/loss magnitudes are drawn from assumed distributions (exponential for
  wins, stop-clustered with a gap tail for losses) -- NOT from real trade
  data, which the CSV export doesn't provide (it exports aggregates only).
  The shapes are plausible and validate against the one observed MaxDD, but
  one data point is weak validation.
* Trades are independent. If the strategy has losing clusters (correlated
  bad days), real bust rates are HIGHER than shown. This is the single
  biggest known gap -- range strategies plausibly do cluster losses on
  choppy/low-volatility days.
* Trailing floor modeled as pure trailing (follows every new high, never
  locks). Apex-style accounts often lock the floor once profit clears a
  threshold -- if so, real risk is somewhat lower than shown here.
* No slippage, commissions, or missed fills. All three make it worse.
* SAMPLE SIZE: the 13-trade profile is far too small to trust -- 4 winning
  trades drive its entire expectancy. It is included only to show how much
  the answer moves when the inputs are uncertain. The 230-trade profile is
  the more defensible one, and even that is a single instrument over a
  single window.
""")


if __name__ == "__main__":
    run()
