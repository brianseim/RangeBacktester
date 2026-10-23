"""
Parse a Pine Logs CSV export from EvoD_Trader_TradeLog.pine into a clean
trades CSV.

TradingView's log-panel export wraps everything in a Date,Message envelope,
and the trade rows arrive in quoted multi-line chunks (one per log.info call,
sized by the script's rowsPerChunk input). This unwraps that back into a
flat table.

Usage:
    python tools/parse_tradelog.py <pine-logs.csv> <out.csv>
"""

import csv
import sys

HEADER_SENTINEL = "idx,signal,dir,"


def parse(path):
    """Returns (config_line, header_fields, [row_dicts])."""
    config = None
    header = None
    rows = []

    with open(path, newline="", encoding="utf-8-sig") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 2:
                continue
            msg = rec[1].strip()
            if msg.startswith("TRADELOG_BEGIN"):
                config = msg
                continue
            if msg.startswith("TRADELOG_END"):
                continue
            if msg.startswith(HEADER_SENTINEL):
                header = msg.split(",")
                continue
            # Everything else is a chunk of newline-separated trade rows
            for line in msg.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if header and len(parts) == len(header):
                    rows.append(dict(zip(header, parts)))

    return config, header, rows


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    config, header, rows = parse(sys.argv[1])

    if not rows:
        print("No trade rows parsed — check the input file format.")
        sys.exit(1)

    with open(sys.argv[2], "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    print(f"config: {config}")
    print(f"parsed {len(rows)} trades -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
