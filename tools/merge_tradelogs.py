"""
Merge several chunked Pine Logs trade-log exports into one clean CSV.

Why this exists: a 1-min chart only reaches back ~14.5 trading days under
TradingView's bar cap, so extending the dataset means several exports taken
at different Bar Replay positions. analyze_tradelog.py deliberately REFUSES
a file containing two TRADELOG_BEGIN markers (mixing runs with different
settings silently corrupts every number downstream). This tool is the
sanctioned way to combine them: it verifies the settings actually match
before merging, instead of assuming.

Config fields that may legitimately differ between chunks: n= and range=.
Everything else -- symbol, timeframe, shape, N, trigger block, TP, SL,
failstop, filter -- must be identical or the merge is refused.

Usage:
    python tools/merge_tradelogs.py merged.csv chunk1.csv chunk2.csv ...
    python tools/merge_tradelogs.py --coverage merged.csv
"""

import csv
import sys
from collections import Counter
from datetime import date, timedelta

HEADER_SENTINEL = "idx,signal,dir,"
# These vary per chunk by design; everything else must match.
VOLATILE_KEYS = {"n", "range"}


def parse_config(line):
    """TRADELOG_BEGIN k=v k=v ... -> dict. Values may contain spaces inside
    parentheses, e.g. shape=ORB(New York), so split on ' ' then re-join any
    fragment that doesn't look like a new key."""
    out, key = {}, None
    for tok in line.replace("TRADELOG_BEGIN", "", 1).strip().split(" "):
        if "=" in tok and not (key and out.get(key, "").count("(") > out.get(key, "").count(")")):
            key, _, val = tok.partition("=")
            out[key] = val
        elif key:
            out[key] += " " + tok
    return out


def parse_one(path):
    cfg, header, rows = None, None, []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 2:
                continue
            msg = rec[1].strip()
            if msg.startswith("TRADELOG_BEGIN"):
                if cfg is not None:
                    raise SystemExit(
                        f"ERROR: {path} contains more than one TRADELOG_BEGIN.\n"
                        "That single file already mixes two runs. Clear the Pine\n"
                        "Logs panel and re-export it on its own before merging."
                    )
                cfg = parse_config(msg)
                continue
            if msg.startswith("TRADELOG_END"):
                continue
            if msg.startswith(HEADER_SENTINEL):
                header = msg.split(",")
                continue
            for line in msg.splitlines():
                line = line.strip()
                if not line or line.startswith(HEADER_SENTINEL):
                    continue
                parts = line.split(",")
                if header and len(parts) == len(header):
                    rows.append(dict(zip(header, parts)))
    if cfg is None:
        raise SystemExit(f"ERROR: no TRADELOG_BEGIN found in {path} — is this a trade-log export?")
    return cfg, header, rows


def trade_key(r):
    """Identity of a trade across overlapping chunks. idx restarts at 1 in
    every export so it cannot be used; entry timestamp + direction can."""
    return (r["entry_date"], r["entry_time"], r["signal"], r["dir"])


def coverage(path):
    """Report which trading days are represented, and flag runs of
    consecutive weekdays with nothing in them.

    HEURISTIC, not proof: a weekday with no trades is perfectly legitimate
    (no signal fired). But three or more consecutive empty weekdays is more
    likely a missing export chunk than three quiet sessions, so those get
    flagged for you to check rather than silently trusted.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        days = sorted({r["entry_date"] for r in csv.DictReader(fh)})
    if not days:
        print("no rows")
        return
    first = date.fromisoformat(days[0])
    last = date.fromisoformat(days[-1])
    have = set(days)

    print(f"span: {days[0]} .. {days[-1]}   ({len(days)} days with trades)")

    missing, cur = [], first
    while cur <= last:
        if cur.weekday() < 5 and cur.isoformat() not in have:
            missing.append(cur)
        cur += timedelta(days=1)

    runs, run = [], []
    for d in missing:
        if run and (d - run[-1]).days <= 3:   # tolerate a weekend inside a run
            run.append(d)
        else:
            if run:
                runs.append(run)
            run = [d]
    if run:
        runs.append(run)

    gaps = [r for r in runs if len(r) >= 3]
    print(f"{len(missing)} weekdays with no trades; {len(gaps)} run(s) of 3+ consecutive")
    if gaps:
        print("\nsuspicious gaps — likely a missing export chunk:")
        for r in gaps:
            print(f"   {r[0]} .. {r[-1]}   ({len(r)} weekdays)")
    else:
        print("no multi-day holes — coverage looks continuous")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--coverage":
        coverage(sys.argv[2])
        return

    out, sources = sys.argv[1], sys.argv[2:]
    base_cfg, base_src, header = None, None, None
    seen, total = {}, 0

    for src in sources:
        cfg, hdr, rows = parse_one(src)
        rng = cfg.get("range", "?")
        print(f"{src}: {len(rows)} trades   range={rng}")

        if base_cfg is None:
            base_cfg, base_src, header = cfg, src, hdr
        else:
            diffs = [
                f"    {k}: {base_src} has '{base_cfg.get(k)}', {src} has '{cfg.get(k)}'"
                for k in sorted(set(base_cfg) | set(cfg))
                if k not in VOLATILE_KEYS and base_cfg.get(k) != cfg.get(k)
            ]
            if diffs:
                raise SystemExit(
                    "ERROR: these exports were produced with different settings.\n"
                    "Merging them would silently mix two strategies:\n"
                    + "\n".join(diffs)
                )
            if hdr != header:
                raise SystemExit(
                    f"ERROR: column layout differs between {base_src} and {src}.\n"
                    "They came from different versions of the exporter."
                )

        for r in rows:
            total += 1
            seen.setdefault(trade_key(r), r)

    ordered = sorted(seen.values(), key=lambda r: (r["entry_date"], r["entry_time"]))
    for i, r in enumerate(ordered, 1):
        r["idx"] = str(i)

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(ordered)

    dupes = total - len(ordered)
    print(f"\n{len(ordered)} unique trades -> {out}"
          + (f"   ({dupes} duplicates from overlapping chunks dropped)" if dupes else ""))
    cfg_str = " ".join(f"{k}={v}" for k, v in base_cfg.items() if k not in VOLATILE_KEYS)
    print(f"config: {cfg_str}")
    print()
    coverage(out)
    print(f"\nanalyze with:  python tools/analyze_tradelog.py {out}")


if __name__ == "__main__":
    main()
