"""
Analyze a Pine Logs trade-log export from EvoD_Trader_TradeLog.pine.

Parses TradingView's Date,Message envelope (trade rows arrive in quoted
multi-line chunks), then reports:
  - exit_reason vs. actual P&L sign  (they are NOT the same thing)
  - true win/loss stats scored by P&L
  - chronological equity curve and real max drawdown
  - loss clustering: is a loss more likely right after a loss?
  - bootstrap bust probability per contract size, IID vs. block resampling

Usage:
    python tools/analyze_tradelog.py <pine-logs.csv> [contracts...]
"""

import csv
import random
import statistics
import sys
from collections import defaultdict

HEADER_SENTINEL = "idx,signal,dir,"
POINT_VALUE = 2.0          # MNQ
N_PATHS = 20_000


def parse(path):
    # A merged file from merge_tradelogs.py is already a clean CSV whose
    # first column is "idx"; a raw Pine Logs export is wrapped in a
    # Date,Message envelope. Detect which, so both work here.
    with open(path, newline="", encoding="utf-8-sig") as fh:
        first = next(csv.reader(fh), [])
    if first and first[0].strip() == "idx":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        return f"(merged file: {path}, {len(rows)} trades)", _coerce(rows)

    config, header, rows = None, None, []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 2:
                continue
            msg = rec[1].strip()
            if msg.startswith("TRADELOG_BEGIN"):
                if config is not None:
                    raise SystemExit(
                        "ERROR: file contains more than one TRADELOG_BEGIN.\n"
                        "Two different runs are mixed in this export — their\n"
                        "settings differ, so combining them is meaningless.\n"
                        "Clear the Pine Logs panel and re-export once."
                    )
                config = msg
                continue
            if msg.startswith("TRADELOG_END") or msg.startswith(HEADER_SENTINEL):
                if msg.startswith(HEADER_SENTINEL):
                    header = msg.split(",")
                continue
            for line in msg.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if header and len(parts) == len(header):
                    rows.append(dict(zip(header, parts)))
    return config, _coerce(rows)


def _coerce(rows):
    for r in rows:
        r["pts"] = float(r["pts"])
        r["ext"] = float(r["entry_ext_pct"])
        r["range_pts"] = float(r["range_pts"])
        r["atr_pts"] = float(r["atr_pts"])
        # Columns present only in the next-open / fixed-TP-SL export
        for opt in ("mfe_pts", "mae_pts", "fill_slip"):
            if opt in r:
                r[opt] = float(r[opt])
    return rows


def section(t):
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def main():
    src = sys.argv[1]
    sizes = [int(a) for a in sys.argv[2:]] or [1, 2, 3, 5, 10, 20]
    config, rows = parse(src)

    print(config)
    n = len(rows)
    if "n=" in config:
        claimed = int(config.split("n=")[1].split()[0])
        print(f"\nparsed {n} rows (header claims n={claimed})"
              + ("" if n == claimed else "   *** MISMATCH — export may be truncated ***"))
    else:
        print(f"\nparsed {n} rows")

    # ---- exit_reason vs P&L sign -------------------------------------
    section("exit_reason is a MECHANISM label, not an OUTCOME label")
    print(f"{'reason':>9} {'n':>5} {'profitable':>11} {'losing':>8} {'net pts':>12}")
    for reason in ("stop", "target", "timeout"):
        sub = [r for r in rows if r["exit_reason"] == reason]
        if not sub:
            continue
        pos = [r for r in sub if r["pts"] > 0]
        print(f"{reason:>9} {len(sub):>5} {len(pos):>11} {len(sub) - len(pos):>8} "
              f"{sum(r['pts'] for r in sub):>+12.2f}")
    stops = [r for r in rows if r["exit_reason"] == "stop"]
    sp = [r for r in stops if r["pts"] > 0]
    print(f"\n{len(sp)} of {len(stops)} 'stop' exits are PROFITABLE "
          f"({len(sp)/max(len(stops),1):.0%}), worth {sum(r['pts'] for r in sp):+.2f} pts")

    # ---- true stats ---------------------------------------------------
    section("Scored by sign of P&L (the correct way)")
    for label, sub in (("ALL", rows),
                       ("BOL", [r for r in rows if r["signal"] == "BOL"]),
                       ("BOS", [r for r in rows if r["signal"] == "BOS"])):
        if not sub:
            continue
        w = [r for r in sub if r["pts"] > 0]
        l = [r for r in sub if r["pts"] <= 0]
        gw = sum(r["pts"] for r in w)
        gl = -sum(r["pts"] for r in l)
        exp = sum(r["pts"] for r in sub) / len(sub)
        pf = gw / gl if gl else float("inf")
        print(f"{label:>4}  n={len(sub):<4} win={len(w)/len(sub):>5.1%}  "
              f"avgW={gw/max(len(w),1):>7.2f}  avgL={-gl/max(len(l),1):>7.2f}  "
              f"exp={exp:>+6.2f}pts (${exp*POINT_VALUE:>+7.2f}/contract)  PF={pf:.2f}")

    # ---- equity curve / real drawdown ---------------------------------
    section("Chronological equity curve (actual order, 1 contract)")
    eq = peak = 0.0
    maxdd = 0.0
    streak = worst_streak = 0
    for r in rows:
        eq += r["pts"]
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
        streak = 0 if r["pts"] > 0 else streak + 1
        worst_streak = max(worst_streak, streak)
    print(f"total          {eq:>+10.2f} pts   (${eq*POINT_VALUE:,.2f} @1 contract)")
    print(f"max drawdown   {maxdd:>10.2f} pts   (${maxdd*POINT_VALUE:,.2f} @1 contract)")
    print(f"worst losing streak: {worst_streak} trades")

    # ---- clustering ----------------------------------------------------
    section("Loss clustering — are losses independent?")
    after_loss = [rows[i]["pts"] > 0 for i in range(1, n) if rows[i-1]["pts"] <= 0]
    after_win = [rows[i]["pts"] > 0 for i in range(1, n) if rows[i-1]["pts"] > 0]
    base = sum(1 for r in rows if r["pts"] > 0) / n
    print(f"baseline win rate              {base:>6.1%}")
    if after_loss:
        print(f"win rate after a LOSS          {sum(after_loss)/len(after_loss):>6.1%}  (n={len(after_loss)})")
    if after_win:
        print(f"win rate after a WIN           {sum(after_win)/len(after_win):>6.1%}  (n={len(after_win)})")
    byday = defaultdict(list)
    for r in rows:
        byday[r["entry_date"]].append(r["pts"])
    daily = [sum(v) for v in byday.values()]
    print(f"\ntrading days: {len(daily)}   avg {statistics.mean(daily):+.2f} pts/day")
    print(f"worst day {min(daily):+.2f} pts    best day {max(daily):+.2f} pts")
    print(f"losing days: {sum(1 for d in daily if d <= 0)}/{len(daily)} "
          f"({sum(1 for d in daily if d<=0)/len(daily):.0%})")

    # ---- day of week ---------------------------------------------------
    section("By weekday")
    for d in ("Mon", "Tue", "Wed", "Thu", "Fri"):
        sub = [r for r in rows if r["dow"] == d]
        if not sub:
            continue
        w = [r for r in sub if r["pts"] > 0]
        print(f"{d}  n={len(sub):<4} win={len(w)/len(sub):>5.1%}  "
              f"exp={sum(r['pts'] for r in sub)/len(sub):>+7.2f} pts")

    # ---- entry extension ------------------------------------------------
    section("Does entry extension past the range edge predict outcome?")
    for lo, hi in ((0, 25), (25, 50), (50, 100), (100, 200), (200, 10**9)):
        sub = [r for r in rows if lo <= r["ext"] < hi]
        if not sub:
            continue
        w = [r for r in sub if r["pts"] > 0]
        lbl = f"{lo}-{hi}%" if hi < 10**9 else f"{lo}%+"
        print(f"{lbl:>10}  n={len(sub):<4} win={len(w)/len(sub):>5.1%}  "
              f"exp={sum(r['pts'] for r in sub)/len(sub):>+7.2f} pts")

    # ---- same-bar ambiguity (the thing that broke the 15-min test) --------
    if "ambiguous" in rows[0]:
        section("Same-bar TP+SL ambiguity — is this test trustworthy?")
        amb = [r for r in rows if r["ambiguous"] == "1"]
        rate = len(amb) / n
        print(f"{len(amb)}/{n} ({rate:.1%}) of trades resolved on a bar that touched")
        print("BOTH the target and the stop. OHLC can't order those, so each was")
        print("scored as a stop — the conservative assumption.")
        if amb:
            amb_pts = sum(r["pts"] for r in amb)
            # Optimistic bracket: score every ambiguous trade as a target
            # instead. The truth is somewhere between the two.
            tp_guess = max((r["mfe_pts"] for r in rows if r["exit_reason"] == "target"),
                           default=0) if "mfe_pts" in rows[0] else 0
            tps = [r["pts"] for r in rows if r["exit_reason"] == "target"]
            tp_val = tps[0] if tps else 0
            optimistic = sum(r["pts"] for r in rows) - amb_pts + len(amb) * tp_val
            print(f"\nscored pessimistically (all stops): {sum(r['pts'] for r in rows):>+9.2f} pts total")
            print(f"if every ambiguous one had hit TP:  {optimistic:>+9.2f} pts total")
            print("the true result lies between these two bounds")
        if rate > 0.25:
            print("\n*** >25% AMBIGUOUS — RESULTS NOT TRUSTWORTHY. ***")
            print("The tie-break rule is driving the outcome, not the strategy.")
            print("Go to a finer chart timeframe or widen TP/SL.")
        elif rate > 0.10:
            print("\n! 10-25% ambiguous — treat the headline numbers as a lower bound.")
        else:
            print("\nOK: ambiguity is low enough that the result reflects the strategy.")

    # ---- next-open fill cost ---------------------------------------------
    if "fill_slip" in rows[0]:
        section("What did waiting for the next bar's open actually cost?")
        slips = [r["fill_slip"] for r in rows]
        worse = [s for s in slips if s > 0]
        print("positive = next-open fill was WORSE than the signal bar's close")
        print(f"mean slip   {statistics.mean(slips):>+8.3f} pts   "
              f"(${statistics.mean(slips)*POINT_VALUE:>+7.2f}/contract)")
        print(f"median slip {statistics.median(slips):>+8.3f} pts")
        print(f"worse than signal close: {len(worse)}/{len(slips)} ({len(worse)/len(slips):.0%})")
        print(f"total slip cost across all trades: {sum(slips):>+.2f} pts "
              f"(${sum(slips)*POINT_VALUE:,.2f}/contract)")
        print(f"\nexpectancy WITHOUT this slip would be "
              f"{(sum(r['pts'] for r in rows) + sum(slips))/n:>+.2f} pts/trade")

    # ---- MFE / MAE diagnostics -------------------------------------------
    if "mfe_pts" in rows[0]:
        section("MFE / MAE — are the TP and SL levels in the right place?")
        wins = [r for r in rows if r["pts"] > 0]
        losses = [r for r in rows if r["pts"] <= 0]
        if wins:
            print(f"winners  (n={len(wins)}): median MFE {statistics.median([r['mfe_pts'] for r in wins]):>6.2f} pts"
                  f"   median MAE {statistics.median([r['mae_pts'] for r in wins]):>6.2f} pts")
        if losses:
            print(f"losers   (n={len(losses)}): median MFE {statistics.median([r['mfe_pts'] for r in losses]):>6.2f} pts"
                  f"   median MAE {statistics.median([r['mae_pts'] for r in losses]):>6.2f} pts")
        tp_hit = [r for r in rows if r["exit_reason"] == "target"]
        if tp_hit:
            maes = sorted(r["mae_pts"] for r in tp_hit)
            print(f"\nOf the {len(tp_hit)} trades that reached target, how deep did they")
            print("first go AGAINST you? (how much room the stop actually needed)")
            for p in (50, 75, 90, 95):
                print(f"   {p}th pct MAE: {maes[min(int(len(maes)*p/100), len(maes)-1)]:>6.2f} pts")
        print("""
CAVEAT — this does NOT let you re-simulate other TP/SL levels. MFE and MAE
are recorded only up to each trade's ACTUAL exit, and they carry no ordering
information: a trade with MAE 12 and MFE 20 might have hit either one first.
Use these as directional hints (is the stop crowding eventual winners? is
the target cutting runners short?), then re-run the export at new levels to
actually measure it.""")

    # ---- bootstrap bust probability --------------------------------------
    section("BUST PROBABILITY — resampling YOUR actual trades")
    print("Fresh 250K eval: start 250,000, $6,500 trailing drawdown\n")
    pts = [r["pts"] for r in rows]
    days = list(byday.values())
    horizon = 250   # trades

    def run(sizes, sampler, tag):
        print(f"  {tag}")
        print(f"  {'size':>5} {'P(bust)':>9} {'median end':>13} {'worst 5%':>12}")
        for c in sizes:
            busts, ends = 0, []
            for i in range(N_PATHS):
                rng = random.Random(7000 + i)
                bal = hwm = 250_000.0
                floor = bal - 6_500.0
                dead = False
                for p in sampler(rng, horizon):
                    bal += p * POINT_VALUE * c
                    if bal > hwm:
                        hwm = bal
                        floor = hwm - 6_500.0
                    if bal <= floor:
                        dead = True
                        break
                busts += dead
                ends.append(bal)
            ends.sort()
            print(f"  {c:>5} {busts/N_PATHS:>8.1%} {ends[len(ends)//2]:>13,.0f} "
                  f"{ends[len(ends)//20]:>12,.0f}")

    def iid(rng, k):
        return [rng.choice(pts) for _ in range(k)]

    def block(rng, k):
        out = []
        while len(out) < k:
            out.extend(rng.choice(days))
        return out[:k]

    run(sizes, iid, "IID resample (assumes trades independent)")
    print()
    run(sizes, block, "BLOCK resample by whole days (preserves clustering)")

    print(f"""
NOTE: block resampling keeps each trading day's trades together, so if bad
days cluster losses, that shows up here and not in the IID column. Compare
the two — a large gap means independence was the wrong assumption and the
IID numbers understate risk.

Horizon is {horizon} trades (~{horizon/max(len(daily),1)*len(daily)/len(daily):.0f} per path);
at {len(rows)/len(daily):.1f} trades/day that's roughly {horizon/(len(rows)/len(daily)):.0f} trading days.
""")


if __name__ == "__main__":
    main()
