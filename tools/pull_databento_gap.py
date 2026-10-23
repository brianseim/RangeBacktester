"""
Pull the 1-minute OHLCV gap from Databento for the DayTrade masters.

RUN THIS ON YOUR WINDOWS MACHINE (same pattern as mt5_pull_xauusd.py).
    pip install databento pandas pyarrow
    set DATABENTO_API_KEY=db-...
    python pull_databento_gap.py --probe      <- prices the query, downloads nothing
    python pull_databento_gap.py              <- actually pulls

Why Databento and not another TradingView extraction: your own ORDERFLOW_SCOPE.md
already settled this -- "a year of 1-minute OHLCV costs $1.28 per symbol... the four
datasets we extracted from TradingView would have cost $5.11 and arrived in minutes,
already clean, already timestamped, with no roll ambiguity and no replay-buffer
ceiling." This gap is 47 days x 4 symbols, so roughly $0.70 at that rate. Scraping it
would be ~12 replay chunks per symbol.

ALWAYS RUN --probe FIRST. get_cost() prices the exact query before a byte is
downloaded. That is the habit your own footnote asks for: "check the price of the
data before building a pipeline to scrape it."

PER-CONTRACT, NOT CONTINUOUS: the MNQ master carries a real `contract` column
(MNQU2025, MNQZ2025, ...) and roll flags derived from it. A continuous series
(MNQ.c.0) would collapse that away, so we pull the individual contract months that
are live in the window and let stage_gap.py stitch them on volume crossover, which
is how the existing file was built.
"""

import argparse
import os
import sys
from pathlib import Path

OUT = Path(r"E:\OneDrive\Documents\DayTrade\data\databento_gap")

DATASET = "GLBX.MDP3"      # CME Globex MDP 3.0
SCHEMA = "ohlcv-1m"

# Window: first missing bar is 2026-08-14 21:00 UTC (= 16:00 CT, start of the
# 2026-08-17 session). End is exclusive, so 2026-10-01 covers through Sep 30.
START = "2026-08-14T21:00:00Z"
END = "2026-10-01T00:00:00Z"

# Contract months live in the window. The Sept quarterly roll (U->Z) falls inside
# it, so both legs are needed for every symbol; stage_gap.py picks the front month
# per session by volume.
#
# Databento uses the exchange's own symbol. CME single-digit-year convention makes
# Sept 2026 = U6 and Dec 2026 = Z6. If a symbol comes back empty, run --probe and
# check the resolved list it prints -- do not assume, the year-digit convention is
# the single most likely thing to be wrong here.
SYMBOLS = {
    "MNQ": ["MNQU6", "MNQZ6"],
    "MES": ["MESU6", "MESZ6"],
    "M2K": ["M2KU6", "M2KZ6"],
    "MGC": ["MGCZ6"],   # gold is a different cycle -- see note below
}
# MGC (micro gold) trades Feb/Apr/Jun/Aug/Oct/Dec, not the equity-index quarterly
# cycle, so Aug->Oct->Dec apply instead of U->Z. MGCV6 (Oct) may also be needed.
# --probe will show which of these actually carry volume in the window.
MGC_CANDIDATES = ["MGCQ6", "MGCV6", "MGCZ6"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="price the query and list resolvable symbols; download nothing")
    args = ap.parse_args()

    try:
        import databento as db
    except ImportError:
        sys.exit("pip install databento")

    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        sys.exit("set DATABENTO_API_KEY=db-...   (https://databento.com/portal/keys)")

    client = db.Historical(key)
    OUT.mkdir(parents=True, exist_ok=True)

    syms = dict(SYMBOLS)
    if args.probe:
        syms["MGC"] = MGC_CANDIDATES

    total = 0.0
    for root, contracts in syms.items():
        for sym in contracts:
            try:
                cost = client.metadata.get_cost(
                    dataset=DATASET, symbols=[sym], schema=SCHEMA,
                    start=START, end=END,
                )
                size = client.metadata.get_billable_size(
                    dataset=DATASET, symbols=[sym], schema=SCHEMA,
                    start=START, end=END,
                )
                total += cost
                print(f"  {sym:<8} ${cost:>7.4f}   {size/1_000_000:>7.2f} MB")
            except Exception as e:
                print(f"  {sym:<8} UNAVAILABLE -> {e}")

    print(f"\n  {'TOTAL':<8} ${total:>7.4f}")

    if args.probe:
        print("\nProbe only -- nothing downloaded. Check that every symbol above resolved")
        print("and that the cost is what you expect, then re-run without --probe.")
        return

    print()
    for root, contracts in SYMBOLS.items():
        for sym in contracts:
            dest = OUT / f"{sym}_{SCHEMA}.csv"
            if dest.exists():
                print(f"  {sym:<8} already present, skipping ({dest.name})")
                continue
            print(f"  {sym:<8} downloading...", end=" ", flush=True)
            try:
                data = client.timeseries.get_range(
                    dataset=DATASET, symbols=[sym], schema=SCHEMA,
                    start=START, end=END,
                )
                df = data.to_df()
                if df.empty:
                    print("EMPTY -- wrong symbol code? run --probe")
                    continue
                df.to_csv(dest)
                print(f"{len(df):,} bars -> {dest.name}")
            except Exception as e:
                print(f"FAILED -> {e}")

    print(f"\nDone. Files in {OUT}")
    print("Next:  python tools/stage_gap.py --dry-run")


if __name__ == "__main__":
    main()
