"""
Stage Databento gap files into the *_1min_master.parquet files.

Rebuilds every derived column using the rules reverse-engineered from the
existing masters (each verified at a 100% match against current data):

    timestamp_ct   UTC -> America/Chicago, DST-aware, then tz-naive
    session        CT date, +1 day when ct_hour >= 17   (CME 17:00->16:00 day,
                   labelled by its CLOSING calendar date). Stored as datetime.date.
    min_of_day_ct  ct.hour*60 + ct.minute
    ct_hour        ct.hour
    dow            CT weekday  (NOT session weekday -- confirmed: CT matches 100%,
                   session weekday only 69%. Sunday=6 appears, from the evening reopen.)
    roll_adjacent  last session of an expiring contract + first session of the next

Defaults to writing *_1min_master_NEW.parquet and leaving the originals alone.
These files took an unattended multi-day scrape to build; --in-place only after
a dry run looks right, and it takes a .bak first.

    python tools/stage_gap.py --dry-run     # report only, writes nothing
    python tools/stage_gap.py               # writes *_NEW.parquet
    python tools/stage_gap.py --in-place    # backs up, then overwrites masters
"""

import argparse
import glob
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

DATA = Path(r"E:\OneDrive\Documents\DayTrade\data")
GAP = DATA / "databento_gap"
CT = "America/Chicago"

# Columns each master carries, in order. MNQ alone tracks contracts.
BASE_COLS = ["timestamp_utc", "timestamp_ct", "session", "open", "high", "low",
             "close", "volume", "min_of_day_ct", "ct_hour", "dow", "roll_adjacent"]
MNQ_COLS = ["timestamp_utc", "timestamp_ct", "session", "contract", "open", "high",
            "low", "close", "volume", "min_of_day_ct", "ct_hour", "dow",
            "is_last_session_of_contract", "is_first_session_of_contract",
            "roll_adjacent"]

DTYPES = {"open": "float32", "high": "float32", "low": "float32", "close": "float32",
          "volume": "int32", "min_of_day_ct": "int64", "ct_hour": "int32",
          "dow": "int32", "roll_adjacent": "bool"}


def derive(df):
    """Add the CT/session/calendar columns from timestamp_utc."""
    utc = pd.to_datetime(df["timestamp_utc"], utc=True)
    ct = utc.dt.tz_convert(CT).dt.tz_localize(None)
    df["timestamp_utc"] = utc.dt.tz_localize(None).astype("datetime64[us]")
    df["timestamp_ct"] = ct.astype("datetime64[us]")
    # Session rolls at 17:00 CT and is named for the day it CLOSES on.
    df["session"] = (ct.dt.normalize()
                     + pd.to_timedelta((ct.dt.hour >= 17).astype(int), unit="D")).dt.date
    df["min_of_day_ct"] = ct.dt.hour * 60 + ct.dt.minute
    df["ct_hour"] = ct.dt.hour
    df["dow"] = ct.dt.dayofweek
    return df


def load_gap(root):
    """Read this symbol's contract files and stitch to a front-month series.

    Front month is chosen PER SESSION by total volume, which is how a real roll
    behaves: liquidity migrates to the next contract over a day or two, and the
    crossover session is the roll. Picking by expiry date instead would put the
    roll on a calendar date that liquidity didn't actually honour.
    """
    files = sorted(glob.glob(str(GAP / f"{root}*_ohlcv-1m.csv")))
    if not files:
        return None, f"no files matching {root}*_ohlcv-1m.csv in {GAP}"

    frames = []
    for f in files:
        raw = pd.read_csv(f)
        tcol = next((c for c in ("ts_event", "timestamp", "ts_recv") if c in raw.columns), None)
        if tcol is None:
            return None, f"{Path(f).name}: no recognisable timestamp column ({list(raw.columns)[:6]})"
        contract = Path(f).name.split("_")[0]
        frames.append(pd.DataFrame({
            "timestamp_utc": raw[tcol],
            "open": raw["open"], "high": raw["high"], "low": raw["low"],
            "close": raw["close"], "volume": raw["volume"], "contract": contract,
        }))

    df = derive(pd.concat(frames, ignore_index=True))

    # front month per session = the contract with the most volume that session
    vol = df.groupby(["session", "contract"])["volume"].sum().reset_index()
    front = vol.sort_values("volume").groupby("session").tail(1)[["session", "contract"]]
    front = front.rename(columns={"contract": "_front"})
    df = df.merge(front, on="session", how="left")
    df = df[df["contract"] == df["_front"]].drop(columns="_front")

    return df.sort_values("timestamp_utc").reset_index(drop=True), None


def contract_flags(df):
    """Mark the last session of each contract and the first of the next."""
    order = df.drop_duplicates("session")[["session", "contract"]].sort_values("session")
    last = order.groupby("contract")["session"].max()
    first = order.groupby("contract")["session"].min()
    # The final session present is only "last of contract" if a later contract
    # actually takes over; otherwise it is just where the data stops. This is the
    # exact bug currently baked into the MNQ master at 2026-08-14.
    final = order["session"].max()
    real_last = {s for c, s in last.items() if s != final}
    df["is_last_session_of_contract"] = df["session"].isin(real_last)
    df["is_first_session_of_contract"] = df["session"].isin(set(first) - {order["session"].min()})
    df["roll_adjacent"] = df["is_last_session_of_contract"] | df["is_first_session_of_contract"]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--in-place", action="store_true")
    args = ap.parse_args()

    if not GAP.exists():
        sys.exit(f"{GAP} not found -- run tools/pull_databento_gap.py first")

    for master_path in sorted(DATA.glob("*_1min_master.parquet")):
        root = master_path.name.split("_")[0]
        print(f"\n=== {root} ===")
        master = pd.read_parquet(master_path)
        is_mnq = "contract" in master.columns
        cols = MNQ_COLS if is_mnq else BASE_COLS

        new, err = load_gap(root)
        if err:
            print(f"  SKIP: {err}")
            continue

        cutoff = master["timestamp_utc"].max()
        new = new[new["timestamp_utc"] > cutoff]
        if new.empty:
            print(f"  nothing newer than {cutoff}")
            continue
        print(f"  master ends {cutoff}   adding {len(new):,} bars "
              f"-> {new['timestamp_utc'].max()}")

        combined = pd.concat([master, new], ignore_index=True)
        combined = (combined.drop_duplicates("timestamp_utc", keep="first")
                            .sort_values("timestamp_utc").reset_index(drop=True))

        if is_mnq:
            # Recompute roll flags across the WHOLE file, which also clears the
            # stale 2026-08-14 "last session of contract" left behind when the
            # original scrape was truncated there.
            was = set(master.loc[master["roll_adjacent"], "session"].unique())
            combined = contract_flags(combined)
            now = set(combined.loc[combined["roll_adjacent"], "session"].unique())
            for s in sorted(was - now):
                print(f"  cleared stale roll flag: {s}  (truncation artifact)")
            for s in sorted(now - was):
                print(f"  new roll session: {s}")
        else:
            combined["roll_adjacent"] = combined["roll_adjacent"].fillna(False)
            if "contract" in combined.columns:
                combined = combined.drop(columns="contract")

        for c, t in DTYPES.items():
            if c in combined.columns:
                combined[c] = combined[c].astype(t)
        combined = combined[cols]

        # --- validation -------------------------------------------------
        bps = combined.groupby("session").size()
        thin = bps[(bps < 1380) & (bps.index != bps.index.max())]
        dupes = combined["timestamp_utc"].duplicated().sum()
        print(f"  total {len(combined):,} bars   {combined['session'].min()} .. "
              f"{combined['session'].max()}")
        print(f"  duplicate timestamps: {dupes}   sessions under 1380 bars: {len(thin)}")
        if len(thin):
            for s, n in thin.tail(5).items():
                print(f"      {s}: {n} bars")
        tgt = combined[(combined["timestamp_ct"] >= "2025-10-01") &
                       (combined["timestamp_ct"] <= "2026-09-30 23:59")]
        print(f"  target window 2025-10-01..2026-09-30: {len(tgt):,} bars, "
              f"{tgt['session'].nunique()} sessions")

        if args.dry_run:
            print("  (dry run -- nothing written)")
            continue

        if args.in_place:
            bak = master_path.with_suffix(".parquet.bak")
            if not bak.exists():
                shutil.copy2(master_path, bak)
                print(f"  backed up -> {bak.name}")
            combined.to_parquet(master_path, index=False)
            print(f"  WROTE {master_path.name}")
        else:
            out = master_path.with_name(master_path.stem + "_NEW.parquet")
            combined.to_parquet(out, index=False)
            print(f"  wrote {out.name}")


if __name__ == "__main__":
    main()
