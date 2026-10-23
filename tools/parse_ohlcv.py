"""
Parse Pine Logs CSV exports from EvoD_OHLCV_Export.pine into a clean OHLCV
file, and stitch multiple chunked exports together.

Because TradingView's bar cap limits one export to roughly two weeks of
1-minute data, building a longer dataset means several exports taken at
different Bar Replay positions. This merges them: rows are deduplicated on
timestamp and sorted, so overlapping windows are safe and you can just throw
every export file at it.

Usage:
    python tools/parse_ohlcv.py out.csv export1.csv [export2.csv ...]

Then check for gaps:
    python tools/parse_ohlcv.py --gaps out.csv
"""

import csv
import sys
from datetime import datetime, timedelta

HEADER_SENTINEL = "timestamp,open,high,low,close"


def parse_one(path):
    rows, meta = [], None
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 2:
                continue
            msg = rec[1].strip()
            if msg.startswith("OHLCV_BEGIN"):
                meta = msg
                if "COUNT ONLY" in msg:
                    print(f"  ! {path}: count-only export, no data rows")
                continue
            if msg.startswith("OHLCV_END") or msg.startswith(HEADER_SENTINEL):
                continue
            if msg.startswith("Set 'Count only'"):
                continue
            for line in msg.splitlines():
                line = line.strip()
                if not line or line.startswith("timestamp,"):
                    continue
                parts = line.split(",")
                if len(parts) >= 5:
                    rows.append(parts)
    return meta, rows


def find_gaps(path):
    """Report missing minutes, skipping normal weekend/maintenance breaks."""
    with open(path, newline="", encoding="utf-8") as fh:
        rdr = csv.reader(fh)
        next(rdr, None)
        stamps = [datetime.strptime(r[0], "%Y-%m-%d %H:%M") for r in rdr if r]
    if not stamps:
        print("no rows")
        return
    print(f"{len(stamps)} rows   {stamps[0]}  ..  {stamps[-1]}")
    gaps = []
    for a, b in zip(stamps, stamps[1:]):
        delta = (b - a).total_seconds() / 60
        if delta > 1:
            gaps.append((a, b, delta))
    # A daily maintenance halt (~60min) and the weekend break are expected.
    notable = [g for g in gaps if g[2] > 90 and g[2] < 60 * 24 * 2]
    print(f"{len(gaps)} discontinuities; {len(notable)} longer than 90min "
          f"and shorter than a weekend (these are the suspicious ones):")
    for a, b, d in notable[:25]:
        print(f"   {a} -> {b}   ({d:.0f} min missing)")
    if len(notable) > 25:
        print(f"   ... and {len(notable)-25} more")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--gaps":
        find_gaps(sys.argv[2])
        return

    out, sources = sys.argv[1], sys.argv[2:]
    seen, merged, ncols = {}, 0, 5
    for src in sources:
        meta, rows = parse_one(src)
        print(f"{src}: {len(rows)} rows")
        if meta:
            print(f"  {meta}")
        for r in rows:
            ncols = max(ncols, len(r))
            if r[0] not in seen:
                seen[r[0]] = r
            merged += 1

    ordered = [seen[k] for k in sorted(seen)]
    dupes = merged - len(ordered)

    header = ["timestamp", "open", "high", "low", "close"]
    if ncols >= 6:
        header.append("volume")

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(ordered)

    print(f"\n{len(ordered)} unique rows -> {out}"
          + (f"   ({dupes} duplicate timestamps dropped)" if dupes else ""))
    if ordered:
        print(f"span: {ordered[0][0]}  ..  {ordered[-1][0]}")
        print(f"\ncheck for holes with:  python tools/parse_ohlcv.py --gaps {out}")


if __name__ == "__main__":
    main()
